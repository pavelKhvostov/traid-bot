"""
Empirical monotonic TF weight optimization для catching 22 user-target fractals.

Objective: max number of (SHORT targets FH в top-N of score_short) + (LONG targets FL в top-N of score_long).
Constraint: w_1h ≤ w_2h ≤ w_4h ≤ w_6h ≤ w_12h ≤ w_1d ≤ w_2d ≤ w_3d
Parameterization: w_i = w_{i-1} + softplus(δ_i)

force(candle, side) = Σ_zones tf_weight[z.tf] × p_pivot_z
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from data import load_btc_1m  # noqa: E402
from zones import precompute_zone_events, snapshot_from_events  # noqa: E402

from force_model_v3.dataset import (  # noqa: E402
    build_datasets, expand_to_cell_wise,
    SMC_TFS, TARGET_ELEMENTS,
    _extract_zone_features, _zone_in_short_region, _zone_in_long_region,
    _candle_context, _build_helpers,
)
from force_model_v3.regions import compute_regions  # noqa: E402
from force_model_v3.train import train_all  # noqa: E402
from force_model_v3 import features as F  # noqa: E402
from force_model_v3.labeling import label_williams_12h  # noqa: E402
from force_model_v3.targets_22 import SHORT_TARGETS, LONG_TARGETS, TARGETS_22_MSK  # noqa: E402


def extract_per_zone(df_1m_score, results, score_start, score_end):
    types_to_scan = list(TARGET_ELEMENTS) + ["ob_vc"]
    events, resampled = precompute_zone_events(df_1m_score, tfs=SMC_TFS, types=types_to_scan)
    helpers = _build_helpers(resampled)
    df_12h = resampled["12h"]
    labels = label_williams_12h(df_12h, n=2)
    atr_12h = helpers["12h"]["atr"]
    prior_trend = F.compute_prior_trend_slope(df_12h, F.PRIOR_TREND_BARS)

    score_mask = (labels.index >= score_start) & (labels.index < score_end) & labels["confirm_ts"].notna()
    sc, lc = [], []
    n_total = int(score_mask.sum())
    for k, (open_ts, row) in enumerate(labels.loc[score_mask].iterrows()):
        if k % 50 == 0 and k > 0:
            print(f"    {k}/{n_total} ...")
        regs = compute_regions(df_12h, open_ts)
        if regs is None or (not regs.has_short and not regs.has_long):
            continue
        atr12 = float(atr_12h.loc[open_ts]) if pd.notna(atr_12h.loc[open_ts]) else 0.0
        ptrend = float(prior_trend.loc[open_ts]) if open_ts in prior_trend.index else 0.0
        if atr12 <= 0 or not np.isfinite(ptrend):
            continue
        candle_ctx = _candle_context(row, atr12, ptrend)
        zs = [z for z in snapshot_from_events(events, resampled, df_1m_score, open_ts) if z.type in TARGET_ELEMENTS]
        liq_s = F.liquidity_count_in_region_short(resampled, open_ts, regs.short_lo, regs.short_hi) if regs.has_short else 0
        liq_l = F.liquidity_count_in_region_long(resampled, open_ts, regs.long_lo, regs.long_hi) if regs.has_long else 0

        sz, lz = [], []
        for z in zs:
            mr = results.get(z.type)
            if mr is None or mr.get("model") is None: continue
            in_s = regs.has_short and _zone_in_short_region(z, regs)
            in_l = regs.has_long and _zone_in_long_region(z, regs)
            if not in_s and not in_l: continue
            liq = liq_s if in_s else liq_l
            feats = _extract_zone_features(z, open_ts, resampled, helpers, events, candle_ctx, liq)
            if feats is None: continue
            feats["tf"] = z.tf; feats["target"] = 0; feats["candle_open_ts"] = open_ts; feats["side"] = "short" if in_s else "long"
            df_row = pd.DataFrame([feats])
            exp = expand_to_cell_wise(df_row, mr["feature_cols"], tfs=SMC_TFS)
            X = exp[mr["cell_cols"]].to_numpy()
            p = float(mr["model"].predict_proba(X)[0, 1])
            (sz if in_s else lz).append({"tf": z.tf, "p": p, "type": z.type})

        is_target_short = open_ts in SHORT_TARGETS
        is_target_long = open_ts in LONG_TARGETS

        if regs.has_short and sz:
            sc.append({"open_ts": open_ts, "is_target": is_target_short, "is_fh": bool(row["is_fh"]), "zones": sz})
        if regs.has_long and lz:
            lc.append({"open_ts": open_ts, "is_target": is_target_long, "is_fl": bool(row["is_fl"]), "zones": lz})
    return sc, lc


def score_candles(candles, weights):
    scores = []
    for c in candles:
        s = sum(weights.get(z["tf"], 0.0) * z["p"] for z in c["zones"])
        scores.append((s, c["open_ts"], c.get("is_target", False), c.get("is_fh", c.get("is_fl", False))))
    scores.sort(key=lambda x: -x[0])
    return scores


def hits_in_topN(scored, key_col="is_target", N=10):
    return sum(1 for _, _, target, _ in scored[:N] if target)


def parameterize_monotone(theta, tfs=SMC_TFS):
    softplus = lambda x: np.log1p(np.exp(np.clip(x, -50, 50)))
    w_arr = [softplus(theta[0])]
    for i in range(1, len(tfs)):
        w_arr.append(w_arr[-1] + softplus(theta[i]))
    return {tf: float(w) for tf, w in zip(tfs, w_arr)}


def hits_fh_fl(scored, N):
    """Count actual FH (for short) / FL (for long) in top-N. The 4th tuple element is is_fh/is_fl."""
    return sum(1 for _, _, _, is_pivot in scored[:N] if is_pivot)


def loss_fn(theta, sc, lc, top_n_main=20, top_n_ext=40):
    """Maximize OVERALL pivot win count в top-N: actual FH (short) + actual FL (long)."""
    w = parameterize_monotone(theta)
    s_sc = score_candles(sc, w)
    s_lc = score_candles(lc, w)
    # Total wins = sum of actual FH in top-N (short) + actual FL in top-N (long)
    s_t20 = hits_fh_fl(s_sc, N=top_n_main)
    l_t20 = hits_fh_fl(s_lc, N=top_n_main)
    s_t40 = hits_fh_fl(s_sc, N=top_n_ext)
    l_t40 = hits_fh_fl(s_lc, N=top_n_ext)
    score = 2.0 * (s_t20 + l_t20) + 0.5 * (s_t40 + l_t40)
    return -score


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--train-start", default="2025-01-01")
    p.add_argument("--train-end", default="2026-01-31")
    p.add_argument("--score-start", default="2026-02-01")
    p.add_argument("--score-end", default="2026-06-01")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--C", type=float, default=1.0)
    args = p.parse_args()

    train_start = pd.Timestamp(args.train_start, tz="UTC")
    train_end = pd.Timestamp(args.train_end, tz="UTC")
    score_start = pd.Timestamp(args.score_start, tz="UTC")
    score_end = pd.Timestamp(args.score_end, tz="UTC")

    print(f"22 targets loaded: {len(SHORT_TARGETS)} FH (short) + {len(LONG_TARGETS)} FL (long)")

    print(f"\n[1/4] Train on {train_start.date()}..{train_end.date()}")
    df_train = load_btc_1m(start=train_start, end=train_end)
    datasets, _ = build_datasets(df_train)
    results = train_all(datasets, C=args.C, test_split_ts=None)

    print(f"\n[2/4] Extract per-zone scores for {score_start.date()}..{score_end.date()}")
    df_score = load_btc_1m(start=train_start, end=score_end)
    sc, lc = extract_per_zone(df_score, results, score_start, score_end)
    print(f"  SHORT candles: {len(sc)}, LONG candles: {len(lc)}")
    n_target_short = sum(1 for c in sc if c["is_target"])
    n_target_long = sum(1 for c in lc if c["is_target"])
    print(f"  Targets in SHORT cohort: {n_target_short}/13  |  in LONG cohort: {n_target_long}/9")

    # Count total actual pivots in each cohort
    n_fh = sum(1 for c in sc if c["is_fh"])
    n_fl = sum(1 for c in lc if c["is_fl"])
    print(f"\n  Actual FH in SHORT cohort: {n_fh}  |  Actual FL in LONG cohort: {n_fl}")
    print(f"  (of which 22-targets: {n_target_short} FH + {n_target_long} FL)")

    print("\n[3/4] Baseline comparisons (wins = actual FH/FL caught in top-N):")
    def evaluate(name, weights):
        s_sc = score_candles(sc, weights)
        s_lc = score_candles(lc, weights)
        # Overall wins
        s_t10 = hits_fh_fl(s_sc, N=10); l_t10 = hits_fh_fl(s_lc, N=10)
        s_t20 = hits_fh_fl(s_sc, N=20); l_t20 = hits_fh_fl(s_lc, N=20)
        s_t30 = hits_fh_fl(s_sc, N=30); l_t30 = hits_fh_fl(s_lc, N=30)
        # 22-target catches
        s22 = hits_in_topN(s_sc, N=20); l22 = hits_in_topN(s_lc, N=20)
        print(f"  {name:<15} t10={s_t10+l_t10}/{n_fh+n_fl}  t20={s_t20+l_t20}/{n_fh+n_fl}  t30={s_t30+l_t30}  |  22-targets t20={s22+l22}/22")

    evaluate("uniform=1",  {tf: 1.0 for tf in SMC_TFS})
    evaluate("naive×hrs",  {"1h":1,"2h":2,"4h":4,"6h":6,"12h":12,"1d":24,"2d":48,"3d":72})
    evaluate("sqrt(hrs)",  {tf: float(np.sqrt(h)) for tf, h in zip(SMC_TFS, [1,2,4,6,12,24,48,72])})
    evaluate("log1p(hrs)", {tf: float(np.log1p(h)) for tf, h in zip(SMC_TFS, [1,2,4,6,12,24,48,72])})

    print("\n[4/4] Nelder-Mead optimization (multi-start)")
    best_neg = float("inf"); best_theta = None
    rng = np.random.default_rng(42)
    starts = [np.zeros(8), np.log(np.array([1,1.4,2,2.4,3.5,5,7,8.5])),
              np.log(np.array([1,1.1,1.3,1.5,2,3,4,5.0])),
              np.log(np.array([2,2,2,2,3,3,3,3.0]))]
    for _ in range(20):
        starts.append(rng.normal(0, 1.0, size=8))
    for i, t0 in enumerate(starts):
        res = minimize(loss_fn, t0, args=(sc, lc, args.top_n, args.top_n*2),
                       method="Nelder-Mead", options={"maxiter": 1000, "xatol": 1e-3, "fatol": 1e-2})
        if res.fun < best_neg:
            best_neg = res.fun; best_theta = res.x
            print(f"  start {i:2d}: improved to score={-res.fun:.2f}")

    best_w = parameterize_monotone(best_theta)
    min_w = min(best_w.values())
    norm_w = {tf: w/min_w for tf, w in best_w.items()}

    print("\n=== OPTIMAL TF weights (monotonic, normalized 1h=1) ===")
    for tf in SMC_TFS:
        print(f"  {tf:<3} | {norm_w[tf]:.3f}×")

    evaluate("OPTIMAL", best_w)

    # Show full ranking under OPTIMAL weights
    s_sc = score_candles(sc, best_w); s_lc = score_candles(lc, best_w)
    print(f"\n=== Top-30 SHORT under OPTIMAL (★ = 22-target, ✓ = actual FH) ===")
    for rank, (score, ts, target, is_fh) in enumerate(s_sc[:30], 1):
        m1 = "★" if target else " "
        m2 = "✓" if is_fh else " "
        msk = ts.tz_convert("Europe/Moscow").strftime("%Y-%m-%d %H:%M")
        print(f"  #{rank:2d}  {msk} MSK  score={score:.3f}  {m1}{m2}")

    print(f"\n=== Top-30 LONG under OPTIMAL ===")
    for rank, (score, ts, target, is_fl) in enumerate(s_lc[:30], 1):
        m1 = "★" if target else " "
        m2 = "✓" if is_fl else " "
        msk = ts.tz_convert("Europe/Moscow").strftime("%Y-%m-%d %H:%M")
        print(f"  #{rank:2d}  {msk} MSK  score={score:.3f}  {m1}{m2}")


if __name__ == "__main__":
    main()
