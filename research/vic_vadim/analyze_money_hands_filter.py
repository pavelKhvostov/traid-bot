"""Money Hands ASVK (bw2 + SMA + MF на HA) как direction-filter для
i-RDRB+FVG zone-mitigation стратегии (BTC 1h, 6y, RR=1.4).

5 форм проверки (как в C3-исследовании ViC Vadim):
  A1 (узкая)   LONG=🟢 (bw2>0 AND bw2>=SMA)  / SHORT=🔴 (bw2<0 AND bw2<=SMA)
  A2 (широкая) LONG=bw2>SMA                  / SHORT=bw2<SMA
  A3 (затух.)  LONG=⚪after🟢 (bw2>0 AND <SMA)/ SHORT=⚪after🔴 (bw2<0 AND >SMA)
  B  (экстр.)  LONG=bw2≤-60                  / SHORT=bw2≥+60
  C  (MF знак) LONG=MF>0                     / SHORT=MF<0

Direct: setup_dir matches form_dir. Считаем для каждой ТФ × формы.

ТФ Hull: {1h, 2h, 4h, 6h, 12h, 1d}. Свеча проверки — последняя закрытая ≤ close FVG.c2.
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
from research.money_hands.plot_money_hands import (
    wavetrend_blueWaves, sma, heikin_ashi, money_flow,
)

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2020-05-15", tz="UTC")
TFS = [("1h", "1h"), ("2h", "2h"), ("4h", "4h"), ("6h", "6h"),
       ("12h", "12h"), ("1d", "1D")]
BW2_SMA_LEN = 14
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m, freq):
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def compute_mh(df_tf):
    """Возвращает bw2, bw2_sma, mf — numpy массивы."""
    hlc3 = (df_tf["high"] + df_tf["low"] + df_tf["close"]) / 3
    _, bw2, _ = wavetrend_blueWaves(hlc3)
    bw2_sma = sma(bw2, BW2_SMA_LEN)
    ha_o, ha_h, ha_l, ha_c = heikin_ashi(df_tf["open"], df_tf["high"], df_tf["low"], df_tf["close"])
    mf = money_flow(ha_o, ha_h, ha_l, ha_c)
    return bw2.to_numpy(), bw2_sma.to_numpy(), mf.to_numpy()


def get_state_at(df_tf, bw2, bw2_sma, mf, t: pd.Timestamp):
    """Возвращает dict с булевыми флагами всех форм для последнего ≤ t бара."""
    i = int(df_tf.index.searchsorted(t, side="right")) - 1
    if i < BW2_SMA_LEN + 5: return None
    b = bw2[i]; s = bw2_sma[i]; m = mf[i]
    if np.isnan(b) or np.isnan(s) or np.isnan(m): return None
    return {
        "A1_long":  (b > 0) and (b >= s),
        "A1_short": (b < 0) and (b <= s),
        "A2_long":  b > s,
        "A2_short": b < s,
        "A3_long":  (b > 0) and (b < s),
        "A3_short": (b < 0) and (b > s),
        "B_long":   b <= -60,
        "B_short":  b >= 60,
        "C_long":   m > 0,
        "C_short":  m < 0,
    }


def scan_with_mh(df_1h, df_1m, mh_tfs):
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
        states = {}
        for tf_label, (df_tf, bw2, bw2_sma, mf) in mh_tfs.items():
            states[tf_label] = get_state_at(df_tf, bw2, bw2_sma, mf, signal_time)

        # Симуляция (как раньше)
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
                    sl_mask = post2_lo <= sl; tp_mask = post2_hi >= tp
                else:
                    sl_mask = post2_hi >= sl; tp_mask = post2_lo <= tp
                sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
                tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
                if sl_first == -1 and tp_first == -1: outcome = "open"
                elif sl_first == -1: outcome = "win"
                elif tp_first == -1: outcome = "loss"
                else: outcome = "win" if tp_first < sl_first else "loss"
        rows.append({"dir": i_dir, "outcome": outcome, "states": states})
    return rows


def stats_filtered(rows, mask_fn, baseline_wr):
    sub = [r for r in rows if mask_fn(r) and r["outcome"] in ("win", "loss")]
    w = sum(1 for r in sub if r["outcome"] == "win")
    l = len(sub) - w
    n = w + l
    wr = w / n * 100 if n else 0
    r = w * RR - l
    return {"n": n, "W": w, "L": l, "WR%": wr,
            "ΣR": r, "R/trade": r / n if n else 0,
            "Δprec": wr - baseline_wr}


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    df_1h = resample(df_1m, "1h")
    print(f"  1h-bars: {len(df_1h):,}", flush=True)

    mh_tfs = {}
    for tf_label, freq in TFS:
        print(f"  MH on {tf_label}...", flush=True)
        df_tf = resample(df_1m, freq)
        bw2, bw2_sma, mf = compute_mh(df_tf)
        mh_tfs[tf_label] = (df_tf, bw2, bw2_sma, mf)

    print("scanning setups...", flush=True)
    rows = scan_with_mh(df_1h, df_1m, mh_tfs)
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    w0 = sum(1 for r in closed if r["outcome"] == "win"); l0 = len(closed) - w0
    base_wr = w0 / len(closed) * 100

    print(f"\n=== Baseline ===")
    print(f"  n={len(closed)}  W={w0} L={l0}  WR={base_wr:.2f}%  ΣR={w0*RR-l0:+.2f}  R/trade={(w0*RR-l0)/len(closed):+.3f}")

    forms = [("A1", "узкая 🟢/🔴"), ("A2", "широкая bw2><SMA"),
             ("A3", "затухание"), ("B", "extremum ±60"), ("C", "MF знак")]

    for form_id, form_desc in forms:
        print(f"\n=== {form_id} ({form_desc}) — direct match ===")
        print(f"{'TF':>4}  {'n':>4} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7}  {'Δn':>5} {'Δprec':>7}")
        for tf_label in mh_tfs.keys():
            def mask_fn(r, t=tf_label, fid=form_id):
                st = r["states"].get(t)
                if st is None: return False
                key = f"{fid}_{'long' if r['dir']=='LONG' else 'short'}"
                return bool(st[key])
            s = stats_filtered(rows, mask_fn, base_wr)
            dn = s["n"] - len(closed)
            print(f"{tf_label:>4}  {s['n']:>4} {s['W']:>4} {s['L']:>4} {s['WR%']:>6.2f} "
                  f"{s['ΣR']:>+8.2f} {s['R/trade']:>+7.3f}  {dn:>+5} {s['Δprec']:>+7.2f}")


if __name__ == "__main__":
    main()
