"""EVoT (ASVK ViC maxV) только в пределах паттерна (C1.open → C5.close).

Для каждого примера: считаем maxV среди 1m свечей паттерна, выводим направление,
значение и положение относительно entry/block/POI.
"""
from __future__ import annotations

import csv
import pathlib
from datetime import datetime, timedelta, timezone

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))


def load_range(start_utc, end_utc):
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            if t < start_utc: continue
            if t >= end_utc: break
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def compute_maxv(window):
    """Возвращает (direction, maxV_close, max_vol, time, opposite_max_vol)."""
    bull = [b for b in window if b[4] > b[1]]
    bear = [b for b in window if b[4] < b[1]]
    max_bull = max(bull, key=lambda x: x[5]) if bull else None
    max_bear = max(bear, key=lambda x: x[5]) if bear else None
    bv = max_bull[5] if max_bull else 0
    sv = max_bear[5] if max_bear else 0
    if bv > sv:
        return "BULL", max_bull[4], bv, max_bull[0], sv
    if sv > bv:
        return "BEAR", max_bear[4], sv, max_bear[0], bv
    return "NONE", None, 0, None, 0


def analyze_pattern(name, side, c1_utc, c5_close_utc, pattern_low, pattern_high, block, entry):
    window = load_range(c1_utc, c5_close_utc)
    direction, mv, max_vol, mv_time, opp_vol = compute_maxv(window)

    print(f"\n{'='*70}\n{name} ({side.upper()})\n{'='*70}")
    print(f"Окно паттерна: {c1_utc.astimezone(MSK).strftime('%Y-%m-%d %H:%M')} → "
          f"{c5_close_utc.astimezone(MSK).strftime('%H:%M')} MSK  ({len(window)} 1m)")

    bull_n = sum(1 for b in window if b[4] > b[1])
    bear_n = sum(1 for b in window if b[4] < b[1])
    print(f"Bull 1m: {bull_n},  Bear 1m: {bear_n}")
    print(f"Max bull vol: ", end="")
    if bull_n:
        mb = max((b for b in window if b[4] > b[1]), key=lambda x: x[5])
        print(f"{mb[5]:.2f}  close={mb[4]:.2f}  time={mb[0].astimezone(MSK).strftime('%H:%M')}")
    print(f"Max bear vol: ", end="")
    if bear_n:
        mbb = max((b for b in window if b[4] < b[1]), key=lambda x: x[5])
        print(f"{mbb[5]:.2f}  close={mbb[4]:.2f}  time={mbb[0].astimezone(MSK).strftime('%H:%M')}")

    print(f"\n→ EVoT direction: {direction}")
    print(f"  maxV (close) = {mv:.2f}" if mv else "  no data")
    print(f"  Время:        {mv_time.astimezone(MSK).strftime('%Y-%m-%d %H:%M')} MSK" if mv_time else "")

    if mv:
        delta = mv - entry
        r_unit = entry - pattern_low if side == "long" else pattern_high - entry
        print(f"\n  Entry:        {entry:.2f}")
        print(f"  maxV − entry: {delta:+.2f} ({delta/entry*100:+.3f}%)")
        print(f"  R_unit:       {r_unit:.2f}")
        print(f"  Δ в R-unit:   {delta / r_unit:+.3f}R")

        if mv < pattern_low: pos = "ПОД pattern_low"
        elif mv < block[0]: pos = "между pattern_low и block.bottom"
        elif mv <= block[1]: pos = "ВНУТРИ block"
        elif mv < entry: pos = "выше block, но ниже entry"
        elif mv > entry and mv <= pattern_high: pos = "выше entry"
        else: pos = "выше pattern"
        print(f"  → Position: {pos}")


# 2026-05-19 LONG (WIN)
analyze_pattern(
    "2026-05-19 LONG (WIN)",
    side="long",
    c1_utc=datetime(2026, 5, 19, 13, 0, tzinfo=timezone.utc),
    c5_close_utc=datetime(2026, 5, 19, 18, 0, tzinfo=timezone.utc),
    pattern_low=76144.71, pattern_high=77048.72,
    block=(76596.00, 76675.76),
    entry=76635.88,
)

# 2026-05-23 LONG (LOSS)
analyze_pattern(
    "2026-05-23 LONG (LOSS)",
    side="long",
    c1_utc=datetime(2026, 5, 22, 23, 0, tzinfo=timezone.utc),
    c5_close_utc=datetime(2026, 5, 23, 4, 0, tzinfo=timezone.utc),
    pattern_low=75220.00, pattern_high=75881.18,
    block=(75489.84, 75500.00),
    entry=75494.92,
)
