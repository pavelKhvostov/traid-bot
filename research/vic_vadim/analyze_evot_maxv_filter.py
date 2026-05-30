"""EVoT maxV (winner кластер: bull или bear) как защитный уровень для
i-RDRB+FVG mitigation стратегии.

Гипотеза (из примера 2026-05-19): maxV в окне setup'а #1..#5,
расположенный по правильную сторону от SL, играет роль скрытой
поддержки/сопротивления. Если SL стоит за уровнем absorption,
вероятность срабатывания SL ниже.

Direction-aware проверки:
  LONG:  maxV > SL — защитный кластер выше стопа (absorption удерживает цену)
  SHORT: maxV < SL — защитный кластер ниже стопа

Также проверяется положение maxV относительно zone и entry.

BTC 1h, 6 лет, RR=1.4. Диапазон EVoT: 5 свечей #1..#5 = [open(k-2), close(k+2)].
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

        # EVoT maxV winner на диапазоне FVG-тройки = #3..#5 = (k, k+1, k+2)
        rng_start = idx_1h[k]
        rng_end = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        sp1 = int(idx1.searchsorted(rng_start, side="left"))
        ep1 = int(idx1.searchsorted(rng_end, side="left"))
        if ep1 <= sp1: continue
        seg_o = o1[sp1:ep1]; seg_c = c1[sp1:ep1]; seg_v = v1[sp1:ep1]
        bull_mask = seg_c > seg_o
        bear_mask = seg_c < seg_o
        if bull_mask.any():
            ix = np.argmax(np.where(bull_mask, seg_v, 0))
            max_bull_vol = float(seg_v[ix]); max_bull_price = float(seg_c[ix])
        else:
            max_bull_vol = 0.0; max_bull_price = np.nan
        if bear_mask.any():
            ix = np.argmax(np.where(bear_mask, seg_v, 0))
            max_bear_vol = float(seg_v[ix]); max_bear_price = float(seg_c[ix])
        else:
            max_bear_vol = 0.0; max_bear_price = np.nan
        if max_bull_vol >= max_bear_vol:
            maxv_price = max_bull_price; maxv_side = "BULL"
        else:
            maxv_price = max_bear_price; maxv_side = "BEAR"

        # Симуляция
        signal_time = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0: outcome = "no_mit"
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

        # Where is maxV relative to entry/SL?
        if i_dir == "LONG":
            above_sl = maxv_price > sl
            above_entry = maxv_price > entry
            in_zone = (zone_b <= maxv_price <= zone_t)
        else:
            above_sl = maxv_price < sl
            above_entry = maxv_price < entry
            in_zone = (zone_b <= maxv_price <= zone_t)
        rows.append({"dir": i_dir, "outcome": outcome,
                     "maxv": maxv_price, "maxv_side": maxv_side,
                     "above_sl": above_sl, "above_entry": above_entry,
                     "in_zone": in_zone, "sl": sl, "entry": entry,
                     "zone_b": zone_b, "zone_t": zone_t})
    return pd.DataFrame(rows)


def stats(sub, label, baseline_wr):
    sub = sub[sub["outcome"].isin(["win", "loss"])]
    w = int((sub["outcome"] == "win").sum()); l = len(sub) - w; n = w + l
    wr = w / n * 100 if n else 0
    r = w * RR - l
    return {"label": label, "n": n, "W": w, "L": l, "WR%": wr,
            "ΣR": r, "R/tr": r / n if n else 0, "Δprec": wr - baseline_wr}


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])

    print("scanning + EVoT maxV...", flush=True)
    df = scan(df_1h, df_1m)
    closed = df[df["outcome"].isin(["win", "loss"])]
    w0 = int((closed["outcome"] == "win").sum()); l0 = len(closed) - w0
    base_wr = w0 / len(closed) * 100
    print(f"\nBaseline: n={len(closed)} W={w0} L={l0} WR={base_wr:.2f}% ΣR={w0*RR-l0:+.2f} R/tr={(w0*RR-l0)/len(closed):+.3f}")

    print(f"\n=== Filter: maxV в защитной зоне (LONG: maxV > SL, SHORT: maxV < SL) ===")
    s = stats(df[df["above_sl"] == True], "maxV защищает SL", base_wr)
    print(f"  n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")
    s = stats(df[df["above_sl"] == False], "maxV против", base_wr)
    print(f"  anti: n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")

    print(f"\n=== Filter: maxV выше/ниже entry ===")
    s = stats(df[df["above_entry"] == True], "maxV сверх entry", base_wr)
    print(f"  above entry: n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")
    s = stats(df[df["above_entry"] == False], "maxV ниже entry", base_wr)
    print(f"  ниже entry: n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")

    print(f"\n=== Filter: maxV в зоне интереса [zone_b, zone_t] ===")
    s = stats(df[df["in_zone"] == True], "maxV в зоне", base_wr)
    print(f"  в зоне: n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")
    s = stats(df[df["in_zone"] == False], "maxV вне зоны", base_wr)
    print(f"  вне зоны: n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")

    print(f"\n=== По стороне winner'а maxV ===")
    s = stats(df[df["maxv_side"] == "BULL"], "BULL winner", base_wr)
    print(f"  BULL winner: n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")
    s = stats(df[df["maxv_side"] == "BEAR"], "BEAR winner", base_wr)
    print(f"  BEAR winner: n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")

    # Confluence with direction
    print(f"\n=== Direction-aware: winner совпадает с направлением setup'а ===")
    direct_winner = ((df["dir"] == "LONG") & (df["maxv_side"] == "BULL")) | \
                    ((df["dir"] == "SHORT") & (df["maxv_side"] == "BEAR"))
    s = stats(df[direct_winner], "winner = direction (impulse)", base_wr)
    print(f"  direct: n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")
    s = stats(df[~direct_winner], "winner противоп. (absorption)", base_wr)
    print(f"  anti  : n={s['n']} W={s['W']} L={s['L']} WR={s['WR%']:.2f}% ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}  Δprec={s['Δprec']:+.2f}pp")

    out = ROOT / "signals" / "irdrb_evot_maxv_filter.csv"
    df.to_csv(out, index=False)
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
