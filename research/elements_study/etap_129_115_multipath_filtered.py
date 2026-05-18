"""etap_129: 1.1.5 multi-path + filters + exits.

16 chains (12h/1d fractal × 4h/6h OB × 1h/2h OB × 15m/20m FVG) → union dedup.
Apply Hull-1h aligned + F6 filter (EMA AND score>0) + floating TP.

Goal: финальный winner на 1.1.5.
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

_E128 = Path(__file__).parent / "etap_128_115_improve.py"
_spec128 = _ilu.spec_from_file_location("etap128_core", _E128)
_e128 = _ilu.module_from_spec(_spec128); _sys.modules["etap128_core"] = _e128
_spec128.loader.exec_module(_e128)
simulate_baseline = _e128.simulate_baseline
simulate_floating = _e128.simulate_floating
simulate_be_ratchet = _e128.simulate_be_ratchet

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR_BASELINE = 2.0


def main():
    print("etap_129: 1.1.5 multi-path + filters + exits (BTC 6.3y)")
    print()
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    for nm in ["df_1d","df_4h","df_1h","df_12h","df_6h","df_2h","df_15m","df_20m"]:
        pass
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    for tf, df in [("1d",df_1d),("12h",df_12h),("6h",df_6h),("4h",df_4h),
                    ("2h",df_2h),("1h",df_1h),("15m",df_15m),("20m",df_20m)]:
        df["atr14"] = _e66.compute_atr(df, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    print("[INFO] Hull-1h L=49 + score series")
    hull_1h = _e67.hull_ma(df_1h["close"], 49)
    hull_lbl = _e67.hull_label_series(df_1h["close"], hull_1h)
    score_long, score_short = build_score_series(df_1h)

    # Collect zones for all TFs
    print("[INFO] collecting zones")
    fractals_12h = _e76.collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    fractals_1d = _e76.collect_fractals_with_sweep(df_1d, df_1d["atr14"], "1d")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")
    print(f"  fractals 12h={len(fractals_12h)} 1d={len(fractals_1d)}")

    # 16 chains: (fractals, obs_macro, obs_htf, fvgs, l1_tf, l2_tf, l3_tf, l4_tf)
    chains = []
    for fl1, l1tf in [(fractals_12h, "12h"), (fractals_1d, "1d")]:
        for l2, l2tf in [(obs_4h, "4h"), (obs_6h, "6h")]:
            for l3, l3tf in [(obs_1h, "1h"), (obs_2h, "2h")]:
                for l4, l4tf in [(fvgs_15m, "15m"), (fvgs_20m, "20m")]:
                    chains.append((fl1, l2, l3, l4, l1tf, l2tf, l3tf, l4tf))

    print(f"[INFO] running {len(chains)} chains")
    all_setups = []
    for fl1, l2, l3, l4, l1tf, l2tf, l3tf, l4tf in chains:
        try:
            s = _e77.detect_strict(fl1, l2, l3, l4, l1tf, l2tf, l3tf, l4tf,
                                    allow_multi=3, proximity_atr=1.0,
                                    min_sweep_depth_atr=0.0)
            all_setups.extend(s)
        except Exception as e:
            print(f"  chain {l1tf}/{l2tf}/{l3tf}/{l4tf} error: {e!r}")
    print(f"  raw setups across 16 chains: {len(all_setups)}")

    # Hull aligned filter
    hull_aligned = []
    for s in all_setups:
        lbl = _e67.safe_label_at(hull_lbl, s["signal_time"])
        if _e67.hull_align(lbl, s["direction"]) == "aligned":
            hull_aligned.append(s)
    print(f"  after hull-1h aligned: {len(hull_aligned)}")

    # Dedup by (signal_time, direction, fvg_b, fvg_t)
    seen = {}
    for s in hull_aligned:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k not in seen: seen[k] = s
    unique = list(seen.values())
    print(f"  after union dedup: {len(unique)}")

    # Build entry/SL/TP + features
    rich = []
    for s in unique:
        fb, ft = s["fvg_b"], s["fvg_t"]
        obb, obt = s["obh_b"], s["obh_t"]
        if s["direction"] == "LONG":
            entry = (fb + ft) / 2
            sl = obb + 0.15 * (obt - obb)
        else:
            entry = (fb + ft) / 2
            sl = obt - 0.15 * (obt - obb)
        if abs(entry - sl) <= 0: continue
        if (s["direction"]=="LONG" and sl>=entry) or (s["direction"]=="SHORT" and sl<=entry): continue
        tp = entry + RR_BASELINE*abs(entry-sl) if s["direction"]=="LONG" else entry - RR_BASELINE*abs(entry-sl)
        outc, R, _, _ = simulate_baseline(s, entry, sl, tp, df_1m)
        if outc not in ("win", "loss"): continue
        # features
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
            "s": s, "entry": entry, "sl": sl, "tp": tp,
            "outcome": outc, "R": R, "year": t.year, "direction": s["direction"],
            "ema_pro": ema_pro, "score": sc_val,
        })
    print(f"  closed baseline: {len(rich)}")

    def stats_grp(g, label):
        n = len(g)
        if n == 0: return None
        W = sum(1 for r in g if r["R"] > 0)
        pnl = sum(r["R"] for r in g)
        yr = defaultdict(float)
        for r in g: yr[r["year"]] += r["R"]
        bad = sum(1 for v in yr.values() if v < 0)
        return {"label": label, "n": n, "W": W, "wr": W/n*100, "pnl": pnl,
                "bad": bad, "n_yrs": len(yr)}

    # Phase 1: baseline + filters
    print("\n=== Filters (baseline RR=2.0) ===")
    def f_ema(r): return r["ema_pro"]
    def f_long(r): return r["direction"] == "LONG"
    def f_short(r): return r["direction"] == "SHORT"
    def f_sc(r): return r["score"] > 0

    filters = [
        ("F0: baseline (hull aligned)",   lambda r: True),
        ("F1: + EMA-2h pro",              f_ema),
        ("F_short: SHORT only",           f_short),
        ("F_ema_sc: EMA AND score>0",     lambda r: f_ema(r) and f_sc(r)),
        ("F_short_ema: SHORT AND EMA",    lambda r: f_short(r) and f_ema(r)),
        ("F_short_sc: SHORT AND score>0", lambda r: f_short(r) and f_sc(r)),
        ("F_short_ema_sc: SHORT+EMA+sc>0",lambda r: f_short(r) and f_ema(r) and f_sc(r)),
    ]
    print(f"  {'Filter':<36} {'n':>4} {'WR':>5} {'PnL':>8} {'bad':>5}")
    print("  " + "-"*64)
    best = None
    for label, fn in filters:
        g = [r for r in rich if fn(r)]
        st = stats_grp(g, label)
        if st is None: continue
        print(f"  {st['label']:<36} {st['n']:>4d} {st['wr']:>4.1f}% {st['pnl']:>+7.1f}R {st['bad']}/{st['n_yrs']}")
        sc = st["pnl"] * (1 - st["bad"]/max(st["n_yrs"],1))
        if (best is None or sc > best[1]) and st["n"] >= 20:
            best = (st["label"], sc, g)

    # Phase 2: exits на лучшем filter
    if best is None: return
    print(f"\n=== Exit alternatives на best filter '{best[0]}' ===")
    winner_g = best[2]
    print(f"  n_setups = {len(winner_g)}")

    # baseline (already in winner_g)
    st = stats_grp(winner_g, "baseline RR=2.0")
    print(f"  {'baseline RR=2.0':<28} n={st['n']:>3d}  WR={st['wr']:>4.1f}%  "
          f"PnL={st['pnl']:>+6.1f}R  bad={st['bad']}/{st['n_yrs']}")

    # floating TP
    floating_trades = []
    for r in winner_g:
        outc, R = simulate_floating(r["s"], r["entry"], r["sl"], df_1m, df_1h,
                                      score_long, score_short)
        if outc in ("win", "loss"):
            floating_trades.append({"R": R, "year": r["year"]})
    if floating_trades:
        n = len(floating_trades); W = sum(1 for t in floating_trades if t["R"] > 0)
        pnl = sum(t["R"] for t in floating_trades)
        yr = defaultdict(float)
        for t in floating_trades: yr[t["year"]] += t["R"]
        bad = sum(1 for v in yr.values() if v < 0)
        print(f"  {'floating TP (1.1.1 cfg)':<28} n={n:>3d}  WR={W/n*100:>4.1f}%  "
              f"PnL={pnl:>+6.1f}R  bad={bad}/{len(yr)}")

    # BE-ratchet
    for trig in [1.0, 1.5]:
        bt = []
        for r in winner_g:
            outc, R = simulate_be_ratchet(r["s"], r["entry"], r["sl"], df_1m, trig)
            if outc in ("win", "loss", "flat"):
                bt.append({"R": R, "year": r["year"], "outc": outc})
        if bt:
            n = len(bt); W = sum(1 for t in bt if t["R"] > 0)
            BE = sum(1 for t in bt if t["outc"] == "flat")
            pnl = sum(t["R"] for t in bt)
            yr = defaultdict(float)
            for t in bt: yr[t["year"]] += t["R"]
            bad = sum(1 for v in yr.values() if v < 0)
            print(f"  BE-ratchet @+{trig}R          n={n:>3d}  WR={W/n*100:>4.1f}%  "
                  f"PnL={pnl:>+6.1f}R  BE={BE}  bad={bad}/{len(yr)}")


if __name__ == "__main__":
    main()
