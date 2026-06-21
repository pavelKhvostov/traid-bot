"""C8 candidate: D-fractal VWAP CLUSTER sweep — grid search for high WR + catch missed.

Hypothesis: single VWAP sweep gives too many false positives. Filter must require
  CLUSTER of multiple direction-matched VWAPs in tight price spread + macro anchor age.

For each baseline pivot bar:
  swept = [VWAP_v for f in direction-matched fractals
           if (FH: bar.high > v_value AND bar.close < v_value;
               FL: bar.low < v_value AND bar.close > v_value)
           AND age_days(f) >= AGE_MIN]
  cluster_spread = (max(swept) - min(swept)) / mean(swept) * 100

  C8(K, X, Y) = len(swept) >= K  AND  cluster_spread <= X  AND  age_min >= Y

Grid:
  K ∈ {2, 3, 4}
  X ∈ {0.5, 1.0, 1.5, 2.0}  (% spread)
  Y ∈ {60, 90, 180}         (days)

Target: maximize P(W) while catching #14, #15, #48.
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF_D_MS = 1440 * 60_000
TF_12H_MS = 720 * 60_000

MSK = timezone(timedelta(hours=3))
MISSED_TS = {
    "#14": int(datetime(2026,3,4,12,0,tzinfo=timezone.utc).timestamp() * 1000),
    "#15": int(datetime(2026,3,8,12,0,tzinfo=timezone.utc).timestamp() * 1000),
    "#48": int(datetime(2026,5,6,0,0,tzinfo=timezone.utc).timestamp() * 1000),
}

START_MS = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp() * 1000)

print("[1/5] Load 1m + aggregate D...")
rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        ts = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if ts < START_MS - 5*TF_D_MS: continue
        rows.append((ts, float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_arr = np.array([r[0] for r in rows], dtype=np.int64)
hi_arr = np.array([r[1] for r in rows])
lo_arr = np.array([r[2] for r in rows])
cl_arr = np.array([r[3] for r in rows])
vo_arr = np.array([r[4] for r in rows])

def agg(rs, tf_ms):
    out=[]; cb=None; h=l=c=v=0.0
    for ts,hh,ll,cc,vv in rs:
        b = ts - (ts%tf_ms)
        if b != cb:
            if cb is not None: out.append((cb,h,l,c,v))
            cb=b; h,l,c,v=hh,ll,cc,vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,h,l,c,v))
    return out
barsD = [b for b in agg(list(zip(ts_arr,hi_arr,lo_arr,cl_arr,vo_arr)), TF_D_MS) if b[0] >= START_MS]

# Williams N=2 fractals
N = 2
fractals = []
for i in range(N, len(barsD)-N):
    h_i, l_i = barsD[i][1], barsD[i][2]
    if all(h_i > barsD[i+j][1] for j in [-2,-1,1,2]):
        fractals.append({"ts": barsD[i][0], "ready": barsD[i+N][0] + TF_D_MS, "side": "FH"})
    if all(l_i < barsD[i+j][2] for j in [-2,-1,1,2]):
        fractals.append({"ts": barsD[i][0], "ready": barsD[i+N][0] + TF_D_MS, "side": "FL"})
print(f"  Fractals: {len(fractals)}")

# Cumulative pv/vol
pv_cum = np.cumsum(cl_arr * vo_arr)
vol_cum = np.cumsum(vo_arr)
def vwap_at(anchor_ts, query_ts):
    i_a = int(np.searchsorted(ts_arr, anchor_ts))
    i_q = int(np.searchsorted(ts_arr, query_ts, side='right')) - 1
    if i_a > i_q: return None
    pv = pv_cum[i_q] - (pv_cum[i_a-1] if i_a > 0 else 0)
    v  = vol_cum[i_q] - (vol_cum[i_a-1] if i_a > 0 else 0)
    return pv / v if v > 0 else None

# === Load baseline + precompute swept VWAPs for each bar ===
print("[2/5] Load baseline + precompute swept VWAPs per bar...")
df_base = pd.read_parquet(BASE_PATH)
print(f"  Baseline: {len(df_base)}")

# For each bar, compute swept VWAPs (with anchor age info)
bar_swept = {}  # idx → list of (vwap_value, anchor_age_days)
for bidx, row in df_base.iterrows():
    bar_open_ms = int(row["ts"])
    bar_close_ms = bar_open_ms + TF_12H_MS
    direction = row["direction"]
    side = "FH" if direction == "high" else "FL"
    # Get bar OHLC from rows
    i_start = int(np.searchsorted(ts_arr, bar_open_ms))
    i_end = int(np.searchsorted(ts_arr, bar_close_ms))
    if i_end <= i_start: continue
    bar_high = hi_arr[i_start:i_end].max()
    bar_low = lo_arr[i_start:i_end].min()
    bar_close = cl_arr[i_end-1]

    rel = [f for f in fractals if f["side"] == side and f["ready"] <= bar_open_ms]
    sweep = []
    for f in rel:
        v = vwap_at(f["ts"], bar_close_ms)
        if v is None: continue
        if side == "FH":
            swept = bar_high > v and bar_close < v
        else:
            swept = bar_low < v and bar_close > v
        if not swept: continue
        age_days = (bar_close_ms - f["ts"]) / (24 * 3600_000)
        sweep.append((v, age_days))
    bar_swept[bidx] = sweep

print(f"  Bars with ≥1 swept: {sum(1 for v in bar_swept.values() if v)}")
print(f"  Bars with ≥2 swept: {sum(1 for v in bar_swept.values() if len(v) >= 2)}")
print(f"  Bars with ≥3 swept: {sum(1 for v in bar_swept.values() if len(v) >= 3)}")
print(f"  Bars with ≥4 swept: {sum(1 for v in bar_swept.values() if len(v) >= 4)}")

# === Grid search ===
print("\n[3/5] Grid search C8(K, X_spread, Y_age_min)...")

# Identify missed indices
missed_idx = {}
for tag, ts in MISSED_TS.items():
    matches = df_base[df_base["ts"] == ts]
    if not matches.empty:
        missed_idx[tag] = matches.index[0]
print(f"  Missed indices: {missed_idx}")

def evaluate(K, X_max_spread, Y_min_age_days):
    keep, conf, imp = 0, 0, 0
    caught_missed = []
    for bidx, sweep in bar_swept.items():
        # Filter by age
        sweep_aged = [(v, a) for v, a in sweep if a >= Y_min_age_days]
        if len(sweep_aged) < K: continue
        # Cluster spread check
        vs = [v for v, _ in sweep_aged]
        spread_pct = (max(vs) - min(vs)) / np.mean(vs) * 100
        if spread_pct > X_max_spread: continue
        # Passes — count
        keep += 1
        row = df_base.iloc[bidx]
        if row["confirmed"]: conf += 1
        if row["is_important"] and row["confirmed"]: imp += 1
        for tag, m_idx in missed_idx.items():
            if bidx == m_idx: caught_missed.append(tag)
    p_w = conf / keep * 100 if keep else 0
    return {"K": K, "X_spread%": X_max_spread, "Y_age_days": Y_min_age_days,
            "keep": keep, "conf": conf, "P_W%": round(p_w, 1),
            "imp": imp, "caught_missed": "+".join(sorted(caught_missed))}

results = []
for K in [2, 3, 4]:
    for X in [0.5, 1.0, 1.5, 2.0]:
        for Y in [60, 90, 180]:
            results.append(evaluate(K, X, Y))

df = pd.DataFrame(results)
df.to_csv(Path.home() / "Desktop" / "c8_vwap_cluster_grid.csv", index=False)

# Print sorted
print(f"\n[4/5] Grid results (sorted by P_W with ≥1 missed caught):")
df_caught = df[df["caught_missed"] != ""].sort_values("P_W%", ascending=False)
print(f"{'K':>2} {'X%':>4} {'Y_d':>4} {'keep':>5} {'conf':>5} {'P_W%':>6} {'imp':>4} {'caught':<15}")
for _, r in df_caught.iterrows():
    print(f"{r['K']:>2} {r['X_spread%']:>4.1f} {r['Y_age_days']:>4} {r['keep']:>5} {r['conf']:>5} {r['P_W%']:>5.1f}% {r['imp']:>4} {r['caught_missed']:<15}")

# Configs that catch ALL 3 missed
print(f"\n[5/5] Configs catching ALL 3 missed (#14+#15+#48):")
all3 = df[df["caught_missed"].str.contains(r"#14.*#15.*#48", regex=True) |
          df["caught_missed"].apply(lambda s: set(["#14","#15","#48"]).issubset(set(s.split("+"))) if s else False)]
all3 = all3.sort_values("P_W%", ascending=False)
if len(all3):
    for _, r in all3.iterrows():
        print(f"  K={r['K']} spread≤{r['X_spread%']}% age≥{r['Y_age_days']}d  → keep={r['keep']} conf={r['conf']} P(W)={r['P_W%']:.1f}% imp={r['imp']}")
else:
    print(f"  NONE — no single config catches all 3")

print(f"\nBaseline reference: 1275 / 620 / 48.6% / 18 imp")
print(f"Canon basket C1-C7: 654 / 437 / 66.8% / 15 imp (need C8 catching missed)")
print(f"\n→ Saved: ~/Desktop/c8_vwap_cluster_grid.csv")
