"""Дамп baseline F1∩F2∩F3 пивотов с C1-C7 флагами в parquet.

Использует pred12h_basket_c1c2c3.py, забирает pivots с уже-вычисленными
c1..c7, confirmed, is_imp. Без Phase 4 force (это в отдельном parquet).

Output: ~/Desktop/pred12h_baseline_c1c7.parquet
"""
from __future__ import annotations
import sys, importlib.util, io, contextlib
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path.home() / 'smc-lib'))

spec = importlib.util.spec_from_file_location(
    "basket", Path.home() / 'smc-lib/scripts/pred12h_basket_c1c2c3.py'
)
mod = importlib.util.module_from_spec(spec); sys.modules['basket'] = mod
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    spec.loader.exec_module(mod)

pivots = mod.pivots
print(f"Loaded {len(pivots)} baseline pivots")

rows = []
for p in pivots:
    rows.append({
        'pivot_open_ts_ms': p['pivot_open_ts'],
        'direction': p['direction'],
        'confirmed': p['confirmed'],
        'is_imp': p.get('is_imp', False),
        'pivot_high': p.get('pivot_high'),
        'pivot_low': p.get('pivot_low'),
        'c1': p.get('c1', False),
        'c2': p.get('c2', False),
        'c3': p.get('c3', False),
        'c4': p.get('c4', False),
        'c5': p.get('c5', False),
        'c6': p.get('c6', False),
        'c7': p.get('c7', False),
    })
df = pd.DataFrame(rows)
df['in_basket'] = df[[f'c{i}' for i in range(1,8)]].any(axis=1)
df['pivot_open_ts'] = pd.to_datetime(df['pivot_open_ts_ms'], unit='ms', utc=True)
df['pivot_close_ts'] = df['pivot_open_ts'] + pd.Timedelta(hours=12)

OUT = Path.home() / 'Desktop/pred12h_baseline_c1c7.parquet'
df.to_parquet(OUT, index=False)
print(f"\n[DONE] saved {len(df):,} pivots to {OUT}")
print(f"  Confirmed: {df['confirmed'].sum()}/{len(df)} = {df['confirmed'].mean()*100:.1f}%")
print(f"  in_basket: {df['in_basket'].sum()}/{len(df)} = {df['in_basket'].mean()*100:.1f}%")
print(f"  imp: {df['is_imp'].sum()}/18")
print(f"  Range: {df['pivot_open_ts'].min()} -> {df['pivot_open_ts'].max()}")
