"""C8 grid search поверх pred12h_C8_force_6y.parquet.

Перебирает параметрическое пространство C8 force-match condition
и ранжирует по precision / recall / frequency.

Usage:
  python3 pred12h_C8_grid_search.py

Output:
  - Топ-20 параметризаций по P(W) при recall ≥ 17/18
  - Топ-20 по frequency при precision ≥ 65%
  - Лучший компромисс (Pareto)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import itertools

P = Path.home() / 'Desktop/pred12h_C8_force_6y.parquet'
if not P.exists():
    print(f"ERROR: {P} not found. Run pred12h_C8_force_batch.py first.")
    sys.exit(1)

df = pd.read_parquet(P)
print(f"Loaded {len(df):,} baseline pivots")
print(f"Confirmed: {df['confirmed'].sum()}  imp: {df['is_imp'].sum()}")
print(f"force_match (direction match): {df['force_match'].sum()} = {df['force_match'].mean()*100:.1f}%")
print()

# BIAS category groups
BIAS_GROUPS = {
    'U': lambda b: b in ('UNANIMOUS BULLISH','UNANIMOUS BEARISH'),
    'UP': lambda b: b in ('UNANIMOUS BULLISH','UNANIMOUS BEARISH') or 'PIVOT signature' in b,
    'UPH': lambda b: b in ('UNANIMOUS BULLISH','UNANIMOUS BEARISH','HTF BULLISH bias','HTF BEARISH bias') or 'PIVOT signature' in b,
    'ALL_BUT_WEAK': lambda b: b != 'BALANCED (weak bias)' and 'WEAK' not in b,
    'ANY': lambda b: True,
}

# Helper: build C8 mask
def make_c8(df, abs_net, d3, wins_fh, wins_fl, bias_group):
    """C8 = bias_group OK + direction match + |total_net|>=T1 + |3d|>=T2 + wins constraint."""
    bias_ok = df['bias'].apply(BIAS_GROUPS[bias_group])
    dir_match = df['force_match']
    net_ok = df['abs_net'] >= abs_net
    d3_ok = df['d3_net'].abs() >= d3
    fh_mask = (df['direction']=='high') & (df['n_wins']<=wins_fh)
    fl_mask = (df['direction']=='low') & (df['n_wins']>=wins_fl)
    wins_ok = fh_mask | fl_mask
    return bias_ok & dir_match & net_ok & d3_ok & wins_ok

# Parameter grid
grid = {
    'abs_net': [0, 500, 1000, 1500, 2000],
    'd3':      [0, 200, 400, 600],
    'wins_fh': [0, 1, 2, 3],
    'wins_fl': [9, 8, 7, 6],
    'bias':    ['U','UP','UPH','ALL_BUT_WEAK'],
}

results = []
n_total_pivots = len(df)
n_imp = int(df['is_imp'].sum())
for combo in itertools.product(*grid.values()):
    params = dict(zip(grid.keys(), combo))
    mask = make_c8(df, params['abs_net'], params['d3'],
                   params['wins_fh'], params['wins_fl'], params['bias'])
    n = mask.sum()
    if n < 50: continue
    conf = df.loc[mask, 'confirmed'].sum()
    imp = df.loc[mask, 'is_imp'].sum()
    p_w = conf/n*100
    recall_imp = imp/n_imp*100
    results.append({
        **params,
        'n_basket': n,
        'conf': conf,
        'P(W)_pct': round(p_w,2),
        'imp_in_basket': imp,
        'recall_imp_pct': round(recall_imp,1),
        # frequency assuming ~6y
        'freq_per_month': round(n/72, 2),
    })

df_g = pd.DataFrame(results)
print(f"Grid search: {len(df_g)} valid parameter combos\n")

print("=" * 100)
print("Топ-15 по P(W) (precision) при recall ≥ 17/18 imp:")
print("=" * 100)
high_recall = df_g[df_g['imp_in_basket']>=17].sort_values('P(W)_pct', ascending=False).head(15)
print(high_recall.to_string(index=False))

print("\n" + "=" * 100)
print("Топ-15 по P(W) при recall = 18/18 (полный):")
print("=" * 100)
full_recall = df_g[df_g['imp_in_basket']==18].sort_values('P(W)_pct', ascending=False).head(15)
print(full_recall.to_string(index=False) if len(full_recall) else "(нет комбинаций с recall=18)")

print("\n" + "=" * 100)
print("Топ-15 по frequency при precision ≥ 65% (для бизнес 8-12/мес):")
print("=" * 100)
high_prec = df_g[df_g['P(W)_pct']>=65].sort_values('freq_per_month', ascending=False).head(15)
print(high_prec.to_string(index=False))

print("\n" + "=" * 100)
print("Pareto front: precision vs recall (по 5 точкам на разных уровнях recall):")
print("=" * 100)
for recall_min in [10, 12, 14, 16, 17, 18]:
    sub = df_g[df_g['imp_in_basket']>=recall_min]
    if len(sub)==0: continue
    best = sub.sort_values('P(W)_pct', ascending=False).iloc[0]
    print(f"  recall ≥ {recall_min}/18:  P(W)={best['P(W)_pct']:.1f}%  n={best['n_basket']}  freq={best['freq_per_month']:.1f}/мес  "
          f"params: net≥{best['abs_net']} 3d≥{best['d3']} wins_fh≤{best['wins_fh']} wins_fl≥{best['wins_fl']} bias={best['bias']}")

# Save full grid for downstream analysis
OUT = Path.home() / 'Desktop/pred12h_C8_grid_results.parquet'
df_g.to_parquet(OUT, index=False)
print(f"\n[DONE] full grid saved to {OUT}")
