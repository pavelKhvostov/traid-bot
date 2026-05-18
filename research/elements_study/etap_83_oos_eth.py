"""Этап 83: OOS тест всех утверждённых стратегий на ETHUSDT.

Тестируем 4 семейства (9 конфигов):
  1. Strategy 1.1.1 (entry=0.80, sl=0.35 sym, RR=2.2, SWEPT ON, no_entry ON)
  2. Strategy 1.1.2 (entry=0.70, sl=0.35 sym, RR=2.2, SWEPT OFF)
  3. Strategy 1.1.4 BFJK portfolio + SHORT-only sub-variant
  4. Strategy 1.1.5 hi-freq (Fractal-12h + sweep + Hull-1h filter)

Ограничение: ETH 1m данные начинаются с 2023-04-26 (~3 года).
Для честного сравнения BTC тоже прогоняется за тот же 3-летний период.

Output: side-by-side BTC vs ETH table per strategy.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

import importlib.util
_spec74 = importlib.util.spec_from_file_location(
    "etap74_core", str(_Path(__file__).parent / "etap_74_114_fixed_BFJK.py"))
_e74 = importlib.util.module_from_spec(_spec74); _spec74.loader.exec_module(_e74)
_spec76 = importlib.util.spec_from_file_location(
    "etap76_core", str(_Path(__file__).parent / "etap_76_115_fractal_chains_survey.py"))
_e76 = importlib.util.module_from_spec(_spec76); _spec76.loader.exec_module(_e76)
_spec77 = importlib.util.spec_from_file_location(
    "etap77_core", str(_Path(__file__).parent / "etap_77_115_fractal_tightened.py"))
_e77 = importlib.util.module_from_spec(_spec77); _spec77.loader.exec_module(_e77)
_spec67 = importlib.util.spec_from_file_location(
    "etap67_core", str(_Path(__file__).parent / "etap_67_114_filter_grid_BF.py"))
_e67 = importlib.util.module_from_spec(_spec67); _spec67.loader.exec_module(_e67)
_e66 = _e74._e66

_e66.TF_HOURS["20m"] = 20/60
_e66.LIFE_DAYS["20m"] = 0.5

# OOS window: ETH 1m data starts 2023-04-26
START_DATE = "2023-05-01"  # round up slightly for clean ATR warmup


# ============== Strategy 1.1.1 ==============

def check_swept(sig, df_1h, df_2h):
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2:
        return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[prev_idx]["low"]); c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx - 1]["low"]); n2l = float(df_top.iloc[prev_idx - 2]["low"])
    n1h = float(df_top.iloc[prev_idx - 1]["high"]); n2h = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def run_strategy_111(symbol, df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m,
                     entry_pct=0.80, sl_pct=0.35, rr=2.2):
    """1.1.1: SWEPT ON, no_entry ON."""
    raw = detect_strategy_1_1_1_signals(
        df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False)
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept(s, df_1h, df_2h)
        if sw is None: continue
        groups[key].append({"sig": s, "swept": sw})
    swept_reps = [next(p["sig"] for p in paths if p["swept"])
                   for key, paths in groups.items() if any(p["swept"] for p in paths)]

    wins = losses = nf = no_entry = opens = skipped = 0
    pnl_r = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])  # [wins, losses, pnl]

    for s in swept_reps:
        fvg_b, fvg_t = s["fvg_zone"]
        obh_b, obh_t = s["ob_htf_zone"]
        direction = s["direction"]
        tf_minutes = 15 if s["fvg_tf"] == "15m" else 20
        forward = df_1m[df_1m.index >= s["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
        if forward.empty: nf += 1; continue
        fw = fvg_t - fvg_b
        if direction == "LONG":
            entry = fvg_b + entry_pct * fw
            sl_lo = obh_b; sl_hi = fvg_b
            sl = sl_lo + sl_pct * (sl_hi - sl_lo)
            if sl >= entry: skipped += 1; continue
            risk = entry - sl
            tp = entry + rr * risk
        else:
            entry = fvg_t - entry_pct * fw
            sl_hi = obh_t; sl_lo = fvg_t
            sl = sl_hi - sl_pct * (sl_hi - sl_lo)
            if sl <= entry: skipped += 1; continue
            risk = sl - entry
            tp = entry - rr * risk

        highs = forward["high"].values.astype(np.float64)
        lows = forward["low"].values.astype(np.float64)
        n = len(highs)
        if direction == "LONG":
            ent_idxs = np.where(lows <= entry)[0]
            tp_pre = np.where(highs >= tp)[0]
        else:
            ent_idxs = np.where(highs >= entry)[0]
            tp_pre = np.where(lows <= tp)[0]
        ent_idx = int(ent_idxs[0]) if ent_idxs.size else n + 1
        tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
        year = s["signal_time"].year
        if tp_pre_i < ent_idx: no_entry += 1; continue
        if ent_idx >= n: nf += 1; continue
        post_l = lows[ent_idx:]; post_h = highs[ent_idx:]
        if direction == "LONG":
            sl_m = post_l <= sl; tp_m = post_h >= tp
        else:
            sl_m = post_h >= sl; tp_m = post_l <= tp
        sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
        tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
        if sl_first == -1 and tp_first == -1: opens += 1; continue
        if sl_first == -1 or (tp_first != -1 and tp_first < sl_first):
            wins += 1; pnl_r += rr
            yearly[year][0] += 1; yearly[year][2] += rr
        else:
            losses += 1; pnl_r -= 1.0
            yearly[year][1] += 1; yearly[year][2] -= 1.0

    closed = wins + losses
    return {"n": closed, "wins": wins, "losses": losses, "no_entry": no_entry,
             "wr": wins/closed*100 if closed else 0, "total": pnl_r,
             "avg": pnl_r/closed if closed else 0,
             "yearly": dict(yearly)}


def run_strategy_112(symbol, df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m,
                     entry_pct=0.70, sl_pct=0.35, rr=2.2):
    """1.1.2: NO SWEPT filter, no_entry ON."""
    raw = detect_strategy_1_1_2_signals(
        df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False)

    # Dedup by (signal_time, direction, entry rounded)
    seen = set(); reps = []
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        if key in seen: continue
        seen.add(key); reps.append(s)

    wins = losses = nf = no_entry = opens = skipped = 0
    pnl_r = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])

    for s in reps:
        fvg_b, fvg_t = s["fvg_zone"]
        obh_b, obh_t = s["ob_htf_zone"]
        direction = s["direction"]
        tf_minutes = 15 if s["fvg_tf"] == "15m" else 20
        forward = df_1m[df_1m.index >= s["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
        if forward.empty: nf += 1; continue
        fw = fvg_t - fvg_b
        if direction == "LONG":
            entry = fvg_b + entry_pct * fw
            sl = obh_b + sl_pct * (fvg_b - obh_b)
            if sl >= entry: skipped += 1; continue
            risk = entry - sl
            tp = entry + rr * risk
        else:
            entry = fvg_t - entry_pct * fw
            sl = obh_t - sl_pct * (obh_t - fvg_t)
            if sl <= entry: skipped += 1; continue
            risk = sl - entry
            tp = entry - rr * risk

        highs = forward["high"].values.astype(np.float64)
        lows = forward["low"].values.astype(np.float64)
        n = len(highs)
        if direction == "LONG":
            ent_idxs = np.where(lows <= entry)[0]
            tp_pre = np.where(highs >= tp)[0]
        else:
            ent_idxs = np.where(highs >= entry)[0]
            tp_pre = np.where(lows <= tp)[0]
        ent_idx = int(ent_idxs[0]) if ent_idxs.size else n + 1
        tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
        year = s["signal_time"].year
        if tp_pre_i < ent_idx: no_entry += 1; continue
        if ent_idx >= n: nf += 1; continue
        post_l = lows[ent_idx:]; post_h = highs[ent_idx:]
        if direction == "LONG":
            sl_m = post_l <= sl; tp_m = post_h >= tp
        else:
            sl_m = post_h >= sl; tp_m = post_l <= tp
        sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
        tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
        if sl_first == -1 and tp_first == -1: opens += 1; continue
        if sl_first == -1 or (tp_first != -1 and tp_first < sl_first):
            wins += 1; pnl_r += rr
            yearly[year][0] += 1; yearly[year][2] += rr
        else:
            losses += 1; pnl_r -= 1.0
            yearly[year][1] += 1; yearly[year][2] -= 1.0

    closed = wins + losses
    return {"n": closed, "wins": wins, "losses": losses, "no_entry": no_entry,
             "wr": wins/closed*100 if closed else 0, "total": pnl_r,
             "avg": pnl_r/closed if closed else 0,
             "yearly": dict(yearly)}


# ============== Strategy 1.1.4 ==============

def run_strategy_114(symbol, df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m,
                      rr=2.0, allow_multi=5, short_only=False):
    """1.1.4 BFJK portfolio using etap_74 fixed detector."""
    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h), ("4h", df_4h),
                    ("2h", df_2h), ("1h", df_1h), ("15m", df_15m), ("20m", df_20m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")

    chains = {
        "B": (fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h),
        "F": (fvgs_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m", df_1d),
        "J": (fvgs_1d, obs_4h, obs_1h, fvgs_20m, "1d", "4h", "1h", "20m", df_1d),
        "K": (fvgs_12h, obs_4h, obs_1h, fvgs_20m, "12h", "4h", "1h", "20m", df_12h),
    }
    raw_setups = []
    for name, args in chains.items():
        s = _e74.detect_fixed(*args, allow_multi=allow_multi)
        for ss in s: ss["chain"] = name
        raw_setups.extend(s)

    seen = {}
    for s in raw_setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k not in seen:
            seen[k] = {**s, "chains": [s["chain"]]}
        else:
            if s["chain"] not in seen[k]["chains"]:
                seen[k]["chains"].append(s["chain"])
    setups = list(seen.values())

    if short_only:
        setups = [s for s in setups if s["direction"] == "SHORT"]

    wins = losses = no_entry = nf = opens = 0
    pnl_r = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])

    for s in setups:
        tup = _e66.build_orders(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
        year = s["signal_time"].year
        if outcome == "win":
            wins += 1; pnl_r += R
            yearly[year][0] += 1; yearly[year][2] += R
        elif outcome == "loss":
            losses += 1; pnl_r += R
            yearly[year][1] += 1; yearly[year][2] += R
        elif outcome == "no_entry": no_entry += 1
        elif outcome == "open": opens += 1
        else: nf += 1

    closed = wins + losses
    return {"n": closed, "wins": wins, "losses": losses, "no_entry": no_entry,
             "wr": wins/closed*100 if closed else 0, "total": pnl_r,
             "avg": pnl_r/closed if closed else 0,
             "yearly": dict(yearly)}


# ============== Strategy 1.1.5 ==============

def run_strategy_115(symbol, df_1d, df_12h, df_4h, df_1h, df_15m, df_1m,
                      rr=2.0):
    """1.1.5 hi-freq: B5 strict + hull_1h_L49 aligned filter."""
    for tf, df in [("1d", df_1d), ("12h", df_12h), ("4h", df_4h),
                    ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    hull_1h = _e67.hull_ma(df_1h["close"], 49)
    hull_lbl = _e67.hull_label_series(df_1h["close"], hull_1h)

    fractals_12h = _e76.collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")

    setups = _e77.detect_strict(fractals_12h, obs_4h, obs_1h, fvgs_15m,
                                  "12h", "4h", "1h", "15m",
                                  allow_multi=3, proximity_atr=1.0,
                                  min_sweep_depth_atr=0.0)
    # Apply Hull-1h filter
    filtered = []
    for s in setups:
        lbl = _e67.safe_label_at(hull_lbl, s["signal_time"])
        if _e67.hull_align(lbl, s["direction"]) == "aligned":
            filtered.append(s)

    wins = losses = no_entry = nf = opens = 0
    pnl_r = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])

    for s in filtered:
        tup = _e76.build_orders_fractal(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
        year = s["signal_time"].year
        if outcome == "win":
            wins += 1; pnl_r += R
            yearly[year][0] += 1; yearly[year][2] += R
        elif outcome == "loss":
            losses += 1; pnl_r += R
            yearly[year][1] += 1; yearly[year][2] += R
        elif outcome == "no_entry": no_entry += 1
        elif outcome == "open": opens += 1

    closed = wins + losses
    return {"n": closed, "wins": wins, "losses": losses, "no_entry": no_entry,
             "wr": wins/closed*100 if closed else 0, "total": pnl_r,
             "avg": pnl_r/closed if closed else 0,
             "yearly": dict(yearly)}


def load_all(symbol, start_date):
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(symbol, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    cutoff = pd.Timestamp(start_date, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    return df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m


def fmt_result(r, label):
    yr_str = ""
    if r["yearly"]:
        yr_lines = []
        for yr in sorted(r["yearly"].keys()):
            w, l, p = r["yearly"][yr]
            n = w + l
            wr = w/n*100 if n else 0
            yr_lines.append(f"    {yr}: n={n} WR={wr:.1f}% R={p:+.1f}")
        yr_str = "\n" + "\n".join(yr_lines)
    return (f"  {label:<20} n={r['n']:>3} WR={r['wr']:5.1f}% "
            f"total={r['total']:+6.1f}R avg={r['avg']:+5.2f}R"
            f"{yr_str}")


def main():
    t0 = time.time()
    print(f"[INFO] OOS test on ETHUSDT vs BTCUSDT (same window from {START_DATE})")
    print(f"[NOTE] ETH 1m data starts 2023-04-26, so window = ~3 years (not 6)")

    print(f"\n[INFO] loading data...")
    btc = load_all("BTCUSDT", START_DATE)
    eth = load_all("ETHUSDT", START_DATE)
    print(f"  BTC: 1d={len(btc[0])}, 1h={len(btc[4])}, 1m={len(btc[8])}")
    print(f"  ETH: 1d={len(eth[0])}, 1h={len(eth[4])}, 1m={len(eth[8])}")

    results = {}

    # ========== Strategy 1.1.1 ==========
    print(f"\n{'='*78}\n1.1.1 (entry=0.80, sl=0.35 sym, RR=2.2, SWEPT ON, no_entry ON)")
    print(f"{'='*78}")
    print(f"\n[BTC]")
    r_btc_111 = run_strategy_111("BTCUSDT", *btc)
    print(fmt_result(r_btc_111, "BTC 1.1.1"))
    print(f"\n[ETH]")
    r_eth_111 = run_strategy_111("ETHUSDT", *eth)
    print(fmt_result(r_eth_111, "ETH 1.1.1"))
    results["1.1.1"] = (r_btc_111, r_eth_111)

    # ========== Strategy 1.1.2 ==========
    print(f"\n{'='*78}\n1.1.2 (entry=0.70, sl=0.35 sym, RR=2.2, NO SWEPT)")
    print(f"{'='*78}")
    print(f"\n[BTC]")
    r_btc_112 = run_strategy_112("BTCUSDT", *btc)
    print(fmt_result(r_btc_112, "BTC 1.1.2"))
    print(f"\n[ETH]")
    r_eth_112 = run_strategy_112("ETHUSDT", *eth)
    print(fmt_result(r_eth_112, "ETH 1.1.2"))
    results["1.1.2"] = (r_btc_112, r_eth_112)

    # ========== Strategy 1.1.4 BFJK Portfolio ==========
    print(f"\n{'='*78}\n1.1.4 BFJK Portfolio (entry=0.70 asym, RR=2.0, allow_multi=5)")
    print(f"{'='*78}")
    print(f"\n[BTC]")
    r_btc_114 = run_strategy_114("BTCUSDT", *btc)
    print(fmt_result(r_btc_114, "BTC 1.1.4 BFJK"))
    print(f"\n[ETH]")
    r_eth_114 = run_strategy_114("ETHUSDT", *eth)
    print(fmt_result(r_eth_114, "ETH 1.1.4 BFJK"))
    results["1.1.4"] = (r_btc_114, r_eth_114)

    # ========== Strategy 1.1.4 SHORT-only ==========
    print(f"\n{'='*78}\n1.1.4 SHORT-only sub-variant")
    print(f"{'='*78}")
    print(f"\n[BTC]")
    r_btc_114s = run_strategy_114("BTCUSDT", *btc, short_only=True)
    print(fmt_result(r_btc_114s, "BTC 1.1.4 SHORT"))
    print(f"\n[ETH]")
    r_eth_114s = run_strategy_114("ETHUSDT", *eth, short_only=True)
    print(fmt_result(r_eth_114s, "ETH 1.1.4 SHORT"))
    results["1.1.4_short"] = (r_btc_114s, r_eth_114s)

    # ========== Strategy 1.1.5 hi-freq ==========
    print(f"\n{'='*78}\n1.1.5 hi-freq (Fractal-12h+sweep+Hull-1h, RR=2.0, AM=3, prox=1xATR)")
    print(f"{'='*78}")
    btc_115_args = (btc[0], btc[1], btc[2], btc[4], btc[6], btc[8])
    eth_115_args = (eth[0], eth[1], eth[2], eth[4], eth[6], eth[8])
    print(f"\n[BTC]")
    r_btc_115 = run_strategy_115("BTCUSDT", *btc_115_args)
    print(fmt_result(r_btc_115, "BTC 1.1.5"))
    print(f"\n[ETH]")
    r_eth_115 = run_strategy_115("ETHUSDT", *eth_115_args)
    print(fmt_result(r_eth_115, "ETH 1.1.5"))
    results["1.1.5"] = (r_btc_115, r_eth_115)

    # ========== FINAL COMPARISON ==========
    print(f"\n\n{'='*100}")
    print(f"FINAL: BTC vs ETH ({START_DATE} -> 2026-04, ~3 years)")
    print(f"{'='*100}")
    print(f"  {'Strategy':<22} {'BTC n':>6} {'BTC WR':>8} {'BTC R':>8} {'BTC avg':>9} "
          f"{'ETH n':>6} {'ETH WR':>8} {'ETH R':>8} {'ETH avg':>9} {'verdict':>10}")
    for name, (rb, re) in results.items():
        verdict = "BOTH OK" if rb["total"] > 0 and re["total"] > 0 else \
                   "BTC ONLY" if rb["total"] > 0 else \
                   "ETH ONLY" if re["total"] > 0 else "BOTH BAD"
        print(f"  {name:<22} {rb['n']:>6} {rb['wr']:>7.1f}% {rb['total']:>+7.1f}R "
              f"{rb['avg']:>+8.2f}R "
              f"{re['n']:>6} {re['wr']:>7.1f}% {re['total']:>+7.1f}R "
              f"{re['avg']:>+8.2f}R {verdict:>10}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
