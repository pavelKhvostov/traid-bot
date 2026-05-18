"""Этап 28 (1.1.7-edition): ICT-style time-grid matrix.

Полная разбивка по hour-of-day × weekday × session. Цель — найти
конкретные time windows с самым большим edge.

Также пробуем композитные time-filters (Mon-Thu + NY, etc.) как Андрей.
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

import pandas as pd

CSV = Path("research/1_1_7/forensic/output/etap_47_111_7_trades_features.csv")


def stats(sub: pd.DataFrame, base_wr: float):
    n = len(sub)
    if n == 0:
        return n, 0, 0, 0, 0
    wins = (sub["outcome"] == "win").sum()
    wr = wins / n * 100
    total = sub["R"].sum()
    d = wr - base_wr
    return n, wr, d, total, total / n


def main():
    df = pd.read_csv(CSV)
    n_all = len(df)
    base_wr = (df["outcome"] == "win").sum() / n_all * 100
    base_R = df["R"].sum()
    print(f"[INFO] baseline n={n_all}  WR={base_wr:.1f}%  total={base_R:+.1f}R\n")

    # Hour × Session
    print("=" * 60)
    print("HOUR OF DAY (UTC)")
    print("=" * 60)
    print(f"{'hr':<4} {'n':<5} {'WR':<7} {'d_pp':<8} {'total':<8}")
    for h in range(24):
        sub = df[df["hour"] == h]
        if len(sub) < 5:
            continue
        n, wr, d, total, avg = stats(sub, base_wr)
        flag = " ***" if (n >= 10 and d >= 5) else (" !" if (n >= 10 and d <= -5) else "")
        print(f"{h:<4} {n:<5} {wr:<7.1f} {d:+7.1f} {total:+7.1f}{flag}")

    print("\n" + "=" * 60)
    print("WEEKDAY × SESSION matrix (total R)")
    print("=" * 60)
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                "Saturday", "Sunday"]
    sessions = ["Asia", "London", "NY", "off"]
    print(f"{'':<10} " + " ".join([f"{s:<10}" for s in sessions]))
    for wd in weekdays:
        cells = []
        for sn in sessions:
            sub = df[(df["weekday"] == wd) & (df["session"] == sn)]
            if len(sub) == 0:
                cells.append(f"{'-':<10}")
            else:
                n, wr, d, total, _ = stats(sub, base_wr)
                cells.append(f"{n}/{wr:.0f}%/{total:+.0f}R".ljust(10))
        print(f"{wd:<10} " + " ".join(cells))

    print("\n" + "=" * 60)
    print("Composite time filters")
    print("=" * 60)

    filters = [
        ("Thu+Fri+Sat",
         df["weekday"].isin(["Thursday", "Friday", "Saturday"])),
        ("Mon-Thu",
         df["weekday"].isin(["Monday", "Tuesday", "Wednesday", "Thursday"])),
        ("not_Sunday",
         df["weekday"] != "Sunday"),
        ("NY+off",
         df["session"].isin(["NY", "off"])),
        ("not_London",
         df["session"] != "London"),
        ("not_Sunday & not_London",
         (df["weekday"] != "Sunday") & (df["session"] != "London")),
        ("Thu-Sat & not_London",
         df["weekday"].isin(["Thursday", "Friday", "Saturday"])
            & (df["session"] != "London")),
    ]

    print(f"{'filter':<35} {'n':<5} {'WR':<7} {'d_pp':<8} {'total':<8} {'avg':<8}")
    for name, mask in filters:
        sub = df[mask]
        n, wr, d, total, avg = stats(sub, base_wr)
        flag = " ***" if d >= 5 else (" !" if d <= -5 else "")
        print(f"{name:<35} {n:<5} {wr:<7.1f} {d:+7.1f} {total:+7.1f} {avg:+7.3f}{flag}")

    # Best per direction
    print("\n" + "=" * 60)
    print("Best time filters per direction")
    print("=" * 60)
    for direction in ["LONG", "SHORT"]:
        sub_dir = df[df["direction"] == direction]
        n_d = len(sub_dir)
        wr_d = (sub_dir["outcome"] == "win").sum() / n_d * 100
        total_d = sub_dir["R"].sum()
        print(f"\n  {direction} baseline: n={n_d} WR={wr_d:.1f}% total={total_d:+.1f}R")
        for name, mask in filters:
            sub = sub_dir[mask[sub_dir.index]]
            if len(sub) < 10:
                continue
            n, wr, d, total, _ = stats(sub, wr_d)
            print(f"    {name:<35} n={n:<4} WR={wr:.1f}% d={d:+5.1f}pp "
                  f"total={total:+.1f}R")


if __name__ == "__main__":
    main()
