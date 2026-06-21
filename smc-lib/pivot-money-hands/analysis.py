"""
EDA для pivot-money-hands.

Для каждой numeric MH-фичи: распределение в "будет pivot в 12h" vs "не будет".
Для категориальных (color): топ-комбинации.

Также: confluence-анализ — насколько часто многие TF "согласованы" (одинаковый color)
и есть ли связь с pivot-вероятностью.

CLI:
    python analysis.py --in /tmp/pivot_mh_strict.csv --label pivot_in_12h_short
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from multi_tf_mh import MH_FIELDS, PIVOT_TFS


def numeric_feature_summary(ds: pd.DataFrame, label_col: str) -> pd.DataFrame:
    """
    Для каждой numeric MH-фичи: mean / median / count в группах label=True vs label=False.
    Сортируется по абсолютному разнице средних (proxy для дискриминативности).
    """
    rows = []
    pos = ds[ds[label_col] == True]   # noqa: E712
    neg = ds[ds[label_col] == False]
    for tf in PIVOT_TFS:
        for fld in ("bw2", "mf", "rsi_mod", "stc_rsi_mod"):
            col = f"mh_{tf}_{fld}"
            if col not in ds.columns:
                continue
            p_vals = pd.to_numeric(pos[col], errors="coerce").dropna()
            n_vals = pd.to_numeric(neg[col], errors="coerce").dropna()
            if len(p_vals) < 5 or len(n_vals) < 5:
                continue
            mean_p, mean_n = p_vals.mean(), n_vals.mean()
            std_pooled = float(np.sqrt((p_vals.std()**2 + n_vals.std()**2) / 2))
            cohen_d = (mean_p - mean_n) / std_pooled if std_pooled > 0 else 0.0
            rows.append({
                "feature": col,
                "n_pos": len(p_vals), "n_neg": len(n_vals),
                "mean_pos": round(mean_p, 2), "mean_neg": round(mean_n, 2),
                "diff": round(mean_p - mean_n, 2),
                "cohen_d": round(cohen_d, 3),
            })
    out = pd.DataFrame(rows)
    out["abs_d"] = out["cohen_d"].abs()
    return out.sort_values("abs_d", ascending=False).drop(columns="abs_d")


def color_breakdown(ds: pd.DataFrame, label_col: str) -> pd.DataFrame:
    """Для каждого TF: какой % бар имеет color=X внутри label=True vs label=False."""
    rows = []
    pos = ds[ds[label_col] == True]   # noqa: E712
    neg = ds[ds[label_col] == False]
    for tf in PIVOT_TFS:
        col = f"mh_{tf}_color"
        if col not in ds.columns:
            continue
        for color in ("green", "white_weak_bull", "red", "white_weak_bear"):
            n_pos = int((pos[col] == color).sum())
            n_neg = int((neg[col] == color).sum())
            pct_pos = 100 * n_pos / max(len(pos), 1)
            pct_neg = 100 * n_neg / max(len(neg), 1)
            rows.append({
                "tf": tf, "color": color,
                "pct_pos": round(pct_pos, 1),
                "pct_neg": round(pct_neg, 1),
                "diff": round(pct_pos - pct_neg, 1),
            })
    out = pd.DataFrame(rows)
    out["abs_diff"] = out["diff"].abs()
    return out.sort_values("abs_diff", ascending=False).drop(columns="abs_diff")


def confluence_features(ds: pd.DataFrame) -> pd.DataFrame:
    """Добавить confluence-метрики: количество TF где color=green/red и средний bw2.
    Возвращает копию ds с новыми колонками."""
    out = ds.copy()
    color_cols = [f"mh_{tf}_color" for tf in PIVOT_TFS]
    bw2_cols = [f"mh_{tf}_bw2" for tf in PIVOT_TFS]
    out["n_green"] = (out[color_cols] == "green").sum(axis=1)
    out["n_red"] = (out[color_cols] == "red").sum(axis=1)
    out["n_bullish"] = ((out[color_cols] == "green") | (out[color_cols] == "white_weak_bull")).sum(axis=1)
    out["n_bearish"] = ((out[color_cols] == "red") | (out[color_cols] == "white_weak_bear")).sum(axis=1)
    out["mean_bw2"] = out[bw2_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    out["mean_stc_rsi"] = out[[f"mh_{tf}_stc_rsi_mod" for tf in PIVOT_TFS]].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--label", default="pivot_in_12h_short", help="какой label анализировать")
    args = p.parse_args()

    ds = pd.read_csv(args.inp)
    ds[args.label] = ds[args.label].astype(bool)
    print(f"Dataset: {ds.shape}, label={args.label}")
    print(f"Label balance: pos={ds[args.label].sum()}/{len(ds)} ({100*ds[args.label].mean():.1f}%)")

    print(f"\n=== NUMERIC FEATURE DIFFERENCES (sorted by |Cohen's d|) ===")
    print(numeric_feature_summary(ds, args.label).head(20).to_string(index=False))

    print(f"\n=== COLOR BREAKDOWN (top differences) ===")
    print(color_breakdown(ds, args.label).head(15).to_string(index=False))

    print(f"\n=== CONFLUENCE METRICS ===")
    cf = confluence_features(ds)
    pos = cf[cf[args.label] == True]
    neg = cf[cf[args.label] == False]
    for col in ("n_green", "n_red", "n_bullish", "n_bearish", "mean_bw2", "mean_stc_rsi"):
        if col not in cf.columns:
            continue
        p_m = float(pd.to_numeric(pos[col], errors="coerce").mean())
        n_m = float(pd.to_numeric(neg[col], errors="coerce").mean())
        print(f"  {col:15s}: pos={p_m:6.2f}  neg={n_m:6.2f}  diff={p_m - n_m:+.2f}")


if __name__ == "__main__":
    main()
