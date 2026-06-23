"""Apply BTC R5 extracted feature rules + type filter to ETH.

BTC R5 feature insights (extracted from /home/vadim/smc-lib/projects/ob_vc/s1/r5_test_trades_summary.txt):
  - snap_zones_near ≥ 35       (winners 38.8 vs losers 31.9)
  - n_ltf_triggers ≤ 2          (winners 2.77 vs losers 3.17)
  - rec_n_BLOCK_fill ≥ 80       (winners 80 vs losers 77)
  - d_LIQ_below_pct < 15        (winners 12 vs losers 20)
  - rec_n_retire < 325          (winners 318 vs losers 335)

Type-tier filter (from R5 BTC):
  Tier A+B = BTC WR ≥ 70% per type
"""
import pathlib
import pandas as pd
import numpy as np

BTC_R5_TIER_AB = {
    'S_nsw_n1_cur','L_nsw_n1_preva','S_sw_n1_cur','L_nsw_n1_prevb',
    'L_nsw_n2_preva','S_sw_n2_prevb','L_sw_n2_cur','S_nsw_n2_preva',
    'S_sw_n1_preva','L_nsw_n2_cur',
    # Tier A
    'L_nsw_n1_cur','L_sw_n1_cur','S_sw_n1_prevb','S_nsw_n1_preva'
}

ETH = pathlib.Path("/home/vadim/smc-lib/projects/ob_vc/eth/data")
feat = pd.read_parquet(ETH / "eth_features_2h.parquet")
types = pd.read_parquet(ETH / "eth_ob_vc_24types.parquet")
types_2h = types[types['tf'] == '2h'].rename(columns={'type_label':'type24','ts_event':'ts'})
m = feat.merge(types_2h[['ts','direction','type24']], on=['ts','direction'], how='left')
m = m.dropna(subset=['type24'])
print(f"ETH eval set: {len(m)} (matched type)")
n0 = len(m); wr0 = m['hit_rr1'].mean()*100; ev0 = m['r_result'].mean()
print(f"Baseline: N={n0}  WR={wr0:.1f}%  EV={ev0:.3f}R  Σ={m['r_result'].sum():.0f}R")
print()

def apply_rule(df, mask, name):
    n = mask.sum()
    if n == 0:
        print(f"  {name:<40} N=0")
        return
    sub = df[mask]
    wr = sub['hit_rr1'].mean()*100
    ev = sub['r_result'].mean()
    sr = sub['r_result'].sum()
    print(f"  {name:<40} N={n:>5}  WR={wr:>5.1f}%  EV={ev:>+.3f}R  Σ={sr:>+6.0f}R")

print("=== Single-feature rules ===")
apply_rule(m, m['snap_zones_near'] >= 35,       "snap_zones_near ≥ 35")
apply_rule(m, m['n_ltf_triggers'] <= 2,         "n_ltf_triggers ≤ 2")
apply_rule(m, m['rec_n_BLOCK_fill'] >= 80,      "rec_n_BLOCK_fill ≥ 80")
apply_rule(m, m['d_LIQ_below_pct'] < 15,        "d_LIQ_below_pct < 15")
apply_rule(m, m['rec_n_retire'] < 325,          "rec_n_retire < 325")

print()
print("=== Type filter ===")
apply_rule(m, m['type24'].isin(BTC_R5_TIER_AB), "Tier A+B (BTC WR≥70%)")

print()
print("=== Combined filters ===")
apply_rule(m,
    (m['snap_zones_near'] >= 35) & (m['n_ltf_triggers'] <= 2),
    "snap_zones≥35 AND ltf≤2")
apply_rule(m,
    (m['snap_zones_near'] >= 35) & (m['type24'].isin(BTC_R5_TIER_AB)),
    "snap_zones≥35 AND Tier A+B")
apply_rule(m,
    (m['snap_zones_near'] >= 35) & (m['n_ltf_triggers'] <= 2) & (m['rec_n_BLOCK_fill'] >= 80),
    "ALL 3 feature rules")
apply_rule(m,
    (m['snap_zones_near'] >= 35) & (m['n_ltf_triggers'] <= 2) & (m['type24'].isin(BTC_R5_TIER_AB)),
    "3 feat AND Tier A+B")

print()
print("=== INVERTED hypothesis test (Are ETH signals reversed?) ===")
apply_rule(m, m['snap_zones_near'] <= 25,       "snap_zones_near ≤ 25 (inverted)")
apply_rule(m, m['n_ltf_triggers'] >= 3,         "n_ltf_triggers ≥ 3 (inverted)")
