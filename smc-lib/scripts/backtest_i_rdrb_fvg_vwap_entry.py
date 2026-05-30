"""Бэктест i-RDRB + FVG со входом по VWAP ("вход по VWAPs ASVK").

Правила:
- Detection: i-RDRB+FVG на 1h.
- Anchor VWAP: 5m свеча, содержащая pattern_low (LONG) / pattern_high (SHORT) на 1m уровне.
- VWAP формула ASVK: cum(volume × close) / cum(volume) с anchor по 1m данным.
- Entry: первое 1m с anchor+1 где VWAP ∈ [bar.low, bar.high].
- Filter: VWAP в момент fill ≤ block.top (LONG) / ≥ block.bottom (SHORT). Иначе skip.
- Entry price = VWAP value.
- SL = pattern_low (LONG) / pattern_high (SHORT).
- TP = RR 1:1 от (entry − SL).
- После fill — TP/SL на 1m. Приоритет SL при one-bar ambiguity.
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
MS_5M = 5 * 60_000
MS_HOUR = 3600_000


def load_1m_full():
    rows = []
    with CSV_PATH.open() as f:
        reader = csv.reader(f)
        next(reader)
        for r in reader:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate_to_1h(data_1m):
    bucket = MS_HOUR
    out: list[Candle] = []
    cur_b = None
    cur_o = cur_h = cur_l = cur_c = 0.0
    for ts, o, h, l, c, _v in data_1m:
        b = ts - (ts % bucket)
        if b != cur_b:
            if cur_b is not None:
                out.append(Candle(open=cur_o, high=cur_h, low=cur_l, close=cur_c, open_time=cur_b))
            cur_b = b
            cur_o, cur_h, cur_l, cur_c = o, h, l, c
        else:
            cur_h = max(cur_h, h); cur_l = min(cur_l, l); cur_c = c
    if cur_b is not None:
        out.append(Candle(open=cur_o, high=cur_h, low=cur_l, close=cur_c, open_time=cur_b))
    return out


print("Loading 1m..."); data = load_1m_full()
print(f"Loaded {len(data):,} 1m rows")
ts_arr = [r[0] for r in data]


def idx_at(ms):
    lo, hi = 0, len(ts_arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_arr[mid] < ms:
            lo = mid + 1
        else:
            hi = mid
    return lo


print("Aggregating to 1h...")
candles_1h = aggregate_to_1h(data)
print(f"Aggregated to {len(candles_1h):,} 1h candles\n")

# Найти все i-RDRB+FVG паттерны
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))
print(f"Total i-RDRB+FVG patterns: {len(patterns)}\n")


def find_anchor_1m(start_ms, end_ms, side, extreme_value):
    """Найти 1m с low == extreme (LONG) или high == extreme (SHORT) в окне [start, end)."""
    j0 = idx_at(start_ms); j1 = idx_at(end_ms)
    for k in range(j0, j1):
        if side == "long" and data[k][3] == extreme_value:
            return k
        if side == "short" and data[k][2] == extreme_value:
            return k
    # fallback: ближайшее
    best_k = None; best_v = float("inf") if side == "long" else float("-inf")
    for k in range(j0, j1):
        v = data[k][3] if side == "long" else data[k][2]
        if (side == "long" and v < best_v) or (side == "short" and v > best_v):
            best_v = v; best_k = k
    return best_k


stats = {
    "long":  {"win": 0, "loss": 0, "no_fill": 0, "filtered": 0},
    "short": {"win": 0, "loss": 0, "no_fill": 0, "filtered": 0},
}
total_r = 0.0

for ir, c5 in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    if side == "long":
        sl = min(c.low for c in all5)
    else:
        sl = max(c.high for c in all5)

    # окно поиска anchor — весь паттерн от C1 до C5 (5 1h свечей)
    p_start = ir.rdrb.c1.open_time
    p_end = c5.open_time + MS_HOUR
    anchor_1m = find_anchor_1m(p_start, p_end, side, sl)
    if anchor_1m is None:
        stats[side]["no_fill"] += 1
        continue
    anchor_ms = data[anchor_1m][0]
    anchor_5m_ms = anchor_ms - (anchor_ms % MS_5M)
    anchor_idx = idx_at(anchor_5m_ms)

    c5_close_ms = c5.open_time + MS_HOUR

    # Считаем VWAP и ищем fill
    cum_pv = 0.0; cum_vol = 0.0
    in_trade = False; outcome = "no_fill"; entry = None; tp = None; r_val = None
    for k in range(anchor_idx, len(data)):
        ts, o_, h_, l_, c_, v_ = data[k]
        cum_pv += v_ * c_
        cum_vol += v_
        vwap = cum_pv / cum_vol if cum_vol > 0 else 0

        if not in_trade:
            if ts < c5_close_ms:
                continue
            # check VWAP в диапазоне свечи
            if l_ <= vwap <= h_:
                # filter
                if side == "long" and vwap > block_t:
                    outcome = "filtered"; break
                if side == "short" and vwap < block_b:
                    outcome = "filtered"; break
                in_trade = True
                entry = vwap
                if side == "long":
                    r_val = entry - sl; tp = entry + r_val
                else:
                    r_val = sl - entry; tp = entry - r_val
                if r_val <= 0:
                    outcome = "filtered"; break
                # check fill bar itself
                if side == "long":
                    if l_ <= sl: outcome = "loss"; break
                    if h_ >= tp: outcome = "win"; break
                else:
                    if h_ >= sl: outcome = "loss"; break
                    if l_ <= tp: outcome = "win"; break
        else:
            if side == "long":
                if l_ <= sl: outcome = "loss"; break
                if h_ >= tp: outcome = "win"; break
            else:
                if h_ >= sl: outcome = "loss"; break
                if l_ <= tp: outcome = "win"; break

    stats[side][outcome] += 1
    if outcome == "win": total_r += 1.0
    elif outcome == "loss": total_r -= 1.0


# Сводка
print(f"{'Outcome':<12} {'LONG':>8} {'SHORT':>8} {'Total':>8}")
print("-" * 42)
for k_ in ("win", "loss", "no_fill", "filtered"):
    l, s = stats["long"][k_], stats["short"][k_]
    print(f"{k_:<12} {l:>8} {s:>8} {l+s:>8}")
tot_l = sum(stats["long"].values()); tot_s = sum(stats["short"].values())
print(f"{'Total':<12} {tot_l:>8} {tot_s:>8} {tot_l+tot_s:>8}")

def wr(side):
    w = stats[side]["win"]; l = stats[side]["loss"]
    return w / (w + l) * 100 if (w + l) else 0

print()
total_w = stats['long']['win'] + stats['short']['win']
total_l = stats['long']['loss'] + stats['short']['loss']
print(f"WR (win / (win+loss)):")
print(f"  LONG:   {wr('long'):.2f}% ({stats['long']['win']}/{stats['long']['win']+stats['long']['loss']})")
print(f"  SHORT:  {wr('short'):.2f}% ({stats['short']['win']}/{stats['short']['win']+stats['short']['loss']})")
print(f"  TOTAL:  {total_w/(total_w+total_l)*100 if (total_w+total_l) else 0:.2f}% ({total_w}/{total_w+total_l})")
print(f"\nTotal R (RR 1:1): {total_r:+.0f}R")
print(f"Expectancy: {total_r/(total_w+total_l) if (total_w+total_l) else 0:+.3f}R per trade")
print(f"\nFiltered out (VWAP за block): {stats['long']['filtered']+stats['short']['filtered']}")
print(f"No fill: {stats['long']['no_fill']+stats['short']['no_fill']}")
print(f"Trades opened: {total_w+total_l} / {len(patterns)} ({(total_w+total_l)/len(patterns)*100:.1f}%)")
