"""Адверсариальная проверка ml-2: P(trend-hold) — одноразовый ревью-скрипт, НЕ etap.
1) базовые ставки P(hold | state, k) train<2023 vs OOS 2023+
2) бейзлайн-таблица (train) -> AUC на OOS per-k
3) логистика на фичах кандидата -> AUC на OOS per-k, lift над таблицей
hold = state_EOD == state_k (полные дни 24 бара, последний/частичный день дропаем)
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
IB, EXT = 3, 0.10
CUT = pd.Timestamp("2023-01-01", tz="UTC")

df = pd.read_csv(DATA, index_col=0, parse_dates=True)
if df.index.tz is None: df.index = df.index.tz_localize("UTC")

rows = []
for day, g in df.groupby(df.index.normalize()):
    if len(g) != 24: continue  # только полные дни
    o = g["open"].iloc[0]; c = g["close"].values
    H, L = g["high"].values, g["low"].values
    hi = np.maximum.accumulate(H); lo = np.minimum.accumulate(L)
    ib_h, ib_l = H[:IB].max(), L[:IB].min(); ib_r = max(ib_h - ib_l, 1e-9)
    ib_mid = (ib_h + ib_l) / 2
    states = []
    for k in range(24):
        if k < IB: states.append("FORMING"); continue
        eu = max(0, hi[k] - ib_h) / ib_r; ed = max(0, ib_l - lo[k]) / ib_r
        if c[k] > ib_h and eu >= EXT: states.append("TREND_UP")
        elif c[k] < ib_l and ed >= EXT: states.append("TREND_DOWN")
        else: states.append("ROTATION")
    final = states[-1]
    # hours_in_state причинно
    his = 0
    for k in range(IB, 24):
        his = his + 1 if k > IB and states[k] == states[k-1] else 1
        eu = max(0, hi[k] - ib_h) / ib_r; ed = max(0, ib_l - lo[k]) / ib_r
        rng = hi[k] - lo[k]
        rows.append(dict(day=day, k=k, state=states[k], final=final,
                         hold=int(states[k] == final), his=his,
                         ext_up=eu, ext_dn=ed,
                         dist_ib=(c[k] - ib_mid) / ib_r,
                         pos_rng=(c[k] - lo[k]) / rng if rng > 0 else 0.5,
                         rng_atr=rng / c[k]))
R = pd.DataFrame(rows)
tr, te = R[R.day < CUT], R[R.day >= CUT]
print(f"дней: train {tr.day.nunique()} / test {te.day.nunique()}; строк {len(R)}")

print("\n=== P(hold | state, k) train -> test (n_test) ===")
for st in ["TREND_UP", "TREND_DOWN", "ROTATION"]:
    line = [st.ljust(11)]
    for k in [4, 6, 8, 12, 16, 20]:
        a = tr[(tr.state == st) & (tr.k == k)]["hold"]
        b = te[(te.state == st) & (te.k == k)]["hold"]
        line.append(f"k{k}: {a.mean():.2f}->{b.mean():.2f}(n{len(b)})")
    print("  " + " | ".join(line))

# бейзлайн-таблица: P(hold | state, k) с train
tab = tr.groupby(["state", "k"])["hold"].mean()
te = te.copy()
te["p_tab"] = te.apply(lambda r: tab.get((r["state"], r["k"]), tr.hold.mean()), axis=1)

# логистика на фичах кандидата, отдельно per state (pooled k, k как фича)
FE = ["k", "his", "ext_up", "ext_dn", "dist_ib", "pos_rng", "rng_atr"]
te["p_ml"] = np.nan
for st in ["TREND_UP", "TREND_DOWN", "ROTATION"]:
    a = tr[tr.state == st]; b = te[te.state == st]
    if a.hold.nunique() < 2: continue
    m = LogisticRegression(max_iter=500).fit(a[FE], a.hold)
    te.loc[b.index, "p_ml"] = m.predict_proba(b[FE])[:, 1]

print("\n=== OOS AUC: таблица vs логистика (per state, pooled по k) ===")
for st in ["TREND_UP", "TREND_DOWN", "ROTATION"]:
    b = te[te.state == st].dropna(subset=["p_ml"])
    if b.hold.nunique() < 2: print(f"  {st}: hold вырожден"); continue
    at = roc_auc_score(b.hold, b.p_tab); am = roc_auc_score(b.hold, b.p_ml)
    print(f"  {st:<11} n={len(b):>5} base={b.hold.mean():.2f}  AUC табл {at:.3f} | ML {am:.3f} | lift {am-at:+.3f}")

print("\n=== per-k AUC (все state вместе), исключая вырожденные ===")
for k in [4, 6, 8, 12, 16, 20]:
    b = te[te.k == k].dropna(subset=["p_ml"])
    if b.hold.nunique() < 2: continue
    at = roc_auc_score(b.hold, b.p_tab); am = roc_auc_score(b.hold, b.p_ml)
    print(f"  k={k:>2} n={len(b):>4} base={b.hold.mean():.2f}  табл {at:.3f} | ML {am:.3f} | lift {am-at:+.3f}")
