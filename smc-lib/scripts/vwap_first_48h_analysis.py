"""Что особенного в первых 48h от anchor? Анализ по нескольким углам:

1. VWAP volatility over time — когда линия «успокаивается»
2. Anchor sensitivity — расходимость близких anchors во времени
3. Cumulative volume — какая доля «финальной» массы накапливается за первые 48h
4. Per-TF interactions distribution — где сидят touches: в первые 48h или позже
5. Price action в первые 48h (range, displacement, volume vs daily avg)
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))
UTC = timezone.utc
MS = 60_000
CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

ANCHOR_TS = int(datetime(2026, 1, 31, 14, 0, tzinfo=UTC).timestamp() * 1000)   # 17:00 MSK
EVAL_END_TS = int(datetime(2026, 6, 13, 12, 0, tzinfo=UTC).timestamp() * 1000)
H48_TS = ANCHOR_TS + 48*3600*1000   # +48h cutoff

# Сравниваемые anchors: best 5
TOP_ANCHORS = [
    ("17:00", int(datetime(2026, 1, 31, 14, 0, tzinfo=UTC).timestamp() * 1000)),
    ("17:15", int(datetime(2026, 1, 31, 14, 15, tzinfo=UTC).timestamp() * 1000)),
    ("16:45", int(datetime(2026, 1, 31, 13, 45, tzinfo=UTC).timestamp() * 1000)),
    ("14:00", int(datetime(2026, 1, 31, 11, 0, tzinfo=UTC).timestamp() * 1000)),
    ("03:00 USER", int(datetime(2026, 1, 31, 0, 0, tzinfo=UTC).timestamp() * 1000)),
]

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]),
                     float(r[3]), float(r[4]), float(r[5])))

# Pre-cut к relevant window — от earliest anchor до EVAL_END
earliest = min(a[1] for a in TOP_ANCHORS)
rows = [r for r in rows if r[0] >= earliest and r[0] <= EVAL_END_TS]
print(f"  1m rows in eval window: {len(rows)}")


def vwap_series(rows_1m, anchor_ts, end_ts):
    """Returns list of (ts, vwap, cum_v) for each 1m bar from anchor to end."""
    out = []
    cum_pv = 0.0; cum_v = 0.0
    for ts, o, h, l, c, v in rows_1m:
        if ts < anchor_ts: continue
        if ts > end_ts: break
        tp = (h + l + c) / 3.0
        cum_pv += tp * v
        cum_v  += v
        out.append((ts, cum_pv / cum_v if cum_v > 0 else None, cum_v))
    return out


# === Часть 1: VWAP volatility — как быстро линия успокаивается ===
print("\n=== Часть 1: VWAP volatility (∂VWAP/∂t по часам с anchor) ===")
print("Для best anchor 17:00 МСК: rolling std VWAP в скользящем 1h окне\n")

best_series = vwap_series(rows, ANCHOR_TS, EVAL_END_TS)
print(f"  total 1m points after anchor: {len(best_series)}")

# Усреднение VWAP по 1h окнам, std в окне
def hourly_volatility(series):
    """returns [(hour_idx, vwap_std_in_hour, vwap_mean_in_hour)]"""
    if not series: return []
    start_ts = series[0][0]
    buckets = {}
    for ts, vw, cv in series:
        if vw is None: continue
        h = (ts - start_ts) // (3600*1000)
        buckets.setdefault(h, []).append(vw)
    out = []
    for h in sorted(buckets.keys()):
        vals = buckets[h]
        if len(vals) < 2: continue
        mean = sum(vals)/len(vals)
        var = sum((v-mean)**2 for v in vals)/len(vals)
        std = var**0.5
        out.append((h, std, mean))
    return out

vol = hourly_volatility(best_series)
print(f"  hour | VWAP std в часе | VWAP mean")
print(f"  -----|-----------------|----------")
for h, std, mean in vol[:8]:
    print(f"  {h:>4} | {std:>15.2f} | {mean:>10.2f}")
print("  ...")
for h, std, mean in vol[24:32]:  # часы 24-32 (= после первого дня)
    print(f"  {h:>4} | {std:>15.2f} | {mean:>10.2f}")
print("  ...")
for h, std, mean in vol[48:56]:  # часы 48-56 (= сразу после 48h)
    print(f"  {h:>4} | {std:>15.2f} | {mean:>10.2f}")
print("  ...")
# Take very late
late = vol[-10:]
for h, std, mean in late[:4]:
    print(f"  {h:>4} | {std:>15.2f} | {mean:>10.2f}")


# === Часть 2: Anchor sensitivity ===
print("\n\n=== Часть 2: Расхождение VWAP между близкими anchors ===")
print("|VWAP_best − VWAP_other| на отметках: 1h, 6h, 12h, 24h, 48h, 7d, 30d, 4mo\n")

# Pre-compute series для всех top
all_series = {label: vwap_series(rows, anc, EVAL_END_TS) for label, anc in TOP_ANCHORS}
best_dict = {ts: vw for ts, vw, cv in all_series["17:00"] if vw is not None}

# Marks (часы от anchor 17:00)
marks_h = [1, 6, 12, 24, 48, 24*7, 24*30, 24*30*4]
mark_labels = ["1h", "6h", "12h", "24h", "48h", "7d", "30d", "4mo"]

print(f"  hour from 17:00 ", end="")
for lbl in mark_labels:
    print(f"{lbl:>8}", end=" ")
print()

# Build per-anchor lookup by hour mark
def vwap_at(series, target_ts):
    """find last vwap before/at target_ts"""
    last = None
    for ts, vw, _ in series:
        if vw is None: continue
        if ts > target_ts: break
        last = vw
    return last

base_anchor = ANCHOR_TS
for label, anc in TOP_ANCHORS:
    if label == "17:00":
        continue
    print(f"  Δ vs {label:<10}: ", end="")
    for mh in marks_h:
        target = base_anchor + mh*3600*1000
        v_best = vwap_at(all_series["17:00"], target)
        v_other = vwap_at(all_series[label], target)
        if v_best is None or v_other is None:
            print(f"{'-':>8}", end=" ")
        else:
            d = abs(v_best - v_other)
            print(f"{d:>7.1f}$", end=" ")
    print()


# === Часть 3: Cumulative volume contribution ===
print("\n\n=== Часть 3: Cumulative volume — доля finalвой massы в первых 48h ===")

last_cv = best_series[-1][2]
# find cv at 48h mark
target = ANCHOR_TS + 48*3600*1000
cv_48 = None
for ts, vw, cv in best_series:
    if ts > target: break
    cv_48 = cv

cv_24 = None
target_24 = ANCHOR_TS + 24*3600*1000
for ts, vw, cv in best_series:
    if ts > target_24: break
    cv_24 = cv

cv_7d = None
target_7d = ANCHOR_TS + 7*24*3600*1000
for ts, vw, cv in best_series:
    if ts > target_7d: break
    cv_7d = cv

cv_30d = None
target_30d = ANCHOR_TS + 30*24*3600*1000
for ts, vw, cv in best_series:
    if ts > target_30d: break
    cv_30d = cv

print(f"  Cumulative volume at:")
print(f"    24h  = {cv_24:>15,.0f}  ({cv_24/last_cv*100:.2f}% от final)")
print(f"    48h  = {cv_48:>15,.0f}  ({cv_48/last_cv*100:.2f}% от final)")
print(f"    7d   = {cv_7d:>15,.0f}  ({cv_7d/last_cv*100:.2f}% от final)")
print(f"    30d  = {cv_30d:>15,.0f}  ({cv_30d/last_cv*100:.2f}% от final)")
print(f"    4mo  = {last_cv:>15,.0f}  (100% final, ~133 дня)")


# === Часть 4: Интеракции в cascade — первые 48h vs позже ===
print("\n\n=== Часть 4: Где сидят touches: первые 48h vs позже ===")
print("Для best anchor 17:00 МСК — interactions per TF, 0-48h vs 48h-now\n")

def agg_from(rows_1m, start_ts, end_ts, tf_ms):
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in rows_1m:
        if ts < start_ts: continue
        if ts > end_ts: break
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v = oo,hh,ll,cc,vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v += vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

def count_interactions(tf_bars, vwap_lookup):
    """Возвращает (n_interactions, n_reactions) для серии TF-баров с VWAP lookup."""
    inter = 0; react = 0
    prev_side = None
    for b in tf_bars:
        ts, o, hi, lo, cl, _ = b
        vw = vwap_lookup(ts + 1)  # vwap at close of bar
        if vw is None:
            prev_side = None
            continue
        touched = (lo <= vw <= hi)
        side = 'above' if cl > vw else ('below' if cl < vw else None)
        if touched and side is not None and prev_side is not None:
            inter += 1
            if side == prev_side: react += 1
        prev_side = side
    return inter, react

def vwap_lookup_factory(series):
    """Lookup function: vw_at(t) = last vwap <= t"""
    arr = [(ts, vw) for ts, vw, _ in series if vw is not None]
    def lookup(t):
        # linear scan (ok for moderate sizes)
        last = None
        for ts, vw in arr:
            if ts > t: break
            last = vw
        return last
    return lookup

lookup = vwap_lookup_factory(best_series)

print(f"  TF    | int 0-48h | int 48h-now | react 0-48h | react 48h-now | score 0-48h | score 48h-now")
print(f"  ------|-----------|-------------|-------------|---------------|-------------|---------------")
for tf_name, tf_min in [('1h', 60), ('2h', 120), ('4h', 240), ('6h', 360), ('8h', 480), ('12h', 720)]:
    tf_ms = tf_min * MS
    bars_48 = agg_from(rows, ANCHOR_TS, H48_TS, tf_ms)
    bars_after = agg_from(rows, H48_TS, EVAL_END_TS, tf_ms)
    i1, r1 = count_interactions(bars_48, lookup)
    i2, r2 = count_interactions(bars_after, lookup)
    s1 = r1/i1 if i1>0 else 0.0
    s2 = r2/i2 if i2>0 else 0.0
    print(f"  {tf_name:<5} | {i1:>9} | {i2:>11} | {r1:>11} | {r2:>13} | {s1:>11.3f} | {s2:>13.3f}")


# === Часть 5: Price action в первые 48h ===
print("\n\n=== Часть 5: Что делала цена в первые 48h ===")
first_48h = [r for r in rows if ANCHOR_TS <= r[0] <= H48_TS]
all_after_48h = [r for r in rows if r[0] > H48_TS and r[0] <= EVAL_END_TS]

def stats(bars_1m, label):
    if not bars_1m: return
    opens = bars_1m[0][1]
    closes = bars_1m[-1][4]
    highs = max(b[2] for b in bars_1m)
    lows = min(b[3] for b in bars_1m)
    vol = sum(b[5] for b in bars_1m)
    n_min = len(bars_1m)
    n_h = n_min / 60
    move_pct = (closes - opens) / opens * 100
    range_pct = (highs - lows) / opens * 100
    print(f"  {label}:")
    print(f"    окно длина = {n_min} мин ({n_h:.1f} ч)")
    print(f"    open  → close: {opens:.0f} → {closes:.0f}  ({move_pct:+.2f}%)")
    print(f"    high / low:    {highs:.0f} / {lows:.0f}   range = {range_pct:.2f}%")
    print(f"    total volume:  {vol:,.0f}  ({vol/n_h:,.0f} per hour)")

stats(first_48h, "First 48h post-anchor (2026-01-31 14:00 UTC → 2026-02-02 14:00 UTC)")
stats(all_after_48h[:48*60], "Hours 48-96 post-anchor (next 48h after)")
# Daily average vol for comparison
daily_window = all_after_48h[:14*24*60]  # next 14 days for baseline
if daily_window:
    avg_daily_vol = sum(b[5] for b in daily_window) / 14
    print(f"\n  Baseline: avg daily volume in next 14 days = {avg_daily_vol:,.0f}")
    first_48h_vol = sum(b[5] for b in first_48h)
    print(f"           first 48h volume / 2 = {first_48h_vol/2:,.0f}")
    print(f"           ratio first-48h-per-day / baseline = {(first_48h_vol/2)/avg_daily_vol:.2f}x")
