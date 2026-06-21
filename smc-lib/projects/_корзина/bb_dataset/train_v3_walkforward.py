"""Train bb-model Phase 2 walk-forward + apply as filter to backtest.

Input:  ~/Desktop/bb_obvc_1h2h_v3.parquet (with 106 features + trade_label)
Output:
  bb_predictions_v3.csv     — per-zone walk-forward P_win + actual
  bb_metrics_v3.json        — per-fold metrics
  bb_feature_importance_v2.csv
  bb_strategy_filter_v3.txt — WR/RR при разных thresholds (главный результат)

Walk-forward: 4y train rolling / 1y test / monthly retrain.

Используется sklearn HistGradientBoostingClassifier (Mac-friendly без libomp).
"""
from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score, average_precision_score


import os
# Resolve paths: env var BB_PARQUET_PATH > archive layout > legacy Mac path
_THIS = Path(__file__).resolve()
_SMC_LIB = _THIS.parents[2]
_ARCHIVE_OUT = _SMC_LIB.parent / "output"
if os.environ.get("BB_PARQUET_PATH"):
    DATA = Path(os.environ["BB_PARQUET_PATH"])
    OUT_DIR = DATA.parent
elif (_ARCHIVE_OUT / "bb_obvc_1h2h_v3.parquet").exists():
    DATA = _ARCHIVE_OUT / "bb_obvc_1h2h_v3.parquet"
    OUT_DIR = _ARCHIVE_OUT
else:
    DATA = Path.home() / "Desktop" / "bb_obvc_1h2h_v3.parquet"
    OUT_DIR = Path.home() / "smc-lib" / "projects" / "bb_dataset"


def get_feature_cols(df: pd.DataFrame) -> list[str]:
    """All numeric feature columns from groups I-XI."""
    return [c for c in df.columns
            if c.startswith(("I_", "II_", "III_", "IV_", "V_", "VI_", "VII_",
                              "VIII_", "IX_", "X_", "XI_"))]


def walk_forward(df: pd.DataFrame, feature_cols: list[str],
                  test_years: float = 1.0, train_years: float = 4.0,
                  retrain_months: int = 1) -> dict:
    """Walk-forward с monthly retrain."""
    df = df.dropna(subset=["trade_label"]).copy()
    df = df[df["trade_label"] >= 0].copy()
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df = df.sort_values("signal_time").reset_index(drop=True)
    print(f"  prepared: {len(df):,} valid trade-labelled rows")
    print(f"  WR base: {df['trade_label'].mean()*100:.1f}%")

    end_ts = df["signal_time"].max()
    test_start = end_ts - pd.Timedelta(days=int(365 * test_years))
    print(f"  test period: {test_start} -> {end_ts}")

    # Generate retrain timestamps (monthly)
    retrain_ts_list = pd.date_range(test_start, end_ts, freq=f"{retrain_months}MS", tz="UTC").tolist()
    if not retrain_ts_list:
        retrain_ts_list = [test_start]
    print(f"  retrain points: {len(retrain_ts_list)}")

    all_preds = []
    metrics_per_fold = []
    importance_acc = np.zeros(len(feature_cols))

    for fold_i, retrain_ts in enumerate(retrain_ts_list):
        train_window_lo = retrain_ts - pd.Timedelta(days=int(365 * train_years))
        train_mask = (df["signal_time"] >= train_window_lo) & (df["signal_time"] < retrain_ts)
        # Test fold = events between this retrain and next retrain
        if fold_i + 1 < len(retrain_ts_list):
            test_end = retrain_ts_list[fold_i + 1]
        else:
            test_end = end_ts + pd.Timedelta(days=1)
        test_mask = (df["signal_time"] >= retrain_ts) & (df["signal_time"] < test_end)

        train_df = df[train_mask]
        test_df = df[test_mask]
        if len(train_df) < 200 or len(test_df) < 10:
            continue

        X_tr = train_df[feature_cols].astype(float).fillna(0.0).to_numpy()
        y_tr = train_df["trade_label"].astype(int).to_numpy()
        X_te = test_df[feature_cols].astype(float).fillna(0.0).to_numpy()
        y_te = test_df["trade_label"].astype(int).to_numpy()

        model = HistGradientBoostingClassifier(
            max_iter=300,
            learning_rate=0.05,
            max_leaf_nodes=31,
            min_samples_leaf=50,
            random_state=42,
        )
        model.fit(X_tr, y_tr)
        p_tr = model.predict_proba(X_tr)[:, 1]
        p_te = model.predict_proba(X_te)[:, 1]

        # Isotonic calibration
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(p_tr, y_tr)
        p_te_cal = iso.transform(p_te)

        fold_metrics = {"fold": fold_i, "retrain_ts": str(retrain_ts),
                         "n_train": int(len(train_df)), "n_test": int(len(test_df))}
        if len(np.unique(y_te)) > 1:
            fold_metrics["auc"] = float(roc_auc_score(y_te, p_te_cal))
            fold_metrics["brier"] = float(brier_score_loss(y_te, p_te_cal))
            fold_metrics["ap"] = float(average_precision_score(y_te, p_te_cal))

        # Feature importance from permutation? Use HGB's built-in (just split contribution)
        # HGB doesn't have direct feature_importance; use OOF gain approximation via
        # split-frequency feature_importances_ attr if present
        if hasattr(model, "_predictors") and model._predictors:
            # Approx: count features used in trees (works in sklearn >= 1.5)
            pass
        # Default skipped — we'll compute importance from final model

        metrics_per_fold.append(fold_metrics)

        out_df = test_df[["signal_time", "tf", "direction", "fvg_tf", "trade_label",
                            "trade_R", "exit_reason"]].copy()
        out_df["P_win"] = p_te_cal
        out_df["P_win_raw"] = p_te
        out_df["fold"] = fold_i
        all_preds.append(out_df)
        print(f"  fold {fold_i}: train={len(train_df)} test={len(test_df)} "
              f"AUC={fold_metrics.get('auc', float('nan')):.3f}")

    preds_df = pd.concat(all_preds, ignore_index=True) if all_preds else pd.DataFrame()
    return {"preds": preds_df, "metrics": metrics_per_fold}


def filter_strategy_eval(preds: pd.DataFrame) -> pd.DataFrame:
    """Apply P_win threshold filter, compute WR / R/tr / RR / total_R per threshold."""
    rows = []
    for th in [0.0, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]:
        kept = preds[preds["P_win"] >= th]
        if len(kept) == 0:
            continue
        wins_mask = kept["trade_label"] == 1
        n = len(kept)
        wins = wins_mask.sum()
        losses = (kept["trade_label"] == 0).sum()
        wr = wins / n * 100 if n > 0 else 0.0
        total_R = kept["trade_R"].sum()
        r_per_tr = kept["trade_R"].mean()
        # Implied RR (mean win R / mean loss R)
        if wins > 0 and losses > 0:
            mean_win_R = kept[wins_mask]["trade_R"].mean()
            mean_loss_R = abs(kept[~wins_mask]["trade_R"].mean())
            rr = mean_win_R / mean_loss_R if mean_loss_R > 0 else float("inf")
        else:
            rr = float("nan")
        rows.append({
            "P_win_th": th,
            "n_kept": n,
            "kept_pct": round(n / len(preds) * 100, 1),
            "WR_pct": round(wr, 1),
            "implied_RR": round(rr, 2),
            "R_per_tr": round(float(r_per_tr), 3),
            "total_R": round(float(total_R), 1),
            "trades_per_year": round(n, 0),
        })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    print(f"[bb-train-v3] loading {DATA}...")
    df = pd.read_parquet(DATA)
    print(f"  {len(df):,} rows × {len(df.columns)} cols")

    feature_cols = get_feature_cols(df)
    print(f"  feature cols: {len(feature_cols)}")

    print("\n[bb-train-v3] walk-forward training...")
    res = walk_forward(df, feature_cols, test_years=1.0, train_years=4.0, retrain_months=1)

    OUT_DIR.mkdir(exist_ok=True)
    res["preds"].to_csv(OUT_DIR / "bb_predictions_v3.csv", index=False)
    print(f"\n[bb-train-v3] saved predictions → bb_predictions_v3.csv ({len(res['preds'])} rows)")

    with open(OUT_DIR / "bb_metrics_v3.json", "w") as f:
        json.dump({"folds": res["metrics"],
                    "summary_AUC_mean": float(np.mean([m.get("auc", np.nan)
                                                          for m in res["metrics"]])),
                    "summary_Brier_mean": float(np.mean([m.get("brier", np.nan)
                                                            for m in res["metrics"]])),
                    "n_folds": len(res["metrics"])}, f, indent=2, default=str)

    # Strategy filter analysis
    print("\n[bb-train-v3] strategy filter analysis (KEEP if P_win >= threshold):")
    print("=" * 100)
    filter_df = filter_strategy_eval(res["preds"])
    print(filter_df.to_string(index=False))
    filter_df.to_csv(OUT_DIR / "bb_strategy_filter_v3.csv", index=False)

    # Target check: WR ≥ 60% и RR ≥ 2.2
    print("\n[bb-train-v3] TARGET CHECK (WR>=60% AND RR>=2.2):")
    target_rows = filter_df[(filter_df["WR_pct"] >= 60) & (filter_df["implied_RR"] >= 2.2)]
    if len(target_rows) > 0:
        print(target_rows.to_string(index=False))
        print(f"\n  ✅ TARGETS HIT at {len(target_rows)} threshold(s)")
    else:
        print("  ❌ NO threshold gives both WR>=60% AND RR>=2.2")
        # Show closest
        filter_df["dist_to_target"] = (
            np.maximum(0, 60 - filter_df["WR_pct"]) +
            np.maximum(0, 2.2 - filter_df["implied_RR"]) * 10
        )
        closest = filter_df.nsmallest(3, "dist_to_target")
        print("  Closest to targets:")
        print(closest[["P_win_th", "n_kept", "WR_pct", "implied_RR", "R_per_tr"]].to_string(index=False))

    print(f"\n[bb-train-v3] TOTAL: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
