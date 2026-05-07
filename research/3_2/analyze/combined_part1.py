"""Combined ASVK + MH партия 1: C1, C2, C3, C9 — segmentation only.

C1 — Двойная дивергенция (ASVK + MH-bw2)
C2 — Phase-aware extreme (ASVK adaptive OS/OB + MH bw2 grey-after-color)
C3 — 8-флажный confluence score (4 ASVK + 4 MH)
C9 — H11 + MF знак (bars_since_OB + MF aligned)
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
OUT_CSV = Path("signals/strategy_3_2_combined_part1.csv")
RR = 1.0


def stats(closed: pd.DataFrame, label: str, total: int) -> str:
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

    baseline_w = int((closed["outcome"] == "win").sum())
    baseline_wr = baseline_w / total * 100
    baseline_pnl = baseline_w * RR - (total - baseline_w)
    print(f"\nBASELINE  closed={total}  W={baseline_w}  "
          f"WR={baseline_wr:.1f}%  PnL={baseline_pnl:+.1f}R")

    # ASVK aligned div
    asvk_long_div = long_mask & (
        (closed["bull_div_in_window"] == True)
        | (closed["h_bull_div_in_window"] == True)
    )
    asvk_short_div = short_mask & (
        (closed["bear_div_in_window"] == True)
        | (closed["h_bear_div_in_window"] == True)
    )
    asvk_div_aligned = asvk_long_div | asvk_short_div

    # MH aligned div
    mh_long_div = long_mask & (
        (closed["bw2_bull_div_in_window"] == True)
        | (closed["bw2_h_bull_div_in_window"] == True)
    )
    mh_short_div = short_mask & (
        (closed["bw2_bear_div_in_window"] == True)
        | (closed["bw2_h_bear_div_in_window"] == True)
    )
    mh_div_aligned = mh_long_div | mh_short_div

    # =========== C1 ===========
    print()
    print("=" * 100)
    print("C1 — DOUBLE DIVERGENCE (ASVK div AND MH-bw2 div)")
    print("=" * 100)
    both_div = asvk_div_aligned & mh_div_aligned
    asvk_only = asvk_div_aligned & ~mh_div_aligned
    mh_only = ~asvk_div_aligned & mh_div_aligned
    neither = ~asvk_div_aligned & ~mh_div_aligned
    print(stats(closed[both_div], "BOTH ASVK + MH div", total))
    print(stats(closed[asvk_only], "ASVK div only", total))
    print(stats(closed[mh_only], "MH-bw2 div only", total))
    print(stats(closed[neither], "Neither", total))

    # =========== C2 ===========
    print()
    print("=" * 100)
    print("C2 — PHASE-AWARE EXTREME (ASVK ema_3 в OS/OB + MH bw2 grey-after-color)")
    print("=" * 100)
    long_in_os = long_mask & (closed["rsi_at_signal"] < closed["below_at_signal"])
    short_in_ob = short_mask & (closed["rsi_at_signal"] > closed["above_at_signal"])
    mh_long_phase = long_mask & (closed["bw2_color"] == "grey_after_red")
    mh_short_phase = short_mask & (closed["bw2_color"] == "grey_after_green")

    c2_long = long_in_os & mh_long_phase
    c2_short = short_in_ob & mh_short_phase
    c2_aligned = c2_long | c2_short
    print(stats(closed[c2_long], "LONG: ASVK_OS + MH grey-after-red", total))
    print(stats(closed[c2_short], "SHORT: ASVK_OB + MH grey-after-green", total))
    print(stats(closed[c2_aligned], "ALL phase-aware extreme", total))
    print()
    print("Контрольная группа — только один из двух условий:")
    print(stats(closed[(long_in_os & ~mh_long_phase) | (short_in_ob & ~mh_short_phase)],
                "ASVK extreme only (no MH phase)", total))
    print(stats(closed[(mh_long_phase & ~long_in_os) | (mh_short_phase & ~short_in_ob)],
                "MH phase only (no ASVK extreme)", total))

    # =========== C3 ===========
    print()
    print("=" * 100)
    print("C3 — 8-FLAG CONFLUENCE SCORE (4 ASVK + 4 MH), sizing 1.0 + 0.25xscore")
    print("=" * 100)

    # ASVK 4 флага
    flag_asvk_div = asvk_div_aligned
    flag_4h_side = (long_mask & (closed.get("rsi_4h_at_signal", pd.Series(50, index=closed.index)) < 50)) | \
                   (short_mask & (closed.get("rsi_4h_at_signal", pd.Series(50, index=closed.index)) >= 50))
    # rsi_4h_at_signal только в multi_tf_h9.csv — здесь его нет в part1.
    # Используем заместитель: ema_3<50 для LONG, >=50 для SHORT (на 1h).
    flag_4h_side = (long_mask & (closed["rsi_at_signal"] < 50)) | \
                   (short_mask & (closed["rsi_at_signal"] >= 50))
    asvk_div_depths = closed[[
        "max_bull_depth_in_window", "max_h_bull_depth_in_window",
        "max_bear_depth_in_window", "max_h_bear_depth_in_window",
    ]].max(axis=1)
    median_depth = asvk_div_depths[flag_asvk_div].median() if flag_asvk_div.any() else np.nan
    flag_deep = flag_asvk_div & (asvk_div_depths >= median_depth)
    has_pct = closed["z_pct_at_signal"].notna()
    bull_pct = has_pct & (closed["z_pct_at_signal"] > 0.75)
    bear_pct = has_pct & (closed["z_pct_at_signal"] < 0.25)
    flag_pct = (bear_pct & long_mask) | (bull_pct & short_mask)

    # MH 4 флага
    flag_mh_div = mh_div_aligned
    flag_mh_color = (long_mask & closed["bw2_color"].isin(["green", "grey_after_red"])) | \
                    (short_mask & closed["bw2_color"].isin(["red", "grey_after_green"]))
    flag_mh_mf = (long_mask & (closed["mf_at_signal"] > 0)) | \
                 (short_mask & (closed["mf_at_signal"] < 0))
    flag_mh_zone = (long_mask & (closed["bw2_at_touch"] <= -60)) | \
                   (short_mask & (closed["bw2_at_touch"] >= 60))

    closed["c3_score"] = (flag_asvk_div.astype(int) + flag_4h_side.astype(int) +
                          flag_deep.astype(int) + flag_pct.astype(int) +
                          flag_mh_div.astype(int) + flag_mh_color.astype(int) +
                          flag_mh_mf.astype(int) + flag_mh_zone.astype(int))
    closed["c3_size"] = 1.0 + 0.25 * closed["c3_score"]

    win_mask_c = closed["outcome"] == "win"
    loss_mask_c = closed["outcome"] == "loss"
    closed["c3_sized_R"] = np.where(win_mask_c, closed["c3_size"] * RR,
                                    np.where(loss_mask_c, -closed["c3_size"], 0))

    print("Распределение по c3_score:")
    by_score = closed.groupby("c3_score").agg(
        n=("outcome", "size"),
        wins=("outcome", lambda s: (s == "win").sum()),
    )
    by_score["losses"] = by_score["n"] - by_score["wins"]
    by_score["WR%"] = (by_score["wins"] / by_score["n"] * 100).round(1)
    by_score["fixedR"] = by_score["wins"] - by_score["losses"]
    by_score["pos_mult"] = (1.0 + 0.25 * by_score.index).round(2)
    by_score["sizedR"] = (by_score["fixedR"] * by_score["pos_mult"]).round(1)
    print(by_score.to_string())

    fixed_total = by_score["fixedR"].sum()
    sized_total = by_score["sizedR"].sum()
    print()
    print(f"Fixed total: {fixed_total:+.1f}R  R/tr={fixed_total/total:+.3f}")
    print(f"Sized total: {sized_total:+.1f}R  R/tr={sized_total/total:+.3f}")
    print(f"Множитель PnL: {sized_total/fixed_total if fixed_total else 0:.2f}x")

    print()
    print("Threshold-сегменты:")
    for thr in [1, 2, 3, 4, 5]:
        sub = closed[closed["c3_score"] >= thr]
        if len(sub) == 0:
            continue
        w = int((sub["outcome"] == "win").sum())
        l = len(sub) - w
        wr = w / len(sub) * 100
        fix = w * RR - l
        sz = sub["c3_sized_R"].sum()
        print(f"  score>={thr}  n={len(sub):<3d}  WR={wr:5.1f}%  "
              f"fixed={fix:+.1f}R (R/tr={fix/len(sub):+.3f})  "
              f"sized={sz:+.1f}R (R/tr={sz/len(sub):+.3f})")

    # =========== C9 ===========
    print()
    print("=" * 100)
    print("C9 — H11 + MF знак (bars_since_OB > 100 AND MF aligned)")
    print("=" * 100)
    h11_long = long_mask & (closed["bars_since_ob"] > 100)
    h11_short = short_mask & (closed["bars_since_os"] > 100)
    mf_long = long_mask & (closed["mf_at_signal"] > 0)
    mf_short = short_mask & (closed["mf_at_signal"] < 0)

    c9_long = h11_long & mf_long
    c9_short = h11_short & mf_short
    c9_aligned = c9_long | c9_short
    print(stats(closed[h11_long | h11_short], "H11 only (baseline H11)", total))
    print(stats(closed[c9_long], "C9 LONG (H11 + MF>0)", total))
    print(stats(closed[c9_short], "C9 SHORT (H11 + MF<0)", total))
    print(stats(closed[c9_aligned], "C9 ALL", total))
    print(stats(closed[(h11_long | h11_short) & ~c9_aligned], "H11 with MF disaligned", total))

    closed.to_csv(OUT_CSV, index=False)
    print(f"\n[OK] saved: {OUT_CSV}")


if __name__ == "__main__":
    main()
