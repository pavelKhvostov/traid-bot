"""Этап 29: гипотеза — после FVG образуется RDRB?

Быстрая статистическая проверка:
1. Detect все FVG на ТФ X
2. Для каждой FVG: проверить окно [c2+1, c2+N] баров — есть ли RDRB?
3. Сравнить с baseline (случайный N-бар window)
4. Разделить same-direction vs opposite-direction RDRB
5. Также spatial check: RDRB внутри FVG zone, above, below

Если % RDRB после FVG значительно выше random baseline — pattern есть.
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

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
WINDOW_BARS = 20  # сколько баров после c2 проверяем

OUT_DIR = Path("research/elements_study/output")


def detect_rdrb(df, idx):
    if idx < 2: return None
    a = df.iloc[idx-2]; m = df.iloc[idx-1]; c = df.iloc[idx]
    a_o, a_c, a_h, a_l = float(a["open"]), float(a["close"]), float(a["high"]), float(a["low"])
    m_c = float(m["close"])
    c_o, c_h, c_l, c_c = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    if m_c > a_h and c_l < a_h and c_c > a_h:
        zb = max(c_l, max(a_o, a_c)); zt = min(a_h, min(c_o, c_c))
        if zt <= zb: return None
        return {"direction": "LONG", "bottom": zb, "top": zt}
    if m_c < a_l and c_h > a_l and c_c < a_l:
        zb = max(a_l, max(c_o, c_c)); zt = min(c_h, min(a_o, a_c))
        if zt <= zb: return None
        return {"direction": "SHORT", "bottom": zb, "top": zt}
    return None


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def analyze_tf(df, tf_label):
    print(f"\n--- {tf_label} ({len(df)} bars) ---")

    # Detect все FVG
    fvgs = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        fvgs.append({"idx": idx, "direction": f.direction,
                      "bottom": f.bottom, "top": f.top, "c2_time": f.c2_time})
    print(f"  FVGs detected: {len(fvgs)}")

    # Detect все RDRB и сохранить idx
    rdrbs_by_idx = {}
    for idx in range(2, len(df) - 1):
        r = detect_rdrb(df, idx)
        if r is None: continue
        rdrbs_by_idx[idx] = r
    print(f"  RDRBs detected: {len(rdrbs_by_idx)}")
    print(f"  RDRB density: {len(rdrbs_by_idx)/len(df)*100:.2f}% of bars have RDRB")

    # Baseline: вероятность случайно встретить RDRB в окне WINDOW_BARS
    # Простая оценка: для произвольной точки i, P(RDRB в [i+1, i+W]) = ?
    # Считаем: 1 - (1 - density)^W (приближение если события независимы)
    density = len(rdrbs_by_idx) / len(df)
    baseline_prob = 1 - (1 - density) ** WINDOW_BARS
    print(f"  Baseline P(RDRB в окне {WINDOW_BARS} бар) ~ {baseline_prob*100:.1f}%")

    # Также эмпирический baseline: для случайных позиций
    np.random.seed(42)
    sample_size = min(5000, len(df) - WINDOW_BARS - 1)
    random_positions = np.random.randint(2, len(df) - WINDOW_BARS - 1, size=sample_size)
    rand_with_rdrb = 0
    rand_with_rdrb_long = 0
    rand_with_rdrb_short = 0
    for pos in random_positions:
        for j in range(pos + 1, pos + 1 + WINDOW_BARS):
            if j in rdrbs_by_idx:
                rand_with_rdrb += 1
                if rdrbs_by_idx[j]["direction"] == "LONG":
                    rand_with_rdrb_long += 1
                else:
                    rand_with_rdrb_short += 1
                break
    rand_pct = rand_with_rdrb / sample_size * 100
    rand_long_pct = rand_with_rdrb_long / sample_size * 100
    rand_short_pct = rand_with_rdrb_short / sample_size * 100
    print(f"  Empirical baseline (random {sample_size} positions):")
    print(f"    any RDRB:    {rand_pct:.1f}%")
    print(f"    LONG RDRB:   {rand_long_pct:.1f}%")
    print(f"    SHORT RDRB:  {rand_short_pct:.1f}%")

    # Тест: после каждого FVG, в окне [c2+1, c2+W], есть RDRB?
    after_fvg_any = 0
    after_fvg_same_dir = 0
    after_fvg_opp_dir = 0
    rdrb_inside_fvg_zone = 0
    rdrb_above_fvg = 0
    rdrb_below_fvg = 0
    for f in fvgs:
        c2_idx = f["idx"]  # FVG.c2 idx; c2_time = open of c2
        found_rdrb = False
        first_rdrb = None
        for j in range(c2_idx + 1, min(c2_idx + 1 + WINDOW_BARS, len(df))):
            if j in rdrbs_by_idx:
                first_rdrb = rdrbs_by_idx[j]
                found_rdrb = True
                break
        if found_rdrb:
            after_fvg_any += 1
            if first_rdrb["direction"] == f["direction"]:
                after_fvg_same_dir += 1
            else:
                after_fvg_opp_dir += 1
            # Spatial relationship
            if zones_overlap(first_rdrb["bottom"], first_rdrb["top"],
                              f["bottom"], f["top"]):
                rdrb_inside_fvg_zone += 1
            elif first_rdrb["bottom"] > f["top"]:
                rdrb_above_fvg += 1
            else:
                rdrb_below_fvg += 1
    n = len(fvgs)
    if n == 0:
        return None
    pct_any = after_fvg_any / n * 100
    pct_same = after_fvg_same_dir / n * 100
    pct_opp = after_fvg_opp_dir / n * 100
    print(f"\n  AFTER FVG (in next {WINDOW_BARS} bars):")
    print(f"    any RDRB:                {pct_any:.1f}% (vs baseline {rand_pct:.1f}%, delta {pct_any-rand_pct:+.1f}pp)")
    print(f"    same-direction RDRB:     {pct_same:.1f}%")
    print(f"    opposite-direction RDRB: {pct_opp:.1f}%")
    print(f"\n  Spatial (of RDRBs that follow):")
    if after_fvg_any > 0:
        print(f"    inside FVG zone:  {rdrb_inside_fvg_zone/after_fvg_any*100:.1f}%")
        print(f"    above FVG:        {rdrb_above_fvg/after_fvg_any*100:.1f}%")
        print(f"    below FVG:        {rdrb_below_fvg/after_fvg_any*100:.1f}%")

    return {"tf": tf_label, "n_fvg": n, "pct_any_rdrb": pct_any,
             "baseline_pct": rand_pct, "delta_pp": pct_any - rand_pct,
             "pct_same_dir": pct_same, "pct_opp_dir": pct_opp,
             "rdrb_in_zone_pct": rdrb_inside_fvg_zone/after_fvg_any*100 if after_fvg_any else 0}


def main():
    results = []
    for tf in ["1h", "2h", "4h", "12h", "1d"]:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        r = analyze_tf(df, tf)
        if r: results.append(r)

    print("\n" + "="*70)
    print("SUMMARY ACROSS TFs")
    print("="*70)
    df_sum = pd.DataFrame(results)
    print(df_sum.to_string(index=False))

    df_sum.to_csv(OUT_DIR / "etap29_fvg_to_rdrb.csv", index=False)


if __name__ == "__main__":
    main()
