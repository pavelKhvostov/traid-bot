"""Влияние Σvolume(i-1, i, i+1) на результат i-RDRB+FVG mitigation setup'а.

Σvol = volume(mid) + volume(trigger) + volume(inversion) — 3 центральные свечи.
Также: relative_vol = Σvol / SMA20(vol_per_bar).

Разбиение setup'ов на 4 квартиля по Σvol и по relative_vol — метрики на каждой.

BTC 1h, 2020-05-15 → present, RR=1.4.
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

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2020-05-15", tz="UTC")

ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4
SMA_WIN = 20


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def scan(df_1h, df_1m):
    n = len(df_1h)
    highs = df_1h["high"].to_numpy()
    lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    vols = df_1h["volume"].to_numpy()
    sma_vol = pd.Series(vols).rolling(SMA_WIN).mean().to_numpy()
    idx = df_1h.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index

    rows = []
    for k in range(SMA_WIN, n - 5):
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

        # Зона интереса
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

        # Σvol(k-1, k, k+1) и relative
        sum_vol = float(vols[k - 1] + vols[k] + vols[k + 1])
        # SMA20 на свечу k (на момент сетапа)
        avg = float(sma_vol[k])
        rel = sum_vol / (3 * avg) if avg > 0 else 0  # сравниваем со средним bar volume × 3

        # Симуляция с митигацией
        start_time = idx[k + 2] + pd.Timedelta(minutes=60)
        sp = int(idx1.searchsorted(start_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mit", "sum_vol": sum_vol, "rel_vol": rel}); continue
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
            rows.append({"dir": i_dir, "outcome": "no_entry", "sum_vol": sum_vol, "rel_vol": rel}); continue
        if e_idx >= m:
            rows.append({"dir": i_dir, "outcome": "not_filled", "sum_vol": sum_vol, "rel_vol": rel}); continue
        post2_lo = post_lo[e_idx:]; post2_hi = post_hi[e_idx:]
        if i_dir == "LONG":
            sl_mask = post2_lo <= sl; tp_mask = post2_hi >= tp
        else:
            sl_mask = post2_hi >= sl; tp_mask = post2_lo <= tp
        sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
        tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
        if sl_first == -1 and tp_first == -1:
            outcome = "open"
        elif sl_first == -1:
            outcome = "win"
        elif tp_first == -1:
            outcome = "loss"
        else:
            outcome = "win" if tp_first < sl_first else "loss"
        r_val = (RR if outcome == "win" else (-1.0 if outcome == "loss" else 0.0))
        rows.append({"dir": i_dir, "outcome": outcome, "sum_vol": sum_vol, "rel_vol": rel, "r": r_val})

    return pd.DataFrame(rows)


def stats_by_bucket(df, key, edges=None, labels=None):
    """Считаем WR/ΣR/n по бакетам по 'key'."""
    df = df[df["outcome"].isin(["win", "loss"])].copy()
    if edges is None:
        df["bucket"] = pd.qcut(df[key], q=4, labels=["Q1 (low)", "Q2", "Q3", "Q4 (high)"])
    else:
        df["bucket"] = pd.cut(df[key], bins=edges, labels=labels)
    out = []
    for b in df["bucket"].cat.categories:
        sub = df[df["bucket"] == b]
        w = int((sub["outcome"] == "win").sum())
        l = int((sub["outcome"] == "loss").sum())
        n = w + l
        wr = w / n * 100 if n else 0
        r = w * RR - l
        out.append({"bucket": b, "n": n, "W": w, "L": l, "WR": wr, "ΣR": r,
                    "R/trade": r / n if n else 0,
                    "range_min": sub[key].min(), "range_max": sub[key].max()})
    return pd.DataFrame(out)


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    print(f"  1h-bars: {len(df_1h):,}", flush=True)

    print("scanning...", flush=True)
    df = scan(df_1h, df_1m)
    out = ROOT / "signals" / "irdrb_fvg_volume_analysis.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    closed = df[df["outcome"].isin(["win", "loss"])]
    print(f"\n=== Σ baseline ===")
    print(f"  total setups: {len(df)}, closed: {len(closed)}")
    w = int((closed["outcome"] == "win").sum()); l = len(closed) - w
    print(f"  WR={w/len(closed)*100:.2f}%  ΣR={w*RR-l:+.2f}  R/trade={(w*RR-l)/len(closed):+.3f}")

    print(f"\n=== По Σvol(k-1,k,k+1) — квартили ===")
    s = stats_by_bucket(df, "sum_vol")
    print(s.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== По relative_vol (Σvol / 3·SMA20) — квартили ===")
    s = stats_by_bucket(df, "rel_vol")
    print(s.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    print(f"\n=== По relative_vol — пороги <0.5 / 0.5-1 / 1-1.5 / >1.5 ===")
    edges = [-np.inf, 0.5, 1.0, 1.5, np.inf]
    labels = ["<0.5", "0.5-1.0", "1.0-1.5", ">1.5"]
    s = stats_by_bucket(df, "rel_vol", edges=edges, labels=labels)
    print(s.to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
