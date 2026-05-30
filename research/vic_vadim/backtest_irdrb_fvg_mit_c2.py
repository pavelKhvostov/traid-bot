"""i-RDRB + FVG + Mitigation + C2-filter.

C2: одна из свечей (i-2, i-1, i) setup'а (anchor/mid/trigger V1 RDRB) на 1h
должна swept одну из HTF-зон ликвидности или неэффективности
(FH/FL фракталы ∪ LONG/SHORT FVG) на ТФ {12h, 1d, 2d, 3d, W=пн-пн}.

Sweep-семантика (как в maxV Vadim Core):
- SHORT-side (для SHORT i-RDRB):
    high(1h_candle) > level AND close(1h_candle) < level
    level = FH.level или SHORT_FVG.top
- LONG-side  (для LONG i-RDRB):
    low(1h_candle)  < level AND close(1h_candle) > level
    level = FL.level или LONG_FVG.bottom

BTC, 2020-05-15 → present.
Execution: entry=0.9, SL=0.2, RR=1.4, без таймстопа, mitigation-trigger.
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
HTF_LIST = [("12h", "12h"), ("1d", "1D"), ("2d", "2D"), ("3d", "3D"), ("W", "7D")]
WEEKLY_ANCHOR = pd.Timestamp("1970-01-05", tz="UTC")  # Mon-anchor (TV-standard)

ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4
TF_MIN_BASE = 60  # 1h


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def compose_htf(df_1m, freq):
    origin = WEEKLY_ANCHOR if freq == "7D" else "epoch"
    return df_1m.resample(freq, origin=origin, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def find_fractals(df_tf, freq) -> tuple[list, list]:
    """5-bar pivot. Returns ([FH levels with ready_time], [FL levels])."""
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    fh, fl = [], []
    for i in range(2, len(df_tf) - 2):
        if h[i] > h[i - 2] and h[i] > h[i - 1] and h[i] > h[i + 1] and h[i] > h[i + 2]:
            fh.append((float(h[i]), idx[i + 2] + tf_dur))
        if l[i] < l[i - 2] and l[i] < l[i - 1] and l[i] < l[i + 1] and l[i] < l[i + 2]:
            fl.append((float(l[i]), idx[i + 2] + tf_dur))
    return fh, fl


def find_fvg_zones(df_tf, freq) -> tuple[list, list]:
    """LONG FVG (high(c0) < low(c2)) и SHORT FVG (low(c0) > high(c2)).
    Returns ([LONG: (bottom, top, ready_time)], [SHORT: ...])."""
    long_fvg, short_fvg = [], []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(2, len(df_tf)):
        if h[k - 2] < l[k]:
            long_fvg.append((float(h[k - 2]), float(l[k]), idx[k] + tf_dur))
        if l[k - 2] > h[k]:
            short_fvg.append((float(h[k]), float(l[k - 2]), idx[k] + tf_dur))
    return long_fvg, short_fvg


def collect_levels(df_1m):
    """Собирает все HTF-зоны для C2-проверки.
    Returns:
      fh_arr, fl_arr — массивы (level, ready_ns) для FH / FL
      long_fvg_arr  — массив (bottom, ready_ns) — ближняя граница LONG FVG
      short_fvg_arr — массив (top, ready_ns)    — ближняя граница SHORT FVG
    """
    all_fh, all_fl, all_long, all_short = [], [], [], []
    for tf_label, freq in HTF_LIST:
        df_tf = compose_htf(df_1m, freq)
        fh, fl = find_fractals(df_tf, freq)
        lfvg, sfvg = find_fvg_zones(df_tf, freq)
        all_fh.extend(fh)
        all_fl.extend(fl)
        all_long.extend([(b, r) for b, t, r in lfvg])    # ближняя к рынку для LONG = bottom
        all_short.extend([(t, r) for b, t, r in sfvg])   # ближняя для SHORT = top
    def to_arr(rows):
        if not rows:
            return np.array([]), np.array([])
        a = np.array([r[0] for r in rows], dtype=np.float64)
        t = np.array([pd.Timestamp(r[1]).value for r in rows], dtype=np.int64)
        return a, t
    return to_arr(all_fh), to_arr(all_fl), to_arr(all_long), to_arr(all_short)


def has_sweep_short(candle_h, candle_c, candle_open_ns, fh_arr, sfvg_arr):
    """SHORT-side sweep: high > level AND close < level, ready_time ≤ candle_open."""
    for arr_v, arr_t in (fh_arr, sfvg_arr):
        if arr_v.size == 0: continue
        mask_ready = arr_t <= candle_open_ns
        if not mask_ready.any(): continue
        levels = arr_v[mask_ready]
        if ((candle_h > levels) & (candle_c < levels)).any():
            return True
    return False


def has_sweep_long(candle_l, candle_c, candle_open_ns, fl_arr, lfvg_arr):
    """LONG-side sweep: low < level AND close > level."""
    for arr_v, arr_t in (fl_arr, lfvg_arr):
        if arr_v.size == 0: continue
        mask_ready = arr_t <= candle_open_ns
        if not mask_ready.any(): continue
        levels = arr_v[mask_ready]
        if ((candle_l < levels) & (candle_c > levels)).any():
            return True
    return False


def scan_1h_c2(df_1h, df_1m, fh_arr, fl_arr, lfvg_arr, sfvg_arr):
    n = len(df_1h)
    highs = df_1h["high"].to_numpy()
    lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    opens_ns = df_1h.index.values.astype("datetime64[ns]").astype(np.int64)
    idx = df_1h.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index

    raw_setups = 0
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
        raw_setups += 1

        # C2: проверка sweep одной из свечей k-2 / k-1 / k
        c2_passed = False
        for ci in (k - 2, k - 1, k):
            ch, cl, cc, co = highs[ci], lows[ci], closes[ci], opens_ns[ci]
            if i_dir == "SHORT":
                if has_sweep_short(ch, cc, co, fh_arr, sfvg_arr):
                    c2_passed = True; break
            else:
                if has_sweep_long(cl, cc, co, fl_arr, lfvg_arr):
                    c2_passed = True; break
        if not c2_passed:
            continue

        # Зона интереса (i-RDRB+FVG)
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

        start_time = idx[k + 2] + pd.Timedelta(minutes=TF_MIN_BASE)
        sp = int(idx1.searchsorted(start_time, side="left"))
        if sp >= len(idx1):
            rows.append({"dir": i_dir, "outcome": "no_data"}); continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mitigation"}); continue
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
            sl_mask = post2_lo <= sl; tp_mask = post2_hi >= tp
        else:
            sl_mask = post2_hi >= sl; tp_mask = post2_lo <= tp
        sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
        tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
        if sl_first == -1 and tp_first == -1:
            outcome = "open"
        elif sl_first == -1:
            outcome = "win"
        elif tp_first == -1:
            outcome = "loss"
        else:
            outcome = "win" if tp_first < sl_first else "loss"
        rows.append({"dir": i_dir, "outcome": outcome,
                     "i_time": idx[k - 2], "fvg_c2_time": idx[k + 2]})

    return raw_setups, pd.DataFrame(rows)


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    print(f"  bars: {len(df_1m):,}", flush=True)

    print("composing 1h + HTF zones (12h, 1d, 2d, 3d, W)...", flush=True)
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    fh_arr, fl_arr, lfvg_arr, sfvg_arr = collect_levels(df_1m)
    print(f"  FH levels: {fh_arr[0].size}  FL: {fl_arr[0].size}  "
          f"LONG FVG: {lfvg_arr[0].size}  SHORT FVG: {sfvg_arr[0].size}", flush=True)

    print("scanning setups + C2 + execution...", flush=True)
    raw, df = scan_1h_c2(df_1h, df_1m, fh_arr, fl_arr, lfvg_arr, sfvg_arr)
    out = ROOT / "signals" / "irdrb_fvg_mit_c2_1h.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"  saved: {out}", flush=True)

    total_c2 = len(df)
    win = int((df["outcome"] == "win").sum())
    loss = int((df["outcome"] == "loss").sum())
    no_mit = int((df["outcome"] == "no_mitigation").sum())
    ne = int((df["outcome"] == "no_entry").sum())
    nf = int((df["outcome"] == "not_filled").sum())
    op = int((df["outcome"] == "open").sum())
    closed = win + loss
    wr = win / closed * 100 if closed else 0
    sum_r = win * RR - loss

    print(f"\n=== Σ summary ===")
    print(f"  raw setups (без C2): {raw}")
    print(f"  C2 passed:           {total_c2}  ({total_c2/raw*100:.1f}% от raw)")
    print(f"  no_mit={no_mit}  no_entry={ne}  not_filled={nf}  open={op}")
    print(f"  closed={closed}  WR={wr:.1f}%  ΣR={sum_r:+.2f}")
    for d in ("LONG", "SHORT"):
        sub = df[df["dir"] == d]
        w = int((sub["outcome"] == "win").sum())
        l = int((sub["outcome"] == "loss").sum())
        cl = w + l
        wr_d = w / cl * 100 if cl else 0
        r = w * RR - l
        print(f"  {d:>5}: n={len(sub)} W={w} L={l} WR={wr_d:.1f}% ΣR={r:+.2f}")


if __name__ == "__main__":
    main()
