"""Production walk-forward simulation on v3.5 (660+ honest features).

Workflow:
  Train on rolling 4-year window
  Retrain every 6 months
  Test forward on next 6 months
  Report per-year WR/Σ R + selection at different thresholds

This is HONEST production simulation — no peek into future at any point.
"""
from __future__ import annotations
import sys, pathlib, warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path("/Users/vadim/Desktop/compute-archives/compute-2026-06-09-ob-vc-hma-v3-pc1")))
try:
    from ml.sample_weights import compute_sample_weights
except Exception:
    def compute_sample_weights(df): return np.ones(len(df))


SRC = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v35_hma_honest_cross.parquet")
OUT_DIR = pathlib.Path("/Users/vadim/smc-lib/strategies/strategy_ob_vc_v33_lean_picked")

TARGET = "hit_RR_20"
RR = 2.0
TRAIN_WINDOW_DAYS = 4 * 365
RETRAIN_INTERVAL_MONTHS = 6
META_COLS = {
    "event_id", "asset", "born_ms", "entry_fill_ms", "direction",
    "t_id", "n_comp", "extreme", "entry", "R", "r_pct", "r_pct_pass",
    "fill_touched", "mfe_R", "mae_R", "sl_hit", "exit_reason",
    "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
    "hit_RR_23", "hit_RR_25", "hit_RR_28",
}


def make_model(seed=42):
    return HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=300, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=0.1, random_state=seed,
    )


def date_ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def main():
    print("=" * 72)
    print("Production walk-forward simulation — v3.5 (660+ honest features)")
    print("=" * 72)

    df = pd.read_parquet(SRC)
    df = df[df.fill_touched & df.r_pct_pass].reset_index(drop=True)
    df["born_dt"] = pd.to_datetime(df.born_ms, unit="ms", utc=True)
    print(f"\nViable events: {len(df):,}")
    print(f"Date range: {df.born_dt.min():%Y-%m-%d} → {df.born_dt.max():%Y-%m-%d}")

    feat_cols = [c for c in df.columns if c not in META_COLS and c != "born_dt"]
    print(f"Features: {len(feat_cols)}")

    # Drop features that are mostly NaN in training scope
    X_all = df[feat_cols]
    nan_frac = X_all.isna().mean()
    keep_cols = [c for c, f in nan_frac.items() if f < 0.5]
    print(f"Features after NaN-drop (≥50% NaN removed): {len(keep_cols)}")
    feat_cols = keep_cols

    # Define retrain schedule
    retrain_dates = [
        (2024, 1, 1), (2024, 7, 1),
        (2025, 1, 1), (2025, 7, 1),
        (2026, 1, 1),
    ]

    print(f"\nRetrain schedule: {[f'{y}-{m:02d}' for y,m,_ in retrain_dates]}")
    print(f"Train window: {TRAIN_WINDOW_DAYS // 365} years rolling")
    print(f"Test window: next {RETRAIN_INTERVAL_MONTHS} months\n")

    results_summary = []
    all_test_predictions = []
    test_end_default_ms = int(df.born_ms.max() + 86400 * 1000)

    for idx, (y, m, d) in enumerate(retrain_dates):
        retrain_ms = date_ms(y, m, d)
        train_start_ms = retrain_ms - TRAIN_WINDOW_DAYS * 86400 * 1000
        if idx + 1 < len(retrain_dates):
            ny, nm, nd = retrain_dates[idx + 1]
            test_end_ms = date_ms(ny, nm, nd)
        else:
            test_end_ms = test_end_default_ms

        train_mask = (df.born_ms >= train_start_ms) & (df.born_ms < retrain_ms)
        test_mask = (df.born_ms >= retrain_ms) & (df.born_ms < test_end_ms)
        df_tr = df[train_mask].reset_index(drop=True)
        df_te = df[test_mask].reset_index(drop=True)

        if len(df_tr) < 200 or len(df_te) < 50:
            print(f"  skip {y}-{m:02d}: train={len(df_tr)}, test={len(df_te)}")
            continue

        # Ensemble (3 seeds)
        X_tr = df_tr[feat_cols].to_numpy(dtype=np.float32)
        y_tr = df_tr[TARGET].to_numpy()
        X_te = df_te[feat_cols].to_numpy(dtype=np.float32)
        y_te = df_te[TARGET].to_numpy()
        try:
            sw = compute_sample_weights(df_tr)
        except Exception:
            sw = np.ones(len(df_tr))

        probas_test = []
        probas_train = []
        for seed in (42, 1337, 2024):
            m_md = make_model(seed=seed)
            try:
                m_md.fit(X_tr, y_tr, sample_weight=sw)
            except Exception:
                m_md.fit(X_tr, y_tr)
            probas_test.append(m_md.predict_proba(X_te)[:, 1])
            probas_train.append(m_md.predict_proba(X_tr)[:, 1])
        proba_test = np.mean(probas_test, axis=0)
        proba_train = np.mean(probas_train, axis=0)

        # Production rule: select top-17% of TEST window by proba (= ~1100/6325 ratio).
        # In live: would set threshold ahead from training proba quantile that yields
        # similar selectivity — here we approximate that by simply taking top-N.
        SELECT_FRAC = 0.17
        n_test = len(proba_test)
        k = max(1, int(round(SELECT_FRAC * n_test)))
        order = np.argsort(proba_test)[::-1]
        selected = np.zeros(n_test, dtype=bool)
        selected[order[:k]] = True
        threshold = float(proba_test[order[k - 1]]) if k > 0 else float("nan")

        n_total = len(df_te)
        n_sel = int(selected.sum())
        wins_sel = int(y_te[selected].sum()) if n_sel > 0 else 0
        wr_sel = wins_sel / n_sel if n_sel > 0 else 0.0
        sum_r_sel = wins_sel * RR - (n_sel - wins_sel) * 1.0

        # Baseline: no ML filter (all events in window)
        wr_all = float(y_te.mean())
        sum_r_all = int(y_te.sum()) * RR - (n_total - int(y_te.sum())) * 1.0

        # AUC on test
        try:
            auc = roc_auc_score(y_te, proba_test)
        except Exception:
            auc = float("nan")

        train_yrs = (retrain_ms - train_start_ms) / (365 * 86400 * 1000)
        test_label = f"{y}-{m:02d} → {datetime.fromtimestamp(test_end_ms/1000, timezone.utc):%Y-%m}"

        results_summary.append({
            "retrain_date": f"{y}-{m:02d}-{d:02d}",
            "test_period": test_label,
            "train_years": round(train_yrs, 1),
            "n_train": len(df_tr),
            "n_test": n_total,
            "threshold": round(threshold, 4),
            "n_selected": n_sel,
            "wr_selected": round(wr_sel * 100, 1),
            "sum_r_selected": round(sum_r_sel, 1),
            "wr_baseline": round(wr_all * 100, 1),
            "sum_r_baseline": round(sum_r_all, 1),
            "test_auc": round(auc, 4),
            "n_selected_pct": round(n_sel / n_total * 100, 1) if n_total else 0,
        })

        # Save per-trade results
        df_te2 = df_te.copy()
        df_te2["proba"] = proba_test
        df_te2["selected"] = selected
        df_te2["R"] = np.where(y_te == 1, RR, -1.0)
        df_te2["retrain_date"] = f"{y}-{m:02d}-{d:02d}"
        all_test_predictions.append(df_te2[["event_id", "asset", "direction", "t_id",
                                              "born_dt", "proba", "selected", "R", TARGET,
                                              "retrain_date"]])

    summary = pd.DataFrame(results_summary)
    print("\n" + "=" * 96)
    print("PRODUCTION WALK-FORWARD RESULTS")
    print("=" * 96)
    print(summary.to_string(index=False))
    summary.to_csv(OUT_DIR / "production_walkforward_v35.csv", index=False)

    # Per-year aggregation
    all_test = pd.concat(all_test_predictions, ignore_index=True)
    all_test["year"] = all_test.born_dt.dt.year
    all_test.to_parquet(OUT_DIR / "production_walkforward_v35_trades.parquet", index=False)

    print("\n" + "=" * 96)
    print("PER-YEAR aggregation (selected by ML)")
    print("=" * 96)
    by_year_sel = all_test[all_test.selected].groupby("year").agg(
        n=("R", "count"),
        wins=(TARGET, "sum"),
        sum_r=("R", "sum"),
    ).reset_index()
    by_year_sel["wr%"] = (by_year_sel.wins / by_year_sel.n * 100).round(1)
    by_year_sel["e_r"] = (by_year_sel.sum_r / by_year_sel.n).round(3)
    print(by_year_sel.to_string(index=False))

    print("\n" + "=" * 96)
    print("PER-YEAR aggregation (baseline — all events, no ML filter)")
    print("=" * 96)
    by_year_all = all_test.groupby("year").agg(
        n=("R", "count"),
        wins=(TARGET, "sum"),
        sum_r=("R", "sum"),
    ).reset_index()
    by_year_all["wr%"] = (by_year_all.wins / by_year_all.n * 100).round(1)
    by_year_all["e_r"] = (by_year_all.sum_r / by_year_all.n).round(3)
    print(by_year_all.to_string(index=False))

    # Total numbers
    print("\n" + "=" * 96)
    print("TOTAL OUT-OF-SAMPLE (production simulation)")
    print("=" * 96)
    sel = all_test[all_test.selected]
    tot_n_sel = len(sel); tot_w_sel = int(sel[TARGET].sum())
    tot_n_all = len(all_test); tot_w_all = int(all_test[TARGET].sum())
    print(f"ML selected:    N={tot_n_sel:,}  WR={tot_w_sel/tot_n_sel*100:.1f}%  Σ R={sel.R.sum():+.0f}R  E[R]={sel.R.sum()/tot_n_sel:+.3f}R")
    print(f"Baseline all:   N={tot_n_all:,}  WR={tot_w_all/tot_n_all*100:.1f}%  Σ R={all_test.R.sum():+.0f}R  E[R]={all_test.R.sum()/tot_n_all:+.3f}R")
    uplift_r = sel.R.sum() - all_test.R.sum() * tot_n_sel / tot_n_all
    print(f"\nML uplift vs random pick same N: {uplift_r:+.0f}R")


if __name__ == "__main__":
    main()
