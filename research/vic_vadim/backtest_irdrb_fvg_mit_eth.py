"""i-RDRB+FVG mitigation entry на ETH 1h, 6 лет (зеркало BTC-версии).

Параметры идентичны BTC: entry=0.9, SL=0.2, RR=1.4, без таймстопа.
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

CACHE = ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def scan(df_1h, df_1m):
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
            entry = zone_b + ENTRY_FRAC * width
            sl = zone_b + SL_FRAC * width
            risk = entry - sl
            tp = entry + RR * risk
        else:
            entry = zone_t - ENTRY_FRAC * width
            sl = zone_t - SL_FRAC * width
            risk = sl - entry
            tp = entry - RR * risk

        signal_time = idx[k + 2] + pd.Timedelta(minutes=60)
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mit"}); continue
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
                     "i_time": idx[k - 2], "fvg_c2_time": idx[k + 2]})
    return pd.DataFrame(rows)


def main():
    print("loading ETH 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    print(f"  bars: {len(df_1m):,}  start: {df_1m.index.min()}  end: {df_1m.index.max()}", flush=True)
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    print(f"  1h-bars: {len(df_1h):,}", flush=True)

    print("scanning...", flush=True)
    df = scan(df_1h, df_1m)

    total = len(df)
    no_mit = int((df["outcome"] == "no_mit").sum())
    ne = int((df["outcome"] == "no_entry").sum())
    nf = int((df["outcome"] == "not_filled").sum())
    op = int((df["outcome"] == "open").sum())
    w = int((df["outcome"] == "win").sum())
    l = int((df["outcome"] == "loss").sum())
    closed = w + l
    wr = w/closed*100 if closed else 0
    r = w*RR - l

    print(f"\n=== ETH 1h, entry=0.9, SL=0.2, RR=1.4 ===")
    print(f"  total={total}  no_mit={no_mit}  no_entry={ne}  not_filled={nf}  open={op}")
    print(f"  closed={closed}  W={w} L={l}  WR={wr:.2f}%  ΣR={r:+.2f}  R/trade={r/closed if closed else 0:+.3f}")

    for d in ("LONG", "SHORT"):
        sub = df[(df["dir"] == d) & df["outcome"].isin(["win", "loss"])]
        ww = int((sub["outcome"] == "win").sum()); ll = len(sub) - ww
        cn = ww + ll
        wwr = ww/cn*100 if cn else 0
        rr_d = ww*RR - ll
        print(f"  {d:>5}: n={cn} W={ww} L={ll} WR={wwr:.2f}% ΣR={rr_d:+.2f} R/trade={rr_d/cn if cn else 0:+.3f}")

    out = ROOT / "signals" / "irdrb_fvg_mit_zone_ETH.csv"
    df.to_csv(out, index=False)
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
