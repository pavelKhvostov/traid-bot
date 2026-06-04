"""V2: pivot's EXTREME must be IN cluster (not just candle range overlap).

Cluster center = mean of clustered maxV prices.
For pivot to "touch cluster":
  if direction == "high": |pivot.high - cluster_center| / cluster_center ≤ tol
  if direction == "low":  |pivot.low - cluster_center| / cluster_center ≤ tol

This is much stricter — pivot's actual reversal point coincides with maxV stack.
"""
from __future__ import annotations
import sys, csv
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.home() / "smc-lib"))
from indicators.vic_asvk import auto_ltf_minutes

MS_M = 60_000
TF_MIN = {"4h": 240, "6h": 360, "12h": 720, "1d": 1440, "2d": 2880, "3d": 4320}
TFS = list(TF_MIN.keys())
MON = int(datetime(2017, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
EPOCH = 0


def main():
    print("[1/3] Load maxV per TF (from cached parquet)...")
    df = pd.read_parquet(Path.home() / "Desktop" / "vic_maxv_per_tf.parquet")
    maxv_per_tf = {}
    for tf in TFS:
        sub = df[df["tf"] == tf].sort_values("ts_ms")
        maxv_per_tf[tf] = list(zip(sub["ts_ms"].astype("int64"), sub["maxV"].astype(float)))
        print(f"  {tf}: {len(maxv_per_tf[tf])} maxV")

    print("\n[2/3] Load baseline pivots...")
    df_base = pd.read_parquet(Path.home() / "Desktop/pred12h_baseline_c1c7.parquet")
    df_base["pivot_open_ts_ms"] = df_base["pivot_open_ts_ms"].astype("int64")

    # Need pivot's HIGH/LOW. Load 12h bars.
    CSV = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
    rows = []
    with CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

    def agg(rs, tf_ms, anchor=MON):
        out = []; cb = None; o = h = l = c = 0.0; v = 0.0
        for ts, oo, hh, ll, cc, vv in rs:
            b = ts - ((ts - anchor) % tf_ms)
            if b != cb:
                if cb is not None: out.append((cb, o, h, l, c, v))
                cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
            else:
                h = max(h, hh); l = min(l, ll); c = cc; v += vv
        if cb is not None: out.append((cb, o, h, l, c, v))
        return out

    bars12 = agg(rows, 720 * MS_M)
    ts12 = np.array([b[0] for b in bars12], dtype=np.int64)
    h12 = np.array([b[2] for b in bars12])
    l12 = np.array([b[3] for b in bars12])
    ts_to_idx = {int(t): i for i, t in enumerate(ts12)}

    pivot_data = []
    for _, p in df_base.iterrows():
        ts = int(p["pivot_open_ts_ms"])
        i = ts_to_idx.get(ts)
        if i is None: continue
        pivot_data.append({
            "ts": ts, "dir": p["direction"],
            "high": float(h12[i]), "low": float(l12[i]),
            "confirmed": bool(p["confirmed"]), "is_imp": bool(p["is_imp"]),
        })
    print(f"  pivots: {len(pivot_data)}")

    # Precompute available maxV per pivot ts
    base_p = sum(1 for p in pivot_data if p["confirmed"]) / len(pivot_data)
    print(f"  base P(W) = {base_p*100:.2f}%")

    # GRID
    TOLERANCES = [0.001, 0.002, 0.003, 0.005, 0.0075, 0.01]  # ±tol around pivot extreme
    LOOKBACKS = [5, 10, 20, 50, 200, 9999]
    K_MINS = [2, 3, 4]

    print(f"\n[3/3] Grid: {len(TOLERANCES)} × {len(LOOKBACKS)} × {len(K_MINS)} = "
          f"{len(TOLERANCES)*len(LOOKBACKS)*len(K_MINS)} combos × {len(pivot_data)} pivots")

    grid = []
    for tol in TOLERANCES:
        for lb in LOOKBACKS:
            for K in K_MINS:
                touched = touched_conf = touched_imp = 0
                for p in pivot_data:
                    pivot_extreme = p["high"] if p["dir"] == "high" else p["low"]
                    # Collect maxV from each TF, lookback last `lb` BEFORE p.ts
                    all_maxv = []
                    for tf in TFS:
                        arr = maxv_per_tf[tf]
                        # binary search for first index where ts >= p["ts"]
                        ts_arr = [a[0] for a in arr]
                        # use numpy
                        idx = np.searchsorted(np.array(ts_arr), p["ts"], side='left')
                        start = max(0, idx - lb)
                        for ts_mv, mv in arr[start:idx]:
                            if mv is not None and mv > 0:
                                all_maxv.append(mv)
                    if not all_maxv: continue
                    # Find maxV's within ±tol of pivot_extreme
                    near = [mv for mv in all_maxv if abs(mv - pivot_extreme) / pivot_extreme <= tol]
                    if len(near) >= K:
                        touched += 1
                        if p["confirmed"]: touched_conf += 1
                        if p["is_imp"]: touched_imp += 1
                p_w = touched_conf / touched if touched else 0
                grid.append({
                    "tol_pct": tol * 100, "lookback": lb, "K_min": K,
                    "touched": touched, "conf": touched_conf, "imp": touched_imp,
                    "P_W": p_w, "lift_pp": (p_w - base_p) * 100,
                })

    df_grid = pd.DataFrame(grid).sort_values(["P_W", "touched"], ascending=[False, False])
    out = Path.home() / "Desktop" / "vic_cluster_grid_v2.csv"
    df_grid.to_csv(out, index=False)

    print(f"\n=== Top 20 combos with ≥30 touches ===")
    print(df_grid[df_grid["touched"] >= 30].head(20).to_string(index=False))
    print(f"\n=== Top 10 combos with ≥100 touches ===")
    print(df_grid[df_grid["touched"] >= 100].head(10).to_string(index=False))
    print(f"\nGrid → {out}")


if __name__ == "__main__":
    main()
