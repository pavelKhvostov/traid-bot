"""Q1 test — Gaussian σ=R/2 force function as predictor of reaction.

Recompute force using Gaussian for each touch event, bucket by force value,
measure P(reaction = +1) per bucket. Check monotonic edge.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import pandas as pd

# Load datasets
df_events = pd.read_parquet(Path.home() / "Desktop/maxv_master_6m.parquet")
df_touches = pd.read_parquet(Path.home() / "Desktop/maxv_touches_6m.parquet")

# Join touches with events to get zone bounds
df = df_touches.merge(
    df_events[["tf", "formed_ts", "zone_lo", "zone_hi"]],
    on=["tf", "formed_ts"], how="left",
)
print(f"Touches: {len(df_touches)}, joined: {len(df)}")

# Gaussian force σ=R/2 where R = max(level-zone_lo, zone_hi-level)
def gaussian_force(touch_price, level, zone_lo, zone_hi):
    R = max(level - zone_lo, zone_hi - level)
    sigma = R / 2
    delta = abs(touch_price - level)
    return math.exp(-((delta / sigma) ** 2))

df["force_gauss"] = df.apply(
    lambda r: gaussian_force(r["touch_price"], r["level"], r["zone_lo"], r["zone_hi"]),
    axis=1,
)
df["force_linear"] = df["force"]  # rename existing

base_p_reaction = (df["label"] == 1).mean()
print(f"\nBase P(reaction = +1): {base_p_reaction*100:.2f}% ({(df['label']==1).sum()}/{len(df)})")

# Bucket by Gaussian force (quintiles) — without explicit labels (auto)
print("\n=== P(reaction) by Gaussian force quintile ===")
df["force_q"] = pd.qcut(df["force_gauss"], 5, duplicates="drop")
gb = df.groupby("force_q", observed=True).agg(
    n=("label", "size"),
    n_react=("label", lambda x: (x == 1).sum()),
    n_stop=("label", lambda x: (x == -1).sum()),
    p_react=("label", lambda x: (x == 1).mean()),
    mean_force=("force_gauss", "mean"),
)
gb["lift_pp"] = (gb["p_react"] - base_p_reaction) * 100
print(gb.round(3).to_string())

# Fixed thresholds
print("\n=== P(reaction) by Gaussian force threshold ===")
for thr in [0.1, 0.3, 0.5, 0.7, 0.85, 0.95]:
    sub = df[df["force_gauss"] >= thr]
    if len(sub) > 0:
        p = (sub["label"] == 1).mean()
        lift = (p - base_p_reaction) * 100
        print(f"  force ≥ {thr:.2f}: n={len(sub):>4}  P(react)={p*100:5.1f}%  lift={lift:+5.2f}pp")

# Correlation
from scipy.stats import spearmanr, pearsonr
df_pos = df[df["label"] != 0]  # exclude timeouts
sp_corr, sp_p = spearmanr(df_pos["force_gauss"], (df_pos["label"] == 1).astype(int))
pe_corr, pe_p = pearsonr(df_pos["force_gauss"], (df_pos["label"] == 1).astype(int))
print(f"\n=== Correlation Gaussian force vs reaction (label=+1) ===")
print(f"  Spearman: {sp_corr:+.4f} (p={sp_p:.4f})")
print(f"  Pearson:  {pe_corr:+.4f} (p={pe_p:.4f})")

# AUC
from sklearn.metrics import roc_auc_score
y = (df["label"] == 1).astype(int)
auc_gauss = roc_auc_score(y, df["force_gauss"])
auc_linear = roc_auc_score(y, df["force_linear"])
print(f"\n=== AUC (force value as score, target = reaction) ===")
print(f"  Gaussian σ=R/2: {auc_gauss:.4f}")
print(f"  Linear (current):  {auc_linear:.4f}")
print(f"  Random baseline: 0.5000")

# Save augmented dataset
out = Path.home() / "Desktop" / "maxv_touches_6m_with_gauss.parquet"
df.to_parquet(out, index=False)
print(f"\n→ {out}")
