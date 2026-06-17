"""etap_212 — ПРОСТОЙ ЧЕСТНЫЙ live-nowcaster направления дня.

Установлено (etap_211): направление ВПЕРЁД = монетка (AUC 0.51); ML-связка
bias+CatBoost+Bulkowski НЕ бьёт наивное «цена уже идёт туда». Поэтому модуль —
не прогноз, а КАЛИБРОВАННОЕ СОСТОЯНИЕ дня, обновляемое каждый час, со стабилизацией:

  P(день закроется зелёным | ход с открытия к часу k)  ← per-hour логистика (калибрована)
  → EMA-сглаживание                                    ← не дёргается
  → мёртвая зона 0.43–0.57                              ← меняет мнение только при перевесе

Честность: walk-forward (fit<2023, test 2023+), reliability-калибровка, статистика
стабильности (сколько раз в день меняет мнение). Никакого lookahead: на час k —
только бары 0..k текущего дня.

Live-API: nowcast_day(bars_1h) → поток (k, p, p_smooth, call) — то, что бот зовёт
на каждом закрытом 1h-баре.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_212_live_nowcaster.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from data_manager import load_df
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

OUT = HERE / "output"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")
HI, LO, ALPHA = 0.57, 0.43, 0.4   # мёртвая зона + сглаживание


def build_rows(h1):
    h1d = h1.index.normalize()
    rows = []
    for day, bars in h1.groupby(h1d):
        if len(bars) < 4: continue
        o = bars["open"].iloc[0]; c = bars["close"].values
        hi = np.maximum.accumulate(bars["high"].values)
        lo = np.minimum.accumulate(bars["low"].values)
        green = int(c[-1] > o)
        for k in range(len(bars)):
            rng = hi[k] - lo[k]
            rows.append(dict(day=day, k=k, green=green,
                             ret_k=c[k]/o - 1,
                             pos_rng=(c[k]-lo[k])/rng if rng > 0 else 0.5))
    return pd.DataFrame(rows)


def fit_per_hour(tr, kmax=24):
    models = {}
    for k in range(kmax):
        s = tr[tr["k"] == k]
        if len(s) < 50 or s["green"].nunique() < 2: continue
        m = LogisticRegression(max_iter=200, C=1.0)
        m.fit(s[["ret_k", "pos_rng"]], s["green"])
        models[k] = m
    return models


def predict(models, df):
    p = np.full(len(df), 0.5)
    for k, m in models.items():
        idx = df["k"].values == k
        if idx.any():
            p[idx] = m.predict_proba(df.loc[idx, ["ret_k", "pos_rng"]])[:, 1]
    return p


def stream(p_seq):
    """EMA-сглаживание + мёртвая зона → поток call'ов, число смен мнения."""
    sm = None; call = "HOLD"; flips = 0; out = []
    for p in p_seq:
        sm = p if sm is None else ALPHA*p + (1-ALPHA)*sm
        new = "LONG" if sm > HI else ("SHORT" if sm < LO else call)
        if new != call and call != "HOLD": flips += 1
        call = new
        out.append((round(float(p), 3), round(float(sm), 3), call))
    return out, flips


def nowcast_day(bars_1h, models):
    """LIVE-API: по 1h-барам дня (накопительно) → поток решений. Бот зовёт это
    после каждой закрытой 1h-свечи. bars_1h — df с open/high/low/close за текущий день."""
    o = bars_1h["open"].iloc[0]; c = bars_1h["close"].values
    hi = np.maximum.accumulate(bars_1h["high"].values); lo = np.minimum.accumulate(bars_1h["low"].values)
    ps = []
    for k in range(len(bars_1h)):
        m = models.get(min(k, max(models)))
        rng = hi[k]-lo[k]
        x = [[c[k]/o-1, (c[k]-lo[k])/rng if rng > 0 else 0.5]]
        ps.append(float(m.predict_proba(x)[0, 1]))
    decisions, flips = stream(ps)
    return [(k, *decisions[k]) for k in range(len(ps))], flips


def main():
    print("Загрузка BTC 1h...")
    h1 = load_df("BTCUSDT", "1h")
    if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
    h1 = h1.sort_index()
    R = build_rows(h1)
    tr, te = R[R["day"] < CUTOFF], R[R["day"] >= CUTOFF]
    models = fit_per_hour(tr)
    te = te.assign(p=predict(models, te))

    print("="*64)
    print(f"LIVE-NOWCASTER (calibrated state) — test 2023+ ({te['day'].nunique()} дней)")
    print("="*64)
    print(f"  база зелёных: {te['green'].mean():.3f} | AUC {roc_auc_score(te['green'], te['p']):.3f} | Brier {brier_score_loss(te['green'], te['p']):.3f}")

    print("\n■ КАЛИБРОВКА (test): прогноз-бакет → факт зелёных")
    for b, g in te.assign(bucket=pd.cut(te["p"], [0, .3, .43, .57, .7, 1.0])).groupby("bucket", observed=True):
        print(f"   p∈{str(b):<12} n={len(g):>5} mean_p={g['p'].mean():.2f} факт={g['green'].mean():.2f}")

    # стабильность по дням
    flips_all, first_commit, correct_final = [], [], []
    by_day = te.sort_values("k").groupby("day")
    for day, g in by_day:
        decisions, flips = stream(g["p"].values)
        flips_all.append(flips)
        calls = [c for _, _, c in decisions]
        commit = next((i for i, c in enumerate(calls) if c != "HOLD"), None)
        first_commit.append(commit if commit is not None else len(calls))
        fin = calls[-1]; gr = g["green"].iloc[0]
        if fin in ("LONG", "SHORT"):
            correct_final.append(int((fin == "LONG") == (gr == 1)))
    fa = np.array(flips_all)
    print("\n■ СТАБИЛЬНОСТЬ (анти-дёрганье)")
    print(f"   смен мнения в день: среднее {fa.mean():.2f} | медиана {np.median(fa):.0f} | ≤1 смены: {(fa<=1).mean()*100:.0f}% дней | 0 смен: {(fa==0).mean()*100:.0f}%")
    print(f"   первый коммит (час): медиана {np.median(first_commit):.0f}")
    print(f"   финальный call дня совпал с цветом дня: {np.mean(correct_final)*100:.0f}% (поздним вечером ≈тавтология — ОК)")

    # примеры: зелёный и красный день
    print("\n■ ПРИМЕРЫ (live-поток, печать чётных часов)")
    for want, lbl in [(1, "ЗЕЛЁНЫЙ"), (0, "КРАСНЫЙ")]:
        cand = [d for d, g in by_day if g["green"].iloc[0] == want and len(g) >= 20]
        day = cand[len(cand)//2]
        g = by_day.get_group(day).sort_values("k")
        decisions, flips = stream(g["p"].values)
        print(f"\n   {pd.Timestamp(day).date()} (факт {lbl}, смен мнения: {flips})")
        print(f"   {'k':>3} {'p':>5} {'p_sm':>5} {'call':>6}")
        for k in range(len(decisions)):
            if k % 3 == 0 or k == len(decisions)-1:
                p, sm, c = decisions[k]
                print(f"   {k:>3} {p:>5.2f} {sm:>5.2f} {c:>6}")

    OUT.mkdir(exist_ok=True)
    te.to_csv(OUT / "etap_212_nowcaster_test.csv", index=False)
    print(f"\nSaved: {OUT / 'etap_212_nowcaster_test.csv'}")
    print("\nLIVE: бот на каждом закрытом 1h-баре зовёт nowcast_day(bars_сегодня, models)")
    print("      → (k, p, p_smooth, call). call ∈ {LONG, SHORT, HOLD}, меняется редко и по делу.")


if __name__ == "__main__":
    main()
