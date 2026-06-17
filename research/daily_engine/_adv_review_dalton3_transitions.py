"""Адверсариальная проверка dalton-3: матрица переходов day-type (etap_217 rules).
Одноразовый ревью-скрипт, НЕ etap. Считает:
  1) финальный тип дня (classify на последнем баре, IB=3, EXT=0.10)
  2) 3x3 переходы train<2023 vs OOS 2023+, chi-square vs unconditional
  3) P(big_day | streak_balance>=N) vs base (big_day = range > rolling med30)
  4) направленная часть: P(green_today | prev_dtype) — проверка на стену direction
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import chi2_contingency

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1h.csv"
IB, EXT = 3, 0.10
CUT = pd.Timestamp("2023-01-01", tz="UTC")

df = pd.read_csv(DATA, index_col=0, parse_dates=True)
if df.index.tz is None: df.index = df.index.tz_localize("UTC")

rows = []
for day, g in df.groupby(df.index.normalize()):
    if len(g) < IB + 2: continue
    o = g["open"].iloc[0]; c = g["close"].iloc[-1]
    H, L = g["high"].values, g["low"].values
    ib_h, ib_l = H[:IB].max(), L[:IB].min(); ib_r = max(ib_h - ib_l, 1e-9)
    hi, lo = H.max(), L.min()
    ext_up = max(0, hi - ib_h) / ib_r; ext_dn = max(0, ib_l - lo) / ib_r
    above = c > ib_h; below = c < ib_l
    if above and ext_up >= EXT: st = "TREND_UP"
    elif below and ext_dn >= EXT: st = "TREND_DOWN"
    else: st = "ROTATION"
    rows.append(dict(day=day, state=st, green=int(c > o), rng=(hi - lo) / c))
d = pd.DataFrame(rows).set_index("day").sort_index()
d["big"] = (d["rng"] > d["rng"].rolling(30).median()).astype(float)
d["prev"] = d["state"].shift(1)
d["prev_green"] = d["green"].shift(1)
d = d.dropna(subset=["prev"])

print(f"дней всего {len(d)} | base rates: {d.state.value_counts(normalize=True).round(3).to_dict()}")

for lab, sub in [("TRAIN <2023", d[d.index < CUT]), ("OOS 2023+", d[d.index >= CUT])]:
    ct = pd.crosstab(sub["prev"], sub["state"])
    pr = pd.crosstab(sub["prev"], sub["state"], normalize="index").round(3)
    chi2, p, dof, _ = chi2_contingency(ct)
    print(f"\n=== {lab} (n={len(sub)}) chi2={chi2:.1f} p={p:.4f}")
    print(pr.to_string())
    # направленная часть: P(green | prev)
    pg = sub.groupby("prev")["green"].agg(["mean", "count"]).round(3)
    print("P(green_today | prev_dtype):"); print(pg.to_string())

# streak_balance -> big_day
d["is_rot"] = (d["state"] == "ROTATION").astype(int)
streak = []
s = 0
for v in d["is_rot"].values:
    streak.append(s)        # streak ДО сегодняшнего дня (только прошлое)
    s = s + 1 if v else 0
d["streak_prior"] = streak
dd = d.dropna(subset=["big"])
for lab, sub in [("TRAIN <2023", dd[dd.index < CUT]), ("OOS 2023+", dd[dd.index >= CUT])]:
    base = sub["big"].mean()
    print(f"\n=== {lab}: P(big_day) base={base:.3f}")
    for n in [0, 1, 2, 3]:
        m = sub["streak_prior"] >= n
        print(f"  streak_balance>={n}: P(big)={sub.loc[m,'big'].mean():.3f} (n={m.sum()})")
    # и наоборот: после TREND-дня
    mt = sub["prev"].isin(["TREND_UP", "TREND_DOWN"])
    print(f"  после TREND-дня:  P(big)={sub.loc[mt,'big'].mean():.3f} (n={mt.sum()}) | после ROT: {sub.loc[~mt,'big'].mean():.3f}")
