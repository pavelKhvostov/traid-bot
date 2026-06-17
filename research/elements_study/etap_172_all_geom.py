"""Dump ALL Bulkowski signals (full history) WITH geometry — for etap_208 fusion.
Reuses etap_172 detectors + bounds-safe swing patch. Output:
  output/etap_172_all_signals_geom.csv
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("etap172", HERE / "etap_172_bulkowski_patterns.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def _confirmed_swings_safe(highs, lows, start, end, n=2):
    sh, sl = [], []
    for j in range(max(start, n), min(end - n + 1, len(highs) - n)):
        hh = highs[j]
        if all(hh > highs[j - k] for k in range(1, n + 1)) and \
           all(hh > highs[j + k] for k in range(1, n + 1)):
            sh.append((j, hh))
        ll = lows[j]
        if all(ll < lows[j - k] for k in range(1, n + 1)) and \
           all(ll < lows[j + k] for k in range(1, n + 1)):
            sl.append((j, ll))
    return sh, sl


m.confirmed_swings = _confirmed_swings_safe

print("Loading BTC 1h -> 12h (full history) ...")
df1h = m.load_df("BTCUSDT", "1h")
df12 = m.compose_from_base(df1h, "12h").reset_index()
if "time" not in df12.columns:
    df12 = df12.rename(columns={df12.columns[0]: "time"})
print(f"  12h bars: {len(df12)}  {df12['time'].iloc[0]} -> {df12['time'].iloc[-1]}")

sigs = []
for i in range(m.LOOKBACK + m.SWING_N + 2, len(df12)):
    for det in m.DETECTORS:
        s = det(df12, i)
        if s is not None:
            s = dict(s); s["time"] = df12["time"].iloc[i]
            sigs.append(s)

out = pd.DataFrame(sigs)
out_path = HERE / "output" / "etap_172_all_signals_geom.csv"
out.to_csv(out_path, index=False)
print(f"  total signals: {len(out)}")
print(f"  by year:\n{out.assign(y=pd.to_datetime(out['time']).dt.year).groupby('y').size().to_string()}")
print(f"Saved: {out_path}")
