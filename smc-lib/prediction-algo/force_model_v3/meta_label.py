"""
Meta-labeling Lopez de Prado Ch 3.6 поверх force-model v3.

Архитектура:
  Primary = force-model v3 (per-candle score_short / score_long)
  Secondary = бинарный classifier на NEW features
  Combined = primary_score × secondary_P(actual_pivot)

Цель: уменьшить false positives primary через meta-classifier,
повысить precision топ-N без падения recall.

Новые features (НЕ дублируют v3):
  - proximity_weighted_score: per-zone score, взвешенный по dist_pct (ближе к high → больше)
  - htf_zone_share: доля HTF-зон (1d+2d+3d) от всех в region
  - cumulative_move_atr: |close[t] - close[t-N]| / ATR за N=10 баров до
  - compression_ratio: ATR(N=5) / ATR(N=30) — низкий = compression перед взрывом
  - candle_session: 1 (00-12 UTC) / 0 (12-24 UTC) — простая бинарка
  - max_zone_score: max per-zone p_pivot в region (vs average — позволит сильному impulse доминировать)
  - n_zones_normalized: count / region_width_atr
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, precision_recall_curve

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
from force_model_v3.targets_22 import SHORT_TARGETS, LONG_TARGETS  # noqa: E402

HTF_TFS = ("1d", "2d", "3d")


def extract_full_candidates(df_1m_score, results, score_start, score_end):
    """Returns DataFrame with one row per candle, with v3 scores + meta-features + labels."""
    types_to_scan = list(TARGET_ELEMENTS) + ["ob_vc"]
    events, resampled = precompute_zone_events(df_1m_score, tfs=SMC_TFS, types=types_to_scan)
    helpers = _build_helpers(resampled)
    df_12h = resampled["12h"]
    labels = label_williams_12h(df_12h, n=2)
    atr_12h = helpers["12h"]["atr"]
    prior_trend = F.compute_prior_trend_slope(df_12h, F.PRIOR_TREND_BARS)

    score_mask = (labels.index >= score_start) & (labels.index < score_end) & labels["confirm_ts"].notna()
    rows = []
    n_total = int(score_mask.sum())
    for k, (open_ts, row) in enumerate(labels.loc[score_mask].iterrows()):
        if k % 50 == 0 and k > 0:
            print(f"    {k}/{n_total}")
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

        # === Meta-features (NEW, не в v3) ===
        # Cumulative move before — trend exhaustion proxy
        idx_in_12h = df_12h.index.get_loc(open_ts)
        N_back = 10
        if idx_in_12h >= N_back:
            close_now = float(df_12h["close"].iloc[idx_in_12h - 1])  # prior close
            close_back = float(df_12h["close"].iloc[idx_in_12h - N_back - 1])
            cum_move_atr = abs(close_now - close_back) / atr12 if atr12 > 0 else 0.0
        else:
            cum_move_atr = 0.0

        # Compression ratio
        atr_short = float(atr_12h.iloc[idx_in_12h - 1]) if idx_in_12h >= 1 and pd.notna(atr_12h.iloc[idx_in_12h - 1]) else atr12
        atr_long_idx = max(0, idx_in_12h - 30)
        atr_long_vals = atr_12h.iloc[atr_long_idx:idx_in_12h].dropna()
        atr_long = float(atr_long_vals.mean()) if len(atr_long_vals) > 0 else atr12
        compression = atr_short / atr_long if atr_long > 0 else 1.0

        # Session
        session = int(open_ts.hour < 12)  # 00:00 UTC = 1, 12:00 UTC = 0

        # SHORT side score + features
        if regs.has_short:
            short_zs = [z for z in zs if _zone_in_short_region(z, regs)]
            short_p_pivots = []
            for z in short_zs:
                mr = results.get(z.type)
                if mr is None or mr.get("model") is None: continue
                feats = _extract_zone_features(z, open_ts, resampled, helpers, events, candle_ctx, liq_s)
                if feats is None: continue
                feats["tf"] = z.tf; feats["target"] = 0; feats["candle_open_ts"] = open_ts; feats["side"] = "short"
                df_row = pd.DataFrame([feats])
                exp = expand_to_cell_wise(df_row, mr["feature_cols"], tfs=SMC_TFS)
                X = exp[mr["cell_cols"]].to_numpy()
                p = float(mr["model"].predict_proba(X)[0, 1])
                # Proximity weight: closer to candle.high = more important
                # zone hi closer to candle.high → smaller dist
                dist = max(0.0, abs(z.hi - regs.candle_high)) if z.type != "fractal" else abs(z.level - regs.candle_high)
                prox = 1.0 / (1.0 + dist / (regs.short_hi - regs.short_lo + 1.0))
                short_p_pivots.append({"p": p, "tf": z.tf, "prox": prox})

            if short_p_pivots:
                ps = np.array([x["p"] for x in short_p_pivots])
                proxs = np.array([x["prox"] for x in short_p_pivots])
                tfs = [x["tf"] for x in short_p_pivots]
                v3_score = float(ps.sum())
                prox_weighted = float((ps * proxs).sum())
                max_p = float(ps.max())
                n_zones = len(short_p_pivots)
                n_htf = sum(1 for t in tfs if t in HTF_TFS)
                htf_share = n_htf / n_zones
                region_w_atr = (regs.short_hi - regs.short_lo) / atr12 if atr12 > 0 else 1.0
                n_norm = n_zones / region_w_atr if region_w_atr > 0 else n_zones

                rows.append({
                    "open_ts": open_ts, "side": "short",
                    "v3_score": v3_score,
                    "prox_weighted_score": prox_weighted,
                    "max_zone_p": max_p,
                    "n_zones": n_zones,
                    "n_zones_norm": n_norm,
                    "htf_zone_share": htf_share,
                    "liq_count": liq_s,
                    "cum_move_atr": cum_move_atr,
                    "compression": compression,
                    "session": session,
                    "region_width_atr": region_w_atr,
                    "is_pivot": bool(row["is_fh"]),  # SHORT side → predict is_FH
                    "is_target": open_ts in SHORT_TARGETS,
                })

        if regs.has_long:
            long_zs = [z for z in zs if _zone_in_long_region(z, regs)]
            long_p_pivots = []
            for z in long_zs:
                mr = results.get(z.type)
                if mr is None or mr.get("model") is None: continue
                feats = _extract_zone_features(z, open_ts, resampled, helpers, events, candle_ctx, liq_l)
                if feats is None: continue
                feats["tf"] = z.tf; feats["target"] = 0; feats["candle_open_ts"] = open_ts; feats["side"] = "long"
                df_row = pd.DataFrame([feats])
                exp = expand_to_cell_wise(df_row, mr["feature_cols"], tfs=SMC_TFS)
                X = exp[mr["cell_cols"]].to_numpy()
                p = float(mr["model"].predict_proba(X)[0, 1])
                dist = max(0.0, abs(z.lo - regs.candle_low)) if z.type != "fractal" else abs(z.level - regs.candle_low)
                prox = 1.0 / (1.0 + dist / (regs.long_hi - regs.long_lo + 1.0))
                long_p_pivots.append({"p": p, "tf": z.tf, "prox": prox})

            if long_p_pivots:
                ps = np.array([x["p"] for x in long_p_pivots])
                proxs = np.array([x["prox"] for x in long_p_pivots])
                tfs = [x["tf"] for x in long_p_pivots]
                v3_score = float(ps.sum())
                prox_weighted = float((ps * proxs).sum())
                max_p = float(ps.max())
                n_zones = len(long_p_pivots)
                n_htf = sum(1 for t in tfs if t in HTF_TFS)
                htf_share = n_htf / n_zones
                region_w_atr = (regs.long_hi - regs.long_lo) / atr12 if atr12 > 0 else 1.0
                n_norm = n_zones / region_w_atr if region_w_atr > 0 else n_zones

                rows.append({
                    "open_ts": open_ts, "side": "long",
                    "v3_score": v3_score,
                    "prox_weighted_score": prox_weighted,
                    "max_zone_p": max_p,
                    "n_zones": n_zones,
                    "n_zones_norm": n_norm,
                    "htf_zone_share": htf_share,
                    "liq_count": liq_l,
                    "cum_move_atr": cum_move_atr,
                    "compression": compression,
                    "session": session,
                    "region_width_atr": region_w_atr,
                    "is_pivot": bool(row["is_fl"]),  # LONG side → predict is_FL
                    "is_target": open_ts in LONG_TARGETS,
                })

    return pd.DataFrame(rows)


def main():
    train_start = pd.Timestamp("2025-01-01", tz="UTC")
    train_end = pd.Timestamp("2026-01-31", tz="UTC")
    score_start = pd.Timestamp("2026-02-01", tz="UTC")
    score_end = pd.Timestamp("2026-06-01", tz="UTC")

    print("[1/4] Train v3 primary models...")
    df_train = load_btc_1m(start=train_start, end=train_end)
    datasets, _ = build_datasets(df_train)
    results = train_all(datasets, C=1.0, test_split_ts=None)

    print("\n[2/4] Extract candidates + meta-features...")
    df_score = load_btc_1m(start=train_start, end=score_end)
    df = extract_full_candidates(df_score, results, score_start, score_end)
    print(f"  Total candidates: {len(df)}")
    print(f"  SHORT side: {(df['side']=='short').sum()}  LONG side: {(df['side']=='long').sum()}")
    print(f"  is_pivot=True: {df['is_pivot'].sum()}/{len(df)}")

    # === Split meta-train / meta-test by chronology ===
    split = df['open_ts'].quantile(0.5)
    train_mask = df['open_ts'] < split
    test_mask = ~train_mask
    print(f"\n[3/4] Meta-train / Meta-test split at {split}")
    print(f"  Meta-train: {train_mask.sum()}  Meta-test: {test_mask.sum()}")

    META_FEATURES = [
        "v3_score", "prox_weighted_score", "max_zone_p",
        "n_zones", "n_zones_norm", "htf_zone_share",
        "liq_count", "cum_move_atr", "compression",
        "session", "region_width_atr",
    ]

    X_train = df.loc[train_mask, META_FEATURES].fillna(0).to_numpy()
    y_train = df.loc[train_mask, "is_pivot"].astype(int).to_numpy()
    X_test = df.loc[test_mask, META_FEATURES].fillna(0).to_numpy()
    y_test = df.loc[test_mask, "is_pivot"].astype(int).to_numpy()
    targets_test = df.loc[test_mask, "is_target"].astype(int).to_numpy()

    print(f"  Train pivots: {y_train.sum()}/{len(y_train)} ({y_train.mean()*100:.1f}%)")
    print(f"  Test pivots:  {y_test.sum()}/{len(y_test)} ({y_test.mean()*100:.1f}%)")

    meta = LogisticRegression(C=1.0, max_iter=2000)
    meta.fit(X_train, y_train)

    p_train = meta.predict_proba(X_train)[:, 1]
    p_test = meta.predict_proba(X_test)[:, 1]
    auc_train = roc_auc_score(y_train, p_train) if len(np.unique(y_train))>1 else None
    auc_test = roc_auc_score(y_test, p_test) if len(np.unique(y_test))>1 else None
    print(f"\n  Meta AUC train={auc_train:.3f}  test={auc_test:.3f}")

    print(f"\n  Meta-classifier coefficients:")
    for feat, w in sorted(zip(META_FEATURES, meta.coef_[0]), key=lambda x: -abs(x[1])):
        print(f"    {feat:<25} = {w:+.4f}")

    print("\n[4/4] Comparison: primary-only (v3_score) vs meta-combined (meta P)")

    # Top-N hit rate
    test_df = df.loc[test_mask].copy()
    test_df["meta_p"] = p_test
    test_df["combined"] = test_df["v3_score"] * test_df["meta_p"]

    n_actual = int(y_test.sum())
    n_targets = int(targets_test.sum())

    def topN_hits(test_df, sort_col, N):
        top = test_df.nlargest(N, sort_col)
        return int(top["is_pivot"].sum()), int(top["is_target"].sum())

    print(f"\n  Total test candidates: {len(test_df)}  actual pivots: {n_actual}  22-targets: {n_targets}")
    print(f"\n  {'Method':<25}  {'Top-10':<20} {'Top-20':<20} {'Top-30':<20}")
    for method, col in [("Primary v3 score", "v3_score"),
                         ("Meta only (P)", "meta_p"),
                         ("Combined (v3 × meta)", "combined"),
                         ("Random (baseline)", None)]:
        if col is None:
            # Random: expected = (N / total) * pivots
            ev10 = 10 * n_actual / len(test_df)
            ev20 = 20 * n_actual / len(test_df)
            ev30 = 30 * n_actual / len(test_df)
            print(f"  {method:<25}  {ev10:.1f} pivots         {ev20:.1f} pivots         {ev30:.1f} pivots")
            continue
        h10, t10 = topN_hits(test_df, col, 10)
        h20, t20 = topN_hits(test_df, col, 20)
        h30, t30 = topN_hits(test_df, col, 30)
        print(f"  {method:<25}  {h10}/{n_actual} pv, {t10}/{n_targets} tg     {h20}/{n_actual} pv, {t20}/{n_targets} tg     {h30}/{n_actual} pv, {t30}/{n_targets} tg")

    # Save
    out = Path.home() / "Desktop" / "meta_label_v3.csv"
    test_df.to_csv(out, index=False)
    print(f"\nResults → {out}")


if __name__ == "__main__":
    main()
