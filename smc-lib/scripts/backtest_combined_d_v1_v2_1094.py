"""Combined D backtest на расширенной выборке V1+V2 = 1094 setups.

V1: FVG на (C3, C4, C5), 5-bar pattern, simulate start = c5_close
V2: FVG на (C4, C5, C6), 6-bar pattern, simulate start = c6_close

Entry/SL formula = Combined D (canonical):
  LONG:  entry=block.top    SL=pl+0.1×(bb-pl)
  SHORT: entry=block.bottom SL=ph-0.1×(ph-bt)

Два TP режима:
  (a) baseline: TP_long = entry_baseline + R_unit_base
                TP_short = entry_baseline - R_unit_base
  (b) RR=2.2:   TP_long = entry + 2.2 × (entry - SL)
                TP_short = entry - 2.2 × (SL - entry)

Pattern_low/high считается по всем 5 (V1) или 6 (V2) свечам.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60   # 30 дней


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]) if len(r) > 5 else 0.0))
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
print(f"  {len(data):,} 1m rows")
candles_1h = aggregate(data, 60)
ts_1m = [r[0] for r in data]
print(f"  {len(candles_1h):,} 1h bars")

# Window: last 6 years
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
candles_1h_w = [c for c in candles_1h if c.open_time >= window_start_ms]
print(f"  6y window: {len(candles_1h_w):,} 1h bars\n")


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def simulate(side, entry, sl, tp, start_ms):
    sk = idx_at(start_ms); ek = min(sk + MAX_HOLD_MIN, len(data))
    in_trade = False
    for k in range(sk, ek):
        _, _, h_, l_, _, _ = data[k]
        if not in_trade:
            if side == "long":
                if l_ <= entry:
                    in_trade = True
                    if l_ <= sl: return "loss"
                    if h_ >= tp: return "win"
            else:
                if h_ >= entry:
                    in_trade = True
                    if h_ >= sl: return "loss"
                    if l_ <= tp: return "win"
        else:
            if side == "long":
                if l_ <= sl: return "loss"
                if h_ >= tp: return "win"
            else:
                if h_ >= sl: return "loss"
                if l_ <= tp: return "win"
    return "no_fill"


# === Pattern detection: V1 + V2 ===
v1_setups = []   # (ir, c5, "V1", pattern_low, pattern_high, start_ms)
v2_setups = []   # (ir, c6, "V2", pattern_low, pattern_high, start_ms)

for i in range(len(candles_1h_w) - 5):
    c1, c2, c3, c4, c5, c6 = candles_1h_w[i:i + 6]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue

    # V1: FVG on C3-C4-C5
    fvg_v1 = detect_fvg(c3, c4, c5)
    if fvg_v1 and fvg_v1.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5))
        ph = max(c.high for c in (c1, c2, c3, c4, c5))
        start_ms = c5.open_time + MS_HOUR
        v1_setups.append((ir, "V1", pl, ph, start_ms))

    # V2: FVG on C4-C5-C6
    fvg_v2 = detect_fvg(c4, c5, c6)
    if fvg_v2 and fvg_v2.direction == ir.direction:
        pl = min(c.low for c in (c1, c2, c3, c4, c5, c6))
        ph = max(c.high for c in (c1, c2, c3, c4, c5, c6))
        start_ms = c6.open_time + MS_HOUR
        v2_setups.append((ir, "V2", pl, ph, start_ms))

print(f"Detected: V1={len(v1_setups)}, V2={len(v2_setups)}, Total={len(v1_setups)+len(v2_setups)}\n")


def trade_one(side, ir, pl, ph, start_ms, tp_mode):
    """Returns (outcome, rr_new, rr_base, entry, sl, tp)."""
    bb, bt = ir.rdrb.block
    entry_base = (bb + bt) / 2

    # Combined D entry/SL
    if side == "long":
        entry = bt
        sl = pl + 0.1 * (bb - pl)
        r_unit_new = entry - sl
        r_unit_base = entry_base - pl
        if r_unit_new <= 0 or r_unit_base <= 0:
            return None
        if tp_mode == "baseline":
            tp = entry_base + r_unit_base
        elif tp_mode == "rr10":
            tp = entry + 1.0 * r_unit_new
        else:  # rr22
            tp = entry + 2.2 * r_unit_new
        if entry >= tp: return None
        rr_new = (tp - entry) / r_unit_new
        rr_base = (tp - entry) / r_unit_base
    else:
        entry = bb
        sl = ph - 0.1 * (ph - bt)
        r_unit_new = sl - entry
        r_unit_base = ph - entry_base
        if r_unit_new <= 0 or r_unit_base <= 0:
            return None
        if tp_mode == "baseline":
            tp = entry_base - r_unit_base
        elif tp_mode == "rr10":
            tp = entry - 1.0 * r_unit_new
        else:  # rr22
            tp = entry - 2.2 * r_unit_new
        if entry <= tp: return None
        rr_new = (entry - tp) / r_unit_new
        rr_base = (entry - tp) / r_unit_base

    outcome = simulate(side, entry, sl, tp, start_ms)
    return outcome, rr_new, rr_base


def run_segment(name, setups, tp_mode):
    stats = {"long": {"win": 0, "loss": 0, "nf": 0, "sr_new": 0.0, "sr_base": 0.0, "rrs": []},
             "short": {"win": 0, "loss": 0, "nf": 0, "sr_new": 0.0, "sr_base": 0.0, "rrs": []}}
    for ir, variant, pl, ph, start_ms in setups:
        side = ir.direction
        r = trade_one(side, ir, pl, ph, start_ms, tp_mode)
        if r is None: continue
        outcome, rr_new, rr_base = r
        s = stats[side]
        if outcome == "win":
            s["win"] += 1; s["sr_new"] += rr_new; s["sr_base"] += rr_base
            s["rrs"].append(rr_new)
        elif outcome == "loss":
            s["loss"] += 1; s["sr_new"] -= 1.0; s["sr_base"] -= (1.0 if tp_mode == "rr22" else r_unit_for_base(side, ir, pl, ph))
        else:
            s["nf"] += 1
    return stats


def r_unit_for_base(side, ir, pl, ph):
    """Returns r_unit_new / r_unit_base ratio (loss in baseline units)."""
    bb, bt = ir.rdrb.block
    entry_base = (bb + bt) / 2
    if side == "long":
        entry = bt
        sl = pl + 0.1 * (bb - pl)
        return (entry - sl) / (entry_base - pl) if (entry_base - pl) > 0 else 1.0
    else:
        entry = bb
        sl = ph - 0.1 * (ph - bt)
        return (sl - entry) / (ph - entry_base) if (ph - entry_base) > 0 else 1.0


def print_stats(name, stats):
    s_l, s_s = stats["long"], stats["short"]
    n_l = s_l["win"] + s_l["loss"]; n_s = s_s["win"] + s_s["loss"]
    n_t = n_l + n_s; w_t = s_l["win"] + s_s["win"]
    wr_l = s_l["win"] / n_l * 100 if n_l else 0
    wr_s = s_s["win"] / n_s * 100 if n_s else 0
    wr_t = w_t / n_t * 100 if n_t else 0
    avg_l = sum(s_l["rrs"]) / len(s_l["rrs"]) if s_l["rrs"] else 0
    avg_s = sum(s_s["rrs"]) / len(s_s["rrs"]) if s_s["rrs"] else 0

    print(f"\n=== {name} ===")
    print(f"{'Side':<8} {'n':<6} {'WIN':<6} {'LOSS':<6} {'NoFill':<8} {'WR':<8} {'ΣR_new':<10} {'avg_RR':<8}")
    print(f"{'LONG':<8} {n_l:<6} {s_l['win']:<6} {s_l['loss']:<6} {s_l['nf']:<8} {wr_l:<7.2f}% {s_l['sr_new']:<+10.1f} {avg_l:<8.2f}")
    print(f"{'SHORT':<8} {n_s:<6} {s_s['win']:<6} {s_s['loss']:<6} {s_s['nf']:<8} {wr_s:<7.2f}% {s_s['sr_new']:<+10.1f} {avg_s:<8.2f}")
    print(f"{'TOTAL':<8} {n_t:<6} {w_t:<6} {s_l['loss']+s_s['loss']:<6} {s_l['nf']+s_s['nf']:<8} {wr_t:<7.2f}% {s_l['sr_new']+s_s['sr_new']:<+10.1f}")


def combine_stats(*statss):
    out = {"long": {"win": 0, "loss": 0, "nf": 0, "sr_new": 0.0, "sr_base": 0.0, "rrs": []},
           "short": {"win": 0, "loss": 0, "nf": 0, "sr_new": 0.0, "sr_base": 0.0, "rrs": []}}
    for s in statss:
        for side in ("long", "short"):
            out[side]["win"] += s[side]["win"]
            out[side]["loss"] += s[side]["loss"]
            out[side]["nf"] += s[side]["nf"]
            out[side]["sr_new"] += s[side]["sr_new"]
            out[side]["sr_base"] += s[side]["sr_base"]
            out[side]["rrs"].extend(s[side]["rrs"])
    return out


print("=" * 78)
print(" COMBINED D entry/SL · TP @ RR=1.0 (fixed, от реального entry)")
print("=" * 78)
v1_r = run_segment("V1 RR=1.0", v1_setups, "rr10")
v2_r = run_segment("V2 RR=1.0", v2_setups, "rr10")
print_stats("V1 only (5-bar, FVG C3-C4-C5)", v1_r)
print_stats("V2 only (6-bar, FVG C4-C5-C6)", v2_r)
print_stats("V1 + V2 COMBINED (1094 raw)", combine_stats(v1_r, v2_r))
