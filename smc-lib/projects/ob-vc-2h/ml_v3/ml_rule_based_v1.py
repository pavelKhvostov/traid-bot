"""Rule-based ML for ob_vc 2h — interpretable + honest live + time-split validation.

Architecture:
  1. TIME SPLIT: train = 2020-2023 (4y), test = 2024-2026 (~2.5y)
  2. LEARN on train:
     - Per-feature WIN filters (top universal boosters of WR)
     - Per-feature AVOID filters (top universal predictors of losses)
     - Top patterns (asset × t_id × direction) with positive baseline edge
  3. RULE COMPOSITION:
     - KEEP if event matches a top pattern
     - AND matches at least one WIN filter
     - AND doesn't match any AVOID filter
  4. APPLY on test → measure WR / Σ R / drawdown
  5. ITERATE: tighten / loosen rules to optimize

All HMA features are LIVE (intraday partial-bar per TF). Wait-window honest.
No lookahead. Target: hit_RR_10 (RR=1 canon).
"""
from __future__ import annotations
import pathlib
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SRC = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/features_v4_comprehensive_btc_eth.parquet")
OUT = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/ml_v3/ml_rule_based_v1_results")
OUT.mkdir(exist_ok=True)

META = {
    "event_id", "asset", "born_ms", "entry_fill_ms", "direction",
    "t_id", "n_comp", "extreme", "entry", "R", "r_pct", "r_pct_pass",
    "fill_touched", "mfe_R", "mae_R", "sl_hit", "exit_reason",
    "hit_RR_10", "hit_RR_14", "hit_RR_15", "hit_RR_17", "hit_RR_20",
    "hit_RR_23", "hit_RR_25", "hit_RR_28", "win", "loss", "born_dt", "year",
}

# Config
TRAIN_END_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
MIN_PATTERN_N = 80              # minimum events per pattern in train
MIN_PATTERN_WR = 0.55           # pattern baseline WR threshold
MIN_FILTER_N = 400              # min events per filter rule in train
WIN_FILTER_WR_LIFT = 0.04       # filter must boost WR by ≥4pp
LOSS_FILTER_WR_DIP = -0.04      # filter must drop WR by ≥4pp
TOP_WIN_FILTERS = 15            # keep top-N win filters
TOP_LOSS_FILTERS = 15           # keep top-N loss filters


def find_top_patterns(df_tr):
    """Find ob_vc patterns (asset × t_id × direction) with positive edge in training."""
    g = df_tr.groupby(["asset", "t_id", "direction"]).agg(
        n=("win", "size"), wins=("win", "sum")
    ).reset_index()
    g["wr"] = g.wins / g.n
    keep = g[(g.n >= MIN_PATTERN_N) & (g.wr >= MIN_PATTERN_WR)]
    return keep.sort_values("wr", ascending=False).reset_index(drop=True)


def find_universal_filters(df_tr, feat_cols, baseline_wr, side="win"):
    """Search universal feature filters that boost or dip WR universally."""
    results = []
    for f in feat_cols:
        vals = df_tr[f].to_numpy()
        m = ~np.isnan(vals)
        if m.sum() < 1500: continue
        for q in [0.10, 0.20, 0.25, 0.33, 0.50, 0.67, 0.75, 0.80, 0.90]:
            for above in [True, False]:
                t = float(np.nanquantile(vals[m], q))
                mask = m.copy()
                mask &= (vals >= t) if above else (vals <= t)
                n = int(mask.sum())
                if n < MIN_FILTER_N: continue
                wr = float(df_tr[mask].win.mean())
                lift = wr - baseline_wr
                if side == "win" and lift < WIN_FILTER_WR_LIFT: continue
                if side == "loss" and lift > LOSS_FILTER_WR_DIP: continue
                results.append({
                    "feature": f, "q": q, "above": above, "threshold": t,
                    "n": n, "wr": wr, "lift": lift,
                })

    df_r = pd.DataFrame(results)
    if side == "win":
        df_r = df_r.sort_values("wr", ascending=False)
    else:
        df_r = df_r.sort_values("wr", ascending=True)
    return df_r


def apply_filter(df, rule):
    vals = df[rule["feature"]].to_numpy()
    m = ~np.isnan(vals)
    if rule["above"]:
        return m & (vals >= rule["threshold"])
    return m & (vals <= rule["threshold"])


def compose_and_apply(df, top_patterns, win_filters, loss_filters):
    """Apply composed rule:
       KEEP if (in top patterns) AND (matches ANY win filter) AND (matches NO loss filters)."""
    # 1. Match top patterns
    pat_mask = pd.Series(False, index=df.index)
    for _, p in top_patterns.iterrows():
        m = (df.asset == p.asset) & (df.t_id == p.t_id) & (df.direction == p.direction)
        pat_mask |= m
    print(f"  Top-patterns match: {int(pat_mask.sum())} / {len(df)}")

    # 2. Match ≥1 win filter
    win_any = pd.Series(False, index=df.index)
    for _, r in win_filters.head(TOP_WIN_FILTERS).iterrows():
        win_any |= pd.Series(apply_filter(df, r), index=df.index)
    print(f"  Win-filter match (≥1): {int(win_any.sum())} / {len(df)}")

    # 3. Avoid loss filters (NOT in any)
    loss_any = pd.Series(False, index=df.index)
    for _, r in loss_filters.head(TOP_LOSS_FILTERS).iterrows():
        loss_any |= pd.Series(apply_filter(df, r), index=df.index)
    print(f"  Loss-filter match (avoid): {int(loss_any.sum())} / {len(df)}")

    final = pat_mask & win_any & (~loss_any)
    print(f"  FINAL selected: {int(final.sum())} / {len(df)}")
    return final


def summarize(df, name):
    n = len(df); w = int(df.win.sum())
    if n == 0:
        return f"  {name}: empty"
    wr = w / n * 100
    sigma_r = w * 1 - (n - w)
    return f"  {name}: N={n:,}  WR={wr:.1f}%  Σ R={sigma_r:+}R  E[R]={sigma_r/n:+.3f}R"


def main():
    print("=" * 72)
    print("Rule-based ML v1 (honest live, time-split, interpretable)")
    print("=" * 72)

    df = pd.read_parquet(SRC)
    df = df[df.fill_touched & df.r_pct_pass].reset_index(drop=True)
    if "hit_RR_10" not in df.columns:
        df["hit_RR_10"] = (df.mfe_R >= 1.0).astype(int)
    df["win"] = df.hit_RR_10
    df["born_dt"] = pd.to_datetime(df.born_ms, unit="ms", utc=True)

    df_tr = df[df.born_ms < TRAIN_END_MS].reset_index(drop=True)
    df_te = df[df.born_ms >= TRAIN_END_MS].reset_index(drop=True)
    print(f"\nTrain: {len(df_tr):,} events ({df_tr.born_dt.min():%Y-%m} → {df_tr.born_dt.max():%Y-%m})")
    print(f"Test:  {len(df_te):,} events ({df_te.born_dt.min():%Y-%m} → {df_te.born_dt.max():%Y-%m})")

    baseline_wr_tr = df_tr.win.mean()
    baseline_wr_te = df_te.win.mean()
    print(f"\nBaseline WR train: {baseline_wr_tr*100:.1f}%   test: {baseline_wr_te*100:.1f}%")

    feat_cols = [c for c in df.columns if c not in META]
    print(f"Features: {len(feat_cols)}")

    # ─── Step 1: top patterns (in train) ───
    print(f"\n[1/3] Searching top patterns (WR ≥ {MIN_PATTERN_WR*100:.0f}%, N ≥ {MIN_PATTERN_N})...")
    top_pats = find_top_patterns(df_tr)
    print(f"  Found {len(top_pats)} patterns:")
    print(top_pats.to_string(index=False))
    top_pats.to_csv(OUT / "top_patterns.csv", index=False)

    # ─── Step 2: universal WIN/LOSS filters (in train) ───
    print(f"\n[2/3] Searching universal WIN filters (lift ≥ +{WIN_FILTER_WR_LIFT*100:.0f}pp, N ≥ {MIN_FILTER_N})...")
    win_f = find_universal_filters(df_tr, feat_cols, baseline_wr_tr, side="win")
    print(f"  Found {len(win_f)} candidate WIN filters; top {TOP_WIN_FILTERS}:")
    print(win_f.head(TOP_WIN_FILTERS)[["feature", "q", "above", "n", "wr", "lift"]].to_string(index=False))
    win_f.to_csv(OUT / "win_filters_train.csv", index=False)

    print(f"\nSearching universal LOSS filters (dip ≤ {LOSS_FILTER_WR_DIP*100:.0f}pp)...")
    loss_f = find_universal_filters(df_tr, feat_cols, baseline_wr_tr, side="loss")
    print(f"  Found {len(loss_f)} candidate LOSS filters; top {TOP_LOSS_FILTERS}:")
    print(loss_f.head(TOP_LOSS_FILTERS)[["feature", "q", "above", "n", "wr", "lift"]].to_string(index=False))
    loss_f.to_csv(OUT / "loss_filters_train.csv", index=False)

    # ─── Step 3: compose + evaluate ───
    print(f"\n[3/3] COMPOSING rule and applying...")

    print(f"\n  ── On TRAIN ──")
    final_tr = compose_and_apply(df_tr, top_pats, win_f, loss_f)
    print(summarize(df_tr[final_tr], "TRAIN selected"))
    print(summarize(df_tr, "TRAIN baseline (all)"))

    print(f"\n  ── On TEST (OUT-OF-SAMPLE) ──")
    final_te = compose_and_apply(df_te, top_pats, win_f, loss_f)
    print(summarize(df_te[final_te], "TEST selected (OOS)"))
    print(summarize(df_te, "TEST baseline (all)"))

    # ─── Per-year on test ───
    print(f"\n  ── Per-year (test set) ──")
    df_te_sel = df_te[final_te].copy()
    df_te_sel["year"] = df_te_sel.born_dt.dt.year
    by_year_sel = df_te_sel.groupby("year").agg(
        n=("win", "size"), wins=("win", "sum")
    ).reset_index()
    by_year_sel["wr"] = (by_year_sel.wins / by_year_sel.n * 100).round(1)
    by_year_sel["sigma_r"] = by_year_sel.wins - (by_year_sel.n - by_year_sel.wins)
    print("    SELECTED by rule:")
    print(by_year_sel.to_string(index=False))

    df_te["year"] = df_te.born_dt.dt.year
    by_year_all = df_te.groupby("year").agg(
        n=("win", "size"), wins=("win", "sum")
    ).reset_index()
    by_year_all["wr"] = (by_year_all.wins / by_year_all.n * 100).round(1)
    by_year_all["sigma_r"] = by_year_all.wins - (by_year_all.n - by_year_all.wins)
    print("    BASELINE all (no rule):")
    print(by_year_all.to_string(index=False))

    # Save trades selected
    df_te_sel.to_csv(OUT / "test_selected_trades.csv", index=False)
    print(f"\nSaved CSVs to {OUT}")


if __name__ == "__main__":
    main()
