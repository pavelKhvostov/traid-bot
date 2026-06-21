"""HMA feature audit:
  - Inventory: per-TF / per-length / per-derivative breakdown
  - Coverage (% non-NaN) per feature
  - Distribution stats (mean / std / range)
  - Per-asset coverage (BTC vs ETH)
  - Per-regime distribution (pre_2023 / post_2023)
  - Correlation clusters (highly correlated groups)
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd


SRC = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v15/feature_dataset_v1.parquet")


def main():
    df = pd.read_parquet(SRC)
    print("=" * 72)
    print("HMA Feature Audit")
    print("=" * 72)
    print(f"Total dataset: {len(df):,} events  ×  {df.shape[1]} cols")

    # Filter HMA-family columns only
    hma_cols = [c for c in df.columns if c.startswith("hma_") or c.startswith("aligned_") or c.startswith("slope_coherence_")]
    print(f"HMA-family columns: {len(hma_cols)}")
    print()

    # Parse hma_{tf}_{L}_{kind} ─────────
    inventory = []
    for c in hma_cols:
        parts = c.split("_")
        if c.startswith("hma_"):
            # hma_{tf}_{L}_{kind1}_{kind2?...}
            tf = parts[1]
            L = parts[2]
            kind = "_".join(parts[3:])
            inventory.append({"col": c, "family": "hma", "tf": tf, "len": L, "kind": kind})
        elif c.startswith("aligned_") or c.startswith("slope_coherence_"):
            inventory.append({"col": c, "family": "aggregate", "tf": "-", "len": "-", "kind": c})
    inv = pd.DataFrame(inventory)

    # ─── 1. Per-TF inventory ────────────────────────────
    print("── 1. Per-TF coverage ──")
    print(f"{'TF':<5} {'features':>9} {'lengths used':<60}")
    print("-" * 80)
    for tf in ["15m", "1h", "2h", "4h", "6h", "12h", "1d", "2d", "3d", "w"]:
        sub = inv[(inv.tf == tf) & (inv.family == "hma")]
        if len(sub) == 0:
            continue
        lens = sorted(set(sub.len), key=lambda x: int(x))
        print(f"{tf:<5} {len(sub):>9} {','.join(lens):<60}")

    # ─── 2. Per-derivative inventory ────────────────────
    print("\n── 2. Per-derivative kinds ──")
    print(f"{'kind':<15} {'count':>6}")
    print("-" * 25)
    for kind, count in inv[inv.family == "hma"].kind.value_counts().items():
        print(f"{kind:<15} {count:>6}")

    # ─── 3. Coverage per feature ────────────────────────
    print("\n── 3. Coverage (% non-NaN) — bottom 15 features ──")
    coverage = df[hma_cols].notna().mean().sort_values()
    print(f"{'feature':<35} {'coverage':>10}")
    print("-" * 50)
    for col, cov in coverage.head(15).items():
        print(f"{col:<35} {cov*100:>9.1f}%")

    print("\n── 4. Coverage by asset ──")
    btc = df[df.asset == "BTC"]
    eth = df[df.asset == "ETH"]
    for tf in ["15m", "1h", "12h", "1d", "w"]:
        col = f"hma_{tf}_200_value"
        if col not in df.columns:
            continue
        cb = btc[col].notna().mean() * 100
        ce = eth[col].notna().mean() * 100
        print(f"  {col:<25}  BTC={cb:>5.1f}%  ETH={ce:>5.1f}%")

    # ─── 5. Distribution stats for key features ─────────
    print("\n── 5. Distribution stats — key dist_pct features (% от HMA) ──")
    print(f"{'feature':<25} {'mean':>8} {'std':>8} {'p1':>8} {'p99':>8}")
    print("-" * 65)
    for tf in ["15m", "1h", "4h", "12h", "1d", "w"]:
        col = f"hma_{tf}_200_dist_pct"
        if col not in df.columns:
            continue
        v = df[col].dropna()
        print(f"{col:<25} {v.mean():>+7.2f} {v.std():>7.2f} "
              f"{v.quantile(0.01):>+7.2f} {v.quantile(0.99):>+7.2f}")

    # ─── 6. Per-regime stats for key features ───────────
    print("\n── 6. dist_pct hma_1d_200 by regime ──")
    for r in ["pre_2023", "post_2023"]:
        v = df[df.regime == r]["hma_1d_200_dist_pct"].dropna()
        print(f"  {r}: n={len(v):,}  mean={v.mean():+.2f}%  std={v.std():.2f}%")

    # ─── 7. Correlation cluster sample ──────────────────
    print("\n── 7. Top correlation pairs (within same TF) ──")
    # Sample for performance: take aligned_*, dist_pct, slope features
    keep = [c for c in hma_cols if any(k in c for k in ["_dist_pct", "_slope5_pct", "_above", "aligned_", "slope_coherence_"])]
    sub = df[keep].select_dtypes(include=[float, int]).dropna(thresh=int(len(df)*0.5), axis=1)
    print(f"  cor matrix over {sub.shape[1]} non-sparse features...")
    corr_arr = sub.corr().abs().to_numpy().copy()
    np.fill_diagonal(corr_arr, 0)
    corr = pd.DataFrame(corr_arr, index=sub.columns, columns=sub.columns)
    # find top pairs
    pairs = []
    for i in range(len(corr)):
        for j in range(i+1, len(corr)):
            r = corr.iloc[i, j]
            if r > 0.95:
                pairs.append((corr.columns[i], corr.columns[j], r))
    pairs.sort(key=lambda x: -x[2])
    print(f"  pairs with |r| > 0.95: {len(pairs):,}")
    for a, b, r in pairs[:15]:
        print(f"    {r:.3f}  {a}  ↔  {b}")


if __name__ == "__main__":
    main()
