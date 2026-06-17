"""etap_211 — ЖИВОЙ внутридневной nowcaster направления дня (честный v1).

Идея (по ТЗ пользователя): направление дня ВПЕРЁД = монетка (AUC 0.50, доказано).
Но если дозаписывать часовики ТЕКУЩЕГО дня, вероятность «день закроется зелёным»
обновляется и становится осмысленной по мере раскрытия дня — модель «живая»,
может переобуться, но через сглаживание не дёргается каждый час.

Вход на час k дня d:
  КОНТЕКСТ (as-of конец дня d-1): bias-score (etap_201) + CatBoost P_big +
    EMA-тренд + value-migration + premium/discount + Bulkowski (side, bars_since) + DOW
  ВНУТРИДЕНЬ (часы 0..k дня d): ret since open, позиция в дневном range, up/down
    excursion, моментум 3h, доля объёма, k
Цель: close_d > open_d (день зелёный).

Честность: walk-forward (train<2023, test 2023-2026), калибровка, shuffle-тест,
кривая AUC vs час дня. + демо гистерезиса (сглаживание + мёртвая зона).

Запуск: venv/Scripts/python.exe research/daily_engine/etap_211_direction_nowcaster.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_201_daily_analyzer as A
sys.path.insert(0, str(HERE.parent.parent))
from data_manager import load_df

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, brier_score_loss

ROOT = HERE.parent.parent
SIG_GEOM = ROOT / "research/elements_study/output/etap_172_all_signals_geom.csv"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")


def build_context(d):
    """Контекст per day (as-of конец d-1). d = дневной df анализатора."""
    o, h, l, c, v = (d[x].values for x in ["open", "high", "low", "close", "volume"])
    e20 = A.ema(d["close"], 20).values; e50 = A.ema(d["close"], 50).values
    rows = []
    for di in range(65, len(d)):
        pc = c[di-1]
        w = slice(di-60, di)               # окно до текущего дня (как-of d-1)
        vpoc, vah, val = A.vpoc_va(h[w], l[w], v[w])
        vpoc_p, _, _ = A.vpoc_va(h[di-65:di-5], l[di-65:di-5], v[di-65:di-5])
        migr = 1 if vpoc > vpoc_p*1.002 else (-1 if vpoc < vpoc_p*0.998 else 0)
        pos_va = (pc - val)/(vah - val) if vah > val else 0.5
        score = (1 if pc > e20[di-1] else -1) + (1 if e20[di-1] > e50[di-1] else -1) + migr \
                + (-1 if pos_va > 0.8 else (1 if pos_va < 0.2 else 0))
        rows.append(dict(day=d.index[di], dow=d.index[di].dayofweek,
                         ctx_score=score, ctx_migr=migr, ctx_posva=pos_va,
                         ctx_trend=int(pc > e20[di-1]) + int(e20[di-1] > e50[di-1]),
                         ctx_ret5=pc/c[di-6]-1))
    return pd.DataFrame(rows).set_index("day")


def main():
    print("Загрузка данных...")
    d = A.daily_from_flow("BTCUSDT")
    h1 = load_df("BTCUSDT", "1h")
    if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
    h1 = h1.sort_index()

    ctx = build_context(d)

    # CatBoost P_big (обучен <2023), предсказан as-of d-1
    print(f"CatBoost big_day <{CUTOFF.date()}...")
    reg, clf, feat_cols, cat_idx, calib = A.train_models(CUTOFF)
    fb = A.build_features(d).shift(1)
    fb["gap"] = (d["open"] - d["close"].shift(1)) / A.atr(d, 14)
    fb["asset"] = "BTCUSDT"
    fb = fb.reindex(columns=feat_cols)
    valid = fb.dropna()
    ctx["p_big"] = pd.Series(clf.predict_proba(valid)[:, 1], index=valid.index).reindex(ctx.index)

    # Bulkowski контекст: последний сигнал (side) + дни с момента сигнала
    bs = pd.read_csv(SIG_GEOM)
    bs["day"] = pd.to_datetime(bs["time"], utc=True).dt.normalize()
    bs["side_n"] = np.where(bs["side"] == "long", 1, -1)
    last = bs.groupby("day")["side_n"].last()
    bulk_side = last.reindex(d.index).ffill(limit=10).fillna(0)
    present = last.reindex(d.index).notna().values
    bars_since = np.full(len(d.index), 30); cnt = 30
    for i, pv in enumerate(present):
        cnt = 0 if pv else min(cnt + 1, 30)
        bars_since[i] = cnt
    # СДВИГ на 1 день: для прогноза дня d используем только сигналы ≤ d-1 (без lookahead)
    ctx["bulk_side"] = bulk_side.shift(1).reindex(ctx.index)
    ctx["bulk_bars_since"] = pd.Series(bars_since, index=d.index).shift(1).reindex(ctx.index)

    # дневной средний объём (для нормировки внутридневного)
    davg = d["volume"].rolling(30).mean().shift(1)

    # --- строим строки (day,hour) ---
    print("Сборка внутридневных строк...")
    h1d = h1.index.normalize()
    rows = []
    o_d = d["open"]; c_d = d["close"]
    for day in ctx.index:
        bars = h1[h1d == day]
        if len(bars) < 4: continue
        opn = bars["open"].iloc[0]
        cl = bars["close"].values; hi = bars["high"].values; lo = bars["low"].values; vol = bars["volume"].values
        green = int(c_d.get(day, np.nan) > o_d.get(day, np.nan))
        if not np.isfinite(c_d.get(day, np.nan)): continue
        cum_h = np.maximum.accumulate(hi); cum_l = np.minimum.accumulate(lo); cum_v = np.cumsum(vol)
        dv = davg.get(day, np.nan)
        ctxr = ctx.loc[day]
        rets = np.concatenate([[0], np.diff(cl)/cl[:-1]])
        for k in range(len(bars)):
            hh, ll = cum_h[k], cum_l[k]
            mom3 = rets[max(0, k-2):k+1].sum()
            rows.append(dict(
                day=day, year=day.year, k=k, green=green,
                # контекст
                dow=ctxr["dow"], ctx_score=ctxr["ctx_score"], ctx_migr=ctxr["ctx_migr"],
                ctx_posva=ctxr["ctx_posva"], ctx_trend=ctxr["ctx_trend"], ctx_ret5=ctxr["ctx_ret5"],
                p_big=ctxr["p_big"], bulk_side=ctxr["bulk_side"], bulk_bars=ctxr["bulk_bars_since"],
                # внутридень 0..k
                ret_k=cl[k]/opn-1, up_exc=hh/opn-1, dn_exc=opn/ll-1,
                pos_rng=(cl[k]-ll)/(hh-ll) if hh > ll else 0.5,
                mom3=mom3, vol_frac=(cum_v[k]/dv) if dv and np.isfinite(dv) else np.nan,
            ))
    R = pd.DataFrame(rows).dropna(subset=["p_big"])
    print(f"  строк: {len(R)}  дней: {R['day'].nunique()}")

    feats = ["k", "dow", "ctx_score", "ctx_migr", "ctx_posva", "ctx_trend", "ctx_ret5",
             "p_big", "bulk_side", "bulk_bars", "ret_k", "up_exc", "dn_exc", "pos_rng", "mom3", "vol_frac"]
    tr = R[R["day"] < CUTOFF]; te = R[R["day"] >= CUTOFF]
    Xtr, ytr = tr[feats], tr["green"]; Xte, yte = te[feats], te["green"]

    clf2 = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_depth=4,
                                          l2_regularization=1.0, random_state=42)
    clf2.fit(Xtr, ytr)
    p = clf2.predict_proba(Xte)[:, 1]
    te = te.assign(p=p)

    print("\n" + "="*70)
    print(f"NOWCASTER направления — OOS 2023-2026 (test {len(te)} строк, {te['day'].nunique()} дней)")
    print("="*70)
    print(f"  Базовая доля зелёных дней (test): {yte.mean():.3f}")
    print(f"  Overall AUC: {roc_auc_score(yte, p):.3f} | Brier: {brier_score_loss(yte, p):.3f}")

    print("\n■ КРИВАЯ СКИЛЛА vs ЧАС ДНЯ (k):  где появляется сигнал")
    print(f"  {'час k':>6} {'n':>5} {'AUC':>6} {'mean_p':>7} {'real_green':>10}")
    for k in [0, 1, 2, 3, 4, 6, 8, 10, 12, 16, 20]:
        s = te[te["k"] == k]
        if len(s) < 20: continue
        try: auc = roc_auc_score(s["green"], s["p"])
        except Exception: auc = float("nan")
        print(f"  {k:>6} {len(s):>5} {auc:>6.3f} {s['p'].mean():>7.3f} {s['green'].mean():>10.3f}")

    print("\n■ КАЛИБРОВКА (test, все часы): pred-бакет → факт green")
    te2 = te.assign(b=pd.cut(te["p"], [0, .35, .45, .55, .65, 1.0]))
    for b, g in te2.groupby("b", observed=True):
        print(f"  p∈{str(b):<14} n={len(g):>5} mean_p={g['p'].mean():.2f} real_green={g['green'].mean():.2f}")

    # --- ЧЕСТНЫЕ БЕЙЗЛАЙНЫ ---
    ctx_feats = ["dow", "ctx_score", "ctx_migr", "ctx_posva", "ctx_trend", "ctx_ret5",
                 "p_big", "bulk_side", "bulk_bars"]
    tr0 = tr[tr["k"] == 0]; te0 = te[te["k"] == 0]   # один ряд на день, без внутридня
    cclf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_depth=4, random_state=42)
    cclf.fit(tr0[ctx_feats], tr0["green"])
    auc_ctx = roc_auc_score(te0["green"], cclf.predict_proba(te0[ctx_feats])[:, 1])
    print(f"\n■ ЧЕСТНЫЙ ПРОГНОЗ ВПЕРЁД (контекст без внутридня, 1 ряд/день):")
    print(f"   цель=ДЕНЬ-ЦВЕТ (close>open):       AUC={auc_ctx:.3f}")
    # сверка: цель=close-to-close (цель проекта, где была стена 0.50)
    cc = (d["close"] > d["close"].shift(1)).astype(int)
    tr0cc = cc.reindex(tr0["day"]).values; te0cc = cc.reindex(te0["day"]).values
    m = np.isfinite(tr0cc); m2 = np.isfinite(te0cc)
    cclf2 = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_depth=4, random_state=42)
    cclf2.fit(tr0[ctx_feats][m], tr0cc[m].astype(int))
    auc_cc = roc_auc_score(te0cc[m2].astype(int), cclf2.predict_proba(te0[ctx_feats][m2])[:, 1])
    print(f"   цель=CLOSE-to-CLOSE (стена проекта): AUC={auc_cc:.3f}")
    print("   → если close-to-close ≈0.50, то 0.6+ на день-цвете — это gap/drift-эффект, не «пробитие стены»")

    print("\n■ БЬЁТ ЛИ ML наивный baseline «цена уже идёт туда» (sign ret_k)?")
    print(f"  {'час k':>6} {'AUC_наив(ret_k)':>16} {'AUC_ML':>8} {'lift':>6}")
    for k in [0, 1, 2, 3, 4, 6, 8, 12]:
        s = te[te["k"] == k]
        if len(s) < 20: continue
        an = roc_auc_score(s["green"], s["ret_k"])
        am = roc_auc_score(s["green"], s["p"])
        print(f"  {k:>6} {an:>16.3f} {am:>8.3f} {am-an:>+6.3f}")

    # shuffle-тест
    rng = np.random.default_rng(0)
    clf_s = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_depth=4, random_state=1)
    clf_s.fit(Xtr, rng.permutation(ytr.values))
    auc_sh = roc_auc_score(yte, clf_s.predict_proba(Xte)[:, 1])
    print(f"\n■ SHUFFLE-тест (перемешанная цель): AUC={auc_sh:.3f}  (должно ≈0.50)")

    # вклад контекста vs внутридня на РАННИХ часах (k<=2)
    early = te[te["k"] <= 2]
    print(f"\n■ РАННИЕ часы k≤2 (контекст важнее внутридня): AUC={roc_auc_score(early['green'], early['p']):.3f} "
          f"(база {early['green'].mean():.2f}) — это «прогноз вперёд», ожидаем ≈монетку")

    # --- гистерезис демо: P(up) по часам + сглаживание + мёртвая зона ---
    print("\n" + "="*70)
    print("■ ГИСТЕРЕЗИС (живой, без дёрганья) — пример дня")
    print("="*70)
    sample_day = te[te["k"] >= 12]["day"].dropna().iloc[len(te[te['k']>=12])//2]
    sd = te[te["day"] == sample_day].sort_values("k")
    alpha = 0.4; sm = None; call = "HOLD"; flips = 0; line = []
    for _, rw in sd.iterrows():
        sm = rw["p"] if sm is None else alpha*rw["p"] + (1-alpha)*sm
        new = "LONG" if sm > 0.57 else ("SHORT" if sm < 0.43 else call)
        if new != call and call != "HOLD": flips += 1
        call = new
        line.append((int(rw["k"]), rw["p"], sm, call))
    print(f"  день {pd.Timestamp(sample_day).date()} (факт {'ЗЕЛЁНЫЙ' if sd['green'].iloc[0]==1 else 'КРАСНЫЙ'}):")
    print(f"  {'k':>3} {'p_raw':>6} {'p_smooth':>9} {'call':>6}")
    for k, pr, smv, cl_ in line:
        if k % 2 == 0 or k >= 20:
            print(f"  {k:>3} {pr:>6.2f} {smv:>9.2f} {cl_:>6}")
    print(f"  смен мнения за день: {flips}  (сглаживание α={alpha}, мёртвая зона 0.43-0.57)")

    te.to_csv(A.OUT / "etap_211_nowcaster_test.csv", index=False)
    print(f"\nSaved: {A.OUT / 'etap_211_nowcaster_test.csv'}")


if __name__ == "__main__":
    main()
