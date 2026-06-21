"""P4ZR — Phase 4 Zone Reversion strategy backtest на 6y BTC.

Стратегия:
  - Сигнал на close каждого 12h-бара
  - Direction: 3D_net > +T (LONG) или < -T (SHORT)
  - BIAS filter: не UNANIMOUS (= тренд, не разворот)
  - Entry: top-1 same-direction zone bounds
  - SL: zone edge + 0.1% buffer; reject если |SL| > 1%
  - TP1: nearest opposing zone mid
  - RR ≥ 2 required
  - Max hold 60h
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.home()/'smc-lib/prediction-algo'))
sys.path.insert(0, str(Path.home()/'smc-lib'))

from data import load_btc_1m
from zones import ALL_TYPES, precompute_zone_events, snapshot_from_events
from force_opinion import SMC_TFS, PROXIMITY_PCT, zone_strength

# Strategy params (relaxed v2)
T_DIR_3D = 100       # min 3D net force for direction (200→100)
S_MIN = 50           # min strength of top-1 same-direction zone (100→50)
PROXIMITY_LIMIT = 2.5  # price must be within X% of top-1 same-dir zone (1.5→2.5)
SL_BUFFER = 0.001    # 0.1% buffer under zone
MAX_SL_PCT = 1.5     # reject if SL > 1.5% (1.0→1.5)
MIN_RR = 1.5         # 2.0→1.5
MAX_HOLD_BARS_12H = 7  # 5→7 × 12h = 84h
BIAS_REVERSAL = {'HTF BULLISH bias','HTF BEARISH bias',
                  'BALANCED (weak bias)',
                  'PIVOT signature (HTF BUYER + LTF flip)',
                  'PIVOT signature (HTF SELLER + LTF flip)'}

print("[1/4] Loading 1m...", flush=True)
df_1m_full = load_btc_1m()
print(f"  total: {len(df_1m_full):,} bars", flush=True)

# 1m fast lookup for outcomes
ts_arr = (df_1m_full.index.astype('int64').values // 10**6)  # seconds
high_1m = df_1m_full['high'].values
low_1m = df_1m_full['low'].values
close_1m = df_1m_full['close'].values

def idx_at(t_s):
    return int(np.searchsorted(ts_arr, t_s, side='left'))

def simulate_trade(entry_time_s, entry_px, sl, tp, direction, max_hold_s):
    """Walk 1m forward from entry_time_s. Determine R outcome."""
    a = idx_at(entry_time_s)
    e_lim = min(idx_at(entry_time_s + max_hold_s), len(close_1m))
    if a >= e_lim: return None
    for i in range(a, e_lim):
        if direction == 'LONG':
            # Did price first hit SL or TP?
            if low_1m[i] <= sl and high_1m[i] >= tp:
                return -1.0  # ambiguous, assume SL first (conservative)
            if low_1m[i] <= sl: return -1.0
            if high_1m[i] >= tp:
                return (tp - entry_px) / (entry_px - sl)
        else:  # SHORT
            if high_1m[i] >= sl and low_1m[i] <= tp:
                return -1.0
            if high_1m[i] >= sl: return -1.0
            if low_1m[i] <= tp:
                return (entry_px - tp) / (sl - entry_px)
    # Timeout: close at last close
    final_close = close_1m[e_lim - 1]
    if direction == 'LONG':
        if final_close > entry_px:
            return (final_close - entry_px) / (entry_px - sl)
        else:
            return -(entry_px - final_close) / (entry_px - sl)
    else:
        if final_close < entry_px:
            return (entry_px - final_close) / (sl - entry_px)
        else:
            return -(final_close - entry_px) / (sl - entry_px)

# 12h bars from 1m
agg = {'open':'first','high':'max','low':'min','close':'last','volume':'sum'}
h12 = df_1m_full.resample('12h', label='left', closed='left').agg(agg).dropna()
print(f"  12h bars: {len(h12)}", flush=True)

# Process in 365-day chunks (precompute reset)
print("[2/4] Chunked precompute + signal extraction...", flush=True)
CHUNK_DAYS = 365
WARMUP_DAYS = 180
trades = []
t0 = time.time()
first_ts = h12.index[0]
last_ts = h12.index[-1]
chunk_start = first_ts.normalize()

ch_n = 0
while chunk_start < last_ts:
    ch_n += 1
    chunk_end = chunk_start + pd.Timedelta(days=CHUNK_DAYS)
    win_start = chunk_start - pd.Timedelta(days=WARMUP_DAYS)
    win_end = chunk_end + pd.Timedelta(hours=24)
    df_w = df_1m_full.loc[win_start:win_end]
    print(f"\n[chunk {ch_n}] {chunk_start.date()}..{chunk_end.date()}: 1m={len(df_w):,}", flush=True)
    tpre = time.time()
    events, resampled = precompute_zone_events(df_w, tfs=SMC_TFS, types=ALL_TYPES)
    print(f"  precompute: {time.time()-tpre:.0f}s", flush=True)

    # Iterate over 12h bars in chunk
    chunk_bars = h12.loc[chunk_start:chunk_end - pd.Timedelta(minutes=1)]
    tsig = time.time()
    sig_count = 0
    for ts_open, bar in chunk_bars.iterrows():
        cut_utc = ts_open + pd.Timedelta(hours=12)
        try:
            zones = snapshot_from_events(events, resampled, df_w, cut_utc)
        except Exception:
            continue
        price = float(bar['close'])

        # Compute force per TF
        tf_buyer = {}; tf_seller = {}
        for tf in SMC_TFS:
            tz = [z for z in zones if z.tf == tf and abs(z.distance_pct) < PROXIMITY_PCT]
            tf_buyer[tf] = sum(zone_strength(z) for z in tz if z.direction.lower()=='long')
            tf_seller[tf] = sum(zone_strength(z) for z in tz if z.direction.lower()=='short')

        d3_net = tf_buyer.get('3d', 0) - tf_seller.get('3d', 0)
        total_net = sum(tf_buyer.values()) - sum(tf_seller.values())
        n_wins = sum(1 for tf in SMC_TFS if tf_buyer[tf] > tf_seller[tf])

        # BIAS classification (simplified — same as force_opinion)
        if n_wins == 9: bias = 'UNANIMOUS BULLISH'
        elif n_wins == 0: bias = 'UNANIMOUS BEARISH'
        elif n_wins >= 7 and total_net > 0:
            ltf_b = sum(tf_buyer[t] for t in ('1h','2h','4h'))
            ltf_s = sum(tf_seller[t] for t in ('1h','2h','4h'))
            bias = 'PIVOT signature (HTF BUYER + LTF flip)' if ltf_s > ltf_b else 'HTF BULLISH bias'
        elif n_wins <= 2 and total_net < 0:
            ltf_b = sum(tf_buyer[t] for t in ('1h','2h','4h'))
            ltf_s = sum(tf_seller[t] for t in ('1h','2h','4h'))
            bias = 'PIVOT signature (HTF SELLER + LTF flip)' if ltf_b > ltf_s else 'HTF BEARISH bias'
        elif abs(total_net) < 100: bias = 'BALANCED (weak bias)'
        elif total_net > 0: bias = 'HTF BULLISH bias'
        else: bias = 'HTF BEARISH bias'

        # Skip if not reversal BIAS
        if bias not in BIAS_REVERSAL: continue

        # Direction filter via 3D
        if d3_net > T_DIR_3D:
            direction = 'LONG'
        elif d3_net < -T_DIR_3D:
            direction = 'SHORT'
        else:
            continue

        # Find top same-direction zones in ±3% near price
        if direction == 'LONG':
            same_dir = [(z, zone_strength(z)) for z in zones
                        if z.direction.lower()=='long' and abs(z.distance_pct) < 3.0]
            opp_dir  = [(z, zone_strength(z)) for z in zones
                        if z.direction.lower()=='short' and abs(z.distance_pct) < 3.0]
        else:
            same_dir = [(z, zone_strength(z)) for z in zones
                        if z.direction.lower()=='short' and abs(z.distance_pct) < 3.0]
            opp_dir  = [(z, zone_strength(z)) for z in zones
                        if z.direction.lower()=='long' and abs(z.distance_pct) < 3.0]

        if not same_dir: continue
        same_dir.sort(key=lambda x: -x[1])
        top_z, top_str = same_dir[0]
        if top_str < S_MIN: continue

        # Zone bounds (z.lo, zone_hi exist on ActiveZone)
        z_lo = float(top_z.lo); z_hi = float(top_z.hi)
        if direction == 'LONG':
            entry_px = z_hi  # enter near top of LONG zone
            sl = z_lo * (1 - SL_BUFFER)
            if (entry_px - sl) / entry_px * 100 > MAX_SL_PCT: continue
            # Check proximity: price within 1.5% of entry
            if abs(price - entry_px) / price * 100 > PROXIMITY_LIMIT: continue
        else:
            entry_px = z_lo  # enter near bottom of SHORT zone
            sl = z_hi * (1 + SL_BUFFER)
            if (sl - entry_px) / entry_px * 100 > MAX_SL_PCT: continue
            if abs(price - entry_px) / price * 100 > PROXIMITY_LIMIT: continue

        # TP = mid of nearest opposing zone (above for LONG, below for SHORT)
        if direction == 'LONG':
            opp_above = [(z, s) for (z, s) in opp_dir if (z.lo + z.hi)/2 > entry_px]
            if not opp_above: continue
            opp_above.sort(key=lambda x: (x[0].lo + x[0].hi)/2)
            tp_z = opp_above[0][0]
            tp = (float(tp_z.lo) + float(tp_z.hi))/2
        else:
            opp_below = [(z, s) for (z, s) in opp_dir if (z.lo + z.hi)/2 < entry_px]
            if not opp_below: continue
            opp_below.sort(key=lambda x: -(x[0].lo + x[0].hi)/2)
            tp_z = opp_below[0][0]
            tp = (float(tp_z.lo) + float(tp_z.hi))/2

        # RR check
        if direction == 'LONG':
            rr = (tp - entry_px) / (entry_px - sl) if (entry_px-sl) > 0 else 0
        else:
            rr = (entry_px - tp) / (sl - entry_px) if (sl-entry_px) > 0 else 0
        if rr < MIN_RR: continue

        # Simulate from cut_utc onward
        entry_ts_s = int(cut_utc.timestamp())
        max_hold_s = MAX_HOLD_BARS_12H * 12 * 3600
        R = simulate_trade(entry_ts_s, entry_px, sl, tp, direction, max_hold_s)
        if R is None: continue
        sig_count += 1
        trades.append({
            'signal_time': cut_utc,
            'direction': direction,
            'price': price, 'entry': entry_px, 'sl': sl, 'tp': tp,
            'rr_planned': rr, 'R': R,
            'd3_net': d3_net, 'total_net': total_net, 'n_wins': n_wins, 'bias': bias,
            'top_str': top_str,
        })
    print(f"  signals: {sig_count}  snapshot+sim: {time.time()-tsig:.0f}s  elapsed: {(time.time()-t0)/60:.1f}m", flush=True)
    chunk_start = chunk_end

# Aggregate
print(f"\n[3/4] Aggregating {len(trades)} trades...", flush=True)
tdf = pd.DataFrame(trades)
OUT = Path.home() / 'Desktop/p4zr_v2_btc_6y_trades.parquet'
tdf.to_parquet(OUT, index=False)
print(f"  saved → {OUT}")

print(f"\n[4/4] Stats:")
n = len(tdf)
if n == 0:
    print("  NO TRADES — relax params")
    sys.exit(0)

W = (tdf['R']>0).sum(); L = (tdf['R']<0).sum()
wr = W/n*100; pnl = tdf['R'].sum()
gw = tdf.loc[tdf['R']>0,'R'].sum(); gl = abs(tdf.loc[tdf['R']<0,'R'].sum())
pf = gw/gl if gl>0 else float('inf')
aw = tdf.loc[tdf['R']>0,'R'].mean() if W else 0
al = tdf.loc[tdf['R']<0,'R'].mean() if L else 0
rr = aw/abs(al) if al!=0 else float('inf')
years = (tdf['signal_time'].max() - tdf['signal_time'].min()).days / 365

print(f"  Years:        {years:.2f}")
print(f"  Trades:       {n} ({W} W / {L} L)")
print(f"  WR:           {wr:.2f}%")
print(f"  Total R:      {pnl:+.2f}R")
print(f"  R/trade:      {pnl/n:+.3f}R")
print(f"  Avg win:      {aw:+.3f}R")
print(f"  Avg loss:     {al:+.3f}R")
print(f"  RR:           {rr:.3f}")
print(f"  PF:           {pf:.3f}")
print(f"  Freq:         {n/(years*12):.2f}/мес")

# By year
print(f"\n  By year:")
tdf['year'] = tdf['signal_time'].dt.year
by_y = tdf.groupby('year').agg(n=('R','size'), wr=('R', lambda s: (s>0).sum()/len(s)*100),
                                 total_R=('R','sum'))
print(by_y.round(2).to_string())

# By direction
print(f"\n  By direction:")
by_d = tdf.groupby('direction').agg(n=('R','size'),
                                      wr=('R', lambda s: (s>0).sum()/len(s)*100),
                                      total_R=('R','sum'),
                                      r_per=('R','mean'))
print(by_d.round(3).to_string())

# By BIAS
print(f"\n  By BIAS:")
by_b = tdf.groupby('bias').agg(n=('R','size'),
                                wr=('R', lambda s: (s>0).sum()/len(s)*100),
                                total_R=('R','sum'),
                                r_per=('R','mean'))
print(by_b.round(3).to_string())
