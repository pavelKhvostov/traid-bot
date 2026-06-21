"""bb_dataset Phase 2 builder.

Для каждой ob_vc(1h, 2h) зоны:
  - извлекает 106 SMC-context фичей через smc_context.extract_features
  - симулирует etap108-сделку через strategy_1_1_1_floating.simulate_floating
  - вычисляет два label:
      bb_label   — bounce(0) / break(1) — close-based (как в v1 MVP)
      trade_label — win(1) / loss(0) — наш target

Output:  ~/Desktop/bb_obvc_1h2h_v2.parquet (~6683 rows × ~115 cols)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path.home() / "smc-lib"
TRAID_BOT = Path.home() / "traid-bot"
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "projects"))
sys.path.insert(0, str(SMC_LIB / "projects" / "bb_dataset"))
sys.path.insert(0, str(SMC_LIB / "strategies" / "strategy_1_1_1"))
sys.path.insert(0, str(SMC_LIB / "strategies" / "strategy_1_1_1" / "strategy_ob_vc_v1rules"))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))
sys.path.insert(0, str(TRAID_BOT))

from data import load_btc_1m
from zones import precompute_zone_events, ALL_TYPES
from strategy_1_1_1_floating import simulate_floating, build_score_series, FLOATING_TP_CONFIG
from backtest import scan_ob_vc_events, HTFS  # from strategy_ob_vc_v1rules/
from smc_context import extract_features, SMC_TFS


OUT_PATH = Path.home() / "Desktop" / "bb_obvc_1h2h_v2.parquet"


def main():
    t0 = time.time()

    # 1) Load 1m
    print("[bb-v2] loading 1m BTC...")
    df_1m = load_btc_1m()
    print(f"  {len(df_1m):,} bars, range {df_1m.index[0]} -> {df_1m.index[-1]}")

    # 2) Precompute zone events on 9 TFs × 10 types (one-shot, ~3-5 min)
    print(f"[bb-v2] precomputing zone events on {len(SMC_TFS)} TFs × {len(ALL_TYPES)} types...")
    t1 = time.time()
    events_by_tf_type, resampled = precompute_zone_events(
        df_1m, tfs=SMC_TFS, types=ALL_TYPES,
    )
    print(f"  done in {(time.time()-t1)/60:.1f} min, {len(events_by_tf_type)} (tf,type) keys")

    # 3) Scan ob_vc events using existing helper
    all_events = []
    for htf in HTFS:
        print(f"[bb-v2] scanning ob_vc HTF={htf}...")
        events = scan_ob_vc_events(resampled, df_1m, htf)
        all_events.extend(events)
    print(f"  total ob_vc events: {len(all_events)}")

    # 4) Compute 4-indicator momentum score on 1h (needed for simulate_floating)
    print("[bb-v2] building 4-indicator score series on 1h...")
    t1 = time.time()
    score_long, score_short = build_score_series(resampled["1h"])
    print(f"  done in {time.time()-t1:.1f}s")

    cfg = FLOATING_TP_CONFIG["BTCUSDT"]
    print(f"[bb-v2] simulator config: {cfg}")

    # 5) Per-event: features + trade-outcome label + bb_label
    out_rows = []
    n_no_features = 0
    n_no_trade = 0
    t1 = time.time()
    for i, ev in enumerate(all_events):
        # Trade-outcome label via simulator
        result = simulate_floating(
            ev, df_1m, resampled["1h"], score_long, score_short,
            R_cap=cfg["R_cap"], threshold=cfg["threshold"], confirm=cfg["confirm"],
        )
        # Features
        try:
            feats = extract_features(ev, events_by_tf_type, resampled, df_1m)
        except Exception as e:
            n_no_features += 1
            if n_no_features < 5:
                print(f"  feat err event {i}: {e}")
            continue
        if not feats:
            n_no_features += 1
            continue

        trade_label = -1
        if result is not None and result.outcome in ("win", "loss", "flat"):
            trade_label = 1 if result.R > 0 else 0
        else:
            n_no_trade += 1

        # bb_label (bounce/break) — we already have it from v1 builder? Skip for now,
        # focus on trade_label
        out_rows.append({
            "signal_time": ev["signal_time"],
            "tf": ev["ob_htf_tf"],
            "direction": ev["direction"],
            "fvg_tf": ev["fvg_tf"],
            "ob_lo": ev["ob_htf_zone"][0],
            "ob_hi": ev["ob_htf_zone"][1],
            "trade_label": trade_label,
            "trade_R": float(result.R) if result is not None else np.nan,
            "exit_reason": result.exit_reason if result is not None else "no_result",
            "outcome": result.outcome if result is not None else "no_result",
            **feats,
        })

        if (i + 1) % 500 == 0:
            elapsed = time.time() - t1
            eta = elapsed / (i + 1) * (len(all_events) - i - 1)
            print(f"  [{i+1}/{len(all_events)}] elapsed {elapsed/60:.1f}m, ETA {eta/60:.1f}m, n_no_trade={n_no_trade}")

    df_out = pd.DataFrame(out_rows)
    print(f"\n[bb-v2] final: {len(df_out)} rows × {len(df_out.columns)} cols")
    print(f"  dropped: no_features={n_no_features}, no_trade={n_no_trade}")
    if len(df_out) > 0:
        valid = df_out[df_out["trade_label"] >= 0]
        print(f"  valid trade labels: {len(valid)}")
        print(f"  trade_label distribution: wins={(valid['trade_label']==1).sum()}, losses={(valid['trade_label']==0).sum()}")
        print(f"  WR base: {(valid['trade_label']==1).mean()*100:.1f}%")

    df_out.to_parquet(OUT_PATH, engine="pyarrow", compression="zstd", index=False)
    print(f"\n[bb-v2] saved to {OUT_PATH}")
    print(f"[bb-v2] TOTAL TIME: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
