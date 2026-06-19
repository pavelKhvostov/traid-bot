"""Backtest Strategy 1.1.1 БЕЗ confluence на BTC 2020-2026.

Использует canonical floating reference (~/smc-lib/strategies/strategy_1_1_1/strategy_1_1_1_floating.py).
Confluence (USDT.D/BTC.CME/TOTALES) НЕ применяется — reference уже без него.

Окно: 2020-05-01 (первый день доступных 1h+ данных) → 2026-06-05.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path.home()/"smc-lib"))
sys.path.insert(0, str(Path.home()/"smc-lib/strategies/strategy_1_1_1"))
sys.path.insert(0, str(Path.home()/"traid-bot"))

from strategy_1_1_1_floating import (
    run_symbol_backtest, aggregate_stats, FLOATING_TP_CONFIG
)

DATA = Path.home()/"traid-bot/data"

def load_csv(name, tf):
    p = DATA / f"BTCUSDT_{tf}.csv"
    df = pd.read_csv(p)
    df["open_time"] = pd.to_datetime(df["open_time"], format="mixed", utc=True)
    df = df.set_index("open_time").sort_index()
    return df

def compose_12h(df_1h): return df_1h.resample("12h", origin="epoch", label="left", closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
def compose_6h(df_1h):  return df_1h.resample("6h",  origin="epoch", label="left", closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
def compose_2h(df_1h):  return df_1h.resample("2h",  origin="epoch", label="left", closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
def compose_20m(df_15m):
    df_1m = df_15m  # fallback: use 15m bars as proxy for 20m (not exact, but close)
    return df_1m.resample("20min", origin="epoch", label="left", closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

print("Loading data...")
df_1d = load_csv("BTCUSDT", "1d")
df_4h = load_csv("BTCUSDT", "4h")
df_1h = load_csv("BTCUSDT", "1h")
df_15m = load_csv("BTCUSDT", "15m")
df_1m = pd.read_csv(DATA/"BTCUSDT_1m.csv", index_col="open_time")
df_1m.index = pd.to_datetime(df_1m.index, format="ISO8601", utc=True)
df_1m = df_1m.sort_index()

# Compose missing TFs from 1h
df_12h = compose_12h(df_1h)
df_6h  = compose_6h(df_1h)
df_2h  = compose_2h(df_1h)
df_20m = compose_20m(df_15m)

# Crop to 2020-2026 window
START = pd.Timestamp("2020-01-01", tz="UTC")
END = pd.Timestamp.now(tz="UTC")
for name, df in [("1d", df_1d), ("12h", df_12h), ("4h", df_4h), ("6h", df_6h),
                  ("1h", df_1h), ("2h", df_2h), ("15m", df_15m), ("20m", df_20m), ("1m", df_1m)]:
    print(f"  {name}: {len(df):>9,} bars  {df.index.min()} → {df.index.max()}")

print("\n=== Running Strategy 1.1.1 backtest (БЕЗ confluence, Floating TP canon) ===")
print(f"Symbol: BTC | Config: R_cap=4.5, threshold=-0.25, confirm=2 | ENTRY_PCT=0.80, SL_PCT=0.35")
print()

trades = run_symbol_backtest(
    "BTCUSDT",
    df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m,
)
print(f"Total signals → trades: {len(trades)}")

if not trades:
    print("No trades, exiting.")
    sys.exit(0)

stats = aggregate_stats(trades)
print(f"\n=== AGGREGATE STATS ===")
print(f"  N closed:      {stats['n']}")
print(f"  W / L:         {stats['W']} / {stats['L']}")
print(f"  WR:            {stats['WR']}%")
print(f"  Total R:       {stats['total_R']:+.2f}R")
print(f"  R/trade:       {stats['R_per_trade']:+.3f}")
print(f"  Years:         {stats['total_years']}  bad: {stats['bad_years']}")

print(f"\n=== By exit reason ===")
for reason, d in stats["by_exit_reason"].items():
    print(f"  {reason:<15} n={d['n']:>4}  R={d['R']:+.2f}  R/trade={d['R']/d['n']:+.3f}")

print(f"\n=== By year ===")
for yr, R in sorted(stats["by_year"].items()):
    flag = "✓" if R > 0 else "✗"
    print(f"  {yr}: {R:+.2f}R  {flag}")

# Save trades to CSV
import csv
df_trades = pd.DataFrame(trades)
out_csv = Path.home()/"Desktop/backtest_111_btc_2020_2026.csv"
df_trades.to_csv(out_csv, index=False)
print(f"\n→ Trades saved: {out_csv}")
