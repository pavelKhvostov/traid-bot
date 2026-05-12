"""Этап 67: индикаторный фильтр-grid на топ-цепочках B и F из etap_66.

B: FVG-12h -> OB-4h -> OB-1h -> FVG-15m   (+21R no_dom @ RR=2.0)
F: FVG-d   -> OB-6h -> OB-2h -> FVG-15m   (+19R no_dom @ RR=2.5)

Фильтры на сигнал:
  H12_L78_align    : close vs Hull-12h(L=78) shifted by 2 — aligned/counter/na
  H4_L78_align     : то же на 4h
  H1_L49_align     : то же на 1h (L=49 — стандарт)
  MH_sign          : Money Hands HA-MF знак (positive/negative)
  RSI_zone_1h      : ASVK RSI zone (green/red/neutral) на 1h к signal_time
  RSI_zone_4h      : то же на 4h
  NY_session       : signal_time UTC hour in [13, 21) (NY window)
  LONG_only / SHORT_only

Каждый фильтр пробуем отдельно + комбинации лучших.
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

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

# Re-use core from etap_66
sys_path_added = False
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "etap66_core", str(_Path(__file__).parent / "etap_66_114_chains_survey.py")
)
_e66 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_e66)

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"


# ===== Indicators =====

def wma_fast(arr: np.ndarray, period: int) -> np.ndarray:
    arr = np.asarray(arr, dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    if period <= 0 or n < period: return out
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def hull_ma(close: pd.Series, length: int) -> pd.Series:
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def hull_label_series(close: pd.Series, hull: pd.Series) -> pd.Series:
    """SAFE label: close[i] > hull[i-2], known at bar close i."""
    n = len(close); out = []
    for i in range(n):
        if i < 2:
            out.append("na"); continue
        c = close.iloc[i]; h2 = hull.iloc[i - 2]
        if pd.isna(c) or pd.isna(h2): out.append("na")
        else: out.append("up" if c > h2 else "down")
    return pd.Series(out, index=close.index)


def rsi_wilder(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0.0); loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def asvk_adjusted_rsi(close):
    rsi = rsi_wilder(close, 14)
    ema_for_coef = rsi.ewm(span=5, adjust=False).mean()
    coef = pd.Series(np.where(rsi >= 50, 1.2, 0.8), index=rsi.index)
    coefficient = (rsi * coef) / ema_for_coef.replace(0, np.nan)
    adj = rsi * coefficient
    return adj.ewm(span=5, adjust=False).mean()


def asvk_dynamic_levels(ema_3, lookback=200):
    n = len(ema_3)
    above = np.full(n, np.nan); below = np.full(n, np.nan)
    arr = ema_3.to_numpy()
    for i in range(lookback - 1, n):
        win = arr[i - lookback + 1: i + 1]
        win = win[~np.isnan(win)]
        if len(win) < 10: continue
        m = win > 50; z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 100/y; c2 = 50/y; c3 = c1-c2
            c5 = (c3/lookback)*z + c3
            above[i] = c5 * y
        m = win < 50; z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 50/y; c2 = 1/y; c3 = c1-c2
            c5 = (c3/lookback)*z + c3
            below[i] = 100 - (c5 * y)
    return pd.Series(above, index=ema_3.index), pd.Series(below, index=ema_3.index)


def asvk_zone_label(ema_3, above, below):
    out = []
    for e, a, b in zip(ema_3, above, below):
        if pd.isna(e) or pd.isna(a) or pd.isna(b):
            out.append("na")
        elif e > a:
            out.append("red")
        elif e < b:
            out.append("green")
        else:
            out.append("neutral")
    return pd.Series(out, index=ema_3.index)


def heikin_ashi(o, h, l, c):
    n = len(c)
    ha_close = (o + h + l + c) / 4
    ha_open = np.zeros(n)
    ha_open[0] = (o.iloc[0] + c.iloc[0]) / 2
    ha_close_arr = ha_close.values
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close_arr[i - 1]) / 2
    ha_open = pd.Series(ha_open, index=c.index)
    ha_high = pd.concat([h, ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([l, ha_open, ha_close], axis=1).min(axis=1)
    return ha_open, ha_high, ha_low, ha_close


def money_flow_ha(df):
    ha_o, _, _, ha_c = heikin_ashi(df["open"], df["high"], df["low"], df["close"])
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    raw = ((ha_c - ha_o) / rng) * 200
    return raw.rolling(60, min_periods=60).mean() - 2.25


# ===== Lookup helpers =====

def safe_label_at(series, ts, default="na"):
    """idx-1 lookup (last closed bar before signal)."""
    idx = series.index.searchsorted(ts, side="right") - 1
    if idx < 0 or idx >= len(series): return default
    v = series.iloc[idx]
    if pd.isna(v): return default
    return v


def hull_align(label, direction):
    if label == "na": return "na"
    is_up = label == "up"
    if direction == "LONG":
        return "aligned" if is_up else "counter"
    return "aligned" if not is_up else "counter"


def mh_sign_align(mh_val, direction):
    if pd.isna(mh_val): return "na"
    is_pos = mh_val > 0
    if direction == "LONG":
        return "aligned" if is_pos else "counter"
    return "aligned" if not is_pos else "counter"


def rsi_zone_align(zone, direction):
    """Premium/discount alignment: LONG benefits from green (discount), SHORT from red (premium)."""
    if zone == "na": return "na"
    if direction == "LONG":
        return "aligned" if zone == "green" else ("counter" if zone == "red" else "neutral")
    return "aligned" if zone == "red" else ("counter" if zone == "green" else "neutral")


def attach_features(setups, hulls, mh_series_by_tf, rsi_zones_by_tf):
    """Mutate setups in-place adding feature columns."""
    for s in setups:
        ts = s["signal_time"]
        d = s["direction"]
        for tf_lbl, ser in hulls.items():
            lbl = safe_label_at(ser, ts)
            s[f"hull_{tf_lbl}"] = hull_align(lbl, d)
        for tf, ser in mh_series_by_tf.items():
            idx = ser.index.searchsorted(ts, side="right") - 1
            v = ser.iloc[idx] if 0 <= idx < len(ser) else np.nan
            s[f"mh_{tf}"] = mh_sign_align(v, d)
        for tf, ser in rsi_zones_by_tf.items():
            z = safe_label_at(ser, ts)
            s[f"rsi_{tf}"] = rsi_zone_align(z, d)
        h = ts.hour
        s["ny_session"] = "in" if 13 <= h < 21 else "out"
        s["london_session"] = "in" if 7 <= h < 16 else "out"


# ===== Evaluator with filter =====

def eval_filter(setups, rr, df_1m, df_1d, filter_fn=None, only_dom=False):
    rows = []
    for s in setups:
        tup = _e66.build_orders(s)
        if tup is None: continue
        entry, sl = tup
        if only_dom and not _e66.do_match_aligned(s, entry, df_1d): continue
        if filter_fn is not None and not filter_fn(s): continue
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
        rows.append({"outcome": outcome, "R": R, "year": s["year"],
                      "direction": s["direction"]})
    return pd.DataFrame(rows)


def metrics(df):
    if df.empty or "outcome" not in df.columns: return None
    cl = df[df["outcome"].isin(["win", "loss"])]
    if cl.empty: return None
    nc = len(cl); wins = (cl["R"] > 0).sum()
    wr = wins/nc*100; tot = cl["R"].sum()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    return {"n": nc, "wr": wr, "total": tot, "bad": bad, "n_yrs": len(yr)}


def main():
    t0 = time.time()
    print("[INFO] load data")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    print("[INFO] compute indicators")
    # Hull labels
    hulls = {}
    for tf, df, L in [("12h", df_12h, 78), ("12h", df_12h, 160),
                       ("4h", df_4h, 78), ("4h", df_4h, 160),
                       ("1h", df_1h, 49), ("1h", df_1h, 78)]:
        h = hull_ma(df["close"], L)
        lbl = hull_label_series(df["close"], h)
        hulls[f"{tf}_L{L}"] = lbl

    # Money Hands HA-MF (sign)
    mh_series = {
        "1h": money_flow_ha(df_1h),
        "4h": money_flow_ha(df_4h),
        "12h": money_flow_ha(df_12h),
    }

    # ASVK RSI zones
    rsi_zones = {}
    for tf, df in [("1h", df_1h), ("4h", df_4h), ("12h", df_12h)]:
        e3 = asvk_adjusted_rsi(df["close"])
        above, below = asvk_dynamic_levels(e3, lookback=200)
        rsi_zones[tf] = asvk_zone_label(e3, above, below)

    print("[INFO] collect zones")
    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")

    # Detect chains B and F
    print("[INFO] detect chain B")
    setups_B = _e66.detect_4stage(fvgs_12h, obs_4h, "OB", obs_1h, "OB",
                                   fvgs_15m, "12h", "4h", "1h", "15m", df_12h)
    seen = set(); B_uniq = []
    for s in setups_B:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k in seen: continue
        seen.add(k); B_uniq.append(s)

    print("[INFO] detect chain F")
    setups_F = _e66.detect_4stage(fvgs_1d, obs_6h, "OB", obs_2h, "OB",
                                   fvgs_15m, "1d", "6h", "2h", "15m", df_1d)
    seen = set(); F_uniq = []
    for s in setups_F:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k in seen: continue
        seen.add(k); F_uniq.append(s)

    print(f"[INFO] B setups: {len(B_uniq)}, F setups: {len(F_uniq)}")

    print("[INFO] attach features")
    attach_features(B_uniq, hulls, mh_series, rsi_zones)
    attach_features(F_uniq, hulls, mh_series, rsi_zones)

    # ===== Define filter battery =====
    filters = {
        "baseline (no filter)": None,
        "hull_12h_L78 aligned": lambda s: s["hull_12h_L78"] == "aligned",
        "hull_12h_L160 aligned": lambda s: s["hull_12h_L160"] == "aligned",
        "hull_4h_L78 aligned": lambda s: s["hull_4h_L78"] == "aligned",
        "hull_4h_L160 aligned": lambda s: s["hull_4h_L160"] == "aligned",
        "hull_1h_L49 aligned": lambda s: s["hull_1h_L49"] == "aligned",
        "mh_1h aligned": lambda s: s["mh_1h"] == "aligned",
        "mh_4h aligned": lambda s: s["mh_4h"] == "aligned",
        "mh_12h aligned": lambda s: s["mh_12h"] == "aligned",
        "rsi_1h aligned": lambda s: s["rsi_1h"] == "aligned",
        "rsi_4h aligned": lambda s: s["rsi_4h"] == "aligned",
        "rsi_1h not counter": lambda s: s["rsi_1h"] != "counter",
        "rsi_4h not counter": lambda s: s["rsi_4h"] != "counter",
        "NY session": lambda s: s["ny_session"] == "in",
        "London session": lambda s: s["london_session"] == "in",
        "LONG only": lambda s: s["direction"] == "LONG",
        "SHORT only": lambda s: s["direction"] == "SHORT",
        # Combos
        "hull_4h_L78 + mh_4h aligned": lambda s: s["hull_4h_L78"] == "aligned" and s["mh_4h"] == "aligned",
        "hull_12h_L78 + hull_4h_L78 aligned": lambda s: s["hull_12h_L78"] == "aligned" and s["hull_4h_L78"] == "aligned",
        "hull_4h_L78 + rsi_4h not counter": lambda s: s["hull_4h_L78"] == "aligned" and s["rsi_4h"] != "counter",
        "mh_1h + mh_4h aligned": lambda s: s["mh_1h"] == "aligned" and s["mh_4h"] == "aligned",
        "hull_12h_L78 + NY": lambda s: s["hull_12h_L78"] == "aligned" and s["ny_session"] == "in",
        "hull_4h_L78 + NY": lambda s: s["hull_4h_L78"] == "aligned" and s["ny_session"] == "in",
        "hull_4h_L78 + LONG": lambda s: s["hull_4h_L78"] == "aligned" and s["direction"] == "LONG",
    }

    RR_LIST = [1.8, 2.0, 2.5]

    chains = [("B (FVG-12h->OB-4h->OB-1h->FVG-15m)", B_uniq),
              ("F (FVG-d->OB-6h->OB-2h->FVG-15m)", F_uniq)]

    all_rows = []
    for chain_label, setups in chains:
        print(f"\n{'='*78}\n{chain_label}  | setups={len(setups)}\n{'='*78}")
        # Try each filter, no_dom + do_match
        for dom in [False, True]:
            dom_lbl = "+do_match" if dom else "no_dom"
            print(f"\n--- {dom_lbl} ---")
            print(f"  {'filter':<42} {'RR':>4} {'n':>4} {'WR':>6} {'total':>8} {'bad':>5}")
            for flt_name, flt_fn in filters.items():
                for rr in RR_LIST:
                    df = eval_filter(setups, rr, df_1m, df_1d, flt_fn, only_dom=dom)
                    m = metrics(df)
                    if m is None:
                        continue
                    if m["n"] < 5: continue  # too few to be meaningful
                    print(f"  {flt_name[:42]:<42} {rr:>4} {m['n']:>4} "
                          f"{m['wr']:>5.1f}% {m['total']:>+7.1f}R {m['bad']:>2}/{m['n_yrs']}")
                    all_rows.append({"chain": chain_label, "dom": dom_lbl,
                                      "filter": flt_name, "rr": rr, **m})

    # FINAL RANKINGS
    print(f"\n\n{'='*80}\nFINAL RANKINGS (n>=10, bad<=1)\n{'='*80}")
    clean = [r for r in all_rows if r["n"] >= 10 and r["bad"] <= 1]
    clean = sorted(clean, key=lambda x: x["total"], reverse=True)
    print(f"\nTOP 20 by total R:")
    for r in clean[:20]:
        print(f"  {r['chain'][:38]:<38} {r['dom']:<10} {r['filter'][:36]:<36} "
              f"RR={r['rr']} n={r['n']:>3} WR={r['wr']:5.1f}% total={r['total']:+6.1f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    # Best per chain
    print(f"\nBEST PER CHAIN (any filter, any RR, n>=10, bad<=1):")
    from collections import defaultdict
    by_chain = defaultdict(list)
    for r in clean: by_chain[r["chain"]].append(r)
    for chain, rs in by_chain.items():
        best = max(rs, key=lambda x: x["total"])
        print(f"  {chain[:60]:<60}: {best['dom']} "
              f"{best['filter'][:36]:<36} RR={best['rr']} "
              f"n={best['n']:>3} WR={best['wr']:5.1f}% "
              f"total={best['total']:+6.1f}R bad={best['bad']}/{best['n_yrs']}")

    # Best with high WR (>=55%)
    print(f"\nBEST WR (WR>=55%, n>=10, bad<=1) — sorted by total R:")
    hi_wr = [r for r in clean if r["wr"] >= 55]
    hi_wr = sorted(hi_wr, key=lambda x: x["total"], reverse=True)
    for r in hi_wr[:15]:
        print(f"  {r['chain'][:38]:<38} {r['dom']:<10} {r['filter'][:36]:<36} "
              f"RR={r['rr']} n={r['n']:>3} WR={r['wr']:5.1f}% total={r['total']:+6.1f}R")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
