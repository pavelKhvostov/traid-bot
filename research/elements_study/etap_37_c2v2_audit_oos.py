"""Этап 37: lookahead audit + OOS validation для C2v2.

CRITICAL FIX: в etap_36 hull_trend_label использовал `close[idx]` где idx —
бар содержащий ts. Этот бар на момент ts ЕЩЁ ФОРМИРУЕТСЯ — его close
будет известен только в момент `ts_next_bar_open`. Pine non-repaint
`request.security(_, "1d", close)` вернул бы close ПРЕДЫДУЩЕГО закрытого
бара.

Fix:
  last_closed_idx = idx - 1   # last bar that has fully closed before ts
  c = close[last_closed_idx]
  h2 = hull[last_closed_idx - 2]   # Pine HULL[2] from last closed bar

Запускаем:
  1. C2v2 baseline (etap_36 reproduction) — на BTC, как было — ожидаем +111R RR=1.0
  2. C2v2 audited — fix lookahead — на BTC — посмотрим сколько потеряем
  3. C2v2 audited — на ETHUSDT — OOS validation #1
  4. C2v2 audited — на SOLUSDT — OOS validation #2
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

START_DATE = "2020-01-01"
SOL_START = "2020-08-11"  # SOL listed Aug 2020 на Binance
MIN_SL_PCT = 1.0
SL_BUF_ATR = 0.3
RR_TEST = [1.0, 1.5, 2.0]

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                 "2h": 3, "1h": 2, "15m": 1}

OUT_DIR = Path("research/elements_study/output")


# ---------- math ----------

def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def hull_ma(close, length=78):
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


# ---------- C2 detector ----------

class FastSim:
    def __init__(self, df_1m):
        self.ts = df_1m.index.values
        self.high = df_1m["high"].to_numpy(dtype=float)
        self.low = df_1m["low"].to_numpy(dtype=float)

    def simulate(self, direction, entry, sl, tp, start_time, timeout_days):
        end_time = start_time + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(self.ts, np.datetime64(
            start_time.tz_localize(None) if start_time.tz else start_time))
        i1 = np.searchsorted(self.ts, np.datetime64(
            end_time.tz_localize(None) if end_time.tz else end_time))
        if i1 <= i0: return ("no_data", 0.0)
        h = self.high[i0:i1]; l = self.low[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0: return ("invalid", 0.0)
        if direction == "LONG":
            act_mask = l <= entry
            if not act_mask.any(): return ("not_filled", 0.0)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0)
            if sl_idx <= tp_idx: return ("loss", -1.0)
            return ("win", (tp - entry) / risk)
        else:
            act_mask = h >= entry
            if not act_mask.any(): return ("not_filled", 0.0)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0)
            if sl_idx <= tp_idx: return ("loss", -1.0)
            return ("win", (entry - tp) / risk)


def collect_obs(df, atr_series, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"time": ob.cur_time, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": atr,
                     "tf": tf, "idx": idx})
    return out


def collect_fvgs(df, atr_series, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"time": f.c2_time, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": atr,
                     "tf": tf, "idx": idx})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def build_c2_setups(obs_6h, fvgs_2h, df_2h):
    a_tf_td = pd.Timedelta("6h")
    a_life = pd.Timedelta(days=TF_LIFE_DAYS["6h"])
    t_sorted = sorted(fvgs_2h, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                         for t in t_sorted])
    ema_arr = df_2h["ema200"].to_numpy()
    close_arr = df_2h["close"].to_numpy()
    setups = []
    for a in obs_6h:
        a_start = a["time"] + a_tf_td
        a_end = a["time"] + a_life
        if a_end <= a_start: continue
        i_start = np.searchsorted(t_times, np.datetime64(
            a_start.tz_localize(None) if a_start.tz else a_start), side="right")
        i_end = np.searchsorted(t_times, np.datetime64(
            a_end.tz_localize(None) if a_end.tz else a_end), side="right")
        for ti in range(i_start, i_end):
            t = t_sorted[ti]
            if t["direction"] != a["direction"]: continue
            if not zones_overlap(t["bottom"], t["top"], a["bottom"], a["top"]):
                continue
            em = float(ema_arr[t["idx"]]); cl = float(close_arr[t["idx"]])
            pro = ((t["direction"] == "LONG" and cl > em) or
                   (t["direction"] == "SHORT" and cl < em))
            if not pro: continue
            setups.append({"anchor_time": a["time"], "trigger_time": t["time"],
                            "direction": t["direction"],
                            "fvg_bottom": t["bottom"], "fvg_top": t["top"],
                            "fvg_atr": t["atr"], "year": t["time"].year})
            break
    return setups


def evaluate_c2(setups, sim, rr):
    rows = []
    for s in setups:
        direction = s["direction"]
        entry = (s["fvg_bottom"] + s["fvg_top"]) / 2
        atr = s["fvg_atr"]
        if direction == "LONG":
            atr_sl = s["fvg_bottom"] - SL_BUF_ATR * atr
            min_dist = entry * MIN_SL_PCT / 100
            sl = min(atr_sl, entry - min_dist)
        else:
            atr_sl = s["fvg_top"] + SL_BUF_ATR * atr
            min_dist = entry * MIN_SL_PCT / 100
            sl = max(atr_sl, entry + min_dist)
        risk = abs(entry - sl)
        if risk <= 0: continue
        tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
        start = s["trigger_time"] + pd.Timedelta("2h")
        outcome, R = sim.simulate(direction, entry, sl, tp, start,
                                    TF_LIFE_DAYS["2h"])
        rows.append({**s, "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R})
    return pd.DataFrame(rows)


# ---------- Hull trend lookups (BUGGY vs SAFE) ----------

def hull_trend_buggy(close, hull, ts):
    """etap_36 version — uses forming bar's close = LOOKAHEAD."""
    idx = hull.index.searchsorted(ts, side="right") - 1
    if idx < 2: return "na"
    c = close.iloc[idx]   # forming bar close — LOOKAHEAD
    h2 = hull.iloc[idx - 2]
    if pd.isna(c) or pd.isna(h2): return "na"
    return "up" if c > h2 else "down"


def hull_trend_safe(close, hull, ts):
    """SAFE version: use last CLOSED bar (idx-1) and HULL[2] from там."""
    idx = hull.index.searchsorted(ts, side="right") - 1
    if idx < 3: return "na"
    last_closed = idx - 1
    c = close.iloc[last_closed]
    h2 = hull.iloc[last_closed - 2]   # = idx - 3
    if pd.isna(c) or pd.isna(h2): return "na"
    return "up" if c > h2 else "down"


def aligned(direction, label):
    if label == "na": return "na"
    if direction == "LONG":
        return "aligned" if label == "up" else "counter"
    return "aligned" if label == "down" else "counter"


# ---------- run pipeline ----------

def run_symbol(symbol, start_date, hull_lookup_fn, label):
    """Returns dict with results."""
    print(f"\n{'='*70}\n[{label}] {symbol}, hull lookup: {hull_lookup_fn.__name__}")
    print(f"{'='*70}")
    tfs = ["1d", "6h", "2h"]
    dfs = {}
    for tf in tfs:
        df = load_df(symbol, tf)
        df = df[df.index >= pd.Timestamp(start_date, tz="UTC")].copy()
        df["atr14"] = compute_atr(df, 14)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        dfs[tf] = df
    df_1m = load_df(symbol, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(start_date, tz="UTC")]
    sim = FastSim(df_1m)
    years = (dfs["1d"].index[-1] - dfs["1d"].index[0]).days / 365
    print(f"  years: {years:.2f}, 1d bars: {len(dfs['1d'])}, "
          f"6h bars: {len(dfs['6h'])}, 1m bars: {len(df_1m)}")

    # indicators
    hull_1d = hull_ma(dfs["1d"]["close"], 78)

    obs_6h = collect_obs(dfs["6h"], dfs["6h"]["atr14"], "6h")
    fvgs_2h = collect_fvgs(dfs["2h"], dfs["2h"]["atr14"], "2h")
    setups = build_c2_setups(obs_6h, fvgs_2h, dfs["2h"])
    print(f"  C2 setups: {len(setups)}")

    # baseline (no filter)
    print(f"\n  --- C2 baseline (no Hull filter) ---")
    for rr in RR_TEST:
        df_e = evaluate_c2(setups, sim, rr)
        cl = df_e[df_e["outcome"].isin(["win", "loss"])]
        if cl.empty: continue
        wr = (cl["outcome"] == "win").mean() * 100
        print(f"    RR={rr}: closed={len(cl)} WR={wr:.1f}% "
              f"total={cl['R'].sum():+.1f}R R/tr={cl['R'].mean():+.3f} "
              f"freq={len(df_e)/years/52:.2f}/wk")

    # apply hull_1d filter
    df_1d = dfs["1d"]
    setups_filtered = []
    for s in setups:
        ts = s["trigger_time"]
        label_h = hull_lookup_fn(df_1d["close"], hull_1d, ts)
        if aligned(s["direction"], label_h) == "aligned":
            setups_filtered.append(s)
    print(f"\n  --- C2 + Hull-1d aligned ({hull_lookup_fn.__name__}) ---")
    print(f"    setups after filter: {len(setups_filtered)}/{len(setups)} "
          f"({len(setups_filtered)/max(len(setups),1)*100:.0f}%)")
    if not setups_filtered:
        return {"symbol": symbol, "n": 0}

    results = {"symbol": symbol, "lookup": hull_lookup_fn.__name__}
    for rr in RR_TEST:
        df_e = evaluate_c2(setups_filtered, sim, rr)
        cl = df_e[df_e["outcome"].isin(["win", "loss"])]
        if cl.empty: continue
        wr = (cl["outcome"] == "win").mean() * 100
        total_R = cl["R"].sum()
        # year-by-year
        yr = cl.groupby("year").agg(
            n=("R", "size"),
            wins=("outcome", lambda x: (x == "win").sum()),
            total_R=("R", "sum"))
        yr["WR"] = yr["wins"] / yr["n"] * 100
        bad_years = (yr["total_R"] < 0).sum()
        print(f"    RR={rr}: closed={len(cl)} WR={wr:.1f}% "
              f"total={total_R:+.1f}R R/tr={cl['R'].mean():+.3f} "
              f"freq={len(df_e)/years/52:.2f}/wk bad_yrs={bad_years}/{len(yr)}")
        if rr == 1.5:  # detail year-by-year for sweet spot
            for y, r in yr.iterrows():
                flag = " !" if r["total_R"] < 0 else ""
                print(f"      {int(y)}: n={int(r['n']):>3} WR={r['WR']:5.1f}% "
                      f"total={r['total_R']:+5.1f}R{flag}")
        results[f"RR{rr}"] = {"closed": len(cl), "wr": wr,
                                "total_R": total_R,
                                "R_tr": cl["R"].mean(),
                                "bad_yrs": bad_years, "yrs": len(yr),
                                "freq_wk": len(df_e)/years/52}
    return results


def main():
    t0 = time.time()
    print("="*70)
    print("ETAP 37: C2v2 lookahead audit + OOS validation")
    print("="*70)

    # 1. BTC reproduce etap_36 (BUGGY hull lookup)
    print("\n\n>>> STEP 1: BTC with BUGGY (etap_36 reproduction) <<<")
    btc_buggy = run_symbol("BTCUSDT", START_DATE, hull_trend_buggy,
                            "BTC-BUGGY")

    # 2. BTC with SAFE lookup (lookahead-fixed)
    print("\n\n>>> STEP 2: BTC with SAFE (lookahead-fixed) <<<")
    btc_safe = run_symbol("BTCUSDT", START_DATE, hull_trend_safe,
                           "BTC-SAFE")

    # 3. ETH OOS
    print("\n\n>>> STEP 3: ETHUSDT OOS with SAFE lookup <<<")
    eth_safe = run_symbol("ETHUSDT", START_DATE, hull_trend_safe,
                           "ETH-SAFE")

    # 4. SOL OOS
    print("\n\n>>> STEP 4: SOLUSDT OOS with SAFE lookup <<<")
    sol_safe = run_symbol("SOLUSDT", SOL_START, hull_trend_safe,
                           "SOL-SAFE")

    # SUMMARY
    print(f"\n\n{'='*70}\nSUMMARY: C2v2 across symbols x lookahead variants")
    print(f"{'='*70}")
    print(f"\n  {'Symbol':<12} {'Lookup':<8} {'RR':<5} "
          f"{'Closed':<8} {'WR':<8} {'Total R':<10} {'R/tr':<10} "
          f"{'Bad yr':<8} {'Freq/wk':<8}")
    for r in [btc_buggy, btc_safe, eth_safe, sol_safe]:
        if not r or r.get("n") == 0: continue
        for rr in RR_TEST:
            k = f"RR{rr}"
            if k not in r: continue
            d = r[k]
            print(f"  {r['symbol']:<12} {r['lookup']:<8} {rr:<5} "
                  f"{d['closed']:<8} {d['wr']:>5.1f}%  "
                  f"{d['total_R']:>+7.1f}R "
                  f"{d['R_tr']:>+.3f}    "
                  f"{d['bad_yrs']}/{d['yrs']:<5} {d['freq_wk']:>.2f}")
    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
