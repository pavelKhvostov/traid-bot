"""Этап 48: финальные combos на 1.1.2 — выбор лучшего улучшения.

Берём готовый CSV из etap_47 и тестируем 3 группы стратегий:

  Группа A — «улучшить total R»: добавить combos на топ-фичах
  Группа B — «удалить негатив»: убрать только anti-patterns (sunday, asvk extremes)
  Группа C — «максимум R/tr»: концентрация на самых чистых сетапах

Цель: найти ОДНО улучшение которое даёт прирост в total R при сохранении
0 bad years.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

CSV = Path("research/elements_study/output/etap47_closed_trades_features.csv")
RR = 1.8


def report(label, sub, base_wr, base_R, base_n):
    if len(sub) < 20:
        print(f"  {label}: n={len(sub)} skip"); return None
    closed = sub[sub["outcome"].isin(["win", "loss"])]
    if closed.empty: return None
    n = len(closed)
    wr = (closed["R"] > 0).mean() * 100
    total = closed["R"].sum()
    rt = closed["R"].mean()
    yr = closed.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    d_R = total - base_R
    d_wr = wr - base_wr
    n_lost = base_n - n
    print(f"  {label}")
    print(f"    n={n} (-{n_lost} от baseline)  WR={wr:.1f}% (d={d_wr:+.1f}pp)  "
          f"total={total:+.1f}R (d={d_R:+.1f})  R/tr={rt:+.3f}  bad={bad}/{len(yr)}")
    return {"label": label, "n": n, "wr": wr, "total": total,
             "d_R": d_R, "rt": rt, "bad": bad, "yrs": len(yr)}


def main():
    print("[INFO] загружаем etap47 trades CSV")
    df = pd.read_csv(CSV, encoding="utf-8-sig")
    print(f"  {len(df)} trades")

    closed = df[df["outcome"].isin(["win", "loss"])]
    base_n = len(closed)
    base_wr = (closed["R"] > 0).mean() * 100
    base_R = closed["R"].sum()
    base_yr = closed.groupby("year")["R"].sum()
    base_bad = (base_yr < 0).sum()
    print(f"\nBASELINE: n={base_n}  WR={base_wr:.1f}%  total={base_R:+.1f}R  "
          f"R/tr={closed['R'].mean():+.3f}  bad={base_bad}/{len(base_yr)}")

    # ==========================================================
    print(f"\n{'='*70}\nГРУППА A: ADD-FILTERS (улучшить total)")
    print(f"{'='*70}")
    print(f"  baseline: +{base_R:.1f}R  WR={base_wr:.1f}%  bad=0/7\n")
    # Single top filters (already known)
    results_A = []
    results_A.append(report("Hull-12h L78 aligned",
                              df[df["hull_12h_L78_align"] == "aligned"],
                              base_wr, base_R, base_n))
    results_A.append(report("EMA200-4h aligned",
                              df[df["ema200_4h_align"] == "aligned"],
                              base_wr, base_R, base_n))
    results_A.append(report("OB depth medium",
                              df[df["ob_depth_bin"] == "medium"],
                              base_wr, base_R, base_n))
    # Two-feature combos (top R/tr + structural)
    results_A.append(report("Hull-12h L78 + OB medium",
                              df[(df["hull_12h_L78_align"] == "aligned") &
                                  (df["ob_depth_bin"] == "medium")],
                              base_wr, base_R, base_n))
    results_A.append(report("Hull-12h L78 + EMA200-4h",
                              df[(df["hull_12h_L78_align"] == "aligned") &
                                  (df["ema200_4h_align"] == "aligned")],
                              base_wr, base_R, base_n))
    results_A.append(report("OB medium + EMA200-4h",
                              df[(df["ob_depth_bin"] == "medium") &
                                  (df["ema200_4h_align"] == "aligned")],
                              base_wr, base_R, base_n))
    # Triple combo
    results_A.append(report("Hull-12h L78 + OB medium + EMA200-4h",
                              df[(df["hull_12h_L78_align"] == "aligned") &
                                  (df["ob_depth_bin"] == "medium") &
                                  (df["ema200_4h_align"] == "aligned")],
                              base_wr, base_R, base_n))

    # ==========================================================
    print(f"\n{'='*70}\nГРУППА B: REMOVE-NEGATIVE (удалить anti-patterns)")
    print(f"{'='*70}")
    print(f"  Идея: оставляем большинство сделок, режем только явный negativ.\n")
    results_B = []
    # Sunday only
    results_B.append(report("- Sunday",
                              df[df["weekday"] != "Sun"],
                              base_wr, base_R, base_n))
    # ASVK extremes (red+green) only
    results_B.append(report("- ASVK-1h red+green",
                              df[~df["asvk_1h_zone"].isin(["red", "green"])],
                              base_wr, base_R, base_n))
    # ASVK 4h extremes
    results_B.append(report("- ASVK-4h red+green",
                              df[~df["asvk_4h_zone"].isin(["red", "green"])],
                              base_wr, base_R, base_n))
    # OB-depth small + large (keep medium only)
    results_B.append(report("- OB small + large (= keep medium)",
                              df[df["ob_depth_bin"] == "medium"],
                              base_wr, base_R, base_n))
    # Sunday + ASVK extremes
    results_B.append(report("- Sunday and ASVK-1h extremes",
                              df[(df["weekday"] != "Sun") &
                                  (~df["asvk_1h_zone"].isin(["red", "green"]))],
                              base_wr, base_R, base_n))
    # Sunday + ASVK extremes + Wednesday (also weak)
    results_B.append(report("- Sunday + Wednesday + ASVK-1h extremes",
                              df[(~df["weekday"].isin(["Sun", "Wed"])) &
                                  (~df["asvk_1h_zone"].isin(["red", "green"]))],
                              base_wr, base_R, base_n))
    # Hull-1d L78 counter only (keep when Hull 1d aligned OR neutral?)
    # Actually let's drop Hull-12h L78 counter (negative pattern)
    results_B.append(report("- Hull-12h L78 counter (= keep aligned only)",
                              df[df["hull_12h_L78_align"] != "counter"],
                              base_wr, base_R, base_n))

    # ==========================================================
    print(f"\n{'='*70}\nГРУППА C: HIGH R/tr (sniper)")
    print(f"{'='*70}")
    results_C = []
    results_C.append(report("EMA200-1h + EMA200-4h aligned",
                              df[(df["ema200_1h_align"] == "aligned") &
                                  (df["ema200_4h_align"] == "aligned")],
                              base_wr, base_R, base_n))
    results_C.append(report("Hull-12h L78 + Hull-1d L49",
                              df[(df["hull_12h_L78_align"] == "aligned") &
                                  (df["hull_1d_L49_align"] == "aligned")],
                              base_wr, base_R, base_n))
    results_C.append(report("Hull-12h L78 + EMA200-1h",
                              df[(df["hull_12h_L78_align"] == "aligned") &
                                  (df["ema200_1h_align"] == "aligned")],
                              base_wr, base_R, base_n))
    results_C.append(report("EMA200-4h + OB medium + ASVK not red",
                              df[(df["ema200_4h_align"] == "aligned") &
                                  (df["ob_depth_bin"] == "medium") &
                                  (df["asvk_1h_zone"] != "red")],
                              base_wr, base_R, base_n))

    # ==========================================================
    # FINAL VERDICT
    # ==========================================================
    print(f"\n{'='*70}\nФИНАЛЬНЫЙ ВЕРДИКТ — ВСЕ ВАРИАНТЫ ОТСОРТИРОВАНЫ ПО total R")
    print(f"{'='*70}")
    all_results = [r for r in results_A + results_B + results_C if r]
    by_total = sorted(all_results, key=lambda x: x["total"], reverse=True)
    print(f"\n  {'Filter':<48} {'n':>5} {'WR':>7} {'Total R':>10} {'R/tr':>8} {'Bad':>6}")
    print("  " + "-" * 85)
    for r in by_total[:15]:
        clean = "✓" if r["bad"] == 0 else f"({r['bad']})"
        print(f"  {r['label']:<48} {r['n']:>5} {r['wr']:>6.1f}% "
              f"{r['total']:>+8.1f}R {r['rt']:>+.3f} {r['bad']}/{r['yrs']:<3}")

    print(f"\n  ВЫИГРЫШНЫЕ (total > baseline +{base_R:.1f}R и 0 bad years):")
    print("  " + "-" * 85)
    winners = [r for r in all_results
                if r["total"] > base_R and r["bad"] == 0]
    winners = sorted(winners, key=lambda x: x["total"], reverse=True)
    for r in winners:
        print(f"  {r['label']:<48} {r['n']:>5} {r['wr']:>6.1f}% "
              f"{r['total']:>+8.1f}R {r['rt']:>+.3f}")
    if not winners:
        print("    Ни один. Лучший вариант не превосходит baseline по total R.")
    print()


if __name__ == "__main__":
    main()
