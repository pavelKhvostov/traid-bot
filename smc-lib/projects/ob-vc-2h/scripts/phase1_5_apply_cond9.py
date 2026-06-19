"""Phase 1.5 — apply condition #9 (FVG not consumed by first_fractal.confirmation_time).

Canon ~/smc-lib/elements/ob_vc/definition.md condition #9:
  Окно проверки: [fvg.c3.close_time, first_fractal.confirmation_time]
  LONG:  on 1m в окне, if min(low) ≤ fvg.zone_lo (= c1.high) → FVG consumed → invalid
  SHORT: on 1m в окне, if max(high) ≥ fvg.zone_hi (= c1.low) → FVG consumed → invalid
  Partial mitigation (low in (zone_lo, zone_hi]) → still valid
  Untouched → valid

Reads:  data/ob_vc_phase1.parquet
Writes: data/ob_vc_phase1_5.parquet (only rows passing #9)
        data/ob_vc_phase1_5_full.parquet (all rows with `cond9_pass` column)
"""
from __future__ import annotations
import sys, time, pathlib
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import DATA_DIR, ALL_HTFS, HTF_TO_LTF, load_1m


t0 = time.time()
print("=" * 78)
print("Phase 1.5 — apply condition #9 (1m wick-fill check)")
print("=" * 78)

df = pd.read_parquet(DATA_DIR / "ob_vc_phase1.parquet")
print(f"\nInput rows: {len(df):,}")

print("\nLoading 1m...")
rows_1m = load_1m()
t_arr = np.array([r[0] for r in rows_1m], dtype=np.int64)
h_arr = np.array([r[2] for r in rows_1m], dtype=np.float64)
l_arr = np.array([r[3] for r in rows_1m], dtype=np.float64)
print(f"  1m bars: {len(t_arr):,}")


# ─── Apply condition #9 row-by-row ─────────────────────────
print("\nChecking #9 on each row...")
cond9 = np.zeros(len(df), dtype=bool)
fvg_c3_close = df["fvg_c3_close_ms"].to_numpy(dtype=np.int64)
fract_confirm = df["fract_confirm_ms"].to_numpy(dtype=np.int64)
fvg_lo = df["fvg_zone_lo"].to_numpy(dtype=np.float64)
fvg_hi = df["fvg_zone_hi"].to_numpy(dtype=np.float64)
direction = df["direction"].to_numpy()

for k in range(len(df)):
    if k % 5000 == 0 and k > 0:
        print(f"  {k:,} / {len(df):,}")

    win_start = fvg_c3_close[k]
    win_end = fract_confirm[k]
    if win_end <= win_start:
        # FVG c3 closes at or after fractal confirms — no consumption window
        cond9[k] = True
        continue

    i_lo = int(np.searchsorted(t_arr, win_start))
    i_hi = int(np.searchsorted(t_arr, win_end, side="right"))
    if i_hi <= i_lo:
        cond9[k] = True
        continue

    if direction[k] == "long":
        # FVG consumed if any low ≤ fvg.zone_lo
        min_low = float(l_arr[i_lo:i_hi].min())
        cond9[k] = (min_low > fvg_lo[k])
    else:
        max_high = float(h_arr[i_lo:i_hi].max())
        cond9[k] = (max_high < fvg_hi[k])

print(f"  {len(df):,} / {len(df):,}  ✓")


# ─── Save outputs ──────────────────────────────────────────
df_full = df.copy()
df_full["cond9_pass"] = cond9
df_pass = df_full[df_full["cond9_pass"]].copy()

out_full = DATA_DIR / "ob_vc_phase1_5_full.parquet"
out_pass = DATA_DIR / "ob_vc_phase1_5.parquet"
df_full.to_parquet(out_full, index=False)
df_pass.to_parquet(out_pass, index=False)
print(f"\nSaved → {out_full.relative_to(pathlib.Path.home())}")
print(f"Saved → {out_pass.relative_to(pathlib.Path.home())}")


# ─── Report ────────────────────────────────────────────────
n_in = len(df)
n_pass = int(cond9.sum())
n_drop = n_in - n_pass

print(f"\n{'='*78}")
print(f"RESULTS — Condition #9 (FVG not consumed by 1m wick-fill)")
print(f"{'='*78}")
print(f"\nTotal:    {n_in:,}")
print(f"Pass #9:  {n_pass:,}  ({n_pass/n_in*100:.1f}%)")
print(f"Drop #9:  {n_drop:,}  ({n_drop/n_in*100:.1f}%)")


# Per HTF×LTF breakdown
print(f"\n{'='*78}")
print(f"PER (HTF, LTF) COMBO — #1-#8 vs #1-#9 (canonical)")
print(f"{'='*78}")
print(f"\n{'combo':<10} {'#1-#8':>8} {'#1-#9':>8} {'pass%':>7} {'drop':>6}")
print("-" * 50)
for htf in ALL_HTFS:
    for ltf in HTF_TO_LTF[htf]:
        g = df_full[(df_full.htf == htf) & (df_full.ltf == ltf)]
        n_total = len(g)
        if n_total == 0: continue
        n_p = int(g["cond9_pass"].sum())
        pct = n_p / n_total * 100
        print(f"{htf}/{ltf:<7} {n_total:>8,} {n_p:>8,} {pct:>6.1f}% {n_total-n_p:>6,}")


# Per HTF unique-OB recount
print(f"\n{'='*78}")
print(f"PER HTF — unique ob_vc instances (before vs after #9)")
print(f"{'='*78}")
print(f"\n{'htf':<5} {'OBs':>7} {'#1-#8':>8} {'rate':>6}   {'#1-#9':>8} {'rate':>6}   {'Δ':>5}")
print("-" * 70)

# Need plain OB counts from Phase 1 stdout — hardcoded for reference (could recompute)
plain_obs = {"3d":209, "2d":296, "1d":613, "12h":1200, "6h":2452,
             "4h":3611, "2h":7316, "1h":14255}

for htf in ALL_HTFS:
    g8 = df[df.htf == htf]
    g9 = df_pass[df_pass.htf == htf]
    u8 = g8.groupby(["direction", "ob_cur_open_ms"]).size().shape[0]
    u9 = g9.groupby(["direction", "ob_cur_open_ms"]).size().shape[0]
    n_obs = plain_obs.get(htf, 0)
    r8 = u8/n_obs*100 if n_obs else 0
    r9 = u9/n_obs*100 if n_obs else 0
    print(f"{htf:<5} {n_obs:>7,} {u8:>8,} {r8:>5.1f}%   {u9:>8,} {r9:>5.1f}%   "
          f"{u9-u8:>+5,}")


print(f"\nElapsed: {time.time() - t0:.1f}s")
