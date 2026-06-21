"""MEC v1 backtest — Multi-Expert Confluence на BTC 6y, leverage x20.

Стратегия:
  TRIGGER L1: baseline pivot ∈ basket C1-C7 (pred12h fire) — REQUIRED

  DIRECTION: FH→SHORT, FL→LONG

  L2/L3 фильтр (мягкий, на cached данных):
    - skip если 3D_net сильно против direction (≥ FORCE_OPPOSE)
    - skip если MH 96h сильно против (top-10%) — если MH данные есть

  EXECUTE x20:
    Entry: open следующего 12h-бара (strict, no lookahead)
    SL: ±SL_PCT% от entry (default 2%)
    TP1: ±TP_PCT% (default 4% = RR 2.0)
    Max hold: 96h

  Outcome:
    SL hit → -1R
    TP hit → +RR_planned
    timeout → linear from current price
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

# Params
SL_PCT = 0.02       # 2% structural SL (x20)
TP_PCT = 0.04       # 4% = RR 2.0
MAX_HOLD_H = 96     # 96h max
FORCE_OPPOSE_3D = 500   # skip если 3D-сила против > этого
MH_OPPOSE = 3.0     # skip если MH 96h против > этого

# Load parquets
ROOT = Path.home() / 'Desktop'
base = pd.read_parquet(ROOT/'pred12h_baseline_c1c7.parquet')
force = pd.read_parquet(ROOT/'pred12h_C8_force_6y.parquet')

# Merge
df = base.merge(force[['pivot_open_ts_ms','direction','total_net','d3_net','n_wins','bias','force_match']],
                on=['pivot_open_ts_ms','direction'], how='left')

# Filter to basket pivots only (L1 trigger)
df = df[df['in_basket']].copy()
print(f"Basket pivots (L1 trigger): {len(df)}")

# MH data
mh = pd.read_csv(ROOT/'PC2/mh_predictions.csv')
mh['ts'] = pd.to_datetime(mh['ts'], utc=True)
mh = mh.sort_values('ts').reset_index(drop=True)
mh_min, mh_max = mh.ts.min(), mh.ts.max()
print(f"MH range: {mh_min} → {mh_max}")
mh_idx = mh.set_index('ts')

def mh_at(t_utc):
    if t_utc < mh_min or t_utc > mh_max: return None
    pos = mh_idx.index.searchsorted(t_utc, side='right') - 1
    if pos < 0: return None
    return mh_idx.iloc[pos]['pred_96h']

# Load 1m for outcome simulation
print("Loading 1m...")
df_1m = pd.read_csv(Path.home()/'traid-bot/data/BTCUSDT_1m_vic_vadim.csv')
df_1m['open_time'] = pd.to_datetime(df_1m['open_time'], utc=True, format='mixed')
df_1m = df_1m.set_index('open_time').sort_index()
ts_arr = (df_1m.index.astype('int64').values // 10**6)  # seconds
hi = df_1m['high'].values
lo = df_1m['low'].values
cl = df_1m['close'].values
op = df_1m['open'].values
print(f"  1m bars: {len(df_1m):,}")

def idx_at(t_s):
    return int(np.searchsorted(ts_arr, t_s, side='left'))

def simulate(entry_ts_s, entry_px, sl, tp, direction):
    a = idx_at(entry_ts_s)
    e_lim = min(idx_at(entry_ts_s + MAX_HOLD_H*3600), len(cl))
    if a >= e_lim: return None
    for i in range(a, e_lim):
        if direction == 'LONG':
            sl_hit = lo[i] <= sl
            tp_hit = hi[i] >= tp
            if sl_hit and tp_hit: return -1.0
            if sl_hit: return -1.0
            if tp_hit: return (tp - entry_px) / (entry_px - sl)
        else:
            sl_hit = hi[i] >= sl
            tp_hit = lo[i] <= tp
            if sl_hit and tp_hit: return -1.0
            if sl_hit: return -1.0
            if tp_hit: return (entry_px - tp) / (sl - entry_px)
    # Timeout
    final = cl[e_lim - 1]
    if direction == 'LONG':
        return (final - entry_px) / (entry_px - sl)
    else:
        return (entry_px - final) / (sl - entry_px)

# Build trades
print("Building trades...")
trades = []
for _, r in df.iterrows():
    pivot_close_utc = pd.Timestamp(r['pivot_open_ts_ms'], unit='ms', tz='UTC') + pd.Timedelta(hours=12)
    # Direction: FH → SHORT, FL → LONG
    trade_dir = 'SHORT' if r['direction'] == 'high' else 'LONG'

    # Filter: 3D force strongly opposing? skip
    d3 = r['d3_net'] if pd.notna(r['d3_net']) else 0
    if trade_dir == 'SHORT' and d3 > FORCE_OPPOSE_3D: continue
    if trade_dir == 'LONG' and d3 < -FORCE_OPPOSE_3D: continue

    # MH check (if available)
    p96 = mh_at(pivot_close_utc)
    mh_used = p96 is not None
    if mh_used:
        if trade_dir == 'SHORT' and p96 > MH_OPPOSE: continue
        if trade_dir == 'LONG' and p96 < -MH_OPPOSE: continue

    # Entry: NEXT 12h bar open = pivot_close (= bar i CLOSE = bar i+1 OPEN)
    entry_ts_s = int(pivot_close_utc.timestamp())
    entry_idx = idx_at(entry_ts_s)
    if entry_idx >= len(op): continue
    entry_px = float(op[entry_idx])

    if trade_dir == 'LONG':
        sl = entry_px * (1 - SL_PCT)
        tp = entry_px * (1 + TP_PCT)
    else:
        sl = entry_px * (1 + SL_PCT)
        tp = entry_px * (1 - TP_PCT)

    R = simulate(entry_ts_s, entry_px, sl, tp, trade_dir)
    if R is None: continue

    trades.append({
        'signal_time': pivot_close_utc,
        'direction': trade_dir,
        'pivot_type': r['direction'],
        'entry': entry_px, 'sl': sl, 'tp': tp,
        'R': float(R),
        'd3_net': d3, 'total_net': r.get('total_net', 0),
        'bias': r.get('bias'),
        'is_imp': r['is_imp'], 'confirmed': r['confirmed'],
        'mh_p96': p96, 'mh_used': mh_used,
    })

tdf = pd.DataFrame(trades)
print(f"\nTotal trades: {len(tdf)}")
OUT = Path.home() / 'Desktop/mec_v1_btc_6y_trades.parquet'
tdf.to_parquet(OUT, index=False)

# Stats
n = len(tdf)
W = (tdf['R']>0).sum(); L = (tdf['R']<0).sum()
wr = W/n*100
pnl = tdf['R'].sum()
gw = tdf.loc[tdf['R']>0,'R'].sum(); gl = abs(tdf.loc[tdf['R']<0,'R'].sum())
pf = gw/gl if gl>0 else float('inf')
aw = tdf.loc[tdf['R']>0,'R'].mean() if W else 0
al = tdf.loc[tdf['R']<0,'R'].mean() if L else 0
rr = aw/abs(al) if al!=0 else float('inf')
years = (tdf['signal_time'].max() - tdf['signal_time'].min()).days / 365

print(f"\n=== MEC v1 Strategy Stats ===")
print(f"  Years:        {years:.2f}")
print(f"  Trades:       {n} ({W} W / {L} L)")
print(f"  WR:           {wr:.2f}%")
print(f"  Total R:      {pnl:+.2f}R")
print(f"  R / trade:    {pnl/n:+.3f}R")
print(f"  Avg win:      {aw:+.3f}R")
print(f"  Avg loss:     {al:+.3f}R")
print(f"  RR:           {rr:.3f}")
print(f"  PF:           {pf:.3f}")
print(f"  Freq:         {n/(years*12):.2f}/мес")

print(f"\n  By direction:")
by_d = tdf.groupby('direction').agg(n=('R','size'),
                                      wr=('R', lambda s: (s>0).sum()/len(s)*100),
                                      total_R=('R','sum'),
                                      r_per=('R','mean'))
print(by_d.round(3).to_string())

print(f"\n  By year:")
tdf['year'] = tdf['signal_time'].dt.year
by_y = tdf.groupby('year').agg(n=('R','size'),
                                wr=('R', lambda s: (s>0).sum()/len(s)*100),
                                total_R=('R','sum'))
print(by_y.round(2).to_string())

print(f"\n  By BIAS:")
by_b = tdf.groupby('bias').agg(n=('R','size'),
                                wr=('R', lambda s: (s>0).sum()/len(s)*100),
                                total_R=('R','sum'),
                                r_per=('R','mean'))
print(by_b.round(3).to_string())

# Compare MH used vs not
if tdf['mh_used'].any():
    print(f"\n  MH availability:")
    by_mh = tdf.groupby('mh_used').agg(n=('R','size'),
                                       wr=('R', lambda s: (s>0).sum()/len(s)*100),
                                       total_R=('R','sum'),
                                       r_per=('R','mean'))
    print(by_mh.round(3).to_string())
