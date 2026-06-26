"""Найти чистые примеры работы магнитуды на BTC (DAILY) для отрисовки на TradingView.

Сигнал (каузально): atr-перцентиль (rolling 200) на close дневной свечи -> прогноз режима.
Исход: forward range за следующие H дней. Чистые примеры:
  экспансия = atr_pctile>=0.68 И forward range в топ-трети; тихо = atr_pctile<=0.32 И в нижней трети.
Окно: загружаемое на TV (Nov 2025+). Печатает unix-таймстемпы/цены для draw_shape.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "ta_laws"))
import geometry as G

H = 2  # дня вперёд (~как 4×12h в модели)
df = pd.read_csv(ROOT / "data" / "BTCUSDT_1d.csv")
df.columns = [c.lower() for c in df.columns]
tcol = "open_time" if "open_time" in df.columns else df.columns[0]
df[tcol] = pd.to_datetime(df[tcol], utc=True)
df = df.sort_values(tcol).reset_index(drop=True)
C = df.close.values; Hi = df.high.values; Lo = df.low.values
atr = G.compute_atr(df[["high", "low", "close"]])
atr_pct = atr / C * 100
pctile = pd.Series(atr_pct).rolling(200, min_periods=60).apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
n = len(df)
fwd = np.full(n, np.nan)
for i in range(n - H - 1):
    fwd[i] = (Hi[i + 1:i + 1 + H].max() - Lo[i + 1:i + 1 + H].min()) / C[i] * 100
ts = df[tcol].values
fr_lo, fr_hi = np.nanquantile(fwd, [1 / 3, 2 / 3])
print(f"[data] {n} дн.баров, последний {pd.Timestamp(ts[-1]).date()}, fwd_range трети {fr_lo:.1f}/{fr_hi:.1f}%")

recent = pd.Timestamp("2025-11-15", tz="UTC").value
exp, quiet = [], []
for i in range(60, n - H - 1):
    if ts[i].astype("datetime64[ns]").astype(np.int64) < recent:
        continue
    if not (np.isfinite(pctile[i]) and np.isfinite(fwd[i])):
        continue
    rec = {"i": i, "open": int(pd.Timestamp(ts[i]).timestamp()),
           "close_t": int((pd.Timestamp(ts[i]) + pd.Timedelta(days=1)).timestamp()),
           "end_t": int((pd.Timestamp(ts[i]) + pd.Timedelta(days=H + 1)).timestamp()),
           "C": round(float(C[i]), 1),
           "fhi": round(float(Hi[i + 1:i + 1 + H].max()), 1),
           "flo": round(float(Lo[i + 1:i + 1 + H].min()), 1),
           "fwd": round(float(fwd[i]), 1), "pctile": round(float(pctile[i]), 2)}
    if pctile[i] >= 0.68 and fwd[i] >= fr_hi:
        exp.append(rec)
    elif pctile[i] <= 0.32 and fwd[i] <= fr_lo:
        quiet.append(rec)


def spaced(cands, k, gap=6):
    out = []
    for c in cands:
        if all(abs(c["i"] - o["i"]) >= gap for o in out):
            out.append(c)
        if len(out) >= k:
            break
    return out


E = spaced(exp, 3); Q = spaced(quiet, 3)
print("\nЭКСПАНСИЯ (прогноз: большой ход):")
for c in E:
    print(c)
print("\nТИХО (прогноз: малый ход):")
for c in Q:
    print(c)
allt = [c["open"] for c in E + Q]
if allt:
    print(f"\nVISIBLE_RANGE from={min(allt)-8*86400} to={max(allt)+10*86400}")
