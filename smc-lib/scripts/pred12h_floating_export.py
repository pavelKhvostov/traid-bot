"""Экспорт pure floating BTC 6y signals + trades в parquet.

Запускает collect_signals + simulate_floating с D-winner конфигом etap108,
сохраняет per-signal результат:
  signal_time, direction, htf, ltf, outcome, R, exit_reason, hold_h, max_R

Для grid search C8: фильтрация signal_time по trade-окнам + агрегация stats.
"""
from __future__ import annotations
import sys, importlib.util, time
from pathlib import Path
import pandas as pd

ROOT = Path.home() / 'traid-bot'
sys.path.insert(0, str(ROOT))

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m
    spec.loader.exec_module(m); return m

e104 = load_mod('e104', ROOT / 'research/elements_study/etap_104_floating_variants.py')
e103 = load_mod('e103', ROOT / 'research/elements_study/etap_103_floating_tp.py')

print("[1/3] Collecting BTC signals...")
t0 = time.time()
sigs, df_1m, df_1h, df_2h, years = e104.collect_signals("BTCUSDT")
print(f"  signals: {len(sigs)}, years={years:.2f}, took {time.time()-t0:.0f}s")

print("[2/3] Score series...")
score_long, score_short = e103.build_score_series(df_1h)

print("[3/3] Simulating floating (R_cap=4.5, threshold=-0.25, confirm=2)...")
trades = e104.evaluate_variant(
    "D_BTC",
    lambda s: e104.variant_rcap_score(s, df_1m, df_1h, score_long, score_short,
                                       R_cap=4.5, threshold=-0.25, confirm=2),
    sigs)
print(f"  trades produced: {len(trades)}")

# Normalize to dataframe
rows = []
for t in trades:
    rows.append({
        'signal_time': pd.Timestamp(t['signal_time']),
        'direction': t['direction'],
        'htf': t.get('htf'),
        'ltf': t.get('ltf'),
        'outcome': t['outcome'],
        'R': float(t['R']),
        'exit_reason': t.get('exit_reason'),
        'hold_h': float(t.get('hold_h', 0)),
        'max_R': float(t.get('max_R', 0)),
    })
df = pd.DataFrame(rows)
OUT = Path.home() / 'Desktop/floating_btc_6y_trades.parquet'
df.to_parquet(OUT, index=False)
print(f"\n[DONE] saved {len(df):,} signal-trades to {OUT}")
print(f"  closed: {(df['outcome'].isin(['win','loss','flat'])).sum()}")
print(f"  WR: {(df['R']>0).sum()/(df['outcome'].isin(['win','loss','flat'])).sum()*100:.1f}%")
print(f"  Total R: {df[df['outcome'].isin(['win','loss','flat'])]['R'].sum():+.2f}")
