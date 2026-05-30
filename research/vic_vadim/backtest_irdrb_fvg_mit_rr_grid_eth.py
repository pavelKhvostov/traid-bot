"""Grid RR ∈ [1.0..3.0 step 0.1] для i-RDRB+FVG+mitigation entry.

Entry=0.9, SL=0.2 (фикс, доли ширины зоны).
TP = entry + RR · risk (LONG) / entry − RR · risk (SHORT)
Без таймстопа после fill.
BTC, 2023-01-01 → present, ТФ ∈ {1h, 2h}.
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
TFS = [("1h", "1h", 60)]

ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR_GRID = [round(x, 1) for x in np.arange(1.0, 3.01, 0.1)]


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def precompute(df_tf, df_1m, tf_min):
    """Для каждого setup'а возвращает (direction, entry, sl, risk, post_lo, post_hi)
    где post_* — массивы 1m баров от mit_time (включительно)."""
    n = len(df_tf)
    highs = df_tf["high"].to_numpy(); lows = df_tf["low"].to_numpy()
    closes = df_tf["close"].to_numpy()
    idx = df_tf.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index
    out = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_tf, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_tf, k + 2)
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
        else:
            entry = zone_t - ENTRY_FRAC * width
            sl = zone_t - SL_FRAC * width
            risk = sl - entry
        start_time = idx[k + 2] + pd.Timedelta(minutes=tf_min)
        sp = int(idx1.searchsorted(start_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0: continue
        mit_idx = sp + int(mit_hits[0])
        out.append({"dir": i_dir, "entry": entry, "sl": sl, "risk": risk,
                    "post_lo": lo1[mit_idx:], "post_hi": hi1[mit_idx:]})
    return out


def sim_one(s, rr):
    direction, entry, sl, risk = s["dir"], s["entry"], s["sl"], s["risk"]
    post_lo, post_hi = s["post_lo"], s["post_hi"]
    if direction == "LONG":
        tp = entry + rr * risk
        entry_idxs = np.where(post_lo <= entry)[0]
        tp_idxs = np.where(post_hi >= tp)[0]
    else:
        tp = entry - rr * risk
        entry_idxs = np.where(post_hi >= entry)[0]
        tp_idxs = np.where(post_lo <= tp)[0]
    m = len(post_lo)
    e_idx = int(entry_idxs[0]) if entry_idxs.size else m + 1
    tp_pre = int(tp_idxs[0]) if tp_idxs.size else m + 1
    if tp_pre < e_idx:
        return "no_entry"
    if e_idx >= m:
        return "not_filled"
    post2_lo = post_lo[e_idx:]; post2_hi = post_hi[e_idx:]
    if direction == "LONG":
        sl_mask = post2_lo <= sl; tp_mask = post2_hi >= tp
    else:
        sl_mask = post2_hi >= sl; tp_mask = post2_lo <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]

    by_tf = {}
    for label, freq, tf_min in TFS:
        df_tf = resample(df_1m, freq)
        print(f"  precompute {label}...", flush=True)
        by_tf[label] = precompute(df_tf, df_1m, tf_min)

    print(f"\n{'TF':>3} {'RR':>4}  {'tot':>4} {'noE':>4} {'open':>4}  {'closed':>6} {'WR%':>5} {'ΣR':>8}  "
          f"{'L_WR%':>6} {'L_R':>8}  {'S_WR%':>6} {'S_R':>8}")
    for label, _, _ in TFS:
        for rr in RR_GRID:
            setups = by_tf[label]
            rows = [(s["dir"], sim_one(s, rr)) for s in setups]
            total = len(rows)
            ne = sum(1 for _, o in rows if o == "no_entry")
            op = sum(1 for _, o in rows if o == "open")
            wins = sum(1 for _, o in rows if o == "win")
            losses = sum(1 for _, o in rows if o == "loss")
            closed = wins + losses
            wr = wins/closed*100 if closed else 0
            sum_r = wins*rr - losses
            L = [r for r in rows if r[0] == "LONG"]
            S = [r for r in rows if r[0] == "SHORT"]
            Lw = sum(1 for _, o in L if o == "win"); Ll = sum(1 for _, o in L if o == "loss")
            Sw = sum(1 for _, o in S if o == "win"); Sl = sum(1 for _, o in S if o == "loss")
            L_wr = Lw/(Lw+Ll)*100 if (Lw+Ll) else 0
            S_wr = Sw/(Sw+Sl)*100 if (Sw+Sl) else 0
            L_r = Lw*rr - Ll
            S_r = Sw*rr - Sl
            print(f"{label:>3} {rr:>4.1f}  {total:>4} {ne:>4} {op:>4}  {closed:>6} {wr:>5.1f} {sum_r:>+7.2f}  "
                  f"{L_wr:>6.1f} {L_r:>+7.2f}  {S_wr:>6.1f} {S_r:>+7.2f}")
        print()


if __name__ == "__main__":
    main()
