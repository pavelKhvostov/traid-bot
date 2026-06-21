"""Multi-TF maxV cluster grid search.

Pipeline:
1. Compute maxV per candle per TF in {4h, 6h, 12h, 1d, 2d, 3d} (6y BTC).
2. Grid search params: tolerance band × lookback × K_min cluster.
3. For each (toleration, lookback, K) combo:
   For each baseline pivot — does its high/low touch ANY cluster of K+ maxVs within tolerance?
   Compute P(W) lift vs base 48.7%.
4. Output: top 10 combos by precision (with min volume).

Canonical maxV (vic_asvk.py):
  bullV = Σvol bull LTF, bearV = Σvol bear LTF
  dominant = bull if bullV > bearV else bear
  maxV = close of LTF bar with max volume in dominant group

LTF auto-select:
  12h → 7m, 1d → 15m, 2d → 30m, 3d → 45m, 4h → 3m, 6h → 4m (~5m round)
"""
from __future__ import annotations
import sys, csv, math
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.home() / "smc-lib"))
sys.path.insert(0, str(Path.home() / "smc-lib" / "prediction-algo"))
from indicators.vic_asvk import auto_ltf_minutes

CSV = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_M = 60_000
TF_MIN = {"4h": 240, "6h": 360, "12h": 720, "1d": 1440, "2d": 2880, "3d": 4320}
TFS = list(TF_MIN.keys())
EPOCH_ANCHOR_MS = 0  # Unix epoch for 3D
MON_ANCHOR_MS = int(datetime(2017, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)


def load_1m():
    rows = []
    with CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def agg(rows_1m, tf_ms, anchor_ms=MON_ANCHOR_MS):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in rows_1m:
        b = ts - ((ts - anchor_ms) % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


def compute_maxv_for_tf(rows_1m, ts_1m, op_1m, cl_1m, vol_1m, tf_min):
    """Для каждой HTF свечи compute maxV (sided)."""
    tf_ms = tf_min * MS_M
    ltf_min = auto_ltf_minutes(tf_min)
    ltf_ms = ltf_min * MS_M
    anchor = EPOCH_ANCHOR_MS if tf_min == 4320 else MON_ANCHOR_MS

    # 1) aggregate to HTF
    htf_bars = agg(rows_1m, tf_ms, anchor)
    # 2) aggregate to LTF
    ltf_bars = agg(rows_1m, ltf_ms, anchor)
    ltf_ts = np.array([b[0] for b in ltf_bars], dtype=np.int64)

    maxv = []
    for hb in htf_bars:
        hb_start = hb[0]; hb_end = hb_start + tf_ms
        lo = int(np.searchsorted(ltf_ts, hb_start, side='left'))
        hi = int(np.searchsorted(ltf_ts, hb_end, side='left'))
        if hi <= lo:
            maxv.append({"ts": hb[0], "tf_min": tf_min, "maxV": None})
            continue
        sub = ltf_bars[lo:hi]
        bullV = sum(b[5] for b in sub if b[4] > b[1])
        bearV = sum(b[5] for b in sub if b[4] < b[1])
        if bullV == 0 and bearV == 0:
            maxv.append({"ts": hb[0], "tf_min": tf_min, "maxV": None}); continue
        dom = "bull" if bullV >= bearV else "bear"
        # max-vol LTF bar в dominant группе
        best = None; best_v = -1
        for b in sub:
            if (dom == "bull" and b[4] > b[1]) or (dom == "bear" and b[4] < b[1]):
                if b[5] > best_v:
                    best_v = b[5]; best = b
        mv = best[4] if best else None  # close of max-vol bar
        maxv.append({"ts": hb[0], "tf_min": tf_min, "maxV": mv, "dom": dom})
    return maxv


def main():
    print("[1/4] Loading 1m...")
    rows = load_1m()
    print(f"  {len(rows):,} rows")
    ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
    op_1m = np.array([r[1] for r in rows]); cl_1m = np.array([r[4] for r in rows])
    vol_1m = np.array([r[5] for r in rows])

    print("\n[2/4] Compute maxV per TF...")
    maxv_per_tf = {}
    for tf, tfm in TF_MIN.items():
        print(f"  {tf} (LTF auto={auto_ltf_minutes(tfm)}m)...", end=" ")
        mv = compute_maxv_for_tf(rows, ts_1m, op_1m, cl_1m, vol_1m, tfm)
        valid = [m for m in mv if m["maxV"] is not None]
        print(f"{len(valid)} maxV computed")
        maxv_per_tf[tf] = valid

    # Save raw maxV per TF
    all_rows = []
    for tf, lst in maxv_per_tf.items():
        for m in lst: all_rows.append({"ts_ms": m["ts"], "tf": tf, "maxV": m["maxV"]})
    df_maxv = pd.DataFrame(all_rows)
    out_maxv = Path.home() / "Desktop" / "vic_maxv_per_tf.parquet"
    df_maxv.to_parquet(out_maxv, index=False)
    print(f"  saved → {out_maxv}")

    print("\n[3/4] Load baseline pivots + grid search...")
    df_base = pd.read_parquet(Path.home() / "Desktop/pred12h_baseline_c1c7.parquet")
    df_base["pivot_open_ts"] = pd.to_datetime(df_base["pivot_open_ts_ms"], unit='ms', utc=True)
    print(f"  baseline pivots: {len(df_base)}, confirmed: {df_base['confirmed'].sum()}")

    # For each pivot, we need its bar high/low to check cluster touching
    # Use 1m data to get exact high/low (or 12h aggregation already)
    bars_12h = agg(rows, 720 * MS_M)
    ts12_arr = np.array([b[0] for b in bars_12h], dtype=np.int64)
    h12_arr = np.array([b[2] for b in bars_12h])
    l12_arr = np.array([b[3] for b in bars_12h])

    pivot_data = []
    for _, p in df_base.iterrows():
        ts = int(p["pivot_open_ts_ms"])
        idx = int(np.searchsorted(ts12_arr, ts, side='left'))
        if idx >= len(bars_12h) or ts12_arr[idx] != ts: continue
        pivot_data.append({
            "ts": ts, "pi": idx, "dir": p["direction"],
            "high": float(h12_arr[idx]), "low": float(l12_arr[idx]),
            "confirmed": bool(p["confirmed"]), "is_imp": bool(p["is_imp"]),
        })
    print(f"  matched pivots: {len(pivot_data)}")

    # Build maxV arrays sorted by ts per TF for fast lookback
    maxv_arr = {tf: sorted([(m["ts"], m["maxV"]) for m in lst], key=lambda x: x[0])
                for tf, lst in maxv_per_tf.items()}

    # Grid search
    TOLERANCES = [0.001, 0.0025, 0.005, 0.0075, 0.01, 0.015]  # ±0.1% ... ±1.5%
    LOOKBACKS = [5, 10, 20, 50, 200, 9999]  # N most recent maxV's per TF
    K_MINS = [2, 3, 4]

    print(f"\n[4/4] Grid search: {len(TOLERANCES)} × {len(LOOKBACKS)} × {len(K_MINS)} = "
          f"{len(TOLERANCES)*len(LOOKBACKS)*len(K_MINS)} combos × {len(pivot_data)} pivots")

    grid_results = []
    base_p = sum(1 for p in pivot_data if p["confirmed"]) / len(pivot_data)

    for tol in TOLERANCES:
        for lb in LOOKBACKS:
            for K in K_MINS:
                touched = 0; touched_conf = 0; touched_imp = 0
                for p in pivot_data:
                    # Get last `lb` maxV values per TF that were available BEFORE pivot.ts
                    all_maxv = []
                    for tf in TFS:
                        arr = maxv_arr[tf]
                        # Find idx of first maxV with ts >= pivot.ts (already closed bars)
                        cut = 0
                        for i, (mts, _) in enumerate(arr):
                            if mts >= p["ts"]: cut = i; break
                        else: cut = len(arr)
                        # Take last `lb` before cut
                        start = max(0, cut - lb)
                        for mts, mv in arr[start:cut]:
                            if mv is not None: all_maxv.append((tf, mts, mv))
                    if not all_maxv: continue
                    # Cluster detection within candle range [low - tol*low, high + tol*high]
                    lo_band = p["low"] * (1 - tol)
                    hi_band = p["high"] * (1 + tol)
                    in_band = [m for m in all_maxv if lo_band <= m[2] <= hi_band]
                    if not in_band: continue
                    # Group by price clusters: any K+ maxVs within ±tol of each other
                    prices = sorted([m[2] for m in in_band])
                    # sliding window check
                    cluster_found = False
                    for i in range(len(prices)):
                        # find max j such that prices[j] <= prices[i] * (1+tol)
                        for j in range(i, len(prices)):
                            if prices[j] > prices[i] * (1 + 2*tol):
                                break
                        else:
                            j = len(prices) - 1
                        if (j - i + 1) >= K:
                            cluster_found = True; break
                    if cluster_found:
                        touched += 1
                        if p["confirmed"]: touched_conf += 1
                        if p["is_imp"]: touched_imp += 1
                p_w = touched_conf / touched if touched else 0
                grid_results.append({
                    "tol_pct": tol * 100, "lookback": lb, "K_min": K,
                    "n_touched": touched, "n_conf": touched_conf, "n_imp": touched_imp,
                    "P_W": p_w, "lift_pp": (p_w - base_p) * 100,
                })

    df_grid = pd.DataFrame(grid_results)
    df_grid = df_grid.sort_values(["P_W", "n_touched"], ascending=[False, False]).reset_index(drop=True)
    out_grid = Path.home() / "Desktop" / "vic_cluster_grid.csv"
    df_grid.to_csv(out_grid, index=False)
    print(f"\nGrid → {out_grid}")
    print(f"\nBase P(W) = {base_p*100:.1f}%")
    print(f"\nTop 20 combos by P(W) (with ≥30 hits):")
    top = df_grid[df_grid["n_touched"] >= 30].head(20)
    print(top.to_string(index=False))


if __name__ == "__main__":
    main()
