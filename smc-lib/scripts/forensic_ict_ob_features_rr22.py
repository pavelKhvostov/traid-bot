"""ICT-aligned forensic фильтры на той же 780-выборке (i-RDRB+FVG, RR=2.2).

Гипотеза: наш C2 == ICT bullish/bearish OB. Проверяем ICT-критерии:
1. OB mitigation: trade-killer если C2 body уже задет между C5 close и нашим fill.
2. OB strength score = (C2_body_R + C4_body_R + FVG_R) / 3 — find sweet spot.
3. OB ∩ FVG overlap exists (valid ICT OB).
4. OB ∩ FVG overlap exists AND entry = midpoint(overlap) вместо 0.5·block.
5. OB body / OB range (% body) — насколько чистая displacement OB.
6. Premium/Discount: HTF swing 50×1h, entry в discount половине (long) / premium (short).
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60
SWING_LOOKBACK = 50  # 1h bars для premium/discount


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


print("Loading..."); data = load_1m()
candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def simulate(side, entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False; fill_ms = None
    for k in range(sk, ek):
        ts, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long":
                if l_ <= entry:
                    in_trade = True; fill_ms = ts
                    if l_ <= sl: return "loss", fill_ms
                    if h_ >= tp: return "win", fill_ms
            else:
                if h_ >= entry:
                    in_trade = True; fill_ms = ts
                    if h_ >= sl: return "loss", fill_ms
                    if l_ <= tp: return "win", fill_ms
        else:
            if side == "long":
                if l_ <= sl: return "loss", fill_ms
                if h_ >= tp: return "win", fill_ms
            else:
                if h_ >= sl: return "loss", fill_ms
                if l_ <= tp: return "win", fill_ms
    return "no_fill", fill_ms


# === Pattern detection + baseline simulation + ICT features ===
print("Building 1h trades + ICT features...")
trades = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue

    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [c1, c2, c3, c4, c5]
    sl = min(c.low for c in all5) if side == "long" else max(c.high for c in all5)
    r_unit = abs(entry - sl)
    if r_unit <= 0: continue
    tp = entry + 2.2 * r_unit if side == "long" else entry - 2.2 * r_unit
    c5_close_ms = c5.open_time + MS_HOUR

    out, fill_ms = simulate(side, entry, sl, tp, c5_close_ms)
    if out not in ("win", "loss"): continue

    # OB candle = C2 (для LONG i-RDRB C2 bear; для SHORT C2 bull)
    c2_body_top = max(c2.open, c2.close)
    c2_body_bot = min(c2.open, c2.close)
    c2_body = c2_body_top - c2_body_bot
    c2_range = c2.high - c2.low
    c2_body_pct = c2_body / c2_range if c2_range > 0 else 0.0

    # FVG zone
    fvg_bot, fvg_top = fvg.zone
    fvg_height = fvg_top - fvg_bot

    # OB ∩ FVG overlap
    ob_fvg_overlap_top = min(c2_body_top, fvg_top)
    ob_fvg_overlap_bot = max(c2_body_bot, fvg_bot)
    has_ob_fvg_overlap = ob_fvg_overlap_top > ob_fvg_overlap_bot
    overlap_mid = (ob_fvg_overlap_top + ob_fvg_overlap_bot) / 2 if has_ob_fvg_overlap else None

    # OB mitigation: was C2 body touched between C5 close and fill?
    ob_mitigated_before_fill = False
    if fill_ms is not None and fill_ms > c5_close_ms:
        sk = idx_at(c5_close_ms); ek = idx_at(fill_ms)
        for k in range(sk, ek):
            _, _, hh, ll, _, _ = data[k]
            if ll <= c2_body_top and hh >= c2_body_bot:
                ob_mitigated_before_fill = True
                break

    # Premium/Discount: 50×1h swing lookback (заканчивается C5)
    if i + 5 >= SWING_LOOKBACK:
        win = candles_1h[i + 5 - SWING_LOOKBACK : i + 5]
        sw_hi = max(c.high for c in win)
        sw_lo = min(c.low for c in win)
        sw_mid = (sw_hi + sw_lo) / 2
        in_discount = entry < sw_mid  # ниже середины свинга
        in_premium = entry > sw_mid
    else:
        in_discount = False; in_premium = False

    # C4 metrics (displacement)
    c4_body = abs(c4.close - c4.open)

    # Strength score
    strength = (c2_body / r_unit + c4_body / r_unit + fvg_height / r_unit) / 3.0

    trades.append({
        "side": side, "outcome": out,
        "entry": entry, "sl": sl, "r_unit": r_unit,
        "c5_close_ms": c5_close_ms, "fill_ms": fill_ms,
        "c2_body_R": c2_body / r_unit, "c2_body_pct": c2_body_pct,
        "c4_body_R": c4_body / r_unit,
        "fvg_R": fvg_height / r_unit,
        "has_overlap": has_ob_fvg_overlap, "overlap_mid": overlap_mid,
        "ob_mitigated": ob_mitigated_before_fill,
        "in_discount": in_discount, "in_premium": in_premium,
        "strength": strength,
        "c2": c2, "c4": c4, "c5": c5,
    })

n_all = len(trades)
w_all = sum(1 for t in trades if t["outcome"] == "win")
print(f"\nBaseline: n={n_all}, WR={w_all/n_all*100:.2f}%, baseline ΔWR=0\n")
baseline_wr = w_all / n_all * 100


def report(name, items):
    n = len(items)
    if n == 0: print(f"  {name:<55} n=0"); return
    w = sum(1 for x in items if x["outcome"] == "win")
    r = w * 2.2 - (n - w) * 1.0
    wr = w / n * 100
    print(f"  {name:<55} n={n:<4} WR={wr:5.2f}% (Δ{wr - baseline_wr:+5.2f}pp)  ΣR={r:+6.1f}  R/tr={r/n:+.3f}")


print("=" * 95)
print("=== 1. OB mitigation: C2 body touched between C5 close and fill ===")
mit_no = [t for t in trades if not t["ob_mitigated"]]
mit_yes = [t for t in trades if t["ob_mitigated"]]
report("OB NOT mitigated before fill (clean OB)", mit_no)
report("OB MITIGATED before fill (spent OB)", mit_yes)

print("\n=== 2. OB ∩ FVG overlap exists ===")
ovl_yes = [t for t in trades if t["has_overlap"]]
ovl_no = [t for t in trades if not t["has_overlap"]]
report("HAS OB∩FVG overlap (valid ICT structure)", ovl_yes)
report("NO overlap", ovl_no)

print("\n=== 3. OB body % (тело / range C2) — насколько 'чистая' OB ===")
buckets = [(0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.01)]
for lo, hi in buckets:
    sub = [t for t in trades if lo <= t["c2_body_pct"] < hi]
    report(f"C2 body_pct ∈ [{lo}, {hi})", sub)

print("\n=== 4. Strength score = (C2_R + C4_R + FVG_R) / 3 ===")
buckets = [(0, 0.5), (0.5, 0.8), (0.8, 1.2), (1.2, 1.8), (1.8, 100)]
for lo, hi in buckets:
    sub = [t for t in trades if lo <= t["strength"] < hi]
    report(f"strength ∈ [{lo}, {hi})", sub)

print("\n=== 5. Premium/Discount (50×1h swing) ===")
discount_long = [t for t in trades if t["side"] == "long" and t["in_discount"]]
premium_long = [t for t in trades if t["side"] == "long" and t["in_premium"]]
discount_short = [t for t in trades if t["side"] == "short" and t["in_discount"]]
premium_short = [t for t in trades if t["side"] == "short" and t["in_premium"]]
report("LONG в discount (entry < swing midpoint)", discount_long)
report("LONG в premium", premium_long)
report("SHORT в premium (entry > swing midpoint)", premium_short)
report("SHORT в discount", discount_short)
ict_zone = discount_long + premium_short
report("==> ICT-aligned zone (long@disc OR short@prem)", ict_zone)
anti_zone = premium_long + discount_short
report("==> Anti-zone (long@prem OR short@disc)", anti_zone)

print("\n=== 6. Composite ICT-valid setups ===")
# A: clean OB + overlap exists
A = [t for t in trades if not t["ob_mitigated"] and t["has_overlap"]]
report("A) clean OB + OB∩FVG overlap", A)

# B: clean OB + overlap + ICT zone
B = [t for t in A if (t["side"] == "long" and t["in_discount"]) or (t["side"] == "short" and t["in_premium"])]
report("B) A + ICT zone (long@disc / short@prem)", B)

# C: A + C2 body R >= 1.0
C = [t for t in A if t["c2_body_R"] >= 1.0]
report("C) A + C2_body ≥ 1.0R (strong OB)", C)

# D: A + strength >= 1.2
D = [t for t in A if t["strength"] >= 1.2]
report("D) A + strength ≥ 1.2", D)

# E: A + C4 body ∈ [1.0, 1.5)
E = [t for t in A if 1.0 <= t["c4_body_R"] < 1.5]
report("E) A + C4 body ∈ [1.0, 1.5)R", E)

# F: all together
F = [t for t in trades
     if not t["ob_mitigated"] and t["has_overlap"]
     and ((t["side"] == "long" and t["in_discount"]) or (t["side"] == "short" and t["in_premium"]))
     and t["c2_body_R"] >= 1.0]
report("F) clean+overlap+zone+strong_OB", F)

# G: strongest pure OB
G = [t for t in trades if t["c2_body_R"] >= 1.5 and not t["ob_mitigated"]]
report("G) C2 ≥ 1.5R + clean (no mit)", G)

print("\n=== 7. Alternative entry: midpoint(OB ∩ FVG overlap) vs 0.5·block ===")
# Только для тех у кого overlap exists: пересимулируем с entry = overlap_mid, SL прежний, TP = entry + 2.2*new_R
n_w = 0; n_l = 0; sumR = 0.0; n_nofill = 0
for t in trades:
    if not t["has_overlap"]: continue
    new_entry = t["overlap_mid"]
    new_r = abs(new_entry - t["sl"])
    if new_r <= 0: continue
    new_tp = new_entry + 2.2 * new_r if t["side"] == "long" else new_entry - 2.2 * new_r
    out2, _ = simulate(t["side"], new_entry, t["sl"], new_tp, t["c5_close_ms"])
    if out2 == "win": n_w += 1; sumR += 2.2
    elif out2 == "loss": n_l += 1; sumR -= 1
    else: n_nofill += 1
n = n_w + n_l
if n:
    print(f"  Entry @ OB∩FVG midpoint:  n={n} (+{n_nofill} no_fill)  WR={n_w/n*100:.2f}%  ΣR={sumR:+.1f}  R/tr={sumR/n:+.3f}")
