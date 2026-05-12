"""Этап 30: узкая гипотеза — RDRB inside FVG zone, same direction, окно 5-10 баров.

Цель: если такой specific pattern существует — это могло бы быть triggers для
mitigation entry. Проверим:
1. Pattern P: FVG_LONG -> RDRB_LONG INSIDE FVG zone within next 5 bars
2. Baseline: probability random 5-bar window contains RDRB-same-dir-inside-zone-of-some-FVG (low)
3. Если pattern P >> baseline -> meaningful

Также проверим: какой WR имеет RDRB-after-FVG simple backtest?
- Setup: FVG c2 detected
- Trigger: первый RDRB same-direction inside FVG zone within 5 bars
- Entry: mid RDRB; SL: trigger_low/high; TP: RR=1
- Сравним с baseline FVG-only (без RDRB-trigger).
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
WINDOW_BARS = 5

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
        return {"direction": "LONG", "bottom": zb, "top": zt,
                "trigger_low": c_l, "trigger_high": c_h}
    if m_c < a_l and c_h > a_l and c_c < a_l:
        zb = max(a_l, max(c_o, c_c)); zt = min(c_h, min(a_o, a_c))
        if zt <= zb: return None
        return {"direction": "SHORT", "bottom": zb, "top": zt,
                "trigger_low": c_l, "trigger_high": c_h}
    return None


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def analyze(df, tf_label):
    print(f"\n--- {tf_label} ({len(df)} bars) ---")
    fvgs = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        fvgs.append({"idx": idx, "direction": f.direction,
                      "bottom": f.bottom, "top": f.top, "c2_time": f.c2_time})
    rdrbs_by_idx = {}
    for idx in range(2, len(df) - 1):
        r = detect_rdrb(df, idx)
        if r is None: continue
        rdrbs_by_idx[idx] = r

    # Pattern P count
    same_dir_inside = 0
    same_dir_inside_first = 0  # treats only first such RDRB
    fvg_with_match = 0
    for f in fvgs:
        match_found = False
        for j in range(f["idx"] + 1, min(f["idx"] + 1 + WINDOW_BARS, len(df))):
            if j not in rdrbs_by_idx: continue
            r = rdrbs_by_idx[j]
            if r["direction"] != f["direction"]: continue
            if not zones_overlap(r["bottom"], r["top"], f["bottom"], f["top"]):
                continue
            same_dir_inside += 1
            if not match_found:
                same_dir_inside_first += 1
                match_found = True
        if match_found:
            fvg_with_match += 1
    n = len(fvgs)
    pct_match = fvg_with_match / n * 100 if n else 0
    print(f"  FVGs: {n}, RDRBs: {len(rdrbs_by_idx)}")
    print(f"  Pattern P (same-dir RDRB inside FVG within {WINDOW_BARS} bars):")
    print(f"    {fvg_with_match} matches ({pct_match:.1f}% of FVGs)")

    # Baseline: рассчитываем эмпирически —
    # для случайных positions, что вероятность В тех же бар что-то inside-zone-some-FVG-same-dir
    # сложнее. Простой подход: random позиции (как baseline), проверяем что в окне есть RDRB
    # любого FVG (same direction inside any FVG zone) — но это требует знания FVG активности
    # на тот момент. Опускаем чёткий baseline — просто absolute pct match.

    return {"tf": tf_label, "n_fvg": n, "match_pct": pct_match,
             "n_match": fvg_with_match}


def main():
    rows = []
    for tf in ["1h", "2h", "4h", "12h", "1d"]:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        rows.append(analyze(df, tf))

    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    df_sum = pd.DataFrame(rows)
    print(df_sum.to_string(index=False))
    df_sum.to_csv(OUT_DIR / "etap30_fvg_rdrb_narrow.csv", index=False)


if __name__ == "__main__":
    main()
