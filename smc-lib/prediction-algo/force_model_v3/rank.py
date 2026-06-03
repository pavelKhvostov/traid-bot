"""
Rank top SHORT / LONG candles by aggregated force (sum of per-zone P-scores) over a window.

Usage:
    python3 -m force_model_v3.rank --train-end 2026-01-31 --score-start 2026-02-01 --score-end 2026-06-01 --top 10
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from data import load_btc_1m  # noqa: E402
from zones import precompute_zone_events, snapshot_from_events  # noqa: E402

from force_model_v3.dataset import (  # noqa: E402
    build_datasets, expand_to_cell_wise,
    SMC_TFS, TARGET_ELEMENTS, FEATURES,
    _extract_zone_features, _zone_in_short_region, _zone_in_long_region,
    _candle_context, _build_helpers,
)
from force_model_v3.regions import compute_regions  # noqa: E402
from force_model_v3.train import train_all  # noqa: E402
from force_model_v3 import features as F  # noqa: E402
from force_model_v3.labeling import label_williams_12h  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--train-start", default="2025-01-01")
    p.add_argument("--train-end", default="2026-01-31")
    p.add_argument("--score-start", default="2026-02-01")
    p.add_argument("--score-end", default="2026-06-01")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--C", type=float, default=1.0)
    args = p.parse_args()

    train_start = pd.Timestamp(args.train_start, tz="UTC")
    train_end = pd.Timestamp(args.train_end, tz="UTC")
    score_start = pd.Timestamp(args.score_start, tz="UTC")
    score_end = pd.Timestamp(args.score_end, tz="UTC")

    print(f"[1/3] Train model on {train_start.date()} .. {train_end.date()}")
    df_1m_train = load_btc_1m(start=train_start, end=train_end)
    datasets_train, _ = build_datasets(df_1m_train)
    results = train_all(datasets_train, C=args.C, test_split_ts=None)

    print(f"\n[2/3] Score candles {score_start.date()} .. {score_end.date()}")
    df_1m_score = load_btc_1m(start=train_start, end=score_end)
    types_to_scan = list(TARGET_ELEMENTS) + ["ob_vc"]
    events, resampled = precompute_zone_events(df_1m_score, tfs=SMC_TFS, types=types_to_scan)
    helpers = _build_helpers(resampled)

    df_12h = resampled["12h"]
    labels = label_williams_12h(df_12h, n=2)
    atr_12h = helpers["12h"]["atr"]
    prior_trend = F.compute_prior_trend_slope(df_12h, F.PRIOR_TREND_BARS)

    score_mask = (labels.index >= score_start) & (labels.index < score_end) & labels["confirm_ts"].notna()
    n_candles = int(score_mask.sum())
    print(f"    candles to score: {n_candles}")

    rows = []
    for k, (open_ts, row) in enumerate(labels.loc[score_mask].iterrows()):
        if k % 50 == 0 and k > 0:
            print(f"    {k}/{n_candles}")
        regs = compute_regions(df_12h, open_ts)
        if regs is None:
            continue
        if not regs.has_short and not regs.has_long:
            continue
        atr12 = float(atr_12h.loc[open_ts]) if pd.notna(atr_12h.loc[open_ts]) else 0.0
        ptrend = float(prior_trend.loc[open_ts]) if open_ts in prior_trend.index else 0.0
        if atr12 <= 0 or not np.isfinite(ptrend):
            continue
        candle_ctx = _candle_context(row, atr12, ptrend)

        zones_snapshot = [z for z in snapshot_from_events(events, resampled, df_1m_score, open_ts)
                          if z.type in TARGET_ELEMENTS]

        liq_short = F.liquidity_count_in_region_short(resampled, open_ts, regs.short_lo, regs.short_hi) if regs.has_short else 0
        liq_long = F.liquidity_count_in_region_long(resampled, open_ts, regs.long_lo, regs.long_hi) if regs.has_long else 0

        score_short = 0.0; n_short = 0
        score_long = 0.0;  n_long = 0

        for z in zones_snapshot:
            elem = z.type
            mr = results.get(elem)
            if mr is None or "model" not in mr or mr["model"] is None:
                continue
            in_short = regs.has_short and _zone_in_short_region(z, regs)
            in_long = regs.has_long and _zone_in_long_region(z, regs)
            if not in_short and not in_long:
                continue
            liq_for_zone = liq_short if in_short else liq_long
            feats = _extract_zone_features(z, open_ts, resampled, helpers, events, candle_ctx, liq_for_zone)
            if feats is None:
                continue
            feats["tf"] = z.tf
            feats["target"] = 0
            feats["candle_open_ts"] = open_ts
            feats["side"] = "short" if in_short else "long"
            df_row = pd.DataFrame([feats])
            exp = expand_to_cell_wise(df_row, mr["feature_cols"], tfs=SMC_TFS)
            X = exp[mr["cell_cols"]].to_numpy()
            p = float(mr["model"].predict_proba(X)[0, 1])
            if in_short:
                score_short += p; n_short += 1
            else:
                score_long += p; n_long += 1

        rows.append({
            "open_ts": open_ts,
            "msk": open_ts.tz_convert("Europe/Moscow").strftime("%Y-%m-%d %H:%M"),
            "O": float(row["open"]), "H": float(row["high"]), "L": float(row["low"]), "C": float(row["close"]),
            "is_fh": bool(row["is_fh"]), "is_fl": bool(row["is_fl"]),
            "has_short": regs.has_short, "has_long": regs.has_long,
            "short_width": (regs.short_hi - regs.short_lo) if regs.has_short else 0.0,
            "long_width": (regs.long_hi - regs.long_lo) if regs.has_long else 0.0,
            "n_short": n_short, "n_long": n_long,
            "score_short": score_short, "score_long": score_long,
        })

    print(f"\n[3/3] Top-{args.top} ranking\n")
    df = pd.DataFrame(rows)

    print(f"=== TOP {args.top} SHORT (highest sum P_FH from SHORT-region zones) ===")
    top_short = df[df["has_short"]].sort_values("score_short", ascending=False).head(args.top)
    cols_s = ["msk", "O", "H", "L", "C", "short_width", "n_short", "score_short", "is_fh"]
    print(top_short[cols_s].to_string(index=False))

    print(f"\n=== TOP {args.top} LONG (highest sum P_FL from LONG-region zones) ===")
    top_long = df[df["has_long"]].sort_values("score_long", ascending=False).head(args.top)
    cols_l = ["msk", "O", "H", "L", "C", "long_width", "n_long", "score_long", "is_fl"]
    print(top_long[cols_l].to_string(index=False))

    # Save
    out = Path.home() / "Desktop" / f"force_v3_ranking_{score_start.strftime('%Y%m%d')}.csv"
    df.to_csv(out, index=False)
    print(f"\nFull ranking → {out}")

    # Diagnostics
    if not df.empty:
        sh_hit_rate = float(df[df["has_short"]].sort_values("score_short", ascending=False).head(args.top)["is_fh"].mean())
        ln_hit_rate = float(df[df["has_long"]].sort_values("score_long", ascending=False).head(args.top)["is_fl"].mean())
        print(f"\nHit rate top-{args.top}:")
        print(f"  SHORT (is_FH actual): {sh_hit_rate*100:.1f}%  (baseline {df['is_fh'].mean()*100:.1f}%)")
        print(f"  LONG (is_FL actual):  {ln_hit_rate*100:.1f}%  (baseline {df['is_fl'].mean()*100:.1f}%)")


if __name__ == "__main__":
    main()
