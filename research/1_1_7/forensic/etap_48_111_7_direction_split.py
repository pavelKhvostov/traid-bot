"""Этап 48 (1.1.7): Direction-split forensic — LONG vs SHORT отдельно.

Baseline 6.3y:
  LONG  : 91 closed, WR 54.9%, +9R
  SHORT : 64 closed, WR 39.1%, -14R  ← основная утечка

Цель: найти разные edges для LONG и SHORT. На 1.1.1 у Андрея EMA200-1h
counter — единственный шарный edge; здесь может быть наоборот.
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


def main():
    df = pd.read_csv(CSV)
    print(f"[INFO] Total: {len(df)}, LONG={sum(df['direction']=='LONG')}, "
          f"SHORT={sum(df['direction']=='SHORT')}")

    for direction in ["LONG", "SHORT"]:
        sub = df[df["direction"] == direction].copy()
        n = len(sub)
        wr = (sub["outcome"] == "win").sum() / n * 100
        total = sub["R"].sum()
        print("\n" + "=" * 72)
        print(f"  DIRECTION = {direction}  (n={n}  WR={wr:.1f}%  total={total:+.1f}R)")
        print("=" * 72)

        features = [c for c in sub.columns
                    if c not in ("signal_time", "direction", "outcome",
                                  "R", "entry")]

        # Печатаем только top-5 positive per direction
        rows = []
        for f in features:
            for cat in sub[f].unique():
                s2 = sub[sub[f] == cat]
                n2 = len(s2)
                if n2 < 10:
                    continue
                wr2 = (s2["outcome"] == "win").sum() / n2 * 100
                total2 = s2["R"].sum()
                d = wr2 - wr
                rows.append((f, str(cat), n2, wr2, d, total2))

        rows.sort(key=lambda x: x[4], reverse=True)
        print(f"\n  TOP-10 positive features:")
        print(f"  {'feature':<28} {'cat':<20} {'n':<5} {'WR':<7} {'d_pp':<8} {'total':<8}")
        for f, cat, n2, wr2, d, total2 in rows[:10]:
            print(f"  {f:<28} {cat:<20} {n2:<5} {wr2:<7.1f} {d:+7.1f} {total2:+7.1f}")

        print(f"\n  TOP-10 negative features:")
        for f, cat, n2, wr2, d, total2 in rows[-10:]:
            print(f"  {f:<28} {cat:<20} {n2:<5} {wr2:<7.1f} {d:+7.1f} {total2:+7.1f}")


if __name__ == "__main__":
    main()
