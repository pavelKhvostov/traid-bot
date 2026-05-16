"""etap_102: ЧИСТЫЙ audit 1.1.1 maximum — все улучшения, реалистично, дедуп.

Параметры LIVE-approved 1.1.1:
  entry = 0.80
  sl    = 0.35 sym (без MIN_SL_PCT)
  RR    = 2.2
  SWEPT = ON
  Simulator = limit-fill + no_entry filter (как в etap_99, etap_85, stage3)

Применяет дедуп по (signal_time, direction, round(entry, 2)) чтобы убрать
multi-shot duplicate inflation. Считает:
  - baseline = первая SWEPT-пара зоны
  - retry    = chain after SL within zone (только если зона ещё валидна)

Прогон на 6y для BTC, ETH, SOL (теперь все три имеют 6y 1m данные).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu

_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E98 = Path(__file__).parent / "etap_98_retry_after_sl_111.py"
_spec = _ilu.spec_from_file_location("etap98_core", _E98)
_e98 = _ilu.module_from_spec(_spec); _sys.modules["etap98_core"] = _e98
_spec.loader.exec_module(_e98)
detect_multi_signals = _e98.detect_multi_signals
check_swept = _e98.check_swept

# LIVE-approved params — как в текущей продакшен 1.1.1
ENTRY_PCT = 0.80
SL_PCT = 0.35
RR = 2.2
DAYS_BACK_TARGET = 2313
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def build_setup(sig):
    """LIVE формула: entry=80%, sl=35% sym (без MIN_SL_PCT)."""
    direction = sig["direction"]
    fb, ft = sig["fvg_zone"]
    obb, obt = sig["ob_htf_zone"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl = obb + SL_PCT * (fb - obb)
        if sl >= entry:
            return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl = obt - SL_PCT * (obt - ft)
        if sl <= entry:
            return None
    return float(entry), float(sl)


def simulate_limit(sig, df_1m, rr=RR):
    """Realistic limit-fill: ждём касания entry, no_entry filter (TP до entry → отмена).
    Возвращает (outcome, R, exit_time, entry, sl, tp)."""
    setup = build_setup(sig)
    if setup is None:
        return ("invalid", 0.0, None, None, None, None)
    entry, sl = setup
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0:
        return ("invalid", 0.0, None, entry, sl, None)
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    tf_min = 15 if sig["fvg_tf"] == "15m" else 20
    fill_start = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    forward = df_1m[df_1m.index >= fill_start]
    if forward.empty:
        return ("nf", 0.0, None, entry, sl, tp)
    h = forward["high"].values.astype(np.float64)
    l = forward["low"].values.astype(np.float64)
    ts = forward.index
    n = len(h)
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre_idxs = np.where(h >= tp)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre_idxs = np.where(l <= tp)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    if tp_pre_i < ent_i:
        return ("no_entry", 0.0, (ts[tp_pre_i] if tp_pre_i < n else None), entry, sl, tp)
    if ent_i >= n:
        return ("nf", 0.0, None, entry, sl, tp)
    post_l = l[ent_i:]; post_h = h[ent_i:]
    post_ts = ts[ent_i:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1:
        return ("open", 0.0, None, entry, sl, tp)
    if sl_f == -1:
        return ("win", rr, post_ts[tp_f], entry, sl, tp)
    if tp_f == -1:
        return ("loss", -1.0, post_ts[sl_f], entry, sl, tp)
    if tp_f < sl_f:
        return ("win", rr, post_ts[tp_f], entry, sl, tp)
    return ("loss", -1.0, post_ts[sl_f], entry, sl, tp)


def run_baseline(groups, df_1m, df_1h, df_2h):
    trades = []
    for gid, gsigs in groups.items():
        gsigs_sorted = sorted(gsigs, key=lambda x: x["fvg_c2_time"])
        first = gsigs_sorted[0]
        if check_swept(first, df_1h, df_2h) is not True:
            continue
        outcome, R, exit_t, e_v, sl_v, tp_v = simulate_limit(first, df_1m)
        trades.append({**first, "outcome": outcome, "R": R, "exit_time": exit_t,
                       "trade_idx": 0, "entry_v": e_v, "sl_v": sl_v, "tp_v": tp_v})
    return trades


def run_retry(groups, df_1m, df_1h, df_2h):
    trades = []
    for gid, gsigs in groups.items():
        gsigs_sorted = sorted(gsigs, key=lambda x: x["fvg_c2_time"])
        first = gsigs_sorted[0]
        if check_swept(first, df_1h, df_2h) is not True:
            continue
        prev_sl_time = None
        for idx, s in enumerate(gsigs_sorted):
            if idx > 0 and check_swept(s, df_1h, df_2h) is not True:
                continue
            tf_min = 15 if s["fvg_tf"] == "15m" else 20
            entry_t = s["signal_time"] + pd.Timedelta(minutes=tf_min)
            if prev_sl_time is not None and entry_t <= prev_sl_time:
                continue
            outcome, R, exit_t, e_v, sl_v, tp_v = simulate_limit(s, df_1m)
            trades.append({**s, "outcome": outcome, "R": R, "exit_time": exit_t,
                           "trade_idx": idx, "entry_v": e_v, "sl_v": sl_v, "tp_v": tp_v})
            if outcome == "loss":
                prev_sl_time = exit_t
                continue
            else:
                break
    return trades


def dedup(trades):
    """Дедуп по (signal_time, direction, round(entry, 2))."""
    seen = {}
    for t in trades:
        if t.get("entry_v") is None:
            continue
        key = (t["signal_time"], t["direction"], round(float(t["entry_v"]), 2))
        if key not in seen:
            seen[key] = t
    return list(seen.values())


def summarize(trades, label):
    closed = [t for t in trades if t["outcome"] in ("win", "loss")]
    W = sum(1 for t in closed if t["outcome"] == "win")
    L = sum(1 for t in closed if t["outcome"] == "loss")
    n = W + L
    wr = W/n*100 if n else 0
    pnl = sum(t["R"] for t in closed)
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for t in closed:
        y = pd.Timestamp(t["signal_time"]).year
        yearly[y][0 if t["outcome"] == "win" else 1] += 1
        yearly[y][2] += t["R"]
    bad = sum(1 for y in yearly if yearly[y][2] < 0)
    return {"n": n, "W": W, "L": L, "wr": wr, "pnl": pnl, "bad": bad,
             "yearly": dict(yearly), "label": label,
             "ne": sum(1 for t in trades if t["outcome"] == "no_entry"),
             "nf": sum(1 for t in trades if t["outcome"] == "nf"),
             "open": sum(1 for t in trades if t["outcome"] == "open")}


def run_symbol(symbol):
    print(f"\n{'#'*72}\n#  {symbol}\n{'#'*72}")
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m, df_1m)):
        return None
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = max(today - pd.Timedelta(days=DAYS_BACK_TARGET), df_1m.index[0])
    actual_days = (today-cutoff).days
    print(f"  cutoff: {cutoff.date()} ({actual_days}d = {actual_days/365:.2f}y)")
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    groups = detect_multi_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                    df_1h, df_2h, df_15m, df_20m)
    print(f"  zones={len(groups)}")

    baseline = run_baseline(groups, df_1m, df_1h, df_2h)
    retry = run_retry(groups, df_1m, df_1h, df_2h)
    b_dedup = dedup(baseline); r_dedup = dedup(retry)

    print(f"\n  raw baseline: {len(baseline)} trades, dedup: {len(b_dedup)} ({len(baseline)-len(b_dedup)} dup схлопнуто)")
    print(f"  raw retry:    {len(retry)} trades, dedup: {len(r_dedup)} ({len(retry)-len(r_dedup)} dup схлопнуто)")

    s_b = summarize(b_dedup, f"{symbol} baseline DEDUP")
    s_r = summarize(r_dedup, f"{symbol} retry DEDUP")

    print(f"\n  {'metric':<14} {'baseline':>12} {'retry':>12}  {'delta':>10}")
    print(f"  {'closed':<14} {s_b['n']:>12d} {s_r['n']:>12d}  {s_r['n']-s_b['n']:>+10d}")
    bwl = f"{s_b['W']}/{s_b['L']}"; rwl = f"{s_r['W']}/{s_r['L']}"
    print(f"  {'W/L':<14} {bwl:>12} {rwl:>12}")
    print(f"  {'WR %':<14} {s_b['wr']:>12.1f} {s_r['wr']:>12.1f}  {s_r['wr']-s_b['wr']:>+10.1f}")
    print(f"  {'PnL R':<14} {s_b['pnl']:>+12.1f} {s_r['pnl']:>+12.1f}  {s_r['pnl']-s_b['pnl']:>+10.1f}")
    print(f"  {'bad years':<14} {s_b['bad']:>12d} {s_r['bad']:>12d}  {s_r['bad']-s_b['bad']:>+10d}")
    print(f"  {'no_entry':<14} {s_b['ne']:>12d} {s_r['ne']:>12d}")
    print(f"  {'nf':<14} {s_b['nf']:>12d} {s_r['nf']:>12d}")

    print(f"\n  По годам:")
    all_y = sorted(set(s_b['yearly']) | set(s_r['yearly']))
    for y in all_y:
        bW, bL, bp = s_b['yearly'].get(y, [0,0,0])
        rW, rL, rp = s_r['yearly'].get(y, [0,0,0])
        bwr = bW/(bW+bL)*100 if (bW+bL) else 0
        rwr = rW/(rW+rL)*100 if (rW+rL) else 0
        print(f"    {y}: baseline n={bW+bL:3d} WR={bwr:5.1f}% PnL={bp:+6.1f}R  |  "
              f"retry n={rW+rL:3d} WR={rwr:5.1f}% PnL={rp:+6.1f}R  d={rp-bp:+5.1f}R")

    return {"symbol": symbol, "years": actual_days/365,
             "baseline": s_b, "retry": s_r}


def main():
    print(f"etap_102: 1.1.1 CLEAN max audit. LIVE params (entry={ENTRY_PCT}, sl={SL_PCT} sym, RR={RR}, SWEPT)")
    print(f"Simulator: limit-fill + no_entry filter. Multi-shot detector + dedup.")
    print(f"Target {DAYS_BACK_TARGET}d (6.34y)")

    results = []
    for sym in SYMBOLS:
        r = run_symbol(sym)
        if r is not None:
            results.append(r)

    print()
    print("=" * 88)
    print("ИТОГ: 1.1.1 с retry-after-SL, REALISTIC limit-fill, дедуп multi-shot")
    print("=" * 88)
    print(f"{'sym':<8} {'years':>5} {'mode':<10} {'n':>4} {'WR':>6} {'PnL':>9} {'R/y':>7} {'bad':>4}")
    print("-" * 64)
    total_b_pnl = 0; total_r_pnl = 0
    total_b_n = 0; total_r_n = 0
    for r in results:
        b = r["baseline"]; rt = r["retry"]
        print(f"{r['symbol']:<8} {r['years']:>5.2f} {'baseline':<10} "
              f"{b['n']:>4d} {b['wr']:>5.1f}% {b['pnl']:>+8.1f}R {b['pnl']/r['years']:>+6.1f} {b['bad']:>4d}")
        print(f"{'':<8} {'':>5} {'retry':<10} "
              f"{rt['n']:>4d} {rt['wr']:>5.1f}% {rt['pnl']:>+8.1f}R {rt['pnl']/r['years']:>+6.1f} {rt['bad']:>4d}")
        print(f"{'':<8} {'':>5} {'  delta':<10} "
              f"{rt['n']-b['n']:>+4d} {rt['wr']-b['wr']:>+5.1f}pp {rt['pnl']-b['pnl']:>+8.1f}R")
        print()
        total_b_pnl += b['pnl']; total_r_pnl += rt['pnl']
        total_b_n += b['n']; total_r_n += rt['n']

    print("-" * 64)
    print(f"TOTAL across BTC + ETH + SOL:")
    print(f"  baseline: n={total_b_n}  PnL={total_b_pnl:+.1f}R")
    print(f"  retry:    n={total_r_n}  PnL={total_r_pnl:+.1f}R")
    print(f"  delta:    {total_r_n-total_b_n:+d} trades  {total_r_pnl-total_b_pnl:+.1f}R")


if __name__ == "__main__":
    main()
