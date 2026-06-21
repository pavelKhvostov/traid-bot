"""Проверка 2026-05-10 23:00 MSK 1h bar и его 1m развёртка."""
import csv, pathlib
from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))
UTC = timezone.utc
DATA = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

# 23:00 MSK 2026-05-10 = 20:00 UTC
target_msk_start = datetime(2026,5,10,23,0,tzinfo=MSK)
target_msk_end = target_msk_start + timedelta(hours=1)

ENTRY = 80893.94
SL = 80816.22
TP = 81442.81

rows1m = []
with DATA.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        if not t.tzinfo: t = t.replace(tzinfo=UTC)
        if target_msk_start <= t.astimezone(MSK) < target_msk_end:
            rows1m.append((t, float(r[1]),float(r[2]),float(r[3]),float(r[4])))

print(f"1m bars в час 23:00 MSK 2026-05-10: {len(rows1m)}")
print(f"Уровни: ENTRY={ENTRY}, SL={SL}, TP={TP}\n")

# часовой OHLC
if rows1m:
    h_o = rows1m[0][1]
    h_h = max(r[2] for r in rows1m)
    h_l = min(r[3] for r in rows1m)
    h_c = rows1m[-1][4]
    print(f"H1 OHLC: O={h_o}, H={h_h}, L={h_l}, C={h_c}\n")

# трассировка событий: момент захода в entry, момент достижения SL и TP
fill_t = None; sl_t = None; tp_t = None
for (t,o,h,l,c) in rows1m:
    if fill_t is None and l <= ENTRY: fill_t = t
    if sl_t is None and l <= SL: sl_t = t
    if tp_t is None and h >= TP: tp_t = t

def fmt(t): return t.astimezone(MSK).strftime('%H:%M:%S') if t else 'не достигнут'
print(f"Entry pullback (low ≤ {ENTRY}): {fmt(fill_t)}")
print(f"SL hit          (low ≤ {SL}):   {fmt(sl_t)}")
print(f"TP hit          (high ≥ {TP}):  {fmt(tp_t)}")

print("\nПервые 12 минут после fill:")
shown = 0
for (t,o,h,l,c) in rows1m:
    if fill_t and t >= fill_t:
        marker=''
        if l <= SL: marker += ' ← SL'
        if h >= TP: marker += ' ← TP'
        if l <= ENTRY and shown==0: marker += ' ← FILL'
        print(f"  {t.astimezone(MSK).strftime('%H:%M')} O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f}{marker}")
        shown += 1
        if shown >= 12: break
