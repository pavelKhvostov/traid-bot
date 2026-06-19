"""SOL baseline at RR=2.0 — applies same TBM as BTC+ETH dataset to enable v3.3 comparison.

For each touched ob_vc:
  - Walk 1m bars from entry touch
  - Find first TP at +2R or SL at -1R
  - Compute mfe_R, mae_R, hit_RR_14/15/17/20/23/25/28

Reports per-type WR at RR=2.0 + total SOL baseline (no ML filter).
"""
from __future__ import annotations
import csv
import pathlib
from datetime import datetime, timezone

import numpy as np
import pandas as pd


SOL_CSV = pathlib.Path.home() / "traid-bot/data/SOLUSDT_1m_vic_vadim.csv"
SOL_PARQUET = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/data/SOLUSDT_2h_24types.parquet")
OUT_PARQUET = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/data/SOLUSDT_2h_24types_full_tbm.parquet")

HORIZON_MS = 14 * 24 * 3600 * 1000
RR_TARGETS = [1.4, 1.5, 1.7, 2.0, 2.3, 2.5, 2.8]


def load_1m():
    rows = []
    with SOL_CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def main():
    print("Loading SOL 1m...")
    rows = load_1m()
    ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
    h_1m = np.array([r[2] for r in rows], dtype=np.float64)
    l_1m = np.array([r[3] for r in rows], dtype=np.float64)
    print(f"  1m bars: {len(rows):,}")

    df = pd.read_parquet(SOL_PARQUET)
    print(f"SOL ob_vc events: {len(df):,}")
    print(f"  touched: {df.touched.sum():,} ({df.touched.mean()*100:.1f}%)")

    # Filter to touched events with valid entry/R
    sub = df[df.touched & df.entry.notna() & df.R.notna()].copy().reset_index(drop=True)
    print(f"  viable for TBM: {len(sub):,}")

    # Compute mfe/mae + hit_RR labels per event
    print("\nComputing TBM at multi-RR per event...")
    results = []
    for i, row in sub.iterrows():
        if i % 500 == 0 and i > 0:
            print(f"  {i}/{len(sub)}...")
        direction = row.direction
        entry = float(row.entry)
        R = float(row.R)
        born_ms = int(row.born_ms)
        if direction == "long":
            sl = entry - R
        else:
            sl = entry + R

        # Find touch index — when price first touches entry
        i_start = int(np.searchsorted(ts_1m, born_ms))
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        if i_start >= i_end:
            results.append({**row.to_dict(), "mfe_R": np.nan, "mae_R": np.nan, "sl_hit": False})
            continue

        slice_l = l_1m[i_start:i_end+1]
        slice_h = h_1m[i_start:i_end+1]

        if direction == "long":
            touch_arr = slice_l <= entry
            if not touch_arr.any():
                results.append({**row.to_dict(), "mfe_R": np.nan, "mae_R": np.nan, "sl_hit": False})
                continue
            touch_rel = int(np.argmax(touch_arr))
        else:
            touch_arr = slice_h >= entry
            if not touch_arr.any():
                results.append({**row.to_dict(), "mfe_R": np.nan, "mae_R": np.nan, "sl_hit": False})
                continue
            touch_rel = int(np.argmax(touch_arr))

        touch_idx = i_start + touch_rel
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]

        # Find sl_hit position
        if direction == "long":
            sl_arr = post_l <= sl
            sl_rel = int(np.argmax(sl_arr)) if sl_arr.any() else -1
        else:
            sl_arr = post_h >= sl
            sl_rel = int(np.argmax(sl_arr)) if sl_arr.any() else -1

        # Compute MFE: max favorable BEFORE sl_hit (or full window if no sl_hit)
        if sl_rel == -1:
            track_h = post_h
            track_l = post_l
            sl_hit = False
        else:
            track_h = post_h[:sl_rel+1]
            track_l = post_l[:sl_rel+1]
            sl_hit = True

        if direction == "long":
            max_high = float(track_h.max())
            min_low = float(track_l.min())
            mfe_R = (max_high - entry) / R
            mae_R = (entry - min_low) / R
        else:
            max_high = float(track_h.max())
            min_low = float(track_l.min())
            mfe_R = (entry - min_low) / R
            mae_R = (max_high - entry) / R

        rec = {**row.to_dict(), "mfe_R": mfe_R, "mae_R": mae_R, "sl_hit": bool(sl_hit)}
        for rr in RR_TARGETS:
            rec[f"hit_RR_{int(rr*10):02d}"] = int(mfe_R >= rr)
        results.append(rec)

    out = pd.DataFrame(results)
    out.to_parquet(OUT_PARQUET, index=False)
    print(f"\nSaved: {OUT_PARQUET}")

    # ─── Stats baseline at RR=2.0 (NO ML filter) ─────
    print("\n" + "=" * 72)
    print("SOL BASELINE at RR=2.0 (all touched events, no ML)")
    print("=" * 72)
    valid = out.dropna(subset=["mfe_R"]).copy()
    valid["y_true_20"] = valid.hit_RR_20.astype(int)
    valid["r_pct"] = valid.R / valid.entry * 100

    print(f"\nTotal touched events: {len(valid):,}")
    print(f"WR @ RR=2.0:         {valid.y_true_20.mean()*100:.1f}%")
    Σ = valid.y_true_20.sum() * 2.0 - (1 - valid.y_true_20).sum() * 1.0
    print(f"Σ R @ RR=2.0:        {Σ:+.0f}R")

    print("\n── By RR target ──")
    for rr in RR_TARGETS:
        col = f"hit_RR_{int(rr*10):02d}"
        wr = valid[col].mean() * 100
        Σ_rr = valid[col].sum() * rr - (1 - valid[col]).sum() * 1.0
        print(f"  RR={rr:.1f}:  WR={wr:.1f}%, Σ R={Σ_rr:+.0f}R, E[R]={Σ_rr/len(valid):+.3f}R")

    print("\n── By asset comparison ──")
    # BTC + ETH baseline (from features_v33_picked)
    btc_eth = pd.read_parquet("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v33_picked.parquet")
    btc_eth_f = btc_eth[btc_eth.fill_touched & btc_eth.r_pct_pass].reset_index(drop=True)
    for asset_label, sub_df in [("BTC", btc_eth_f[btc_eth_f.asset == "BTC"]),
                                  ("ETH", btc_eth_f[btc_eth_f.asset == "ETH"]),
                                  ("SOL", valid)]:
        n = len(sub_df)
        wr = sub_df.hit_RR_20.mean() * 100
        Σ = sub_df.hit_RR_20.sum() * 2.0 - (n - sub_df.hit_RR_20.sum()) * 1.0
        print(f"  {asset_label}: N={n:,}, WR={wr:.1f}%, Σ R={Σ:+.0f}R, E[R]={Σ/n:+.3f}R")

    print("\n── SOL per-type @ RR=2.0 ──")
    T_ORDER = ["T1a","T1b","T2","T3a","T3b","T4","T5a","T5b","T6","T7a","T7b","T8",
                "T9a","T9b","T10","T11a","T11b","T12","T13a","T13b","T14","T15a","T15b","T16"]
    print(f"{'T':<6} {'N':>5} {'WR%':>6} {'EV':>10} {'ΣR':>7}")
    for t in T_ORDER:
        g = valid[valid.t_id == t]
        n = len(g)
        if n == 0:
            print(f"{t:<6} {0:>5}")
            continue
        wr = g.hit_RR_20.mean() * 100
        ev = wr/100 * 2.0 - (1 - wr/100) * 1.0
        Σ = g.hit_RR_20.sum() * 2.0 - (n - g.hit_RR_20.sum())
        print(f"{t:<6} {n:>5} {wr:>5.1f}% {ev:>+7.3f}R {Σ:>+5.0f}R")


if __name__ == "__main__":
    main()
