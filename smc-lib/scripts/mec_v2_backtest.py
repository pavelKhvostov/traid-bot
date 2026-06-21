"""MEC v2 — Strategy 1.1.1 floating с 1h/2h structural entry + Multi-Expert filters.

Архитектура:
  L1 trigger: pure floating signal (ob_vc cascade SWEPT, structural 1h/2h+15m/20m)
  L2/L3 entry: floating уже использует structural entry на FVG-LTF mid
  L4 confluence filters (multi-expert):
    F1: Force direction — 3D_net должен соглашаться с trade direction (или нейтрально)
    F2: BIAS reversal — не UNANIMOUS bias (= тренд, не разворот)
    F3: MH 96h direction — должна совпадать (когда данные есть)
    F4: Top zone strength — для x20 хочется HTF confluence

Strategy outcomes используются from existing floating trades parquet.
Filters применяются к signal_time → закрытые trades subset.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path.home() / 'Desktop'
trades = pd.read_parquet(ROOT/'floating_btc_6y_trades.parquet')
base = pd.read_parquet(ROOT/'pred12h_baseline_c1c7.parquet')
force = pd.read_parquet(ROOT/'pred12h_C8_force_6y.parquet')

# Merge baseline + force
pivots = base.merge(force[['pivot_open_ts_ms','direction','total_net','d3_net','n_wins','bias','force_match','top_long_str','top_short_str']],
                    on=['pivot_open_ts_ms','direction'], how='left')
pivots['pivot_close_ts'] = pd.to_datetime(pivots['pivot_open_ts_ms'], unit='ms', utc=True) + pd.Timedelta(hours=12)
pivots = pivots.sort_values('pivot_close_ts').reset_index(drop=True)
pivot_close_arr = pd.DatetimeIndex(pivots['pivot_close_ts']).asi8  # int64 ns

# Trades
trades['signal_time'] = pd.to_datetime(trades['signal_time'], utc=True)
trades_closed = trades[trades['outcome'].isin(['win','loss','flat'])].copy()
trades_closed = trades_closed.sort_values('signal_time').reset_index(drop=True)
print(f"Closed floating trades: {len(trades_closed)}")

# MH predictions (1y from PC2)
mh = pd.read_csv(ROOT/'PC2/mh_predictions.csv')
mh['ts'] = pd.to_datetime(mh['ts'], utc=True)
mh_min, mh_max = mh.ts.min(), mh.ts.max()
mh_idx = mh.set_index('ts')
print(f"MH range: {mh_min} → {mh_max}")

# For each trade, lookup Force snapshot (from nearest preceding 12h pivot) + MH at signal_time
def force_at(t):
    t_ns = pd.Timestamp(t).value
    pos = int(np.searchsorted(pivot_close_arr, t_ns, side='right')) - 1
    if pos < 0: return None
    return pivots.iloc[pos]

def mh_at(t):
    if t < mh_min or t > mh_max: return None
    pos = mh_idx.index.searchsorted(t, side='right') - 1
    if pos < 0: return None
    return mh_idx.iloc[pos]['pred_96h']

print("Enriching trades via merge_asof...")
# Normalize dtypes to ns
trades_closed['signal_time'] = pd.to_datetime(trades_closed['signal_time'], utc=True).astype('datetime64[ns, UTC]')
# Force lookup: nearest preceding pivot
piv = pivots[['pivot_close_ts','d3_net','total_net','bias']].copy()
piv['pivot_close_ts'] = pd.to_datetime(piv['pivot_close_ts'], utc=True).astype('datetime64[ns, UTC]')
piv = piv.dropna(subset=['d3_net']).sort_values('pivot_close_ts')
trades_closed = pd.merge_asof(
    trades_closed.sort_values('signal_time'),
    piv,
    left_on='signal_time', right_on='pivot_close_ts',
    direction='backward',
)

# MH lookup
mh_sub = mh[['ts','pred_96h']].copy()
mh_sub['ts'] = pd.to_datetime(mh_sub['ts'], utc=True).astype('datetime64[ns, UTC]')
mh_sub = mh_sub.sort_values('ts')
trades_closed = pd.merge_asof(
    trades_closed.sort_values('signal_time'),
    mh_sub,
    left_on='signal_time', right_on='ts',
    direction='backward',
    tolerance=pd.Timedelta(hours=2),
)
trades_closed = trades_closed.rename(columns={'pred_96h':'mh_p96'})
trades_closed = trades_closed.reset_index(drop=True)
print(f"  d3_net coverage: {trades_closed['d3_net'].notna().sum()}/{len(trades_closed)}")
print(f"  mh_p96 coverage: {trades_closed['mh_p96'].notna().sum()}/{len(trades_closed)}")
print(f"  bias non-null unique: {trades_closed['bias'].dropna().unique()}")

# Stats helper
def stats(mask, label):
    sub = trades_closed[mask]
    n = len(sub)
    if n == 0:
        print(f"  {label:50s}  n=0"); return
    W = (sub['R']>0).sum(); L = (sub['R']<0).sum()
    pnl = sub['R'].sum()
    gw = sub.loc[sub['R']>0,'R'].sum(); gl = abs(sub.loc[sub['R']<0,'R'].sum())
    pf = gw/gl if gl>0 else float('inf')
    aw = sub.loc[sub['R']>0,'R'].mean() if W else 0
    al = sub.loc[sub['R']<0,'R'].mean() if L else 0
    rr = aw/abs(al) if al!=0 else float('inf')
    wr = W/n*100
    years = (sub['signal_time'].max() - sub['signal_time'].min()).days / 365.25
    freq = n/(years*12) if years>0 else 0
    print(f"  {label:50s}  n={n:>4}  WR={wr:5.1f}%  PF={pf:5.2f}  RR={rr:5.2f}  R={pnl:>+7.1f}  R/tr={pnl/n:>+5.2f}  freq={freq:.2f}/mo")

print("\n=== MEC v2 filters cumulatively ===\n")
m_all = pd.Series(True, index=trades_closed.index)
stats(m_all, 'Pure floating (no filter)')

# F1: Force direction not strongly opposing
fm_long_ok = (trades_closed['direction']=='LONG') & ((trades_closed['d3_net'].fillna(0) >= -500))
fm_short_ok = (trades_closed['direction']=='SHORT') & ((trades_closed['d3_net'].fillna(0) <= 500))
m_force = fm_long_ok | fm_short_ok
stats(m_force, 'F1: 3D-force не сильно против')

# F2: BIAS not UNANIMOUS
m_bias = ~trades_closed['bias'].fillna('').str.startswith('UNANIMOUS')
stats(m_force & m_bias, 'F1+F2: + BIAS не UNANIMOUS')

# F3: MH agrees (where data exists)
mh_long_ok = (trades_closed['direction']=='LONG') & (trades_closed['mh_p96'].fillna(0) > -2.0)
mh_short_ok = (trades_closed['direction']=='SHORT') & (trades_closed['mh_p96'].fillna(0) < 2.0)
m_mh = mh_long_ok | mh_short_ok
stats(m_force & m_bias & m_mh, 'F1+F2+F3: + MH не сильно против')

# F3 strong: MH strongly agrees
mh_long_strong = (trades_closed['direction']=='LONG') & (trades_closed['mh_p96'].fillna(-99) > 1.0)
mh_short_strong = (trades_closed['direction']=='SHORT') & (trades_closed['mh_p96'].fillna(99) < -1.0)
m_mh_strong = mh_long_strong | mh_short_strong
stats(m_force & m_bias & m_mh_strong, 'F1+F2+F3 STRONG: + MH сильно ЗА')

# In MH window only
in_mh = trades_closed['mh_p96'].notna()
stats(in_mh, 'In MH window (no filter)')
stats(in_mh & m_force, 'In MH + F1')
stats(in_mh & m_force & m_bias, 'In MH + F1+F2')
stats(in_mh & m_force & m_bias & m_mh, 'In MH + F1+F2+F3')
stats(in_mh & m_force & m_bias & m_mh_strong, 'In MH + F1+F2+F3 STRONG')

# By BIAS individually
print("\n=== By BIAS (sanity check) ===\n")
for b in trades_closed['bias'].dropna().unique():
    stats(trades_closed['bias']==b, f'BIAS = {b}')

OUT = ROOT/'mec_v2_filtered_trades.parquet'
trades_closed.to_parquet(OUT, index=False)
print(f"\n[DONE] enriched trades saved to {OUT}")
