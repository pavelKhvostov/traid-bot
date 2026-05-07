"""H15 — Position sizing по confluence-stack.

Размер позиции масштабируется в зависимости от количества выполненных
ASVK-условий:
  base = 1.0R
  +0.5R если aligned div (H1)
  +0.5R если 4h-RSI на правильной стороне 50 (H9)
  +0.5R если DEEP div (H8 top 50% по depth)
  +0.5R если pct-aligned (H17 LONG в pct<25 или SHORT в pct>75)

Max = 3.0R. Не меняет WR, перераспределяет PnL по «качеству» сетапа.

Сравнение с baseline (всё по 1R) и с «hard filter only» (только сделки
с confluence_score >= threshold).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df

ENRICHED_4H = Path("signals/strategy_3_2_multi_tf_h9.csv")
OUT_CSV = Path("signals/strategy_3_2_h15.csv")
RR = 1.0


def main():
    print(f"[INFO] загрузка enriched (multi_tf): {ENRICHED_4H}")
    df = pd.read_csv(ENRICHED_4H)
    print(f"  rows: {len(df)}")

    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    total = len(closed)
    long_mask = closed["direction"] == "LONG"
    short_mask = closed["direction"] == "SHORT"

    # Confluence flags
    aligned_long_div = long_mask & (
        (closed["bull_div_in_window"] == True)
        | (closed["h_bull_div_in_window"] == True)
    )
    aligned_short_div = short_mask & (
        (closed["bear_div_in_window"] == True)
        | (closed["h_bear_div_in_window"] == True)
    )
    flag_div = aligned_long_div | aligned_short_div  # H1

    # H9 — 4h side of 50
    flag_4h_side = (long_mask & (closed["rsi_4h_at_signal"] < 50)) | \
                   (short_mask & (closed["rsi_4h_at_signal"] >= 50))

    # H8 — deep div: max depth среди divs в окне ≥ median (только если есть div)
    div_depths = closed[[
        "max_bull_depth_in_window", "max_h_bull_depth_in_window",
        "max_bear_depth_in_window", "max_h_bear_depth_in_window",
    ]].max(axis=1)
    median_depth = div_depths[flag_div].median() if flag_div.any() else np.nan
    flag_deep = flag_div & (div_depths >= median_depth)

    # H17 — pct-aligned (counter-trend extremum)
    has_pct = closed["z_pct_at_signal"].notna()
    bull_pct = has_pct & (closed["z_pct_at_signal"] > 0.75)
    bear_pct = has_pct & (closed["z_pct_at_signal"] < 0.25)
    flag_pct = (bear_pct & long_mask) | (bull_pct & short_mask)

    # Confluence score
    closed["flag_div"] = flag_div.astype(int)
    closed["flag_4h_side"] = flag_4h_side.astype(int)
    closed["flag_deep"] = flag_deep.astype(int)
    closed["flag_pct"] = flag_pct.astype(int)
    closed["confluence_score"] = (
        closed["flag_div"] + closed["flag_4h_side"] + closed["flag_deep"] + closed["flag_pct"]
    )
    closed["position_size"] = 1.0 + 0.5 * closed["confluence_score"]

    # PnL с sizing
    win_mask = closed["outcome"] == "win"
    loss_mask = closed["outcome"] == "loss"
    closed["sized_R"] = np.where(win_mask, closed["position_size"] * RR,
                                 np.where(loss_mask, -closed["position_size"], 0))
    closed.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")

    print()
    print("=" * 100)
    print(f"BASELINE  closed={total}  W={int(win_mask.sum())}  "
          f"WR={(win_mask).mean()*100:.1f}%  PnL=+{int(win_mask.sum())*RR - int(loss_mask.sum()):.1f}R")
    print()

    print("Распределение по confluence_score:")
    by_score = closed.groupby("confluence_score").agg(
        n=("outcome", "size"),
        wins=("outcome", lambda s: (s == "win").sum()),
    )
    by_score["losses"] = by_score["n"] - by_score["wins"]
    by_score["WR%"] = (by_score["wins"] / by_score["n"] * 100).round(1)
    by_score["fixedR"] = by_score["wins"] * RR - by_score["losses"]
    by_score["pos_mult"] = (1.0 + 0.5 * by_score.index)
    by_score["sizedR"] = by_score["fixedR"] * by_score["pos_mult"]
    by_score["sizedR/tr"] = (by_score["sizedR"] / by_score["n"]).round(3)
    print(by_score.to_string())
    print()

    fixed_total = (by_score["fixedR"]).sum()
    sized_total = (by_score["sizedR"]).sum()
    sized_n = by_score["n"].sum()
    print(f"Fixed-1R total: {fixed_total:+.1f}R  (R/tr={fixed_total/sized_n:+.3f})")
    print(f"Sized total:    {sized_total:+.1f}R  (R/tr={sized_total/sized_n:+.3f})")
    print(f"Множитель PnL:  {sized_total / fixed_total if fixed_total else 0:.2f}x")

    print()
    print("Только сегменты по threshold confluence_score:")
    for thr in [1, 2, 3, 4]:
        sub = closed[closed["confluence_score"] >= thr]
        if len(sub) == 0:
            continue
        w = int((sub["outcome"] == "win").sum())
        l = len(sub) - w
        wr = w / len(sub) * 100
        fixed = w * RR - l
        sized = sub["sized_R"].sum()
        print(f"  score>={thr}  n={len(sub):<3d}  WR={wr:5.1f}%  "
              f"fixed={fixed:+.1f}R (R/tr={fixed/len(sub):+.3f})  "
              f"sized={sized:+.1f}R (R/tr={sized/len(sub):+.3f})")


if __name__ == "__main__":
    main()
