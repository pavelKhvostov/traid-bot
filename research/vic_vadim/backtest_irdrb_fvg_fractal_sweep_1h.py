"""C2: одна из свечей setup'а (#1, #2 или #3) sweep-нула фрактал 1h ТФ
того же направления что i-RDRB.

5-bar fractal на 1h: pivot center c2-back required, ready_time = (i+2)+1h.
Sweep semantics:
  LONG (i-RDRB LONG → expected up):  low(candle) < FL_level AND close > FL_level
  SHORT (i-RDRB SHORT → expected dn): high(candle) > FH_level AND close < FH_level

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


def find_fractals_1h(df_1h):
    """5-bar pivots. Возвращает (FH_levels_array, FH_ready_ns_array,
    FL_levels_array, FL_ready_ns_array)."""
    h = df_1h["high"].to_numpy()
    l = df_1h["low"].to_numpy()
    idx_ns = df_1h.index.values.astype("datetime64[ns]").astype(np.int64)
    one_hour_ns = 60 * 60 * 1_000_000_000
    fh_lvl, fh_t, fl_lvl, fl_t = [], [], [], []
    for i in range(2, len(df_1h) - 2):
        if h[i] > h[i - 2] and h[i] > h[i - 1] and h[i] > h[i + 1] and h[i] > h[i + 2]:
            fh_lvl.append(h[i]); fh_t.append(idx_ns[i + 2] + one_hour_ns)
        if l[i] < l[i - 2] and l[i] < l[i - 1] and l[i] < l[i + 1] and l[i] < l[i + 2]:
            fl_lvl.append(l[i]); fl_t.append(idx_ns[i + 2] + one_hour_ns)
    return (np.array(fh_lvl, dtype=np.float64), np.array(fh_t, dtype=np.int64),
            np.array(fl_lvl, dtype=np.float64), np.array(fl_t, dtype=np.int64))


def has_sweep_fl(c_low, c_close, c_open_ns, fl_lvl, fl_t):
    """LONG sweep: low < FL_level AND close > FL_level, ready_time ≤ candle open."""
    if fl_lvl.size == 0: return False
    mask = fl_t <= c_open_ns
    if not mask.any(): return False
    levels = fl_lvl[mask]
    return bool(((c_low < levels) & (c_close > levels)).any())


def has_sweep_fh(c_high, c_close, c_open_ns, fh_lvl, fh_t):
    if fh_lvl.size == 0: return False
    mask = fh_t <= c_open_ns
    if not mask.any(): return False
    levels = fh_lvl[mask]
    return bool(((c_high > levels) & (c_close < levels)).any())


def scan(df_1h, df_1m, fh_lvl, fh_t, fl_lvl, fl_t):
    n = len(df_1h)
    highs = df_1h["high"].to_numpy()
    lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    opens_ns = df_1h.index.values.astype("datetime64[ns]").astype(np.int64)
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

        # C2: проверка sweep одной из свечей #1/#2/#3 (= k-2, k-1, k)
        passed = False
        for ci in (k - 2, k - 1, k):
            if i_dir == "LONG":
                if has_sweep_fl(lows[ci], closes[ci], opens_ns[ci], fl_lvl, fl_t):
                    passed = True; break
            else:
                if has_sweep_fh(highs[ci], closes[ci], opens_ns[ci], fh_lvl, fh_t):
                    passed = True; break

        # Geometry + execution
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
            rows.append({"dir": i_dir, "outcome": "no_mit", "passed": passed}); continue
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
            rows.append({"dir": i_dir, "outcome": "no_entry", "passed": passed}); continue
        if e_idx >= m:
            rows.append({"dir": i_dir, "outcome": "not_filled", "passed": passed}); continue
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
        rows.append({"dir": i_dir, "outcome": outcome, "passed": passed})
    return pd.DataFrame(rows)


def stats(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])]
    w = int((closed["outcome"] == "win").sum())
    l = int((closed["outcome"] == "loss").sum())
    n = w + l
    wr = w/n*100 if n else 0
    r = w*RR - l
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
        print(f"  1h-bars: {len(df_1h):,}")
        fh_lvl, fh_t, fl_lvl, fl_t = find_fractals_1h(df_1h)
        print(f"  FH fractals: {fh_lvl.size}  FL fractals: {fl_lvl.size}")
        df = scan(df_1h, df_1m, fh_lvl, fh_t, fl_lvl, fl_t)
        base = stats(df, f"{asset} baseline")
        passed = stats(df[df["passed"] == True], f"{asset} sweep passed")
        anti = stats(df[df["passed"] == False], f"{asset} no sweep")
        all_rows.extend([base, passed, anti])
        for r in (base, passed, anti):
            print(f"  {r['label']:>30}: total={r['total']:>4} closed={r['closed']:>4} "
                  f"W={r['W']:>3} L={r['L']:>3} WR={r['WR']:>5.2f}% ΣR={r['ΣR']:>+7.2f} R/tr={r['R/tr']:>+6.3f}")

    print(f"\n=== Σ портфель (BTC + ETH) ===")
    for kind in ("baseline", "sweep passed", "no sweep"):
        subs = [s for s in all_rows if kind in s["label"]]
        w = sum(s["W"] for s in subs); l = sum(s["L"] for s in subs)
        n = w + l
        wr = w/n*100 if n else 0; r = w*RR - l
        print(f"  Σ {kind:>13}: closed={n:>4} W={w:>3} L={l:>3} WR={wr:>5.2f}% ΣR={r:>+7.2f} R/tr={r/n if n else 0:>+6.3f}")


if __name__ == "__main__":
    main()
