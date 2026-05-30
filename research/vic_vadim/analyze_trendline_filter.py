"""ASVK Trend Line (Hull MA-78) на разных ТФ как direction-filter для
i-RDRB+FVG zone-mitigation стратегии (BTC 1h, 6y, RR=1.4).

Для каждого setup'а проверяем цвет Hull-78 на ТФ X в момент close FVG.c2
(свеча #5):
  GREEN: close(X)_lastclosed > HMA78(X)_lastclosed
  RED:   close(X)_lastclosed < HMA78(X)_lastclosed

Direct match  — LONG ∩ GREEN, SHORT ∩ RED (направление совпадает с трендом)
Anti  match   — LONG ∩ RED,   SHORT ∩ GREEN (контр-тренд)

ТФ: {1h, 2h, 4h, 6h, 12h, 1d}
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb
from strategies.strategy_1_1_1 import detect_fvg
from research.asvk_trend_line.plot_asvk_trend_line import hma

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2020-05-15", tz="UTC")
TFS_HULL = [("1h", "1h"), ("2h", "2h"), ("4h", "4h"), ("6h", "6h"),
            ("12h", "12h"), ("1d", "1D")]
HMA_LEN = 78
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m, freq):
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def compute_hull_color(df_tf):
    """Возвращает массив (1 = GREEN, 0 = RED) на каждом баре ТФ."""
    h = hma(df_tf["close"], HMA_LEN)
    return (df_tf["close"].to_numpy() > h.to_numpy()).astype(int)


def get_hull_at(df_tf, color_arr, t: pd.Timestamp) -> int | None:
    """Hull-цвет на ПОСЛЕДНЕЙ закрытой свече ТФ ≤ t."""
    i = int(df_tf.index.searchsorted(t, side="right")) - 1
    if i < HMA_LEN: return None
    return int(color_arr[i])


def scan_with_hull(df_1h, df_1m, hull_tfs):
    """hull_tfs: dict label -> (df_tf, color_arr)"""
    n = len(df_1h)
    highs = df_1h["high"].to_numpy()
    lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    idx = df_1h.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_1h, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_1h, k + 2)
        if fvg is None or fvg.direction != i_dir: continue
        if i_dir == "LONG":
            zone_b = float(min(lows[k - 2], lows[k - 1], lows[k], lows[k + 1]))
            zone_t = float(lows[k + 2])
        else:
            zone_t = float(max(highs[k - 2], highs[k - 1], highs[k], highs[k + 1]))
            zone_b = float(highs[k + 2])
        if zone_t <= zone_b: continue
        width = zone_t - zone_b
        if i_dir == "LONG":
            entry = zone_b + ENTRY_FRAC * width
            sl = zone_b + SL_FRAC * width
            risk = entry - sl
            tp = entry + RR * risk
        else:
            entry = zone_t - ENTRY_FRAC * width
            sl = zone_t - SL_FRAC * width
            risk = sl - entry
            tp = entry - RR * risk

        # Hull color на момент close FVG.c2
        signal_time = idx[k + 2] + pd.Timedelta(minutes=60)  # close FVG.c2
        hull_colors = {}
        for tf_label, (df_tf, color_arr) in hull_tfs.items():
            c = get_hull_at(df_tf, color_arr, signal_time)
            hull_colors[tf_label] = c  # 1 GREEN, 0 RED, None если N/A

        # Симуляция (как в backtest_irdrb_fvg_mit_zone.py)
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            outcome = "no_mit"
        else:
            mit_idx = sp + int(mit_hits[0])
            post_lo = lo1[mit_idx:]; post_hi = hi1[mit_idx:]
            m = len(post_lo)
            if i_dir == "LONG":
                entry_idxs = np.where(post_lo <= entry)[0]
                tp_idxs = np.where(post_hi >= tp)[0]
            else:
                entry_idxs = np.where(post_hi >= entry)[0]
                tp_idxs = np.where(post_lo <= tp)[0]
            e_idx = int(entry_idxs[0]) if entry_idxs.size else m + 1
            tp_pre = int(tp_idxs[0]) if tp_idxs.size else m + 1
            if tp_pre < e_idx:
                outcome = "no_entry"
            elif e_idx >= m:
                outcome = "not_filled"
            else:
                post2_lo = post_lo[e_idx:]; post2_hi = post_hi[e_idx:]
                if i_dir == "LONG":
                    sl_mask = post2_lo <= sl; tp_mask = post2_hi >= tp
                else:
                    sl_mask = post2_hi >= sl; tp_mask = post2_lo <= tp
                sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
                tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
                if sl_first == -1 and tp_first == -1: outcome = "open"
                elif sl_first == -1: outcome = "win"
                elif tp_first == -1: outcome = "loss"
                else: outcome = "win" if tp_first < sl_first else "loss"

        row = {"dir": i_dir, "outcome": outcome}
        for tf_label in hull_tfs.keys():
            row[f"hull_{tf_label}"] = hull_colors[tf_label]
        rows.append(row)
    return pd.DataFrame(rows)


def stats_filtered(df, filter_mask, label):
    sub = df[filter_mask & df["outcome"].isin(["win", "loss"])]
    w = int((sub["outcome"] == "win").sum())
    l = int((sub["outcome"] == "loss").sum())
    n = w + l
    wr = w / n * 100 if n else 0
    r = w * RR - l
    r_per = r / n if n else 0
    return {"label": label, "n": n, "W": w, "L": l, "WR%": wr,
            "ΣR": r, "R/trade": r_per}


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]

    df_1h = resample(df_1m, "1h")
    print(f"  1h-bars: {len(df_1h):,}", flush=True)

    hull_tfs = {}
    for tf_label, freq in TFS_HULL:
        print(f"  Hull-78 on {tf_label}...", flush=True)
        df_tf = resample(df_1m, freq)
        color_arr = compute_hull_color(df_tf)
        hull_tfs[tf_label] = (df_tf, color_arr)

    print("scanning setups...", flush=True)
    df = scan_with_hull(df_1h, df_1m, hull_tfs)

    closed = df[df["outcome"].isin(["win", "loss"])]
    w0 = int((closed["outcome"] == "win").sum()); l0 = len(closed) - w0
    print(f"\n=== Baseline (без Hull-фильтра) ===")
    print(f"  n={len(closed)} W={w0} L={l0} WR={w0/len(closed)*100:.2f}% ΣR={w0*RR-l0:+.2f} R/trade={(w0*RR-l0)/len(closed):+.3f}")

    print(f"\n=== Direct match: LONG∩GREEN ∪ SHORT∩RED ===")
    print(f"{'TF':>4}  {'n':>4} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7}  {'Δn':>5} {'Δprec':>7}")
    print(f"{'base':>4}  {len(closed):>4} {w0:>4} {l0:>4} {w0/len(closed)*100:>6.2f} {w0*RR-l0:>+8.2f} {(w0*RR-l0)/len(closed):>+7.3f}")
    for tf_label in hull_tfs.keys():
        col = f"hull_{tf_label}"
        mask = ((df["dir"] == "LONG") & (df[col] == 1)) | ((df["dir"] == "SHORT") & (df[col] == 0))
        s = stats_filtered(df, mask, f"direct {tf_label}")
        dn = s["n"] - len(closed)
        dp = s["WR%"] - w0/len(closed)*100
        print(f"{tf_label:>4}  {s['n']:>4} {s['W']:>4} {s['L']:>4} {s['WR%']:>6.2f} {s['ΣR']:>+8.2f} {s['R/trade']:>+7.3f}  {dn:>+5} {dp:>+7.2f}")

    print(f"\n=== Anti match: LONG∩RED ∪ SHORT∩GREEN ===")
    print(f"{'TF':>4}  {'n':>4} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7}  {'Δn':>5} {'Δprec':>7}")
    for tf_label in hull_tfs.keys():
        col = f"hull_{tf_label}"
        mask = ((df["dir"] == "LONG") & (df[col] == 0)) | ((df["dir"] == "SHORT") & (df[col] == 1))
        s = stats_filtered(df, mask, f"anti {tf_label}")
        dn = s["n"] - len(closed)
        dp = s["WR%"] - w0/len(closed)*100
        print(f"{tf_label:>4}  {s['n']:>4} {s['W']:>4} {s['L']:>4} {s['WR%']:>6.2f} {s['ΣR']:>+8.2f} {s['R/trade']:>+7.3f}  {dn:>+5} {dp:>+7.2f}")

    out = ROOT / "signals" / "irdrb_trendline_filter.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
