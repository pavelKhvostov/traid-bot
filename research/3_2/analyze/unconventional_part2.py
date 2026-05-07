"""Partition 2: N8 (failure-of-pattern), N9 (win-streak adaptive sizing)."""
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

INPUT_CSV = Path("signals/strategy_3_2_3y_RR1_unconventional.csv")
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
    df = pd.read_csv(INPUT_CSV)
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    total = len(closed)
    print(f"BASELINE  closed={total}  WR={(closed['outcome']=='win').mean()*100:.1f}%")
    print()

    # ---------- N8 failure-of-pattern ----------
    print("=" * 100)
    print("N8 — FAILURE-OF-PATTERN (prev signal был quick_failure <=2h)")
    print("=" * 100)
    qf_count = closed["quick_failure"].sum()
    print(f"Total quick_failures: {int(qf_count)} из {total}")
    after_qf = closed["prev_was_quick_failure"] == True
    not_after_qf = ~after_qf
    print(stats(closed[after_qf], "After prev quick_failure", total))
    print(stats(closed[not_after_qf], "Not after quick_failure", total))

    # Direction split
    long_mask = closed["direction"] == "LONG"
    short_mask = closed["direction"] == "SHORT"
    print()
    print("Per direction:")
    print(stats(closed[after_qf & long_mask], "After QF · LONG", total))
    print(stats(closed[after_qf & short_mask], "After QF · SHORT", total))

    # Same direction logic — gostпредположим, что quick_failure следующего того же direction = опасно
    # У нас нет прямого "prev direction". Аппроксимация: direction текущей == direction prev (chronological)
    df_sorted = df.sort_values("signal_time").reset_index(drop=True)
    df_sorted["prev_direction"] = df_sorted["direction"].shift(1)
    df_sorted["prev_qf"] = df_sorted["quick_failure"].shift(1).fillna(False)
    df_sorted_closed = df_sorted[df_sorted["outcome"].isin(["win", "loss"])]
    same_dir_after_qf = (df_sorted_closed["prev_qf"] == True) & \
                        (df_sorted_closed["direction"] == df_sorted_closed["prev_direction"])
    diff_dir_after_qf = (df_sorted_closed["prev_qf"] == True) & \
                        (df_sorted_closed["direction"] != df_sorted_closed["prev_direction"])
    print(stats(df_sorted_closed[same_dir_after_qf], "Same direction after QF", total))
    print(stats(df_sorted_closed[diff_dir_after_qf], "Opposite direction after QF", total))

    # ---------- N9 win-streak / loss-streak adaptive sizing ----------
    print()
    print("=" * 100)
    print("N9 — WIN/LOSS STREAK ADAPTIVE SIZING")
    print("=" * 100)
    print()
    print("Распределение outcome по win_streak_before:")
    by_ws = closed.groupby("win_streak_before").agg(
        n=("outcome", "size"),
        wins=("outcome", lambda s: (s == "win").sum()),
    )
    by_ws["losses"] = by_ws["n"] - by_ws["wins"]
    by_ws["WR%"] = (by_ws["wins"] / by_ws["n"] * 100).round(1)
    by_ws["fixed_R"] = by_ws["wins"] - by_ws["losses"]
    by_ws["R/tr"] = (by_ws["fixed_R"] / by_ws["n"]).round(3)
    print(by_ws.head(8).to_string())

    print()
    print("Распределение по loss_streak_before:")
    by_ls = closed.groupby("loss_streak_before").agg(
        n=("outcome", "size"),
        wins=("outcome", lambda s: (s == "win").sum()),
    )
    by_ls["losses"] = by_ls["n"] - by_ls["wins"]
    by_ls["WR%"] = (by_ls["wins"] / by_ls["n"] * 100).round(1)
    by_ls["fixed_R"] = by_ls["wins"] - by_ls["losses"]
    by_ls["R/tr"] = (by_ls["fixed_R"] / by_ls["n"]).round(3)
    print(by_ls.head(8).to_string())

    # Anti-martingale sizing simulation
    print()
    print("Anti-martingale sizing variants (size = base + k*win_streak - k*loss_streak):")
    for k in [0.0, 0.25, 0.5, 1.0]:
        sized_R = []
        for _, row in closed.iterrows():
            ws = row["win_streak_before"]
            ls = row["loss_streak_before"]
            size = max(0.1, 1.0 + k * ws - k * ls)
            r = (RR * size) if row["outcome"] == "win" else -1.0 * size
            sized_R.append(r)
        total_r = sum(sized_R)
        rt = total_r / len(closed)
        print(f"  k={k:<5}  total_R={total_r:+6.2f}  R/tr={rt:+.3f}  "
              f"(min size: {min(max(0.1, 1.0 + k * row['win_streak_before'] - k * row['loss_streak_before']) for _, row in closed.iterrows()):.2f}  "
              f"max size: {max(1.0 + k * row['win_streak_before'] - k * row['loss_streak_before'] for _, row in closed.iterrows()):.2f})")

    # Pro-momentum: больше после wins, меньше после losses
    print()
    print("Pro-momentum (только когда recent wins):")
    after_3plus_wins = closed["win_streak_before"] >= 3
    after_3plus_losses = closed["loss_streak_before"] >= 3
    print(stats(closed[after_3plus_wins], "After 3+ wins", total))
    print(stats(closed[after_3plus_losses], "After 3+ losses", total))


if __name__ == "__main__":
    main()
