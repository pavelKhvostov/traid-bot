"""
Walk-forward validation harness для Phase 1 lookup модели.

Идея:
  - Train на скользящем окне (например, последние N дней до test cut-off)
  - Тест на одном cut-off
  - Re-train каждые retrain_freq дней (а не каждый cut-off)
  - Метрики: Brier, reliability bins, top-K accuracy, lift vs random

Output: dict с метриками + per-cut-off предсказания.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from model import LookupModel


@dataclass
class WalkForwardResult:
    predictions: pd.DataFrame       # original records + P_hit_12h, P_hit_D, bucket_used
    brier_12h: float
    brier_D: float
    brier_12h_baseline: float
    brier_D_baseline: float
    reliability_12h: pd.DataFrame   # bins: pred, mean_pred, mean_actual, count
    reliability_D: pd.DataFrame
    top5_hit_D_mean: float
    top5_hit_12h_mean: float
    top3_above_hit_D_mean: float
    top3_below_hit_D_mean: float
    random5_hit_D_mean: float
    n_test_records: int
    n_test_cuts: int
    train_window_days: int
    retrain_freq_days: int
    min_count: int


def reliability_bins(preds: np.ndarray, actuals: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Calibration curve: бакеты предсказаний → mean predicted vs mean actual."""
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for i in range(n_bins):
        mask = (preds >= bin_edges[i]) & (preds < bin_edges[i + 1])
        if i == n_bins - 1:
            mask |= (preds == 1.0)
        n = int(mask.sum())
        if n == 0:
            continue
        rows.append({
            "bin_lo": float(bin_edges[i]),
            "bin_hi": float(bin_edges[i + 1]),
            "n": n,
            "mean_pred": float(preds[mask].mean()),
            "mean_actual": float(actuals[mask].mean()),
        })
    return pd.DataFrame(rows)


def walk_forward(
    dataset: pd.DataFrame,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    train_window_days: int = 365,
    retrain_freq_days: int = 30,
    min_count: int = 20,
    alpha: float = 1.0,
    include_inside: bool = False,
    verbose: bool = True,
) -> WalkForwardResult:
    """
    Прогнать walk-forward на dataset.

    test_start, test_end: границы тестового периода.
    train_window_days: размер окна тренировки (сколько дней до test_cut использовать).
    retrain_freq_days: как часто переобучать (между переобучениями используется одна и та же модель).
    """
    ds = dataset.copy()
    ds["cut_off_ts"] = pd.to_datetime(ds["cut_off_ts"], utc=True)
    if not include_inside:
        ds = ds[ds["side"].isin(["above", "below"])]

    # Test cut-offs
    test_cuts = sorted(ds[(ds["cut_off_ts"] >= test_start) & (ds["cut_off_ts"] < test_end)]["cut_off_ts"].unique())
    if verbose:
        print(f"  Test cuts: {len(test_cuts)}, retrain every {retrain_freq_days}d, train window {train_window_days}d")

    all_preds: list[pd.DataFrame] = []
    last_train_date = None
    model: LookupModel | None = None

    for i, cut in enumerate(test_cuts):
        cut = pd.Timestamp(cut)
        # Решить, надо ли переобучить
        need_retrain = (model is None) or (last_train_date is None) or ((cut - last_train_date).days >= retrain_freq_days)
        if need_retrain:
            train_lo = cut - pd.Timedelta(days=train_window_days)
            train_data = ds[(ds["cut_off_ts"] >= train_lo) & (ds["cut_off_ts"] < cut)]
            if len(train_data) < 100:
                if verbose:
                    print(f"  [{i+1}/{len(test_cuts)}] cut={cut}: too few train rows ({len(train_data)}), skipping")
                continue
            model = LookupModel.fit(train_data, min_count=min_count, alpha=alpha)
            last_train_date = cut
            if verbose and (i % max(1, len(test_cuts)//20) == 0 or i == 0):
                print(f"  [{i+1}/{len(test_cuts)}] retrain @ {cut}, train_n={len(train_data)}")

        # Predict
        cut_data = ds[ds["cut_off_ts"] == cut]
        if cut_data.empty:
            continue
        preds = model.predict(cut_data)
        out = cut_data.reset_index(drop=True).copy()
        out["P_hit_12h"] = preds["P_hit_12h"].to_numpy()
        out["P_hit_D"] = preds["P_hit_D"].to_numpy()
        out["bucket_used"] = preds["bucket_used"].to_numpy()
        out["n_train_bucket"] = preds["n_train"].to_numpy()
        all_preds.append(out)

    pred_df = pd.concat(all_preds, ignore_index=True)

    # Metrics
    y_12 = pred_df["hit_12h"].astype(int).to_numpy()
    y_D = pred_df["hit_D"].astype(int).to_numpy()
    p_12 = pred_df["P_hit_12h"].to_numpy()
    p_D = pred_df["P_hit_D"].to_numpy()

    brier_12 = float(((p_12 - y_12) ** 2).mean())
    brier_D = float(((p_D - y_D) ** 2).mean())
    # Baseline: mean of all training data — для простоты возьмём mean самого test (это leakage, но мы только сравниваем)
    # Корректнее: average of model's global_rates over retrains. Упростим — global hit rate test = baseline.
    base_12 = float(y_12.mean())
    base_D = float(y_D.mean())
    brier_12_base = float(((base_12 - y_12) ** 2).mean())
    brier_D_base = float(((base_D - y_D) ** 2).mean())

    rel_12 = reliability_bins(p_12, y_12)
    rel_D = reliability_bins(p_D, y_D)

    # Top-K per cut-off
    top5_D = []
    top5_12 = []
    top3_above = []
    top3_below = []
    rnd_5 = []
    rng = np.random.default_rng(42)
    for cut, grp in pred_df.groupby("cut_off_ts"):
        if len(grp) == 0:
            continue
        if len(grp) >= 5:
            top5 = grp.nlargest(5, "P_hit_D")
            top5_D.append(top5["hit_D"].mean())
            top5_12_g = grp.nlargest(5, "P_hit_12h")
            top5_12.append(top5_12_g["hit_12h"].mean())
            sample = grp.iloc[rng.choice(len(grp), size=5, replace=False)]
            rnd_5.append(sample["hit_D"].mean())
        above = grp[grp["side"] == "above"]
        below = grp[grp["side"] == "below"]
        if len(above) >= 3:
            top3_above.append(above.nlargest(3, "P_hit_D")["hit_D"].mean())
        if len(below) >= 3:
            top3_below.append(below.nlargest(3, "P_hit_D")["hit_D"].mean())

    return WalkForwardResult(
        predictions=pred_df,
        brier_12h=brier_12, brier_D=brier_D,
        brier_12h_baseline=brier_12_base, brier_D_baseline=brier_D_base,
        reliability_12h=rel_12, reliability_D=rel_D,
        top5_hit_D_mean=float(np.mean(top5_D)) if top5_D else float("nan"),
        top5_hit_12h_mean=float(np.mean(top5_12)) if top5_12 else float("nan"),
        top3_above_hit_D_mean=float(np.mean(top3_above)) if top3_above else float("nan"),
        top3_below_hit_D_mean=float(np.mean(top3_below)) if top3_below else float("nan"),
        random5_hit_D_mean=float(np.mean(rnd_5)) if rnd_5 else float("nan"),
        n_test_records=len(pred_df),
        n_test_cuts=int(pred_df["cut_off_ts"].nunique()),
        train_window_days=train_window_days,
        retrain_freq_days=retrain_freq_days,
        min_count=min_count,
    )


def print_result(r: WalkForwardResult) -> None:
    print(f"=== Walk-forward result ===")
    print(f"  Train window: {r.train_window_days}d, Re-train every: {r.retrain_freq_days}d, min_count: {r.min_count}")
    print(f"  Test: {r.n_test_cuts} cuts, {r.n_test_records} records")
    print(f"  Brier 12h: {r.brier_12h:.4f} (baseline {r.brier_12h_baseline:.4f}, lift {100*(1-r.brier_12h/r.brier_12h_baseline):.1f}%)")
    print(f"  Brier  D:  {r.brier_D:.4f} (baseline {r.brier_D_baseline:.4f}, lift {100*(1-r.brier_D/r.brier_D_baseline):.1f}%)")
    print(f"  Top-5 hit_D:  {r.top5_hit_D_mean:.3f} vs random {r.random5_hit_D_mean:.3f}  (lift {r.top5_hit_D_mean/max(r.random5_hit_D_mean, 1e-6):.1f}x)")
    print(f"  Top-5 hit_12h: {r.top5_hit_12h_mean:.3f}")
    print(f"  Top-3 ABOVE hit_D: {r.top3_above_hit_D_mean:.3f}")
    print(f"  Top-3 BELOW hit_D: {r.top3_below_hit_D_mean:.3f}")
    print(f"\n  Reliability D (calibration):")
    print(r.reliability_D.to_string(index=False))
