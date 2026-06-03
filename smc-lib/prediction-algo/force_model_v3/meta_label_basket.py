"""
Meta-labeling Lopez de Prado Ch 3.6 поверх rule-based C1-C7 basket.

Primary = C1-C7 basket из ~/Desktop/pred12h_baseline_c1c7.parquet (657 in-basket, P=66.8% in-sample)
Secondary = binary classifier с features
Target = filter basket positives by P(confirmed pivot)

Train: in-sample period (2020-06..2026-02, 613 in-basket candidates)
Test: out-of-sample (2026-02..2026-06, 44 in-basket candidates)
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from data import load_btc_1m  # noqa: E402
from resample import resample_one  # noqa: E402
from force_model_v3.targets_22 import SHORT_TARGETS, LONG_TARGETS  # noqa: E402


def add_candle_features(df_basket: pd.DataFrame, df_12h: pd.DataFrame) -> pd.DataFrame:
    """Добавить candle-level features для каждого pivot."""
    # ATR(14)
    high = df_12h["high"]; low = df_12h["low"]; close = df_12h["close"]
    prev_c = close.shift(1)
    tr = pd.concat([high-low, (high-prev_c).abs(), (low-prev_c).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=14).mean()

    out_rows = []
    for _, p in df_basket.iterrows():
        ts = p["pivot_open_ts"]
        if ts not in df_12h.index:
            continue
        idx = df_12h.index.get_loc(ts)
        r = df_12h.iloc[idx]
        atr = float(atr14.iloc[idx]) if idx >= 14 and pd.notna(atr14.iloc[idx]) else 0.0
        if atr <= 0:
            continue

        # Candle context
        body = abs(r["close"] - r["open"])
        rng = r["high"] - r["low"]
        is_bull = r["close"] > r["open"]

        # Cumulative move before
        N_back = 10
        if idx >= N_back + 1:
            cum_move = abs(float(df_12h["close"].iloc[idx-1]) - float(df_12h["close"].iloc[idx-N_back-1])) / atr
        else:
            cum_move = 0.0

        # Compression (recent ATR vs long ATR)
        atr_short_idx = max(0, idx-5)
        atr_long_idx = max(0, idx-30)
        atr_short = float(atr14.iloc[atr_short_idx:idx].mean()) if idx > atr_short_idx else atr
        atr_long = float(atr14.iloc[atr_long_idx:idx].mean()) if idx > atr_long_idx else atr
        compression = atr_short / atr_long if atr_long > 0 else 1.0

        # Range/body ratio
        r_b_ratio = rng / max(body, atr * 0.01)

        # Position of close in range
        close_pos = (r["close"] - r["low"]) / max(rng, 1.0) if rng > 0 else 0.5

        # Volume features (если есть)
        vol = float(r.get("volume", 0))
        vol_norm = vol / df_12h["volume"].iloc[max(0, idx-20):idx].mean() if idx >= 20 else 1.0
        if not np.isfinite(vol_norm): vol_norm = 1.0

        # Session
        session = int(ts.hour < 12)

        out_rows.append({
            **p.to_dict(),
            "body_atr": body / atr,
            "range_atr": rng / atr,
            "candle_dir": int(is_bull),
            "cum_move_atr": cum_move,
            "compression": compression,
            "r_b_ratio": r_b_ratio,
            "close_pos": close_pos,
            "vol_norm": vol_norm,
            "session": session,
            "atr14": atr,
        })
    return pd.DataFrame(out_rows)


def main():
    parquet_path = Path.home() / "Desktop" / "pred12h_baseline_c1c7.parquet"
    print(f"[1/4] Load basket parquet: {parquet_path}")
    df = pd.read_parquet(parquet_path)
    df["pivot_open_ts"] = pd.to_datetime(df["pivot_open_ts"], utc=True)
    print(f"  Total baseline pivots: {len(df)}")
    print(f"  Range: {df['pivot_open_ts'].min()} → {df['pivot_open_ts'].max()}")
    print(f"  in_basket: {df['in_basket'].sum()}  ({df['in_basket'].mean()*100:.1f}%)")
    print(f"  confirmed: {df['confirmed'].sum()}  ({df['confirmed'].mean()*100:.1f}%)")

    print(f"\n[2/4] Load 12h bars + add candle features...")
    df_1m = load_btc_1m(start="2020-05-01", end="2026-06-01")
    df_12h = resample_one(df_1m, "12h", pd.Timestamp("2026-06-01", tz="UTC"))

    # Filter to basket-only candidates (primary = basket says yes)
    df_basket = df[df["in_basket"]].copy()
    print(f"  Basket candidates: {len(df_basket)}")

    df_basket = add_candle_features(df_basket, df_12h)
    print(f"  With features: {len(df_basket)}")

    # Mark 22-targets
    targets_set = SHORT_TARGETS | LONG_TARGETS
    df_basket["is_target22"] = df_basket["pivot_open_ts"].isin(targets_set)
    print(f"  22-targets in basket: {df_basket['is_target22'].sum()}")

    print("\n[3/4] Train secondary on in-sample, test on 2026-02..2026-06")
    test_start = pd.Timestamp("2026-02-01", tz="UTC")
    train_mask = df_basket["pivot_open_ts"] < test_start
    test_mask = ~train_mask

    META_FEATURES = [
        "c1", "c2", "c3", "c4", "c5", "c6", "c7",  # individual basket conditions
        "body_atr", "range_atr", "candle_dir",
        "cum_move_atr", "compression", "r_b_ratio",
        "close_pos", "vol_norm", "session",
    ]
    # Count of fired conditions
    df_basket["n_conditions"] = df_basket[["c1","c2","c3","c4","c5","c6","c7"]].sum(axis=1)
    META_FEATURES.append("n_conditions")

    X_train = df_basket.loc[train_mask, META_FEATURES].fillna(0).astype(float).to_numpy()
    y_train = df_basket.loc[train_mask, "confirmed"].astype(int).to_numpy()
    X_test = df_basket.loc[test_mask, META_FEATURES].fillna(0).astype(float).to_numpy()
    y_test = df_basket.loc[test_mask, "confirmed"].astype(int).to_numpy()
    targets_test = df_basket.loc[test_mask, "is_target22"].astype(int).to_numpy()

    print(f"  Train: {train_mask.sum()}  confirmed: {y_train.sum()} ({y_train.mean()*100:.1f}%)")
    print(f"  Test:  {test_mask.sum()}  confirmed: {y_test.sum()} ({y_test.mean()*100:.1f}%)")
    print(f"  22-targets в test (in basket): {targets_test.sum()}")

    meta = LogisticRegression(C=1.0, max_iter=2000)
    meta.fit(X_train, y_train)
    p_train = meta.predict_proba(X_train)[:, 1]
    p_test = meta.predict_proba(X_test)[:, 1]
    auc_train = roc_auc_score(y_train, p_train) if len(np.unique(y_train))>1 else None
    auc_test = roc_auc_score(y_test, p_test) if len(np.unique(y_test))>1 else None
    print(f"\n  Meta AUC train={auc_train:.3f}  test={auc_test:.3f}")

    print(f"\n  Meta coefficients:")
    for feat, w in sorted(zip(META_FEATURES, meta.coef_[0]), key=lambda x: -abs(x[1])):
        print(f"    {feat:<20} = {w:+.4f}")

    print("\n[4/4] Comparison: basket-only (P=68.2%) vs basket+meta filtered")
    test_df = df_basket.loc[test_mask].copy()
    test_df["meta_p"] = p_test

    print(f"\n  Test basket candidates: {len(test_df)}")
    print(f"  Actual confirmed: {y_test.sum()}/{len(test_df)} = {y_test.mean()*100:.1f}%")

    # Threshold analysis
    print(f"\n  meta_p threshold  | n_selected  precision  recall  | 22-targets caught")
    for thr in [0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75]:
        sel = test_df[test_df["meta_p"] >= thr]
        n_sel = len(sel)
        if n_sel == 0:
            print(f"  thr ≥ {thr:.2f}        | 0          —          —      | 0/{int(targets_test.sum())}")
            continue
        prec = sel["confirmed"].mean()
        rec = sel["confirmed"].sum() / y_test.sum() if y_test.sum() > 0 else 0
        tg = int(sel["is_target22"].sum())
        print(f"  thr ≥ {thr:.2f}        | {n_sel:>3}        {prec*100:5.1f}%     {rec*100:5.1f}%  | {tg}/{int(targets_test.sum())}")

    # Top-N ranking
    print(f"\n  Top-N by meta_p (forced ranking):")
    for N in [10, 15, 20, 30]:
        top = test_df.nlargest(N, "meta_p")
        prec = top["confirmed"].mean()
        rec = top["confirmed"].sum() / y_test.sum() if y_test.sum() > 0 else 0
        tg = int(top["is_target22"].sum())
        print(f"  top-{N:<2}: confirmed {top['confirmed'].sum()}/{N} ({prec*100:.0f}%), recall {rec*100:.0f}%, targets {tg}/{int(targets_test.sum())}")

    # Comparison: random N picks vs meta-top-N
    print(f"\n  Random selection baseline (expected hits):")
    for N in [10, 15, 20, 30]:
        ev = N * y_test.mean()
        print(f"  random N={N}: expected {ev:.1f} confirmed")

    out = Path.home() / "Desktop" / "meta_label_basket.csv"
    test_df.to_csv(out, index=False)
    print(f"\nFull → {out}")


if __name__ == "__main__":
    main()
