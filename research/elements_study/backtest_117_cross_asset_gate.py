"""Cross-asset гейт для Strategy 1.1.7 (iFVG-continuation, V2c = 4h-only).

Прежний вердикт: BTC 2024-2026 (2.3y) +37.5R @RR2.5, WR 39.4%, 0/3 bad years, decision PENDING.
Пробел: ни cross-asset, ни полная история, ни L/S-split (bull-drift?).

Этот скрипт переиспользует канонический детектор etap_95.detect_117_setups + simulate
(iFVG-4h → OB-1h(dir B) → FVG-15m, continuation в направлении B), прогоняет на
BTC/ETH/SOL по ПОЛНОЙ истории, RR ∈ {2.0, 2.5}, с год-разбивкой и LONG/SHORT-сплитом.

TF композируются из 1m (не зависим от наличия 4h/1d CSV по ETH/SOL).

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/elements_study/backtest_117_cross_asset_gate.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import etap_95_strategy_117_ifvg as e95  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RR_GRID = [2.0, 2.5]


def load_1m(sym: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    df.index.name = "open_time"
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    out = df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    out.index.name = "open_time"
    return out


def run_symbol(sym: str):
    df_1m = load_1m(sym)
    df_4h = resample(df_1m, "4h")
    df_1h = resample(df_1m, "1h")
    df_15m = resample(df_1m, "15min")
    for df in (df_4h, df_1h, df_15m):
        df["atr14"] = e95._e66.compute_atr(df, 14)

    setups = e95.detect_117_setups(df_4h, df_1h, df_15m, df_1m, "4h", allow_multi=3)

    out = {}
    for rr in RR_GRID:
        ow = ol = nf = ne = op = 0
        yearly = defaultdict(lambda: [0, 0, 0.0])     # year -> [w, l, R]
        side = {"LONG": [0, 0, 0.0], "SHORT": [0, 0, 0.0]}  # dir -> [w, l, R]
        for s in setups:
            o, R = e95.simulate(s, df_1m, rr=rr)
            yr = s["signal_time"].year
            d = s["direction"]
            if o == "win":
                ow += 1; yearly[yr][0] += 1; yearly[yr][2] += R
                side[d][0] += 1; side[d][2] += R
            elif o == "loss":
                ol += 1; yearly[yr][1] += 1; yearly[yr][2] += R
                side[d][1] += 1; side[d][2] += R
            elif o == "no_entry":
                ne += 1
            elif o == "open":
                op += 1
            else:
                nf += 1
        closed = ow + ol
        out[rr] = {
            "n": len(setups), "closed": closed, "w": ow, "l": ol, "nf": nf, "ne": ne, "open": op,
            "wr": ow / closed * 100 if closed else 0.0, "total": ow * rr - ol,
            "yearly": dict(yearly), "side": side,
        }
    return out


def main():
    results = {}
    for sym in SYMBOLS:
        print(f"loading + scanning {sym}...", flush=True)
        results[sym] = run_symbol(sym)

    print("\n" + "=" * 90)
    print("Strategy 1.1.7 iFVG-continuation (4h, V2c) — CROSS-ASSET, ПОЛНАЯ ИСТОРИЯ")
    print("=" * 90)
    print(f"{'sym':>7} {'RR':>4} {'sigs':>5} {'closed':>6} {'WR%':>6} {'totalR':>8} {'avgR':>7}  "
          f"{'L_n':>4} {'L_R':>7}  {'S_n':>4} {'S_R':>7}")
    for sym in SYMBOLS:
        for rr in RR_GRID:
            m = results[sym][rr]
            avg = m["total"] / m["closed"] if m["closed"] else 0
            L, S = m["side"]["LONG"], m["side"]["SHORT"]
            print(f"{sym:>7} {rr:>4.1f} {m['n']:>5} {m['closed']:>6} {m['wr']:>6.1f} "
                  f"{m['total']:>+8.1f} {avg:>+7.3f}  "
                  f"{L[0]+L[1]:>4} {L[2]:>+7.1f}  {S[0]+S[1]:>4} {S[2]:>+7.1f}")
        print()

    print("=" * 90)
    print("ГОД-РАЗБИВКА  RR=2.5  (totalR per year, + = плюсовой год)")
    print("=" * 90)
    years = list(range(2020, 2027))
    print(f"{'sym':>7}  " + "  ".join(f"{y:>7}" for y in years) + f"  {'+yrs':>6}")
    for sym in SYMBOLS:
        y = results[sym][2.5]["yearly"]
        cells, pos, tot_yrs = [], 0, 0
        for yr in years:
            if yr in y and (y[yr][0] + y[yr][1]) > 0:
                r = y[yr][2]; cells.append(f"{r:>+7.1f}"); tot_yrs += 1
                if r > 0:
                    pos += 1
            else:
                cells.append(f"{'-':>7}")
        print(f"{sym:>7}  " + "  ".join(cells) + f"  {pos:>3}/{tot_yrs}")


if __name__ == "__main__":
    main()
