"""
Direction prediction: будет ли BTC ВЫШЕ или НИЖЕ через 6h / 12h.

Target labels:
  - direction_6h: 'up' если close[t+6h] > close[t] * (1+thr), 'down' если < (1-thr), else 'flat'
  - direction_12h: то же на 12h
  (thr задаётся параметром, по умолчанию 0.5%)

Также бинарные binary labels (без flat):
  - up_6h: bool
  - up_12h: bool

Использует существующие MH features из dataset.py.

Train: HistGradientBoostingClassifier на 35 MH-фичах + 7 color (=42 столбца).
Walk-forward validation.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, brier_score_loss, accuracy_score

from model import prepare_xy, feature_columns
from multi_tf_mh import PIVOT_TFS


def add_direction_labels(
    ds: pd.DataFrame,
    df_1m: pd.DataFrame,
    horizons_h: tuple[int, ...] = (6, 12),
    flat_threshold_pct: float = 0.5,
) -> pd.DataFrame:
    """
    Добавить return и direction labels для каждого 1h bar в ds.

    Используем 1m данные для точного hi/lo и close в момент t+H.
    Также считаем max_up_pct / max_down_pct (excursions).
    """
    ds = ds.copy()
    ds["bar_ts"] = pd.to_datetime(ds["bar_ts"], utc=True)

    # 1h cut-off = bar_ts + 1h (закрытие бара)
    df_1m = df_1m.copy()
    df_1m.index = pd.to_datetime(df_1m.index, utc=True)

    # Префетчим closes
    closes_at_ts: dict[pd.Timestamp, float] = {}

    def close_at(ts: pd.Timestamp) -> float | None:
        # Берём close последней 1m bar чей open < ts
        seg = df_1m.loc[df_1m.index < ts]
        if seg.empty:
            return None
        return float(seg["close"].iloc[-1])

    for H in horizons_h:
        rets = []
        max_up = []
        max_dn = []
        dirs = []
        ups = []
        thr = flat_threshold_pct / 100
        for ts in ds["bar_ts"]:
            c0_ts = ts + pd.Timedelta(hours=1)
            c1_ts = c0_ts + pd.Timedelta(hours=H)
            c0 = close_at(c0_ts)
            if c0 is None:
                rets.append(np.nan); max_up.append(np.nan); max_dn.append(np.nan)
                dirs.append("flat"); ups.append(False)
                continue
            # сегмент 1m [c0_ts, c1_ts]
            seg = df_1m.loc[(df_1m.index >= c0_ts) & (df_1m.index < c1_ts)]
            if seg.empty:
                rets.append(np.nan); max_up.append(np.nan); max_dn.append(np.nan)
                dirs.append("flat"); ups.append(False)
                continue
            c1 = float(seg["close"].iloc[-1])
            ret = (c1 - c0) / c0
            max_up_pct = (seg["high"].max() - c0) / c0
            max_dn_pct = (c0 - seg["low"].min()) / c0
            d = "up" if ret > thr else ("down" if ret < -thr else "flat")
            rets.append(ret); max_up.append(max_up_pct); max_dn.append(max_dn_pct)
            dirs.append(d); ups.append(ret > 0)
        ds[f"return_{H}h"] = rets
        ds[f"max_up_{H}h_pct"] = max_up
        ds[f"max_down_{H}h_pct"] = max_dn
        ds[f"direction_{H}h"] = dirs
        ds[f"up_{H}h"] = ups
    return ds


def walk_forward_binary(
    ds: pd.DataFrame,
    label_col: str,
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
) -> pd.DataFrame:
    """Walk-forward по бинарной задаче. Возвращает DataFrame per fold с метриками."""
    ds = ds.sort_values("bar_ts").reset_index(drop=True)
    ds[label_col] = ds[label_col].astype(int)

    start = ds["bar_ts"].iloc[0] + pd.Timedelta(days=train_days)
    end = ds["bar_ts"].iloc[-1] - pd.Timedelta(days=test_days)
    cur = start
    cat_features = [f"mh_{tf}_color" for tf in PIVOT_TFS]
    folds = []

    while cur < end:
        train = ds[(ds["bar_ts"] >= cur - pd.Timedelta(days=train_days)) & (ds["bar_ts"] < cur)]
        test = ds[(ds["bar_ts"] >= cur) & (ds["bar_ts"] < cur + pd.Timedelta(days=test_days))]
        cur += pd.Timedelta(days=step_days)
        if len(train) < 500 or len(test) < 50:
            continue

        X_tr, y_tr = prepare_xy(train, label_col)
        X_te, y_te = prepare_xy(test, label_col)
        if y_tr.nunique() < 2 or y_te.nunique() < 2:
            continue
        cat_mask = [c in cat_features for c in X_tr.columns]
        clf = HistGradientBoostingClassifier(
            max_iter=300, max_depth=4, learning_rate=0.05,
            categorical_features=cat_mask, random_state=42,
        )
        clf.fit(X_tr, y_tr)
        p = clf.predict_proba(X_te)[:, 1]
        pred = (p > 0.5).astype(int)
        baseline = float(y_tr.mean())
        folds.append({
            "test_start": test["bar_ts"].iloc[0],
            "test_end": test["bar_ts"].iloc[-1],
            "n_train": len(train), "n_test": len(test),
            "baseline_pos": baseline,
            "auc": roc_auc_score(y_te, p),
            "acc": accuracy_score(y_te, pred),
            "brier": brier_score_loss(y_te, p),
            "brier_baseline": brier_score_loss(y_te, np.full(len(y_te), baseline)),
        })
    return pd.DataFrame(folds)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True, help="dataset CSV (нужен MH snapshot + bar_ts)")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--flat-threshold", type=float, default=0.5, help="percent threshold for flat class")
    p.add_argument("--train-days", type=int, default=180)
    p.add_argument("--test-days", type=int, default=30)
    args = p.parse_args()

    print(f"Loading MH dataset: {args.inp}")
    ds = pd.read_csv(args.inp)

    print(f"Loading 1m BTC data...")
    import sys, os
    from pathlib import Path
    sys.path.insert(0, str(Path.home() / "smc-lib" / "prediction-algo"))
    from data import load_btc_1m
    df_1m = load_btc_1m(
        start=pd.Timestamp(args.start, tz="UTC") - pd.Timedelta(days=1),
        end=pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=2),
    )
    print(f"  1m rows: {len(df_1m)}")

    print(f"Adding direction labels (threshold={args.flat_threshold}%)...")
    ds = add_direction_labels(ds, df_1m, horizons_h=(6, 12), flat_threshold_pct=args.flat_threshold)
    ds = ds.dropna(subset=["return_12h"])

    print(f"\n=== LABEL DISTRIBUTIONS ===")
    for H in (6, 12):
        col = f"direction_{H}h"
        print(f"  {col}: {dict(ds[col].value_counts())}")
        rets = ds[f"return_{H}h"]
        print(f"    mean ret: {rets.mean()*100:+.3f}%   p50: {rets.median()*100:+.3f}%   p10/p90: {rets.quantile(0.1)*100:+.2f}/{rets.quantile(0.9)*100:+.2f}%")

    for label in ["up_6h", "up_12h"]:
        print(f"\n=== WALK-FORWARD: {label} ===")
        folds = walk_forward_binary(ds, label, train_days=args.train_days, test_days=args.test_days)
        if folds.empty:
            print("  (no folds)")
            continue
        print(f"  Folds: {len(folds)}")
        print(f"  AUC:    mean={folds['auc'].mean():.3f}   median={folds['auc'].median():.3f}   range={folds['auc'].min():.3f}..{folds['auc'].max():.3f}")
        print(f"  Acc:    mean={folds['acc'].mean():.3f}   baseline (always majority)={max(folds['baseline_pos'].mean(), 1-folds['baseline_pos'].mean()):.3f}")
        print(f"  Brier:  mean={folds['brier'].mean():.4f}  vs baseline {folds['brier_baseline'].mean():.4f}")
        # фолд с лучшим AUC
        best = folds.sort_values("auc", ascending=False).head(3)
        print(f"  Top-3 folds by AUC:")
        for _, row in best.iterrows():
            print(f"    {row['test_start'].date()}..{row['test_end'].date()}: AUC={row['auc']:.3f}  Acc={row['acc']:.3f}")


if __name__ == "__main__":
    main()
