"""Cross-join baseline 1275 × Andrey's top features → candidates for C8-C14.

Computes Andrey's strict-causal features at bar i on our 12h dataset, joins
with baseline 1275, and reports standalone WR + imp_caught per candidate.

Features computed:
  sweep_SSL_failed_24h / sweep_BSL_failed_24h   (binary, direction-matched)
  sweep_SSL_failed_72h / sweep_BSL_failed_72h   (binary, direction-matched)
  vsa_climax_bull / vsa_climax_bear             (continuous → thr=1.0)
  candle_close_pos_in_range                     (continuous → thr 0.2 for long, 0.8 short)
  candle_range_vs_atr                           (continuous → thr 2.0)
  cdl_hammer / cdl_inv_hammer (long)            (binary)
  cdl_shooting_star (short)                     (binary)
  pre_3d_return_pct                             (continuous → thr ±5%)

Output: ~/Desktop/baseline_andrey_features_xjoin.csv
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

print("[1/4] Loading 1m and aggregating 12h...")
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
print(f"  12h bars: {n}")

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

# ATR14
tr = np.zeros(n)
tr[0] = hi[0] - lo[0]
for i in range(1, n):
    tr[i] = max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
atr14 = pd.Series(tr).rolling(14).mean().bfill().values

# === Features ===
print("[2/4] Computing features...")
# Volume zscore (20-bar rolling)
vol_mean20 = pd.Series(vo).rolling(20).mean().bfill().values
vol_std20 = pd.Series(vo).rolling(20).std().bfill().replace(0, 1).values
vsa_vz = (vo - vol_mean20) / vol_std20

# Range z-score
rng_mean20 = pd.Series(rng).rolling(20).mean().bfill().values
rng_std20 = pd.Series(rng).rolling(20).std().bfill().replace(0, 1).values
z_range = (rng - rng_mean20) / rng_std20

# VSA climax (Andrey def)
climax_bull = np.clip(z_range, 0, None) * np.clip(vsa_vz, 0, None) * close_pos
climax_bear = np.clip(z_range, 0, None) * np.clip(vsa_vz, 0, None) * (1 - close_pos)

# Candle range vs ATR
range_vs_atr = rng / np.maximum(atr14, 1e-9)

# Trend (5-bar EMA20 slope)
ema20 = pd.Series(cl).ewm(span=20).mean().values
uptrend = np.concatenate([[False]*20, ema20[20:] > ema20[15:-5]])
downtrend = np.concatenate([[False]*20, ema20[20:] < ema20[15:-5]])
lwp = np.where(rng>0, lower_wick/rng, 0)
uwp = np.where(rng>0, upper_wick/rng, 0)
bp = np.where(rng>0, body/rng, 0)

# Candle patterns (per Andrey)
cdl_hammer = ((lwp >= 0.5) & (uwp < 0.15) & (bp < 0.4) & downtrend).astype(int)
cdl_inv_hammer = ((uwp >= 0.5) & (lwp < 0.15) & (bp < 0.4) & downtrend).astype(int)
cdl_shooting_star = ((uwp >= 0.5) & (lwp < 0.15) & (bp < 0.4) & uptrend).astype(int)
cdl_hanging_man = ((lwp >= 0.5) & (uwp < 0.15) & (bp < 0.4) & uptrend).astype(int)

# Sweep BSL/SSL failed in N hours (N_bars = N/12)
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
bsl_f_24, ssl_f_24 = sweep_failed(2)   # 24h = 2 × 12h
bsl_f_72, ssl_f_72 = sweep_failed(6)   # 72h
bsl_f_168, ssl_f_168 = sweep_failed(14) # 7d

# 3-day return
pre_3d_return_pct = np.zeros(n)
for i in range(6, n):
    p3 = cl[i-6]
    pre_3d_return_pct[i] = (cl[i] - p3) / p3 * 100 if p3 else 0

# ts → bar idx
ts_to_idx = {int(t): k for k, t in enumerate(ts)}

# === Load baseline ===
print("[3/4] Loading baseline + cross-join...")
df_base = pd.read_parquet(BASE_PATH)
df_base["bar_idx"] = df_base["ts"].apply(lambda t: ts_to_idx.get(int(t), -1))
df_base = df_base[df_base["bar_idx"] >= 0].copy()
print(f"  Baseline mapped: {len(df_base)}")

# Attach features
df_base["close_pos"] = df_base["bar_idx"].apply(lambda i: close_pos[i])
df_base["range_vs_atr"] = df_base["bar_idx"].apply(lambda i: range_vs_atr[i])
df_base["climax_bull"] = df_base["bar_idx"].apply(lambda i: climax_bull[i])
df_base["climax_bear"] = df_base["bar_idx"].apply(lambda i: climax_bear[i])
df_base["pre_3d_return"] = df_base["bar_idx"].apply(lambda i: pre_3d_return_pct[i])
df_base["bsl_failed_24"] = df_base["bar_idx"].apply(lambda i: bsl_f_24[i])
df_base["ssl_failed_24"] = df_base["bar_idx"].apply(lambda i: ssl_f_24[i])
df_base["bsl_failed_72"] = df_base["bar_idx"].apply(lambda i: bsl_f_72[i])
df_base["ssl_failed_72"] = df_base["bar_idx"].apply(lambda i: ssl_f_72[i])
df_base["bsl_failed_168"] = df_base["bar_idx"].apply(lambda i: bsl_f_168[i])
df_base["ssl_failed_168"] = df_base["bar_idx"].apply(lambda i: ssl_f_168[i])
df_base["cdl_hammer"] = df_base["bar_idx"].apply(lambda i: cdl_hammer[i])
df_base["cdl_inv_hammer"] = df_base["bar_idx"].apply(lambda i: cdl_inv_hammer[i])
df_base["cdl_shooting_star"] = df_base["bar_idx"].apply(lambda i: cdl_shooting_star[i])
df_base["cdl_hanging_man"] = df_base["bar_idx"].apply(lambda i: cdl_hanging_man[i])

# === Evaluate each candidate ===
print("\n[4/4] Per-feature WR on baseline 1275:")
baseline = df_base["confirmed"].mean() * 100
print(f"  Baseline confirmed: {df_base['confirmed'].sum()} / {len(df_base)} = {baseline:.1f}%\n")

results = []

def evaluate(name, mask, target_dir):
    sub = df_base[(df_base["direction"] == target_dir) & mask]
    if len(sub) == 0:
        return None
    keep = len(sub)
    conf = sub["confirmed"].sum()
    p_w = conf / keep * 100
    imp = sub[sub["is_important"] & sub["confirmed"]].shape[0]
    return {"feature": name, "dir": target_dir, "keep": keep, "conf": int(conf), "P_W_pct": round(p_w,1), "imp": int(imp)}

candidates = [
    # SSL failed → for LL (long pivot)
    ("ssl_failed_24",                df_base["ssl_failed_24"]==1, "low"),
    ("ssl_failed_72",                df_base["ssl_failed_72"]==1, "low"),
    ("ssl_failed_168",               df_base["ssl_failed_168"]==1, "low"),
    # BSL failed → for HH (high pivot)
    ("bsl_failed_24",                df_base["bsl_failed_24"]==1, "high"),
    ("bsl_failed_72",                df_base["bsl_failed_72"]==1, "high"),
    ("bsl_failed_168",               df_base["bsl_failed_168"]==1, "high"),
    # VSA climax
    ("climax_bull (≥1)",             df_base["climax_bull"]>=1.0, "low"),
    ("climax_bull (≥2)",             df_base["climax_bull"]>=2.0, "low"),
    ("climax_bear (≥1)",             df_base["climax_bear"]>=1.0, "high"),
    ("climax_bear (≥2)",             df_base["climax_bear"]>=2.0, "high"),
    # close_pos (long: close near low; short: close near high)
    ("close_pos ≤ 0.2 (long)",       df_base["close_pos"]<=0.2, "low"),
    ("close_pos ≤ 0.3 (long)",       df_base["close_pos"]<=0.3, "low"),
    ("close_pos ≥ 0.7 (short)",      df_base["close_pos"]>=0.7, "high"),
    ("close_pos ≥ 0.8 (short)",      df_base["close_pos"]>=0.8, "high"),
    # range_vs_atr (climax wide bar)
    ("range_vs_atr ≥ 1.5",           df_base["range_vs_atr"]>=1.5, "low"),
    ("range_vs_atr ≥ 1.5",           df_base["range_vs_atr"]>=1.5, "high"),
    ("range_vs_atr ≥ 2.0",           df_base["range_vs_atr"]>=2.0, "low"),
    ("range_vs_atr ≥ 2.0",           df_base["range_vs_atr"]>=2.0, "high"),
    # 3d return (exhaustion)
    ("pre_3d_return ≤ -5%",          df_base["pre_3d_return"]<=-5, "low"),
    ("pre_3d_return ≤ -10%",         df_base["pre_3d_return"]<=-10, "low"),
    ("pre_3d_return ≥ +5%",          df_base["pre_3d_return"]>=5, "high"),
    ("pre_3d_return ≥ +10%",         df_base["pre_3d_return"]>=10, "high"),
    # Candle patterns
    ("cdl_hammer (long)",            df_base["cdl_hammer"]==1, "low"),
    ("cdl_inv_hammer (long)",        df_base["cdl_inv_hammer"]==1, "low"),
    ("cdl_shooting_star (short)",    df_base["cdl_shooting_star"]==1, "high"),
    ("cdl_hanging_man (short)",      df_base["cdl_hanging_man"]==1, "high"),
]

for name, mask, td in candidates:
    r = evaluate(name, mask, td)
    if r:
        results.append(r)

df_r = pd.DataFrame(results).sort_values(["dir", "P_W_pct"], ascending=[True, False])
df_r.to_csv(Path.home() / "Desktop" / "baseline_andrey_features_xjoin.csv", index=False)

print(f"{'Feature':<32} {'dir':<5} {'keep':>5} {'conf':>5} {'P(W)%':>7} {'imp':>4}")
print("-" * 70)
for _, r in df_r.iterrows():
    flag = "★" if r["P_W_pct"] >= 65 and r["keep"] >= 30 else (" " if r["P_W_pct"] >= 55 else "·")
    print(f"{flag} {r['feature']:<30} {r['dir']:<5} {r['keep']:>5} {r['conf']:>5} {r['P_W_pct']:>6.1f}% {r['imp']:>4}")

print(f"\nBaseline (no filter) WR per dir:")
for d in ("high", "low"):
    sub = df_base[df_base["direction"]==d]
    print(f"  {d}: {sub['confirmed'].sum()}/{len(sub)} = {sub['confirmed'].mean()*100:.1f}%")
print(f"\n→ Saved: ~/Desktop/baseline_andrey_features_xjoin.csv")
