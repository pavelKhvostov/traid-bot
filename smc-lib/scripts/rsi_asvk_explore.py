"""RSI ASVK — explorer на свежих BTC 1h данных.

Цель: понять, как ведёт себя индикатор. Распечатать последние ~7 дней
последовательность: ts (MSK) | close | rsi | ema_3 | above | below | NWE_out | zone
+ summary распределения зон + примеры reversal-кандидатов.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from indicators.rsi_asvk import adjusted_rsi, asvk_zone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_HOUR = 3600_000


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


print("Loading data...")
data = load_1m()
bars_1h = aggregate(data, 60)
closes = [b[4] for b in bars_1h]
opens_ts = [b[0] for b in bars_1h]
print(f"  {len(bars_1h):,} 1h bars total")

print("Computing ASVK RSI on FULL series (need ≥200 bars history for adaptive)...")
res = adjusted_rsi(closes, period=14)
print("  done")

# Tail — последние 168 баров (7 дней)
N_TAIL = 168
ema3 = res["ema_3"]
rsi = res["rsi"]
above = res["above"]
below = res["below"]
nwe_out = res["nwe_out"]
nwe_upper = res["nwe_upper"]
nwe_lower = res["nwe_lower"]


def fmt_msk(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d %H:%M')


print(f"\n{'='*108}")
print(f" Last {N_TAIL} 1h bars (BTC) — состояние индикатора")
print(f"{'='*108}")
print(f"{'idx':>5} {'time MSK':>11}  {'close':>9}  {'rsi':>6}  {'ema_3':>7}  "
      f"{'above':>6}  {'below':>5}  {'NWE':>7}  {'NWE±':>10}  zone")
print("-" * 108)

zone_counts = {}
zone_seq = []
for i in range(len(bars_1h) - N_TAIL, len(bars_1h)):
    if i < 0: continue
    z = asvk_zone(ema3[i], above[i], below[i], nwe_upper[i], nwe_lower[i])
    zone_counts[z] = zone_counts.get(z, 0) + 1
    zone_seq.append((i, z))

# Распечатаю каждый 4-й бар + все смены зоны
prev_zone = None
for i in range(len(bars_1h) - N_TAIL, len(bars_1h)):
    if i < 0: continue
    z = asvk_zone(ema3[i], above[i], below[i], nwe_upper[i], nwe_lower[i])
    show = (z != prev_zone) or (i % 4 == 0)
    if not show:
        prev_zone = z
        continue
    nwe_str = (f"{nwe_lower[i]:.1f}..{nwe_upper[i]:.1f}"
               if nwe_lower[i] is not None and nwe_upper[i] is not None else "  —  ")
    marker = " <-- ZONE CHANGE" if z != prev_zone and prev_zone is not None else ""
    print(f"{i:>5} {fmt_msk(opens_ts[i]):>11}  "
          f"{closes[i]:>9.1f}  "
          f"{(rsi[i] or 0):>5.1f}  "
          f"{(ema3[i] or 0):>6.1f}  "
          f"{(above[i] or 0):>5.1f}  "
          f"{(below[i] or 0):>4.1f}  "
          f"{(nwe_out[i] or 0):>6.1f}  "
          f"{nwe_str:>10}  "
          f"{z}{marker}")
    prev_zone = z

print(f"\n--- Zone distribution за {N_TAIL}h ---")
for z in ("red", "yellow_ob", "neutral", "yellow_os", "green"):
    pct = zone_counts.get(z, 0) / N_TAIL * 100
    print(f"  {z:<12} {zone_counts.get(z, 0):>3}  ({pct:>5.1f}%)")

# Reversal candidates — переход из red в yellow_ob (bearish exit) или из green в yellow_os (bullish exit)
print("\n--- Reversal candidates за период (zone transitions из extreme в neutralизация) ---")
last_i = None
last_z = None
extreme_in_streak = None
for i, z in zone_seq:
    if z in ("red", "green"):
        extreme_in_streak = z
    elif extreme_in_streak is not None:
        # переход из red → yellow_ob/neutral = bearish reversal candidate
        # green → yellow_os/neutral = bullish reversal candidate
        side = "BEARISH (top reversal)" if extreme_in_streak == "red" else "BULLISH (bottom reversal)"
        print(f"  {fmt_msk(opens_ts[i])}  close={closes[i]:>9.1f}  "
              f"exit from {extreme_in_streak} → {z}  ← {side}")
        extreme_in_streak = None

# Текущее состояние
i = len(bars_1h) - 1
z = asvk_zone(ema3[i], above[i], below[i], nwe_upper[i], nwe_lower[i])
print(f"\n=== CURRENT BAR ({fmt_msk(opens_ts[i])} MSK, close={closes[i]:.1f}) ===")
print(f"  RSI(14):  {rsi[i]:.2f}" if rsi[i] is not None else "  RSI: n/a")
print(f"  ema_3:    {ema3[i]:.2f}" if ema3[i] is not None else "  ema_3: n/a")
print(f"  above:    {above[i]:.2f}" if above[i] is not None else "  above: n/a")
print(f"  below:    {below[i]:.2f}" if below[i] is not None else "  below: n/a")
print(f"  NWE_out:  {nwe_out[i]:.2f}" if nwe_out[i] is not None else "  NWE: n/a")
if nwe_lower[i] is not None and nwe_upper[i] is not None:
    print(f"  NWE band: [{nwe_lower[i]:.2f}, {nwe_upper[i]:.2f}]")
print(f"  ZONE:     {z}")

interp = {
    "red": "🔴 EXTENSION UP — extreme импульс вверх; ждать exit в yellow_ob → bear-reversal candidate.",
    "yellow_ob": "🟡 OVERBOUGHT zone — дотянулись до OB-band, но не пробили above. Зона предупреждения.",
    "neutral": "⚪ NEUTRAL — внутри bands. Нет сильного импульса в обе стороны.",
    "yellow_os": "🟡 OVERSOLD zone — дотянулись до OS-band, но не пробили below. Зона предупреждения.",
    "green": "🟢 EXTENSION DOWN — extreme импульс вниз; ждать exit в yellow_os → bull-reversal candidate.",
}
print(f"\n  Интерпретация: {interp[z]}")
