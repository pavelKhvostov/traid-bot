"""Entry-backtest i-RDRB+FVG mitigation с новой точкой входа:
50% диапазона между EVoT maxV (3 свечи FVG: #3..#5) и верхней/нижней
границей FVG (low(#5) для LONG, high(#5) для SHORT).

  LONG:  entry = maxV + 0.5 * (low(#5) - maxV)    (требует maxV < low(#5))
  SHORT: entry = high(#5) + 0.5 * (maxV - high(#5)) (требует maxV > high(#5))

SL = zone_bottom + 0.2*width (LONG) / zone_top - 0.2*width (SHORT)  — как было.
RR = 1.4.
Митигация zone_top/zone_bottom без изменения.
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
    idx_1h = df_1h.index
    o1 = df_1m["open"].to_numpy(); c1 = df_1m["close"].to_numpy()
    v1 = df_1m["volume"].to_numpy()
    idx1 = df_1m.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()

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
        # SL без изменений
        if i_dir == "LONG":
            sl = zone_b + SL_FRAC * width
        else:
            sl = zone_t - SL_FRAC * width

        # EVoT maxV на тройке FVG (#3..#5)
        rng_start = idx_1h[k]
        rng_end = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        sp1 = int(idx1.searchsorted(rng_start, side="left"))
        ep1 = int(idx1.searchsorted(rng_end, side="left"))
        if ep1 <= sp1: continue
        seg_o = o1[sp1:ep1]; seg_c = c1[sp1:ep1]; seg_v = v1[sp1:ep1]
        bull_mask = seg_c > seg_o
        bear_mask = seg_c < seg_o
        max_bull_vol = float(seg_v[bull_mask].max()) if bull_mask.any() else 0.0
        max_bear_vol = float(seg_v[bear_mask].max()) if bear_mask.any() else 0.0
        if max_bull_vol == 0 and max_bear_vol == 0: continue
        if max_bull_vol >= max_bear_vol:
            ix = int(np.argmax(np.where(bull_mask, seg_v, 0)))
            maxv_price = float(seg_c[ix])
        else:
            ix = int(np.argmax(np.where(bear_mask, seg_v, 0)))
            maxv_price = float(seg_c[ix])

        # New entry = 50% диапазона [maxV, FVG-граница]
        if i_dir == "LONG":
            fvg_border = zone_t  # = low(#5)
            if maxv_price >= fvg_border:
                rows.append({"dir": i_dir, "outcome": "bad_geometry"}); continue
            entry = maxv_price + 0.5 * (fvg_border - maxv_price)
            if entry <= sl:
                rows.append({"dir": i_dir, "outcome": "bad_risk"}); continue
            risk = entry - sl
            tp = entry + RR * risk
        else:
            fvg_border = zone_b  # = high(#5)
            if maxv_price <= fvg_border:
                rows.append({"dir": i_dir, "outcome": "bad_geometry"}); continue
            entry = fvg_border + 0.5 * (maxv_price - fvg_border)
            if entry >= sl:
                rows.append({"dir": i_dir, "outcome": "bad_risk"}); continue
            risk = sl - entry
            tp = entry - RR * risk

        # Симуляция (mitigation как раньше)
        signal_time = idx_1h[k + 2] + pd.Timedelta(minutes=60)
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
                     "entry": entry, "sl": sl, "tp": tp,
                     "maxv": maxv_price, "fvg_border": fvg_border,
                     "zone_b": zone_b, "zone_t": zone_t,
                     "risk_pct": risk/entry*100})
    return pd.DataFrame(rows)


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])

    print("scanning...", flush=True)
    df = scan(df_1h, df_1m)

    total = len(df)
    bg = int((df["outcome"] == "bad_geometry").sum())
    br = int((df["outcome"] == "bad_risk").sum())
    no_mit = int((df["outcome"] == "no_mit").sum())
    ne = int((df["outcome"] == "no_entry").sum())
    nf = int((df["outcome"] == "not_filled").sum())
    op = int((df["outcome"] == "open").sum())
    w = int((df["outcome"] == "win").sum())
    l = int((df["outcome"] == "loss").sum())
    closed = w + l
    wr = w/closed*100 if closed else 0
    r = w*RR - l

    print(f"\ntotal={total}")
    print(f"  bad_geometry={bg}  bad_risk={br}  no_mit={no_mit}  no_entry={ne}  not_filled={nf}  open={op}")
    print(f"  closed={closed}  WR={wr:.2f}%  ΣR={r:+.2f}  R/trade={r/closed if closed else 0:+.3f}")
    print(f"\n=== Baseline (старый entry=0.9, для сравнения) ===")
    print(f"  closed=730  WR=50.27%  ΣR=+150.80  R/trade=+0.207")
    print(f"\n=== Δ ===")
    print(f"  Δclosed={closed-730:+}  ΔWR={wr-50.27:+.2f}pp  ΔΣR={r-150.80:+.2f}  ΔR/trade={(r/closed if closed else 0)-0.207:+.3f}")

    for d in ("LONG", "SHORT"):
        sub = df[(df["dir"] == d) & df["outcome"].isin(["win", "loss"])]
        ww = int((sub["outcome"] == "win").sum()); ll = len(sub) - ww
        cn = ww + ll
        wwr = ww/cn*100 if cn else 0
        rr_d = ww*RR - ll
        print(f"  {d:>5}: n={cn} W={ww} L={ll} WR={wwr:.2f}% ΣR={rr_d:+.2f} R/trade={rr_d/cn if cn else 0:+.3f}")

    out = ROOT / "signals" / "irdrb_fvg_evot_entry.csv"
    df.to_csv(out, index=False)
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
