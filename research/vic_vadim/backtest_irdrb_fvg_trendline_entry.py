"""i-RDRB+FVG mitigation entry со смещённой точкой входа на Hull-78 1h.

Логика entry:
  1. Setup готов на close FVG.c2 (свеча #5)
  2. Митигация: touch zone_top для LONG / zone_bottom для SHORT
  3. Hull-78 на 1h на момент митигации (последнее закрытое значение):
     - Если Hull ∈ (zone_bottom, zone_top) → entry = Hull (fixed level)
     - Иначе → skip setup (out of zone)
  4. После активации: ждём touch цены к этому уровню → fill
  5. SL = старая формула (zone_b + 0.2*width LONG), TP = entry + RR*risk

BTC + ETH 1h, 6 лет, RR=1.4.
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

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
]
START = pd.Timestamp("2020-05-15", tz="UTC")
SL_FRAC = 0.2
RR = 1.4
HMA_LEN = 78


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def scan(df_1h, df_1m, hull_arr):
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
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
            sl = zone_b + SL_FRAC * width
        else:
            sl = zone_t - SL_FRAC * width

        signal_time = idx[k + 2] + pd.Timedelta(minutes=60)
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        # Митигация
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mit"}); continue
        mit_idx = sp + int(mit_hits[0])
        mit_time = idx1[mit_idx]

        # Hull-78 1h на момент митигации — последний закрытый 1h бар ≤ mit_time
        i_hull = int(idx.searchsorted(mit_time, side="right")) - 1
        if i_hull < HMA_LEN: continue
        hull_val = hull_arr[i_hull]
        if np.isnan(hull_val):
            rows.append({"dir": i_dir, "outcome": "no_hull"}); continue

        # Skip если Hull вне зоны
        if not (zone_b < hull_val < zone_t):
            rows.append({"dir": i_dir, "outcome": "hull_out_of_zone"}); continue

        # Entry = Hull value (fixed)
        entry = float(hull_val)
        if i_dir == "LONG":
            if entry <= sl:
                rows.append({"dir": i_dir, "outcome": "hull_below_sl"}); continue
            risk = entry - sl
            tp = entry + RR * risk
        else:
            if entry >= sl:
                rows.append({"dir": i_dir, "outcome": "hull_above_sl"}); continue
            risk = sl - entry
            tp = entry - RR * risk

        # Симуляция: после mit_time ждём touch entry. no_entry если TP до entry.
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
            rows.append({"dir": i_dir, "outcome": "no_entry"}); continue
        if e_idx >= m:
            rows.append({"dir": i_dir, "outcome": "not_filled"}); continue
        post2_lo = post_lo[e_idx:]; post2_hi = post_hi[e_idx:]
        if i_dir == "LONG":
            sl_mask = post2_lo <= sl; tp_mask_a = post2_hi >= tp
        else:
            sl_mask = post2_hi >= sl; tp_mask_a = post2_lo <= tp
        sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
        tp_first = int(np.argmax(tp_mask_a)) if tp_mask_a.any() else -1
        if sl_first == -1 and tp_first == -1: outcome = "open"
        elif sl_first == -1: outcome = "win"
        elif tp_first == -1: outcome = "loss"
        else: outcome = "win" if tp_first < sl_first else "loss"
        rows.append({"dir": i_dir, "outcome": outcome,
                     "hull_in_zone_pct": (hull_val - zone_b) / width})
    return pd.DataFrame(rows)


def main():
    for asset, path in ASSETS:
        print(f"\n=== {asset} ===")
        df_1m = load_1m(path)
        df_1m = df_1m[df_1m.index >= START]
        df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
            "open":"first","high":"max","low":"min","close":"last","volume":"sum"
        }).dropna(subset=["close"])
        hull = hma(df_1h["close"], HMA_LEN).to_numpy()
        df = scan(df_1h, df_1m, hull)
        total = len(df)
        cats = {}
        for o in df["outcome"].unique():
            cats[o] = int((df["outcome"] == o).sum())
        w = cats.get("win", 0); l = cats.get("loss", 0); closed = w + l
        wr = w/closed*100 if closed else 0
        r = w*RR - l
        print(f"  total={total}")
        for o in sorted(cats.keys()):
            print(f"    {o:>20}: {cats[o]}")
        print(f"  closed={closed} W={w} L={l} WR={wr:.2f}% ΣR={r:+.2f} R/tr={r/closed if closed else 0:+.3f}")
        for d in ("LONG", "SHORT"):
            sub = df[(df["dir"] == d) & df["outcome"].isin(["win", "loss"])]
            ww = int((sub["outcome"] == "win").sum()); ll = len(sub) - ww
            cn = ww + ll
            wwr = ww/cn*100 if cn else 0
            print(f"    {d:>5}: n={cn} W={ww} L={ll} WR={wwr:.2f}% ΣR={ww*RR-ll:+.2f}")
        # Сохраним
        out = ROOT / "signals" / f"irdrb_fvg_trendline_entry_{asset}.csv"
        df.to_csv(out, index=False)


if __name__ == "__main__":
    main()
