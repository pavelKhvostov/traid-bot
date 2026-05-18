"""etap_122: forensic анализ Wicked+Fractal OB-D + V2 FVG-entry (winner из etap_121).

V2 baseline: 222 closed, WR 36.9%, +24R на BTC 6.3y.

Цель: найти features которые отличают wins от losses → построить фильтры.

Features:
  - wick_ratio (cur/prev)
  - zone_pct (height OB-D как % of cur close)
  - touch_delay_h (час от cur_close до touch)
  - reaction_delay_h (от touch до FVG c2_close)
  - fvg_tf (15m/20m)
  - fvg_size_pct (FVG height % of entry)
  - fvg_depth (relative position in OB-D zone)
  - ob_d_tf (1d/12h)
  - direction
  - hull_1h dir, rsi_1h, mh color, asvk zone at signal_time
  - year
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
from strategies.strategy_1_1_1 import detect_fvg

_E121 = Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_spec = _ilu.spec_from_file_location("etap121_core", _E121)
_e121 = _ilu.module_from_spec(_spec); _sys.modules["etap121_core"] = _e121
_spec.loader.exec_module(_e121)
collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
find_first_touch_and_invalidation = _e121.find_first_touch_and_invalidation
simulate = _e121.simulate
any_edge_inside = _e121.any_edge_inside

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec103 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec103); _sys.modules["etap103_core"] = _e103
_spec103.loader.exec_module(_e103)
build_score_series = _e103.build_score_series

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ENTRY_PCT = 0.70
SL_PCT = 0.35
RR = 2.0
MIN_SL_PCT = 1.0


def react_v2_detailed(ob_d, touch_t, inval_t, df_15m, df_20m):
    """V2: FVG-only + полные features."""
    for df_ltf, tf_min, tf_label in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
        df_w = df_ltf[(df_ltf.index >= touch_t) & (df_ltf.index < inval_t)]
        for k in range(2, len(df_w)):
            fvg = detect_fvg(df_w, k)
            if fvg is None or fvg.direction != ob_d.direction: continue
            if not any_edge_inside(fvg.bottom, fvg.top, ob_d.bottom, ob_d.top): continue
            fb, ft = fvg.bottom, fvg.top
            if ob_d.direction == "LONG":
                entry = fb + ENTRY_PCT * (ft - fb)
                sl = ob_d.bottom + SL_PCT * (fb - ob_d.bottom)
            else:
                entry = ft - ENTRY_PCT * (ft - fb)
                sl = ob_d.top - SL_PCT * (ob_d.top - ft)
            if MIN_SL_PCT > 0:
                d = entry * MIN_SL_PCT / 100
                if ob_d.direction == "LONG":
                    sl = min(sl, entry - d)
                else:
                    sl = max(sl, entry + d)
            if abs(entry - sl) <= 0: continue
            if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                continue
            signal_time = fvg.c2_time + pd.Timedelta(minutes=tf_min)
            # Features
            zone_pct = (ob_d.top - ob_d.bottom) / ob_d.top * 100
            touch_delay_h = (touch_t - ob_d.cur_close).total_seconds() / 3600
            reaction_delay_h = (signal_time - touch_t).total_seconds() / 3600
            fvg_size_pct = (ft - fb) / entry * 100
            # depth: для LONG = (entry - ob_d.bottom) / (ob_d.top - ob_d.bottom)
            if ob_d.direction == "LONG":
                fvg_depth = (entry - ob_d.bottom) / (ob_d.top - ob_d.bottom) if ob_d.top > ob_d.bottom else 0.5
            else:
                fvg_depth = (ob_d.top - entry) / (ob_d.top - ob_d.bottom) if ob_d.top > ob_d.bottom else 0.5
            return {
                "entry": entry, "sl": sl, "direction": ob_d.direction,
                "signal_time": signal_time,
                "reaction_tf": f"FVG-{tf_label}",
                # features
                "wick_ratio": ob_d.wick_ratio,
                "zone_pct": zone_pct,
                "touch_delay_h": touch_delay_h,
                "reaction_delay_h": reaction_delay_h,
                "fvg_tf": tf_label,
                "fvg_size_pct": fvg_size_pct,
                "fvg_depth": fvg_depth,
                "ob_d_tf": "1d" if ob_d.tf_hours == 24 else "12h",
            }
    return None


def hull_dir(close, t):
    """Hull-1h: close > hull[t-2] → up else down."""
    # Simple: используем etap_103 score_long как proxy
    # Здесь упрощённо — нужен hull series. Используем precomputed.
    return None  # will use precomputed score instead


def main():
    print("etap_122: forensic Wicked+Fractal OB-D + V2 (BTC 6.3y)")
    print()
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")
    df_2h = compose_from_base(df_1h, "2h")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    # EMA-2h
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    # Score
    print("[INFO] score series on 1h")
    score_long, score_short = build_score_series(df_1h)

    # Collect
    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    print(f"  Wicked+Fractal 1d: {len(wf_1d)}, 12h: {len(wf_12h)}")

    trades = []
    for ob_list, df_l1 in [(wf_1d, df_1d), (wf_12h, df_12h)]:
        for ob_d in ob_list:
            touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
            if touch_t is None: continue
            if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)
            setup = react_v2_detailed(ob_d, touch_t, inval_t, df_15m, df_20m)
            if setup is None: continue
            outcome, R = simulate(setup, df_1m)
            setup["outcome"] = outcome; setup["R"] = R
            setup["year"] = setup["signal_time"].year
            # EMA-2h flag
            t = setup["signal_time"]
            idx = df_2h.index.searchsorted(t, side="right") - 1
            if idx >= 0 and not pd.isna(df_2h["ema200"].iloc[idx]):
                c = float(df_2h["close"].iloc[idx]); e = float(df_2h["ema200"].iloc[idx])
                pro = c > e if setup["direction"] == "LONG" else c < e
                setup["ema_pro"] = pro
            else:
                setup["ema_pro"] = None
            # Score sign
            sc_series = score_long if setup["direction"] == "LONG" else score_short
            sidx = sc_series.index.searchsorted(t, side="right") - 1
            if sidx >= 0 and not pd.isna(sc_series.iloc[sidx]):
                setup["score"] = float(sc_series.iloc[sidx])
            else:
                setup["score"] = None
            trades.append(setup)

    # Dedup
    seen = {}
    for t in trades:
        k = (t["signal_time"], t["direction"], round(t["entry"], 2))
        if k not in seen: seen[k] = t
    unique = list(seen.values())
    closed = [t for t in unique if t["outcome"] in ("win", "loss")]
    wins = [t for t in closed if t["R"] > 0]
    losses = [t for t in closed if t["R"] < 0]
    print(f"\n  Closed: {len(closed)}  Wins: {len(wins)}  Losses: {len(losses)}  "
          f"WR: {len(wins)/len(closed)*100:.1f}%  PnL: {sum(t['R'] for t in closed):+.1f}R")

    df = pd.DataFrame(closed)

    print()
    print("=" * 92)
    print("Feature distributions: wins vs losses")
    print("=" * 92)

    numeric_features = ["wick_ratio", "zone_pct", "touch_delay_h", "reaction_delay_h",
                         "fvg_size_pct", "fvg_depth", "score"]
    print(f"{'Feature':<22} {'wins_mean':>10} {'wins_med':>10} {'loss_mean':>10} {'loss_med':>10} {'diff_med':>10}")
    print("-" * 92)
    for feat in numeric_features:
        w_vals = [t[feat] for t in wins if t.get(feat) is not None]
        l_vals = [t[feat] for t in losses if t.get(feat) is not None]
        if not w_vals or not l_vals:
            print(f"{feat:<22} no data"); continue
        w_mean = np.mean(w_vals); w_med = np.median(w_vals)
        l_mean = np.mean(l_vals); l_med = np.median(l_vals)
        diff = w_med - l_med
        print(f"{feat:<22} {w_mean:>10.3f} {w_med:>10.3f} {l_mean:>10.3f} {l_med:>10.3f} {diff:>+10.3f}")

    print()
    print("Categorical features (win rate by category):")
    print()
    for cat in ["fvg_tf", "ob_d_tf", "direction"]:
        print(f"  By {cat}:")
        groups = defaultdict(list)
        for t in closed: groups[t[cat]].append(t)
        for k, g in groups.items():
            W = sum(1 for t in g if t["R"] > 0)
            wr = W / len(g) * 100
            pnl = sum(t["R"] for t in g)
            print(f"    {k}: n={len(g)}  WR={wr:.1f}%  PnL={pnl:+.1f}R")
        print()

    # EMA-2h
    print("  By EMA-2h pro-trend:")
    for v in [True, False]:
        g = [t for t in closed if t.get("ema_pro") == v]
        if not g: continue
        W = sum(1 for t in g if t["R"] > 0)
        wr = W / len(g) * 100
        pnl = sum(t["R"] for t in g)
        print(f"    {'pro' if v else 'counter'}: n={len(g)}  WR={wr:.1f}%  PnL={pnl:+.1f}R")

    # Score sign
    print()
    print("  By score sign at signal_time:")
    for label, fn in [("score>+0.25", lambda s: s > 0.25),
                      ("0 < score <= +0.25", lambda s: 0 < s <= 0.25),
                      ("-0.25 <= score <= 0", lambda s: -0.25 <= s <= 0),
                      ("score < -0.25", lambda s: s < -0.25)]:
        g = [t for t in closed if t.get("score") is not None and fn(t["score"])]
        if not g: continue
        W = sum(1 for t in g if t["R"] > 0)
        wr = W / len(g) * 100
        pnl = sum(t["R"] for t in g)
        print(f"    {label}: n={len(g)}  WR={wr:.1f}%  PnL={pnl:+.1f}R")

    # By year
    print()
    print("  By year:")
    yr_groups = defaultdict(list)
    for t in closed: yr_groups[t["year"]].append(t)
    for y in sorted(yr_groups):
        g = yr_groups[y]
        W = sum(1 for t in g if t["R"] > 0)
        wr = W / len(g) * 100
        pnl = sum(t["R"] for t in g)
        print(f"    {y}: n={len(g)}  WR={wr:.1f}%  PnL={pnl:+.1f}R")

    # Quantile analysis на ключевых features
    print()
    print("=" * 92)
    print("Quantile analysis (split each feature into 4 buckets, show WR per bucket):")
    print("=" * 92)
    for feat in ["wick_ratio", "zone_pct", "touch_delay_h", "fvg_depth", "score"]:
        vals = [(t[feat], t["R"] > 0) for t in closed if t.get(feat) is not None]
        if len(vals) < 20: continue
        vals.sort(key=lambda x: x[0])
        n = len(vals)
        q1 = n // 4
        buckets = [vals[:q1], vals[q1:2*q1], vals[2*q1:3*q1], vals[3*q1:]]
        labels = ["Q1 (lowest)", "Q2", "Q3", "Q4 (highest)"]
        print(f"\n  {feat}:")
        for label, b in zip(labels, buckets):
            if not b: continue
            n_b = len(b); wr_b = sum(1 for _, w in b if w) / n_b * 100
            v_lo = b[0][0]; v_hi = b[-1][0]
            print(f"    {label}: range=[{v_lo:.3f}..{v_hi:.3f}]  n={n_b}  WR={wr_b:.1f}%")


if __name__ == "__main__":
    main()
