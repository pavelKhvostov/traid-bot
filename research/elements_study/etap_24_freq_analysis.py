"""Этап 24: анализ trade-off между частотой и edge.

Вопрос: сколько хороших комбинаций я отсёк фильтром n/нед>=1?

Объединяю все grid'ы (etap_14, 17, 18, 22) и смотрю:
  - bucket'ы по частоте: high (>=2/нед), medium (1-2), low (0.5-1), rare (0.2-0.5), sniper (<0.2)
  - топ-кандидаты в каждой
  - "missed gems": low freq + высокий R/tr + положительный total_R
  - portfolio approach: можно ли скомбинировать несколько rare'ов в агрегированный high-freq поток

Ключевая метрика: **R/year @ 1% risk** = total_R / 6.33 годa.
Это позволяет сравнивать стратегии разной частоты на одной шкале.
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

OUT_DIR = Path("research/elements_study/output")
YEARS = 6.33

# Все grid CSV — нормализуем колонки, объединяем
GRIDS = [
    ("etap14_full_grid.csv", "etap14_pairs"),       # OB/FVG/RDRB pairs
    ("etap17_grid.csv", "etap17_sweep_frsweep"),    # +SWEPT +FRSWEEP
    ("etap18_fractal_grid.csv", "etap18_fractals"), # 4 fractal families
    ("etap22_grid.csv", "etap22_extended"),          # confluence/triple/fract-range
]


def load_and_normalize():
    dfs = []
    for csv_name, source_label in GRIDS:
        path = OUT_DIR / csv_name
        if not path.exists():
            print(f"[WARN] {path} not found")
            continue
        df = pd.read_csv(path)
        df["source"] = source_label
        # Колонки могут немного отличаться. Привожу к стандарту.
        # etap_14/17 — anchor, trigger, filter, RR, n_total, n_per_week, n_closed, WR%, total_R, R/trade
        # etap_18 — family, anchor, trigger, filter, RR, n_total, n_per_week, n_closed, WR%, total_R, R/trade
        # etap_22 — family, anchor, trigger, filter, RR, ...
        # etap_17 has extra anchor_filter
        if "family" not in df.columns:
            df["family"] = source_label
        if "anchor_filter" not in df.columns:
            df["anchor_filter"] = "all"
        # synthesize setup label
        df["setup"] = (df["anchor"].astype(str) + " x " + df["trigger"].astype(str)
                        + " " + df["filter"].astype(str)
                        + " RR=" + df["RR"].astype(str))
        dfs.append(df[["source", "family", "anchor", "trigger", "filter",
                        "anchor_filter", "RR", "n_total", "n_per_week",
                        "n_closed", "WR%", "total_R", "R/trade", "setup"]])
    combined = pd.concat(dfs, ignore_index=True)
    # дополнительная метрика
    combined["R_per_year"] = (combined["total_R"] / YEARS).round(2)
    return combined


def freq_bucket(n_per_week):
    if n_per_week >= 2.0: return "0_high (>=2/wk)"
    if n_per_week >= 1.0: return "1_med (1-2)"
    if n_per_week >= 0.5: return "2_low (0.5-1)"
    if n_per_week >= 0.2: return "3_rare (0.2-0.5)"
    return "4_sniper (<0.2)"


def main():
    print("[INFO] loading all grids")
    df = load_and_normalize()
    print(f"  total candidates: {len(df)}")
    df["bucket"] = df["n_per_week"].apply(freq_bucket)

    # очень мягкий sanity filter (адекватные)
    sane = df[(df["WR%"] >= 50) & (df["total_R"] > 0)]
    print(f"  sane (WR>=50, total_R>0): {len(sane)}")

    # ----- 1. ТОЛЬКО ПО ЧАСТОТЕ -----
    print("\n" + "="*80)
    print("РАСПРЕДЕЛЕНИЕ САНИРОВАННЫХ КАНДИДАТОВ ПО BUCKET'АМ ЧАСТОТЫ")
    print("="*80)
    bucket_stats = sane.groupby("bucket").agg(
        n_candidates=("setup", "size"),
        median_WR=("WR%", "median"),
        median_total_R=("total_R", "median"),
        median_R_tr=("R/trade", "median"),
        max_total_R=("total_R", "max"),
        max_R_tr=("R/trade", "max"),
    ).round(3)
    print(bucket_stats.to_string())

    # ----- 2. ТОП КАНДИДАТЫ ПО bucket'у -----
    print("\n" + "="*80)
    print("ТОП-5 КАНДИДАТОВ В КАЖДОМ BUCKET'е (sorted by R_per_year)")
    print("="*80)
    for bucket in sorted(sane["bucket"].unique()):
        sub = sane[sane["bucket"] == bucket]
        if sub.empty: continue
        print(f"\n--- {bucket} ({len(sub)} candidates) ---")
        top = sub.sort_values("R_per_year", ascending=False).head(5)
        cols = ["source", "anchor", "trigger", "filter", "RR",
                 "n_per_week", "WR%", "total_R", "R/trade", "R_per_year"]
        print(top[cols].to_string(index=False))

    # ----- 3. "MISSED GEMS" — низкая частота но высокий R/tr -----
    print("\n" + "="*80)
    print("MISSED GEMS — n/нед < 1 но R/tr > 0.25 и total_R > 25")
    print("="*80)
    gems = sane[(sane["n_per_week"] < 1) &
                (sane["R/trade"] > 0.25) &
                (sane["total_R"] > 25)]
    if len(gems):
        gems_top = gems.sort_values("R/trade", ascending=False).head(20)
        cols = ["source", "anchor", "trigger", "filter", "RR",
                 "n_per_week", "WR%", "total_R", "R/trade", "R_per_year"]
        print(gems_top[cols].to_string(index=False))
        print(f"\n  Total 'missed gems': {len(gems)}")
        print(f"  Их суммарный R/year при portfolio = {gems['R_per_year'].sum():.1f}/year")
        print(f"  (это сумма если бы все запускались параллельно — реальный portfolio")
        print(f"   будет ниже из-за корреляции и overlap)")
    else:
        print("  нет таких")

    # ----- 4. STRICT vs RELAXED tradeoff -----
    print("\n" + "="*80)
    print("ЧТО МЫ ТЕРЯЕМ ПРИ РАЗНЫХ ПОРОГАХ n/нед")
    print("="*80)
    thresholds = [1.0, 0.5, 0.3, 0.2, 0.1]
    print(f"\n  Из {len(sane)} 'санированных' кандидатов (WR>=50, total_R>0):")
    print(f"  {'threshold':<14} {'pass':<6} {'top R/tr':<10} {'top total_R':<12} {'top R/year':<12}")
    for thr in thresholds:
        pf = sane[sane["n_per_week"] >= thr]
        if pf.empty: continue
        top_rt = pf["R/trade"].max()
        top_tr = pf["total_R"].max()
        top_yr = pf["R_per_year"].max()
        print(f"  >= {thr:>4}/нед     {len(pf):<6} {top_rt:<10.3f} {top_tr:<12.1f} {top_yr:<12.1f}")

    # ----- 5. PORTFOLIO POTENTIAL -----
    print("\n" + "="*80)
    print("PORTFOLIO POTENTIAL — топ-10 'снайперских' (n/нед<0.5) с R/tr>0.30")
    print("="*80)
    snipers = sane[(sane["n_per_week"] < 0.5) & (sane["R/trade"] > 0.30)]
    if len(snipers):
        snipers_top = snipers.sort_values("R_per_year", ascending=False).head(10)
        cols = ["source", "anchor", "trigger", "filter", "RR",
                 "n_per_week", "WR%", "total_R", "R/trade", "R_per_year"]
        print(snipers_top[cols].to_string(index=False))
        agg_rpy = snipers_top["R_per_year"].sum()
        agg_freq = snipers_top["n_per_week"].sum()
        print(f"\n  Top-10 sniper portfolio (теоретический):")
        print(f"    aggregated R/year @ 1% risk = {agg_rpy:.1f}/year")
        print(f"    aggregated n/нед = {agg_freq:.2f}")
        print(f"    Сравни с D2: +14.1 R/year (+89.5R / 6.33y), 1.11/нед")
    else:
        print("  нет таких")

    # ----- 6. UNIQUE setup analysis (исключая дубликаты по anchor/trigger/filter+RR) -----
    print("\n" + "="*80)
    print("UNIQUE TOP — лучшие уникальные setup'ы (топ-20 по R/year)")
    print("="*80)
    sane_unique = sane.copy()
    sane_unique["unique_key"] = (sane_unique["anchor"].astype(str) + "|" +
                                    sane_unique["trigger"].astype(str) + "|" +
                                    sane_unique["filter"].astype(str) + "|" +
                                    sane_unique["RR"].astype(str))
    # для каждого unique_key — берём из последнего источника (etap22 > etap18 > etap17 > etap14)
    # на самом деле колонки идентичные у одного и того же setup'а — берём первый
    sane_unique = sane_unique.drop_duplicates(subset="unique_key", keep="first")
    print(f"  total unique: {len(sane_unique)}")
    print(f"\n  TOP-20 by R_per_year:")
    cols = ["source", "anchor", "trigger", "filter", "RR",
             "n_per_week", "WR%", "total_R", "R/trade", "R_per_year"]
    top20 = sane_unique.sort_values("R_per_year", ascending=False).head(20)
    print(top20[cols].to_string(index=False))

    # save combined
    sane.to_csv(OUT_DIR / "etap24_combined_sane.csv", index=False)
    print(f"\n[INFO] saved: etap24_combined_sane.csv")


if __name__ == "__main__":
    main()
