"""Непрерывная лента режима магнитуды для окна на TV — показать, что метка есть на КАЖДОМ баре.

Каждому дневному бару: atr-перцентиль -> режим (exp>=0.66 / quiet<=0.33 / mid). Сливает смежные бары
одного режима в участки, печатает (start_t, end_t) для фон-прямоугольников. Только exp/quiet (mid не красим).
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

FROM, TO = 1762560000, 1776556800
df = pd.read_csv(ROOT / "data" / "BTCUSDT_1d.csv")
df.columns = [c.lower() for c in df.columns]
tcol = "open_time" if "open_time" in df.columns else df.columns[0]
df[tcol] = pd.to_datetime(df[tcol], utc=True)
df = df.sort_values(tcol).reset_index(drop=True)
C = df.close.values
atr = G.compute_atr(df[["high", "low", "close"]])
atr_pct = atr / C * 100
pctile = pd.Series(atr_pct).rolling(200, min_periods=60).apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
ts = df[tcol].values
sec = ts.astype("datetime64[s]").astype(np.int64)


def cls(p):
    if not np.isfinite(p):
        return "na"
    return "exp" if p >= 0.66 else ("quiet" if p <= 0.33 else "mid")


mask = (sec >= FROM) & (sec <= TO)
idx = np.where(mask)[0]
runs = []
i0 = idx[0]
cur = cls(pctile[i0])
start = i0
n_exp = n_quiet = n_mid = 0
for k in idx:
    c = cls(pctile[k])
    if c == "exp":
        n_exp += 1
    elif c == "quiet":
        n_quiet += 1
    elif c == "mid":
        n_mid += 1
    if c != cur:
        if cur in ("exp", "quiet"):
            runs.append((cur, int(sec[start]), int(sec[k - 1] + 86400)))
        cur = c; start = k
if cur in ("exp", "quiet"):
    runs.append((cur, int(sec[start]), int(sec[idx[-1]] + 86400)))

tot = n_exp + n_quiet + n_mid
print(f"баров в окне: {tot}  exp={n_exp} ({n_exp/tot*100:.0f}%)  quiet={n_quiet} ({n_quiet/tot*100:.0f}%)  mid={n_mid} ({n_mid/tot*100:.0f}%)")
print(f"участков (exp/quiet): {len(runs)}")
for r in runs:
    print(r)
