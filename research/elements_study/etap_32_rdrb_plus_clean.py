"""Этап 32: честный тест RDRB+ как ПРЕДИКТОРА (не trade entry).

Логика:
  Same entry/SL/TP для обеих групп:
    Entry = FVG.c2 close
    SL    = FVG.bottom - 0.3*ATR (LONG) или FVG.top + 0.3*ATR (SHORT)
    TP    = entry + RR * |entry - SL|

  Compare:
    A) FVG WITHOUT RDRB+ (no consolidation above, либо immediate move)
    B) FVG WITH RDRB+ (consolidated above, FVG protected)

Если RDRB+ ИСТИННО предиктор continuation — группа B должна иметь WR > A.
Если group B не лучше A — RDRB+ не несёт edge.

Также testим разные RR (1.0, 1.5, 2.0) и lookforward windows.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"

LOOKFORWARD = 10
MIN_RANGE_BARS = 3
RANGE_SIZE_MULT = 2.5
SL_BUF_ATR = 0.3
RRS = [1.0, 1.5, 2.0]
MAX_HOLD_BARS = 50

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_rdrb_plus(df, fvg_idx, fvg_top, fvg_bottom, direction):
    fvg_size = fvg_top - fvg_bottom
    if fvg_size <= 0: return None
    end_idx = min(fvg_idx + 1 + LOOKFORWARD, len(df))
    bars = []
    for j in range(fvg_idx + 1, end_idx):
        h = float(df.iloc[j]["high"]); l = float(df.iloc[j]["low"])
        if direction == "LONG":
            if l < fvg_top: return None
        else:
            if h > fvg_bottom: return None
        bars.append((h, l))
        if len(bars) >= MIN_RANGE_BARS:
            highs = [b[0] for b in bars]; lows = [b[1] for b in bars]
            range_size = max(highs) - min(lows)
            if range_size <= RANGE_SIZE_MULT * fvg_size:
                return {"confirm_idx": j, "n_bars": len(bars)}
            else:
                return None
    return None


def simulate(df, entry, sl, tp, start_idx, direction, max_bars=MAX_HOLD_BARS):
    end_idx = min(start_idx + max_bars, len(df))
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    activation = None
    # for fixed-entry test: ENTRY = c2_close happens at c2 close = idx+1 open
    # we just check if SL/TP from start_idx forward
    for j in range(start_idx, end_idx):
        h = float(df.iloc[j]["high"]); l = float(df.iloc[j]["low"])
        if direction == "LONG":
            if l <= sl: return ("loss", -1.0)
            if h >= tp: return ("win", (tp-entry)/risk)
        else:
            if h >= sl: return ("loss", -1.0)
            if l <= tp: return ("win", (entry-tp)/risk)
    return ("open", 0.0)


def analyze_tf(df, tf_label):
    print(f"\n{'='*60}\n{tf_label}: {len(df)} bars\n{'='*60}")
    df = df.copy()
    df["atr14"] = compute_atr(df)

    fvgs = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        atr = float(df["atr14"].iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        fvgs.append({"idx": idx, "direction": f.direction,
                      "bottom": f.bottom, "top": f.top, "atr": atr})

    fvg_with = []; fvg_without = []
    for f in fvgs:
        rdrb = detect_rdrb_plus(df, f["idx"], f["top"], f["bottom"], f["direction"])
        if rdrb:
            fvg_with.append(f)
        else:
            fvg_without.append(f)
    print(f"FVGs: {len(fvgs)}; WITH RDRB+: {len(fvg_with)} ({len(fvg_with)/len(fvgs)*100:.1f}%)")

    def bt(fvgs_list, rr):
        rows = []
        for f in fvgs_list:
            # Entry = c2 close
            c2_close = float(df.iloc[f["idx"]]["close"])
            entry = c2_close
            atr = f["atr"]
            if f["direction"] == "LONG":
                sl = f["bottom"] - SL_BUF_ATR * atr
                tp = entry + rr * abs(entry - sl)
            else:
                sl = f["top"] + SL_BUF_ATR * atr
                tp = entry - rr * abs(entry - sl)
            out, R = simulate(df, entry, sl, tp, f["idx"] + 1, f["direction"])
            rows.append({"outcome": out, "R": R})
        df_e = pd.DataFrame(rows)
        closed = df_e[df_e["outcome"].isin(["win", "loss"])]
        if closed.empty: return None
        n = len(df_e); nc = len(closed)
        w = (closed["outcome"] == "win").sum()
        return {"n": n, "closed": nc,
                 "WR": round(w/nc*100, 1),
                 "total_R": round(closed["R"].sum(), 1),
                 "R_tr": round(closed["R"].mean(), 3)}

    print(f"\n{'RR':<6}{'group':<14}{'n':<6}{'closed':<8}{'WR':<8}{'R/tr':<8}{'total_R':<10}")
    for rr in RRS:
        for label, group in [("WITHOUT", fvg_without), ("WITH RDRB+", fvg_with)]:
            s = bt(group, rr)
            if s:
                print(f"{rr:<6}{label:<14}{s['n']:<6}{s['closed']:<8}"
                        f"{s['WR']}%{'':<3}{s['R_tr']}{'':<3}{s['total_R']}")


def main():
    for tf in ["1h", "4h", "12h", "1d"]:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        analyze_tf(df, tf)


if __name__ == "__main__":
    main()
