"""A — Cascade: A1 Pre-W ∩ A2 ext_5 ∩ A3 color ∩ A4 body+wick.

Генерирует baseline A4-output: список pivot candidates на 12h, оценивает Williams n=2 confirmation.

Output: ~/Desktop/pred12h_baseline_v2.parquet
    pivot_open_ts_ms · direction · confirmable · confirmed · body_pct · wick_pct · color

Окно: 2020-01-01 → текущий момент (UTC).
Causal: ✅ (для feature; confirmation на i+1,i+2 — label only, не feature).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from _lib import load_12h, BASELINE

LEFT_EXT_N = 5
BODY_MAX = 0.80
WICK_MIN = 0.03


def main():
    bars = load_12h()
    n = bars["n"]
    o, h, l, c = bars["o"], bars["h"], bars["l"], bars["c"]
    body = np.abs(c - o); rng = h - l
    safe = np.where(rng > 0, rng, 1.0)
    body_pct = body / safe
    upper_wick_pct = (h - np.maximum(o, c)) / safe
    lower_wick_pct = (np.minimum(o, c) - l) / safe
    color = np.where(c > o, 1, np.where(c < o, -1, 0))
    non_doji = color != 0

    # A1 Pre-W (3-bar local extreme)
    fh_prew = np.zeros(n, dtype=bool); fl_prew = np.zeros(n, dtype=bool)
    fh_prew[2:] = (h[2:] > h[1:-1]) & (h[2:] > h[:-2])
    fl_prew[2:] = (l[2:] < l[1:-1]) & (l[2:] < l[:-2])

    # A2 ext_5
    left_max_h = np.full(n, -np.inf); left_min_l = np.full(n, np.inf)
    for i in range(LEFT_EXT_N, n):
        left_max_h[i] = h[i - LEFT_EXT_N:i].max()
        left_min_l[i] = l[i - LEFT_EXT_N:i].min()
    fh_a2 = fh_prew & (h > left_max_h)
    fl_a2 = fl_prew & (l < left_min_l)

    # A3 color: opp_colors ∨ three_same (no doji)
    opp = np.zeros(n, dtype=bool)
    opp[1:] = non_doji[1:] & non_doji[:-1] & (color[1:] != color[:-1])
    three = np.zeros(n, dtype=bool)
    three[2:] = (non_doji[2:] & non_doji[1:-1] & non_doji[:-2]
                 & (color[2:] == color[1:-1]) & (color[1:-1] == color[:-2]))
    a3_pass = opp | three
    fh_a3 = fh_a2 & a3_pass; fl_a3 = fl_a2 & a3_pass

    # A4 body+wick
    fh_a4 = fh_a3 & (rng > 0) & (body_pct <= BODY_MAX) & (upper_wick_pct >= WICK_MIN)
    fl_a4 = fl_a3 & (rng > 0) & (body_pct <= BODY_MAX) & (lower_wick_pct >= WICK_MIN)

    # Williams n=2 right confirmation (label only)
    fh_conf = np.zeros(n, dtype=bool); fl_conf = np.zeros(n, dtype=bool)
    fh_conf[:-2] = (h[:-2] > h[1:-1]) & (h[:-2] > h[2:])
    fl_conf[:-2] = (l[:-2] < l[1:-1]) & (l[:-2] < l[2:])

    confirmable_mask = np.arange(n) < (n - 2)

    rows = []
    t = bars["t"]
    for i in range(n):
        if fh_a4[i]:
            rows.append({
                "pivot_open_ts_ms": int(t[i]), "direction": "high",
                "confirmable": bool(confirmable_mask[i]), "confirmed": bool(fh_conf[i]),
                "body_pct": float(body_pct[i]), "wick_pct": float(upper_wick_pct[i]),
                "color": int(color[i]),
            })
        if fl_a4[i]:
            rows.append({
                "pivot_open_ts_ms": int(t[i]), "direction": "low",
                "confirmable": bool(confirmable_mask[i]), "confirmed": bool(fl_conf[i]),
                "body_pct": float(body_pct[i]), "wick_pct": float(lower_wick_pct[i]),
                "color": int(color[i]),
            })

    df = pd.DataFrame(rows)
    df.to_parquet(BASELINE, index=False)
    n_conf = int(df["confirmed"].sum())
    wr = 100 * n_conf / len(df) if len(df) else 0
    print(f"A4 baseline: n = {len(df)}, conf = {n_conf}, WR = {wr:.2f}%")
    print(f"Saved: {BASELINE}")


if __name__ == "__main__":
    main()
