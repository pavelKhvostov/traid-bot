"""Прямой контраст: что общего у winners vs losers.

Логика:
  1. Для каждой фичи — distribution winners vs losers
  2. Найти фичи с максимальным разделением (мера: difference in means / pooled std)
  3. Per-feature: разбить на 4 квартиля → WR per quartile
  4. Найти combinations features где WR > 70% при N ≥ 200
"""
from __future__ import annotations
import pathlib
import warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

SRC = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v4_comprehensive_btc_eth.parquet")
OUT = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/winners_vs_losers_analysis")
OUT.mkdir(exist_ok=True)

META_COLS = {
    "event_id", "asset", "born_ms", "entry_fill_ms", "direction",
    "t_id", "n_comp", "extreme", "entry", "R", "r_pct", "r_pct_pass",
    "fill_touched", "mfe_R", "mae_R", "sl_hit", "exit_reason",
    "hit_RR_10", "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
    "hit_RR_23", "hit_RR_25", "hit_RR_28",
}


def discriminator_score(values_win, values_loss):
    """Cohen's d — стандартизованная разница средних. >0.2 заметно, >0.5 large."""
    m_w = np.nanmean(values_win); m_l = np.nanmean(values_loss)
    s_w = np.nanstd(values_win); s_l = np.nanstd(values_loss)
    n_w = (~np.isnan(values_win)).sum(); n_l = (~np.isnan(values_loss)).sum()
    if n_w < 30 or n_l < 30: return np.nan, np.nan
    pooled = np.sqrt(((n_w - 1) * s_w**2 + (n_l - 1) * s_l**2) / (n_w + n_l - 2))
    if pooled < 1e-9: return 0.0, np.nan
    d = (m_w - m_l) / pooled
    # p-value via t-test
    _, p = stats.ttest_ind(values_win[~np.isnan(values_win)],
                             values_loss[~np.isnan(values_loss)],
                             equal_var=False)
    return float(d), float(p)


def main():
    print("=" * 72)
    print("Прямой контраст: winners vs losers (RR=1 canon, hit_RR_10)")
    print("=" * 72)

    df = pd.read_parquet(SRC)
    df_v = df[df.fill_touched & df.r_pct_pass].reset_index(drop=True)
    print(f"\nViable events: {len(df_v):,}")
    if "hit_RR_10" not in df_v.columns:
        df_v["hit_RR_10"] = (df_v.mfe_R >= 1.0).astype(int)

    n_wins = int(df_v.hit_RR_10.sum())
    n_loss = len(df_v) - n_wins
    print(f"Winners: {n_wins:,}  Losers: {n_loss:,}  baseline WR: {n_wins/len(df_v)*100:.1f}%")

    feat_cols = [c for c in df_v.columns if c not in META_COLS]
    print(f"Features to analyze: {len(feat_cols)}")

    # ─── Step 1: Cohen's d for each feature ────
    print("\n[1/3] Computing per-feature discriminator (Cohen's d + p-value)...")
    wins_mask = df_v.hit_RR_10 == 1
    rows = []
    for c in feat_cols:
        vals = df_v[c].to_numpy()
        v_w = vals[wins_mask]
        v_l = vals[~wins_mask]
        d, p = discriminator_score(v_w, v_l)
        if np.isnan(d): continue
        m_w = np.nanmean(v_w); m_l = np.nanmean(v_l)
        rows.append({
            "feature": c,
            "cohens_d": d,
            "p_value": p,
            "mean_winners": m_w,
            "mean_losers": m_l,
            "delta_mean": m_w - m_l,
        })
    scores = pd.DataFrame(rows).sort_values("cohens_d", key=lambda x: x.abs(), ascending=False)
    scores.to_csv(OUT / "feature_discriminator_scores.csv", index=False)

    print(f"\n  Top 25 by |Cohen's d| (большее = сильнее разделение):")
    print(scores.head(25).to_string(index=False))

    # ─── Step 2: Quartile WR per top feature ────
    print(f"\n[2/3] Quartile WR for top-20 discriminating features...")
    top20 = scores.head(20).feature.tolist()
    qrows = []
    for f in top20:
        vals = df_v[f].to_numpy()
        m = ~np.isnan(vals)
        if m.sum() < 100: continue
        sub = df_v[m].copy()
        try:
            sub["q"] = pd.qcut(sub[f], q=4, duplicates="drop")
        except Exception:
            continue
        for q_name, g in sub.groupby("q"):
            qrows.append({
                "feature": f,
                "quartile": str(q_name),
                "n": len(g),
                "wr": g.hit_RR_10.mean() * 100,
                "wins": int(g.hit_RR_10.sum()),
            })
    qdf = pd.DataFrame(qrows)
    qdf.to_csv(OUT / "feature_quartile_wr.csv", index=False)
    # Show table per feature
    print("\n  WR per quartile (top-20 features):")
    print(f"  {'feature':<32} quartile WRs (low → high)")
    for f in top20:
        q_sub = qdf[qdf.feature == f].copy()
        if len(q_sub) == 0: continue
        wrs_str = "  ".join(f"{r.wr:.1f}%(N={r.n})" for _, r in q_sub.iterrows())
        print(f"  {f:<32} {wrs_str}")

    # ─── Step 3: Search 2-3 feature combos for WR > 70% ────
    print(f"\n[3/3] Searching 2-feature combinations for WR > 70% (N ≥ 200)...")
    top10 = scores.head(10).feature.tolist()
    combos = []
    for i, f1 in enumerate(top10):
        for f2 in top10[i+1:]:
            for q1 in [0.25, 0.5, 0.75]:
                for q2 in [0.25, 0.5, 0.75]:
                    v1 = df_v[f1].to_numpy(); v2 = df_v[f2].to_numpy()
                    m1 = ~np.isnan(v1); m2 = ~np.isnan(v2)
                    valid = m1 & m2
                    if valid.sum() < 200: continue
                    # Try 4 quadrant directions
                    for c1_high in [True, False]:
                        for c2_high in [True, False]:
                            t1 = np.nanquantile(v1, q1)
                            t2 = np.nanquantile(v2, q2)
                            mask = valid.copy()
                            if c1_high: mask &= v1 >= t1
                            else: mask &= v1 <= t1
                            if c2_high: mask &= v2 >= t2
                            else: mask &= v2 <= t2
                            n = mask.sum()
                            if n < 200: continue
                            wr = df_v[mask].hit_RR_10.mean()
                            if wr >= 0.65:
                                combos.append({
                                    "feat1": f1, "q1": q1, "c1_high": c1_high,
                                    "feat2": f2, "q2": q2, "c2_high": c2_high,
                                    "n": int(n), "wr": float(wr),
                                })
    cdf = pd.DataFrame(combos).sort_values("wr", ascending=False)
    cdf.to_csv(OUT / "two_feature_combos_wr65plus.csv", index=False)

    print(f"\n  Found {len(cdf)} 2-feature combinations with WR ≥ 65% (N ≥ 200)")
    if len(cdf) > 0:
        print(f"\n  Top 20:")
        for _, row in cdf.head(20).iterrows():
            print(f"  WR {row.wr*100:5.1f}%  N {row.n:>4}  "
                  f"({row.feat1[:25]:<25} {'≥' if row.c1_high else '≤'} q{row.q1}  AND  "
                  f"{row.feat2[:25]:<25} {'≥' if row.c2_high else '≤'} q{row.q2})")
    else:
        print("  ❌ Ни одна 2-feature комбинация не даёт WR ≥ 65% на N ≥ 200")
        print("     Это значит: edge в данных распределён, single features не сильны.")

    print(f"\nSaved CSVs to: {OUT}")


if __name__ == "__main__":
    main()
