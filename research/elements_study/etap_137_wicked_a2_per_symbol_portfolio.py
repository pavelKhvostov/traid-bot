"""etap_137: A2 portfolio с per-symbol optimal floating TP configs.

etap_136 grid выбрал:
  BTC: cap=5.0 th=-0.50 cf=1  (max PnL, WR 68%)  -- alt: cap=5.0 th=0.0 cf=1 (0 bad years)
  ETH: cap=5.0 th=-0.50 cf=3  (max PnL, WR 38%)

Тестируем portfolio merge с двумя BTC-конфигами:
  Variant A: max-PnL  (BTC cap=5.0 th=-0.5 cf=1 + ETH cap=5.0 th=-0.5 cf=3)
  Variant B: robust   (BTC cap=5.0 th=0.0 cf=1  + ETH cap=5.0 th=-0.5 cf=3)
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E121 = _Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_E131 = _Path(__file__).parent / "etap_131_wicked_4stage_strict_dedup.py"
_E128 = _Path(__file__).parent / "etap_128_115_improve.py"
_E103 = _Path(__file__).parent / "etap_103_floating_tp.py"
for nm, p in [("etap121_core", _E121), ("etap131_core", _E131),
               ("etap128_core", _E128), ("etap103_core", _E103)]:
    _spec = _ilu.spec_from_file_location(nm, p)
    _m = _ilu.module_from_spec(_spec); _sys.modules[nm] = _m
    _spec.loader.exec_module(_m)

_e121 = _sys.modules["etap121_core"]
_e131 = _sys.modules["etap131_core"]
_e128 = _sys.modules["etap128_core"]
_e103 = _sys.modules["etap103_core"]

collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
first_setup_per_ob = _e131.first_setup_per_ob
simulate_floating = _e128.simulate_floating
build_score_series = _e103.build_score_series

SYMBOLS = [("BTCUSDT", "2020-01-01"), ("ETHUSDT", "2020-05-15")]


def collect_trades_with_config(symbol, start_date, cap, th, cf):
    df_1d = load_df(symbol, "1d"); df_1h = load_df(symbol, "1h"); df_1m = load_df(symbol, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h"); df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m"); df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(start_date, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]
    setups = []
    for ob, df_l1 in all_ob_d:
        s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                               macro_kind="FVG", swept_required=False,
                               entry_pct=0.80, sl_pct=0.35)
        if s is not None: setups.append(s)
    score_long, score_short = build_score_series(df_1h)
    trades = []
    for s in setups:
        outc, R = simulate_floating(s, s["entry"], s["sl"], df_1m, df_1h,
                                     score_long, score_short, R_cap=cap,
                                     threshold=th, confirm=cf)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year,
                            "time": s["signal_time"], "direction": s["direction"],
                            "symbol": symbol})
    return trades


def analyze_portfolio(label, trades):
    trades.sort(key=lambda t: t["time"])
    by_year = defaultdict(lambda: {"n":0, "W":0, "R":0.0})
    for t in trades:
        by_year[t["year"]]["n"] += 1
        if t["R"] > 0: by_year[t["year"]]["W"] += 1
        by_year[t["year"]]["R"] += t["R"]
    bad = sum(1 for yr in by_year if by_year[yr]["R"] < 0)
    n = sum(by_year[yr]["n"] for yr in by_year)
    R = sum(by_year[yr]["R"] for yr in by_year)
    W = sum(by_year[yr]["W"] for yr in by_year)
    print(f"\n  {label}")
    print(f"  Portfolio: n={n} WR={W/n*100:.1f}% PnL={R:+.1f}R bad={bad}/{len(by_year)} R/tr={R/n:+.2f}")
    for yr in sorted(by_year):
        d = by_year[yr]
        wr = d["W"]/d["n"]*100 if d["n"] else 0
        marker = " <- BAD" if d["R"] < 0 else ""
        print(f"    {yr}: n={d['n']:>3d} WR={wr:>4.1f}% PnL={d['R']:>+6.1f}R{marker}")
    cum = 0.0; peak = 0.0; max_dd = 0.0
    for t in trades:
        cum += t["R"]; peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    print(f"  Max DD: -{max_dd:.1f}R  Peak: {peak:.1f}R  Final: {cum:.1f}R")


def main():
    print("etap_137: A2 portfolio per-symbol optimal floating TP")
    print()
    # Variant A: max-PnL
    btc_trades_A = collect_trades_with_config("BTCUSDT", "2020-01-01", 5.0, -0.5, 1)
    eth_trades   = collect_trades_with_config("ETHUSDT", "2020-05-15", 5.0, -0.5, 3)
    analyze_portfolio("Variant A (max-PnL): BTC cap=5.0 th=-0.5 cf=1 + ETH cap=5.0 th=-0.5 cf=3",
                      btc_trades_A + eth_trades)

    # Variant B: robust (BTC 0-bad config)
    btc_trades_B = collect_trades_with_config("BTCUSDT", "2020-01-01", 5.0, 0.0, 1)
    analyze_portfolio("Variant B (robust): BTC cap=5.0 th=0.0 cf=1 + ETH cap=5.0 th=-0.5 cf=3",
                      btc_trades_B + eth_trades)

    # Reference: global config (etap_135)
    print("\n  Reference: etap_135 global config cap=5.0 th=-0.5 cf=3 -> +77.9R / 0 bad / 146 closed")


if __name__ == "__main__":
    main()
