"""Grid точки входа в V1 RDRB зону: entry_frac = 0.1..0.9 (шаг 0.1).
SL фикс = 0.2 от V1.bottom (LONG) / V1.top (SHORT).
RR = 1.4.
Митигация: ждать первого касания V1.zone_top для LONG / V1.zone_bottom для SHORT.

BTC 1h, 6 лет.
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
RR = 1.4
SL_FRAC = 0.2
ENTRY_GRID = [round(x, 1) for x in np.arange(0.3, 0.91, 0.1)]  # 0.3..0.9 (чтобы entry > SL)


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def scan():
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])
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

        v1_b = rdrb.bottom; v1_t = rdrb.top
        v1_width = v1_t - v1_b
        if v1_width <= 0: continue

        # SL фикс 0.2 V1
        if i_dir == "LONG":
            sl = v1_b + SL_FRAC * v1_width
            mit_level = v1_t  # цена должна коснуться V1.top для митигации (приходит сверху)
        else:
            sl = v1_t - SL_FRAC * v1_width
            mit_level = v1_b  # цена касается V1.bottom (приходит снизу)

        signal_time = idx[k + 2] + pd.Timedelta(minutes=60)
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        # Митигация
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= mit_level)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= mit_level)[0]
        if mit_hits.size == 0:
            continue
        mit_idx = sp + int(mit_hits[0])
        post_lo = lo1[mit_idx:]; post_hi = hi1[mit_idx:]
        m = len(post_lo)

        # Для каждой entry_frac посчитать outcome
        outcomes = {}
        for ef in ENTRY_GRID:
            if i_dir == "LONG":
                entry = v1_b + ef * v1_width
                if entry <= sl:
                    outcomes[ef] = "bad_geom"; continue
                risk = entry - sl
                tp = entry + RR * risk
                ei = np.where(post_lo <= entry)[0]
                ti = np.where(post_hi >= tp)[0]
            else:
                entry = v1_t - ef * v1_width
                if entry >= sl:
                    outcomes[ef] = "bad_geom"; continue
                risk = sl - entry
                tp = entry - RR * risk
                ei = np.where(post_hi >= entry)[0]
                ti = np.where(post_lo <= tp)[0]
            e_idx = int(ei[0]) if ei.size else m + 1
            tp_pre = int(ti[0]) if ti.size else m + 1
            if tp_pre < e_idx: outcomes[ef] = "no_entry"
            elif e_idx >= m: outcomes[ef] = "not_filled"
            else:
                p2l = post_lo[e_idx:]; p2h = post_hi[e_idx:]
                if i_dir == "LONG":
                    slm = p2l <= sl; tpm = p2h >= tp
                else:
                    slm = p2h >= sl; tpm = p2l <= tp
                sf = int(np.argmax(slm)) if slm.any() else -1
                tf = int(np.argmax(tpm)) if tpm.any() else -1
                if sf == -1 and tf == -1: outcomes[ef] = "open"
                elif sf == -1: outcomes[ef] = "win"
                elif tf == -1: outcomes[ef] = "loss"
                else: outcomes[ef] = "win" if tf < sf else "loss"
        rows.append({"dir": i_dir, **{f"e_{ef}": outcomes[ef] for ef in ENTRY_GRID}})
    return pd.DataFrame(rows)


def stats(df, col):
    closed = df[df[col].isin(["win", "loss"])]
    w = int((closed[col] == "win").sum())
    l = len(closed) - w
    n = w + l
    wr = w/n*100 if n else 0
    sR = w*RR - l
    bad = int((df[col] == "bad_geom").sum())
    ne = int((df[col] == "no_entry").sum())
    nf = int((df[col] == "not_filled").sum())
    return n, w, l, wr, sR, sR/n if n else 0, bad, ne, nf


def main():
    print("scanning BTC 1h...", flush=True)
    df = scan()
    print(f"setups (после mit): {len(df)}\n")

    print(f"{'ENTRY':>5} {'closed':>6} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8} "
          f"{'R/tr':>7} {'bad':>4} {'noE':>4} {'nf':>3} {'R/yr':>7}")
    for ef in ENTRY_GRID:
        n, w, l, wr, sR, r_tr, bad, ne, nf = stats(df, f"e_{ef}")
        print(f"{ef:>5.1f} {n:>6} {w:>4} {l:>4} {wr:>6.2f} {sR:>+8.2f} "
              f"{r_tr:>+7.3f} {bad:>4} {ne:>4} {nf:>3} {sR/6:>+7.2f}")

    print(f"\n=== Baseline (entry=0.9 в zone interest, SL=0.2 zone) ===")
    print(f"  closed=730 WR=50.27% ΣR=+150.80 R/tr=+0.207  R/yr=+25.13")


if __name__ == "__main__":
    main()
