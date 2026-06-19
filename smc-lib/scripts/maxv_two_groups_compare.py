"""Compare two groups of D maxV's:
Group 1: 30-01, 31-01, 06-05
Group 2: 04-02, 05-02, 08-02
"""
from __future__ import annotations
import math, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
LTF_MIN = 32
TF_MS = 1440 * MS_M
K_V = 3.0
TAU = 7.0

# Расширенное окно
DATE_FROM = "2026-01-25"
DATE_TO = "2026-05-07"

GROUP_1 = ["2026-01-30", "2026-01-31", "2026-05-06"]
GROUP_2 = ["2026-02-04", "2026-02-05", "2026-02-08"]

start_ms = int(datetime.fromisoformat(DATE_FROM).replace(tzinfo=timezone.utc).timestamp() * 1000)
end_ms = int(datetime.fromisoformat(DATE_TO).replace(tzinfo=timezone.utc).timestamp() * 1000) + TF_MS

rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        ts = int(t.timestamp() * 1000)
        if ts < start_ms: continue
        if ts >= end_ms: break
        rows.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

last_ts = rows[-1][0]
win_end = last_ts + MS_M

def agg(rs, tf_ms, anchor=0):
    out = []; cb = None; o=h=l=c=0.0; v=0.0
    for ts, oo, hh, ll, cc, vv in rs:
        b = ts - ((ts - anchor) % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v=oo,hh,ll,cc,vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

barsD = agg(rows, TF_MS)
barsD_by_start = {b[0]: b for b in barsD}

def maxv_for_d(d_start_ms, ltf_min=LTF_MIN):
    d_end = d_start_ms + TF_MS
    ltf_ms = ltf_min * MS_M
    out = []; cb=None; o=h=l=c=0.0; v=0.0
    for ts, oo, hh, ll, cc, vv in rows:
        if ts < d_start_ms: continue
        if ts >= d_end: break
        b = ts - ((ts - d_start_ms) % ltf_ms)
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v=oo,hh,ll,cc,vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    if not out: return None
    return max(out, key=lambda b: b[5])

def check_mitigation(level, formation_end_ms):
    for ts, o, h, l, c, v in rows:
        if ts < formation_end_ms: continue
        if l <= level <= h:
            return True, ts
    return False, None

def w_pos(p): return 1.5 if "wick" in p else 0.7
def w_age(days): return 1 + 0.3 * math.log(1 + max(days, 0) / 30)
def w_virgin(is_mit, days_since_touch):
    if not is_mit: return K_V
    return 1.0 + (K_V - 1.0) * math.exp(-max(days_since_touch, 0) / TAU)

def analyze(date_str):
    d_start = int(datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp() * 1000)
    db = barsD_by_start.get(d_start)
    if db is None: return None
    mb = maxv_for_d(d_start)
    if mb is None: return None
    mb_ts, mb_o, mb_h, mb_l, mb_c, mb_v = mb
    d_o, d_h, d_l, d_c = db[1], db[2], db[3], db[4]
    body_lo, body_hi = min(d_o, d_c), max(d_o, d_c)
    if mb_c < body_lo: pos = "lower_wick"
    elif mb_c > body_hi: pos = "upper_wick"
    elif mb_c < (body_lo + body_hi)/2: pos = "body_bottom"
    else: pos = "body_top"
    d_color = "BULL" if d_c > d_o else ("BEAR" if d_c < d_o else "doji")
    d_range = d_h - d_l
    d_body = abs(d_c - d_o)
    age_days = (win_end - d_start) / (24*3600*1000)
    parent_d_end = d_start + TF_MS
    is_mit, first_touch = check_mitigation(mb_c, parent_d_end)
    days_since_touch = (win_end - first_touch) / (24*3600*1000) if is_mit else 0.0
    W_v = w_virgin(is_mit, days_since_touch)
    AMP = w_pos(pos) * w_age(age_days) * W_v
    return {
        "date": date_str,
        "d_color": d_color,
        "d_OHLC": (d_o, d_h, d_l, d_c),
        "d_range": d_range,
        "d_body": d_body,
        "body_pct": d_body / d_range * 100 if d_range > 0 else 0,
        "level": mb_c,
        "zone": (mb_l, mb_h),
        "zone_pct_of_d": (mb_h - mb_l) / d_range * 100 if d_range > 0 else 0,
        "vol": mb_v,
        "pos": pos,
        "mit": is_mit,
        "days_since_touch": days_since_touch,
        "age": age_days,
        "W_pos": w_pos(pos),
        "W_age": w_age(age_days),
        "W_v": W_v,
        "AMP": AMP,
    }

def print_group(name, dates):
    print(f"\n{'='*90}\n{name}\n{'='*90}")
    for d in dates:
        r = analyze(d)
        if r is None:
            print(f"  {d}: NO DATA")
            continue
        o, h, l, c = r["d_OHLC"]
        zlo, zhi = r["zone"]
        mit_str = f"MIT ({r['days_since_touch']:.0f}d ago)" if r["mit"] else "VIRGIN"
        print(f"\n  D {r['date']} [{r['d_color']}]:")
        print(f"    OHLC: O={o:.0f} H={h:.0f} L={l:.0f} C={c:.0f}  range={r['d_range']:.0f}  body={r['body_pct']:.0f}%")
        print(f"    maxV: L={r['level']:.0f}  zone=[{zlo:.0f}..{zhi:.0f}]  ({r['zone_pct_of_d']:.0f}% of D range)  V={r['vol']:.0f}")
        print(f"    pos={r['pos']:<12}  mitigation={mit_str}  age={r['age']:.0f}d")
        print(f"    W_pos={r['W_pos']:.2f}  W_age={r['W_age']:.2f}  W_v={r['W_v']:.2f}  →  AMP={r['AMP']:.2f}")

print_group("ГРУППА 1:  30-01, 31-01, 06-05", GROUP_1)
print_group("ГРУППА 2:  04-02, 05-02, 08-02", GROUP_2)
