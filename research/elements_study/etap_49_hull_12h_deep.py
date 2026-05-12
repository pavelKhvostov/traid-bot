"""Этап 49: глубокая аналитика по Hull-12h L78 фильтру для 1.1.2.

Из etap_47 CSV вытягиваем все trades + features и анализируем:
  - Year-by-year (Hull aligned vs counter)
  - LONG vs SHORT split
  - Размер edge (avg R aligned vs counter)
  - Корреляция с другими фичами
  - Распределение outcome по hull labels
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

CSV = Path("research/elements_study/output/etap47_closed_trades_features.csv")


def main():
    print("[INFO] загружаем CSV")
    df = pd.read_csv(CSV, encoding="utf-8-sig")
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    print(f"  closed trades: {len(closed)}")

    # ============================================================
    print(f"\n{'='*70}\n1. РАСПРЕДЕЛЕНИЕ Hull-12h L78 labels")
    print(f"{'='*70}")
    dist = closed["hull_12h_L78_align"].value_counts()
    for lbl, n in dist.items():
        print(f"  {lbl:<10}  n={n}  ({n/len(closed)*100:.1f}%)")

    # ============================================================
    print(f"\n{'='*70}\n2. WR / R/tr ПО labels")
    print(f"{'='*70}")
    g = closed.groupby("hull_12h_L78_align").agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"),
        avg_R=("R", "mean"),
    )
    g["WR"] = g["wins"] / g["n"] * 100
    print(g.to_string())

    # ============================================================
    print(f"\n{'='*70}\n3. YEAR-BY-YEAR: aligned vs counter vs all")
    print(f"{'='*70}")
    for year in sorted(closed["year"].unique()):
        yr_df = closed[closed["year"] == year]
        all_n = len(yr_df)
        all_wr = (yr_df["R"] > 0).mean() * 100
        all_R = yr_df["R"].sum()
        al = yr_df[yr_df["hull_12h_L78_align"] == "aligned"]
        ct = yr_df[yr_df["hull_12h_L78_align"] == "counter"]
        al_wr = (al["R"] > 0).mean()*100 if len(al) else 0
        al_R = al["R"].sum()
        ct_wr = (ct["R"] > 0).mean()*100 if len(ct) else 0
        ct_R = ct["R"].sum()
        print(f"  {year}:")
        print(f"    all      n={all_n:>3}  WR={all_wr:5.1f}%  total={all_R:+5.1f}R")
        print(f"    aligned  n={len(al):>3}  WR={al_wr:5.1f}%  total={al_R:+5.1f}R")
        print(f"    counter  n={len(ct):>3}  WR={ct_wr:5.1f}%  total={ct_R:+5.1f}R")

    # ============================================================
    print(f"\n{'='*70}\n4. LONG vs SHORT split")
    print(f"{'='*70}")
    for direction in ["LONG", "SHORT"]:
        sub = closed[closed["direction"] == direction]
        al = sub[sub["hull_12h_L78_align"] == "aligned"]
        ct = sub[sub["hull_12h_L78_align"] == "counter"]
        print(f"  {direction}:")
        print(f"    all      n={len(sub):>3}  WR={(sub['R']>0).mean()*100:5.1f}%  "
              f"total={sub['R'].sum():+5.1f}R")
        print(f"    aligned  n={len(al):>3}  WR={(al['R']>0).mean()*100 if len(al) else 0:5.1f}%  "
              f"total={al['R'].sum():+5.1f}R  R/tr={al['R'].mean() if len(al) else 0:+.3f}")
        print(f"    counter  n={len(ct):>3}  WR={(ct['R']>0).mean()*100 if len(ct) else 0:5.1f}%  "
              f"total={ct['R'].sum():+5.1f}R  R/tr={ct['R'].mean() if len(ct) else 0:+.3f}")

    # ============================================================
    print(f"\n{'='*70}\n5. EDGE SIZE: aligned vs counter R-distribution")
    print(f"{'='*70}")
    for label in ["aligned", "counter"]:
        sub = closed[closed["hull_12h_L78_align"] == label]
        if sub.empty: continue
        wins = sub[sub["R"] > 0]
        losses = sub[sub["R"] < 0]
        print(f"  {label}  (n={len(sub)})")
        print(f"    wins:   {len(wins)}  (avg R = +{wins['R'].mean() if len(wins) else 0:.2f})")
        print(f"    losses: {len(losses)}  (avg R = {losses['R'].mean() if len(losses) else 0:.2f})")
        print(f"    expected: {sub['R'].mean():+.3f}R/trade")

    # ============================================================
    print(f"\n{'='*70}\n6. КАК Hull-12h КОРРЕЛИРУЕТ С ДРУГИМИ ФИЧАМИ")
    print(f"{'='*70}")
    print(f"  Когда Hull-12h aligned, КАКОВО распределение остальных фич?")

    aligned_df = closed[closed["hull_12h_L78_align"] == "aligned"]
    counter_df = closed[closed["hull_12h_L78_align"] == "counter"]

    for feat in ["ema200_1h_align", "ema200_4h_align",
                  "hull_4h_L78_align", "hull_1d_L78_align",
                  "asvk_1h_zone", "session", "weekday"]:
        print(f"\n  --- {feat} ---")
        print(f"  aligned:  ", end="")
        for v, n in aligned_df[feat].value_counts(normalize=True).head(3).items():
            print(f"{v}={n*100:.0f}%  ", end="")
        print(f"\n  counter:  ", end="")
        for v, n in counter_df[feat].value_counts(normalize=True).head(3).items():
            print(f"{v}={n*100:.0f}%  ", end="")
        print()

    # ============================================================
    print(f"\n{'='*70}\n7. ЧАСТОТА (frequency) ПО МЕСЯЦАМ")
    print(f"{'='*70}")
    aligned_df["month_year"] = pd.to_datetime(aligned_df["signal_time"]).dt.to_period("M")
    counts_by_month = aligned_df.groupby("month_year").size()
    print(f"  Aligned setups: {len(aligned_df)} за {len(counts_by_month)} месяцев")
    print(f"    avg per month: {counts_by_month.mean():.1f}")
    print(f"    min: {counts_by_month.min()}  max: {counts_by_month.max()}")
    months_zero = 76 - len(counts_by_month)  # ~76 months in 6.33 years
    print(f"    месяцев БЕЗ aligned setups: {months_zero}")


if __name__ == "__main__":
    main()
