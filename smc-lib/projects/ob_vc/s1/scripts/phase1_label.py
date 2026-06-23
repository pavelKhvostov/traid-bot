"""ob_vc s1 — Phase 1: Label all 2h ob_vc events (strict, lookahead-free).

Target: hit_RR_2 — entry filled, hit TP=2R before SL=1R within max_horizon.

Canon entry (V1 — для baseline):
  Entry  = mid zone (deep=0.5 — simplified; реальный canon depends on n_FVG)
  SL     = drop edge (zone_lo для LONG, zone_hi для SHORT)
  R      = |entry - SL|
  TP     = entry ± 2R  (RR target 2:1)

Strict timing:
  Entry timing = ts of ob_vc event (= HTF close = canon rule #9)
  Entry FILL — pending limit, ждём fill до max 7 days
  После fill: simulate forward до 14 days до TP/SL

Output: ~/smc-lib/projects/ob_vc/s1/data/labels_2h.parquet
"""
import sys, time, pathlib
import pandas as pd, numpy as np

P_EVENTS = pathlib.Path.home() / "smc-lib/projects/живой-рынок/data/events_v12_2020-01-01_2026-06-15.parquet"
CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT_DIR = pathlib.Path.home() / "smc-lib/projects/ob_vc/s1/data"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = OUT_DIR / "labels_2h.parquet"

RR_TARGET = 1.0   # TP at 1R (canon TBM, WR > 70% target)
MAX_FILL_WAIT_MS = 7 * 24 * 3600 * 1000
MAX_HORIZON_MS   = 14 * 24 * 3600 * 1000

print("Loading e12 events ...", flush=True)
e = pd.read_parquet(P_EVENTS)
ov2h = e[(e.element_type=='ob_vc') & (e.action=='born') & (e.tf=='2h')]
print(f"  2h ob_vc born (raw): {len(ov2h):,}", flush=True)
# Dedup HTF×LTF: per (source_idx, direction)
agg = ov2h.groupby(['source_idx','direction']).size().reset_index(name='n_ltf_triggers')
first = ov2h.drop_duplicates(['source_idx','direction'], keep='first')[['source_idx','direction','ts','zone_lo','zone_hi']]
events = first.merge(agg, on=['source_idx','direction']).sort_values('ts').reset_index(drop=True)
print(f"  Unique 2h ob_vc: {len(events):,}", flush=True)

print("Loading 1m bars ...", flush=True)
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
print(f"  1m bars: {N:,} ({time.time()-t0:.1f}s)", flush=True)

print(f"\nLabeling {len(events):,} 2h ob_vc events ...", flush=True)
rows = []
ptr = 0
t0 = time.time()
for i, r in enumerate(events.itertuples(index=False)):
    ts_event = int(r.ts)
    direction = r.direction
    zone_lo, zone_hi = float(r.zone_lo), float(r.zone_hi)
    entry = (zone_lo + zone_hi) / 2
    if direction == 'long':
        sl = zone_lo
        if entry <= sl: continue
        R = entry - sl
        tp = entry + RR_TARGET * R
    else:
        sl = zone_hi
        if entry >= sl: continue
        R = sl - entry
        tp = entry - RR_TARGET * R

    # Advance ptr
    while ptr < N and ts_arr[ptr] < ts_event:
        ptr += 1
    if ptr >= N:
        break

    # Phase A: wait for entry fill (pending limit)
    end_fill = ts_event + MAX_FILL_WAIT_MS
    k = ptr; fill_idx = -1
    while k < N and ts_arr[k] < end_fill:
        if direction == 'long' and lo_arr[k] <= entry: fill_idx = k; break
        if direction == 'short' and hi_arr[k] >= entry: fill_idx = k; break
        k += 1
    if fill_idx < 0:
        rows.append({'ts': ts_event, 'source_idx': int(r.source_idx),
                     'direction': direction, 'zone_lo': zone_lo, 'zone_hi': zone_hi,
                     'entry': entry, 'sl': sl, 'tp': tp, 'R': R,
                     'n_ltf_triggers': int(r.n_ltf_triggers),
                     'outcome':'no_fill', 'hit_rr1':0, 'r_result':0.0,
                     'ts_fill': None, 'wait_h': None})
        continue
    ts_fill = int(ts_arr[fill_idx])
    wait_h = (ts_fill - ts_event) / 3600_000.0

    # Phase B: simulate TP vs SL
    j = fill_idx
    end_sim = ts_fill + MAX_HORIZON_MS
    while j < N and ts_arr[j] < end_sim: j += 1
    win_lo = lo_arr[fill_idx:j]
    win_hi = hi_arr[fill_idx:j]
    if direction == 'long':
        sl_hits = np.where(win_lo <= sl)[0]
        tp_hits = np.where(win_hi >= tp)[0]
    else:
        sl_hits = np.where(win_hi >= sl)[0]
        tp_hits = np.where(win_lo <= tp)[0]
    sl_first = int(sl_hits[0]) if len(sl_hits) else -1
    tp_first = int(tp_hits[0]) if len(tp_hits) else -1
    if sl_first == -1 and tp_first == -1:
        outcome = 'no_close'; hit = 0; r_res = 0.0
    elif tp_first != -1 and (sl_first == -1 or tp_first < sl_first):
        outcome = 'tp'; hit = 1; r_res = RR_TARGET
    elif sl_first != -1 and (tp_first == -1 or sl_first < tp_first):
        outcome = 'sl'; hit = 0; r_res = -1.0
    else:
        outcome = 'sl_same_bar'; hit = 0; r_res = -1.0

    rows.append({
        'ts': ts_event,
        'source_idx': int(r.source_idx),
        'direction': direction,
        'zone_lo': zone_lo, 'zone_hi': zone_hi,
        'entry': entry, 'sl': sl, 'tp': tp, 'R': R,
        'n_ltf_triggers': int(r.n_ltf_triggers),
        'outcome': outcome, 'hit_rr1': hit, 'r_result': r_res,
        'ts_fill': ts_fill, 'wait_h': wait_h,
    })
    if (i+1) % 1000 == 0:
        elapsed = time.time() - t0
        rate = (i+1) / elapsed
        print(f"  {i+1:>4}/{len(events)}  ({rate:.0f}/s)", flush=True)

df = pd.DataFrame(rows)
df.to_parquet(OUT, compression='zstd', compression_level=9, index=False)
print(f"\nSaved {len(df):,} → {OUT}")

# Stats
print()
print("=== Outcome ===")
print(df['outcome'].value_counts().to_string())
closed = df[df['outcome'].isin(['tp','sl','sl_same_bar'])]
print()
print(f"Closed: {len(closed):,}")
print(f"hit_RR_1: {df['hit_rr1'].sum():,}")
print(f"WR (hit_RR_1 / closed): {df['hit_rr1'].sum() / max(len(closed),1) * 100:.2f}%")
print(f"Σ R: {df['r_result'].sum():.0f}")
print(f"EV/trade: {df['r_result'].mean():.3f}")
print(f"Trades/мес closed: {len(closed)/78:.1f}")
print()
print("=== Per direction ===")
print(closed.groupby('direction')[['hit_rr1','r_result']].agg(['count','mean','sum']).to_string())
