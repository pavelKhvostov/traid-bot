"""Partition 4: N11 — Reversed analysis.

Brute-force поиск комбинаций бинарных признаков (1-2-3 шт), при которых
WR существенно НИЖЕ baseline. Цель: «category to avoid» — анти-фильтр.

Гипотеза: если убрать пару категорий «не играть», baseline WR растёт без
сложного confluence-engine.
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

from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

INPUT_CSV = Path("signals/strategy_3_2_3y_RR1_unconventional.csv")
RR = 1.0
MIN_N = 10  # минимум сделок в группе для значимости


def main():
    df = pd.read_csv(INPUT_CSV)
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    total = len(closed)
    base_w = (closed["outcome"] == "win").sum()
    base_wr = base_w / total * 100
    print(f"BASELINE  closed={total}  WR={base_wr:.1f}%  R/tr={(2*base_w-total)/total:.3f}")
    print()

    # Список бинарных признаков
    long_mask = closed["direction"] == "LONG"
    short_mask = closed["direction"] == "SHORT"

    features = {}
    features["dir=LONG"] = long_mask
    features["dir=SHORT"] = short_mask
    features["session=asia"] = closed["session"] == "asia"
    features["session=us"] = closed["session"] == "us"
    features["session=europe"] = closed["session"] == "europe"
    features["weekday=Sunday"] = closed["weekday"] == "Sunday"
    features["weekday=Friday"] = closed["weekday"] == "Friday"
    features["fvg_age<24h"] = closed["fvg_4h_age_hours"] < 24
    features["fvg_age>168h"] = closed["fvg_4h_age_hours"] >= 168
    q_size = closed["fvg_4h_size_pct"].quantile([0.25, 0.75])
    features["fvg_size_small"] = closed["fvg_4h_size_pct"] < q_size[0.25]
    features["fvg_size_large"] = closed["fvg_4h_size_pct"] >= q_size[0.75]
    features["bw2_green_phase"] = closed["bw2_color"] == "green"
    features["bw2_red_phase"] = closed["bw2_color"] == "red"
    features["bw2_grey_after_green"] = closed["bw2_color"] == "grey_after_green"
    features["bw2_grey_after_red"] = closed["bw2_color"] == "grey_after_red"
    features["mf>0"] = closed["mf_at_signal"] > 0
    features["mf<0"] = closed["mf_at_signal"] < 0
    q_mf = closed["abs_mf_at_signal"].quantile([0.25, 0.75])
    features["abs_mf_low"] = closed["abs_mf_at_signal"] < q_mf[0.25]
    features["abs_mf_mid"] = (closed["abs_mf_at_signal"] >= q_mf[0.25]) & \
                              (closed["abs_mf_at_signal"] < q_mf[0.75])
    features["abs_mf_high"] = closed["abs_mf_at_signal"] >= q_mf[0.75]
    features["aligned_div_present"] = (
        ((closed["bull_div_in_window"] == True) & long_mask)
        | ((closed["h_bull_div_in_window"] == True) & long_mask)
        | ((closed["bear_div_in_window"] == True) & short_mask)
        | ((closed["h_bear_div_in_window"] == True) & short_mask)
    )
    features["div_age_fresh<=6h"] = closed["aligned_div_age_hours"] <= 6
    features["div_age_old>30h"] = closed["aligned_div_age_hours"] > 30
    features["after_3+_wins"] = closed["win_streak_before"] >= 3
    features["after_3+_losses"] = closed["loss_streak_before"] >= 3
    features["bars_since_OB>100_LONG"] = long_mask & (closed["bars_since_ob"] > 100)
    features["nwe_width_narrow"] = (closed["nwe_width_at_signal"] <=
                                      closed["nwe_width_at_signal"].quantile(0.3))

    print(f"Features prepared: {len(features)}")
    print()

    # ---------- Single-feature: топ-anti ----------
    print("=" * 100)
    print("SINGLE-FEATURE WORST (n>=10)")
    print("=" * 100)
    rows = []
    for name, mask in features.items():
        n = int(mask.sum())
        if n < MIN_N:
            continue
        sub = closed[mask]
        w = (sub["outcome"] == "win").sum()
        wr = w / n * 100
        rt = (2 * w - n) / n
        rows.append((name, n, wr, rt))
    rows.sort(key=lambda r: r[2])  # by WR ascending
    print(f"{'feature':<35s} {'n':>5} {'WR':>7} {'R/tr':>8}")
    for r in rows[:8]:
        print(f"  {r[0]:<35s} {r[1]:>5} {r[2]:>7.1f}% {r[3]:>+8.3f}")

    print()
    print("=" * 100)
    print("PAIR-FEATURE WORST (n>=10)")
    print("=" * 100)
    pair_rows = []
    keys = list(features.keys())
    for k1, k2 in combinations(keys, 2):
        mask = features[k1] & features[k2]
        n = int(mask.sum())
        if n < MIN_N:
            continue
        sub = closed[mask]
        w = (sub["outcome"] == "win").sum()
        wr = w / n * 100
        rt = (2 * w - n) / n
        pair_rows.append((f"{k1} & {k2}", n, wr, rt))
    pair_rows.sort(key=lambda r: r[2])
    print(f"{'pair':<60s} {'n':>5} {'WR':>7} {'R/tr':>8}")
    for r in pair_rows[:15]:
        print(f"  {r[0]:<60s} {r[1]:>5} {r[2]:>7.1f}% {r[3]:>+8.3f}")

    print()
    print("=" * 100)
    print("TRIPLE-FEATURE WORST (n>=10)")
    print("=" * 100)
    triple_rows = []
    for k1, k2, k3 in combinations(keys, 3):
        mask = features[k1] & features[k2] & features[k3]
        n = int(mask.sum())
        if n < MIN_N:
            continue
        sub = closed[mask]
        w = (sub["outcome"] == "win").sum()
        wr = w / n * 100
        rt = (2 * w - n) / n
        triple_rows.append((f"{k1} & {k2} & {k3}", n, wr, rt))
    triple_rows.sort(key=lambda r: r[2])
    print(f"{'triple':<70s} {'n':>5} {'WR':>7} {'R/tr':>8}")
    for r in triple_rows[:15]:
        print(f"  {r[0]:<70s} {r[1]:>5} {r[2]:>7.1f}% {r[3]:>+8.3f}")

    # ---------- Cumulative removal of worst ----------
    print()
    print("=" * 100)
    print("CUMULATIVE REMOVAL — убираем worst-сегменты по очереди и смотрим на остаток")
    print("=" * 100)

    # Берём top-3 single features по WR < 50%
    bad_singles = [(n, m) for n, m in [(r[0], features[r[0]]) for r in rows[:5]] if m.sum() > 0]
    print(f"\nWorst-3 singles to potentially exclude:")
    for nm, _ in bad_singles[:3]:
        idx = next(i for i, r in enumerate(rows) if r[0] == nm)
        print(f"  - {nm}: n={rows[idx][1]} WR={rows[idx][2]:.1f}%")

    # Кумулятивное удаление
    cur_mask = pd.Series(True, index=closed.index)
    print("\nProgressive exclusion:")
    print(f"  start: n={cur_mask.sum()} WR={base_wr:.1f}% R/tr={(2*base_w - total)/total:+.3f}")
    for nm, m in bad_singles[:3]:
        cur_mask = cur_mask & (~m)
        sub = closed[cur_mask]
        n = len(sub)
        w = (sub["outcome"] == "win").sum()
        if n > 0:
            wr = w / n * 100
            rt = (2 * w - n) / n
            print(f"  - {nm}: n={n} WR={wr:.1f}% R/tr={rt:+.3f}")

    # Try: убрать top-3 worst pairs
    print()
    print("Сравнение: убрать top-3 worst PAIRS:")
    cur_mask = pd.Series(True, index=closed.index)
    used_keys = set()
    excluded_pairs = []
    for r in pair_rows[:5]:
        pair_str, _, _, _ = r
        k1, k2 = pair_str.split(" & ")
        # Чтобы не дублировать признаки, отслеживаем, нo это grubo. Допустим, что pairs независимы.
        pair_mask = features[k1] & features[k2]
        cur_mask = cur_mask & ~pair_mask
        excluded_pairs.append(pair_str)
        if len(excluded_pairs) == 3:
            break
    print(f"  excluded pairs: {excluded_pairs}")
    sub = closed[cur_mask]
    n = len(sub)
    w = (sub["outcome"] == "win").sum()
    if n > 0:
        wr = w / n * 100
        rt = (2 * w - n) / n
        print(f"  remaining: n={n} WR={wr:.1f}% R/tr={rt:+.3f}")


if __name__ == "__main__":
    main()
