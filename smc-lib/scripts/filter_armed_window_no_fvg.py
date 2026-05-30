"""Фильтр: armed window не должен взаимодействовать с unmitigated 4h/6h FVG.

Применяется к 506 trades (F1 ∪ F2). Удаляем те, у которых ARMED window
(от C5 close до fill) хоть какой-то 1m свечой касается активного 4h/6h FVG.

Активный FVG = сформирован до начала armed window AND ещё не митигирован
к началу armed window.
"""
from __future__ import annotations

import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from elements.fvg.code import detect_fvg

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_HOUR = 3600_000
MAX_HOLD_MIN = 30 * 24 * 60
HTF_LIST = [("4h", 4 * MS_HOUR), ("6h", 6 * MS_HOUR), ("8h", 8 * MS_HOUR),
            ("12h", 12 * MS_HOUR), ("1D", 24 * MS_HOUR)]
FVG_TFS = [("4h", 4 * MS_HOUR), ("6h", 6 * MS_HOUR)]


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

htf_candles = {name: aggregate(data, ms // 60_000) for name, ms in HTF_LIST}


# HTF OBs / RDRBs (для F1∪F2 filter)
htf_obs = {}; htf_rdrbs = {}
for name, cs in htf_candles.items():
    tf_ms = next(ms for n, ms in HTF_LIST if n == name)
    obs = []; rdrbs = []
    for i in range(len(cs) - 1):
        c, nxt = cs[i], cs[i + 1]
        if c.close < c.open and nxt.close > c.high:
            obs.append({"dir": "long", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
        elif c.close > c.open and nxt.close < c.low:
            obs.append({"dir": "short", "open_ts": c.open_time, "end_ts": c.open_time + tf_ms})
    htf_obs[name] = obs
    for i in range(len(cs) - 2):
        r = detect_rdrb(cs[i], cs[i + 1], cs[i + 2])
        if r is None: continue
        rdrbs.append({"dir": r.direction, "c1_ts": cs[i].open_time,
                      "c3_end_ts": cs[i + 2].open_time + tf_ms,
                      "window_end_ts": cs[i].open_time + 3 * tf_ms})
    htf_rdrbs[name] = rdrbs


# FVGs на 4h и 6h (все, с mitigation_ts)
fvg_pools = {}
for name, tf_ms in FVG_TFS:
    cs = htf_candles[name]
    fvgs = []
    for i in range(len(cs) - 2):
        c1, c3 = cs[i], cs[i + 2]
        # bullish
        if c1.high < c3.low:
            f = {"dir": "bull", "formed_ts": c3.open_time + tf_ms,
                 "top": c3.low, "bottom": c1.high, "tf": name}
            # mitigation: low <= top
            f["mit_ts"] = None
            for j in range(i + 3, len(cs)):
                if cs[j].low <= f["top"]: f["mit_ts"] = cs[j].open_time; break
            fvgs.append(f)
        # bearish
        elif c1.low > c3.high:
            f = {"dir": "bear", "formed_ts": c3.open_time + tf_ms,
                 "top": c1.low, "bottom": c3.high, "tf": name}
            f["mit_ts"] = None
            for j in range(i + 3, len(cs)):
                if cs[j].high >= f["bottom"]: f["mit_ts"] = cs[j].open_time; break
            fvgs.append(f)
    fvg_pools[name] = fvgs
    print(f"  {name}: {sum(1 for x in fvgs if x['dir']=='bull')} bull FVG, {sum(1 for x in fvgs if x['dir']=='bear')} bear FVG")


def idx_at(ms):
    lo, hi = 0, len(ts_1m)
    while lo < hi:
        m = (lo + hi) // 2
        if ts_1m[m] < ms: lo = m + 1
        else: hi = m
    return lo


def check_f1(pattern_candles, direction):
    for name, obs in htf_obs.items():
        for ob in obs:
            if ob["dir"] != direction: continue
            for c in pattern_candles:
                if ob["open_ts"] <= c.open_time < ob["end_ts"]: return True
    return False


def check_f2_same(pattern_candles, direction, fill_close_ms):
    htf_dir_target = "short" if direction == "long" else "long"
    for name, rdrbs in htf_rdrbs.items():
        for r in rdrbs:
            if r["dir"] != htf_dir_target: continue
            if r["c3_end_ts"] > fill_close_ms: continue
            for c in pattern_candles:
                if r["c1_ts"] <= c.open_time < r["window_end_ts"]: return True
    return False


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


def armed_window_touches_fvg(c5_close_ms, fill_ms, fvg_dirs=None):
    """Возвращает True если в armed window какая-то 1m свеча касается активного 4h/6h FVG."""
    if fill_ms is None: return False
    sk = idx_at(c5_close_ms); ek = idx_at(fill_ms) + 1
    if sk >= ek: return False
    for name, fvgs in fvg_pools.items():
        for f in fvgs:
            if fvg_dirs and f["dir"] not in fvg_dirs: continue
            if f["formed_ts"] > c5_close_ms: continue  # сформирован после начала armed window — пропускаем
            if f["mit_ts"] is not None and f["mit_ts"] <= c5_close_ms: continue  # уже митигирован
            top = f["top"]; bot = f["bottom"]
            # check overlap with any 1m bar in armed window
            for k in range(sk, ek):
                _, _, h_, l_, _, _ = data[k]
                if l_ <= top and h_ >= bot:
                    return True
    return False


# Pattern detection
patterns = []
for i in range(len(candles_1h) - 4):
    c1, c2, c3, c4, c5 = candles_1h[i:i + 5]
    ir = detect_i_rdrb(c1, c2, c3, c4)
    if ir is None: continue
    fvg = detect_fvg(c3, c4, c5)
    if fvg is None or fvg.direction != ir.direction: continue
    patterns.append((ir, c5))


# F1 ∪ F2 filter set + armed-window FVG check
print(f"\n{len(patterns)} total i-RDRB+FVG patterns")

filtered_506 = []  # passes F1∪F2
for ir, c5 in patterns:
    side = ir.direction
    block_b, block_t = ir.rdrb.block
    entry = (block_b + block_t) / 2
    all5 = [ir.rdrb.c1, ir.rdrb.c2, ir.rdrb.c3, ir.c4, c5]
    sl = min(c.low for c in all5) if side == "long" else max(c.high for c in all5)
    r_unit = abs(entry - sl)
    if r_unit <= 0: continue
    tp = entry + r_unit if side == "long" else entry - r_unit
    c5_close_ms = c5.open_time + MS_HOUR

    out, fill_ms = simulate(side, entry, sl, tp, c5_close_ms)
    if out not in ("win", "loss"): continue

    fill_close_ms = (fill_ms or c5_close_ms) + MS_HOUR
    f1 = check_f1(all5, side)
    f2 = check_f2_same(all5, side, fill_close_ms)
    if not (f1 or f2): continue
    filtered_506.append({"side": side, "entry": entry, "sl": sl, "tp": tp,
                          "c5_close_ms": c5_close_ms, "fill_ms": fill_ms, "outcome": out, "r_unit": r_unit})

print(f"F1 ∪ F2 filtered: {len(filtered_506)}\n")


def report(name, items):
    n = len(items)
    if n == 0: print(f"  {name:<60} n=0"); return
    w = sum(1 for x in items if x["outcome"] == "win")
    r = w - (n - w)
    wr = w / n * 100
    print(f"  {name:<60} n={n:<5} W={w:<4} L={n-w:<4} WR={wr:5.2f}%  ΣR={r:+5d}  R/tr={r/n:+.3f}")


print("=== Фильтр armed-window ===")
# Базовый 506
report("F1 ∪ F2 (baseline reference)", filtered_506)

# Удаляем те, у которых armed window касается ANY 4h/6h FVG
no_any_fvg = []
no_bull_only = []  # без bullish FVG
no_bear_only = []  # без bearish FVG
for t in filtered_506:
    touch_any = armed_window_touches_fvg(t["c5_close_ms"], t["fill_ms"])
    touch_bull = armed_window_touches_fvg(t["c5_close_ms"], t["fill_ms"], fvg_dirs={"bull"})
    touch_bear = armed_window_touches_fvg(t["c5_close_ms"], t["fill_ms"], fvg_dirs={"bear"})
    if not touch_any: no_any_fvg.append(t)
    if not touch_bull: no_bull_only.append(t)
    if not touch_bear: no_bear_only.append(t)

report("После: NO 4h/6h FVG (any dir) interaction в armed window", no_any_fvg)
report("После: NO bullish 4h/6h FVG interaction", no_bull_only)
report("После: NO bearish 4h/6h FVG interaction", no_bear_only)

# Также противоположный фильтр (для контекста)
yes_any = [t for t in filtered_506 if t not in no_any_fvg]
report("ОБРАТНОЕ: ЕСТЬ 4h/6h FVG interaction (anti-set)", yes_any)

# Также проверим on RR sweep по best filter
print("\n=== TP sweep на NO-FVG subset (RR 1.0/1.4/2.0/2.5/2.9) ===")
for rr_target in (1.0, 1.4, 2.0, 2.5, 2.9):
    n_w = 0; n_l = 0; total_r = 0.0
    for t in no_any_fvg:
        new_tp = t["entry"] + rr_target * t["r_unit"] if t["side"] == "long" else t["entry"] - rr_target * t["r_unit"]
        out2, _ = simulate(t["side"], t["entry"], t["sl"], new_tp, t["c5_close_ms"])
        if out2 == "win": n_w += 1; total_r += rr_target
        elif out2 == "loss": n_l += 1; total_r -= 1
    n = n_w + n_l
    if n:
        wr = n_w / n * 100
        print(f"  RR={rr_target}  n={n}  WR={wr:5.2f}%  ΣR={total_r:+.1f}  R/tr={total_r/n:+.3f}")
