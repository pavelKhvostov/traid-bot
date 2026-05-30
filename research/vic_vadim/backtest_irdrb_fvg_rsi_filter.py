"""i-RDRB+FVG zone-mitigation + ASVK RSI-фильтр на 2h.

Условие C2:
  LONG:  хотя бы 1 close-бар из последних 10 2h-баров до signal_time
         с raw RSI(14, Wilder) ≤ below_level (адаптивный OS, ASVK).
  SHORT: симметрично — close-RSI ≥ above_level.

below_level / above_level — адаптивные уровни ASVK, считаются от ema_3
на 2h ТФ (rolling 200 баров).

BTC + ETH 1h, 6 лет, entry=0.9, SL=0.2, RR=1.4.
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
from research.asvk_rsi.plot_asvk_rsi import (
    rsi_wilder, adjusted_rsi, dynamic_levels, RSI_PERIOD,
)

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
]
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4
WIN_BARS_2H = 10  # окно проверки 10 2h-баров


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m, freq):
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def scan(df_1h, df_2h, df_1m, rsi_2h, above_2h, below_2h):
    """Сканирует setup'ы + RSI-фильтр на 2h. Возвращает (raw, df_results, df_filtered)."""
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    idx_1h = df_1h.index
    idx_2h = df_2h.index
    rsi_arr = rsi_2h.to_numpy()
    above_arr = above_2h.to_numpy()
    below_arr = below_2h.to_numpy()
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index

    rows = []
    raw_count = 0
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
        raw_count += 1

        # RSI-фильтр: окно 10 2h-баров ДО signal_time (= close FVG.c2)
        signal_time = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        # последний закрытый 2h-бар на момент signal_time
        i2 = int(idx_2h.searchsorted(signal_time, side="right")) - 1
        if i2 < WIN_BARS_2H + RSI_PERIOD:
            continue
        win_start = i2 - WIN_BARS_2H + 1
        win_rsi = rsi_arr[win_start: i2 + 1]
        win_above = above_arr[win_start: i2 + 1]
        win_below = below_arr[win_start: i2 + 1]
        # хотя бы 1 close с условием
        if i_dir == "LONG":
            if np.isnan(win_below).all(): continue
            condition_met = bool(np.nansum(win_rsi <= win_below) >= 1)
        else:
            if np.isnan(win_above).all(): continue
            condition_met = bool(np.nansum(win_rsi >= win_above) >= 1)

        # Setup geometry + execution
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

        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mit", "rsi_passed": condition_met}); continue
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
            rows.append({"dir": i_dir, "outcome": "no_entry", "rsi_passed": condition_met}); continue
        if e_idx >= m:
            rows.append({"dir": i_dir, "outcome": "not_filled", "rsi_passed": condition_met}); continue
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
        rows.append({"dir": i_dir, "outcome": outcome, "rsi_passed": condition_met})

    return raw_count, pd.DataFrame(rows)


def stats(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])]
    w = int((closed["outcome"] == "win").sum())
    l = int((closed["outcome"] == "loss").sum())
    n = w + l
    wr = w/n*100 if n else 0
    r = w*RR - l
    return {"label": label, "total": len(df), "closed": n,
            "W": w, "L": l, "WR": wr, "ΣR": r, "R/tr": r/n if n else 0}


def main():
    all_rows = []
    for asset, path in ASSETS:
        print(f"\n=== {asset} ===", flush=True)
        df_1m = load_1m(path)
        df_1m = df_1m[df_1m.index >= START]
        df_1h = resample(df_1m, "1h")
        df_2h = resample(df_1m, "2h")
        print(f"  bars: 1m={len(df_1m):,}, 1h={len(df_1h):,}, 2h={len(df_2h):,}")
        rsi_2h = rsi_wilder(df_2h["close"], RSI_PERIOD)
        ema3_2h = adjusted_rsi(df_2h["close"])
        above_2h, below_2h = dynamic_levels(ema3_2h)
        print(f"  scanning...")
        raw, df = scan(df_1h, df_2h, df_1m, rsi_2h, above_2h, below_2h)
        print(f"  raw setups: {raw}, after scan: {len(df)}")
        # Baseline (без RSI-фильтра) — все строки
        base = stats(df, f"{asset} baseline")
        passed = stats(df[df["rsi_passed"] == True], f"{asset} RSI passed")
        anti = stats(df[df["rsi_passed"] == False], f"{asset} RSI anti")
        all_rows.extend([base, passed, anti])
        for r in (base, passed, anti):
            print(f"  {r['label']:>26}: total={r['total']:>4} closed={r['closed']:>4} "
                  f"W={r['W']:>3} L={r['L']:>3} WR={r['WR']:>5.2f}% ΣR={r['ΣR']:>+7.2f} R/tr={r['R/tr']:>+6.3f}")

    # Σ портфель
    print(f"\n=== Σ портфель (BTC + ETH) ===")
    for kind in ("baseline", "RSI passed", "RSI anti"):
        subs = [s for s in all_rows if kind in s["label"]]
        w = sum(s["W"] for s in subs); l = sum(s["L"] for s in subs)
        n = w + l
        wr = w/n*100 if n else 0; r = w*RR - l
        print(f"  Σ {kind:>11}: closed={n:>4} W={w:>3} L={l:>3} WR={wr:>5.2f}% ΣR={r:>+7.2f} R/tr={r/n if n else 0:>+6.3f}")


if __name__ == "__main__":
    main()
