"""Combined партия 3: C5, C6, C7, C8 — экспериментальные сегменты.

C5 — Cross-acceleration: ASVK delta_ema3 > 0 (или < 0 для SHORT) AND
     MH bw2 в правильной фазе (green для LONG / red для SHORT).

C6 — Hidden-pair: hidden bull на ASVK И hidden bull на bw2 to trend continuation.
     Применяем только в pro-trend сегменте (z_above или z_pct).

C7 — Disagreement inverse: opposite-div на ASVK И opposite-div на bw2 to
     перевернуть направление. Возможно, двойной anti-signal сработает там
     где H18 (одиночный) провалился.

C8 — Volatility-regime фильтр: MH bw2 в серой фазе И ASVK NWE-канал узкий
     (нижние 30% по nwe_width) to market в тихой фазе to mean-reversion плохо.
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

INPUT_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_mh.csv")
OUT_CSV = Path("signals/strategy_3_2_combined_part3.csv")
RR = 1.0


def stats(closed: pd.DataFrame, label: str, total: int):
    n = len(closed)
    if n == 0:
        return f"  {label:<55s}  n=0"
    w = int((closed["outcome"] == "win").sum())
    l = n - w
    wr = w / n * 100
    pnl = w * RR - l
    rt = pnl / n
    share = n / total * 100 if total else 0
    return (f"  {label:<55s}  n={n:<3d} ({share:5.1f}%)  W={w:<3d} L={l:<3d}  "
            f"WR={wr:5.1f}%  PnL={pnl:+5.1f}R  R/tr={rt:+.3f}")


def main():
    print(f"[INFO] загрузка {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    print(f"  rows: {len(df)}")

    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    total = len(closed)
    long_mask = closed["direction"] == "LONG"
    short_mask = closed["direction"] == "SHORT"

    # delta_ema3 уже в part1 (rsi_velocity). delta_bw2 — в mh.
    print(f"\nBASELINE  closed={total}  W={int((closed['outcome']=='win').sum())}  "
          f"WR={(closed['outcome']=='win').mean()*100:.1f}%  "
          f"PnL={int((closed['outcome']=='win').sum())*RR - int((closed['outcome']=='loss').sum()):+.1f}R")

    # ============ C5 — Cross-acceleration ============
    print()
    print("=" * 100)
    print("C5 — CROSS-ACCELERATION (ASVK delta_ema3 + MH bw2 phase)")
    print("=" * 100)
    asvk_long_acc = long_mask & (closed["rsi_velocity"] > 0)
    asvk_short_acc = short_mask & (closed["rsi_velocity"] < 0)
    mh_long_phase_g = long_mask & (closed["bw2_color"] == "green")
    mh_short_phase_r = short_mask & (closed["bw2_color"] == "red")

    c5_long = asvk_long_acc & mh_long_phase_g
    c5_short = asvk_short_acc & mh_short_phase_r
    c5_aligned = c5_long | c5_short
    print(stats(closed[c5_long], "LONG: ASVK acc UP + MH green", total))
    print(stats(closed[c5_short], "SHORT: ASVK acc DOWN + MH red", total))
    print(stats(closed[c5_aligned], "ALL c5 aligned", total))
    print(stats(closed[~c5_aligned], "ALL non-aligned", total))

    # ============ C6 — Hidden-pair pro-trend ============
    print()
    print("=" * 100)
    print("C6 — HIDDEN PAIR (h_bull/h_bear на обоих) to trend continuation")
    print("=" * 100)
    asvk_long_hidden = long_mask & (closed["h_bull_div_in_window"] == True)
    asvk_short_hidden = short_mask & (closed["h_bear_div_in_window"] == True)
    mh_long_hidden = long_mask & (closed["bw2_h_bull_div_in_window"] == True)
    mh_short_hidden = short_mask & (closed["bw2_h_bear_div_in_window"] == True)

    c6_long = asvk_long_hidden & mh_long_hidden
    c6_short = asvk_short_hidden & mh_short_hidden
    c6_aligned = c6_long | c6_short
    print(stats(closed[c6_long], "LONG: hidden bull on BOTH", total))
    print(stats(closed[c6_short], "SHORT: hidden bear on BOTH", total))
    print(stats(closed[c6_aligned], "ALL hidden-pair", total))

    # Контроль: hidden только на одном
    c6_asvk_only = ((asvk_long_hidden & ~mh_long_hidden) |
                    (asvk_short_hidden & ~mh_short_hidden))
    c6_mh_only = ((mh_long_hidden & ~asvk_long_hidden) |
                  (mh_short_hidden & ~asvk_short_hidden))
    print(stats(closed[c6_asvk_only], "Hidden ASVK only", total))
    print(stats(closed[c6_mh_only], "Hidden MH only", total))

    # ============ C7 — Disagreement inverse ============
    print()
    print("=" * 100)
    print("C7 — DISAGREEMENT INVERSE (opposite-div на ОБОИХ)")
    print("=" * 100)
    asvk_long_opp = long_mask & ((closed["bear_div_in_window"] == True)
                                  | (closed["h_bear_div_in_window"] == True))
    asvk_short_opp = short_mask & ((closed["bull_div_in_window"] == True)
                                    | (closed["h_bull_div_in_window"] == True))
    mh_long_opp = long_mask & ((closed["bw2_bear_div_in_window"] == True)
                                | (closed["bw2_h_bear_div_in_window"] == True))
    mh_short_opp = short_mask & ((closed["bw2_bull_div_in_window"] == True)
                                  | (closed["bw2_h_bull_div_in_window"] == True))

    c7_long_double_opp = asvk_long_opp & mh_long_opp
    c7_short_double_opp = asvk_short_opp & mh_short_opp
    c7_double_opp = c7_long_double_opp | c7_short_double_opp
    print(stats(closed[c7_double_opp], "Both ASVK+MH opposite-div", total))
    # Оригинальный outcome — насколько эти сделки выиграли при оригинальной direction
    # Если они в среднем проигрывают (R/tr < 0) — инверс может работать
    print(stats(closed[(asvk_long_opp & ~mh_long_opp) | (asvk_short_opp & ~mh_short_opp)],
                "ASVK opposite only", total))
    print(stats(closed[(mh_long_opp & ~asvk_long_opp) | (mh_short_opp & ~asvk_short_opp)],
                "MH opposite only", total))

    # ============ C8 — Volatility-regime ============
    print()
    print("=" * 100)
    print("C8 — VOLATILITY REGIME (MH серый + ASVK NWE-канал узкий)")
    print("=" * 100)
    grey_mask = closed["bw2_color"].isin(["grey_after_green", "grey_after_red"])
    has_width = closed["nwe_width_at_signal"].notna()
    width_30pct = closed["nwe_width_at_signal"].quantile(0.3)
    narrow_nwe = has_width & (closed["nwe_width_at_signal"] <= width_30pct)
    print(f"  NWE-width 30th percentile: {width_30pct:.2f}")

    quiet_phase = grey_mask & narrow_nwe
    print(stats(closed[quiet_phase], "Quiet phase (grey + narrow NWE)", total))
    print(stats(closed[grey_mask], "MH grey only", total))
    print(stats(closed[narrow_nwe], "Narrow NWE only", total))
    print(stats(closed[~quiet_phase], "NOT quiet (active phase)", total))

    closed.to_csv(OUT_CSV, index=False)
    print(f"\n[OK] saved: {OUT_CSV}")


if __name__ == "__main__":
    main()
