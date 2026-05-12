"""Этап 33: RDRB+ filter БЕЗ lookahead bug.

Critical fix vs etap_32:
  - Entry NOT at FVG c2.close (lookahead — мы ещё не знаем будет ли RDRB+)
  - Entry на confirm_idx.close (когда RDRB+ полностью сформирована)
  - SL/TP считаются от confirm_idx onwards

Это true real-time tradable test.

Группы:
  A) FVG WITHOUT RDRB+: entry at c2.close (no waiting), as baseline
     - same as raw FVG continuation backtest
  B) FVG WITH RDRB+: entry at confirm_idx.close (waited for RDRB+ to form)

Это РАЗНЫЕ entry timings но это и есть то как стратегия работала бы в real time.
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
            fvg_with.append({**f, "rdrb": rdrb})
        else:
            fvg_without.append(f)
    print(f"FVGs: {len(fvgs)}; WITH RDRB+: {len(fvg_with)} ({len(fvg_with)/len(fvgs)*100:.1f}%)")

    def bt(fvgs_list, rr, entry_at_confirm=False):
        rows = []
        for f in fvgs_list:
            if entry_at_confirm and "rdrb" in f:
                ent_idx = f["rdrb"]["confirm_idx"]
            else:
                ent_idx = f["idx"]
            entry = float(df.iloc[ent_idx]["close"])
            atr_at_entry = float(df["atr14"].iloc[ent_idx])
            if pd.isna(atr_at_entry) or atr_at_entry <= 0:
                continue
            if f["direction"] == "LONG":
                # SL = FVG.bottom - 0.3*ATR (FVG protection level)
                sl = f["bottom"] - SL_BUF_ATR * atr_at_entry
                if sl >= entry:
                    continue  # invalid (FVG already mitigated below entry)
                tp = entry + rr * abs(entry - sl)
            else:
                sl = f["top"] + SL_BUF_ATR * atr_at_entry
                if sl <= entry:
                    continue
                tp = entry - rr * abs(entry - sl)
            out, R = simulate(df, entry, sl, tp, ent_idx + 1, f["direction"])
            rows.append({"outcome": out, "R": R})
        df_e = pd.DataFrame(rows)
        if df_e.empty: return None
        closed = df_e[df_e["outcome"].isin(["win", "loss"])]
        if closed.empty: return None
        n = len(df_e); nc = len(closed)
        w = (closed["outcome"] == "win").sum()
        return {"n": n, "closed": nc,
                 "WR": round(w/nc*100, 1),
                 "total_R": round(closed["R"].sum(), 1),
                 "R_tr": round(closed["R"].mean(), 3)}

    print(f"\n{'RR':<6}{'group':<22}{'n':<6}{'closed':<8}{'WR':<8}{'R/tr':<10}{'total_R':<10}")
    for rr in RRS:
        # WITHOUT: entry at FVG c2 close (no wait)
        s_wo = bt(fvg_without, rr, entry_at_confirm=False)
        # WITH RDRB+ NO LOOKAHEAD: entry at confirm_idx.close (waited)
        s_w = bt(fvg_with, rr, entry_at_confirm=True)
        # WITH RDRB+ LOOKAHEAD (for comparison): entry at FVG c2 close (cheating)
        s_w_cheat = bt(fvg_with, rr, entry_at_confirm=False)
        for label, s in [("WITHOUT", s_wo),
                          ("WITH RDRB+ honest", s_w),
                          ("WITH RDRB+ lookahead", s_w_cheat)]:
            if s:
                print(f"{rr:<6}{label:<22}{s['n']:<6}{s['closed']:<8}"
                        f"{s['WR']}%{'':<3}{s['R_tr']:<10}{s['total_R']}")


def main():
    for tf in ["1h", "4h", "12h", "1d"]:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        analyze_tf(df, tf)


if __name__ == "__main__":
    main()
