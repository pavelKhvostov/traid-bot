"""Baseline 1267 — generate F1∩F2∩F3 pred-fractal events on 6y BTC 12h.

Canon: ~/smc-lib/projects/pred12h-fractal-three-candles.md

Expected on 6y in-sample:
  pre-W (3-bar extreme): 2891
  + F1 left_ext_5:        1889
  + F2 (opp ∨ three_same): 1408
  + F3 (body≤0.80 ∧ wick≥0.03): 1267   ← baseline
  P(W) confirmed ≈ 48.9%
  18/18 important recall

Output: ~/Desktop/baseline_1267.parquet
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
TF12_MS = 12 * 3600_000
OUT = Path.home() / "Desktop" / "baseline_1267.parquet"

# === Load 1m ===
print("[1/5] Loading 1m BTC...")
rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  {len(rows):,} 1m rows; last = {datetime.fromtimestamp(rows[-1][0]/1000, tz=timezone.utc)}")

# === Aggregate 12h (epoch anchor UTC 00:00 / 12:00) ===
print("[2/5] Aggregating to 12h...")
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
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
bars12 = [b for b in bars12 if b[0] >= window_start_ms]
print(f"  12h bars in 6y window: {len(bars12)}")
print(f"  Range: {datetime.fromtimestamp(bars12[0][0]/1000, tz=timezone.utc)} → {datetime.fromtimestamp(bars12[-1][0]/1000, tz=timezone.utc)}")

# === Filter cascade ===
print("[3/5] Applying F1∩F2∩F3 cascade...")

def color_of(b):
    if b[4] > b[1]: return "bull"
    if b[4] < b[1]: return "bear"
    return "doji"

# Important pivots (18 imp from 4mo window 2026-02-04+)
START_IMP_MS = int(datetime(2026, 2, 4, 0, 0, tzinfo=timezone(timedelta(hours=3))).timestamp() * 1000)
IMPORTANT = {1, 3, 4, 5, 9, 10, 11, 14, 15, 20, 23, 26, 29, 40, 41, 42, 47, 48}

# Pass 1: collect all Williams N=2 fractals in 4mo window (for important indexing)
gt_in_window = []
for i in range(2, len(bars12) - 2):
    bi = bars12[i]
    if bi[0] < START_IMP_MS: continue
    bip1, bip2 = bars12[i+1], bars12[i+2]
    bim1, bim2 = bars12[i-1], bars12[i-2]
    if bi[2] > bim1[2] and bi[2] > bim2[2] and bi[2] > bip1[2] and bi[2] > bip2[2]:
        gt_in_window.append({"i": i, "dir": "high", "ts": bi[0]})
    if bi[3] < bim1[3] and bi[3] < bim2[3] and bi[3] < bip1[3] and bi[3] < bip2[3]:
        gt_in_window.append({"i": i, "dir": "low", "ts": bi[0]})
imp_idx = {gt_in_window[n-1]["i"] for n in IMPORTANT if n <= len(gt_in_window)}
print(f"  Ground truth Williams в 4mo окне: {len(gt_in_window)}; important set: {len(imp_idx)}")

# Pass 2: cascade
events = []
cnt_pre, cnt_f1, cnt_f2, cnt_f3 = 0, 0, 0, 0

for i in range(2, len(bars12) - 2):
    bi = bars12[i]
    bim1, bim2 = bars12[i-1], bars12[i-2]
    bip1, bip2 = bars12[i+1], bars12[i+2]

    pre_fh = bi[2] > bim1[2] and bi[2] > bim2[2]
    pre_fl = bi[3] < bim1[3] and bi[3] < bim2[3]
    if not (pre_fh or pre_fl): continue

    for direction in (("high",) if pre_fh else ()) + (("low",) if pre_fl else ()):
        cnt_pre += 1

        # F1: left_ext_5
        left_lo = max(0, i-5)
        if direction == "high":
            f1 = bi[2] > max(b[2] for b in bars12[left_lo:i]) if i > left_lo else True
        else:
            f1 = bi[3] < min(b[3] for b in bars12[left_lo:i]) if i > left_lo else True
        if not f1: continue
        cnt_f1 += 1

        # F2: opp_colors ∨ three_same
        c0, c1, c2 = color_of(bi), color_of(bim1), color_of(bim2)
        opp_colors = (c0 != c1) and ("doji" not in (c0, c1))
        three_same = (c0 == c1 == c2) and (c0 != "doji")
        if not (opp_colors or three_same): continue
        cnt_f2 += 1

        # F3: body/range ≤ 0.80 ∧ wick/range ≥ 0.03
        rng = bi[2] - bi[3] if bi[2] > bi[3] else 1e-9
        body = abs(bi[4] - bi[1])
        if direction == "high":
            relevant_wick = bi[2] - max(bi[1], bi[4])
        else:
            relevant_wick = min(bi[1], bi[4]) - bi[3]
        body_pct = body / rng
        wick_pct = relevant_wick / rng
        if not (body_pct <= 0.80 and wick_pct >= 0.03): continue
        cnt_f3 += 1

        # Williams confirm
        if direction == "high":
            confirmed = bi[2] > bip1[2] and bi[2] > bip2[2]
            level = bi[2]
        else:
            confirmed = bi[3] < bip1[3] and bi[3] < bip2[3]
            level = bi[3]

        events.append({
            "idx": i,
            "ts": bi[0],
            "direction": direction,
            "level": level,
            "confirmed": confirmed,
            "is_important": i in imp_idx and bi[0] >= START_IMP_MS,
            "open": bi[1], "high": bi[2], "low": bi[3], "close": bi[4],
            "volume": bi[5],
            "body_pct": body_pct,
            "wick_pct": wick_pct,
            "opp_colors": opp_colors,
            "three_same": three_same,
        })

print(f"\n[4/5] Cascade counts:")
print(f"  pre-W (3-bar extreme): {cnt_pre}")
print(f"  + F1 (left_ext_5):     {cnt_f1}")
print(f"  + F2 (opp ∨ three):    {cnt_f2}")
print(f"  + F3 (body+wick):      {cnt_f3}   ← baseline")

df = pd.DataFrame(events)
conf = df["confirmed"].sum()
imp_caught = df[df["is_important"] & df["confirmed"]]
imp_total_in_baseline = df[df["is_important"]]

print(f"\n  Confirmed (Williams N=2): {conf} / {len(df)} = {conf/len(df)*100:.1f}%")
print(f"  Important pivots in baseline: {len(imp_total_in_baseline)} / 18")
print(f"  Important confirmed: {len(imp_caught)} / {len(imp_total_in_baseline)}")

# Direction breakdown
print(f"\n  By direction:")
for d in ("high", "low"):
    sub = df[df["direction"] == d]
    sub_conf = sub["confirmed"].sum()
    print(f"    {d}: {len(sub)} / conf {sub_conf} = {sub_conf/len(sub)*100:.1f}%")

# === Save ===
print(f"\n[5/5] Saving...")
df.to_parquet(OUT, index=False)
print(f"  → {OUT}")
print(f"\n  Columns: {list(df.columns)}")
