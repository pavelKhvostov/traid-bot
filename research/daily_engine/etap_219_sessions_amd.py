"""etap_219 — #4 Сессии / AMD power-of-3 (ICT): Азия→Лондон-свип(Judas)→NY.

Гипотеза юзера («3 янв поглощает 2-е»): настоящий ход = Лондон/NY забирает азиатскую
ликвидность и разворачивается. Power-of-3: Accumulation(Азия) → Manipulation(свип) →
Distribution(тренд). Проверяем условную P(green) по Judas-свипу + добавляет ли к IB-слою.

Сессии (UTC): Азия 00–06, Лондон 07–11, NY 12–19.
  bullish_judas: Лондон снял азиатский LOW и закрылся обратно ВЫШЕ него → день green?
  bearish_judas: снял HIGH и вернулся ниже → день red?

Запуск: venv/Scripts/python.exe research/daily_engine/etap_219_sessions_amd.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

DATA = HERE.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")
ASIA, LON, NY = range(0, 7), range(7, 12), range(12, 20)


def build(df):
    dd = df.index.normalize(); rows = []
    for day, g in df.groupby(dd):
        if len(g) < 13: continue
        hh = g.index.hour.values
        o = g["open"].iloc[0]; c = g["close"].values; H = g["high"].values; L = g["low"].values
        a = np.isin(hh, list(ASIA)); lon = np.isin(hh, list(LON))
        if a.sum() < 3 or lon.sum() < 2: continue
        a_hi, a_lo = H[a].max(), L[a].min()
        lon_hi, lon_lo = H[lon].max(), L[lon].min()
        lon_close = c[lon][-1]
        swept_lo = int(lon_lo < a_lo); swept_hi = int(lon_hi > a_hi)
        # judas: снял сторону, но закрыл Лондон ОБРАТНО внутрь/за противоположную
        bull_judas = int(swept_lo and lon_close > a_lo)
        bear_judas = int(swept_hi and lon_close < a_hi)
        green = int(c[-1] > o)
        rows.append(dict(day=day, green=green, swept_lo=swept_lo, swept_hi=swept_hi,
                         bull_judas=bull_judas, bear_judas=bear_judas,
                         lon_ret=lon_close/o-1, asia_range=(a_hi-a_lo)/o,
                         lon_pos=(lon_close-a_lo)/max(a_hi-a_lo, 1e-9)))
    return pd.DataFrame(rows)


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    R = build(df).fillna(0.0)
    te = R[R.day >= CUTOFF]
    print("="*66); print(f"#4 СЕССИИ / AMD (ICT) — конец Лондона → день, OOS 2023+ ({len(te)})"); print("="*66)

    print("\n■ JUDAS-свип Лондоном азиатской ликвидности → P(green) дня")
    cases = [
        ("bull judas (снял LOW, вернулся выше)", te.bull_judas == 1),
        ("bear judas (снял HIGH, вернулся ниже)", te.bear_judas == 1),
        ("снял LOW и НЕ вернулся (продолж. вниз)", (te.swept_lo == 1) & (te.bull_judas == 0)),
        ("снял HIGH и НЕ вернулся (продолж. вверх)", (te.swept_hi == 1) & (te.bear_judas == 0)),
        ("не трогал азиатский диапазон (inside)", (te.swept_lo == 0) & (te.swept_hi == 0)),
    ]
    for lab, m in cases:
        g = te[m]
        if len(g): print(f"   {lab:<42} n={len(g):>4} P(green)={g.green.mean():.2f}")

    print("\n■ Лучше ли Judas, чем просто 'Лондон закрылся выше/ниже open'?")
    base_up = te[te.lon_ret > 0]; base_dn = te[te.lon_ret < 0]
    print(f"   Лондон зелёный (lon_ret>0): n={len(base_up):>4} P(green)={base_up.green.mean():.2f}")
    print(f"   Лондон красный (lon_ret<0): n={len(base_dn):>4} P(green)={base_dn.green.mean():.2f}")

    print("\n■ AUC: session-фичи vs день; и lift над 'lon_ret' (наивный)")
    feats = ["swept_lo", "swept_hi", "bull_judas", "bear_judas", "lon_ret", "lon_pos", "asia_range"]
    tr = R[R.day < CUTOFF]
    m = LogisticRegression(max_iter=400).fit(tr[feats], tr.green)
    auc_full = roc_auc_score(te.green, m.predict_proba(te[feats])[:, 1])
    auc_naive = roc_auc_score(te.green, te.lon_ret)
    m2 = LogisticRegression(max_iter=400).fit(tr[["lon_ret"]], tr.green)
    auc_lon = roc_auc_score(te.green, m2.predict_proba(te[["lon_ret"]])[:, 1])
    print(f"   naive(lon_ret)={auc_naive:.3f} | lon_ret-only={auc_lon:.3f} | +session-структура={auc_full:.3f} "
          f"(lift {auc_full-auc_lon:+.3f})")
    print("   (все as-of конца Лондона, час ~12 — это уже не «ночь», но раньше NY-тренда)")

    R.to_csv(HERE / "output" / "etap_219_sessions.csv", index=False)
    print("\nSaved: output/etap_219_sessions.csv")


if __name__ == "__main__":
    main()
