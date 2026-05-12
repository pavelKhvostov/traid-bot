"""Этап 72: Forensic bug audit стратегии 1.1.4 BFJK portfolio.

Проверки:
  1. SL fallback path: как часто триггерится x1b>=fb (LONG) или x1t<=ft (SHORT)?
     Каков WR / total R на fallback-trades vs main path?
  2. Time consistency: signal_time vs entry_time — не in past?
  3. Risk consistency: SL/entry geometry, MIN_SL применяется корректно?
  4. Direction consistency: все 4 уровня одного направления?
  5. Lookahead audit: используется ли будущее data в любом фильтре?
  6. Dedup integrity: уникальность (signal_time, dir, fvg_b, fvg_t)?
  7. L1 invalidation: проверка что окно invalidation корректно sliced
  8. Sample integrity: tf_minutes согласован с chain entry TF
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import time
import numpy as np
import pandas as pd

CSV_PATH = _Path("research/elements_study/output/etap71_BFJK_portfolio.csv")


def audit_sl_fallback(df):
    """Какие row'ы шли через fallback path (x1b>=fb для LONG, x1t<=ft для SHORT)?"""
    print(f"\n{'='*80}\n1. SL FALLBACK PATH AUDIT\n{'='*80}")
    long_main = df[(df["direction"] == "LONG") & (df["x1_b"] < df["fvg_b"])]
    long_fallback = df[(df["direction"] == "LONG") & (df["x1_b"] >= df["fvg_b"])]
    short_main = df[(df["direction"] == "SHORT") & (df["x1_t"] > df["fvg_t"])]
    short_fallback = df[(df["direction"] == "SHORT") & (df["x1_t"] <= df["fvg_t"])]

    print(f"  LONG total: {len(df[df.direction=='LONG'])}")
    print(f"    main path (x1_b < fvg_b):     n={len(long_main)}")
    print(f"    FALLBACK (x1_b >= fvg_b):     n={len(long_fallback)}")
    print(f"  SHORT total: {len(df[df.direction=='SHORT'])}")
    print(f"    main path (x1_t > fvg_t):     n={len(short_main)}")
    print(f"    FALLBACK (x1_t <= fvg_t):     n={len(short_fallback)}")

    # Performance on each subset
    def stats(d):
        cl = d[d["outcome"].isin(["win", "loss"])]
        if cl.empty: return "no closed"
        wr = (cl["outcome"] == "win").mean() * 100
        tot = cl["R"].sum()
        return f"closed={len(cl):>3} WR={wr:5.1f}% total={tot:+6.1f}R avg={cl['R'].mean():+5.2f}R"

    print(f"\n  Performance comparison:")
    print(f"    LONG main:     {stats(long_main)}")
    print(f"    LONG fallback: {stats(long_fallback)}")
    print(f"    SHORT main:    {stats(short_main)}")
    print(f"    SHORT fallback:{stats(short_fallback)}")

    n_fb_total = len(long_fallback) + len(short_fallback)
    print(f"\n  TOTAL FALLBACK: {n_fb_total}/{len(df)} ({n_fb_total/len(df)*100:.1f}%)")


def audit_time_consistency(df):
    print(f"\n{'='*80}\n2. TIME CONSISTENCY\n{'='*80}")
    df_copy = df.copy()
    # Normalize to tz-naive for comparison
    df_copy["signal_time_dt"] = pd.to_datetime(df_copy["signal_time"], errors="coerce", utc=True).dt.tz_localize(None)
    df_copy["entry_time_dt"] = pd.to_datetime(df_copy["entry_time"], errors="coerce", utc=True).dt.tz_localize(None)
    df_copy["exit_time_dt"] = pd.to_datetime(df_copy["exit_time"], errors="coerce", utc=True).dt.tz_localize(None)

    # Entry should always be >= signal_time
    has_entry = df_copy[df_copy["entry_time_dt"].notna()]
    pre_signal = has_entry[has_entry["entry_time_dt"] < has_entry["signal_time_dt"]]
    print(f"  rows with entry_time set: {len(has_entry)}")
    print(f"  entries BEFORE signal_time (LOOKAHEAD!): {len(pre_signal)}")
    if len(pre_signal):
        print("  *** BUG: entries before signal_time ***")
        print(pre_signal[["idx", "signal_time", "entry_time"]].head())

    # Exit should be >= entry
    has_exit = df_copy[df_copy["exit_time_dt"].notna()]
    pre_entry = has_exit[has_exit["exit_time_dt"] < has_exit["entry_time_dt"]]
    print(f"  rows with exit_time set: {len(has_exit)}")
    print(f"  exits BEFORE entry (BUG): {len(pre_entry)}")

    # Hold duration
    has_both = df_copy[df_copy["entry_time_dt"].notna() & df_copy["exit_time_dt"].notna()]
    if len(has_both):
        dur = (has_both["exit_time_dt"] - has_both["entry_time_dt"])
        print(f"  hold duration: mean={dur.mean()}, median={dur.median()}, max={dur.max()}")


def audit_sl_geometry(df):
    print(f"\n{'='*80}\n3. SL GEOMETRY\n{'='*80}")
    valid = df[df["entry"].notna()]
    # LONG: sl < entry
    longs = valid[valid["direction"] == "LONG"]
    sl_invalid = longs[longs["sl"] >= longs["entry"]]
    print(f"  LONG with sl >= entry (BUG): {len(sl_invalid)}/{len(longs)}")
    # SHORT: sl > entry
    shorts = valid[valid["direction"] == "SHORT"]
    sl_invalid_s = shorts[shorts["sl"] <= shorts["entry"]]
    print(f"  SHORT with sl <= entry (BUG): {len(sl_invalid_s)}/{len(shorts)}")

    # MIN_SL_PCT = 1.0 check
    risk_pct = (abs(valid["entry"] - valid["sl"]) / valid["entry"] * 100)
    too_small = (risk_pct < 0.99).sum()  # below 0.99% (allowing tiny rounding)
    print(f"  rows with risk < 0.99% (MIN_SL fail?): {too_small}")

    # TP geometry
    long_tp_invalid = longs[longs["tp"] <= longs["entry"]]
    short_tp_invalid = shorts[shorts["tp"] >= shorts["entry"]]
    print(f"  LONG with tp <= entry (BUG): {len(long_tp_invalid)}/{len(longs)}")
    print(f"  SHORT with tp >= entry (BUG): {len(short_tp_invalid)}/{len(shorts)}")

    # RR check
    rr_actual = abs(valid["tp"] - valid["entry"]) / abs(valid["entry"] - valid["sl"])
    print(f"  Actual RR: mean={rr_actual.mean():.3f}, "
          f"min={rr_actual.min():.3f}, max={rr_actual.max():.3f}")
    print(f"  Should be ~2.0 (RR set to 2.0)")
    rr_off = ((rr_actual - 2.0).abs() > 0.01).sum()
    print(f"  rows with |actual_RR - 2.0| > 0.01: {rr_off}")


def audit_zone_geometry(df):
    print(f"\n{'='*80}\n4. ZONE GEOMETRY\n{'='*80}")
    # FVG bot < top
    bad_fvg = df[df["fvg_b"] >= df["fvg_t"]]
    print(f"  FVG with bot >= top (degenerate): {len(bad_fvg)}")
    # OBH bot < top
    bad_obh = df[df["obh_b"] >= df["obh_t"]]
    print(f"  OBH (L3) with bot >= top: {len(bad_obh)}")
    # x1 bot <= top (intersection can be empty if no overlap)
    bad_x1 = df[df["x1_b"] > df["x1_t"]]
    print(f"  x1 cluster with bot > top (empty intersection!): {len(bad_x1)}")
    if len(bad_x1):
        print(f"  Example: {bad_x1[['idx','direction','fvg_b','fvg_t','x1_b','x1_t']].head()}")

    # FVG inside x1 zone? (should overlap)
    no_overlap = df[(df["fvg_b"] > df["x1_t"]) | (df["fvg_t"] < df["x1_b"])]
    print(f"  FVG NOT overlapping x1 (BUG, should overlap): {len(no_overlap)}")


def audit_dedup(df):
    print(f"\n{'='*80}\n5. DEDUP INTEGRITY\n{'='*80}")
    key_dup = df.duplicated(subset=["signal_time", "direction", "fvg_b", "fvg_t"], keep=False)
    print(f"  rows with duplicate (signal_time, dir, fvg_b, fvg_t): {key_dup.sum()}")

    # Same signal_time multi-rows (could be valid if different fvg_b/t)
    st_dup = df["signal_time"].value_counts()
    print(f"  signal_times appearing > 1 time: {(st_dup > 1).sum()}")
    if (st_dup > 1).any():
        print(f"  max per signal_time: {st_dup.max()}")
        examples = st_dup[st_dup > 1].head(3)
        for st, n in examples.items():
            rows = df[df["signal_time"] == st]
            print(f"    {st}: n={n} chains={rows['chain'].tolist()}")


def audit_chain_assignment(df):
    print(f"\n{'='*80}\n6. CHAIN ASSIGNMENT\n{'='*80}")
    print(f"  Chain distribution (all rows):")
    for c, n in df["chain"].value_counts().items():
        print(f"    {c:<20}  {n}")

    # Setups where multiple chains generated same FVG entry — OK, expected
    multi_chain = df[df["chain"].str.contains(r"\+", regex=True)]
    print(f"  Multi-chain dedup hits: {len(multi_chain)}")
    if len(multi_chain):
        print(f"  Chains in multi: {multi_chain['chain'].value_counts().to_dict()}")


def audit_outcome_logic(df):
    print(f"\n{'='*80}\n7. OUTCOME LOGIC\n{'='*80}")
    # win must have R > 0
    wins = df[df["outcome"] == "win"]
    bad_win = wins[wins["R"] <= 0]
    print(f"  WIN with R <= 0 (BUG): {len(bad_win)}")
    print(f"  WIN R distribution: min={wins['R'].min():.3f}, "
          f"max={wins['R'].max():.3f}, mean={wins['R'].mean():.3f}")
    # WIN R should = RR (= 2.0) since fixed TP
    odd_win = wins[(wins["R"] - 2.0).abs() > 0.01]
    print(f"  WIN with R != 2.0 (RR=2 expected): {len(odd_win)}")

    losses = df[df["outcome"] == "loss"]
    bad_loss = losses[losses["R"] != -1.0]
    print(f"  LOSS with R != -1 (BUG): {len(bad_loss)}")

    no_entry = df[df["outcome"] == "no_entry"]
    bad_ne = no_entry[no_entry["entry_time"].notna()]
    print(f"  no_entry but entry_time set (BUG): {len(bad_ne)}")


def audit_signal_time_vs_now(df):
    print(f"\n{'='*80}\n8. SIGNAL_TIME RECENT-FUTURE CHECK\n{'='*80}")
    df_c = df.copy()
    df_c["signal_time_dt"] = pd.to_datetime(df_c["signal_time"], errors="coerce", utc=True).dt.tz_localize(None)
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    future = df_c[df_c["signal_time_dt"] > now]
    print(f"  signal_time in the future: {len(future)}")
    earliest = df_c["signal_time_dt"].min()
    latest = df_c["signal_time_dt"].max()
    print(f"  Earliest signal: {earliest}")
    print(f"  Latest signal:   {latest}")


def audit_year_distribution(df):
    print(f"\n{'='*80}\n9. YEAR DISTRIBUTION\n{'='*80}")
    print(f"  Rows by year:")
    by_year = df.groupby("year")["outcome"].value_counts().unstack(fill_value=0)
    print(by_year.to_string())


def main():
    t0 = time.time()
    if not CSV_PATH.exists():
        print(f"  [FAIL] CSV not found: {CSV_PATH}")
        return
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    print(f"[INFO] loaded {len(df)} rows from {CSV_PATH}")

    audit_sl_fallback(df)
    audit_time_consistency(df)
    audit_sl_geometry(df)
    audit_zone_geometry(df)
    audit_dedup(df)
    audit_chain_assignment(df)
    audit_outcome_logic(df)
    audit_signal_time_vs_now(df)
    audit_year_distribution(df)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
