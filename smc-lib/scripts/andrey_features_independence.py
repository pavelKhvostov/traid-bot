"""C8-C15 independence audit + catch missed (#14, #15, #48).

Steps:
  1. Identify the 3 missed pivots in baseline by timestamp
  2. For each missed: which C8-C15 fires?
  3. Pairwise overlap matrix for C8-C15
  4. Union C8∪…∪C15 basket: total catch, WR, imp coverage
  5. Compare lift over baseline 1275 / vs canon basket C1-C7 (654 / 66.8% / 15 imp)
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASE_PATH = Path.home() / "Desktop" / "baseline_1267.parquet"
TF12_MS = 12 * 3600_000
MSK = timezone(timedelta(hours=3))

# === Missed pivots ===
MISSED = {
    "#14": datetime(2026, 3, 4, 15, 0, tzinfo=MSK),
    "#15": datetime(2026, 3, 8, 15, 0, tzinfo=MSK),
    "#48": datetime(2026, 5, 6, 3, 0, tzinfo=MSK),
}
MISSED_TS = {k: int(v.timestamp() * 1000) for k, v in MISSED.items()}

# === Load 1m and aggregate (same as previous script) ===
print("[1/3] Loading + computing features (same as before)...")
rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
def agg(d, tf_ms):
    out = []; cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out
bars12 = agg(rows, TF12_MS)
last_ts = rows[-1][0]
window_start = last_ts - 6 * 365 * 24 * 3600 * 1000
bars12 = [b for b in bars12 if b[0] >= window_start]
n = len(bars12)
ts = np.array([b[0] for b in bars12], dtype=np.int64)
op = np.array([b[1] for b in bars12])
hi = np.array([b[2] for b in bars12])
lo = np.array([b[3] for b in bars12])
cl = np.array([b[4] for b in bars12])
vo = np.array([b[5] for b in bars12])

rng = hi - lo
body = np.abs(cl - op)
upper_wick = hi - np.maximum(op, cl)
lower_wick = np.minimum(op, cl) - lo
close_pos = np.where(rng > 0, (cl - lo) / rng, 0.5)

tr = np.zeros(n); tr[0] = hi[0] - lo[0]
for i in range(1, n):
    tr[i] = max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
atr14 = pd.Series(tr).rolling(14).mean().bfill().values

vol_mean20 = pd.Series(vo).rolling(20).mean().bfill().values
vol_std20 = pd.Series(vo).rolling(20).std().bfill().replace(0, 1).values
vsa_vz = (vo - vol_mean20) / vol_std20
rng_mean20 = pd.Series(rng).rolling(20).mean().bfill().values
rng_std20 = pd.Series(rng).rolling(20).std().bfill().replace(0, 1).values
z_range = (rng - rng_mean20) / rng_std20
climax_bull = np.clip(z_range, 0, None) * np.clip(vsa_vz, 0, None) * close_pos
climax_bear = np.clip(z_range, 0, None) * np.clip(vsa_vz, 0, None) * (1 - close_pos)

ema20 = pd.Series(cl).ewm(span=20).mean().values
uptrend = np.concatenate([[False]*20, ema20[20:] > ema20[15:-5]])
downtrend = np.concatenate([[False]*20, ema20[20:] < ema20[15:-5]])
lwp = np.where(rng>0, lower_wick/rng, 0)
uwp = np.where(rng>0, upper_wick/rng, 0)
bp = np.where(rng>0, body/rng, 0)

cdl_hammer = ((lwp >= 0.5) & (uwp < 0.15) & (bp < 0.4) & downtrend).astype(int)
cdl_shooting_star = ((uwp >= 0.5) & (lwp < 0.15) & (bp < 0.4) & uptrend).astype(int)

def sweep_failed(win_bars):
    bsl_failed = np.zeros(n, dtype=int)
    ssl_failed = np.zeros(n, dtype=int)
    for i in range(win_bars, n):
        prev_hi = hi[i-win_bars:i].max()
        prev_lo = lo[i-win_bars:i].min()
        if hi[i] > prev_hi and cl[i] < prev_hi:
            bsl_failed[i] = 1
        if lo[i] < prev_lo and cl[i] > prev_lo:
            ssl_failed[i] = 1
    return bsl_failed, ssl_failed
bsl_f_24, ssl_f_24 = sweep_failed(2)

ts_to_idx = {int(t): k for k, t in enumerate(ts)}

# === Load baseline ===
df_base = pd.read_parquet(BASE_PATH)
df_base["bar_idx"] = df_base["ts"].apply(lambda t: ts_to_idx.get(int(t), -1))
df_base = df_base[df_base["bar_idx"] >= 0].copy().reset_index(drop=True)

# Attach all 8 C-conditions as bool arrays
df_base["C8_climax_bear_2"]  = df_base["bar_idx"].apply(lambda i: climax_bear[i] >= 2.0)
df_base["C9_cdl_hammer"]     = df_base["bar_idx"].apply(lambda i: cdl_hammer[i] == 1)
df_base["C10_climax_bear_1"] = df_base["bar_idx"].apply(lambda i: climax_bear[i] >= 1.0)
df_base["C11_climax_bull_2"] = df_base["bar_idx"].apply(lambda i: climax_bull[i] >= 2.0)
df_base["C12_climax_bull_1"] = df_base["bar_idx"].apply(lambda i: climax_bull[i] >= 1.0)
df_base["C13_cdl_shooting_star"] = df_base["bar_idx"].apply(lambda i: cdl_shooting_star[i] == 1)
df_base["C14_ssl_failed_24"] = df_base["bar_idx"].apply(lambda i: ssl_f_24[i] == 1)
df_base["C15_bsl_failed_24"] = df_base["bar_idx"].apply(lambda i: bsl_f_24[i] == 1)

# Direction-match for each (per spec — long-side for FL, short-side for FH)
DIR_MAP = {
    "C8":  "high", "C9":  "low", "C10": "high", "C11": "low",
    "C12": "low",  "C13": "high","C14": "low",  "C15": "high",
}

# === [2/3] Independence — pairwise overlap on baseline ===
print("\n[2/3] Pairwise overlap (intersection) on baseline 1275:")
COLS = ["C8_climax_bear_2","C9_cdl_hammer","C10_climax_bear_1","C11_climax_bull_2",
        "C12_climax_bull_1","C13_cdl_shooting_star","C14_ssl_failed_24","C15_bsl_failed_24"]
SHORT = ["C8","C9","C10","C11","C12","C13","C14","C15"]

# Apply direction filter per condition
masks = {}
for short_name, col in zip(SHORT, COLS):
    masks[short_name] = (df_base["direction"] == DIR_MAP[short_name]) & df_base[col]

# Overlap matrix
print(f"\n{'':<5}", end="")
for n2 in SHORT: print(f"{n2:>6}", end="")
print()
for n1 in SHORT:
    print(f"{n1:<5}", end="")
    for n2 in SHORT:
        a = masks[n1]; b = masks[n2]
        # Direction must match — so for cross-dir comparisons, count = 0
        inter = (a & b).sum()
        print(f"{inter:>6}", end="")
    print()

# IoU within same-direction conditions
print(f"\nIoU per direction group:")
for dir_lbl, group in [("LONG/FL", ["C9","C11","C12","C14"]), ("SHORT/FH", ["C8","C10","C13","C15"])]:
    print(f"  {dir_lbl}:")
    for i, a in enumerate(group):
        for b in group[i+1:]:
            ma, mb = masks[a], masks[b]
            inter = (ma & mb).sum()
            union = (ma | mb).sum()
            iou = inter / union * 100 if union else 0
            print(f"    {a:>3} ∩ {b:<3}  inter={inter:>3}  union={union:>3}  IoU={iou:>5.1f}%")

# === [3/3] Catch missed + union basket ===
print("\n[3/3] Catch of 3 missed pivots:")
for name, ts_target in MISSED_TS.items():
    sub = df_base[df_base["ts"] == ts_target]
    if sub.empty:
        print(f"  {name} {datetime.fromtimestamp(ts_target/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}: NOT in baseline")
        continue
    row = sub.iloc[0]
    line = f"  {name} {datetime.fromtimestamp(ts_target/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC  dir={row['direction']:<5}"
    fires = []
    for s in SHORT:
        if DIR_MAP[s] != row["direction"]:
            continue
        if df_base.loc[row.name, COLS[SHORT.index(s)]]:
            fires.append(s)
    line += f"  fires: {', '.join(fires) if fires else 'NONE'}"
    print(line)

# Union basket
print(f"\n[3.5] Union basket (C8∪…∪C15) per direction:")
for dir_lbl, group in [("low (LL/long)", ["C9","C11","C12","C14"]), ("high (HH/short)", ["C8","C10","C13","C15"])]:
    union_mask = pd.Series(False, index=df_base.index)
    for s in group:
        union_mask |= masks[s]
    sub = df_base[union_mask & (df_base["direction"] == DIR_MAP[group[0]])]
    keep = len(sub)
    conf = sub["confirmed"].sum()
    imp = sub[sub["is_important"] & sub["confirmed"]].shape[0]
    p_w = conf / keep * 100 if keep else 0
    print(f"  {dir_lbl:<18} keep={keep:>4} conf={conf:>4} P(W)={p_w:>5.1f}% imp={imp}")

# Full union both directions
total_mask = pd.Series(False, index=df_base.index)
for s in SHORT:
    total_mask |= masks[s]
sub_total = df_base[total_mask]
print(f"\n  TOTAL basket C8∪…∪C15: keep={len(sub_total)} conf={sub_total['confirmed'].sum()} "
      f"P(W)={sub_total['confirmed'].mean()*100:.1f}% "
      f"imp={sub_total[sub_total['is_important'] & sub_total['confirmed']].shape[0]}/18")

print(f"\n  Baseline: 1275 / 620 conf / 48.6% / 18 imp")
print(f"  Canon C1-C7 (per memory): 654 / 437 conf / 66.8% / 15 imp")
