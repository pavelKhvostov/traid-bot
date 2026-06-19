"""TBM v2 — full excursion tracking + multi-RR labels + R% filter + entry delay.

For each ob_vc event:
  - Read 1m bars from born_ms to born_ms + 14d
  - Find first entry-touch (LONG: low<=entry; SHORT: high>=entry)
  - Track MFE (max favorable excursion in R units) until SL hit OR horizon end
  - Track MAE (max adverse excursion in R units)
  - Compute time_to_mfe (minutes after entry-touch)
  - Derive binary labels hit_RR_X for RR in [1.4, 1.5, 1.7, 2.0, 2.3, 2.5, 2.8]
  - Compute r_pct = R/entry × 100 (futures viability filter)
  - Compute fill_delay = time from born to first entry-touch

Output columns added to events:
  fill_delay_min       — minutes from born_ms to entry-touch (NaN if not touched)
  fill_touched         — bool
  mfe_R, mae_R         — max excursions in R units (NaN if not touched)
  time_to_mfe_min      — when MFE peaked
  sl_hit               — bool: did SL trigger
  exit_reason          — 'sl' | 'horizon' | 'no_touch'
  hit_RR_{14..28}      — binary: did MFE reach this RR
  max_RR               — same as mfe_R, redundant name for clarity
  r_pct                — R / entry × 100 in percent
  r_pct_pass           — bool: r_pct >= 0.5 (futures viable)
"""
from __future__ import annotations
import csv
import pathlib
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc")
OUT = REPO / "ml_v2" / "labels_v2.parquet"

HORIZON_MS = 14 * 24 * 3600 * 1000   # 14 days TBM horizon
RR_GRID = [1.4, 1.5, 1.7, 2.0, 2.3, 2.5, 2.8]
R_PCT_THRESHOLD = 0.5   # futures viability: 0.5% min movement entry→SL


def load_1m(symbol: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (ts_ms, high, low) numpy arrays for 1m bars."""
    path = pathlib.Path.home() / f"traid-bot/data/{symbol}_1m_vic_vadim.csv"
    ts, h, l = [], [], []
    with path.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            ts.append(t)
            h.append(float(r[2]))
            l.append(float(r[3]))
    return (np.array(ts, dtype=np.int64),
            np.array(h, dtype=np.float64),
            np.array(l, dtype=np.float64))


def tbm_excursion(direction: str, entry: float, sl: float, born_ms: int,
                   ts_1m: np.ndarray, h_1m: np.ndarray, l_1m: np.ndarray) -> dict:
    """Full excursion tracking for one event.

    Returns dict:
      fill_delay_min, fill_touched, mfe_R, mae_R, time_to_mfe_min,
      sl_hit, exit_reason
    """
    if direction == "long":
        R = entry - sl
        if R <= 0:
            return {"fill_touched": False, "exit_reason": "no_touch"}
    else:
        R = sl - entry
        if R <= 0:
            return {"fill_touched": False, "exit_reason": "no_touch"}

    i_start = int(np.searchsorted(ts_1m, born_ms, side="left"))
    if i_start >= len(ts_1m):
        return {"fill_touched": False, "exit_reason": "no_touch"}
    i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS, side="right")) - 1)
    if i_end <= i_start:
        return {"fill_touched": False, "exit_reason": "no_touch"}

    # Find first entry touch
    if direction == "long":
        win_l = l_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(win_l <= entry)) if (win_l <= entry).any() else -1
    else:
        win_h = h_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(win_h >= entry)) if (win_h >= entry).any() else -1

    if touch_rel == -1:
        return {"fill_touched": False, "exit_reason": "no_touch"}

    touch_idx = i_start + touch_rel
    fill_delay_min = (ts_1m[touch_idx] - born_ms) / 60_000

    # Track post-entry excursion until SL hit or horizon end
    post_h = h_1m[touch_idx:i_end+1]
    post_l = l_1m[touch_idx:i_end+1]
    post_ts = ts_1m[touch_idx:i_end+1]

    if direction == "long":
        sl_arr = (post_l <= sl)
        sl_rel = int(np.argmax(sl_arr)) if sl_arr.any() else -1
        if sl_rel == -1:
            # No SL hit — use entire horizon
            track_h = post_h
            track_l = post_l
            track_ts = post_ts
            sl_hit = False
            exit_reason = "horizon"
        else:
            # Cut at SL hit
            track_h = post_h[:sl_rel + 1]
            track_l = post_l[:sl_rel + 1]
            track_ts = post_ts[:sl_rel + 1]
            sl_hit = True
            exit_reason = "sl"
        if len(track_h) == 0:
            mfe_R = 0.0; mae_R = 0.0; time_to_mfe_min = 0.0
        else:
            max_h = track_h.max()
            min_l = track_l.min()
            mfe_R = (max_h - entry) / R
            mae_R = (entry - min_l) / R
            mfe_idx = int(np.argmax(track_h))
            time_to_mfe_min = (track_ts[mfe_idx] - post_ts[0]) / 60_000
    else:  # short
        sl_arr = (post_h >= sl)
        sl_rel = int(np.argmax(sl_arr)) if sl_arr.any() else -1
        if sl_rel == -1:
            track_h = post_h
            track_l = post_l
            track_ts = post_ts
            sl_hit = False
            exit_reason = "horizon"
        else:
            track_h = post_h[:sl_rel + 1]
            track_l = post_l[:sl_rel + 1]
            track_ts = post_ts[:sl_rel + 1]
            sl_hit = True
            exit_reason = "sl"
        if len(track_h) == 0:
            mfe_R = 0.0; mae_R = 0.0; time_to_mfe_min = 0.0
        else:
            min_l = track_l.min()
            max_h = track_h.max()
            mfe_R = (entry - min_l) / R
            mae_R = (max_h - entry) / R
            mfe_idx = int(np.argmin(track_l))
            time_to_mfe_min = (track_ts[mfe_idx] - post_ts[0]) / 60_000

    return {
        "fill_touched": True,
        "fill_delay_min": fill_delay_min,
        "mfe_R": mfe_R,
        "mae_R": mae_R,
        "time_to_mfe_min": time_to_mfe_min,
        "sl_hit": sl_hit,
        "exit_reason": exit_reason,
    }


def process_asset(symbol: str) -> pd.DataFrame:
    print(f"\n[{symbol}] loading events...")
    events = pd.read_parquet(REPO / "data" / f"{symbol}_2h_24types.parquet")
    print(f"[{symbol}] events: {len(events):,}")

    print(f"[{symbol}] loading 1m bars...")
    t0 = time.time()
    ts_1m, h_1m, l_1m = load_1m(symbol)
    print(f"[{symbol}] 1m bars: {len(ts_1m):,}  ({time.time()-t0:.1f}s)")

    print(f"[{symbol}] computing TBM v2 excursions...")
    t0 = time.time()
    out_rows = []
    for i, row in events.iterrows():
        if i % 1000 == 0 and i > 0:
            print(f"  {i:,} / {len(events):,}  ({time.time()-t0:.0f}s)")
        direction = row["direction"]
        entry = float(row["entry"])
        # SL = drop_lo for long, drop_hi for short
        sl = float(row["drop_lo"]) if direction == "long" else float(row["drop_hi"])
        born_ms = int(row["born_ms"])
        result = tbm_excursion(direction, entry, sl, born_ms, ts_1m, h_1m, l_1m)
        out_rows.append(result)
    print(f"  {len(events):,} / {len(events):,}  ({time.time()-t0:.0f}s)")

    out = pd.DataFrame(out_rows)

    # Multi-RR binary labels
    for rr in RR_GRID:
        col = f"hit_RR_{int(rr*10):02d}"
        out[col] = (out["mfe_R"] >= rr).fillna(False).astype(int)
    out["max_RR"] = out["mfe_R"]

    # R% futures viability filter
    r_pct = events["R"].astype(float) / events["entry"].astype(float) * 100
    out["r_pct"] = r_pct.values
    out["r_pct_pass"] = (r_pct >= R_PCT_THRESHOLD).values

    # Combine with events meta
    keep_event_cols = ["t_id", "direction", "extreme", "ltf", "n_comp",
                        "born_ms", "cur_open_ms", "cur_close_ms",
                        "fvg_zone_lo", "fvg_zone_hi", "drop_lo", "drop_hi",
                        "entry", "R", "touched", "outcome"]
    final = pd.concat([events[keep_event_cols].reset_index(drop=True),
                        out.reset_index(drop=True)], axis=1)
    final["asset"] = symbol[:3]
    final["event_id"] = final["asset"] + "_" + final.index.astype(str).str.zfill(6)
    return final


def main():
    t_total = time.time()
    parts = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        parts.append(process_asset(sym))
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(OUT, index=False)
    print(f"\n[done] saved -> {OUT}")
    print(f"[done] total events: {len(df):,}  ({time.time()-t_total:.0f}s)")
    print()

    # Diagnostic
    print("=" * 72)
    print("Diagnostic")
    print("=" * 72)
    print(f"\nFill statistics:")
    print(f"  touched: {df.fill_touched.sum():,} / {len(df):,} ({df.fill_touched.mean()*100:.1f}%)")
    if df.fill_touched.any():
        fd = df.loc[df.fill_touched, "fill_delay_min"].dropna()
        print(f"  fill_delay_min: median={fd.median():.0f}  p10={fd.quantile(0.1):.0f}  p90={fd.quantile(0.9):.0f}")
        print(f"  fill_delay distribution:")
        for q in [0.25, 0.5, 0.75, 0.9, 0.95]:
            print(f"    p{int(q*100)}: {fd.quantile(q):.0f} min")

    print(f"\nR% (futures viability):")
    print(f"  median R%: {df.r_pct.median():.3f}%")
    print(f"  r_pct >= 0.5%: {df.r_pct_pass.sum():,} / {len(df):,} ({df.r_pct_pass.mean()*100:.1f}%)")
    print(f"  r_pct < 0.5%:  {(~df.r_pct_pass).sum():,} ({(~df.r_pct_pass).mean()*100:.1f}%)")

    print(f"\nExit reasons:")
    print(df.exit_reason.value_counts().to_string())

    print(f"\nMFE distribution (touched events only):")
    mfe = df.loc[df.fill_touched, "mfe_R"].dropna()
    if len(mfe):
        print(f"  median MFE: {mfe.median():.2f}R")
        print(f"  p10/p25/p50/p75/p90/p95: "
              f"{mfe.quantile(0.10):.2f} / {mfe.quantile(0.25):.2f} / "
              f"{mfe.quantile(0.50):.2f} / {mfe.quantile(0.75):.2f} / "
              f"{mfe.quantile(0.90):.2f} / {mfe.quantile(0.95):.2f}")

    print(f"\nHit-rate per RR (touched events only):")
    print(f"  {'RR':<6} {'hit':>6} {'%':>8} {'%_with_r_pct_pass':>20}")
    print("  " + "-" * 45)
    touched_mask = df.fill_touched
    pass_mask = df.r_pct_pass
    for rr in RR_GRID:
        col = f"hit_RR_{int(rr*10):02d}"
        hit = df.loc[touched_mask, col].sum()
        pct = hit / touched_mask.sum() * 100
        # With R% filter
        hit_filt = df.loc[touched_mask & pass_mask, col].sum()
        pct_filt = hit_filt / max(1, (touched_mask & pass_mask).sum()) * 100
        print(f"  {rr:<6.1f} {hit:>6,} {pct:>7.1f}% {pct_filt:>19.1f}%")

    print(f"\nExpected R per RR (touched only, no R% filter):")
    print(f"  {'RR':<6} {'WR%':>6} {'E[R]':>8}")
    print("  " + "-" * 25)
    for rr in RR_GRID:
        col = f"hit_RR_{int(rr*10):02d}"
        wins = df.loc[touched_mask, col].sum()
        losses = touched_mask.sum() - wins
        n = touched_mask.sum()
        wr = wins / n * 100
        # E[R] = WR × RR - (1-WR) × 1 (loss = -1R if SL hit)
        e_r = (wins * rr - losses * 1) / n
        print(f"  {rr:<6.1f} {wr:>5.1f}% {e_r:>+7.3f}R")


if __name__ == "__main__":
    main()
