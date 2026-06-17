"""Адверсариальная проверка ml-3 (hazard-слой): одноразовый ревью-скрипт, НЕ etap.
1) Считает РЕАЛЬНУЮ частоту смен intraday-состояния (etap_217 classify, IB=3, EXT=0.10)
   — проверка предпосылки '0.70 смен/день' (та цифра была про сглаженный call, не про state).
2) hazard P(flip next hour | state, hours_in_state) train<2023 vs OOS 2023+ — монотонность? стабильность?
3) AUC логистики flip_next ~ state + hours_in_state + k (train→OOS) vs константа-per-state.
4) Sparsity ячеек (state, hours_in_state, hour_utc).
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
IB, EXT = 3, 0.10
CUT = pd.Timestamp("2023-01-01", tz="UTC")

df = pd.read_csv(DATA, index_col=0, parse_dates=True)
if df.index.tz is None: df.index = df.index.tz_localize("UTC")
df = df.sort_index()

rows = []
for day, g in df.groupby(df.index.normalize()):
    if len(g) < IB + 2: continue
    H, L, c = g["high"].values, g["low"].values, g["close"].values
    hi = np.maximum.accumulate(H); lo = np.minimum.accumulate(L)
    ib_h, ib_l = H[:IB].max(), L[:IB].min(); ib_r = max(ib_h - ib_l, 1e-9)
    states = []
    for k in range(len(g)):
        if k < IB: st = "FORMING"
        else:
            eu = max(0, hi[k]-ib_h)/ib_r; ed = max(0, ib_l-lo[k])/ib_r
            if c[k] > ib_h and eu >= EXT: st = "TREND_UP"
            elif c[k] < ib_l and ed >= EXT: st = "TREND_DOWN"
            else: st = "ROTATION"
        states.append(st)
    his = 1
    for k in range(len(states)):
        if k > 0 and states[k] == states[k-1]: his += 1
        else: his = 1
        flip = int(states[k+1] != states[k]) if k+1 < len(states) else np.nan
        rows.append(dict(day=day, k=k, state=states[k], his=his, flip=flip))
R = pd.DataFrame(rows)

# 1) реальная частота смен state в день (после формирования IB)
post = R[R.k >= IB]
fl_day = post.groupby("day")["flip"].sum()
print(f"дней {fl_day.shape[0]} | СМЕН STATE/день (после IB): среднее {fl_day.mean():.2f} | медиана {fl_day.median():.0f} | <=1: {(fl_day<=1).mean()*100:.0f}% | 0: {(fl_day==0).mean()*100:.0f}%")

W = post.dropna(subset=["flip"]).copy()  # FORMING исключён (k>=IB), последний час дня выброшен
W["flip"] = W["flip"].astype(int)
tr, te = W[W.day < CUT], W[W.day >= CUT]
print(f"строк train {len(tr)} / OOS {len(te)} | base hazard train {tr.flip.mean():.3f} OOS {te.flip.mean():.3f}")

# какие переходы вообще бывают
nxt = R.assign(nstate=R.groupby("day")["state"].shift(-1)).dropna(subset=["nstate"])
nxt = nxt[(nxt.k >= IB) & (nxt.state != nxt.nstate)]
print("\nматрица переходов (всего, train+OOS):")
print(pd.crosstab(nxt.state, nxt.nstate).to_string())

# 2) hazard vs hours_in_state по state, train vs OOS
print("\nhazard P(flip|state, his):  (n)")
bins = [(1,1),(2,2),(3,3),(4,5),(6,8),(9,24)]
for st in ["ROTATION", "TREND_UP", "TREND_DOWN"]:
    line = f"  {st:<11}"
    for lab, sub in [("TR", tr), ("OOS", te)]:
        s = sub[sub.state == st]
        cells = []
        for a, b in bins:
            m = s[(s.his >= a) & (s.his <= b)]
            cells.append(f"{a}-{b}:{m.flip.mean():.2f}({len(m)})" if len(m) else f"{a}-{b}:--")
        line += f" | {lab} " + " ".join(cells)
    print(line)

# 3) логистика flip ~ his + k + state-dummies, OOS AUC vs per-state константа
X = pd.get_dummies(W[["his", "k", "state"]], columns=["state"], drop_first=True).astype(float)
Xtr, Xte = X[W.day.values < CUT], X[W.day.values >= CUT]
m = LogisticRegression(max_iter=500).fit(Xtr, tr.flip)
p = m.predict_proba(Xte)[:, 1]
base = tr.groupby("state")["flip"].mean()
pb = te.state.map(base).values
print(f"\nAUC OOS: логистика(his,k,state) {roc_auc_score(te.flip, p):.3f} | константа-per-state {roc_auc_score(te.flip, pb):.3f}")
print(f"Brier OOS: модель {brier_score_loss(te.flip, p):.4f} | константа {brier_score_loss(te.flip, pb):.4f}")
# his-only внутри state: per-state AUC his как скор
for st in ["ROTATION", "TREND_UP", "TREND_DOWN"]:
    s = te[te.state == st]
    if s.flip.nunique() > 1:
        print(f"  {st}: AUC(–his) OOS {roc_auc_score(s.flip, -s.his):.3f} (n={len(s)}, flips {s.flip.sum()})")

# 4) sparsity ячеек (state, his, k)
cell = tr.groupby(["state", "his", "k"]).size()
print(f"\nячейки (state,his,k) train: всего {len(cell)} | n<30: {(cell<30).mean()*100:.0f}% | n<10: {(cell<10).mean()*100:.0f}%")
cell2 = tr.groupby(["state", "his"]).size()
print(f"ячейки (state,his) train: всего {len(cell2)} | n<30: {(cell2<30).mean()*100:.0f}%")
