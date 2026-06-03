"""C8 v2 — на основе эмпирических данных, не интуиции.

STRONG (включает в basket): BIAS ∈ {HTF biased, BALANCED, PIVOT signature} + force_match
WEAK (исключает из basket): BIAS = UNANIMOUS (тренд, не разворот)

Цель: max P(W) при разумном recall.
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
df['abs_net'] = df['total_net'].abs()

# Extended imp = original 18 + 3 new user-named (06-05 #48 already in)
targets = [('2026-05-06 03:00','high'),('2026-05-10 15:00','high'),
           ('2026-05-13 15:00','low'),('2026-05-18 15:00','low')]
target_ts = {(int(pd.Timestamp(t+'+03:00').timestamp()*1000), s) for t,s in targets}
df['is_target'] = df.apply(lambda r: (r['pivot_open_ts_ms'], r['direction']) in target_ts, axis=1)
df['is_imp_ext'] = df['is_imp'] | df['is_target']
imp_ext_total = int(df['is_imp_ext'].sum())  # 21

# BIAS-категории
BIAS_UNANIMOUS = {'UNANIMOUS BULLISH','UNANIMOUS BEARISH'}
BIAS_HTF       = {'HTF BULLISH bias','HTF BEARISH bias'}
BIAS_PIVOT     = {'PIVOT signature (HTF BUYER + LTF flip)','PIVOT signature (HTF SELLER + LTF flip)'}
BIAS_BALANCED  = {'BALANCED (weak bias)'}

STRONG_SETS = {
    'PIVOT_only':    BIAS_PIVOT,
    'PIVOT+HTF':     BIAS_PIVOT | BIAS_HTF,
    'PIVOT+HTF+BAL': BIAS_PIVOT | BIAS_HTF | BIAS_BALANCED,
    'HTF+BAL':       BIAS_HTF | BIAS_BALANCED,
    'HTF_only':      BIAS_HTF,
}

def stats(mask):
    n = int(mask.sum())
    conf = int(df.loc[mask, 'confirmed'].sum())
    imp_old = int(df.loc[mask, 'is_imp'].sum())
    imp_ext = int(df.loc[mask, 'is_imp_ext'].sum())
    pw = conf/n*100 if n else 0
    return {'n':n,'conf':conf,'P(W)':round(pw,2),'imp_old':imp_old,'imp_ext':imp_ext}

print("=== Reference ===")
print(f"baseline:  {stats(pd.Series(True, index=df.index))}")
print(f"basket:    {stats(df['in_basket'])}")
print(f"basket+4:  {stats(df['in_basket'] | df['is_target'])}")

grid = {
    'strong_bias':    list(STRONG_SETS.keys()),
    'strong_fmatch':  [True, False],         # require force_match for STRONG?
    'strong_net_min': [0, 500, 1000],        # min abs_net for STRONG
    'weak_unan':      [False, True],         # exclude UNANIMOUS from basket?
    'weak_unan_min':  [0, 500, 1000, 2000],  # only exclude UNANIMOUS if abs_net >= this
}

results = []
for combo in itertools.product(*grid.values()):
    p = dict(zip(grid.keys(), combo))
    bset = STRONG_SETS[p['strong_bias']]
    fm = df['force_match'].fillna(False)
    strong_mask = df['bias'].isin(bset) & (df['abs_net'] >= p['strong_net_min'])
    if p['strong_fmatch']:
        strong_mask &= fm
    if p['weak_unan']:
        weak_mask = df['bias'].isin(BIAS_UNANIMOUS) & (df['abs_net'] >= p['weak_unan_min'])
    else:
        weak_mask = pd.Series(False, index=df.index)
    final = (df['in_basket'] | strong_mask) & ~weak_mask
    s = stats(final)
    if s['n'] < 200: continue
    # also report Δ vs basket
    s['Δ_PW_vs_basket'] = round(s['P(W)'] - 66.67, 2)
    s['Δ_imp_ext'] = s['imp_ext'] - 15
    results.append({**p, **s})

df_r = pd.DataFrame(results)
print(f"\nGrid points (n≥200): {len(df_r)}")

print("\n--- Top-15 by P(W) UNCONDITIONAL ---")
print(df_r.sort_values('P(W)', ascending=False).head(15)[
    ['strong_bias','strong_fmatch','strong_net_min','weak_unan','weak_unan_min',
     'n','conf','P(W)','imp_old','imp_ext','Δ_PW_vs_basket','Δ_imp_ext']].to_string(index=False))

for recall_min in [17, 19, 20]:
    sub = df_r[df_r['imp_ext'] >= recall_min].sort_values('P(W)', ascending=False).head(10)
    if len(sub):
        print(f"\n--- Top-10 by P(W) при imp_ext ≥ {recall_min}/21 ---")
        print(sub[['strong_bias','strong_fmatch','strong_net_min','weak_unan','weak_unan_min',
                    'n','P(W)','imp_old','imp_ext','Δ_PW_vs_basket']].to_string(index=False))

OUT = Path.home() / 'Desktop/pred12h_C8_grid_v2_results.parquet'
df_r.to_parquet(OUT, index=False)
print(f"\n[DONE] {len(df_r)} combos → {OUT}")
