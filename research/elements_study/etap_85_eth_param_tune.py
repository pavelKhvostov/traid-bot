"""Этап 85: поиск ETH-specific параметров для слабых стратегий.

Из etap_83: на ETH слабы 1.1.1, 1.1.4 BFJK, 1.1.5 (1.1.2 универсальна).
Гипотеза: ETH требует других entry/SL/RR.

Grid (для каждой стратегии):
  entry_pct: [0.50, 0.60, 0.70, 0.80, 0.90]
  sl_pct: [0.25, 0.35, 0.45, 0.55]
  RR: [1.5, 1.8, 2.0, 2.5, 3.0]
  100 combos × 3 strategies × 2 symbols = 600 runs

Оптимизация: detected setups кешируем 1 раз per symbol/strategy,
варьируем только параметры построения ордера + симуляция.

Метрика отбора: total R > 0, n >= 30 (для статистической значимости),
sort by avg R/trade.

Параллельно тестируем BTC чтобы понять: ETH-specific params значит
лучше для ETH но потенциально хуже для BTC. Идеально - одни params
работают для обоих.
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

START_DATE = "2023-05-01"

# Grid
ENTRY_GRID = [0.50, 0.60, 0.70, 0.80, 0.90]
SL_GRID = [0.25, 0.35, 0.45, 0.55]
RR_GRID = [1.5, 1.8, 2.0, 2.5, 3.0]


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
    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m), ("20m", df_20m)]:
        df["atr14"] = _e66.compute_atr(df, 14)
    return {"1d": df_1d, "12h": df_12h, "6h": df_6h, "4h": df_4h, "2h": df_2h,
             "1h": df_1h, "15m": df_15m, "20m": df_20m, "1m": df_1m}


# ============ Cached setups ============

def cache_114_setups(dfs):
    """Detect 1.1.4 BFJK setups (4 chains, dedup). Params don't affect detection."""
    fvgs_1d = _e66.collect_fvgs(dfs["1d"], dfs["1d"]["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(dfs["12h"], dfs["12h"]["atr14"], "12h")
    obs_4h = _e66.collect_obs(dfs["4h"], dfs["4h"]["atr14"], "4h")
    obs_6h = _e66.collect_obs(dfs["6h"], dfs["6h"]["atr14"], "6h")
    obs_2h = _e66.collect_obs(dfs["2h"], dfs["2h"]["atr14"], "2h")
    obs_1h = _e66.collect_obs(dfs["1h"], dfs["1h"]["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(dfs["15m"], dfs["15m"]["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(dfs["20m"], dfs["20m"]["atr14"], "20m")

    chains = {
        "B": (fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", dfs["12h"]),
        "F": (fvgs_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m", dfs["1d"]),
        "J": (fvgs_1d, obs_4h, obs_1h, fvgs_20m, "1d", "4h", "1h", "20m", dfs["1d"]),
        "K": (fvgs_12h, obs_4h, obs_1h, fvgs_20m, "12h", "4h", "1h", "20m", dfs["12h"]),
    }
    raw = []
    for name, args in chains.items():
        s = _e74.detect_fixed(*args, allow_multi=5)
        for ss in s: ss["chain"] = name
        raw.extend(s)
    seen = {}
    for s in raw:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k not in seen: seen[k] = s
    return list(seen.values())


def cache_115_setups(dfs):
    """Detect 1.1.5 hi-freq with Hull-1h filter."""
    hull_1h = _e67.hull_ma(dfs["1h"]["close"], 49)
    hull_lbl = _e67.hull_label_series(dfs["1h"]["close"], hull_1h)
    fractals_12h = _e76.collect_fractals_with_sweep(dfs["12h"], dfs["12h"]["atr14"], "12h")
    obs_4h = _e66.collect_obs(dfs["4h"], dfs["4h"]["atr14"], "4h")
    obs_1h = _e66.collect_obs(dfs["1h"], dfs["1h"]["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(dfs["15m"], dfs["15m"]["atr14"], "15m")
    setups = _e77.detect_strict(fractals_12h, obs_4h, obs_1h, fvgs_15m,
                                  "12h", "4h", "1h", "15m",
                                  allow_multi=3, proximity_atr=1.0,
                                  min_sweep_depth_atr=0.0)
    filtered = []
    for s in setups:
        lbl = _e67.safe_label_at(hull_lbl, s["signal_time"])
        if _e67.hull_align(lbl, s["direction"]) == "aligned":
            filtered.append(s)
    return filtered


def cache_111_signals(dfs):
    """Detect 1.1.1 raw signals with SWEPT filter."""
    raw = detect_strategy_1_1_1_signals(
        dfs["1d"], dfs["12h"], dfs["4h"], dfs["6h"],
        dfs["1h"], dfs["2h"], dfs["15m"], dfs["20m"], verbose=False)
    # SWEPT filter
    swept = []
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept(s, dfs["1h"], dfs["2h"])
        if sw is None: continue
        groups[key].append({"sig": s, "swept": sw})
    for key, paths in groups.items():
        if any(p["swept"] for p in paths):
            swept.append(next(p["sig"] for p in paths if p["swept"]))
    return swept


def check_swept(sig, df_1h, df_2h):
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2: return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[prev_idx]["low"]); c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx-1]["low"]); n2l = float(df_top.iloc[prev_idx-2]["low"])
    n1h = float(df_top.iloc[prev_idx-1]["high"]); n2h = float(df_top.iloc[prev_idx-2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


# ============ Parametric simulate ============

def eval_114(setups, entry_pct, sl_L, sl_S, rr, df_1m, df_1d=None):
    """1.1.4: USER asymmetric SL (sl_L for LONG, sl_S for SHORT)."""
    wins = losses = ne = nf = opens = 0
    pnl_r = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for s in setups:
        direction = s["direction"]
        fb, ft = s["fvg_b"], s["fvg_t"]
        x1b, x1t = s["x1_bottom"], s["x1_top"]
        if direction == "LONG":
            entry = fb + entry_pct * (ft - fb)
            if x1b >= fb:
                obb = s["obh_b"]
                sl = obb + sl_L * (fb - obb)
            else:
                sl = x1b + sl_L * (fb - x1b)
            sl = min(sl, entry - entry * 0.01)  # min_sl 1%
            if sl >= entry: continue
        else:
            entry = ft - entry_pct * (ft - fb)
            if x1t <= ft:
                obt = s["obh_t"]
                sl = obt - sl_S * (obt - ft)
            else:
                sl = x1t - sl_S * (x1t - ft)
            sl = max(sl, entry + entry * 0.01)
            if sl <= entry: continue
        risk = abs(entry - sl)
        tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
        outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
        year = s["signal_time"].year
        if outcome == "win":
            wins += 1; pnl_r += R
            yearly[year][0] += 1; yearly[year][2] += R
        elif outcome == "loss":
            losses += 1; pnl_r += R
            yearly[year][1] += 1; yearly[year][2] += R
        elif outcome == "no_entry": ne += 1
    closed = wins + losses
    bad = sum(1 for yr, (w, l, p) in yearly.items() if p < 0)
    return {"n": closed, "wr": wins/closed*100 if closed else 0,
             "total": pnl_r, "avg": pnl_r/closed if closed else 0,
             "bad": bad, "n_yrs": len(yearly), "ne": ne}


def eval_115(setups, entry_pct, sl_L, sl_S, rr, df_1m):
    """1.1.5: USER-style asymmetric SL anchored to sweep extreme."""
    wins = losses = ne = nf = opens = 0
    pnl_r = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for s in setups:
        direction = s["direction"]
        fb, ft = s["fvg_b"], s["fvg_t"]
        sweep_ext = s["sweep_extreme"]
        if direction == "LONG":
            entry = fb + entry_pct * (ft - fb)
            sl_anchor = sweep_ext * (1 - 0.001)  # 0.1% buffer
            if sl_anchor < fb:
                sl = sl_anchor + sl_L * (fb - sl_anchor)
            else:
                obb = s["obh_b"]
                sl = obb + sl_L * (fb - obb) if obb < fb else fb * 0.99
            sl = min(sl, entry - entry * 0.01)
            if sl >= entry: continue
        else:
            entry = ft - entry_pct * (ft - fb)
            sl_anchor = sweep_ext * (1 + 0.001)
            if sl_anchor > ft:
                sl = sl_anchor - sl_S * (sl_anchor - ft)
            else:
                obt = s["obh_t"]
                sl = obt - sl_S * (obt - ft) if obt > ft else ft * 1.01
            sl = max(sl, entry + entry * 0.01)
            if sl <= entry: continue
        risk = abs(entry - sl)
        tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
        outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
        year = s["signal_time"].year
        if outcome == "win":
            wins += 1; pnl_r += R
            yearly[year][0] += 1; yearly[year][2] += R
        elif outcome == "loss":
            losses += 1; pnl_r += R
            yearly[year][1] += 1; yearly[year][2] += R
        elif outcome == "no_entry": ne += 1
    closed = wins + losses
    bad = sum(1 for yr, (w, l, p) in yearly.items() if p < 0)
    return {"n": closed, "wr": wins/closed*100 if closed else 0,
             "total": pnl_r, "avg": pnl_r/closed if closed else 0,
             "bad": bad, "n_yrs": len(yearly), "ne": ne}


def eval_111(signals, entry_pct, sl_pct, rr, df_1m):
    """1.1.1: SWEPT signals + symmetric sl_pct, no_entry on."""
    wins = losses = ne = nf = opens = 0
    pnl_r = 0.0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    for s in signals:
        fb, ft = s["fvg_zone"]
        obh_b, obh_t = s["ob_htf_zone"]
        direction = s["direction"]
        tf_minutes = 15 if s["fvg_tf"] == "15m" else 20
        forward = df_1m[df_1m.index >= s["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
        if forward.empty: continue
        fw = ft - fb
        if direction == "LONG":
            entry = fb + entry_pct * fw
            sl = obh_b + sl_pct * (fb - obh_b)
            if sl >= entry: continue
            risk = entry - sl; tp = entry + rr * risk
        else:
            entry = ft - entry_pct * fw
            sl = obh_t - sl_pct * (obh_t - ft)
            if sl <= entry: continue
            risk = sl - entry; tp = entry - rr * risk

        highs = forward["high"].values.astype(np.float64)
        lows = forward["low"].values.astype(np.float64)
        n = len(highs)
        if direction == "LONG":
            ent = np.where(lows <= entry)[0]
            tp_pre = np.where(highs >= tp)[0]
        else:
            ent = np.where(highs >= entry)[0]
            tp_pre = np.where(lows <= tp)[0]
        ent_i = int(ent[0]) if ent.size else n + 1
        tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
        year = s["signal_time"].year
        if tp_pre_i < ent_i: ne += 1; continue
        if ent_i >= n: nf += 1; continue
        post_l = lows[ent_i:]; post_h = highs[ent_i:]
        if direction == "LONG":
            sl_m = post_l <= sl; tp_m = post_h >= tp
        else:
            sl_m = post_h >= sl; tp_m = post_l <= tp
        sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
        tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
        if sl_f == -1 and tp_f == -1: opens += 1; continue
        if sl_f == -1 or (tp_f != -1 and tp_f < sl_f):
            wins += 1; pnl_r += rr
            yearly[year][0] += 1; yearly[year][2] += rr
        else:
            losses += 1; pnl_r -= 1.0
            yearly[year][1] += 1; yearly[year][2] -= 1.0
    closed = wins + losses
    bad = sum(1 for yr, (w, l, p) in yearly.items() if p < 0)
    return {"n": closed, "wr": wins/closed*100 if closed else 0,
             "total": pnl_r, "avg": pnl_r/closed if closed else 0,
             "bad": bad, "n_yrs": len(yearly), "ne": ne}


def grid_search_asymmetric(setups, df_1m, eval_fn, name):
    """USER-style asymmetric SL: separate sl_L, sl_S grids."""
    rows = []
    for entry_pct in ENTRY_GRID:
        for sl_L in SL_GRID:
            for sl_S in SL_GRID:
                for rr in RR_GRID:
                    m = eval_fn(setups, entry_pct, sl_L, sl_S, rr, df_1m)
                    if m["n"] < 20: continue
                    rows.append({"entry": entry_pct, "sl_L": sl_L, "sl_S": sl_S, "rr": rr, **m})
    return rows


def grid_search_symmetric(signals, df_1m, eval_fn, name):
    """Symmetric SL (one sl_pct for both directions)."""
    rows = []
    for entry_pct in ENTRY_GRID:
        for sl_pct in SL_GRID:
            for rr in RR_GRID:
                m = eval_fn(signals, entry_pct, sl_pct, rr, df_1m)
                if m["n"] < 20: continue
                rows.append({"entry": entry_pct, "sl": sl_pct, "rr": rr, **m})
    return rows


def main():
    t0 = time.time()
    print(f"[INFO] ETH param tune (apples-to-apples 3y window)")
    print(f"[INFO] grid: entry x sl x RR = {len(ENTRY_GRID)} x {len(SL_GRID)} x {len(RR_GRID)} = {len(ENTRY_GRID)*len(SL_GRID)*len(RR_GRID)} combos symmetric, x4 for asymmetric")

    btc = load_all("BTCUSDT", START_DATE)
    eth = load_all("ETHUSDT", START_DATE)

    print(f"\n[INFO] caching detected setups...")
    s114_btc = cache_114_setups(btc)
    s114_eth = cache_114_setups(eth)
    print(f"  1.1.4 BFJK: BTC={len(s114_btc)}, ETH={len(s114_eth)}")
    s115_btc = cache_115_setups(btc)
    s115_eth = cache_115_setups(eth)
    print(f"  1.1.5: BTC={len(s115_btc)}, ETH={len(s115_eth)}")
    s111_btc = cache_111_signals(btc)
    s111_eth = cache_111_signals(eth)
    print(f"  1.1.1 SWEPT: BTC={len(s111_btc)}, ETH={len(s111_eth)}")

    # ====== 1.1.4 grid ======
    print(f"\n{'='*88}\n1.1.4 BFJK grid (asymmetric SL)\n{'='*88}")
    rows_btc = grid_search_asymmetric(s114_btc, btc["1m"], eval_114, "1.1.4 BTC")
    rows_eth = grid_search_asymmetric(s114_eth, eth["1m"], eval_114, "1.1.4 ETH")
    print(f"  combos with n>=20: BTC={len(rows_btc)}, ETH={len(rows_eth)}")

    print(f"\n  TOP 10 by ETH total R (with positive BTC too):")
    eth_sorted = sorted(rows_eth, key=lambda x: x["total"], reverse=True)
    for r in eth_sorted[:10]:
        # Find matching BTC config
        btc_match = next((b for b in rows_btc if b["entry"]==r["entry"]
                           and b["sl_L"]==r["sl_L"] and b["sl_S"]==r["sl_S"]
                           and b["rr"]==r["rr"]), None)
        bt = "—" if not btc_match else f"BTC: n={btc_match['n']:>3} WR={btc_match['wr']:5.1f}% R={btc_match['total']:+6.1f}"
        print(f"    e={r['entry']:.2f} slL={r['sl_L']:.2f} slS={r['sl_S']:.2f} RR={r['rr']:.1f}: "
              f"ETH n={r['n']:>3} WR={r['wr']:5.1f}% R={r['total']:+6.1f} avg={r['avg']:+5.2f} bad={r['bad']}/{r['n_yrs']} | {bt}")

    print(f"\n  BASELINE (entry=0.70, slL=0.35, slS=0.65, RR=2.0):")
    base_eth = next((r for r in rows_eth if r["entry"]==0.70 and r["sl_L"]==0.35 and r["sl_S"]==0.55 and r["rr"]==2.0), None)
    if base_eth:
        print(f"    ETH: n={base_eth['n']} WR={base_eth['wr']:.1f}% R={base_eth['total']:+.1f}R avg={base_eth['avg']:+.2f}R bad={base_eth['bad']}/{base_eth['n_yrs']}")
    # closest match for sl_S=0.65 not in grid; using 0.55

    # ====== 1.1.5 grid ======
    print(f"\n{'='*88}\n1.1.5 hi-freq grid (asymmetric SL anchored to sweep)\n{'='*88}")
    rows_btc = grid_search_asymmetric(s115_btc, btc["1m"], eval_115, "1.1.5 BTC")
    rows_eth = grid_search_asymmetric(s115_eth, eth["1m"], eval_115, "1.1.5 ETH")
    print(f"  combos with n>=20: BTC={len(rows_btc)}, ETH={len(rows_eth)}")

    print(f"\n  TOP 10 by ETH total R (with matching BTC):")
    eth_sorted = sorted(rows_eth, key=lambda x: x["total"], reverse=True)
    for r in eth_sorted[:10]:
        btc_match = next((b for b in rows_btc if b["entry"]==r["entry"]
                           and b["sl_L"]==r["sl_L"] and b["sl_S"]==r["sl_S"]
                           and b["rr"]==r["rr"]), None)
        bt = "—" if not btc_match else f"BTC: n={btc_match['n']:>3} WR={btc_match['wr']:5.1f}% R={btc_match['total']:+6.1f}"
        print(f"    e={r['entry']:.2f} slL={r['sl_L']:.2f} slS={r['sl_S']:.2f} RR={r['rr']:.1f}: "
              f"ETH n={r['n']:>3} WR={r['wr']:5.1f}% R={r['total']:+6.1f} avg={r['avg']:+5.2f} bad={r['bad']}/{r['n_yrs']} | {bt}")

    # ====== 1.1.1 grid ======
    print(f"\n{'='*88}\n1.1.1 SWEPT grid (symmetric SL)\n{'='*88}")
    rows_btc = grid_search_symmetric(s111_btc, btc["1m"], eval_111, "1.1.1 BTC")
    rows_eth = grid_search_symmetric(s111_eth, eth["1m"], eval_111, "1.1.1 ETH")
    print(f"  combos with n>=20: BTC={len(rows_btc)}, ETH={len(rows_eth)}")

    print(f"\n  TOP 10 by ETH total R (with matching BTC):")
    eth_sorted = sorted(rows_eth, key=lambda x: x["total"], reverse=True)
    for r in eth_sorted[:10]:
        btc_match = next((b for b in rows_btc if b["entry"]==r["entry"]
                           and b["sl"]==r["sl"] and b["rr"]==r["rr"]), None)
        bt = "—" if not btc_match else f"BTC: n={btc_match['n']:>3} WR={btc_match['wr']:5.1f}% R={btc_match['total']:+6.1f}"
        print(f"    e={r['entry']:.2f} sl={r['sl']:.2f} RR={r['rr']:.1f}: "
              f"ETH n={r['n']:>3} WR={r['wr']:5.1f}% R={r['total']:+6.1f} avg={r['avg']:+5.2f} bad={r['bad']}/{r['n_yrs']} | {bt}")

    # ====== Best config working on BOTH ======
    print(f"\n\n{'='*100}")
    print(f"DUAL-ASSET CANDIDATES (good on both BTC AND ETH)")
    print(f"{'='*100}")

    print(f"\n--- 1.1.4 BFJK ---")
    rows_btc = grid_search_asymmetric(s114_btc, btc["1m"], eval_114, "1.1.4 BTC")
    rows_eth = grid_search_asymmetric(s114_eth, eth["1m"], eval_114, "1.1.4 ETH")
    # Find configs where BOTH have positive R, ETH avg >= 0.30, BTC avg >= 0.50
    dual = []
    for r in rows_eth:
        btc_match = next((b for b in rows_btc if b["entry"]==r["entry"]
                           and b["sl_L"]==r["sl_L"] and b["sl_S"]==r["sl_S"]
                           and b["rr"]==r["rr"]), None)
        if btc_match is None: continue
        if r["total"] > 0 and btc_match["total"] > 0 and r["avg"] >= 0.30 and btc_match["avg"] >= 0.50:
            dual.append({"eth": r, "btc": btc_match,
                          "combined": r["total"] + btc_match["total"]})
    dual = sorted(dual, key=lambda x: x["combined"], reverse=True)[:10]
    for d in dual:
        r, b = d["eth"], d["btc"]
        print(f"  e={r['entry']:.2f} slL={r['sl_L']:.2f} slS={r['sl_S']:.2f} RR={r['rr']:.1f}: "
              f"BTC n={b['n']:>3} R={b['total']:+6.1f} avg={b['avg']:+5.2f} | "
              f"ETH n={r['n']:>3} R={r['total']:+6.1f} avg={r['avg']:+5.2f} | sum={d['combined']:+.1f}")

    print(f"\n--- 1.1.5 hi-freq ---")
    rows_btc = grid_search_asymmetric(s115_btc, btc["1m"], eval_115, "1.1.5 BTC")
    rows_eth = grid_search_asymmetric(s115_eth, eth["1m"], eval_115, "1.1.5 ETH")
    dual = []
    for r in rows_eth:
        btc_match = next((b for b in rows_btc if b["entry"]==r["entry"]
                           and b["sl_L"]==r["sl_L"] and b["sl_S"]==r["sl_S"]
                           and b["rr"]==r["rr"]), None)
        if btc_match is None: continue
        if r["total"] > 0 and btc_match["total"] > 0:
            dual.append({"eth": r, "btc": btc_match,
                          "combined": r["total"] + btc_match["total"]})
    dual = sorted(dual, key=lambda x: x["combined"], reverse=True)[:10]
    for d in dual:
        r, b = d["eth"], d["btc"]
        print(f"  e={r['entry']:.2f} slL={r['sl_L']:.2f} slS={r['sl_S']:.2f} RR={r['rr']:.1f}: "
              f"BTC n={b['n']:>3} R={b['total']:+6.1f} avg={b['avg']:+5.2f} | "
              f"ETH n={r['n']:>3} R={r['total']:+6.1f} avg={r['avg']:+5.2f} | sum={d['combined']:+.1f}")

    print(f"\n--- 1.1.1 SWEPT ---")
    rows_btc = grid_search_symmetric(s111_btc, btc["1m"], eval_111, "1.1.1 BTC")
    rows_eth = grid_search_symmetric(s111_eth, eth["1m"], eval_111, "1.1.1 ETH")
    dual = []
    for r in rows_eth:
        btc_match = next((b for b in rows_btc if b["entry"]==r["entry"]
                           and b["sl"]==r["sl"] and b["rr"]==r["rr"]), None)
        if btc_match is None: continue
        if r["total"] > 0 and btc_match["total"] > 0:
            dual.append({"eth": r, "btc": btc_match,
                          "combined": r["total"] + btc_match["total"]})
    dual = sorted(dual, key=lambda x: x["combined"], reverse=True)[:10]
    for d in dual:
        r, b = d["eth"], d["btc"]
        print(f"  e={r['entry']:.2f} sl={r['sl']:.2f} RR={r['rr']:.1f}: "
              f"BTC n={b['n']:>3} R={b['total']:+6.1f} avg={b['avg']:+5.2f} | "
              f"ETH n={r['n']:>3} R={r['total']:+6.1f} avg={r['avg']:+5.2f} | sum={d['combined']:+.1f}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
