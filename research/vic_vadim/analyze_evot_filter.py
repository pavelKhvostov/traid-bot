"""EVoT ASVK как направленный volume-фильтр для i-RDRB+FVG mitigation.

Диапазон: все 1m-минуты внутри 5 свечей setup'а (#1..#5 на 1h) =
[open(k-2), close(k+2)].

  bullMinute = volume(1m) если close(1m) > open(1m), иначе 0
  bearMinute = volume(1m) если close(1m) < open(1m), иначе 0
  rBull = Σ bullMinute,  rBear = Σ bearMinute
  rDelta = rBull − rBear
  rNorm = rDelta / (rBull + rBear)  ∈ [−1, +1]

Direct match:  LONG ∩ rNorm > 0,  SHORT ∩ rNorm < 0  (объём в направлении сетапа)
Anti match:    LONG ∩ rNorm < 0,  SHORT ∩ rNorm > 0  (объём против сетапа)

BTC 1h, 6 лет, RR=1.4.
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


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def scan(df_1h, df_1m):
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    idx_1h = df_1h.index
    o1 = df_1m["open"].to_numpy()
    c1 = df_1m["close"].to_numpy()
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

        # EVoT range: 5 свечей #1..#5 = [open(k-2), close(k+2)]
        rng_start = idx_1h[k - 2]
        rng_end = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        sp1 = int(idx1.searchsorted(rng_start, side="left"))
        ep1 = int(idx1.searchsorted(rng_end, side="left"))
        if ep1 <= sp1:
            continue
        seg_o = o1[sp1:ep1]; seg_c = c1[sp1:ep1]; seg_v = v1[sp1:ep1]
        bull_mask = seg_c > seg_o
        bear_mask = seg_c < seg_o
        r_bull = float(seg_v[bull_mask].sum())
        r_bear = float(seg_v[bear_mask].sum())
        r_vol = r_bull + r_bear
        if r_vol == 0:
            continue
        r_norm = (r_bull - r_bear) / r_vol  # [-1, +1]

        # Симуляция
        signal_time = idx_1h[k + 2] + pd.Timedelta(minutes=60)
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
            if tp_pre < e_idx: outcome = "no_entry"
            elif e_idx >= m: outcome = "not_filled"
            else:
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
        rows.append({"dir": i_dir, "outcome": outcome, "r_norm": r_norm,
                     "r_vol": r_vol, "r_bull": r_bull, "r_bear": r_bear})
    return pd.DataFrame(rows)


def stats(sub, label):
    sub = sub[sub["outcome"].isin(["win", "loss"])]
    w = int((sub["outcome"] == "win").sum()); l = len(sub) - w
    n = w + l
    wr = w/n*100 if n else 0
    r = w*RR - l
    return {"label": label, "n": n, "W": w, "L": l, "WR%": wr,
            "ΣR": r, "R/trade": r/n if n else 0}


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])

    print("scanning setups + EVoT...", flush=True)
    df = scan(df_1h, df_1m)
    closed = df[df["outcome"].isin(["win", "loss"])]
    w0 = int((closed["outcome"] == "win").sum()); l0 = len(closed) - w0
    base_wr = w0/len(closed)*100

    print(f"\n=== Baseline ===")
    print(f"  n={len(closed)} W={w0} L={l0} WR={base_wr:.2f}% ΣR={w0*RR-l0:+.2f} R/trade={(w0*RR-l0)/len(closed):+.3f}")

    print(f"\n=== Direct match (rNorm в направлении setup'а) ===")
    direct = df[((df["dir"] == "LONG") & (df["r_norm"] > 0)) |
                ((df["dir"] == "SHORT") & (df["r_norm"] < 0))]
    s = stats(direct, "direct")
    print(f"  n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/trade={s['R/trade']:+.3f}  Δprec={s['WR%']-base_wr:+.2f}pp  Δn={s['n']-len(closed):+}")

    print(f"\n=== Anti match (rNorm против setup'а) ===")
    anti = df[((df["dir"] == "LONG") & (df["r_norm"] < 0)) |
              ((df["dir"] == "SHORT") & (df["r_norm"] > 0))]
    s = stats(anti, "anti")
    print(f"  n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/trade={s['R/trade']:+.3f}  Δprec={s['WR%']-base_wr:+.2f}pp  Δn={s['n']-len(closed):+}")

    print(f"\n=== По квартилям r_norm (direction-signed) ===")
    df["r_signed"] = df.apply(lambda r: r["r_norm"] if r["dir"] == "LONG" else -r["r_norm"], axis=1)
    closed_2 = df[df["outcome"].isin(["win", "loss"])].copy()
    closed_2["bucket"] = pd.qcut(closed_2["r_signed"], q=4,
                                  labels=["Q1 (low/anti)", "Q2", "Q3", "Q4 (high/direct)"])
    print(f"{'bucket':>18} {'n':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7}  {'range':>22}")
    for b in closed_2["bucket"].cat.categories:
        sub = closed_2[closed_2["bucket"] == b]
        w = int((sub["outcome"] == "win").sum()); l = len(sub) - w; n = w+l
        wr = w/n*100 if n else 0; r = w*RR-l
        rng = f"{sub['r_signed'].min():+.3f} .. {sub['r_signed'].max():+.3f}"
        print(f"{b!s:>18} {n:>4} {wr:>6.2f} {r:>+8.2f} {(r/n if n else 0):>+7.3f}  {rng:>22}")

    print(f"\n=== Threshold пороги |r_signed| ===")
    print(f"{'thresh':>10} {'side':>7} {'n':>4} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7}  {'Δprec':>7}")
    for th in (0.0, 0.1, 0.2, 0.3, 0.5):
        for side, mask in [("direct≥", closed_2["r_signed"] >= th),
                            ("anti≤", closed_2["r_signed"] <= -th)]:
            sub = closed_2[mask]
            w = int((sub["outcome"] == "win").sum()); l = len(sub) - w; n = w+l
            wr = w/n*100 if n else 0; r = w*RR-l
            print(f"{th:>+10.2f} {side:>7} {n:>4} {w:>4} {l:>4} {wr:>6.2f} {r:>+8.2f} {(r/n if n else 0):>+7.3f}  {wr-base_wr:>+7.2f}")

    out = ROOT / "signals" / "irdrb_evot_filter.csv"
    df.to_csv(out, index=False)
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
