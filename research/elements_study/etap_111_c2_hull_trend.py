"""etap_111: тестируем замену EMA-200 (2h) на Hull-6h trendline в C2.

BTC только, 3 года.

Сравнение:
  - EMA-200 (2h)   — оригинал из etap_43
  - Hull-6h (78)   — наш trendline indicator

Trend-фильтр срабатывает в момент close c2-свечи trigger FVG-2h:
  LONG:  для EMA-200 — close_2h(c2) > ema200_2h(c2)
         для Hull-6h — close_6h(last_closed_before_c2_2h_close) > hull_6h[t-2]
  SHORT: зеркально

Остальная логика C2 без изменений.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

DAYS_BACK = 1095  # 3 года
SYMBOL = "BTCUSDT"
ANCHOR_TF = "6h"
TRIGGER_TF = "2h"
MIN_SL_PCT = 1.0
SL_BUF_ATR = 0.3
ENTRY_PCT = 0.5
RR = 1.0
LIFE_DAYS = 10
TIMEOUT_DAYS = 3
HULL_LEN = 78


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low), (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float); weights /= weights.sum()
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


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": ob.cur_time, "direction": ob.direction,
                    "bottom": ob.bottom, "top": ob.top, "atr": a, "tf": tf, "idx": idx,
                    "prev_time": ob.prev_time})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": f.c2_time, "direction": f.direction,
                    "bottom": f.bottom, "top": f.top, "atr": a, "tf": tf, "idx": idx,
                    "c0_time": f.c0_time})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def is_pro_trend_ema200(t, df_2h_ema, ema_arr, close_arr):
    """t = dict trigger FVG-2h. Использует EMA-200 на 2h в момент c2."""
    direction = t["direction"]
    idx = t["idx"]
    em = float(ema_arr[idx]); cl = float(close_arr[idx])
    if pd.isna(em): return False
    if direction == "LONG":  return cl > em
    else:                    return cl < em


def is_pro_trend_hull6h(t, df_6h, hull_6h):
    """t = trigger FVG-2h. Использует Hull-6h trendline.
    Проверяет close_6h[last closed before c2 close] > hull_6h[t-2]."""
    direction = t["direction"]
    # c2 close time = c2.open + 2h
    c2_close = t["time"] + pd.Timedelta(hours=2)
    # последний закрытый 6h бар на момент c2_close
    idx_pos = df_6h.index.searchsorted(c2_close, side="right") - 1
    if idx_pos < 2: return False  # need hull[idx-2]
    if pd.isna(hull_6h.iloc[idx_pos - 2]): return False
    close_6h = float(df_6h["close"].iloc[idx_pos])
    hull_val = float(hull_6h.iloc[idx_pos - 2])
    if direction == "LONG":  return close_6h > hull_val
    else:                    return close_6h < hull_val


def build_c2_setups(obs_6h, fvgs_2h, pro_trend_fn):
    a_tf_td = pd.Timedelta(ANCHOR_TF)
    a_life = pd.Timedelta(days=LIFE_DAYS)
    t_sorted = sorted(fvgs_2h, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                        for t in t_sorted])
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
            if not zones_overlap(t["bottom"], t["top"], a["bottom"], a["top"]): continue
            if not pro_trend_fn(t): continue
            setups.append({"anchor": a, "trigger": t, "direction": t["direction"],
                           "year": t["time"].year})
            break
    return setups


def build_c2_orders(s):
    t = s["trigger"]
    direction = t["direction"]
    fb, ft = t["bottom"], t["top"]
    atr = t["atr"]
    if direction == "LONG":
        entry = fb + ENTRY_PCT * (ft - fb)
        atr_sl = fb - SL_BUF_ATR * atr
        min_dist = entry * MIN_SL_PCT / 100
        sl = min(atr_sl, entry - min_dist)
    else:
        entry = ft - ENTRY_PCT * (ft - fb)
        atr_sl = ft + SL_BUF_ATR * atr
        min_dist = entry * MIN_SL_PCT / 100
        sl = max(atr_sl, entry + min_dist)
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + RR * risk if direction == "LONG" else entry - RR * risk
    return entry, sl, tp


def evaluate(setups, sim):
    rows = []
    for s in setups:
        tup = build_c2_orders(s)
        if tup is None: continue
        entry, sl, tp = tup
        start = s["trigger"]["time"] + pd.Timedelta(TRIGGER_TF)
        outcome, R = sim.simulate(s["direction"], entry, sl, tp, start, TIMEOUT_DAYS)
        rows.append({"year": s["year"], "direction": s["direction"],
                     "outcome": outcome, "R": R})
    return pd.DataFrame(rows)


def report(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])]
    nc = len(closed)
    if nc == 0:
        print(f"  {label}: no closed"); return
    wins = (closed["R"] > 0).sum(); losses = (closed["R"] < 0).sum()
    wr = wins / nc * 100
    pnl = closed["R"].sum()
    yr = closed.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    print(f"  {label:<28}: total={len(df):4d}  closed={nc:4d}  W={wins:3d} L={losses:3d}  "
          f"WR={wr:5.1f}%  PnL={pnl:+7.1f}R  bad_yrs={bad}/{len(yr)}")
    yrs_str = "  ".join(f"{int(y)}:{r:+.1f}" for y, r in yr.sort_index().items())
    print(f"    year-by-year: {yrs_str}")


def main():
    print(f"etap_111: C2 trend-filter A/B test — EMA-200 vs Hull-6h")
    print(f"BTC, {DAYS_BACK}d (~3y)")
    print()

    print("[INFO] loading data")
    df_6h_full = load_df(SYMBOL, "6h")
    df_2h_full = load_df(SYMBOL, "2h")
    df_1m = load_df(SYMBOL, "1m")
    if df_6h_full.empty or df_2h_full.empty:
        # compose from 1h if missing
        df_1h = load_df(SYMBOL, "1h")
        df_6h_full = compose_from_base(df_1h, "6h") if df_6h_full.empty else df_6h_full
        df_2h_full = compose_from_base(df_1h, "2h") if df_2h_full.empty else df_2h_full

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_6h = df_6h_full[df_6h_full.index >= cutoff].copy()
    df_2h = df_2h_full[df_2h_full.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    df_6h["atr14"] = compute_atr(df_6h, 14)
    df_2h["atr14"] = compute_atr(df_2h, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()
    hull_6h = hull_ma(df_6h["close"], length=HULL_LEN)

    sim = FastSim(df_1m)
    years = (df_6h.index[-1] - df_6h.index[0]).days / 365
    print(f"  years actual: {years:.2f}")

    print("[INFO] collecting OB-6h and FVG-2h")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    fvgs_2h = collect_fvgs(df_2h, df_2h["atr14"], "2h")
    print(f"  OB-6h: {len(obs_6h)}, FVG-2h: {len(fvgs_2h)}")

    # NO filter (для контекста — сколько ВСЕГО возможных setup'ов)
    print()
    print("[A] NO trend filter (raw OB-6h x FVG-2h)")
    setups_raw = build_c2_setups(obs_6h, fvgs_2h, pro_trend_fn=lambda t: True)
    print(f"  setups: {len(setups_raw)}")
    df_raw = evaluate(setups_raw, sim)
    report(df_raw, "NO_FILTER")

    # EMA-200 (original C2)
    print()
    print("[B] EMA-200 on 2h (original C2)")
    ema_arr = df_2h["ema200"].to_numpy()
    close_2h = df_2h["close"].to_numpy()
    setups_ema = build_c2_setups(obs_6h, fvgs_2h,
                                   pro_trend_fn=lambda t: is_pro_trend_ema200(t, df_2h, ema_arr, close_2h))
    print(f"  setups: {len(setups_ema)}")
    df_ema = evaluate(setups_ema, sim)
    report(df_ema, "EMA-200_2h (original)")

    # Hull-6h
    print()
    print("[C] Hull-6h trendline (new)")
    setups_hull = build_c2_setups(obs_6h, fvgs_2h,
                                    pro_trend_fn=lambda t: is_pro_trend_hull6h(t, df_6h, hull_6h))
    print(f"  setups: {len(setups_hull)}")
    df_hull = evaluate(setups_hull, sim)
    report(df_hull, "Hull-6h (new)")

    # Сравнительная сводка
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    def stats(df, label):
        closed = df[df["outcome"].isin(["win", "loss"])]
        if not len(closed): return None
        W = (closed["R"] > 0).sum(); L = (closed["R"] < 0).sum()
        wr = W / len(closed) * 100
        pnl = closed["R"].sum()
        yr = closed.groupby("year")["R"].sum()
        bad = (yr < 0).sum()
        return {"label": label, "total": len(df), "closed": len(closed),
                "W": W, "L": L, "wr": wr, "pnl": pnl, "bad": bad, "n_yrs": len(yr)}

    for r in [stats(df_raw, "NO_FILTER"), stats(df_ema, "EMA-200_2h"), stats(df_hull, "Hull-6h")]:
        if r is None: continue
        print(f"  {r['label']:<20}  total={r['total']:4d}  closed={r['closed']:4d}  "
              f"WR={r['wr']:5.1f}%  PnL={r['pnl']:+7.1f}R  bad={r['bad']}/{r['n_yrs']}")


if __name__ == "__main__":
    main()
