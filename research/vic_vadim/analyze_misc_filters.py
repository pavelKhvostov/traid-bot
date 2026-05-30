"""Комплексный анализ нескольких C2-фильтров на i-RDRB+FVG mit setup'е.

Метрики:
  A. Setup-internal:
     - body_pct_c4   = |close-open| / (high-low) свечи #4 (inversion)
     - v1_break_pct  = (close(#4) - zone_V1_far) / V1_width (для LONG: close-top)
     - zone_width_pct = (zone_top - zone_bottom) / entry × 100
     - v1_to_zone_ratio = V1_width / zone_width
  B. Mitigation:
     - mit_depth_pct = (zone_top - mit_bar.low) / zone_width (LONG; SHORT зеркально)
     - mit_wick_reaction = размер rejection wick первой 1m свечи в зоне
  C. Time:
     - hour_of_day (UTC) и day_of_week
  D. Cluster:
     - bars_since_last_same_dir_setup (на 1h)

Для каждой — quantile split (4 квартиля). BTC+ETH 1h, 6y, RR=1.4.
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
]
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def scan(df_1h, df_1m):
    n = len(df_1h)
    o = df_1h["open"].to_numpy()
    h = df_1h["high"].to_numpy()
    l = df_1h["low"].to_numpy()
    c = df_1h["close"].to_numpy()
    idx_1h = df_1h.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    op1 = df_1m["open"].to_numpy(); cl1 = df_1m["close"].to_numpy()
    idx1 = df_1m.index

    rows = []
    last_long_k = -10000
    last_short_k = -10000
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_1h, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = c[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_1h, k + 2)
        if fvg is None or fvg.direction != i_dir: continue

        # Geometry
        if i_dir == "LONG":
            zone_b = float(min(l[k - 2], l[k - 1], l[k], l[k + 1]))
            zone_t = float(l[k + 2])
        else:
            zone_t = float(max(h[k - 2], h[k - 1], h[k], h[k + 1]))
            zone_b = float(h[k + 2])
        if zone_t <= zone_b: continue
        zone_width = zone_t - zone_b
        if i_dir == "LONG":
            entry = zone_b + ENTRY_FRAC * zone_width
            sl = zone_b + SL_FRAC * zone_width
            tp = entry + RR * (entry - sl)
        else:
            entry = zone_t - ENTRY_FRAC * zone_width
            sl = zone_t - SL_FRAC * zone_width
            tp = entry - RR * (sl - entry)

        # A. Setup-internal features
        c4_h = h[k + 1]; c4_l = l[k + 1]; c4_o = o[k + 1]
        c4_range = c4_h - c4_l
        body_pct_c4 = abs(c4_close - c4_o) / c4_range if c4_range > 0 else 0
        v1_width = rdrb.top - rdrb.bottom
        if i_dir == "LONG":
            v1_break_pct = (c4_close - rdrb.top) / v1_width if v1_width > 0 else 0
        else:
            v1_break_pct = (rdrb.bottom - c4_close) / v1_width if v1_width > 0 else 0
        zone_width_pct = zone_width / entry * 100
        v1_to_zone = v1_width / zone_width if zone_width > 0 else 0

        # D. Cluster (bars since last same-dir setup)
        if i_dir == "LONG":
            bars_since = k - last_long_k
        else:
            bars_since = k - last_short_k

        # C. Time
        signal_time = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        hour = signal_time.hour
        dow = signal_time.dayofweek

        # Execution + mitigation
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1):
            if i_dir == "LONG": last_long_k = k
            else: last_short_k = k
            continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            outcome = "no_mit"
            mit_depth_pct = np.nan; wick_reaction = np.nan
        else:
            mit_idx = sp + int(mit_hits[0])
            # B. Mitigation depth & wick reaction
            mit_lo = lo1[mit_idx]; mit_hi = hi1[mit_idx]
            mit_op = op1[mit_idx]; mit_cl = cl1[mit_idx]
            if i_dir == "LONG":
                mit_depth_pct = (zone_t - mit_lo) / zone_width
                # rejection wick (LONG): low away from close ↑
                bar_range = mit_hi - mit_lo
                wick_lower = (mit_cl - mit_lo) / bar_range if bar_range > 0 else 0
                wick_reaction = wick_lower  # для LONG: лучше большой нижний хвост (отскок)
            else:
                mit_depth_pct = (mit_hi - zone_b) / zone_width
                bar_range = mit_hi - mit_lo
                wick_upper = (mit_hi - mit_cl) / bar_range if bar_range > 0 else 0
                wick_reaction = wick_upper

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
                     "body_pct_c4": body_pct_c4, "v1_break_pct": v1_break_pct,
                     "zone_width_pct": zone_width_pct, "v1_to_zone": v1_to_zone,
                     "mit_depth_pct": mit_depth_pct, "wick_reaction": wick_reaction,
                     "hour": hour, "dow": dow, "bars_since_same_dir": bars_since})
        if i_dir == "LONG": last_long_k = k
        else: last_short_k = k
    return pd.DataFrame(rows)


def quantile_stats(df, col, n_q=4):
    closed = df[df["outcome"].isin(["win", "loss"])].dropna(subset=[col]).copy()
    if len(closed) < n_q * 4:
        return None
    closed["bucket"] = pd.qcut(closed[col], q=n_q, labels=False, duplicates="drop")
    out = []
    for b in sorted(closed["bucket"].unique()):
        sub = closed[closed["bucket"] == b]
        w = int((sub["outcome"] == "win").sum())
        l = int((sub["outcome"] == "loss").sum())
        n = w + l
        wr = w/n*100 if n else 0
        r = w*RR - l
        out.append({"q": b, "n": n, "WR%": wr, "ΣR": r, "R/tr": r/n if n else 0,
                    "range": f"{sub[col].min():.4f}..{sub[col].max():.4f}"})
    return out


def main():
    print("loading + scanning...", flush=True)
    parts = []
    for asset, path in ASSETS:
        print(f"  {asset}...", flush=True)
        df_1m = load_1m(path)
        df_1m = df_1m[df_1m.index >= START]
        df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
            "open":"first","high":"max","low":"min","close":"last","volume":"sum"
        }).dropna(subset=["close"])
        df = scan(df_1h, df_1m)
        df["asset"] = asset
        parts.append(df)
    df_all = pd.concat(parts, ignore_index=True)

    closed = df_all[df_all["outcome"].isin(["win", "loss"])]
    w0 = int((closed["outcome"] == "win").sum()); l0 = len(closed) - w0
    base_wr = w0/len(closed)*100
    print(f"\nBaseline Σ: n={len(closed)} W={w0} L={l0} WR={base_wr:.2f}% "
          f"ΣR={w0*RR-l0:+.2f} R/tr={(w0*RR-l0)/len(closed):+.3f}")

    features = [
        ("body_pct_c4", "Тело #4 (inversion) body/range"),
        ("v1_break_pct", "Глубина пробоя V1 свечой #4 / V1.width"),
        ("zone_width_pct", "Ширина зоны интереса в %"),
        ("v1_to_zone", "V1.width / zone.width"),
        ("mit_depth_pct", "Глубина первой митигации (1m bar) / zone.width"),
        ("wick_reaction", "Rejection wick первого 1m бара митигации (%/range)"),
        ("bars_since_same_dir", "Bars since last setup того же направления"),
    ]
    for col, desc in features:
        print(f"\n=== {desc}  [{col}] ===")
        res = quantile_stats(df_all, col, n_q=4)
        if res is None:
            print("  (n too small for split)"); continue
        print(f"  {'q':>2} {'n':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7} {'Δprec':>7}  {'range':>30}")
        for r in res:
            d = r['WR%'] - base_wr
            print(f"  {r['q']:>2} {r['n']:>4} {r['WR%']:>6.2f} {r['ΣR']:>+8.2f} "
                  f"{r['R/tr']:>+7.3f} {d:>+7.2f}  {r['range']:>30}")

    # Hour-of-day binary buckets
    print(f"\n=== Hour-of-day (UTC), buckets по 6 часов ===")
    closed2 = df_all[df_all["outcome"].isin(["win", "loss"])].copy()
    closed2["hour_bucket"] = (closed2["hour"] // 6) * 6
    print(f"  {'hour':>6} {'n':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7} {'Δprec':>7}")
    for b in sorted(closed2["hour_bucket"].unique()):
        sub = closed2[closed2["hour_bucket"] == b]
        w = int((sub["outcome"] == "win").sum())
        l = int((sub["outcome"] == "loss").sum())
        n = w + l
        wr = w/n*100 if n else 0
        r = w*RR - l
        d = wr - base_wr
        print(f"  {b:>2}-{b+5:>2} {n:>4} {wr:>6.2f} {r:>+8.2f} {(r/n if n else 0):>+7.3f} {d:>+7.2f}")

    # Day of week
    print(f"\n=== Day of Week (0=Mon, 6=Sun) ===")
    print(f"  {'dow':>3} {'n':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7} {'Δprec':>7}")
    for d_ in range(7):
        sub = closed2[closed2["dow"] == d_]
        w = int((sub["outcome"] == "win").sum())
        l = int((sub["outcome"] == "loss").sum())
        n = w + l
        wr = w/n*100 if n else 0
        r = w*RR - l
        dprec = wr - base_wr
        names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        print(f"  {names[d_]:>3} {n:>4} {wr:>6.2f} {r:>+8.2f} {(r/n if n else 0):>+7.3f} {dprec:>+7.2f}")


if __name__ == "__main__":
    main()
