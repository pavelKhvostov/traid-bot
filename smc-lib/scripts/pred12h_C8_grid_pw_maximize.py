"""C8 двусторонний: STRONG override включает (даже если C1-C7=False),
WEAK override исключает (даже если C1-C7=True). Иначе — keep C1-C7.

Цель: max P(W) при сохранении приемлемого recall и basket size.
"""
from __future__ import annotations
import sys, itertools
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path.home() / 'Desktop'
base = pd.read_parquet(ROOT / 'pred12h_baseline_c1c7.parquet')
force = pd.read_parquet(ROOT / 'pred12h_C8_force_6y.parquet')

df = base.merge(force[['pivot_open_ts_ms','direction','total_net','d3_net','n_wins','bias','force_match']],
                on=['pivot_open_ts_ms','direction'], how='left')

# Mark 4 user-named pivots as extended imp
targets = [('2026-05-06 03:00','high'),('2026-05-10 15:00','high'),
           ('2026-05-13 15:00','low'),('2026-05-18 15:00','low')]
target_ts = {(int(pd.Timestamp(t+'+03:00').timestamp()*1000), s) for t,s in targets}
df['is_target'] = df.apply(lambda r: (r['pivot_open_ts_ms'], r['direction']) in target_ts, axis=1)
df['is_imp_ext'] = df['is_imp'] | df['is_target']
imp_ext_total = int(df['is_imp_ext'].sum())  # 21

BIAS_STRONG = {'U': {'UNANIMOUS BULLISH','UNANIMOUS BEARISH'},
               'UP': {'UNANIMOUS BULLISH','UNANIMOUS BEARISH','PIVOT signature (HTF BUYER + LTF flip)','PIVOT signature (HTF SELLER + LTF flip)'},
               'UPH': {'UNANIMOUS BULLISH','UNANIMOUS BEARISH','PIVOT signature (HTF BUYER + LTF flip)','PIVOT signature (HTF SELLER + LTF flip)','HTF BULLISH bias','HTF BEARISH bias'}}
BIAS_WEAK_ALWAYS = {'BALANCED (weak bias)', 'HTF BULLISH (weak)', 'HTF BEARISH (weak)'}

def stats(mask):
    n = int(mask.sum())
    conf = int(df.loc[mask, 'confirmed'].sum())
    imp_old = int(df.loc[mask, 'is_imp'].sum())
    imp_ext = int(df.loc[mask, 'is_imp_ext'].sum())
    pw = conf/n*100 if n else 0
    return {'n':n, 'conf':conf, 'P(W)':round(pw,2),
            'imp_old':imp_old, 'imp_ext':imp_ext}

print("=== Reference ===")
print(f"baseline F1∩F2∩F3: {stats(pd.Series(True, index=df.index))}")
print(f"current basket C1-C7: {stats(df['in_basket'])}")
print(f"+ {{4 targets}} manual: {stats(df['in_basket'] | df['is_target'])}")
print()

# Grid: strong + weak параметры
grid = {
    'strong_net':  [1000, 1500, 2000, 2500, 3000],
    'strong_d3':   [400, 600, 800, 1000],
    'strong_bias': ['U', 'UP', 'UPH'],
    'weak_net':    [300, 500, 700],  # |net| below = weak
    'weak_contrary': [True, False],  # exclude if force contrary to direction
}

results = []
for combo in itertools.product(*grid.values()):
    p = dict(zip(grid.keys(), combo))
    bias_strong_set = BIAS_STRONG[p['strong_bias']]

    # STRONG: force_match + abs_net >= strong_net + d3 >= strong_d3 + bias in strong_bias_set
    strong = (df['force_match'].fillna(False) &
              (df['total_net'].abs() >= p['strong_net']) &
              (df['d3_net'].abs() >= p['strong_d3']) &
              df['bias'].isin(bias_strong_set))

    # WEAK: |net| < weak_net OR (contrary direction если включено) OR BIAS = BALANCED
    weak_net = df['total_net'].abs() < p['weak_net']
    weak_bias = df['bias'].isin(BIAS_WEAK_ALWAYS)
    if p['weak_contrary']:
        contrary = (df['force_match'].fillna(False) == False)
        weak = weak_net | weak_bias | contrary
    else:
        weak = weak_net | weak_bias

    # Final: STRONG override → True, else WEAK override → False, else C1-C7
    final = strong | (~weak & df['in_basket'])

    s = stats(final)
    if s['n'] < 100: continue
    results.append({**p, **s, 'basket_pct_kept': round(s['n']/657*100, 1)})

df_r = pd.DataFrame(results)
print(f"Grid points (n>=100): {len(df_r)}")

# Top по P(W) с разными recall thresholds
for recall_min in [17, 18, 19, 20]:
    sub = df_r[df_r['imp_ext'] >= recall_min].sort_values('P(W)', ascending=False).head(10)
    if len(sub):
        print(f"\n--- Top-10 by P(W) при imp_ext ≥ {recall_min}/21 ---")
        print(sub[['strong_net','strong_d3','strong_bias','weak_net','weak_contrary',
                    'n','conf','P(W)','imp_old','imp_ext','basket_pct_kept']].to_string(index=False))

# Top по P(W) без recall constraint
print(f"\n--- Top-10 by P(W) UNCONDITIONAL ---")
top_uncond = df_r.sort_values('P(W)', ascending=False).head(10)
print(top_uncond[['strong_net','strong_d3','strong_bias','weak_net','weak_contrary',
                   'n','conf','P(W)','imp_old','imp_ext','basket_pct_kept']].to_string(index=False))

OUT = Path.home() / 'Desktop/pred12h_C8_grid_pw_results.parquet'
df_r.to_parquet(OUT, index=False)
print(f"\n[DONE] {len(df_r)} combos saved to {OUT}")
