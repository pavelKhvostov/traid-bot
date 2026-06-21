"""VWAP-cross strategy на 4h fractals.

Концепция:
  1. На 4h TF определяем последний confirmed FH и последний confirmed FL (Williams N=2).
  2. Anchored VWAP считается на 1m данных от каждого якоря (open_time pivot-свечи).
  3. При появлении нового FH/FL — соответствующий VWAP перeanchorится.
  4. Состояние:
       BULL  : VWAP_FL > VWAP_FH  (нижняя средняя обогнала верхнюю → накопление выше пивотов)
       BEAR  : VWAP_FH > VWAP_FL
  5. Сигнал crossover = смена состояния на закрытии 4h-бара.
  6. Trade:
       Entry  = close 4h cross-бара
       SL     = противоположная VWAP (та, которая сейчас "снизу" для LONG, "сверху" для SHORT)
       TP     = entry ± k_RR × R   (R = |entry − SL|)
  7. Max hold = 30 дней; force-close при противоположном crossover (regime flip).

Параметры:
  --rr     : RR multiplier (default 1.0)
  --regime_exit : True → exit on opposite cross (вместо MAX_HOLD)
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.fractal.code import detect_fractal

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
TF_4H_MS = 4 * MS_HOUR
MAX_HOLD_MIN = 30 * 24 * 60
RR = 1.0
REGIME_EXIT = True  # exit on opposite cross (else только TP/SL)

t0 = time.time()


def load_1m():
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp() * 1000),
                         float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows


def aggregate_4h(d):
    bucket = TF_4H_MS
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


print("Loading 1m..."); data = load_1m()
print(f"  {len(data):,} 1m rows ({time.time()-t0:.1f}s)")

# numpy arrays для скана
ts_arr = np.array([r[0] for r in data], dtype=np.int64)
op_arr = np.array([r[1] for r in data], dtype=np.float64)
hi_arr = np.array([r[2] for r in data], dtype=np.float64)
lo_arr = np.array([r[3] for r in data], dtype=np.float64)
cl_arr = np.array([r[4] for r in data], dtype=np.float64)
vol_arr = np.array([r[5] for r in data], dtype=np.float64)
tp_arr = (hi_arr + lo_arr + cl_arr) / 3.0
pv_arr = tp_arr * vol_arr

# cumulative для anchored VWAP
cum_pv = np.cumsum(pv_arr)
cum_v = np.cumsum(vol_arr)


def anchored_vwap_at(anchor_ts, query_ts):
    """VWAP value at query_ts, anchored at anchor_ts (both inclusive on 1m grid)."""
    if query_ts < anchor_ts: return None
    i0 = int(np.searchsorted(ts_arr, anchor_ts, side='left'))
    i1 = int(np.searchsorted(ts_arr, query_ts, side='right')) - 1
    if i1 < i0 or i0 >= len(ts_arr): return None
    pv = cum_pv[i1] - (cum_pv[i0-1] if i0 > 0 else 0)
    vv = cum_v[i1] - (cum_v[i0-1] if i0 > 0 else 0)
    return pv / vv if vv > 0 else None


# 4h candles
bars_4h = aggregate_4h(data)
print(f"  {len(bars_4h):,} 4h bars")

# 6y window
last_ts = data[-1][0]
window_start_ms = last_ts - 6 * 365 * 24 * 3600 * 1000
bars_4h_idx_start = next(i for i, b in enumerate(bars_4h) if b[0] >= window_start_ms)
print(f"  Window starts at 4h idx {bars_4h_idx_start}")

# Detect 4h fractals (N=2) — confirmed at center.open + 3*TF
candles_4h = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars_4h]

fractals = []  # {dir, center_idx, level, confirm_ts, anchor_ts (= center.open_time)}
for i in range(2, len(candles_4h) - 2):
    f = detect_fractal(candles_4h[i-2:i+3], n=2)
    if f is None: continue
    fractals.append({
        "dir": f.direction,
        "center_idx": i,
        "level": f.level,
        "confirm_ts": candles_4h[i].open_time + 3 * TF_4H_MS,
        "anchor_ts": candles_4h[i].open_time,
    })
print(f"  {len(fractals):,} 4h fractals total")


# === Strategy loop ===
# Walk через 4h bars начиная с window_start; на каждом close:
#   1. Найти ACTIVE FH = последний confirmed FH (confirm_ts <= bar.close_ts)
#      ACTIVE FL = последний confirmed FL.
#   2. Считать VWAP_FH(bar.close_ts) и VWAP_FL(bar.close_ts).
#   3. Сравнить с prev состоянием. Если cross → enter trade в этом направлении.
#   4. Управление trade (TP/SL/regime_exit).

print("\nRunning strategy backtest...")

def idx_at(ms):
    return int(np.searchsorted(ts_arr, ms, side='left'))


# Symbols for tracking state
trades = []  # {entry_ts, side, entry, sl, tp, exit_ts, exit_price, outcome, r_unit, hold_h}
open_trade = None
prev_state = None  # "BULL" / "BEAR" / None

# Precompute confirmed fractals sorted by confirm_ts
fh_sorted = sorted([f for f in fractals if f["dir"] == "high"], key=lambda x: x["confirm_ts"])
fl_sorted = sorted([f for f in fractals if f["dir"] == "low"], key=lambda x: x["confirm_ts"])
fh_confirm_ts = np.array([f["confirm_ts"] for f in fh_sorted])
fl_confirm_ts = np.array([f["confirm_ts"] for f in fl_sorted])


def active_fractal(sorted_list, sorted_ts, query_ts):
    """Last confirmed fractal whose confirm_ts <= query_ts."""
    if len(sorted_ts) == 0: return None
    idx = int(np.searchsorted(sorted_ts, query_ts, side='right')) - 1
    return sorted_list[idx] if idx >= 0 else None


def simulate_outcome(trade, max_close_ts):
    """Simulate trade from entry_ts looking forward up to max_close_ts or MAX_HOLD."""
    sk = idx_at(trade["entry_ts"])
    ek = min(sk + MAX_HOLD_MIN, len(data), idx_at(max_close_ts))
    side = trade["side"]
    entry = trade["entry"]; sl = trade["sl"]; tp = trade["tp"]
    for k in range(sk, ek):
        h_ = hi_arr[k]; l_ = lo_arr[k]
        if side == "long":
            if l_ <= sl:
                return {"exit_ts": int(ts_arr[k]), "exit_price": sl,
                        "outcome": "loss", "pnl_R": -1.0,
                        "hold_min": int(ts_arr[k] - trade["entry_ts"]) // 60_000}
            if h_ >= tp:
                return {"exit_ts": int(ts_arr[k]), "exit_price": tp,
                        "outcome": "win", "pnl_R": RR,
                        "hold_min": int(ts_arr[k] - trade["entry_ts"]) // 60_000}
        else:
            if h_ >= sl:
                return {"exit_ts": int(ts_arr[k]), "exit_price": sl,
                        "outcome": "loss", "pnl_R": -1.0,
                        "hold_min": int(ts_arr[k] - trade["entry_ts"]) // 60_000}
            if l_ <= tp:
                return {"exit_ts": int(ts_arr[k]), "exit_price": tp,
                        "outcome": "win", "pnl_R": RR,
                        "hold_min": int(ts_arr[k] - trade["entry_ts"]) // 60_000}
    return None


crossover_count = {"bull": 0, "bear": 0, "skipped_no_pair": 0}

for bi in range(bars_4h_idx_start, len(bars_4h) - 1):  # exclude last possibly forming
    b_open, _, _, _, _, _ = bars_4h[bi]
    bar_close_ts = b_open + TF_4H_MS  # inclusive end

    # Active fractals as of bar close
    fh = active_fractal(fh_sorted, fh_confirm_ts, bar_close_ts)
    fl = active_fractal(fl_sorted, fl_confirm_ts, bar_close_ts)
    if fh is None or fl is None:
        crossover_count["skipped_no_pair"] += 1
        prev_state = None
        continue

    v_fh = anchored_vwap_at(fh["anchor_ts"], bar_close_ts - 60_000)  # last 1m closed
    v_fl = anchored_vwap_at(fl["anchor_ts"], bar_close_ts - 60_000)
    if v_fh is None or v_fl is None:
        prev_state = None
        continue

    cur_state = "BULL" if v_fl > v_fh else "BEAR"

    # Manage open trade
    if open_trade is not None:
        # check regime flip
        if REGIME_EXIT and cur_state != prev_state and prev_state is not None:
            # close at current bar close
            close_price = bars_4h[bi][4]  # close of current 4h bar
            # compute outcome from price path inside trade
            outcome = simulate_outcome(open_trade, bar_close_ts)
            if outcome is None:
                # forced close at this price
                exit_price = close_price
                pnl_R = ((exit_price - open_trade["entry"]) / open_trade["r_unit"]
                         if open_trade["side"] == "long" else
                         (open_trade["entry"] - exit_price) / open_trade["r_unit"])
                trade_done = {**open_trade, "exit_ts": bar_close_ts,
                              "exit_price": exit_price, "outcome": "regime_exit",
                              "pnl_R": pnl_R}
            else:
                trade_done = {**open_trade, **outcome}
            trades.append(trade_done)
            open_trade = None

    # Detect crossover
    if prev_state is not None and cur_state != prev_state and open_trade is None:
        side = "long" if cur_state == "BULL" else "short"
        entry = bars_4h[bi][4]  # close of cross 4h bar
        # SL = opposite VWAP at the cross moment
        sl = v_fh if side == "long" else v_fl
        if side == "long":
            if entry <= sl:
                prev_state = cur_state
                continue
            r_unit = entry - sl
            tp = entry + RR * r_unit
        else:
            if entry >= sl:
                prev_state = cur_state
                continue
            r_unit = sl - entry
            tp = entry - RR * r_unit

        open_trade = {
            "entry_ts": bar_close_ts, "side": side,
            "entry": entry, "sl": sl, "tp": tp, "r_unit": r_unit,
            "fh_anchor": fh["anchor_ts"], "fl_anchor": fl["anchor_ts"],
        }
        crossover_count["bull" if side == "long" else "bear"] += 1

    prev_state = cur_state


# При завершении — закрываем open trade
if open_trade is not None:
    outcome = simulate_outcome(open_trade, int(ts_arr[-1]))
    if outcome is not None:
        trades.append({**open_trade, **outcome})

# Финальный exit для regime-flipped trades, у которых не было outcome
# (уже учтены выше как regime_exit)

print(f"  Crossovers: bull={crossover_count['bull']}, bear={crossover_count['bear']}")
print(f"  Trades closed: {len(trades)}")
print(f"  Backtest time: {time.time()-t0:.1f}s")


# === Stats ===
def stat(rs):
    w = sum(1 for r in rs if r["outcome"] == "win")
    l = sum(1 for r in rs if r["outcome"] == "loss")
    re = sum(1 for r in rs if r["outcome"] == "regime_exit")
    n = w + l + re  # all decided trades
    wr = w / (w + l) * 100 if (w + l) > 0 else 0
    sr = sum(r["pnl_R"] for r in rs)
    return n, w, l, re, wr, sr


def bk(name, rs):
    n, w, l, re, wr, sr = stat(rs)
    rtr = sr / n if n else 0
    print(f"  {name:<48} n={n:>4}  W={w:>3}  L={l:>3}  RegExit={re:>3}  "
          f"WR(W/W+L)={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


print("\n" + "=" * 96)
print(f" Stratagy stats (RR={RR}, regime_exit={REGIME_EXIT})")
print("=" * 96)
bk("ALL trades", trades)
bk("LONG", [t for t in trades if t["side"] == "long"])
bk("SHORT", [t for t in trades if t["side"] == "short"])

print("\n--- Per-year ---")
year_groups = {}
for t in trades:
    y = datetime.fromtimestamp(t["entry_ts"] / 1000, tz=timezone.utc).year
    year_groups.setdefault(y, []).append(t)
for y in sorted(year_groups):
    bk(f"{y}", year_groups[y])

print("\n--- Hold duration ---")
holds = [t.get("hold_min", 0) for t in trades if "hold_min" in t]
if holds:
    print(f"  median hold: {sorted(holds)[len(holds)//2]/60:.1f}h, "
          f"mean: {sum(holds)/len(holds)/60:.1f}h, max: {max(holds)/60:.1f}h")

# Equity curve
trades_sorted = sorted(trades, key=lambda t: t["entry_ts"])
eq = 0; peak = 0; mdd = 0
for t in trades_sorted:
    eq += t["pnl_R"]
    if eq > peak: peak = eq
    if peak - eq > mdd: mdd = peak - eq
print(f"\n  Final equity: {eq:+.1f}R  Peak: {peak:+.1f}R  MDD: {mdd:.1f}R  MDD/Eq: {mdd/eq:.3f}" if eq > 0 else f"\n  Equity: {eq:+.1f}R")

# Save trades
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/vwap_cross_4h_trades.csv"
with OUT.open('w', newline='') as f:
    w = csv.writer(f)
    cols = ["entry_ts", "exit_ts", "side", "entry", "sl", "tp", "exit_price",
            "r_unit", "outcome", "pnl_R"]
    w.writerow(cols)
    for t in trades:
        w.writerow([t.get(c, "") for c in cols])
print(f"\nSaved → {OUT}")
print(f"Total: {time.time()-t0:.1f}s")
