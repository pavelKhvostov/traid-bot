"""etap_114: Floating TP для 1.1.4 BFJK portfolio.

Baseline (canonical etap_74): WR 64.3%, +107R на 115 closed (BTC 6.3y).
Применяем тот же momentum-score (Hull/MH/RSI/ASVK) + R_cap как для 1.1.1.

Сравниваем:
  - Baseline RR=2.0 (canonical)
  - D R_cap + score-exit (различные конфиги)

Tests: BTC 6.3y, потом ETH/SOL.
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

# Reuse 1.1.4 detector + build_orders from etap_66/74
_E66 = Path(__file__).parent / "etap_66_114_chains_survey.py"
_spec = _ilu.spec_from_file_location("etap66_core", _E66)
_e66 = _ilu.module_from_spec(_spec); _sys.modules["etap66_core"] = _e66
_spec.loader.exec_module(_e66)

_E74 = Path(__file__).parent / "etap_74_114_fixed_BFJK.py"
_spec74 = _ilu.spec_from_file_location("etap74_core", _E74)
_e74 = _ilu.module_from_spec(_spec74); _sys.modules["etap74_core"] = _e74
_spec74.loader.exec_module(_e74)

# Score from etap_103
_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec103 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec103); _sys.modules["etap103_core"] = _e103
_spec103.loader.exec_module(_e103)
build_score_series = _e103.build_score_series

# 20m for J/K chains
_e66.TF_HOURS["20m"] = 20/60
_e66.LIFE_DAYS["20m"] = 0.5

ALLOW_MULTI = 5
RR_BASELINE = 2.0
MAX_HOLD_DAYS = 7
START_DATE = "2020-01-01"


def collect_bfjk_setups(symbol, end_date=None):
    """Возвращает (setups_list, df_1m, df_1h) после полного 1.1.4 BFJK detect + dedup."""
    df_1d = load_df(symbol, "1d")
    df_4h = load_df(symbol, "4h")
    df_1h = load_df(symbol, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(symbol, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    cutoff = max(pd.Timestamp(START_DATE, tz="UTC"), df_1m.index[0])
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

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m), ("20m", df_20m)]:
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
        s = _e74.detect_fixed(*args, allow_multi=ALLOW_MULTI)
        for ss in s: ss["chain"] = name
        raw_setups.extend(s)

    # Dedup
    seen = {}
    for s in raw_setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k not in seen:
            seen[k] = {**s, "chains": [s["chain"]]}
        else:
            if s["chain"] not in seen[k]["chains"]:
                seen[k]["chains"].append(s["chain"])
    setups = list(seen.values())
    return setups, df_1m, df_1h, df_2h


def simulate_baseline_rr(s, df_1m, rr=RR_BASELINE):
    """Canonical 1.1.4 simulator (etap_74)."""
    tup = _e66.build_orders(s)
    if tup is None: return None
    entry, sl = tup
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
    outcome, R, et, xt = _e74.simulate_with_times(s, entry, sl, tp, df_1m, MAX_HOLD_DAYS)
    return {"outcome": outcome, "R": R, "entry": entry, "sl": sl, "tp": tp,
            "entry_time": et, "exit_time": xt, "exit_reason": "rr_fix"}


def simulate_floating_rcap(s, df_1m, df_1h, score_long, score_short,
                             R_cap=4.5, threshold=-0.25, confirm=2):
    """Floating TP: hard SL + R_cap + score-exit."""
    tup = _e66.build_orders(s)
    if tup is None: return None
    entry, sl = tup
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp_cap = entry + R_cap * risk if direction == "LONG" else entry - R_cap * risk
    tp_proxy = entry + RR_BASELINE * risk if direction == "LONG" else entry - RR_BASELINE * risk
    score_series = score_long if direction == "LONG" else score_short

    start = s["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return {"outcome": "no_data", "R": 0.0, "entry": entry, "sl": sl, "tp": tp_cap,
                "entry_time": None, "exit_time": None, "exit_reason": "no_data"}
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    times = df_1m.index[i0:i1]
    n = len(h)

    # no_entry check with tp_proxy
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre = np.where(h >= tp_proxy)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre = np.where(l <= tp_proxy)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i:
        return {"outcome": "no_entry", "R": 0.0, "entry": entry, "sl": sl, "tp": tp_cap,
                "entry_time": None, "exit_time": None, "exit_reason": "no_entry"}
    if ent_i >= n:
        return {"outcome": "not_filled", "R": 0.0, "entry": entry, "sl": sl, "tp": tp_cap,
                "entry_time": None, "exit_time": None, "exit_reason": "nf"}
    activation = times[ent_i]

    # Walk post-activation with checkpoints
    post_h = h[ent_i:]; post_l = l[ent_i:]
    post_ts = times[ent_i:]
    end_time = activation + pd.Timedelta(days=MAX_HOLD_DAYS)

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
        sc = score_series.iloc[score_idx]
        if pd.isna(sc): continue
        if sc <= threshold: consec += 1
        else: consec = 0
        if consec >= confirm:
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                floating_price = float(closes_1h[cp_close_idx])
                floating_time = cp
                break

    if cap_hit_idx is not None:
        return {"outcome": "win", "R": R_cap, "entry": entry, "sl": sl, "tp": tp_cap,
                "entry_time": activation, "exit_time": post_ts[cap_hit_idx],
                "exit_reason": "R_cap", "max_R": max_R}
    if sl_exit_idx is not None:
        return {"outcome": "loss", "R": -1.0, "entry": entry, "sl": sl, "tp": tp_cap,
                "entry_time": activation, "exit_time": post_ts[sl_exit_idx],
                "exit_reason": "sl_hit", "max_R": max_R}
    if floating_price is not None:
        R = (floating_price - entry)/risk if direction == "LONG" else (entry - floating_price)/risk
        outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
        return {"outcome": outc, "R": float(R), "entry": entry, "sl": sl, "tp": tp_cap,
                "entry_time": activation, "exit_time": floating_time,
                "exit_reason": "score_exit", "max_R": max_R}
    # max_hold
    last_c = float(df_1m["close"].values[i0:i1][-1])
    R = (last_c - entry)/risk if direction == "LONG" else (entry - last_c)/risk
    outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
    return {"outcome": outc, "R": float(R), "entry": entry, "sl": sl, "tp": tp_cap,
            "entry_time": activation, "exit_time": post_ts[-1],
            "exit_reason": "max_hold", "max_R": max_R}


def stats(trades, label):
    closed = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]
    if not closed: return None
    n = len(closed)
    W = sum(1 for t in closed if t["R"] > 0); L = sum(1 for t in closed if t["R"] < 0)
    wr = W/n*100
    pnl = sum(t["R"] for t in closed)
    Rs = sorted([t["R"] for t in closed], reverse=True)
    median_R = float(np.median(Rs))
    top5_pct = sum(Rs[:5])/pnl*100 if pnl > 0 else 0
    yearly = defaultdict(lambda: [0,0,0.0])
    for t in closed:
        y = pd.Timestamp(t.get("signal_time")).year if t.get("signal_time") else 0
        yearly[y][0 if t["R"]>0 else 1] += 1
        yearly[y][2] += t["R"]
    bad = sum(1 for y in yearly if yearly[y][2] < 0)
    return {"label": label, "n": n, "W": W, "L": L, "wr": wr, "pnl": pnl,
            "median_R": median_R, "max_R": max(Rs), "top5_pct": top5_pct,
            "bad": bad, "n_yrs": len(yearly)}


def main():
    print("etap_114: Floating TP для 1.1.4 BFJK (BTC 6.3y)")
    print("Reference (canonical etap_74): n=115, WR 64.3%, +107R")
    print()
    print("[INFO] collecting BFJK setups...")
    setups, df_1m, df_1h, df_2h = collect_bfjk_setups("BTCUSDT")
    # Inject signal_time as year/etc — we use existing fields
    print(f"  unique setups: {len(setups)}")
    score_long, score_short = build_score_series(df_1h)

    print()
    # Baseline
    base_trades = []
    for s in setups:
        r = simulate_baseline_rr(s, df_1m)
        if r is None: continue
        r["signal_time"] = s["signal_time"]
        r["direction"] = s["direction"]
        base_trades.append(r)
    base = stats(base_trades, "baseline RR=2.0")
    print(f"  {base['label']:<32}: n={base['n']:>3d} WR={base['wr']:5.1f}% PnL={base['pnl']:+7.1f}R "
          f"medR={base['median_R']:+.2f} maxR={base['max_R']:+.1f} top5={base['top5_pct']:.1f}% bad={base['bad']}/{base['n_yrs']}")

    # Variants
    configs = [
        ("D R_cap=2.5 th=0 cf=2", 2.5, 0.0, 2),
        ("D R_cap=3.0 th=0 cf=2", 3.0, 0.0, 2),
        ("D R_cap=3.5 th=0 cf=2", 3.5, 0.0, 2),
        ("D R_cap=4.0 th=0 cf=2", 4.0, 0.0, 2),
        ("D R_cap=4.5 th=0 cf=2", 4.5, 0.0, 2),
        ("D R_cap=4.5 th=-0.25 cf=2", 4.5, -0.25, 2),
        ("D R_cap=5.0 th=-0.25 cf=2", 5.0, -0.25, 2),
        ("D R_cap=3.5 th=0 cf=1", 3.5, 0.0, 1),
        ("D R_cap=4.5 th=-0.5 cf=1", 4.5, -0.5, 1),
    ]
    print()
    print(f"  {'Variant':<32} {'n':>4} {'WR':>6} {'PnL':>9} {'medR':>6} {'maxR':>5} {'top5%':>6} {'bad':>5}  pass")
    print("  " + "-"*100)
    results = [base]
    for label, R_cap, th, cf in configs:
        trades = []
        for s in setups:
            r = simulate_floating_rcap(s, df_1m, df_1h, score_long, score_short,
                                         R_cap=R_cap, threshold=th, confirm=cf)
            if r is None: continue
            r["signal_time"] = s["signal_time"]
            r["direction"] = s["direction"]
            trades.append(r)
        st = stats(trades, label)
        if st is None:
            print(f"  {label:<32}: no closed"); continue
        pass_ = "PASS" if (st["median_R"] > 0 and st["top5_pct"] < 25) else "    "
        print(f"  {st['label']:<32} {st['n']:>4d} {st['wr']:>5.1f}% {st['pnl']:>+8.1f}R "
              f"{st['median_R']:>+5.2f} {st['max_R']:>+4.1f} {st['top5_pct']:>5.1f}% "
              f"{st['bad']}/{st['n_yrs']}  {pass_}")
        results.append(st)

    # rank
    print()
    print("RANKED by PnL:")
    for r in sorted(results, key=lambda x: x["pnl"], reverse=True)[:5]:
        delta = r["pnl"] - base["pnl"]
        print(f"  {r['label']:<32}  PnL={r['pnl']:+7.1f}R  Δ={delta:+5.1f}R  "
              f"WR={r['wr']:.1f}%  medR={r['median_R']:+.2f}  top5={r['top5_pct']:.1f}%")


if __name__ == "__main__":
    main()
