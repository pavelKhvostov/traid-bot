"""etap_101: audit +313R BTC results from etap_100.

Проверяет 3 потенциальных источника инфляции:
  1. Instant entry vs realistic limit fill (etap_42 модель не ждёт прикосновения
     цены к entry — limit-ордер в реальности может вообще не заполниться)
  2. Multi-shot duplicates — разные macro-зоны могут производить ту же
     (signal_time, direction, entry); retry удваивает их
  3. Lookahead audit — проверка что детектор и SWEPT используют только
     прошлые данные относительно момента сигнала

Запускает 3 модели исполнения для baseline и retry на BTC 6.34y:
  - instant: trade fires at entry_time, walk 1m for SL/TP (etap_42 M0)
  - limit:   wait for entry price touch within max_hold, then SL/TP race
  - market:  enter at signal_close price (close of entry FVG bar), then SL/TP
             on real entry (= signal_close), real SL/TP scaled to risk
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

_E100 = Path(__file__).parent / "etap_100_retry_111_e42_params.py"
_spec2 = _ilu.spec_from_file_location("etap100_core", _E100)
_e100 = _ilu.module_from_spec(_spec2); _sys.modules["etap100_core"] = _e100
_spec2.loader.exec_module(_e100)
build_setup = _e100.build_setup

ENTRY_PCT = 0.80
SL_PCT = 0.40
MIN_SL_PCT = 1.0
RR = 2.5
MAX_HOLD_DAYS = 7
DAYS_BACK_TARGET = 2313
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def simulate_instant(sig, df_1m, rr=RR, max_hold_days=MAX_HOLD_DAYS):
    """etap_42 М0: trade fires at entry_time, no fill wait."""
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
    entry_time = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = entry_time + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_time.tz_localize(None) if entry_time.tz else entry_time)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return ("no_data", 0.0, None, entry, sl, tp)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    ts = df_1m.index.values[i0:i1]
    if direction == "LONG":
        sl_hits = l <= sl; tp_hits = h >= tp
    else:
        sl_hits = h >= sl; tp_hits = l <= tp
    sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h)
    tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h)
    if sl_idx == len(h) and tp_idx == len(h):
        return ("open", 0.0, None, entry, sl, tp)
    if sl_idx <= tp_idx:
        return ("loss", -1.0, pd.Timestamp(ts[sl_idx]).tz_localize("UTC"), entry, sl, tp)
    return ("win", rr, pd.Timestamp(ts[tp_idx]).tz_localize("UTC"), entry, sl, tp)


def simulate_limit(sig, df_1m, rr=RR, max_hold_days=MAX_HOLD_DAYS):
    """Realistic limit-fill: wait for price to touch entry within max_hold.
    Если касание не наступило за max_hold — not_filled.
    Если цена пробила SL без касания entry (gap) — not_filled (limit не заполнился).
    После заполнения SL/TP race forward."""
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
    activation_time = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = activation_time + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(activation_time.tz_localize(None) if activation_time.tz else activation_time)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return ("no_data", 0.0, None, entry, sl, tp)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    ts = df_1m.index.values[i0:i1]
    n = len(h)
    # find first touch of entry
    if direction == "LONG":
        touch = np.where(l <= entry)[0]
    else:
        touch = np.where(h >= entry)[0]
    if touch.size == 0:
        return ("not_filled", 0.0, None, entry, sl, tp)
    fill_i = int(touch[0])
    # после fill — SL/TP race
    post_h = h[fill_i:]; post_l = l[fill_i:]
    post_ts = ts[fill_i:]
    if direction == "LONG":
        sl_hits = post_l <= sl; tp_hits = post_h >= tp
    else:
        sl_hits = post_h >= sl; tp_hits = post_l <= tp
    sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(post_h)
    tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(post_h)
    if sl_idx == len(post_h) and tp_idx == len(post_h):
        return ("open", 0.0, None, entry, sl, tp)
    if sl_idx <= tp_idx:
        return ("loss", -1.0, pd.Timestamp(post_ts[sl_idx]).tz_localize("UTC"), entry, sl, tp)
    return ("win", rr, pd.Timestamp(post_ts[tp_idx]).tz_localize("UTC"), entry, sl, tp)


def simulate_market(sig, df_1m, rr=RR, max_hold_days=MAX_HOLD_DAYS):
    """Market entry: вход по close цене бара signal_close (= entry_time =
    signal_time + tf_min). SL/TP сохраняем как в плане (entry/sl/tp computed
    by build_setup), но с MARKET fill цена может быть очень далека от entry.
    Risk = |market_fill - sl|. TP = market_fill ± rr*risk."""
    setup = build_setup(sig)
    if setup is None:
        return ("invalid", 0.0, None, None, None, None)
    plan_entry, plan_sl = setup
    direction = sig["direction"]
    tf_min = 15 if sig["fvg_tf"] == "15m" else 20
    fill_time = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = fill_time + pd.Timedelta(days=max_hold_days)
    ft64 = np.datetime64(fill_time.tz_localize(None) if fill_time.tz else fill_time)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, ft64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return ("no_data", 0.0, None, plan_entry, plan_sl, None)
    # market fill = close of i0 bar (1m bar at fill_time)
    # use close of LAST 1m bar BEFORE fill_time (already-closed price)
    if i0 == 0:
        return ("no_data", 0.0, None, plan_entry, plan_sl, None)
    market_fill = float(df_1m["close"].values[i0 - 1])
    # риск пересчитываем от market_fill до plan_sl
    if direction == "LONG":
        if market_fill <= plan_sl:
            return ("invalid_market", 0.0, None, market_fill, plan_sl, None)
        risk = market_fill - plan_sl
        tp = market_fill + rr * risk
    else:
        if market_fill >= plan_sl:
            return ("invalid_market", 0.0, None, market_fill, plan_sl, None)
        risk = plan_sl - market_fill
        tp = market_fill - rr * risk
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    ts = df_1m.index.values[i0:i1]
    if direction == "LONG":
        sl_hits = l <= plan_sl; tp_hits = h >= tp
    else:
        sl_hits = h >= plan_sl; tp_hits = l <= tp
    sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h)
    tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h)
    if sl_idx == len(h) and tp_idx == len(h):
        return ("open", 0.0, None, market_fill, plan_sl, tp)
    if sl_idx <= tp_idx:
        return ("loss", -1.0, pd.Timestamp(ts[sl_idx]).tz_localize("UTC"), market_fill, plan_sl, tp)
    return ("win", rr, pd.Timestamp(ts[tp_idx]).tz_localize("UTC"), market_fill, plan_sl, tp)


SIMULATORS = {
    "instant": simulate_instant,
    "limit":   simulate_limit,
    "market":  simulate_market,
}


def run(groups, df_1m, df_1h, df_2h, mode: str, simulator):
    trades = []
    for gid, gsigs in groups.items():
        gsigs_sorted = sorted(gsigs, key=lambda x: x["fvg_c2_time"])
        first = gsigs_sorted[0]
        if check_swept(first, df_1h, df_2h) is not True:
            continue
        if mode == "baseline":
            outcome, R, exit_t, e_v, sl_v, tp_v = simulator(first, df_1m)
            trades.append({**first, "outcome": outcome, "R": R, "exit_time": exit_t,
                           "trade_idx_in_zone": 0, "entry_v": e_v, "sl_v": sl_v, "tp_v": tp_v})
            continue
        prev_sl_time = None
        for idx, s in enumerate(gsigs_sorted):
            if idx > 0 and check_swept(s, df_1h, df_2h) is not True:
                continue
            tf_min = 15 if s["fvg_tf"] == "15m" else 20
            entry_t = s["signal_time"] + pd.Timedelta(minutes=tf_min)
            if prev_sl_time is not None and entry_t <= prev_sl_time:
                continue
            outcome, R, exit_t, e_v, sl_v, tp_v = simulator(s, df_1m)
            trades.append({**s, "outcome": outcome, "R": R, "exit_time": exit_t,
                           "trade_idx_in_zone": idx, "entry_v": e_v, "sl_v": sl_v, "tp_v": tp_v})
            if outcome == "loss":
                prev_sl_time = exit_t; continue
            else:
                break
    return trades


def summarize(trades, label):
    closed = [t for t in trades if t["outcome"] in ("win", "loss")]
    W = sum(1 for t in closed if t["outcome"] == "win")
    L = sum(1 for t in closed if t["outcome"] == "loss")
    n = W + L
    wr = (W/n*100) if n else 0
    pnl = sum(t["R"] for t in closed)
    nf = sum(1 for t in trades if t["outcome"] == "not_filled")
    op = sum(1 for t in trades if t["outcome"] == "open")
    inv = sum(1 for t in trades if t["outcome"].startswith("invalid"))
    nd = sum(1 for t in trades if t["outcome"] == "no_data")
    print(f"  {label:<30}: total={len(trades):4d}  closed={n:4d}  W={W:3d} L={L:3d}  "
          f"WR={wr:5.1f}%  PnL={pnl:+7.1f}R  nf={nf} open={op} inv={inv} nd={nd}")
    return {"n": n, "W": W, "L": L, "wr": wr, "pnl": pnl, "trades": trades}


def dedup_trades(trades):
    """Дедуп по (signal_time, direction, round(entry_v, 2)).
    Берём первый трейд на ключ (одинаковый исход у одинаковых сетапов)."""
    dedup_map: dict = {}
    for t in trades:
        if t.get("entry_v") is None:
            continue
        key = (t["signal_time"], t["direction"], round(float(t["entry_v"]), 2))
        if key not in dedup_map:
            dedup_map[key] = t
    return list(dedup_map.values())


def audit_symbol(symbol: str):
    print(f"\n{'#'*72}\n#  {symbol}\n{'#'*72}")
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m, df_1m)):
        print(f"  [SKIP] empty data")
        return None
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = max(today - pd.Timedelta(days=DAYS_BACK_TARGET), df_1m.index[0])
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]
    actual_days = (today-cutoff).days
    print(f"  cutoff: {cutoff.date()} ({actual_days}d = {actual_days/365:.2f}y)")

    groups = detect_multi_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                    df_1h, df_2h, df_15m, df_20m)
    print(f"  zones={len(groups)}")

    results = {}
    print(f"\n  --- raw (без дедупа) ---")
    for sim_name, simulator in SIMULATORS.items():
        for mode in ["baseline", "retry"]:
            label = f"{sim_name:<7} {mode}"
            trs = run(groups, df_1m, df_1h, df_2h, mode, simulator)
            summary = summarize(trs, label)
            results[(sim_name, mode)] = summary

    print(f"\n  --- DEDUP (по signal_time, direction, entry) ---")
    dedup_results = {}
    for (sim_name, mode), summary in results.items():
        trs = summary["trades"]
        dedup_trs = dedup_trades(trs)
        label = f"{sim_name:<7} {mode} DEDUP"
        ds = summarize(dedup_trs, label)
        dedup_results[(sim_name, mode)] = ds

    return {"symbol": symbol, "years": actual_days/365,
            "zones": len(groups), "raw": results, "dedup": dedup_results}


def main():
    print(f"etap_101: audit. SYMBOLS={SYMBOLS}, days={DAYS_BACK_TARGET}")
    print(f"params: entry={ENTRY_PCT} sl={SL_PCT} MIN_SL={MIN_SL_PCT}% RR={RR} max_hold={MAX_HOLD_DAYS}d")

    all_results = []
    for sym in SYMBOLS:
        r = audit_symbol(sym)
        if r is not None:
            all_results.append(r)

    print()
    print("=" * 88)
    print("SUMMARY: realistic (limit+dedup) is the live-tradeable estimate")
    print("=" * 88)
    hdr = f"{'sym':<8} {'yrs':>5} {'mode':<10} | {'instant':>26} | {'limit':>26} | {'market':>26}"
    print(hdr); print("-" * len(hdr))
    for r in all_results:
        for mode in ["baseline", "retry"]:
            cells = []
            for sim_name in ["instant", "limit", "market"]:
                d = r["dedup"][(sim_name, mode)]
                cells.append(f"{d['n']:3d}t {d['wr']:5.1f}% {d['pnl']:+8.1f}R")
            print(f"{r['symbol']:<8} {r['years']:>5.2f} {mode:<10} | "
                  f"{cells[0]:>26} | {cells[1]:>26} | {cells[2]:>26}")

    print()
    print("DELTA retry vs baseline (по реалистичной модели limit+dedup):")
    print("-" * 60)
    for r in all_results:
        b = r["dedup"][("limit", "baseline")]
        rt = r["dedup"][("limit", "retry")]
        print(f"  {r['symbol']}  baseline={b['pnl']:+6.1f}R  retry={rt['pnl']:+6.1f}R  "
              f"delta={rt['pnl']-b['pnl']:+6.1f}R  ({rt['n']-b['n']:+d} trades)")


if __name__ == "__main__":
    main()
