"""Двойной фильтр: OB-4h match (старый Фактор 2) + OB-1h на свечах #2-#3
с nested FVG-15m или FVG-20m.

+ Grid RR 1.0..3.0 для отфильтрованных setup'ов.

BTC + ETH + SOL, 1h, 6 лет.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb
from strategies.strategy_1_1_1 import detect_fvg, detect_ob_pair, zones_overlap

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


def resample(df_1m, freq):
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])


def find_fvg_in_window(df_ltf, start, end, ob_b, ob_t, direction):
    """Найти первую FVG нужного направления в окне [start, end], overlap с OB-zone."""
    seg = df_ltf[(df_ltf.index >= start) & (df_ltf.index <= end)]
    for k in range(2, len(seg)):
        fvg = detect_fvg(seg, k)
        if fvg is None or fvg.direction != direction: continue
        if zones_overlap(fvg.bottom, fvg.top, ob_b, ob_t):
            return fvg
    return None


def scan_asset(asset, path):
    df_1m = load_1m(path)
    df_1m = df_1m[df_1m.index >= START]
    df_1h = resample(df_1m, "1h")
    df_4h = resample(df_1m, "4h")
    df_15m = resample(df_1m, "15min")
    df_20m = resample(df_1m, "20min")

    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes_a = df_1h["close"].to_numpy()
    idx = df_1h.index
    idx_4h = df_4h.index
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
            entry = zone_b + ENTRY_FRAC * width
            sl = zone_b + SL_FRAC * width
        else:
            entry = zone_t - ENTRY_FRAC * width
            sl = zone_t - SL_FRAC * width
        risk = abs(entry - sl)

        # OB-4h match (Фактор 2)
        rng_start = idx[k - 2]
        rng_end = idx[k + 2] + pd.Timedelta(minutes=60)
        sp4 = int(idx_4h.searchsorted(rng_start, side="left"))
        ep4 = int(idx_4h.searchsorted(rng_end + pd.Timedelta(hours=4), side="right"))
        ob4h_match = False
        for ci in range(max(sp4, 1), min(ep4, len(idx_4h))):
            ob = detect_ob_pair(df_4h, ci)
            if ob is None: continue
            if ob.direction == i_dir:
                ob4h_match = True; break

        # OB-1h на свечах (#3, #4) = (k, k+1) direction-aware
        ob_1h_34 = detect_ob_pair(df_1h, k + 1)  # prev=df[k], cur=df[k+1] = #3, #4
        ob1h_34_match = ob_1h_34 is not None and ob_1h_34.direction == i_dir

        # FVG-15m или FVG-20m внутри OB-1h (#3-#4) — direction-aware
        fvg_in_ob1h = False
        if ob1h_34_match:
            search_start = idx[k]  # open #3
            search_end = idx[k + 1] + pd.Timedelta(minutes=60)  # close #4
            f15 = find_fvg_in_window(df_15m, search_start, search_end,
                                       ob_1h_34.bottom, ob_1h_34.top, i_dir)
            f20 = find_fvg_in_window(df_20m, search_start, search_end,
                                       ob_1h_34.bottom, ob_1h_34.top, i_dir)
            fvg_in_ob1h = (f15 is not None) or (f20 is not None)

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

        # Для каждого RR проверяем outcome
        outcomes_by_rr = {}
        for rr in RR_GRID:
            if i_dir == "LONG":
                tp = entry + rr * risk
                tp_idxs = np.where(post_hi >= tp)[0]
            else:
                tp = entry - rr * risk
                tp_idxs = np.where(post_lo <= tp)[0]
            e_idx = int(entry_idxs[0]) if entry_idxs.size else m + 1
            tp_pre = int(tp_idxs[0]) if tp_idxs.size else m + 1
            if tp_pre < e_idx: outcomes_by_rr[rr] = "no_entry"
            elif e_idx >= m: outcomes_by_rr[rr] = "not_filled"
            else:
                p2l = post_lo[e_idx:]; p2h = post_hi[e_idx:]
                if i_dir == "LONG":
                    slm = p2l <= sl; tpm = p2h >= tp
                else:
                    slm = p2h >= sl; tpm = p2l <= tp
                sf = int(np.argmax(slm)) if slm.any() else -1
                tf = int(np.argmax(tpm)) if tpm.any() else -1
                if sf == -1 and tf == -1: outcomes_by_rr[rr] = "open"
                elif sf == -1: outcomes_by_rr[rr] = "win"
                elif tf == -1: outcomes_by_rr[rr] = "loss"
                else: outcomes_by_rr[rr] = "win" if tf < sf else "loss"

        rows.append({"dir": i_dir, "ob4h": ob4h_match, "ob1h_34": ob1h_34_match,
                     "fvg_in_ob1h": fvg_in_ob1h, **{f"rr_{rr}": outcomes_by_rr[rr] for rr in RR_GRID}})
    return pd.DataFrame(rows)


def stats_for_subset(sub, rr_col, rr_val):
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
        df = scan_asset(asset, path)
        df["asset"] = asset
        parts.append(df)
    df_all = pd.concat(parts, ignore_index=True)
    out = ROOT / "signals" / "ob4h_ob1h_fvg_grid.csv"
    df_all.to_csv(out, index=False)
    print(f"saved: {out} ({len(df_all)} rows)\n")

    # 3 категории сетапов (без OB-4h, фокус на #3-#4)
    cats = {
        "BASELINE": pd.Series(True, index=df_all.index),
        "OB-1h(#3-#4)": df_all["ob1h_34"] == True,
        "OB-1h(#3-#4) + FVG-nested": (df_all["ob1h_34"] == True) & (df_all["fvg_in_ob1h"] == True),
    }

    for cat_name, mask in cats.items():
        sub = df_all[mask]
        print(f"\n=== {cat_name} (n={len(sub)}) ===")
        print(f"  {'RR':>4} {'closed':>6} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7} {'R/yr':>7}")
        for rr in RR_GRID:
            n, w, l, wr, sR, r_tr = stats_for_subset(sub, f"rr_{rr}", rr)
            print(f"  {rr:>4.1f} {n:>6} {w:>4} {l:>4} {wr:>6.2f} {sR:>+8.2f} {r_tr:>+7.3f} {sR/6:>+7.2f}")


if __name__ == "__main__":
    main()
