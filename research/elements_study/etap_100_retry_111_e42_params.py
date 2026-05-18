"""etap_100: retry-after-SL для 1.1.1 с etap_42 параметрами (M0 baseline).

Цель: ответ на вопрос пользователя "вспомни как +168R" — воспроизвести
M0 Fixed RR=2.5 baseline и проверить retry поверх него.

Параметры (как в etap_42 / etap_41):
  ENTRY_PCT  = 0.80
  SL_PCT     = 0.40   (vs 0.35 в etap_99)
  MIN_SL_PCT = 1.0    (минимальное расстояние entry-SL 1% от entry)
  RR         = 2.5    (vs 2.2 в etap_99)
  Instant entry @ signal_time + tf_minutes (без no_entry filter)
  MAX_HOLD   = 7 дней (open после)

Reference target BTC 6.33y: 210 SWEPT setups, WR 51.4%, +168R, R/tr +0.800, 0/7 bad.
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

# импорт detect_multi_signals и check_swept из etap_98
_E98_PATH = Path(__file__).parent / "etap_98_retry_after_sl_111.py"
_spec = _ilu.spec_from_file_location("etap98_core", _E98_PATH)
_e98 = _ilu.module_from_spec(_spec)
_sys.modules["etap98_core"] = _e98
_spec.loader.exec_module(_e98)
detect_multi_signals = _e98.detect_multi_signals
check_swept = _e98.check_swept

# --- параметры etap_42 ---
ENTRY_PCT = 0.80
SL_PCT = 0.40
MIN_SL_PCT = 1.0
RR = 2.5
MAX_HOLD_DAYS = 7

DAYS_BACK_TARGET = 2313  # 6.33y как в etap_42
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def build_setup(sig):
    """etap_42-style: ENTRY/SL c MIN_SL_PCT защитой."""
    direction = sig["direction"]
    fb, ft = sig["fvg_zone"]
    obb, obt = sig["ob_htf_zone"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl = obb + SL_PCT * (fb - obb)
        if MIN_SL_PCT > 0:
            min_sl_dist = entry * MIN_SL_PCT / 100
            sl = min(sl, entry - min_sl_dist)
        if sl >= entry:
            return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl = obt - SL_PCT * (obt - ft)
        if MIN_SL_PCT > 0:
            min_sl_dist = entry * MIN_SL_PCT / 100
            sl = max(sl, entry + min_sl_dist)
        if sl <= entry:
            return None
    return float(entry), float(sl)


def simulate_fixed_rr(sig, df_1m, rr=RR, max_hold_days=MAX_HOLD_DAYS):
    """M0 simulation: instant entry @ entry_time = signal_time + tf_minutes.
    Возвращает (outcome, R, exit_time)."""
    setup = build_setup(sig)
    if setup is None:
        return ("invalid", 0.0, None, None, None, None)
    entry, sl = setup
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0:
        return ("invalid", 0.0, None, entry, sl, None)
    tp = entry + rr * risk if direction == "LONG" else entry - rr * risk

    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    entry_time = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    end_time = entry_time + pd.Timedelta(days=max_hold_days)

    if entry_time.tz is None:
        et64 = np.datetime64(entry_time)
    else:
        et64 = np.datetime64(entry_time.tz_localize(None))
    if end_time.tz is None:
        ee64 = np.datetime64(end_time)
    else:
        ee64 = np.datetime64(end_time.tz_localize(None))

    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return ("no_data", 0.0, None, entry, sl, tp)

    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    ts = df_1m.index.values[i0:i1]

    if direction == "LONG":
        sl_hits = l <= sl
        tp_hits = h >= tp
    else:
        sl_hits = h >= sl
        tp_hits = l <= tp

    sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h)
    tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h)

    if sl_idx == len(h) and tp_idx == len(h):
        return ("open", 0.0, None, entry, sl, tp)
    if sl_idx <= tp_idx:
        return ("loss", -1.0, pd.Timestamp(ts[sl_idx]).tz_localize("UTC"), entry, sl, tp)
    return ("win", rr, pd.Timestamp(ts[tp_idx]).tz_localize("UTC"), entry, sl, tp)


def run_experiment(groups, df_1m, df_1h, df_2h, mode: str):
    """Three modes:
      'etap42_strict': dedup по (signal_time, direction, round(entry,2)) +
                       any-swept (как etap_42). Reference for ~+168R BTC.
      'baseline':      multi-shot per-zone, первая пара зоны должна быть SWEPT.
      'retry':         baseline + chain after SL within zone.
    """
    trades = []

    if mode == "etap42_strict":
        # plate all signals across all zones, then dedupe by (time, dir, entry)
        all_sigs = []
        for gsigs in groups.values():
            all_sigs.extend(gsigs)
        # dedup key
        dedup: dict[tuple, list[dict]] = {}
        for s in all_sigs:
            sw = check_swept(s, df_1h, df_2h)
            if sw is None:
                continue
            entry_setup = build_setup(s)
            if entry_setup is None:
                continue
            entry_v, _ = entry_setup
            key = (s["signal_time"], s["direction"], round(entry_v, 2))
            dedup.setdefault(key, []).append({"sig": s, "swept": sw})
        # take any SWEPT variant per key (как в etap_42)
        for key, paths in dedup.items():
            swept_paths = [p["sig"] for p in paths if p["swept"]]
            if not swept_paths:
                continue
            s = swept_paths[0]
            outcome, R, exit_t, entry_v, sl_v, tp_v = simulate_fixed_rr(s, df_1m)
            trades.append({**s, "outcome": outcome, "R": R, "exit_time": exit_t,
                            "trade_idx_in_zone": 0, "entry_v": entry_v,
                            "sl_v": sl_v, "tp_v": tp_v, "n_in_zone_total": 1,
                            "dedup_paths": len(paths)})
        return trades

    # baseline / retry modes — на уровне macro-зон (multi-shot framework)
    for gid, gsigs in groups.items():
        gsigs_sorted = sorted(gsigs, key=lambda x: x["fvg_c2_time"])
        first = gsigs_sorted[0]
        if check_swept(first, df_1h, df_2h) is not True:
            continue

        if mode == "baseline":
            outcome, R, exit_t, entry_v, sl_v, tp_v = simulate_fixed_rr(first, df_1m)
            trades.append({**first, "outcome": outcome, "R": R, "exit_time": exit_t,
                            "trade_idx_in_zone": 0, "entry_v": entry_v,
                            "sl_v": sl_v, "tp_v": tp_v, "n_in_zone_total": len(gsigs_sorted)})
            continue

        # retry
        prev_sl_time = None
        for idx, s in enumerate(gsigs_sorted):
            if idx > 0 and check_swept(s, df_1h, df_2h) is not True:
                continue
            tf_min = 15 if s["fvg_tf"] == "15m" else 20
            entry_t = s["signal_time"] + pd.Timedelta(minutes=tf_min)
            if prev_sl_time is not None and entry_t <= prev_sl_time:
                continue
            outcome, R, exit_t, entry_v, sl_v, tp_v = simulate_fixed_rr(s, df_1m)
            trades.append({**s, "outcome": outcome, "R": R, "exit_time": exit_t,
                            "trade_idx_in_zone": idx, "entry_v": entry_v,
                            "sl_v": sl_v, "tp_v": tp_v, "n_in_zone_total": len(gsigs_sorted)})
            if outcome == "loss":
                prev_sl_time = exit_t
                continue
            else:
                break
    return trades


def summarize(trades):
    closed = [t for t in trades if t["outcome"] in ("win", "loss")]
    W = sum(1 for t in closed if t["outcome"] == "win")
    L = sum(1 for t in closed if t["outcome"] == "loss")
    n = W + L
    wr = (W / n * 100) if n else 0.0
    pnl = sum(t["R"] for t in closed)
    r_per = pnl / n if n else 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for t in closed:
        y = pd.Timestamp(t["signal_time"]).year
        yearly[y][0 if t["outcome"] == "win" else 1] += 1
        yearly[y][2] += t["R"]
    bad = sum(1 for y in yearly if yearly[y][2] < 0)
    return {
        "n": n, "W": W, "L": L, "wr": wr, "pnl": pnl, "r_per": r_per,
        "bad": bad, "yearly": dict(yearly),
        "open": sum(1 for t in trades if t["outcome"] == "open"),
        "invalid": sum(1 for t in trades if t["outcome"] == "invalid"),
        "no_data": sum(1 for t in trades if t["outcome"] == "no_data"),
    }


def run_symbol(symbol: str) -> dict:
    print(f"\n{'#'*72}\n#  {symbol}\n{'#'*72}")

    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m, df_1m)):
        print(f"  [SKIP]: пустые данные")
        return None
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_1m, "20m")

    today = pd.Timestamp.now(tz="UTC").normalize()
    target_cutoff = today - pd.Timedelta(days=DAYS_BACK_TARGET)
    data_start = df_1m.index[0]
    cutoff = max(target_cutoff, data_start)
    actual_days = (today - cutoff).days
    print(f"  target cutoff = {target_cutoff.date()}, 1m starts = {data_start.date()}")
    print(f"  effective cutoff = {cutoff.date()}  ({actual_days}d = {actual_days/365:.2f}y)")

    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    print(f"  detect multi-shot...")
    groups = detect_multi_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                    df_1h, df_2h, df_15m, df_20m)
    total_pairs = sum(len(g) for g in groups.values())
    multi_zones = sum(1 for g in groups.values() if len(g) > 1)
    swept_pass = sum(1 for g in groups.values() for s in g
                      if check_swept(s, df_1h, df_2h) is True)
    print(f"  zones={len(groups)}  pairs={total_pairs}  multi-zones={multi_zones}  swept_pairs={swept_pass}")

    print(f"  etap42_strict (dedup, для sanity check)...")
    strict = run_experiment(groups, df_1m, df_1h, df_2h, mode="etap42_strict")
    print(f"  baseline multi-shot...")
    baseline = run_experiment(groups, df_1m, df_1h, df_2h, mode="baseline")
    print(f"  retry...")
    retry = run_experiment(groups, df_1m, df_1h, df_2h, mode="retry")

    s = summarize(strict)
    b = summarize(baseline)
    r = summarize(retry)

    retry_only_closed = [t for t in retry
                          if t["trade_idx_in_zone"] > 0 and t["outcome"] in ("win", "loss")]
    rW = sum(1 for t in retry_only_closed if t["outcome"] == "win")
    rL = sum(1 for t in retry_only_closed if t["outcome"] == "loss")
    rn = rW + rL
    rwr = (rW / rn * 100) if rn else 0.0
    rpnl = sum(t["R"] for t in retry_only_closed)

    print(f"\n  {'metric':<12} {'e42_strict':>12} {'baseline_ms':>12} {'retry':>12}  {'delta':>10}")
    print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*12}  {'-'*10}")
    print(f"  {'closed':<12} {s['n']:>12d} {b['n']:>12d} {r['n']:>12d}  {r['n']-b['n']:>+10d}")
    swl = f"{s['W']}/{s['L']}"
    bwl = f"{b['W']}/{b['L']}"
    rwl = f"{r['W']}/{r['L']}"
    print(f"  {'W/L':<12} {swl:>12} {bwl:>12} {rwl:>12}")
    print(f"  {'WR %':<12} {s['wr']:>12.1f} {b['wr']:>12.1f} {r['wr']:>12.1f}  {r['wr']-b['wr']:>+10.1f}")
    print(f"  {'PnL R':<12} {s['pnl']:>+12.1f} {b['pnl']:>+12.1f} {r['pnl']:>+12.1f}  {r['pnl']-b['pnl']:>+10.1f}")
    print(f"  {'R/trade':<12} {s['r_per']:>+12.3f} {b['r_per']:>+12.3f} {r['r_per']:>+12.3f}  {r['r_per']-b['r_per']:>+10.3f}")
    print(f"  {'bad years':<12} {s['bad']:>12d} {b['bad']:>12d} {r['bad']:>12d}  {r['bad']-b['bad']:>+10d}")

    print(f"\n  retry-only trades (idx > 0): n={rn} W/L={rW}/{rL} WR={rwr:.1f}% PnL={rpnl:+.1f}R")

    print(f"\n  По годам (baseline -> retry):")
    all_years = sorted(set(list(b["yearly"].keys()) + list(r["yearly"].keys())))
    for y in all_years:
        bW, bL, bp = b["yearly"].get(y, [0, 0, 0.0])
        rW2, rL2, rp = r["yearly"].get(y, [0, 0, 0.0])
        bwr2 = bW / (bW + bL) * 100 if (bW + bL) else 0
        rwr2 = rW2 / (rW2 + rL2) * 100 if (rW2 + rL2) else 0
        print(f"    {y}: baseline n={bW+bL:3d} WR={bwr2:5.1f}% PnL={bp:+6.1f}R  |  "
              f"retry n={rW2+rL2:3d} WR={rwr2:5.1f}% PnL={rp:+6.1f}R  |  d={rp-bp:+5.1f}R")

    return {"symbol": symbol, "years": actual_days/365, "zones": len(groups),
            "pairs": total_pairs, "swept_pairs": swept_pass,
            "strict": s, "baseline": b, "retry": r,
            "retry_only": {"n": rn, "W": rW, "L": rL, "wr": rwr, "pnl": rpnl}}


def main():
    print(f"etap_100: 1.1.1 retry-after-SL c etap_42 параметрами (M0 Fixed RR=2.5)")
    print(f"params: entry={ENTRY_PCT} sl={SL_PCT} MIN_SL={MIN_SL_PCT}% RR={RR}  "
          f"max_hold={MAX_HOLD_DAYS}d, SWEPT ON, target {DAYS_BACK_TARGET}d (~6.33y)")
    print(f"reference: BTC 6.33y etap_42 M0 RR=2.5 = 210 setups, WR 51.4%, +168R, 0/7 bad")

    results = []
    for sym in SYMBOLS:
        r = run_symbol(sym)
        if r is not None:
            results.append(r)

    # сводка
    print(f"\n\n{'='*96}")
    print(f"СВОДКА  (etap_42 params: entry={ENTRY_PCT} sl={SL_PCT} MIN_SL={MIN_SL_PCT}% RR={RR} M0 fixed)")
    print(f"{'='*96}")
    print(f"{'sym':<8} {'years':>5} {'mode':<13} {'n':>4} {'WR':>6} {'PnL':>9} {'R/t':>7} {'bad':>4}")
    print("-" * 64)
    for r in results:
        s = r["strict"]; b = r["baseline"]; rt = r["retry"]
        print(f"{r['symbol']:<8} {r['years']:>5.2f} {'e42_strict':<13} "
              f"{s['n']:>4d} {s['wr']:>5.1f}% {s['pnl']:>+8.1f}R {s['r_per']:>+6.3f} {s['bad']:>4d}")
        print(f"{'':<8} {'':>5} {'baseline_ms':<13} "
              f"{b['n']:>4d} {b['wr']:>5.1f}% {b['pnl']:>+8.1f}R {b['r_per']:>+6.3f} {b['bad']:>4d}")
        print(f"{'':<8} {'':>5} {'retry':<13} "
              f"{rt['n']:>4d} {rt['wr']:>5.1f}% {rt['pnl']:>+8.1f}R {rt['r_per']:>+6.3f} {rt['bad']:>4d}")
        ro = r["retry_only"]
        print(f"{'':<8} {'':>5} {'  delta':<13} "
              f"{rt['n']-b['n']:>+4d} {rt['wr']-b['wr']:>+5.1f}pp {rt['pnl']-b['pnl']:>+8.1f}R")
        print(f"{'':<8} {'':>5} {'  retry-only':<13} "
              f"n={ro['n']} W/L={ro['W']}/{ro['L']} WR={ro['wr']:.1f}% PnL={ro['pnl']:+.1f}R")
        print()

    total_b = sum(r["baseline"]["pnl"] for r in results)
    total_r = sum(r["retry"]["pnl"] for r in results)
    total_bn = sum(r["baseline"]["n"] for r in results)
    total_rn = sum(r["retry"]["n"] for r in results)
    total_ro_pnl = sum(r["retry_only"]["pnl"] for r in results)
    total_ro_n = sum(r["retry_only"]["n"] for r in results)
    print("-" * 64)
    print(f"SUMS across symbols:")
    print(f"  baseline: n={total_bn}  PnL={total_b:+.1f}R")
    print(f"  retry:    n={total_rn}  PnL={total_r:+.1f}R")
    print(f"  delta:    {total_rn-total_bn:+d} trades  {total_r-total_b:+.1f}R")
    print(f"  retry-only: n={total_ro_n}  PnL={total_ro_pnl:+.1f}R")


if __name__ == "__main__":
    main()
