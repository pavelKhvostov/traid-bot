"""Обзор зон интереса на BTC D с 2026-04-04 по сегодня по всем 11 элементам smc-lib."""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle, intervals_overlap
from elements.ob.code import detect_ob
from elements.block_orders.code import detect_block_orders
from elements.ob_liq.code import detect_ob_liq
from elements.rb.code import detect_rb
from elements.fvg.code import detect_fvg
from elements.i_fvg.code import detect_i_fvg
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from elements.i_rdrb_fvg.code import detect_i_rdrb_fvg
from elements.marubozu.code import detect_marubozu
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
TF_MIN = 1440  # D


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def aggregate(d, tf_min):
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0
    for ts, oo, hh, ll, cc in d:
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c))
            cb = b; o, h, l, c = oo, hh, ll, cc
        else:
            h = max(h, hh); l = min(l, ll); c = cc
    if cb is not None: out.append((cb, o, h, l, c))
    return out


def to_candle(row):
    ts, o, h, l, c = row
    return Candle(open=o, high=h, low=l, close=c, open_time=ts)


def datestr(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d')


print("Loading 1m...")
data = load_1m()
d_all = aggregate(data, TF_MIN)
# Skip unclosed last D
last_1m_ts = data[-1][0]
if last_1m_ts < d_all[-1][0] + TF_MIN * 60_000 - 60_000:
    d_all = d_all[:-1]

# Range: 2026-04-04 to today, плюс padding 6 баров слева для окон
range_start_ms = int(datetime(2026, 4, 4, tzinfo=timezone.utc).timestamp() * 1000)
# 2026-04-04 00:00 MSK = 2026-04-03 21:00 UTC. Будем фильтровать по дате открытия в MSK
# Простой подход: бар "в окне" если его open_time (MSK дата) >= 2026-04-04

def in_window(ts):
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(MSK).date() >= datetime(2026, 4, 4).date()


# Полный массив с padding (берём всё)
all_idx_in_window = [i for i, r in enumerate(d_all) if in_window(r[0])]
first_window_idx = min(all_idx_in_window)
last_window_idx = max(all_idx_in_window)

candles_all = [to_candle(r) for r in d_all]
print(f"Total D candles: {len(d_all)}. Окно с 2026-04-04: индексы [{first_window_idx}, {last_window_idx}] ({last_window_idx - first_window_idx + 1} баров)")

# Helper: считать что центр в окне
def center_in_window(idx):
    return first_window_idx <= idx <= last_window_idx


# ===== Детекторы =====

results: dict[str, list] = {}

# 1. OB — 2-candle (cur в окне)
ob_hits = []
for i in range(1, len(candles_all)):
    if not center_in_window(i):
        continue
    r = detect_ob(candles_all[i-1], candles_all[i])
    if r:
        ob_hits.append((d_all[i][0], r))
results['ob'] = ob_hits

# 2. block_orders — пробуем все слайсы [i-k, i] с k от 3 до 6 (preceding + 1-5 candles)
bo_hits = []
seen = set()
for end in range(2, len(candles_all)):
    if not center_in_window(end):
        continue
    for start in range(max(0, end - 6), end - 1):
        slice_ = candles_all[start:end + 1]
        r = detect_block_orders(slice_)
        if r:
            # Дедуп по (start_ts, n_initial, n_counter)
            key = (d_all[start + 1][0], r.n_initial, r.n_counter)
            if key in seen:
                continue
            seen.add(key)
            bo_hits.append((d_all[end][0], r, start))
results['block_orders'] = bo_hits

# 3. ob_liq — 5-candle (центр = prev на индексе i, нужны i-2..i+2)
ob_liq_hits = []
for i in range(2, len(candles_all) - 2):
    if not center_in_window(i):
        continue
    r = detect_ob_liq(candles_all[i-2], candles_all[i-1], candles_all[i], candles_all[i+1], candles_all[i+2])
    if r:
        ob_liq_hits.append((d_all[i][0], r))
results['ob_liq'] = ob_liq_hits

# 4. rb — 1-candle
rb_hits = []
for i in range(len(candles_all)):
    if not center_in_window(i):
        continue
    r = detect_rb(candles_all[i])
    if r:
        rb_hits.append((d_all[i][0], r))
results['rb'] = rb_hits

# 5. fvg — 3-candle (c2 центр)
fvg_hits = []
for i in range(1, len(candles_all) - 1):
    if not center_in_window(i):
        continue
    r = detect_fvg(candles_all[i-1], candles_all[i], candles_all[i+1])
    if r:
        fvg_hits.append((d_all[i+1][0], r, i-1, i+1))
results['fvg'] = fvg_hits

# 6. rdrb — 3-candle (C2 центр)
rdrb_hits = []
for i in range(1, len(candles_all) - 1):
    if not center_in_window(i):
        continue
    r = detect_rdrb(candles_all[i-1], candles_all[i], candles_all[i+1])
    if r:
        rdrb_hits.append((d_all[i+1][0], r))
results['rdrb'] = rdrb_hits

# 7. i_rdrb — 4-candle (C4 = i+2)
i_rdrb_hits = []
for i in range(1, len(candles_all) - 2):
    if not center_in_window(i + 2):
        continue
    r = detect_i_rdrb(candles_all[i-1], candles_all[i], candles_all[i+1], candles_all[i+2])
    if r:
        i_rdrb_hits.append((d_all[i+2][0], r))
results['i_rdrb'] = i_rdrb_hits

# 8. i_rdrb_fvg — 5-candle
i_rdrb_fvg_hits = []
for i in range(1, len(candles_all) - 3):
    if not center_in_window(i + 3):
        continue
    r = detect_i_rdrb_fvg(candles_all[i-1], candles_all[i], candles_all[i+1], candles_all[i+2], candles_all[i+3])
    if r:
        i_rdrb_fvg_hits.append((d_all[i+3][0], r))
results['i_rdrb_fvg'] = i_rdrb_fvg_hits

# 9. marubozu — 1-candle
marubozu_hits = []
for i in range(len(candles_all)):
    if not center_in_window(i):
        continue
    r = detect_marubozu(candles_all[i])
    if r:
        marubozu_hits.append((d_all[i][0], r))
results['marubozu'] = marubozu_hits

# 10. fractal — 5-candle N=2
fractal_hits = []
for i in range(2, len(candles_all) - 2):
    if not center_in_window(i):
        continue
    r = detect_fractal(candles_all[i-2:i+3], n=2)
    if r:
        fractal_hits.append((d_all[i][0], r))
results['fractal'] = fractal_hits

# 11. i_fvg — composite (FVG-A → FVG-B противоположного направления)
# Сканируем все пары FVG: для каждой A проверяем все B позже A.c3, B противоположного направления.
# Берём первый touch — первая B в хронологии чьи свечи касаются A.zone.
all_fvgs_idx = []  # (idx_of_c3, fvg)
for i in range(1, len(candles_all) - 1):
    r = detect_fvg(candles_all[i-1], candles_all[i], candles_all[i+1])
    if r:
        all_fvgs_idx.append((i + 1, r, i - 1, i + 1))  # (c3_idx, fvg, c1_idx, c3_idx)

i_fvg_hits = []
for a_c3_idx, a, a_c1_idx, a_c3_idx2 in all_fvgs_idx:
    for b_c3_idx, b, b_c1_idx, b_c3_idx2 in all_fvgs_idx:
        if b.direction == a.direction:
            continue
        if b_c1_idx <= a_c3_idx:  # B должна быть позже A
            continue
        if not center_in_window(b_c3_idx):
            continue
        between = candles_all[a_c3_idx + 1:b_c1_idx]
        result = detect_i_fvg(
            candles_all[a_c1_idx], candles_all[a_c1_idx + 1], candles_all[a_c3_idx],
            between,
            candles_all[b_c1_idx], candles_all[b_c1_idx + 1], candles_all[b_c3_idx],
        )
        if result:
            i_fvg_hits.append((d_all[b_c3_idx][0], result, a_c1_idx, b_c1_idx))
            break  # первая B для этой A
results['i_fvg'] = i_fvg_hits


# ===== Print summary =====

print(f"\n{'='*82}")
print(f"  ОБЗОР ЗОН ИНТЕРЕСА на BTC D с 2026-04-04 по {datestr(d_all[last_window_idx][0])}")
print(f"  Окно: {last_window_idx - first_window_idx + 1} D-баров")
print(f"{'='*82}\n")

order = ['ob', 'block_orders', 'ob_liq', 'rb', 'fvg', 'i_fvg', 'rdrb', 'i_rdrb', 'i_rdrb_fvg', 'marubozu', 'fractal']
for name in order:
    hits = results[name]
    print(f"### {name.upper():<14}  {len(hits):>3} зон")
    if not hits:
        print(f"    —\n")
        continue
    for hit in hits:
        ts = hit[0]; r = hit[1]
        date = datestr(ts)
        if name == 'ob':
            print(f"    {date}  {r.direction.upper():<5}  zone {r.zone[0]:.0f}–{r.zone[1]:.0f}  (breaker {r.breaker_block[0]:.0f}–{r.breaker_block[1]:.0f})")
        elif name == 'block_orders':
            print(f"    {date}  {r.direction.upper():<5}  N₁={r.n_initial} N₂={r.n_counter}  zone {r.zone[0]:.0f}–{r.zone[1]:.0f}")
        elif name == 'ob_liq':
            print(f"    {date}  {r.direction.upper():<5}  zone {r.zone[0]:.0f}–{r.zone[1]:.0f}  liq {r.liq_zone[0]:.0f}–{r.liq_zone[1]:.0f}")
        elif name == 'rb':
            zone = r.zone
            print(f"    {date}  {r.direction.upper():<7}  zone {zone[0]:.0f}–{zone[1]:.0f}")
        elif name == 'fvg':
            print(f"    {date}  {r.direction.upper():<5}  zone {r.zone[0]:.0f}–{r.zone[1]:.0f}")
        elif name == 'i_fvg':
            print(f"    {date}  {r.direction.upper():<5}  overlap {r.overlap[0]:.0f}–{r.overlap[1]:.0f}  (A {r.a.direction} / B {r.b.direction})")
        elif name == 'rdrb':
            print(f"    {date}  {r.direction.upper():<5}  V={r.variant}  POI {r.poi[0]:.0f}–{r.poi[1]:.0f}  block {r.block[0]:.0f}–{r.block[1]:.0f}")
        elif name == 'i_rdrb':
            print(f"    {date}  {r.direction.upper():<5}  V={r.rdrb.variant}  POI {r.rdrb.poi[0]:.0f}–{r.rdrb.poi[1]:.0f}")
        elif name == 'i_rdrb_fvg':
            print(f"    {date}  {r.direction.upper():<5}  RDRB-POI {r.irdrb.rdrb.poi[0]:.0f}–{r.irdrb.rdrb.poi[1]:.0f}  + FVG {r.fvg.zone[0]:.0f}–{r.fvg.zone[1]:.0f}")
        elif name == 'marubozu':
            print(f"    {date}  {r.direction.upper():<5}  zone (body) {r.zone[0]:.0f}–{r.zone[1]:.0f}")
        elif name == 'fractal':
            mark = "▼ FH" if r.direction == "high" else "▲ FL"
            print(f"    {date}  {mark}  level {r.level:.0f}")
    print()
