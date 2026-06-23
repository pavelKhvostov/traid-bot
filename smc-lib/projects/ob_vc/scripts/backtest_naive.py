"""ob_vc backtest на e12 events, 6y BTC, strict timing, dedup HTF×LTF.

Canon rules applied:
  • Entry timing = event ts (strict, no lookahead — e12 emit'ит на close)
  • Entry price = mid zone (deep=0.5; simplified — не дифференцируем n_FVG=1/≥2)
  • SL = drop edge (zone_lo для LONG, zone_hi для SHORT)
  • R = |entry - SL|
  • TP = entry ± 1.7R
  • Simulate forward 1m bars: hit SL vs TP whichever first
  • Max horizon: 7 days; если ни одного — skip
  • Dedup: per (tf, source_idx, direction) — один OB → один trade
"""
import sys, time, pathlib
import pandas as pd
import numpy as np

P = pathlib.Path.home() / "smc-lib/projects/живой-рынок/data"
EVENTS = P / "events_v12_2020-01-01_2026-06-15.parquet"
CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = P / "ob_vc_trades.parquet"

TP_R = 1.7
MAX_FILL_WAIT_MS  = 7 * 24 * 3600 * 1000     # entry must fill в 7 days
MAX_HORIZON_MS    = 7 * 24 * 3600 * 1000     # после fill — еще 7d на TP/SL

print("Loading e12 events...", flush=True)
e = pd.read_parquet(EVENTS)
ob_vc = e[(e['element_type'] == 'ob_vc') & (e['action'] == 'born')].copy()
print(f"  ob_vc born events (raw): {len(ob_vc):,}", flush=True)

# Dedup: per (tf, source_idx, direction) — это уникальный HTF parent OB
ob_vc_dedup = ob_vc.drop_duplicates(subset=['tf', 'source_idx', 'direction']).copy()
print(f"  After dedup HTF×LTF: {len(ob_vc_dedup):,}", flush=True)

print("\nLoading 1m candles...", flush=True)
t0 = time.time()
m = pd.read_csv(CSV_1M, usecols=['open_time','high','low','close'])
_dt = pd.to_datetime(m['open_time'], format='ISO8601', utc=True)
_epoch = pd.Timestamp('1970-01-01', tz='UTC')
m['ts_ms'] = ((_dt - _epoch).dt.total_seconds() * 1000).astype('int64')
m = m.sort_values('ts_ms').reset_index(drop=True)
ts_arr = m['ts_ms'].values
hi_arr = m['high'].values
lo_arr = m['low'].values
N = len(ts_arr)
print(f"  1m rows: {N:,}  ({time.time()-t0:.1f}s)", flush=True)

print(f"\nBacktesting {len(ob_vc_dedup):,} ob_vc trades...", flush=True)
results = []
t0 = time.time()
ob_vc_dedup = ob_vc_dedup.sort_values('ts').reset_index(drop=True)
ptr = 0
for i, row in enumerate(ob_vc_dedup.itertuples(index=False)):
    ts_entry = int(row.ts)
    direction = row.direction
    zone_lo = float(row.zone_lo)
    zone_hi = float(row.zone_hi)

    # entry = mid, SL = drop edge
    entry = (zone_lo + zone_hi) / 2
    if direction == 'long':
        sl = zone_lo
        if entry <= sl: continue
        R = entry - sl
        tp = entry + TP_R * R
    else:   # short
        sl = zone_hi
        if entry >= sl: continue
        R = sl - entry
        tp = entry - TP_R * R

    # Find pointer at ts_entry
    while ptr < N and ts_arr[ptr] < ts_entry:
        ptr += 1
    if ptr >= N:
        break

    # ── PHASE 1: WAIT FOR ENTRY FILL ──
    # Pending limit @ entry — wait for price to come back to entry
    end_fill_ts = ts_entry + MAX_FILL_WAIT_MS
    k = ptr
    fill_idx = -1
    while k < N and ts_arr[k] < end_fill_ts:
        if direction == 'long' and lo_arr[k] <= entry:
            fill_idx = k; break
        if direction == 'short' and hi_arr[k] >= entry:
            fill_idx = k; break
        k += 1
    if fill_idx < 0:
        outcome = 'no_fill'; r = 0.0
        results.append({
            'ts_entry': ts_entry, 'tf': row.tf, 'direction': direction,
            'entry': entry, 'sl': sl, 'tp': tp, 'R': R,
            'outcome': outcome, 'r_result': r, 'source_idx': int(row.source_idx),
            'ts_fill': None, 'wait_h': None,
        })
        continue
    ts_fill = int(ts_arr[fill_idx])
    wait_h = (ts_fill - ts_entry) / 3600_000.0

    # ── PHASE 2: SIMULATE TP vs SL FROM FILL ──
    j = fill_idx
    end_ts = ts_fill + MAX_HORIZON_MS
    while j < N and ts_arr[j] < end_ts:
        j += 1
    win_lo = lo_arr[fill_idx:j]
    win_hi = hi_arr[fill_idx:j]

    # Check whether SL or TP hit first.
    # ВАЖНО: на bar fill_idx цена уже touched entry — нужно проверять SL уже на этом баре!
    # Conservative: на bar fill_idx SL может hit если price went past it. Same logic.
    if direction == 'long':
        sl_hits = np.where(win_lo <= sl)[0]
        tp_hits = np.where(win_hi >= tp)[0]
    else:
        sl_hits = np.where(win_hi >= sl)[0]
        tp_hits = np.where(win_lo <= tp)[0]

    sl_first = int(sl_hits[0]) if len(sl_hits) else -1
    tp_first = int(tp_hits[0]) if len(tp_hits) else -1
    if sl_first == -1 and tp_first == -1:
        outcome = 'no_close'; r = 0.0
    elif tp_first != -1 and (sl_first == -1 or tp_first < sl_first):
        outcome = 'tp'; r = TP_R
    elif sl_first != -1 and (tp_first == -1 or sl_first < tp_first):
        outcome = 'sl'; r = -1.0
    elif sl_first == tp_first:
        outcome = 'sl_same_bar'; r = -1.0
    else:
        outcome = 'no_close'; r = 0.0

    results.append({
        'ts_entry': ts_entry,
        'tf': row.tf,
        'direction': direction,
        'entry': entry,
        'sl': sl,
        'tp': tp,
        'R': R,
        'outcome': outcome,
        'r_result': r,
        'source_idx': int(row.source_idx),
        'ts_fill': ts_fill,
        'wait_h': wait_h,
    })
    if (i+1) % 50000 == 0:
        elapsed = time.time() - t0
        rate = (i+1) / elapsed
        print(f"  {i+1:>6}/{len(ob_vc_dedup):>6}  ({rate:.0f}/s)", flush=True)

df = pd.DataFrame(results)
df.to_parquet(OUT, compression='zstd', compression_level=9, index=False)
print(f"\nSaved {len(df):,} trades → {OUT}")

# Stats
print("\n=== Outcome distribution ===")
print(df['outcome'].value_counts().to_string())
print(f"\n=== Per HTF tf ===")
closed = df[df['outcome'].isin(['tp','sl','sl_same_bar'])]
g = closed.groupby('tf').agg(
    n=('outcome','count'),
    wins=('outcome', lambda s: (s=='tp').sum()),
    sum_R=('r_result','sum'),
)
g['WR'] = g['wins'] / g['n'] * 100
g['EV'] = g['sum_R'] / g['n']
g = g.sort_values('sum_R', ascending=False)
print(g.to_string())

print(f"\n=== Global ===")
print(f"Total closed: {len(closed):,}")
print(f"Wins: {(closed['outcome']=='tp').sum():,}")
print(f"WR: {(closed['outcome']=='tp').mean()*100:.1f}%")
print(f"Σ R: {closed['r_result'].sum():.0f}")
print(f"EV/trade: {closed['r_result'].mean():.3f}")
print(f"Years: ~6.5")
print(f"Trades/мес: {len(closed)/78:.1f}")
