"""Этап 31: RDRB+ (MMXM/Lumi version) — balanced range above FVG protects it.

RDRB+ для LONG bullish setup:
  1. FVG bullish detected (gap up)
  2. В следующих N барах: range consolidation выше FVG.top
     - Все low баров > FVG.top (FVG не фильнут)
     - Range size мал (max(highs) - min(lows) < threshold)
     - Минимум 3 бара в range
  3. Отсюда: continuation entry
     - Entry: на close consolidation (последний бар RDRB+)
     - SL: ниже RDRB+ low (или FVG.bottom)
     - TP: предыдущий high * 2 (continuation target)

Для SHORT — зеркально (range ниже FVG.bottom).

Тесты:
  A. % FVGs которые получают RDRB+ структуру
  B. Continuation backtest: WR/R-tr для FVG-with-RDRB+ vs FVG-without
  C. Сравнение с baseline FVG-only continuation
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

LOOKFORWARD = 10  # сколько баров после FVG для поиска RDRB+
MIN_RANGE_BARS = 3  # минимум баров в RDRB+ range
RANGE_SIZE_MULT = 2.5  # range_size <= MULT * fvg_size = consolidation
RR = 1.0

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_rdrb_plus(df, fvg_idx, fvg_top, fvg_bottom, direction, lookforward):
    """Returns dict if RDRB+ structure found, None otherwise.
    Result: {confirm_idx, range_low, range_high, n_bars_in_range}
    """
    fvg_size = fvg_top - fvg_bottom
    if fvg_size <= 0:
        return None
    end_idx = min(fvg_idx + 1 + lookforward, len(df))
    bars = []
    for j in range(fvg_idx + 1, end_idx):
        h = float(df.iloc[j]["high"])
        l = float(df.iloc[j]["low"])
        if direction == "LONG":
            if l < fvg_top:
                # FVG mitigated -> no protection -> not RDRB+
                if len(bars) >= MIN_RANGE_BARS:
                    # already had range, but now broken — still RDRB+ if accumulated bars met criteria
                    pass
                return None  # strict: any mitigation breaks it
            bars.append({"idx": j, "high": h, "low": l})
        else:  # SHORT
            if h > fvg_bottom:
                return None
            bars.append({"idx": j, "high": h, "low": l})
        # check if we have enough bars
        if len(bars) >= MIN_RANGE_BARS:
            highs = [b["high"] for b in bars]
            lows = [b["low"] for b in bars]
            range_size = max(highs) - min(lows)
            if range_size <= RANGE_SIZE_MULT * fvg_size:
                # this is RDRB+
                return {"confirm_idx": j,
                         "range_low": min(lows),
                         "range_high": max(highs),
                         "n_bars": len(bars)}
            else:
                # range too wide — moved too far — not consolidation
                return None
    return None


def simulate_continuation(df, entry, sl, tp, start_idx, direction, max_bars=50):
    """First-hit simulation на следующих barах TF."""
    end_idx = min(start_idx + max_bars, len(df))
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    for j in range(start_idx, end_idx):
        h = float(df.iloc[j]["high"])
        l = float(df.iloc[j]["low"])
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
        fvgs.append({"idx": idx, "direction": f.direction,
                      "bottom": f.bottom, "top": f.top, "c2_time": f.c2_time})
    print(f"FVGs detected: {len(fvgs)}")

    # check RDRB+ for each
    fvg_with = []
    fvg_without = []
    for f in fvgs:
        rdrb = detect_rdrb_plus(df, f["idx"], f["top"], f["bottom"],
                                 f["direction"], LOOKFORWARD)
        if rdrb:
            fvg_with.append({**f, "rdrb": rdrb})
        else:
            fvg_without.append(f)
    pct_with = len(fvg_with) / len(fvgs) * 100 if fvgs else 0
    print(f"FVG with RDRB+:    {len(fvg_with)} ({pct_with:.1f}%)")
    print(f"FVG without RDRB+: {len(fvg_without)}")

    # ----- Backtest A: continuation from FVG with RDRB+ -----
    # Entry: buy at confirm_idx close + ATR factor (or at break of range_high)
    # Simpler: entry at range_high break, sl at range_low, tp = entry + RR * risk
    rows_with = []
    for f in fvg_with:
        rdrb = f["rdrb"]
        confirm_idx = rdrb["confirm_idx"]
        if f["direction"] == "LONG":
            entry = rdrb["range_high"]  # buy stop at top of range
            sl = rdrb["range_low"]
        else:
            entry = rdrb["range_low"]
            sl = rdrb["range_high"]
        risk = abs(entry - sl)
        if risk <= 0: continue
        if f["direction"] == "LONG":
            tp = entry + RR * risk
        else:
            tp = entry - RR * risk
        out, R = simulate_continuation(df, entry, sl, tp,
                                         confirm_idx + 1, f["direction"])
        rows_with.append({"outcome": out, "R": R})
    df_with = pd.DataFrame(rows_with)

    # ----- Backtest B: continuation from FVG WITHOUT RDRB+ (baseline) -----
    # Entry: same logic but using FVG.top/bottom as range proxy
    rows_without = []
    for f in fvg_without:
        if f["direction"] == "LONG":
            entry = f["top"] + 0.1 * (f["top"] - f["bottom"])  # break above FVG top
            sl = f["bottom"]
        else:
            entry = f["bottom"] - 0.1 * (f["top"] - f["bottom"])
            sl = f["top"]
        risk = abs(entry - sl)
        if risk <= 0: continue
        if f["direction"] == "LONG":
            tp = entry + RR * risk
        else:
            tp = entry - RR * risk
        out, R = simulate_continuation(df, entry, sl, tp,
                                         f["idx"] + 1, f["direction"])
        rows_without.append({"outcome": out, "R": R})
    df_without = pd.DataFrame(rows_without)

    def stats(df_e, label):
        if df_e.empty:
            print(f"  {label}: no data"); return None
        closed = df_e[df_e["outcome"].isin(["win", "loss"])]
        if closed.empty:
            print(f"  {label}: no closed"); return None
        n = len(df_e); nc = len(closed)
        w = (closed["outcome"] == "win").sum()
        return {"label": label, "n": n, "closed": nc,
                 "WR": round(w/nc*100, 1),
                 "total_R": round(closed["R"].sum(), 1),
                 "R_tr": round(closed["R"].mean(), 3)}

    s_with = stats(df_with, "FVG WITH RDRB+")
    s_without = stats(df_without, "FVG WITHOUT")

    print(f"\nContinuation backtest (RR={RR}):")
    if s_with: print(f"  WITH RDRB+: n={s_with['n']}, closed={s_with['closed']}, "
                      f"WR={s_with['WR']}%, R/tr={s_with['R_tr']}")
    if s_without: print(f"  WITHOUT:    n={s_without['n']}, closed={s_without['closed']}, "
                         f"WR={s_without['WR']}%, R/tr={s_without['R_tr']}")
    if s_with and s_without:
        print(f"  delta WR:    {s_with['WR'] - s_without['WR']:+.1f}pp")
        print(f"  delta R/tr:  {s_with['R_tr'] - s_without['R_tr']:+.3f}")

    return {"tf": tf_label, "n_fvg": len(fvgs), "n_with_rdrb_plus": len(fvg_with),
             "pct_with": round(pct_with, 1),
             "with_WR": s_with["WR"] if s_with else None,
             "with_Rtr": s_with["R_tr"] if s_with else None,
             "without_WR": s_without["WR"] if s_without else None,
             "without_Rtr": s_without["R_tr"] if s_without else None}


def main():
    rows = []
    for tf in ["1h", "2h", "4h", "12h", "1d"]:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        rows.append(analyze_tf(df, tf))

    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(pd.DataFrame(rows).to_string(index=False))
    pd.DataFrame(rows).to_csv(OUT_DIR / "etap31_rdrb_plus.csv", index=False)


if __name__ == "__main__":
    main()
