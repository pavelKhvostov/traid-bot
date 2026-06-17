"""Запуск live-nowcaster (etap_212) на ПОСЛЕДНЕМ дне данных (≈сегодня)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent.parent))
import etap_212_live_nowcaster as N
from data_manager import load_df

h1 = load_df("BTCUSDT", "1h")
if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
h1 = h1.sort_index()
R = N.build_rows(h1)
models = N.fit_per_hour(R[R["day"] < N.CUTOFF])

days = h1.index.normalize().unique()
last = days[-1]
bars = h1[h1.index.normalize() == last]
o = bars["open"].iloc[0]; cl = bars["close"].iloc[-1]
decisions, flips = N.nowcast_day(bars, models)

print("="*60)
print(f"LIVE NOWCASTER — {pd.Timestamp(last).date()}  ({len(bars)} закрытых 1h-баров)")
print(f"open {o:,.0f} → последний close {cl:,.0f}  ({(cl/o-1)*100:+.2f}%)")
print("="*60)
print(f"{'час':>4} {'UTC':>6} {'P(up)':>6} {'P_сглаж':>8} {'call':>6}")
for k, p, sm, call in decisions:
    t = bars.index[k].strftime("%H:%M")
    print(f"{k:>4} {t:>6} {p:>6.2f} {sm:>8.2f} {call:>6}")
print("-"*60)
last_call = decisions[-1][3]; last_sm = decisions[-1][2]
print(f"СЕЙЧАС: call={last_call} | P_сглаж={last_sm:.2f} | смен мнения за день: {flips}")
print(f"(день ещё {'идёт' if len(bars) < 24 else 'закрыт'}; это СОСТОЯНИЕ, не прогноз)")
