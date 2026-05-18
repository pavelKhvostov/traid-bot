"""etap_128: улучшение 1.1.5 fractal-sweep — forensic + filters + exit alternatives.

Baseline: 242 closed, WR 47.9%, +106R, 0 bad years на BTC 6.3y.

Тестируем:
  Phase 1: feature extraction wins vs losses (forensic)
  Phase 2: filter combinations (EMA, score, direction, fractal-strength)
  Phase 3: exit alternatives на лучшем фильтре:
    - floating TP (R_cap=4.5, th=-0.25, cf=2 как 1.1.1)
    - BE-ratchet @+1R, +1.5R
    - G2: TP-extension via score @+2R touch (как для 1.1.4)
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

# Reuse 1.1.5 detection from etap_81
_E76 = Path(__file__).parent / "etap_76_115_fractal_chains_survey.py"
_spec76 = _ilu.spec_from_file_location("etap76_core", _E76)
_e76 = _ilu.module_from_spec(_spec76); _sys.modules["etap76_core"] = _e76
_spec76.loader.exec_module(_e76)

_E77 = Path(__file__).parent / "etap_77_115_fractal_tightened.py"
_spec77 = _ilu.spec_from_file_location("etap77_core", _E77)
_e77 = _ilu.module_from_spec(_spec77); _sys.modules["etap77_core"] = _e77
_spec77.loader.exec_module(_e77)

_E67 = Path(__file__).parent / "etap_67_114_filter_grid_BF.py"
_spec67 = _ilu.spec_from_file_location("etap67_core", _E67)
_e67 = _ilu.module_from_spec(_spec67); _sys.modules["etap67_core"] = _e67
_spec67.loader.exec_module(_e67)

_e66 = _e76._e66

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec103 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec103); _sys.modules["etap103_core"] = _e103
_spec103.loader.exec_module(_e103)
build_score_series = _e103.build_score_series

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR_BASELINE = 2.0
MAX_HOLD_DAYS = 7


def simulate_baseline(s, entry, sl, tp, df_1m):
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0, None, None)
    start = s["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0, None, None)
    h = df_1m["high"].values[i0:i1]
    l = df_1m["low"].values[i0:i1]
    if direction == "LONG":
        ent = np.where(l <= entry)[0]; tp_pre = np.where(h >= tp)[0]
    else:
        ent = np.where(h >= entry)[0]; tp_pre = np.where(l <= tp)[0]
    ent_i = int(ent[0]) if ent.size else len(h) + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else len(h) + 1
    if tp_pre_i < ent_i: return ("no_entry", 0.0, None, None)
    if ent_i >= len(h): return ("not_filled", 0.0, None, None)
    post_h = h[ent_i:]; post_l = l[ent_i:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1: return ("open", 0.0, None, None)
    if sl_f == -1: return ("win", (tp-entry)/risk if direction=="LONG" else (entry-tp)/risk, None, None)
    if tp_f == -1: return ("loss", -1.0, None, None)
    if tp_f < sl_f: return ("win", (tp-entry)/risk if direction=="LONG" else (entry-tp)/risk, None, None)
    return ("loss", -1.0, None, None)


def simulate_floating(s, entry, sl, df_1m, df_1h, score_long, score_short,
                       R_cap=4.5, threshold=-0.25, confirm=2):
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tp_cap = entry + R_cap*risk if direction == "LONG" else entry - R_cap*risk
    tp_proxy = entry + RR_BASELINE*risk if direction == "LONG" else entry - RR_BASELINE*risk
    score_series = score_long if direction == "LONG" else score_short
    start = s["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    times = df_1m.index[i0:i1]
    n = len(h)
    if direction == "LONG":
        ent = np.where(l <= entry)[0]; tp_pre = np.where(h >= tp_proxy)[0]
    else:
        ent = np.where(h >= entry)[0]; tp_pre = np.where(l <= tp_proxy)[0]
    ent_i = int(ent[0]) if ent.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i: return ("no_entry", 0.0)
    if ent_i >= n: return ("not_filled", 0.0)
    activation = times[ent_i]
    post_h = h[ent_i:]; post_l = l[ent_i:]; post_ts = times[ent_i:]
    end_time = activation + pd.Timedelta(days=MAX_HOLD_DAYS)
    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values
    consec = 0; sl_exit = None; cap_hit = None; float_p = None
    prev_idx = 0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_idx = np.searchsorted(post_ts.values, cp64)
        if cur_idx > prev_idx:
            wl = post_l[prev_idx:cur_idx]; wh = post_h[prev_idx:cur_idx]
            if direction == "LONG":
                if (wl <= sl).any(): sl_exit = 1; break
                if (wh >= tp_cap).any(): cap_hit = 1; break
            else:
                if (wh >= sl).any(): sl_exit = 1; break
                if (wl <= tp_cap).any(): cap_hit = 1; break
        prev_idx = cur_idx
        sidx = score_series.index.searchsorted(cp, side="right") - 1
        if sidx < 0: continue
        sv = score_series.iloc[sidx]
        if pd.isna(sv): continue
        if sv <= threshold: consec += 1
        else: consec = 0
        if consec >= confirm:
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                float_p = float(closes_1h[cp_close_idx]); break
    if cap_hit: return ("win", R_cap)
    if sl_exit: return ("loss", -1.0)
    if float_p is not None:
        R = (float_p - entry)/risk if direction == "LONG" else (entry - float_p)/risk
        return ("win" if R > 0 else "loss", R)
    return ("open", 0.0)


def simulate_be_ratchet(s, entry, sl, df_1m, trigger_R, rr=RR_BASELINE):
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    start = s["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1]; l = df_1m["low"].values[i0:i1]
    if direction == "LONG":
        ent = np.where(l <= entry)[0]; tp_pre = np.where(h >= tp)[0]
    else:
        ent = np.where(h >= entry)[0]; tp_pre = np.where(l <= tp)[0]
    ent_i = int(ent[0]) if ent.size else len(h) + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else len(h) + 1
    if tp_pre_i < ent_i: return ("no_entry", 0.0)
    if ent_i >= len(h): return ("not_filled", 0.0)
    post_h = h[ent_i:]; post_l = l[ent_i:]
    current_sl = sl
    triggered = False
    for j in range(len(post_h)):
        if direction == "LONG":
            mfe_R = (post_h[j] - entry) / risk
            if mfe_R >= trigger_R and not triggered:
                current_sl = max(current_sl, entry); triggered = True
            if post_l[j] <= current_sl:
                return ("flat" if triggered else "loss", 0.0 if triggered else -1.0)
            if post_h[j] >= tp: return ("win", rr)
        else:
            mfe_R = (entry - post_l[j]) / risk
            if mfe_R >= trigger_R and not triggered:
                current_sl = min(current_sl, entry); triggered = True
            if post_h[j] >= current_sl:
                return ("flat" if triggered else "loss", 0.0 if triggered else -1.0)
            if post_l[j] <= tp: return ("win", rr)
    return ("open", 0.0)


def main():
    print("etap_128: 1.1.5 fractal-sweep improvement (BTC 6.3y)")
    print()
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    for nm in ["df_1d","df_4h","df_1h","df_12h","df_2h","df_15m"]:
        pass
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    for tf, df in [("1d", df_1d), ("12h", df_12h), ("4h", df_4h),
                    ("1h", df_1h), ("2h", df_2h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()

    print("[INFO] Hull-1h L=49")
    hull_1h = _e67.hull_ma(df_1h["close"], 49)
    hull_lbl = _e67.hull_label_series(df_1h["close"], hull_1h)

    print("[INFO] score series")
    score_long, score_short = build_score_series(df_1h)

    print("[INFO] 1.1.5 detection (B5 strict)")
    fractals_12h = _e76.collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    raw_setups = _e77.detect_strict(fractals_12h, obs_4h, obs_1h, fvgs_15m,
                                      "12h", "4h", "1h", "15m",
                                      allow_multi=3, proximity_atr=1.0,
                                      min_sweep_depth_atr=0.0)
    # Hull-1h aligned filter (как в etap_81)
    setups = []
    for s in raw_setups:
        lbl = _e67.safe_label_at(hull_lbl, s["signal_time"])
        if _e67.hull_align(lbl, s["direction"]) == "aligned":
            setups.append(s)
    print(f"  total {len(raw_setups)} -> hull_aligned {len(setups)}")

    # Build entry/SL/TP (canonical 1.1.5 — entry=mid FVG, SL=OB-htf edge × 0.15)
    rich = []
    for s in setups:
        fb, ft = s["fvg_b"], s["fvg_t"]
        obb, obt = s["obh_b"], s["obh_t"]
        if s["direction"] == "LONG":
            entry = (fb + ft) / 2
            ob_depth = obt - obb
            sl = obb + 0.15 * ob_depth
        else:
            entry = (fb + ft) / 2
            ob_depth = obt - obb
            sl = obt - 0.15 * ob_depth
        if abs(entry - sl) <= 0: continue
        if (s["direction"]=="LONG" and sl>=entry) or (s["direction"]=="SHORT" and sl<=entry): continue
        tp = entry + RR_BASELINE*abs(entry-sl) if s["direction"]=="LONG" else entry - RR_BASELINE*abs(entry-sl)
        outc, R, _, _ = simulate_baseline(s, entry, sl, tp, df_1m)
        if outc not in ("win", "loss"): continue
        # Features
        t = s["signal_time"]
        idx2h = df_2h.index.searchsorted(t, side="right") - 1
        ema_pro = False
        if idx2h >= 0 and not pd.isna(df_2h["ema200"].iloc[idx2h]):
            c = float(df_2h["close"].iloc[idx2h]); e = float(df_2h["ema200"].iloc[idx2h])
            ema_pro = (c > e) if s["direction"] == "LONG" else (c < e)
        sc_series = score_long if s["direction"] == "LONG" else score_short
        sidx = sc_series.index.searchsorted(t, side="right") - 1
        sc_val = float(sc_series.iloc[sidx]) if sidx >= 0 and not pd.isna(sc_series.iloc[sidx]) else 0
        rich.append({
            "s": s, "entry": entry, "sl": sl, "tp": tp, "outcome": outc, "R": R,
            "year": t.year, "direction": s["direction"],
            "ema_pro": ema_pro, "score": sc_val,
        })

    print(f"  baseline closed: {len(rich)}")
    wins = [r for r in rich if r["R"] > 0]
    losses = [r for r in rich if r["R"] < 0]
    pnl = sum(r["R"] for r in rich)
    print(f"  W={len(wins)} L={len(losses)} WR={len(wins)/len(rich)*100:.1f}% PnL={pnl:+.1f}R")

    # Phase 1: forensic
    print("\n=== Phase 1: forensic ===")
    print(f"  Feature distributions (wins | losses):")
    for feat in ["score"]:
        w = [r[feat] for r in wins]
        l = [r[feat] for r in losses]
        print(f"    {feat}: wins mean={np.mean(w):+.3f} med={np.median(w):+.3f}  |  "
              f"losses mean={np.mean(l):+.3f} med={np.median(l):+.3f}")
    # by direction
    for d in ["LONG", "SHORT"]:
        g = [r for r in rich if r["direction"] == d]
        W = sum(1 for r in g if r["R"] > 0)
        wr = W/len(g)*100 if g else 0
        print(f"    {d}: n={len(g)} WR={wr:.1f}% PnL={sum(r['R'] for r in g):+.1f}R")
    # by ema_pro
    for v in [True, False]:
        g = [r for r in rich if r["ema_pro"] == v]
        if not g: continue
        W = sum(1 for r in g if r["R"] > 0)
        wr = W/len(g)*100
        print(f"    EMA pro={v}: n={len(g)} WR={wr:.1f}% PnL={sum(r['R'] for r in g):+.1f}R")

    # Phase 2: filter combinations
    print("\n=== Phase 2: Filters ===")
    def f_ema(r): return r["ema_pro"]
    def f_long(r): return r["direction"] == "LONG"
    def f_sc(r): return r["score"] > 0

    filters = [
        ("F0: baseline (hull aligned)",   lambda r: True),
        ("F1: + EMA-2h pro",              f_ema),
        ("F2: + LONG only",               f_long),
        ("F3: + EMA AND LONG",            lambda r: f_ema(r) and f_long(r)),
        ("F4: + EMA OR LONG",             lambda r: f_ema(r) or f_long(r)),
        ("F5: + score>0",                 f_sc),
        ("F6: + EMA AND score>0",         lambda r: f_ema(r) and f_sc(r)),
    ]
    print(f"  {'Filter':<32} {'n':>4} {'WR':>5} {'PnL':>8} {'bad':>5}")
    print("  " + "-"*60)
    best = None
    for label, fn in filters:
        g = [r for r in rich if fn(r)]
        if not g: continue
        n = len(g); W = sum(1 for r in g if r["R"] > 0)
        wr = W/n*100
        pnl = sum(r["R"] for r in g)
        yr_map = defaultdict(float)
        for r in g: yr_map[r["year"]] += r["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        print(f"  {label:<32} {n:>4d} {wr:>4.1f}% {pnl:>+7.1f}R {bad}/{len(yr_map)}")
        score_v = pnl * (1 - bad / max(len(yr_map), 1))
        if best is None or score_v > best[1]:
            best = (label, score_v, fn, g)

    # Phase 3: exit alternatives на winner filter
    print(f"\n=== Phase 3: Exit alternatives на best filter '{best[0]}' ===")
    winner_g = best[3]
    winner_setups = [r for r in winner_g]
    print(f"  Best filter has {len(winner_setups)} setups")

    # baseline RR=2.0 (already in winner_setups via rich, but recompute consistent)
    n = len(winner_setups)
    W = sum(1 for r in winner_setups if r["R"] > 0)
    pnl = sum(r["R"] for r in winner_setups)
    yr_b = defaultdict(float)
    for r in winner_setups: yr_b[r["year"]] += r["R"]
    bad_b = sum(1 for v in yr_b.values() if v < 0)
    print(f"  {'baseline RR=2.0':<28} n={n:>3d}  WR={W/n*100:>4.1f}%  PnL={pnl:>+6.1f}R  bad={bad_b}/{len(yr_b)}")

    # floating TP
    trades = []
    for r in winner_setups:
        outc, R = simulate_floating(r["s"], r["entry"], r["sl"], df_1m, df_1h, score_long, score_short)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": r["year"]})
    if trades:
        n = len(trades); W = sum(1 for t in trades if t["R"] > 0)
        pnl = sum(t["R"] for t in trades)
        yr_m = defaultdict(float)
        for t in trades: yr_m[t["year"]] += t["R"]
        bad = sum(1 for v in yr_m.values() if v < 0)
        print(f"  {'floating TP (1.1.1 cfg)':<28} n={n:>3d}  WR={W/n*100:>4.1f}%  PnL={pnl:>+6.1f}R  bad={bad}/{len(yr_m)}")

    # BE-ratchet @+1R
    for trig in [1.0, 1.5]:
        trades = []
        for r in winner_setups:
            outc, R = simulate_be_ratchet(r["s"], r["entry"], r["sl"], df_1m, trig)
            if outc in ("win", "loss", "flat"):
                trades.append({"R": R, "year": r["year"], "outc": outc})
        if trades:
            n = len(trades); W = sum(1 for t in trades if t["R"] > 0)
            BE = sum(1 for t in trades if t["outc"] == "flat")
            pnl = sum(t["R"] for t in trades)
            yr_m = defaultdict(float)
            for t in trades: yr_m[t["year"]] += t["R"]
            bad = sum(1 for v in yr_m.values() if v < 0)
            print(f"  BE-ratchet @+{trig}R           n={n:>3d}  WR={W/n*100:>4.1f}%  PnL={pnl:>+6.1f}R  "
                  f"BE={BE}  bad={bad}/{len(yr_m)}")


if __name__ == "__main__":
    main()
