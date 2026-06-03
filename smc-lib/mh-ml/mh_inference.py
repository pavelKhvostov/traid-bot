"""MH multi-horizon inference + narrative output.

Workflow:
  1. Build features на полных historical данных
  2. Build labels (для cohort analysis)
  3. Train 6 models на последних train_window_days данных
  4. Predict для текущего cut-off (последний 15m timestamp)
  5. Cohort analysis: найти исторические похожие моменты, агрегировать их fwd-moves
  6. Format narrative output (human-readable)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

MH_ML = Path(__file__).resolve().parent
sys.path.insert(0, str(MH_ML))

from mh_features import build_features, TFS_8  # noqa: E402
from mh_labels import build_labels, HORIZONS_HOURS  # noqa: E402


@dataclass
class HorizonPrediction:
    horizon_hours: int
    pred_pct: float                  # точечный прогноз (regression output)
    direction_up_prob: float         # P(price>now) — оценка через cohort
    cohort_n: int                    # сколько исторических соседей в когорте
    cohort_median_pct: float
    cohort_p25: float
    cohort_p75: float


@dataclass
class MhInferenceResult:
    cut_off_ts: pd.Timestamp
    price_now: float
    feature_vector: pd.Series         # текущие фичи
    per_horizon: list[HorizonPrediction]
    models_trained_at: pd.Timestamp


def train_and_predict(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    train_window_days: int = 1825,
    horizons_hours: tuple[int, ...] = HORIZONS_HOURS,
    cohort_k: int = 50,
) -> MhInferenceResult:
    """Train на rolling train_window_days до последнего timestamp, predict для последней свечи + cohort."""
    df = features.join(labels, how="inner")
    df = df[~df["bw2_15m"].isna()]
    feature_cols = features.columns.tolist()

    cut_off_ts = df.index[-1]
    train_lo = cut_off_ts - pd.Timedelta(days=train_window_days)
    train_data = df[(df.index >= train_lo) & (df.index < cut_off_ts)]
    if len(train_data) < 100:
        raise ValueError(f"Too few train rows ({len(train_data)}) — need more historical data")

    X_train = train_data[feature_cols].to_numpy()
    X_current = df.loc[[cut_off_ts], feature_cols].to_numpy()
    feature_vec = df.loc[cut_off_ts, feature_cols]

    per_horizon = []
    for h in horizons_hours:
        label_col = f"pct_{h}h"
        y_train = train_data[label_col].to_numpy()
        train_valid = ~np.isnan(y_train)
        if train_valid.sum() < 100:
            continue

        # Train model
        model = HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
            min_samples_leaf=20, verbose=0, random_state=42,
        )
        model.fit(X_train[train_valid], y_train[train_valid])
        pred_pct = float(model.predict(X_current)[0])

        # Cohort analysis (KNN на feature space)
        # Простая реализация: cosine distance в подмножестве continuous features
        cont_cols = [c for c in feature_cols if any(c.startswith(p) for p in ["bw2_", "mf_", "rsi_mod_", "stc_rsi_mod_"])
                     and not any(c.startswith(p) for p in ["bw2_sign_", "mf_sign_", "rsi_in_", "stc_in_", "rsi_above_"])]
        X_cont = train_data[cont_cols].fillna(0).to_numpy()
        X_cur_cont = df.loc[cut_off_ts, cont_cols].fillna(0).to_numpy().reshape(1, -1)
        norms = np.linalg.norm(X_cont, axis=1)
        cur_norm = np.linalg.norm(X_cur_cont)
        sims = (X_cont @ X_cur_cont.T).flatten() / (norms * cur_norm + 1e-9)
        # Take top-k by similarity, valid label only
        y_for_cohort = train_data[label_col].to_numpy()
        cohort_valid = ~np.isnan(y_for_cohort)
        sims_valid = sims[cohort_valid]
        y_valid = y_for_cohort[cohort_valid]
        if len(y_valid) > cohort_k:
            top_idx = np.argpartition(sims_valid, -cohort_k)[-cohort_k:]
            cohort_y = y_valid[top_idx]
        else:
            cohort_y = y_valid

        cohort_n = len(cohort_y)
        cohort_median = float(np.median(cohort_y)) if cohort_n > 0 else 0.0
        cohort_p25 = float(np.percentile(cohort_y, 25)) if cohort_n > 0 else 0.0
        cohort_p75 = float(np.percentile(cohort_y, 75)) if cohort_n > 0 else 0.0
        prob_up = float(np.mean(cohort_y > 0)) if cohort_n > 0 else 0.5

        per_horizon.append(HorizonPrediction(
            horizon_hours=h,
            pred_pct=pred_pct,
            direction_up_prob=prob_up,
            cohort_n=cohort_n,
            cohort_median_pct=cohort_median,
            cohort_p25=cohort_p25,
            cohort_p75=cohort_p75,
        ))

    # Price now — берём последний close
    # (предполагаем что features построены на 15m grid, цена в момент grid close)
    # Здесь price_now НЕ хранится в features, придётся передавать снаружи

    return MhInferenceResult(
        cut_off_ts=cut_off_ts,
        price_now=0.0,    # caller заполнит
        feature_vector=feature_vec,
        per_horizon=per_horizon,
        models_trained_at=cut_off_ts,
    )


def format_narrative(
    result: MhInferenceResult,
    price_now: float,
) -> str:
    """Форматировать narrative output (Russian)."""
    lines = []
    lines.append("=" * 75)
    lines.append(f"  MH EXPERT AGENT — BTC {price_now:,.0f}   |   cut_off {result.cut_off_ts}")
    lines.append("=" * 75)
    lines.append("")
    lines.append("ТЕКУЩЕЕ СОСТОЯНИЕ MH (8 TFs)")
    lines.append("-" * 75)
    f = result.feature_vector
    for tf in TFS_8:
        bw2 = f.get(f"bw2_{tf}", float("nan"))
        mf = f.get(f"mf_{tf}", float("nan"))
        rsi = f.get(f"rsi_mod_{tf}", float("nan"))
        stc = f.get(f"stc_rsi_mod_{tf}", float("nan"))
        in_ob = "OB" if f.get(f"in_OB_{tf}", 0) else ("OS" if f.get(f"in_OS_{tf}", 0) else "—")
        bw2_str = f"{bw2:+.1f}" if pd.notna(bw2) else "  N/A"
        mf_str = f"{mf:+.1f}" if pd.notna(mf) else "  N/A"
        rsi_str = f"{rsi:.0f}" if pd.notna(rsi) else "N/A"
        stc_str = f"{stc:.0f}" if pd.notna(stc) else "N/A"
        lines.append(f"  {tf:>3}: bw2={bw2_str:>7}  MF={mf_str:>7}  rsi={rsi_str:>3}  stc={stc_str:>3}  [{in_ob}]")
    lines.append("")

    # Cross-TF aggregates
    lines.append("CROSS-TF AGGREGATES")
    lines.append("-" * 75)
    cons = int(f.get("bw2_consensus", 0))
    ob_cnt = int(f.get("n_TFs_in_OB", 0))
    os_cnt = int(f.get("n_TFs_in_OS", 0))
    cas_bull = f.get("cascade_bull_freshness_h", 9999)
    cas_bear = f.get("cascade_bear_freshness_h", 9999)
    lines.append(f"  bw2_consensus: {cons:+d}/8     n_OB: {ob_cnt}/8     n_OS: {os_cnt}/8")
    lines.append(f"  cascade_bull_freshness: {cas_bull:.1f}h   cascade_bear_freshness: {cas_bear:.1f}h")
    lines.append("")

    # Multi-horizon predictions
    lines.append("ПРОГНОЗ (multi-horizon)")
    lines.append("-" * 75)
    lines.append(f"  {'Горизонт':<10}{'ML pred':>10}{'cohort med':>12}{'cohort 25-75':>20}{'P(up)':>10}{'N':>6}")
    for hp in result.per_horizon:
        h_str = f"{hp.horizon_hours}h"
        lines.append(
            f"  {h_str:<10}{hp.pred_pct:>+9.2f}%{hp.cohort_median_pct:>+11.2f}%"
            f"   [{hp.cohort_p25:+.2f}%, {hp.cohort_p75:+.2f}%]   "
            f"{hp.direction_up_prob:>6.0%}    {hp.cohort_n:>4d}"
        )
    lines.append("")
    lines.append("=" * 75)
    return "\n".join(lines)


if __name__ == "__main__":
    # Standalone usage: load data, build features+labels, train+predict, print narrative
    sys.path.insert(0, str(MH_ML.parent / "prediction-algo"))
    from data import load_btc_1m

    print("Loading 1m BTC...")
    df = load_btc_1m()
    print(f"  {len(df):,} bars")

    print("Building features...")
    feat = build_features(df)
    print(f"  features: {feat.shape}")

    print("Building labels...")
    lbl = build_labels(df)
    print(f"  labels: {lbl.shape}")

    print("Training + predicting...")
    result = train_and_predict(feat, lbl, train_window_days=1825)

    price_now = float(df["close"].iloc[-1])
    print(format_narrative(result, price_now))
