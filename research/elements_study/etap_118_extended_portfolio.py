"""etap_118: Extended portfolio = BFJK + 3 новые цепочки (E-4a, B-3a, B-2d).

Сравнение с canonical BFJK (+107R / 1 bad year).

Новые цепочки (из etap_117 survey):
  E-4a: FVG-1d + OB-4h + OB-2h + FVG-20m   (+24R, 30 closed, 0 bad ★)
  B-3a: FVG-12h + OB-4h + OB-2h + FVG-15m  (+23R, 43 closed)
  B-2d: FVG-12h + FVG-4h + OB-1h + FVG-15m (+24R, 33 closed, FVG-4h L2)

Тестируем:
  1. Canonical BFJK (reference)
  2. Extended 7-chain portfolio (BFJK + 3 new)
  3. Extended 7-chain + EMA-2h filter
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

_E116 = Path(__file__).parent / "etap_116_fvg_d_strategy_explorer.py"
_spec = _ilu.spec_from_file_location("etap116_core", _E116)
_e116 = _ilu.module_from_spec(_spec); _sys.modules["etap116_core"] = _e116
_spec.loader.exec_module(_e116)

detect_generic_4stage = _e116.detect_generic_4stage
collect_rdrb_zones = _e116.collect_rdrb_zones
compute_atr = _e116.compute_atr
_e66 = _e116._e66
_e66.TF_HOURS["20m"] = 20/60
_e66.LIFE_DAYS["20m"] = 0.5

_E74 = Path(__file__).parent / "etap_74_114_fixed_BFJK.py"
_spec74 = _ilu.spec_from_file_location("etap74_core", _E74)
_e74 = _ilu.module_from_spec(_spec74); _sys.modules["etap74_core"] = _e74
_spec74.loader.exec_module(_e74)

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ALLOW_MULTI = 5
RR = 2.0
MAX_HOLD_DAYS = 7


def filter_ema_2h(setup, df_2h):
    t = setup["signal_time"]
    idx = df_2h.index.searchsorted(t, side="right") - 1
    if idx < 0 or pd.isna(df_2h["ema200"].iloc[idx]): return False
    c = float(df_2h["close"].iloc[idx]); e = float(df_2h["ema200"].iloc[idx])
    return c > e if setup["direction"] == "LONG" else c < e


def evaluate_with_dedup(setups_per_chain, df_1m, df_2h=None, apply_ema_filter=False):
    """Принимает {chain_name: setups}, делает union dedup, симулирует."""
    seen = {}
    for chain_name, setups in setups_per_chain.items():
        for s in setups:
            k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
            if k not in seen:
                seen[k] = {**s, "chains": [chain_name]}
            else:
                if chain_name not in seen[k]["chains"]:
                    seen[k]["chains"].append(chain_name)
    setups = list(seen.values())
    if apply_ema_filter and df_2h is not None:
        setups = [s for s in setups if filter_ema_2h(s, df_2h)]
    print(f"    unique setups: {len(setups)}")

    rows = []
    for s in sorted(setups, key=lambda x: x["signal_time"]):
        tup = _e66.build_orders(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + RR*risk if s["direction"] == "LONG" else entry - RR*risk
        outcome, R, et, xt = _e74.simulate_with_times(s, entry, sl, tp, df_1m, MAX_HOLD_DAYS)
        rows.append({
            "year": s["year"], "direction": s["direction"], "chain": "+".join(sorted(s["chains"])),
            "outcome": outcome, "R": R, "signal_time": s["signal_time"],
        })
    return pd.DataFrame(rows)


def stats(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])]
    nc = len(closed)
    if nc == 0:
        print(f"  {label}: no closed"); return None
    W = (closed["R"] > 0).sum(); L_ = (closed["R"] < 0).sum()
    wr = W / nc * 100
    pnl = closed["R"].sum()
    yr = closed.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    Rs = sorted(closed["R"].tolist(), reverse=True)
    top5 = sum(Rs[:5]) / pnl * 100 if pnl > 0 else 0
    yrs_str = "  ".join(f"{int(y)}:{r:+.0f}" for y, r in yr.sort_index().items())
    print(f"  {label}:")
    print(f"    n_total={len(df)}  closed={nc}  W/L={W}/{L_}  WR={wr:.1f}%  PnL={pnl:+.1f}R  "
          f"top5={top5:.1f}%  bad={bad}/{len(yr)}")
    print(f"    by year: {yrs_str}")
    return {"label": label, "n": nc, "wr": wr, "pnl": pnl, "top5": top5,
            "bad": bad, "n_yrs": len(yr)}


def main():
    print("etap_118: Extended portfolio = BFJK + E-4a + B-3a + B-2d (BTC 6.3y)")
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
        df["atr14"] = compute_atr(df, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    # zones
    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")
    fvgs_4h = _e66.collect_fvgs(df_4h, df_4h["atr14"], "4h")

    # detect all 7 chains
    print("[INFO] detecting all 7 chains")
    chains = {}
    # Canonical BFJK
    chains["B"] = detect_generic_4stage(fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    chains["F"] = detect_generic_4stage(fvgs_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m", df_1d, allow_multi=ALLOW_MULTI)
    chains["J"] = detect_generic_4stage(fvgs_1d, obs_4h, obs_1h, fvgs_20m, "1d", "4h", "1h", "20m", df_1d, allow_multi=ALLOW_MULTI)
    chains["K"] = detect_generic_4stage(fvgs_12h, obs_4h, obs_1h, fvgs_20m, "12h", "4h", "1h", "20m", df_12h, allow_multi=ALLOW_MULTI)
    # New chains
    chains["E-4a"] = detect_generic_4stage(fvgs_1d, obs_4h, obs_2h, fvgs_20m, "1d", "4h", "2h", "20m", df_1d, allow_multi=ALLOW_MULTI)
    chains["B-3a"] = detect_generic_4stage(fvgs_12h, obs_4h, obs_2h, fvgs_15m, "12h", "4h", "2h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    chains["B-2d"] = detect_generic_4stage(fvgs_12h, fvgs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)

    for name, s in chains.items():
        print(f"  {name}: {len(s)} setups")

    print()
    print("=" * 80)
    print("1. Canonical BFJK (reference)")
    print("=" * 80)
    bfjk = {k: chains[k] for k in ["B", "F", "J", "K"]}
    df_bfjk = evaluate_with_dedup(bfjk, df_1m)
    s_bfjk = stats(df_bfjk, "BFJK")

    print()
    print("=" * 80)
    print("2. Extended 7-chain (BFJK + E-4a + B-3a + B-2d)")
    print("=" * 80)
    ext = {k: chains[k] for k in ["B", "F", "J", "K", "E-4a", "B-3a", "B-2d"]}
    df_ext = evaluate_with_dedup(ext, df_1m)
    s_ext = stats(df_ext, "Extended-7")

    print()
    print("=" * 80)
    print("3. Extended 7-chain + EMA-2h filter")
    print("=" * 80)
    df_ext_ema = evaluate_with_dedup(ext, df_1m, df_2h=df_2h, apply_ema_filter=True)
    s_ext_ema = stats(df_ext_ema, "Extended-7 + EMA")

    print()
    print("=" * 80)
    print("4. BFJK + EMA-2h filter (для сравнения вклада фильтра)")
    print("=" * 80)
    df_bfjk_ema = evaluate_with_dedup(bfjk, df_1m, df_2h=df_2h, apply_ema_filter=True)
    s_bfjk_ema = stats(df_bfjk_ema, "BFJK + EMA")

    # Chain breakdown в extended
    print()
    print("=" * 80)
    print("Extended-7 by chain (без EMA):")
    print("=" * 80)
    closed = df_ext[df_ext["outcome"].isin(["win", "loss"])]
    chain_stats = closed.groupby("chain").agg(n=("R", "size"), W=("R", lambda x: (x>0).sum()),
                                                pnl=("R", "sum"))
    chain_stats["WR"] = chain_stats["W"] / chain_stats["n"] * 100
    chain_stats = chain_stats.sort_values("pnl", ascending=False)
    print(chain_stats.to_string())

    # FINAL comparison
    print()
    print("=" * 88)
    print("FINAL — Portfolio comparison")
    print("=" * 88)
    print(f"  {'Config':<28} {'n':>4} {'WR':>6} {'PnL':>9} {'top5%':>6} {'bad':>5}")
    print("  " + "-"*68)
    for s in [s_bfjk, s_bfjk_ema, s_ext, s_ext_ema]:
        if s is None: continue
        print(f"  {s['label']:<28} {s['n']:>4d} {s['wr']:>5.1f}% "
              f"{s['pnl']:>+8.1f}R {s['top5']:>5.1f}% {s['bad']}/{s['n_yrs']}")


if __name__ == "__main__":
    main()
