"""Reconstruct 24-type classification ob_vc и посчитать количество per type.

Dimensions per canon:
  • direction: long / short
  • swept: 1.1.1 — min(prev.low, cur.low) < min(prev2.low, prev3.low) для LONG (зеркально SHORT)
  • n_FVG: 1 vs ≥2 — здесь использую proxy = n_ltf_triggers (sum unique LTF triggers per OB)
  • extreme: prev / cur — какая свеча имеет lower low (LONG) / higher high (SHORT)
  • wick_ratio (только для extreme=prev): prev_wick / cur_wick ≥ 2× → suffix 'a', иначе 'b'

T-mapping (compatible with memory canon):
  Каждая комбинация (direction × swept × n_FVG × extreme) → T1..T16
  Extreme=prev split → suffix a/b
"""
import sys, time, pathlib
import pandas as pd
import numpy as np

P = pathlib.Path.home() / "smc-lib/projects/живой-рынок/data"
EVENTS = P / "events_v12_2020-01-01_2026-06-15.parquet"
CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = P / "ob_vc_24types_classified.parquet"

HTF_TFS = ['1h', '2h', '4h', '6h', '12h', '1D']
HTF_MS = {'1h':3600_000, '2h':7200_000, '4h':14400_000, '6h':21600_000, '12h':43200_000, '1D':86400_000}

print("Loading e12 events...", flush=True)
e = pd.read_parquet(EVENTS)
ov = e[(e.element_type=='ob_vc') & (e.action=='born')].copy()
print(f"  raw: {len(ov):,}", flush=True)

# Dedup + count n_ltf_triggers per unique OB
agg = ov.groupby(['tf','source_idx','direction']).size().reset_index(name='n_ltf_triggers')
# Take first event per group for ts
first = ov.drop_duplicates(['tf','source_idx','direction'], keep='first')[['tf','source_idx','direction','ts','zone_lo','zone_hi']]
ov_dedup = first.merge(agg, on=['tf','source_idx','direction'])
print(f"  dedup: {len(ov_dedup):,}", flush=True)

print("\nLoading 1m bars + resampling to HTFs ...", flush=True)
t0 = time.time()
m = pd.read_csv(CSV_1M, usecols=['open_time','open','high','low','close'])
_dt = pd.to_datetime(m['open_time'], format='ISO8601', utc=True)
_epoch = pd.Timestamp('1970-01-01', tz='UTC')
m['ts_ms'] = ((_dt - _epoch).dt.total_seconds() * 1000).astype('int64')
m = m.sort_values('ts_ms').reset_index(drop=True)
print(f"  1m loaded: {len(m):,} ({time.time()-t0:.1f}s)", flush=True)

# Resample to each HTF — use ts_ms floored to TF boundary as group key
def resample_htf(m_df, tf_ms):
    grp = (m_df['ts_ms'] // tf_ms) * tf_ms
    agg = m_df.groupby(grp, sort=True).agg(
        open=('open','first'), high=('high','max'),
        low=('low','min'), close=('close','last')
    )
    agg.index.name = 'bar_open_ts'
    return agg.reset_index()

htf_bars = {}
for tf in HTF_TFS:
    htf_bars[tf] = resample_htf(m, HTF_MS[tf])
    print(f"  {tf}: {len(htf_bars[tf]):,} bars", flush=True)

# Build index dict per tf: bar_open_ts → row index
htf_idx = {tf: dict(zip(b['bar_open_ts'].values, range(len(b)))) for tf, b in htf_bars.items()}

print(f"\nClassifying {len(ov_dedup):,} unique OBs ...", flush=True)
rows = []
unmapped = 0
t0 = time.time()
for i, r in enumerate(ov_dedup.itertuples(index=False)):
    tf = r.tf
    direction = r.direction
    ts_event = int(r.ts)
    n_ltf = int(r.n_ltf_triggers)
    bars = htf_bars[tf]
    idx_map = htf_idx[tf]
    tf_ms = HTF_MS[tf]

    # The event ts is HTF close (born) = bar_open_ts + tf_ms (i.e., next bar's open)
    # cur bar open = ts_event - tf_ms
    cur_open_ts = ts_event - tf_ms
    cur_idx = idx_map.get(cur_open_ts)
    if cur_idx is None or cur_idx < 3:
        unmapped += 1
        continue
    cur = bars.iloc[cur_idx]
    prev = bars.iloc[cur_idx - 1]
    prev2 = bars.iloc[cur_idx - 2]
    prev3 = bars.iloc[cur_idx - 3]

    # Swept canon 1.1.1
    if direction == 'long':
        swept = bool(min(prev['low'], cur['low']) < min(prev2['low'], prev3['low']))
    else:
        swept = bool(max(prev['high'], cur['high']) > max(prev2['high'], prev3['high']))

    # Extreme: какая свеча имеет более экстремальный low (LONG) / high (SHORT)
    if direction == 'long':
        if prev['low'] <= cur['low']:
            extreme = 'prev'
        else:
            extreme = 'cur'
    else:
        if prev['high'] >= cur['high']:
            extreme = 'prev'
        else:
            extreme = 'cur'

    # wick_ratio (только для extreme=prev)
    wick_suffix = ''
    if extreme == 'prev':
        if direction == 'long':
            prev_wick = min(prev['open'], prev['close']) - prev['low']
            cur_wick  = min(cur['open'],  cur['close'])  - cur['low']
        else:
            prev_wick = prev['high'] - max(prev['open'], prev['close'])
            cur_wick  = cur['high']  - max(cur['open'],  cur['close'])
        if cur_wick <= 0:
            wick_ratio = float('inf')
        else:
            wick_ratio = prev_wick / cur_wick
        wick_suffix = 'a' if wick_ratio >= 2.0 else 'b'

    # n_FVG proxy: 1 если n_ltf_triggers==1 else ≥2
    n_fvg = 1 if n_ltf == 1 else 2

    # Type mapping per memory canon T1-T16
    # Order: direction × swept × n_FVG × extreme
    # Memory dump показал, что numbering такой:
    # Если использовать упорядоченный generator (по 4 dim) — я могу пронумеровать вручную:
    # (long, swept,    n=1, prev)  → T1
    # (long, swept,    n=1, cur)   → T2
    # (long, swept,    n=2, prev)  → T3
    # (long, swept,    n=2, cur)   → T4
    # (long, no-swept, n=1, prev)  → T5
    # ...
    # Этот mapping не строгий — точное значение T# зависит от memory canon mapping
    # Здесь используем компактное type_label вместо точного T#:
    type_label = f"{direction[0].upper()}_{'sw' if swept else 'nsw'}_n{n_fvg}_{extreme}{wick_suffix}"

    rows.append({
        'ts_event': ts_event,
        'tf': tf,
        'direction': direction,
        'swept': swept,
        'n_fvg_proxy': n_fvg,
        'n_ltf_triggers': n_ltf,
        'extreme': extreme,
        'wick_suffix': wick_suffix,
        'type_label': type_label,
        'zone_lo': float(r.zone_lo), 'zone_hi': float(r.zone_hi),
    })

df = pd.DataFrame(rows)
df.to_parquet(OUT, compression='zstd', compression_level=9, index=False)
print(f"\nClassified: {len(df):,}  (unmapped: {unmapped})")
print(f"Elapsed: {time.time()-t0:.1f}s")
print()
print("=== Count per type ===")
print(df.groupby('type_label').size().sort_values(ascending=False).to_string())
print()
print("=== Per dimension ===")
print("Direction:");     print(df.groupby('direction').size().to_string())
print("Swept:");         print(df.groupby('swept').size().to_string())
print("n_FVG (proxy):"); print(df.groupby('n_fvg_proxy').size().to_string())
print("Extreme:");       print(df.groupby('extreme').size().to_string())
print()
print("=== Per (direction × swept × n_fvg × extreme + wick) ===")
print(df.groupby(['direction','swept','n_fvg_proxy','extreme','wick_suffix']).size().to_string())
print()
print(f"Total unique types: {df['type_label'].nunique()}")
