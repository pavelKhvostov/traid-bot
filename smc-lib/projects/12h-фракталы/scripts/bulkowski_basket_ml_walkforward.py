"""ML walk-forward (train + retrain) на Bulkowski features 12h pivots.

Dataset: 1357 baseline pivots × 8 Bulkowski features + structural (body, wick, color)
Targets (binary):
  hit_2 = move_pct ≥ 2%
  hit_3 = move_pct ≥ 3%
  hit_4 = move_pct ≥ 4%
  hit_5 = move_pct ≥ 5%

Walk-forward:
  Sort by close_ms. Slide an expanding-train + fixed-test window.
  - Initial train: first 30% of data
  - Step: 5% of data
  - Test fold: next 5% after train
  - RETRAIN model each step on growing train (purged: drop overlap horizon)
  - Predict on test fold → out-of-sample probabilities
  - Collect all OOS predictions → compute WR per decile

Model: LightGBM (default) + RandomForest baseline.

Output:
  oos_predictions_<target>.parquet  ← all walk-forward predictions
  walkforward_metrics.csv           ← AUC / WR by target × model × fold
  selection_curves.csv              ← top-K selection: WR vs N kept
  feature_importance.csv            ← averaged across folds
"""
from __future__ import annotations
import pathlib, time
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

try:
    from lightgbm import LGBMClassifier
    HAS_LGB = True
except Exception as e:
    HAS_LGB = False
    print(f"WARN: lightgbm unavailable ({type(e).__name__}), using GradientBoosting + RF")
    from sklearn.ensemble import GradientBoostingClassifier


OUT = pathlib.Path.home() / "Desktop/12h-fractal-new-out"
FEAT_PATH = OUT / "bulkowski_basket_features.parquet"

PURGE_DAYS = 14  # horizon for realized move — purge train/test overlap
PURGE_MS = PURGE_DAYS * 24 * 60 * 60 * 1000

TRAIN_INIT_FRAC = 0.30
STEP_FRAC = 0.05
TEST_FRAC = 0.05

TARGETS = ["hit_2", "hit_3", "hit_4", "hit_5"]


def make_lgb(seed=42):
    if HAS_LGB:
        return LGBMClassifier(
            n_estimators=300, learning_rate=0.03, max_depth=4,
            num_leaves=15, min_child_samples=20, subsample=0.8,
            colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=0.1,
            random_state=seed, n_jobs=-1, verbose=-1,
        )
    # sklearn GradientBoosting fallback
    return GradientBoostingClassifier(
        n_estimators=300, learning_rate=0.03, max_depth=4,
        min_samples_leaf=20, subsample=0.8, random_state=seed,
    )


def make_rf(seed=42):
    return RandomForestClassifier(
        n_estimators=300, max_depth=6, min_samples_leaf=20,
        random_state=seed, n_jobs=-1,
    )


def walkforward_oos(df, feat_cols, target, model_fn, label):
    """Walk-forward with retraining. Returns OOS predictions DataFrame."""
    df = df.sort_values("close_ms").reset_index(drop=True)
    n = len(df)
    train_end = int(n * TRAIN_INIT_FRAC)
    step = max(1, int(n * STEP_FRAC))
    test_sz = max(1, int(n * TEST_FRAC))

    oos_records = []
    fold_metrics = []
    fold_i = 0
    while train_end + test_sz <= n:
        # Purge: drop train rows whose close_ms + PURGE_MS > test_start_ms
        test_start_ms = int(df.close_ms.iloc[train_end])
        train_df = df.iloc[:train_end].copy()
        train_df = train_df[train_df.close_ms + PURGE_MS <= test_start_ms]
        if len(train_df) < 50:
            train_end += step
            fold_i += 1
            continue

        test_df = df.iloc[train_end:train_end + test_sz]

        X_tr = train_df[feat_cols].to_numpy(dtype=np.float32)
        y_tr = train_df[target].to_numpy(dtype=int)
        X_te = test_df[feat_cols].to_numpy(dtype=np.float32)
        y_te = test_df[target].to_numpy(dtype=int)

        if y_tr.sum() < 5 or y_tr.sum() > len(y_tr) - 5:
            # No class diversity
            train_end += step; fold_i += 1; continue

        model = model_fn()
        model.fit(X_tr, y_tr)
        proba = model.predict_proba(X_te)[:, 1]

        # Importance (LightGBM only)
        imp = None
        if hasattr(model, "feature_importances_"):
            imp = pd.Series(model.feature_importances_, index=feat_cols)

        auc = roc_auc_score(y_te, proba) if y_te.sum() > 0 and y_te.sum() < len(y_te) else np.nan
        fold_metrics.append({
            "fold": fold_i, "model": label, "target": target,
            "n_train": len(train_df), "n_test": len(test_df),
            "base_rate_train": float(y_tr.mean()),
            "base_rate_test": float(y_te.mean()),
            "auc_test": auc,
            "train_end_ms": int(train_df.close_ms.iloc[-1]),
            "test_start_ms": test_start_ms,
            "test_end_ms": int(test_df.close_ms.iloc[-1]),
        })

        for k, (ts, yt, p) in enumerate(zip(test_df.close_ms.values, y_te, proba)):
            oos_records.append({
                "fold": fold_i, "model": label, "target": target,
                "close_ms": int(ts), "y_true": int(yt), "y_proba": float(p),
                "direction": test_df.direction.iloc[k],
                "is_long": int(test_df.is_long.iloc[k]),
            })

        train_end += step
        fold_i += 1

    return pd.DataFrame(oos_records), pd.DataFrame(fold_metrics)


def selection_curve(oos_df, target):
    """Top-K selection: sort by y_proba desc, compute WR for top-K."""
    sub = oos_df[oos_df.target == target].sort_values("y_proba", ascending=False).reset_index(drop=True)
    rows = []
    for k in (10, 20, 30, 50, 75, 100, 150, 200, 300, 500, len(sub)):
        if k > len(sub): break
        top = sub.iloc[:k]
        rows.append({
            "target": target,
            "top_k": k,
            "wr": float(top.y_true.mean()),
            "y_proba_threshold": float(top.y_proba.iloc[-1]),
        })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    df = pd.read_parquet(FEAT_PATH)
    print(f"loaded: {len(df)} rows")

    # Build targets
    for thr in (2, 3, 4, 5):
        df[f"hit_{thr}"] = (df.move_pct >= thr).astype(int)

    # Features: Bulkowski + structural + direction
    bulkowski_cols = [c for c in df.columns if c.startswith(("4h_", "1d_"))]
    feat_cols = bulkowski_cols + ["is_long", "body_pct", "wick_pct", "color"]
    print(f"features: {len(feat_cols)} -> {feat_cols}")

    print(f"\nBase rates:")
    for t in TARGETS:
        print(f"  {t}: {df[t].mean()*100:.1f}% (N={df[t].sum()}/{len(df)})")

    all_oos = []
    all_metrics = []
    for target in TARGETS:
        for label, model_fn in [("gbm", make_lgb), ("rf", make_rf)]:
            print(f"\n[{label}] walk-forward on {target}...")
            oos, mets = walkforward_oos(df, feat_cols, target, model_fn, label)
            print(f"  folds: {len(mets)}, OOS rows: {len(oos)}")
            if len(mets) > 0:
                auc_mean = float(mets.auc_test.dropna().mean())
                print(f"  mean AUC: {auc_mean:.4f}")
            all_oos.append(oos)
            all_metrics.append(mets)

    oos_all = pd.concat(all_oos, ignore_index=True) if all_oos else pd.DataFrame()
    metrics_all = pd.concat(all_metrics, ignore_index=True) if all_metrics else pd.DataFrame()

    oos_all.to_parquet(OUT / "bulkowski_basket_oos_predictions.parquet", index=False)
    metrics_all.to_csv(OUT / "bulkowski_basket_walkforward_metrics.csv", index=False)

    # Selection curves per target × model
    print(f"\n{'─'*70}")
    print(f"Selection curves (top-K by y_proba desc, WR realized)")
    print(f"{'─'*70}")
    curves = []
    for label in ["gbm", "rf"]:
        for target in TARGETS:
            sub = oos_all[(oos_all.model == label) & (oos_all.target == target)]
            if sub.empty:
                continue
            curve = selection_curve(sub, target)
            curve["model"] = label
            curves.append(curve)
            print(f"\n  [{label}] {target} (base {df[target].mean()*100:.1f}%):")
            for _, r in curve.iterrows():
                print(f"    top_{int(r.top_k):>4}: WR={r.wr*100:>5.1f}%  thr={r.y_proba_threshold:.3f}")
    if curves:
        pd.concat(curves, ignore_index=True).to_csv(OUT / "bulkowski_basket_selection_curves.csv", index=False)

    # Overall summary
    print(f"\n{'═'*70}")
    print(f"Summary: AUC mean per (model × target) [walk-forward OOS]")
    print(f"{'═'*70}")
    if not metrics_all.empty:
        summary = metrics_all.groupby(["model", "target"]).agg(
            auc_mean=("auc_test", "mean"),
            auc_std=("auc_test", "std"),
            n_folds=("fold", "count"),
            n_test_total=("n_test", "sum"),
        ).reset_index()
        print(summary.to_string(index=False))
        summary.to_csv(OUT / "bulkowski_basket_summary.csv", index=False)

    print(f"\nElapsed: {time.time()-t0:.1f}s")
    print(f"Outputs in {OUT}")


if __name__ == "__main__":
    main()
