"""etap_109: Floating TP analysis for Strategy 1.1.2 (same framework as etap_104 для 1.1.1).

1.1.2 отличия от 1.1.1:
  - Macro = OB-{4h,6h} вместо FVG-{4h,6h}
  - LIVE params: entry=0.70 (не 0.80), sl=0.35 sym, RR=2.2
  - Нет SWEPT фильтра (без strict-SWEPT gate)
  - Структура signal'a та же (fvg_zone, ob_htf_zone)

Запускаем те же 14 variants + grid поиск winner'a + verify на ETH/SOL.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu

_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, OBZone
from strategies.strategy_1_1_2 import collect_valid_macro_obs

# reuse score + simulators
_E98 = Path(__file__).parent / "etap_98_retry_after_sl_111.py"
_spec = _ilu.spec_from_file_location("etap98_core", _E98)
_e98 = _ilu.module_from_spec(_spec); _sys.modules["etap98_core"] = _e98
_spec.loader.exec_module(_e98)
find_all_signals_in_htf = _e98.find_all_signals_in_htf

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec3 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec3); _sys.modules["etap103_core"] = _e103
_spec3.loader.exec_module(_e103)
build_score_series = _e103.build_score_series

# 1.1.2 LIVE params
ENTRY_PCT = 0.70
SL_PCT = 0.35
RR_BASELINE = 2.2
MAX_HOLD_DAYS = 7
DAYS_BACK_TARGET = 2313
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def build_setup_112(sig):
    """1.1.2 LIVE formula: entry_pct=0.70, sl_pct=0.35 sym (без MIN_SL_PCT)."""
    direction = sig["direction"]
    fb, ft = sig["fvg_zone"]
    obb, obt = sig["ob_htf_zone"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl = obb + SL_PCT * (fb - obb)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl = obt - SL_PCT * (obt - ft)
        if sl <= entry: return None
    return float(entry), float(sl)


def detect_multi_signals_112(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m):
    """Multi-shot 1.1.2: все (OB-htf, entry-FVG) pairs на (top × OB-macro × ob-htf)."""
    groups: dict[tuple, list[dict]] = {}

    def _scan_top(df_top, top_hours, top_label):
        if df_top is None or df_top.empty:
            return
        for idx in range(1, len(df_top)):
            ob_top = detect_ob_pair(df_top, idx)
            if ob_top is None: continue
            valid_4h = collect_valid_macro_obs(df_4h, ob_top, htf_hours=4, top_tf_hours=top_hours)
            valid_6h = collect_valid_macro_obs(df_6h, ob_top, htf_hours=6, top_tf_hours=top_hours)
            for ob_macro, macro_tf in [(ob, "4h") for ob in valid_4h] + [(ob, "6h") for ob in valid_6h]:
                search_start = ob_top.cur_time + pd.Timedelta(hours=top_hours)
                # find_all_signals_in_htf принимает OBZone duck-typed как FVGZone (только bottom/top)
                pairs_1h = find_all_signals_in_htf(df_1h, df_15m, df_20m, ob_top, ob_macro,
                                                     search_start, 60, "1h")
                pairs_2h = find_all_signals_in_htf(df_2h, df_15m, df_20m, ob_top, ob_macro,
                                                     search_start, 120, "2h")
                all_pairs = pairs_1h + pairs_2h
                if not all_pairs:
                    continue
                all_pairs.sort(key=lambda p: p["fvg_entry"].c2_time)
                gid = (top_label, ob_top.cur_time, macro_tf, ob_macro.cur_time, ob_top.direction)
                for p in all_pairs:
                    ob_htf = p["ob_htf"]
                    fvg_entry = p["fvg_entry"]
                    groups.setdefault(gid, []).append({
                        "group_id": gid,
                        "direction": ob_top.direction,
                        "signal_time": fvg_entry.c2_time,
                        "top_tf": top_label,
                        "ob_d_cur_time": ob_top.cur_time,
                        "ob_d_zone": (ob_top.bottom, ob_top.top),
                        "ob_macro_tf": macro_tf,
                        "ob_macro_cur_time": ob_macro.cur_time,
                        "ob_macro_zone": (ob_macro.bottom, ob_macro.top),
                        "ob_htf_tf": p["htf_label"],
                        "ob_htf_prev_time": ob_htf.prev_time,
                        "ob_htf_cur_time": ob_htf.cur_time,
                        "ob_htf_zone": (ob_htf.bottom, ob_htf.top),
                        "fvg_tf": p["fvg_tf"],
                        "fvg_c0_time": fvg_entry.c0_time,
                        "fvg_c2_time": fvg_entry.c2_time,
                        "fvg_zone": (fvg_entry.bottom, fvg_entry.top),
                    })

    _scan_top(df_1d, 24, "1d")
    _scan_top(df_12h, 12, "12h")
    return groups


# Adapted simulators (entry/sl computed via build_setup_112)
def find_entry_fill(sig, df_1m, entry, direction, sl):
    risk = abs(entry - sl)
    tf_min = 15 if sig["fvg_tf"] == "15m" else 20
    fill_start = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    forward = df_1m[df_1m.index >= fill_start]
    if forward.empty:
        return None, None, "no_data"
    h = forward["high"].values.astype(np.float64)
    l = forward["low"].values.astype(np.float64)
    ts = forward.index
    n = len(h)
    tp_proxy = entry + RR_BASELINE * risk if direction == "LONG" else entry - RR_BASELINE * risk
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre = np.where(h >= tp_proxy)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre = np.where(l <= tp_proxy)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i:
        return None, None, "no_entry"
    if ent_i >= n:
        return None, None, "nf"
    return ent_i, ts[ent_i], None


def _walk_to_end(df_1m, activation_time, max_hold_days):
    end_time = activation_time + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(activation_time.tz_localize(None) if activation_time.tz else activation_time)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return None
    return (df_1m["high"].values[i0:i1].astype(np.float64),
            df_1m["low"].values[i0:i1].astype(np.float64),
            df_1m["close"].values[i0:i1].astype(np.float64),
            df_1m.index[i0:i1], end_time)


def _finalize(direction, entry, sl, risk, sl_exit_idx, post_ts, post_c,
              activation, floating_price, floating_time, max_R, exit_reason_for_score):
    if sl_exit_idx is not None:
        return {"outcome": "loss", "R": -1.0, "exit_time": post_ts[sl_exit_idx],
                "exit_reason": "sl_hit",
                "hold_h": (post_ts[sl_exit_idx] - activation).total_seconds()/3600,
                "max_R": max_R}
    if floating_price is not None:
        R = (floating_price - entry)/risk if direction == "LONG" else (entry - floating_price)/risk
        outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
        return {"outcome": outc, "R": float(R), "exit_time": floating_time,
                "exit_reason": exit_reason_for_score,
                "hold_h": (floating_time - activation).total_seconds()/3600, "max_R": max_R}
    last_c = float(post_c[-1])
    R = (last_c - entry)/risk if direction == "LONG" else (entry - last_c)/risk
    outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
    return {"outcome": outc, "R": float(R), "exit_time": post_ts[-1],
            "exit_reason": "max_hold",
            "hold_h": (post_ts[-1] - activation).total_seconds()/3600, "max_R": max_R}


def variant_baseline_rr(sig, df_1m, rr=RR_BASELINE):
    setup = build_setup_112(sig)
    if setup is None: return None
    entry, sl = setup
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction, sl)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, _ = walk
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
        max_R = (max(post_h) - entry) / risk
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
        max_R = (entry - min(post_l)) / risk
    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1:
        last_c = float(post_c[-1])
        R = (last_c - entry)/risk if direction == "LONG" else (entry - last_c)/risk
        outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
        return {"outcome": outc, "R": float(R), "exit_time": post_ts[-1],
                "exit_reason": "max_hold",
                "hold_h": (post_ts[-1]-activation).total_seconds()/3600, "max_R": max_R}
    if sl_f == -1:
        return {"outcome": "win", "R": rr, "exit_time": post_ts[tp_f],
                "exit_reason": "tp_fixed",
                "hold_h": (post_ts[tp_f]-activation).total_seconds()/3600, "max_R": max_R}
    if tp_f == -1:
        return {"outcome": "loss", "R": -1.0, "exit_time": post_ts[sl_f],
                "exit_reason": "sl_hit",
                "hold_h": (post_ts[sl_f]-activation).total_seconds()/3600, "max_R": max_R}
    if tp_f < sl_f:
        return {"outcome": "win", "R": rr, "exit_time": post_ts[tp_f],
                "exit_reason": "tp_fixed",
                "hold_h": (post_ts[tp_f]-activation).total_seconds()/3600, "max_R": max_R}
    return {"outcome": "loss", "R": -1.0, "exit_time": post_ts[sl_f],
            "exit_reason": "sl_hit",
            "hold_h": (post_ts[sl_f]-activation).total_seconds()/3600, "max_R": max_R}


def variant_rcap_score(sig, df_1m, df_1h, score_long, score_short,
                        R_cap=4.5, threshold=-0.25, confirm=2):
    setup = build_setup_112(sig)
    if setup is None: return None
    entry, sl = setup
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp_cap = entry + R_cap * risk if direction == "LONG" else entry - R_cap * risk
    ent_i, activation, err = find_entry_fill(sig, df_1m, entry, direction, sl)
    if err is not None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": err, "hold_h": 0, "max_R": 0}
    score_series = score_long if direction == "LONG" else score_short
    walk = _walk_to_end(df_1m, activation, MAX_HOLD_DAYS)
    if walk is None:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_data", "hold_h": 0, "max_R": 0}
    post_h, post_l, post_c, post_ts, end_time = walk

    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values

    consec = 0
    sl_exit_idx = None; cap_hit_idx = None
    floating_price = None; floating_time = None
    max_R = 0.0
    prev_post_idx = 0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_post_idx = np.searchsorted(post_ts.values, cp64)
        if cur_post_idx > prev_post_idx:
            w_l = post_l[prev_post_idx:cur_post_idx]
            w_h = post_h[prev_post_idx:cur_post_idx]
            if direction == "LONG":
                max_R = max(max_R, (max(w_h) - entry) / risk)
                if (w_l <= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(w_l <= sl)); break
                if (w_h >= tp_cap).any():
                    cap_hit_idx = prev_post_idx + int(np.argmax(w_h >= tp_cap)); break
            else:
                max_R = max(max_R, (entry - min(w_l)) / risk)
                if (w_h >= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(w_h >= sl)); break
                if (w_l <= tp_cap).any():
                    cap_hit_idx = prev_post_idx + int(np.argmax(w_l <= tp_cap)); break
        prev_post_idx = cur_post_idx
        score_idx = score_series.index.searchsorted(cp, side="right") - 1
        if score_idx < 0: continue
        s = score_series.iloc[score_idx]
        if pd.isna(s): continue
        if s <= threshold: consec += 1
        else: consec = 0
        if consec >= confirm:
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                floating_price = float(closes_1h[cp_close_idx])
                floating_time = cp
                break

    if cap_hit_idx is not None:
        return {"outcome": "win", "R": R_cap, "exit_time": post_ts[cap_hit_idx],
                "exit_reason": "R_cap",
                "hold_h": (post_ts[cap_hit_idx]-activation).total_seconds()/3600,
                "max_R": max_R}
    return _finalize(direction, entry, sl, risk, sl_exit_idx, post_ts, post_c,
                      activation, floating_price, floating_time, max_R, "score_exit")


def collect_signals_112(symbol):
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_15m = load_df(symbol, "15m")
    df_1m = load_df(symbol, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = max(today - pd.Timedelta(days=DAYS_BACK_TARGET), df_1m.index[0])
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]
    groups = detect_multi_signals_112(df_1d_f, df_12h_f, df_4h, df_6h,
                                        df_1h, df_2h, df_15m, df_20m)
    sigs = []
    for gid, gsigs in groups.items():
        sigs.extend(sorted(gsigs, key=lambda x: x["fvg_c2_time"]))
    return sigs, df_1m, df_1h, df_2h, (today-cutoff).days/365


def evaluate(simulate_fn, signals):
    trades = []
    for s in signals:
        r = simulate_fn(s)
        if r is None: continue
        trades.append({"signal_time": s["signal_time"], "direction": s["direction"], **r})
    return trades


def distribution_stats(trades):
    closed = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]
    if not closed: return None
    Rs = sorted([t["R"] for t in closed], reverse=True)
    n = len(closed); W = sum(1 for r in Rs if r > 0); L = sum(1 for r in Rs if r < 0)
    wr = W/n*100; pnl = sum(Rs); r_per = pnl/n
    median_R = float(np.median(Rs))
    max_R = max(Rs); min_R = min(Rs)
    top5_pct = sum(Rs[:5])/pnl*100 if pnl > 0 else 0
    top10_n = max(1, n // 10)
    top10pct_pct = sum(Rs[:top10_n])/pnl*100 if pnl > 0 else 0
    avg_loss = np.mean([r for r in Rs if r < 0]) if L else 0
    return {"n": n, "W": W, "L": L, "wr": wr, "pnl": pnl, "r_per": r_per,
            "median_R": median_R, "max_R": max_R, "min_R": min_R,
            "top5_pct": top5_pct, "top10pct_pct": top10pct_pct, "avg_loss": avg_loss}


def run_btc_variants():
    print("# BTC 1.1.2 — 14 variants")
    sigs, df_1m, df_1h, df_2h, years = collect_signals_112("BTCUSDT")
    print(f"  signals: {len(sigs)}  years={years:.2f}")
    score_long, score_short = build_score_series(df_1h)

    variants = [
        ("BASELINE RR=2.2",         lambda s: variant_baseline_rr(s, df_1m)),
        ("D R_cap=2.5 th=0 cf=2",   lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 2.5, 0.0, 2)),
        ("D R_cap=3.0 th=0 cf=2",   lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 3.0, 0.0, 2)),
        ("D R_cap=3.5 th=0 cf=2",   lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 3.5, 0.0, 2)),
        ("D R_cap=4.0 th=0 cf=2",   lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 4.0, 0.0, 2)),
        ("D R_cap=4.5 th=0 cf=2",   lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 4.5, 0.0, 2)),
        ("D R_cap=4.5 th=-0.25 cf=2", lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 4.5, -0.25, 2)),
        ("D R_cap=4.5 th=-0.5 cf=1",  lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 4.5, -0.5, 1)),
        ("D R_cap=3.5 th=0 cf=1",   lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 3.5, 0.0, 1)),
        ("D R_cap=5.0 th=-0.25 cf=2", lambda s: variant_rcap_score(s, df_1m, df_1h, score_long, score_short, 5.0, -0.25, 2)),
    ]
    print()
    print(f"  {'Variant':<28} {'n':>4} {'WR':>5} {'PnL':>9} {'medR':>6} {'maxR':>5} {'top5%':>6} {'pass':>5}")
    print("  " + "-"*86)
    results = []
    for label, fn in variants:
        trs = evaluate(fn, sigs)
        st = distribution_stats(trs)
        if st is None:
            print(f"  {label:<28} NO DATA"); continue
        pass_ = "PASS" if (st["median_R"] > 0 and st["top5_pct"] < 20) else "    "
        print(f"  {label:<28} {st['n']:>4d} {st['wr']:>4.1f}% {st['pnl']:>+8.1f}R "
              f"{st['median_R']:>+5.2f} {st['max_R']:>+4.1f} {st['top5_pct']:>5.1f}% {pass_}")
        results.append((label, st))
    return results, df_1m, df_1h, df_2h, score_long, score_short


def main():
    print("etap_109: Floating TP for Strategy 1.1.2 (entry=0.70, no SWEPT)")
    print()
    results, df_1m, df_1h, df_2h, score_long, score_short = run_btc_variants()

    # Cross-symbol verify with best PASS config on BTC
    passing = [(l, st) for l, st in results if st["median_R"] > 0 and st["top5_pct"] < 20 and "D" in l]
    if not passing:
        print("\n  [WARN] no PASS variant on BTC")
        return
    passing.sort(key=lambda x: x[1]["pnl"] * (1 - x[1]["top5_pct"]/100), reverse=True)
    best_label, best_st = passing[0]
    print(f"\nWinner on BTC: {best_label}")
    print(f"  BTC PnL={best_st['pnl']:+.1f}R  WR={best_st['wr']:.1f}%  medR={best_st['median_R']:+.2f}")

    # Parse winner params from label
    import re
    m = re.search(r"R_cap=([\d.]+).*th=([+\-]?[\d.]+)\s*cf=(\d+)", best_label)
    if not m:
        print(f"  [WARN] can't parse params from label: {best_label}")
        return
    R_cap, th, cf = float(m.group(1)), float(m.group(2)), int(m.group(3))

    # Verify ETH/SOL
    for symbol in ["ETHUSDT", "SOLUSDT"]:
        print(f"\n--- {symbol} ---")
        sigs, df_1m_s, df_1h_s, _, years = collect_signals_112(symbol)
        score_long_s, score_short_s = build_score_series(df_1h_s)
        print(f"  signals: {len(sigs)}  years={years:.2f}")
        trs_b = evaluate(lambda s: variant_baseline_rr(s, df_1m_s), sigs)
        st_b = distribution_stats(trs_b)
        trs = evaluate(lambda s: variant_rcap_score(s, df_1m_s, df_1h_s,
                                                       score_long_s, score_short_s,
                                                       R_cap, th, cf), sigs)
        st = distribution_stats(trs)
        if st_b is None or st is None:
            print("  no data")
            continue
        delta = st["pnl"] - st_b["pnl"]
        print(f"  baseline: PnL={st_b['pnl']:+.1f}R WR={st_b['wr']:.1f}% medR={st_b['median_R']:+.2f}")
        print(f"  D winner: PnL={st['pnl']:+.1f}R WR={st['wr']:.1f}% medR={st['median_R']:+.2f} "
              f"top5={st['top5_pct']:.1f}% {'PASS' if st['median_R']>0 and st['top5_pct']<20 else 'FAIL'}")
        print(f"  delta:    {delta:+.1f}R ({delta/abs(st_b['pnl'])*100 if st_b['pnl'] else 0:+.1f}%)")


if __name__ == "__main__":
    main()
