"""Проверка: RDRB block на 2026-05-01 05:00-07:00 vs reaction 2026-05-19.

User says: "2026-05-01 с 05-00 по 07-00 образовался RDRB block. Посмотри как цена
на него реагировала 2026-05-19. RDRB block 2026-05-19 с ним в одной зоне."

Time in user's display = UTC+3 (MSK). RDRB на 1h = 3 свечи C1-C2-C3.
05:00-07:00 MSK = 02:00-04:00 UTC (3 свечи: 02:00, 03:00, 04:00 UTC open).

Сделаем заодно проверку 05:00-07:00 UTC, чтобы не промахнуться часовым поясом.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.rdrb.code import detect_rdrb

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc, _ in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append(Candle(open=o, high=h, low=l, close=c, open_time=cb))
    return out


print("Loading 1m..."); data = load_1m()
candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]


def fmt_msk(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=MSK).strftime("%Y-%m-%d %H:%M MSK")


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def find_candle_by_open_time(cs, target_ms):
    for i, c in enumerate(cs):
        if c.open_time == target_ms: return i
    return None


# === Вариант A: 05:00-07:00 MSK = 02:00-04:00 UTC ===
print("\n" + "=" * 80)
print("ВАРИАНТ A: 2026-05-01 05:00→07:00 MSK (= 02:00→04:00 UTC)")
print("=" * 80)

t_a_c1_utc = datetime(2026, 5, 1, 2, 0, tzinfo=timezone.utc)
t_a_c1_ms = int(t_a_c1_utc.timestamp() * 1000)
i_a = find_candle_by_open_time(candles_1h, t_a_c1_ms)
if i_a is None:
    print(f"  Не нашёл 1h свечу с open_time {t_a_c1_utc}")
else:
    c1, c2, c3 = candles_1h[i_a], candles_1h[i_a + 1], candles_1h[i_a + 2]
    for n, c in [("C1", c1), ("C2", c2), ("C3", c3)]:
        print(f"  {n} ({fmt_msk(c.open_time)}): O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} C={c.close:.2f}  body={'bull' if c.is_bull else 'bear' if c.is_bear else 'doji'}")
    r_a = detect_rdrb(c1, c2, c3)
    if r_a is None:
        print("  → НЕ RDRB")
    else:
        print(f"\n  ✓ RDRB detected: {r_a.direction.upper()} {r_a.variant}")
        print(f"     block: [{r_a.block[0]:.2f}, {r_a.block[1]:.2f}] (h={r_a.block[1]-r_a.block[0]:.2f})")
        print(f"     poi:   [{r_a.poi[0]:.2f}, {r_a.poi[1]:.2f}]")
        print(f"     liq:   {r_a.liq if r_a.liq is None else f'[{r_a.liq[0]:.2f}, {r_a.liq[1]:.2f}]'}")
        rdrb_a = r_a

# === Вариант B: 05:00-07:00 UTC ===
print("\n" + "=" * 80)
print("ВАРИАНТ B: 2026-05-01 05:00→07:00 UTC")
print("=" * 80)

t_b_c1_utc = datetime(2026, 5, 1, 5, 0, tzinfo=timezone.utc)
t_b_c1_ms = int(t_b_c1_utc.timestamp() * 1000)
i_b = find_candle_by_open_time(candles_1h, t_b_c1_ms)
if i_b is None:
    print(f"  Не нашёл 1h свечу с open_time {t_b_c1_utc}")
else:
    c1, c2, c3 = candles_1h[i_b], candles_1h[i_b + 1], candles_1h[i_b + 2]
    for n, c in [("C1", c1), ("C2", c2), ("C3", c3)]:
        print(f"  {n} ({fmt_msk(c.open_time)}): O={c.open:.2f} H={c.high:.2f} L={c.low:.2f} C={c.close:.2f}  body={'bull' if c.is_bull else 'bear' if c.is_bear else 'doji'}")
    r_b = detect_rdrb(c1, c2, c3)
    if r_b is None:
        print("  → НЕ RDRB")
    else:
        print(f"\n  ✓ RDRB detected: {r_b.direction.upper()} {r_b.variant}")
        print(f"     block: [{r_b.block[0]:.2f}, {r_b.block[1]:.2f}] (h={r_b.block[1]-r_b.block[0]:.2f})")
        print(f"     poi:   [{r_b.poi[0]:.2f}, {r_b.poi[1]:.2f}]")
        print(f"     liq:   {r_b.liq if r_b.liq is None else f'[{r_b.liq[0]:.2f}, {r_b.liq[1]:.2f}]'}")

# Pick the version that detected an RDRB
detected = None
if i_a is not None and (r_a := detect_rdrb(candles_1h[i_a], candles_1h[i_a+1], candles_1h[i_a+2])) is not None:
    detected = ("A (02-04 UTC = 05-07 MSK)", r_a, candles_1h[i_a+2].open_time + 3600_000)
elif i_b is not None and (r_b := detect_rdrb(candles_1h[i_b], candles_1h[i_b+1], candles_1h[i_b+2])) is not None:
    detected = ("B (05-07 UTC = 08-10 MSK)", r_b, candles_1h[i_b+2].open_time + 3600_000)

if detected is None:
    print("\n❌ В обоих вариантах RDRB не обнаружен.")
    sys.exit(0)

label, rdrb_5_01, c3_close_ms = detected
bb, bt = rdrb_5_01.block
print(f"\n{'=' * 80}")
print(f"BERU вариант: {label}, BLOCK = [{bb:.2f}, {bt:.2f}]")
print(f"{'=' * 80}")

# === Реакция цены 2026-05-19 ===
print("\nРЕАКЦИЯ ЦЕНЫ 2026-05-19 (вся торговая сессия UTC):")
d_19_start = int(datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
d_19_end = int(datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

# Find when price first touched the block on/after 05-01 C3 close
print(f"\n  Поиск первого касания block [{bb:.2f}, {bt:.2f}] после C3 close ({fmt_msk(c3_close_ms)}):")
sk = idx_at(c3_close_ms)
first_touch_ms = None
for k in range(sk, len(data)):
    ts, _, hh, ll, _, _ = data[k]
    if ll <= bt and hh >= bb:
        first_touch_ms = ts; break
if first_touch_ms is None:
    print("    Цена ни разу не коснулась block!")
else:
    print(f"    Первое касание: {fmt_msk(first_touch_ms)}")
    days_to_touch = (first_touch_ms - c3_close_ms) / (24*3600_000)
    print(f"    Прошло {days_to_touch:.1f} дней от формирования")

# Show 2026-05-19 OHLC and overlap with block
sk19 = idx_at(d_19_start); ek19 = idx_at(d_19_end)
day_hi = max(data[k][2] for k in range(sk19, ek19))
day_lo = min(data[k][3] for k in range(sk19, ek19))
print(f"\n  2026-05-19 диапазон: low={day_lo:.2f}, high={day_hi:.2f}")
overlap_lo = max(day_lo, bb); overlap_hi = min(day_hi, bt)
if overlap_hi > overlap_lo:
    print(f"  ✓ ПЕРЕСЕЧЕНИЕ с block: [{overlap_lo:.2f}, {overlap_hi:.2f}] (overlap_h={overlap_hi-overlap_lo:.2f})")
    # Сколько минут price был внутри block в течение 05-19
    mins_in_block = sum(1 for k in range(sk19, ek19) if data[k][3] <= bt and data[k][2] >= bb)
    print(f"  Минут внутри block за 05-19: {mins_in_block}")
else:
    print(f"  ❌ Цена 05-19 не пересекла block")

# Reaction after first touch on 05-19: find first 4h/1d move from block
# Найти на 05-19 момент входа в block и реакцию (max move за 24h после)
for k in range(sk19, ek19):
    ts, _, hh, ll, _, _ = data[k]
    if ll <= bt and hh >= bb:
        touch_ts_19 = ts
        ek_after = min(k + 24*60, len(data))
        hi_after = max(data[j][2] for j in range(k, ek_after))
        lo_after = min(data[j][3] for j in range(k, ek_after))
        c_at_touch = data[k][4]
        print(f"\n  Первое касание 05-19: {fmt_msk(touch_ts_19)}, close@touch={c_at_touch:.2f}")
        print(f"  За 24h после: low={lo_after:.2f} ({(lo_after-c_at_touch)/c_at_touch*100:+.2f}%), high={hi_after:.2f} ({(hi_after-c_at_touch)/c_at_touch*100:+.2f}%)")
        break

# === RDRB block на 2026-05-19 (любой) ===
print(f"\n{'=' * 80}")
print("RDRB на 2026-05-19 (1h, перебираем все 3-candle окна за день):")
print(f"{'=' * 80}")
rdrbs_19 = []
# Iterate 1h candles whose c1 opens on 2026-05-19
for i in range(len(candles_1h) - 2):
    c1, c2, c3 = candles_1h[i:i+3]
    if c1.open_time < d_19_start: continue
    if c1.open_time >= d_19_end: break
    r = detect_rdrb(c1, c2, c3)
    if r is None: continue
    rdrbs_19.append((c1.open_time, r))

if not rdrbs_19:
    print("  RDRB на 1h 2026-05-19 не обнаружен.")
else:
    for c1_ts, r in rdrbs_19:
        bb19, bt19 = r.block
        overlap_lo = max(bb19, bb); overlap_hi = min(bt19, bt)
        print(f"\n  RDRB {r.direction.upper()} {r.variant}: C1 open = {fmt_msk(c1_ts)}")
        print(f"    block: [{bb19:.2f}, {bt19:.2f}] (h={bt19-bb19:.2f})")
        if overlap_hi > overlap_lo:
            print(f"    ✓ overlap с 05-01 block: [{overlap_lo:.2f}, {overlap_hi:.2f}] (h={overlap_hi-overlap_lo:.2f})")
        else:
            dist = bb - bt19 if bt19 < bb else bb19 - bt
            print(f"    ❌ нет overlap (расстояние ~ {dist:.2f})")
