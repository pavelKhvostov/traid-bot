"""C2: ViC.D(D-1) maxV из предыдущего календарного дня попадает в защитный
коридор внутри зоны интереса.

  LONG:  ViC.D ∈ (SL, zone_top)         — выше SL, внутри зоны/около зоны
  SHORT: ViC.D ∈ (zone_bottom, SL)       — ниже SL

ViC.D = calculate_vic_d(df_1m, day, ltf_minutes=15) — Pine ASVK ViC canon.

Также проверяем альтернативное (мягкое) условие:
  LONG:  ViC.D ∈ (zone_bottom, zone_top)
  SHORT: ViC.D ∈ (zone_bottom, zone_top)

BTC + ETH 1h, 6 лет.
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
from vic_levels import calculate_vic_d

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
]
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4
VIC_LTF = 15


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def precompute_vic_d(df_1m, days):
    """Возвращает dict day(UTC normalized) → vic_d level."""
    out = {}
    for d in days:
        out[d] = calculate_vic_d(df_1m, d, ltf_minutes=VIC_LTF)
    return out


def scan(df_1h, df_1m, vic_cache):
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    idx_1h = df_1h.index
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

        signal_time = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        # ViC.D(D-1): D = текущий календарный день signal_time, D-1 = предыдущий
        day_d = signal_time.normalize()  # начало дня signal_time UTC
        day_prev = day_d - pd.Timedelta(days=1)
        vic_d = vic_cache.get(day_prev)

        # Условия
        strict_pass = False  # ViC.D в защитном коридоре
        wide_pass = False    # ViC.D в зоне интереса
        if vic_d is not None:
            if i_dir == "LONG":
                strict_pass = sl < vic_d < zone_t
                wide_pass = zone_b < vic_d < zone_t
            else:
                strict_pass = zone_b < vic_d < sl
                wide_pass = zone_b < vic_d < zone_t

        # Execution
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mit",
                         "strict": strict_pass, "wide": wide_pass}); continue
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
            rows.append({"dir": i_dir, "outcome": "no_entry",
                         "strict": strict_pass, "wide": wide_pass}); continue
        if e_idx >= m:
            rows.append({"dir": i_dir, "outcome": "not_filled",
                         "strict": strict_pass, "wide": wide_pass}); continue
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
                     "strict": strict_pass, "wide": wide_pass})
    return pd.DataFrame(rows)


def stats(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])]
    w = int((closed["outcome"] == "win").sum())
    l = int((closed["outcome"] == "loss").sum())
    n = w + l
    wr = w/n*100 if n else 0; r = w*RR - l
    return {"label": label, "total": len(df), "closed": n,
            "W": w, "L": l, "WR": wr, "ΣR": r, "R/tr": r/n if n else 0}


def main():
    all_rows = []
    for asset, path in ASSETS:
        print(f"\n=== {asset} ===", flush=True)
        df_1m = load_1m(path)
        df_1m = df_1m[df_1m.index >= START]
        df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
            "open":"first","high":"max","low":"min","close":"last","volume":"sum"
        }).dropna(subset=["close"])
        # Precompute ViC.D для каждого дня в данных
        days = pd.date_range(start=df_1m.index.min().normalize(),
                             end=df_1m.index.max().normalize(), freq="D")
        print(f"  precompute ViC.D for {len(days)} days...", flush=True)
        vic_cache = precompute_vic_d(df_1m, days)
        df = scan(df_1h, df_1m, vic_cache)
        base = stats(df, f"{asset} baseline")
        strict = stats(df[df["strict"] == True], f"{asset} STRICT (ViC.D ∈ (SL, top))")
        strict_anti = stats(df[df["strict"] == False], f"{asset} STRICT anti")
        wide = stats(df[df["wide"] == True], f"{asset} WIDE (ViC.D ∈ zone)")
        wide_anti = stats(df[df["wide"] == False], f"{asset} WIDE anti")
        all_rows.extend([base, strict, strict_anti, wide, wide_anti])
        for r in (base, strict, strict_anti, wide, wide_anti):
            print(f"  {r['label']:>45}: total={r['total']:>4} closed={r['closed']:>4} "
                  f"W={r['W']:>3} L={r['L']:>3} WR={r['WR']:>5.2f}% ΣR={r['ΣR']:>+7.2f} R/tr={r['R/tr']:>+6.3f}")

    print(f"\n=== Σ портфель ===")
    for kind in ("baseline", "STRICT (", "STRICT anti", "WIDE (", "WIDE anti"):
        subs = [s for s in all_rows if kind in s["label"]]
        w = sum(s["W"] for s in subs); l = sum(s["L"] for s in subs)
        n = w + l
        wr = w/n*100 if n else 0; r = w*RR - l
        print(f"  Σ {kind:>14}: closed={n:>4} W={w:>3} L={l:>3} WR={wr:>5.2f}% ΣR={r:>+7.2f} R/tr={r/n if n else 0:>+6.3f}")


if __name__ == "__main__":
    main()
