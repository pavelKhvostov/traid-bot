"""Фильтр: свечи #3 (trigger) и #4 (inversion) обе закрываются в направлении сетапа.
  LONG i-RDRB:  close(#3) > open(#3) AND close(#4) > open(#4) (обе bullish)
  SHORT i-RDRB: close(#3) < open(#3) AND close(#4) < open(#4) (обе bearish)

BTC + ETH + SOL, 1h, 6 лет, RR=1.4 (как baseline).
Grid RR 1.0..3.0 для found subset.
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

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
    ("SOLUSDT", ROOT / "data" / "SOLUSDT_1m_vic_vadim.csv"),
]
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR_GRID = [round(x, 1) for x in np.arange(1.0, 3.01, 0.1)]


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def scan(asset, path):
    df_1m = load_1m(path)
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes_a = df_1h["close"].to_numpy()
    opens_a = df_1h["open"].to_numpy()
    idx = df_1h.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_1h, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes_a[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_1h, k + 2)
        if fvg is None or fvg.direction != i_dir: continue
        if i_dir == "LONG":
            zone_b = float(min(lows[k-2], lows[k-1], lows[k], lows[k+1]))
            zone_t = float(lows[k+2])
        else:
            zone_t = float(max(highs[k-2], highs[k-1], highs[k], highs[k+1]))
            zone_b = float(highs[k+2])
        if zone_t <= zone_b: continue
        width = zone_t - zone_b
        if i_dir == "LONG":
            entry = zone_b + ENTRY_FRAC * width; sl = zone_b + SL_FRAC * width
        else:
            entry = zone_t - ENTRY_FRAC * width; sl = zone_t - SL_FRAC * width
        risk = abs(entry - sl)

        # Фильтр: свечи #3 (k) и #4 (k+1) обе закрываются в направлении сетапа
        c3_dir = closes_a[k] > opens_a[k]
        c4_dir = closes_a[k+1] > opens_a[k+1]
        if i_dir == "LONG":
            c34_match = c3_dir and c4_dir  # обе bullish
        else:
            c34_match = (not c3_dir) and (not c4_dir)  # обе bearish

        # Симуляция при разных RR
        signal_time = idx[k + 2] + pd.Timedelta(minutes=60)
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0: continue
        mit_idx = sp + int(mit_hits[0])
        post_lo = lo1[mit_idx:]; post_hi = hi1[mit_idx:]
        m = len(post_lo)
        if i_dir == "LONG":
            entry_idxs = np.where(post_lo <= entry)[0]
        else:
            entry_idxs = np.where(post_hi >= entry)[0]

        outcomes = {}
        for rr in RR_GRID:
            if i_dir == "LONG":
                tp = entry + rr * risk
                tp_idxs = np.where(post_hi >= tp)[0]
            else:
                tp = entry - rr * risk
                tp_idxs = np.where(post_lo <= tp)[0]
            e_idx = int(entry_idxs[0]) if entry_idxs.size else m + 1
            tp_pre = int(tp_idxs[0]) if tp_idxs.size else m + 1
            if tp_pre < e_idx: outcomes[rr] = "no_entry"
            elif e_idx >= m: outcomes[rr] = "not_filled"
            else:
                p2l = post_lo[e_idx:]; p2h = post_hi[e_idx:]
                if i_dir == "LONG":
                    slm = p2l <= sl; tpm = p2h >= tp
                else:
                    slm = p2h >= sl; tpm = p2l <= tp
                sf = int(np.argmax(slm)) if slm.any() else -1
                tf = int(np.argmax(tpm)) if tpm.any() else -1
                if sf == -1 and tf == -1: outcomes[rr] = "open"
                elif sf == -1: outcomes[rr] = "win"
                elif tf == -1: outcomes[rr] = "loss"
                else: outcomes[rr] = "win" if tf < sf else "loss"

        rows.append({"asset": asset, "dir": i_dir, "c34_match": c34_match,
                     **{f"rr_{rr}": outcomes[rr] for rr in RR_GRID}})
    return pd.DataFrame(rows)


def stats_for(sub, rr_col, rr_val):
    closed = sub[sub[rr_col].isin(["win", "loss"])]
    w = int((closed[rr_col] == "win").sum())
    l = len(closed) - w
    n = w + l
    wr = w/n*100 if n else 0
    sR = w*rr_val - l
    return n, w, l, wr, sR, sR/n if n else 0


def main():
    parts = []
    for asset, path in ASSETS:
        print(f"scanning {asset}...", flush=True)
        df = scan(asset, path)
        parts.append(df)
    df_all = pd.concat(parts, ignore_index=True)
    out = ROOT / "signals" / "c34_dir_filter.csv"
    df_all.to_csv(out, index=False)
    print(f"saved: {out} ({len(df_all)} rows)\n")

    cats = {
        "BASELINE (все)": pd.Series(True, index=df_all.index),
        "c34 MATCH (#3 и #4 в dir)": df_all["c34_match"] == True,
        "c34 NO match (anti)": df_all["c34_match"] == False,
    }

    for cat_name, mask in cats.items():
        sub = df_all[mask]
        print(f"\n=== {cat_name} (n={len(sub)}) ===")
        print(f"  {'RR':>4} {'closed':>6} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7} {'R/yr':>7}")
        for rr in RR_GRID:
            n, w, l, wr, sR, r_tr = stats_for(sub, f"rr_{rr}", rr)
            print(f"  {rr:>4.1f} {n:>6} {w:>4} {l:>4} {wr:>6.2f} {sR:>+8.2f} {r_tr:>+7.3f} {sR/6:>+7.2f}")

    # Per-asset для c34 MATCH
    print(f"\n=== c34 MATCH per asset (RR=1.4) ===")
    print(f"  {'asset':>8} {'n':>5} {'closed':>6} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8}")
    for asset in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        sub = df_all[(df_all["asset"]==asset) & (df_all["c34_match"]==True)]
        n, w, l, wr, sR, _ = stats_for(sub, "rr_1.4", 1.4)
        print(f"  {asset:>8} {len(sub):>5} {n:>6} {w:>4} {l:>4} {wr:>6.2f} {sR:>+8.2f}")


if __name__ == "__main__":
    main()
