"""Разметка зон интереса на BTCUSDT 12h по канону проекта (для TradingView MCP).

Берёт OHLCV 12h (с графика TV, переданы через /tmp/tv_bars.csv), считает зоны
по нашим знаниям: фракталы Williams (ликвидность), FVG (неэффективность),
OB (Order Block), RDRB, sweep/DOL (ICT). Выводит зоны рядом с текущей ценой
для нанесения на график.

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/tv_mark_zones.py
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
_sys.path.insert(0, str(_ROOT))

import json
import numpy as np
import pandas as pd

df = pd.read_csv("/tmp/tv_bars.csv")
df = df.sort_values("time").reset_index(drop=True)
O = df["open"].values; H = df["high"].values; L = df["low"].values; C = df["close"].values
V = df["volume"].values
n = len(df)
price = C[-1]
print(f"[zones] {n} баров 12h, текущая цена = {price:.0f}", flush=True)

zones = []  # каждая: dict(kind, dir, top, bottom, dist_pct, note)

def add(kind, direction, top, bottom, note):
    mid = (top + bottom) / 2
    dist = (mid / price - 1) * 100
    zones.append({"kind": kind, "dir": direction, "top": round(top, 1),
                  "bottom": round(bottom, 1), "dist_pct": round(dist, 1), "note": note})

N = 2  # Williams fractal
# 1) ФРАКТАЛЫ (ликвидность) — последние подтверждённые
for i in range(N, n - N - 1):
    is_fh = H[i] > max(H[i-N:i].max(), H[i+1:i+1+N].max())
    is_fl = L[i] < min(L[i-N:i].min(), L[i+1:i+1+N].min())
    if is_fh:
        add("FRACTAL_HIGH(liq)", "SHORT-DOL", H[i], H[i], f"BSL — ликвидность сверху, бар {i}")
    if is_fl:
        add("FRACTAL_LOW(liq)", "LONG-DOL", L[i], L[i], f"SSL — ликвидность снизу, бар {i}")

# 2) FVG (неэффективность) — КАНОН: 3-баровая группа (c1,c2,c3)=(i-1,i,i+1),
#    гэп между КРАЙНИМИ свечами c1 и c3, средняя c2 его не закрыла.
#    bullish: c1.high < c3.low → зона [c1.high, c3.low]
#    bearish: c1.low  > c3.high → зона [c3.high, c1.low]
for i in range(1, n - 1):
    c1h, c1l = H[i-1], L[i-1]   # c1 = i-1
    c3h, c3l = H[i+1], L[i+1]   # c3 = i+1
    # bullish FVG
    if c1h < c3l:
        gap_top, gap_bot = c3l, c1h
        # незакрыт, если после c3 цена не возвращалась внутрь гэпа целиком (low ниже gap_bot)
        filled = (L[i+2:] < gap_bot).any() if i+2 < n else False
        if not filled:
            add("FVG_bull", "LONG", gap_top, gap_bot, f"бычий гэп c1-c3 (бар {i-1}..{i+1}), незакрыт")
    # bearish FVG
    if c1l > c3h:
        gap_top, gap_bot = c1l, c3h
        filled = (H[i+2:] > gap_top).any() if i+2 < n else False
        if not filled:
            add("FVG_bear", "SHORT", gap_top, gap_bot, f"медвежий гэп c1-c3 (бар {i-1}..{i+1}), незакрыт")

# 3) OB (Order Block) — последние, незатронутые
for i in range(1, n):
    # bullish OB: prev красная, cur.close > prev.open
    if C[i-1] < O[i-1] and C[i] > O[i-1]:
        ob_top, ob_bot = O[i-1], min(L[i-1], L[i])
        mitigated = (L[i+1:] < ob_bot).any() if i+1 < n else False
        if not mitigated and ob_top < price:
            add("OB_bull", "LONG", ob_top, ob_bot, f"бычий OB бар {i}")
    # bearish OB: prev зелёная, cur.close < prev.open
    if C[i-1] > O[i-1] and C[i] < O[i-1]:
        ob_top, ob_bot = max(H[i-1], H[i]), O[i-1]
        mitigated = (H[i+1:] > ob_top).any() if i+1 < n else False
        if not mitigated and ob_bot > price:
            add("OB_bear", "SHORT", ob_top, ob_bot, f"медвежий OB бар {i}")

# структура: 30-барные HH/LL (зоны притяжения / DOL)
recent = 60
hh = H[-recent:].max(); ll = L[-recent:].min()
add("RANGE_HIGH(DOL)", "SHORT", hh, hh, f"максимум {recent} баров — цель ликвидности сверху")
add("RANGE_LOW(DOL)", "LONG", ll, ll, f"минимум {recent} баров — цель ликвидности снизу")

# отбираем БЛИЖАЙШИЕ зоны к цене (±15%), сортируем по близости
near = [z for z in zones if abs(z["dist_pct"]) <= 15]
near.sort(key=lambda z: abs(z["dist_pct"]))

# дедуп близких уровней (в пределах 0.4%)
seen = []
final = []
for z in near:
    mid = (z["top"] + z["bottom"]) / 2
    if any(abs(mid - s) / price < 0.004 and z["kind"][:3] == k[:3] for s, k in seen):
        continue
    seen.append((mid, z["kind"]))
    final.append(z)

print(f"\n=== ЗОНЫ ИНТЕРЕСА вокруг {price:.0f} (±15%, отсортированы по близости) ===", flush=True)
above = [z for z in final if z["dist_pct"] > 0][:8]
below = [z for z in final if z["dist_pct"] <= 0][:8]
print("\n--- НАД ценой (сопротивление / цели шорта / BSL) ---", flush=True)
for z in sorted(above, key=lambda z: -z["dist_pct"]):
    rng = f"{z['bottom']:.0f}-{z['top']:.0f}" if z['top'] != z['bottom'] else f"{z['top']:.0f}"
    print(f"  +{z['dist_pct']:.1f}%  {z['kind']:<18} {rng:<16} {z['note']}", flush=True)
print(f"\n  >>> ТЕКУЩАЯ ЦЕНА: {price:.0f} <<<", flush=True)
print("\n--- ПОД ценой (поддержка / цели лонга / SSL) ---", flush=True)
for z in sorted(below, key=lambda z: -z["dist_pct"]):
    rng = f"{z['bottom']:.0f}-{z['top']:.0f}" if z['top'] != z['bottom'] else f"{z['top']:.0f}"
    print(f"  {z['dist_pct']:.1f}%  {z['kind']:<18} {rng:<16} {z['note']}", flush=True)

# сохраняем для нанесения на TV
json.dump(final, open("/tmp/tv_zones.json", "w"), ensure_ascii=False, indent=1)
print(f"\n[saved] {len(final)} зон → /tmp/tv_zones.json", flush=True)
