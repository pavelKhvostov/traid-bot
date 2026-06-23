"""Cross-asset compare: ETH per-type WR vs BTC R5 dump per-type WR.

Strategy = type-filter из R5 BTC dump applied to ETH labels.
Цель: проверить universal ли 24-type taxonomy.
"""
import pathlib
import pandas as pd
import numpy as np

# BTC R5 reference per-type WR (from dump)
BTC_R5 = {
    'L_nsw_n1_cur':     (100.0, 2),    'L_sw_n1_cur':      (100.0, 1),
    'S_sw_n1_prevb':    (100.0, 1),    'S_nsw_n1_preva':   (100.0, 2),
    'S_nsw_n1_cur':     (100.0, 4),
    'L_nsw_n1_preva':   (83.3, 6),     'S_sw_n1_cur':      (80.0, 5),
    'L_nsw_n1_prevb':   (80.0, 5),     'L_nsw_n2_preva':   (77.8, 9),
    'S_sw_n2_prevb':    (76.9, 13),    'L_sw_n2_cur':      (76.5, 17),
    'S_nsw_n2_preva':   (75.0, 16),    'S_sw_n1_preva':    (75.0, 4),
    'L_nsw_n2_cur':     (72.7, 11),    'S_sw_n2_preva':    (69.2, 13),
    'L_sw_n1_preva':    (66.7, 3),     'L_sw_n2_prevb':    (66.7, 3),
    'L_sw_n2_preva':    (64.7, 17),    'S_nsw_n2_cur':     (64.3, 14),
    'S_sw_n2_cur':      (60.0, 10),    'L_nsw_n2_prevb':   (50.0, 8),
    'S_nsw_n2_prevb':   (0.0, 3),
}

ETH = pathlib.Path("/home/vadim/smc-lib/projects/ob_vc/eth/data")
labels = pd.read_parquet(ETH / "eth_labels_2h.parquet")
types = pd.read_parquet(ETH / "eth_ob_vc_24types.parquet")
print(f"Labels: {len(labels)}  Types: {len(types)}", flush=True)

# Filter to closed trades
closed = labels[labels['outcome'].isin(['tp','sl','sl_same_bar'])].copy()
print(f"Closed labels: {len(closed)}", flush=True)
# Match by (source_idx, direction)
# Types parquet has 2h ob_vc subset only — filter for 'tf'=='2h'
if 'tf' in types.columns:
    types_2h = types[types['tf'] == '2h'].copy()
else:
    types_2h = types.copy()
print(f"Types 2h: {len(types_2h)}", flush=True)

# Build 24-type label
def make_label(r):
    d = 'L' if r['direction']=='long' else 'S'
    sw = 'sw' if r['swept'] else 'nsw'
    n = f"n{int(r['n_fvg_proxy'])}"
    if r['extreme'] == 'cur':
        ext = 'cur'
    else:
        ext = f"prev{r['wick_suffix']}"
    return f"{d}_{sw}_{n}_{ext}"

# types parquet already has 'type_label' (pre-built)
types_2h = types_2h.rename(columns={'type_label': 'type24', 'ts_event': 'ts'})
m = closed.merge(types_2h[['ts','direction','type24']], on=['ts','direction'], how='left')
matched = m['type24'].notna().sum()
print(f"Matched: {matched}/{len(closed)}", flush=True)
m = m.dropna(subset=['type24'])

# Per-type ETH stats
g = m.groupby('type24').agg(N=('hit_rr1','size'), W=('hit_rr1','sum'))
g['WR_ETH'] = (g['W']/g['N']*100).round(1)

# Add BTC reference
g['WR_BTC'] = g.index.map(lambda t: BTC_R5.get(t, (np.nan, 0))[0])
g['N_BTC']  = g.index.map(lambda t: BTC_R5.get(t, (np.nan, 0))[1])
g = g.sort_values('WR_ETH', ascending=False)
print()
print("=== Per-type cross-asset comparison ===")
print(g.to_string())

# Correlation
mask = g['WR_BTC'].notna() & (g['N_BTC'] >= 3)
if mask.sum() >= 5:
    pe = np.corrcoef(g.loc[mask, 'WR_ETH'], g.loc[mask, 'WR_BTC'])[0,1]
    print(f"\nPearson WR ETH vs BTC (N_BTC≥3): {pe:.3f}")

# Strategy: Tier A+B (BTC WR ≥ 70%) applied to ETH
tier_AB = [t for t,(wr,n) in BTC_R5.items() if wr >= 70 and n >= 3]
sel = m[m['type24'].isin(tier_AB)]
sel_wr = sel['hit_rr1'].mean() * 100 if len(sel) else 0
print(f"\n=== STRATEGY: trade only types where BTC R5 WR ≥ 70% (Tier A+B) ===")
print(f"  Types ({len(tier_AB)}): {tier_AB}")
print(f"  ETH trades: {len(sel)}  wins: {sel['hit_rr1'].sum()}  WR: {sel_wr:.1f}%")
ev = sel['r_result'].mean() if len(sel) else 0
sum_r = sel['r_result'].sum() if len(sel) else 0
print(f"  EV/trade: {ev:.3f}R  Σ R: {sum_r:.1f}")
# Months
yr = (sel['ts'].max() - sel['ts'].min()) / (1000*86400*365.25) if len(sel) else 0
months = yr*12 if yr else 0
print(f"  Period: {yr:.2f} y  ≈ {len(sel)/max(months,1):.1f} trades/мес")

# Compare with baseline (all closed trades)
print()
print(f"=== Baseline (no filter) ETH ===")
print(f"  trades: {len(m)}  wins: {m['hit_rr1'].sum()}  WR: {m['hit_rr1'].mean()*100:.1f}%  EV: {m['r_result'].mean():.3f}R")

# Tier A only (WR≥80%)
tier_A = [t for t,(wr,n) in BTC_R5.items() if wr >= 80 and n >= 2]
sel_A = m[m['type24'].isin(tier_A)]
print()
print(f"=== STRATEGY: Tier A only (BTC WR ≥ 80%) ===")
print(f"  Types: {tier_A}")
print(f"  ETH trades: {len(sel_A)}  wins: {sel_A['hit_rr1'].sum()}  WR: {sel_A['hit_rr1'].mean()*100 if len(sel_A) else 0:.1f}%")
