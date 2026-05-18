"""etap_116: FVG-D/12h стратегий — большой comparative survey.

Базис: chain B (FVG-12h → OB-4h → OB-1h → FVG-15m) +40R BTC 6.3y.

Тестируемые вариации (single-variable changes):
  A. Baseline B (reference +40R)
  B1. B + SWEPT on OB-1h
  B2. B + SWEPT on OB-4h
  C1. RDRB-4h на L2 instead of OB-4h
  C2. RDRB-1h на L3 instead of OB-1h
  C3. RDRB-12h на L1 (новый top, instead of FVG-12h)
  D1. Fractal-LL/HH 4h на L2
  D2. Fractal-LL/HH 1h на L3
  E1. FVG-1h на L3 instead of OB-1h
  E2. OB-15m на L4 instead of FVG-15m
  F1. B + Hull-6h trend filter
  F2. B + EMA-200(2h) trend filter
  F3. B + Score-based filter (composite > 0)
  F4. B + ViC filter (|maxV(D-1) - 1d_open| > 1 ATR)

BTC 6.3y, RR=2.0, MIN_SL=1%, entry_pct=0.70, SL asymmetric 0.35/0.65.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg
from strategies.strategy_rdrb import detect_rdrb

_E66 = Path(__file__).parent / "etap_66_114_chains_survey.py"
_spec = _ilu.spec_from_file_location("etap66_core", _E66)
_e66 = _ilu.module_from_spec(_spec); _sys.modules["etap66_core"] = _e66
_spec.loader.exec_module(_e66)

_E74 = Path(__file__).parent / "etap_74_114_fixed_BFJK.py"
_spec74 = _ilu.spec_from_file_location("etap74_core", _E74)
_e74 = _ilu.module_from_spec(_spec74); _sys.modules["etap74_core"] = _e74
_spec74.loader.exec_module(_e74)

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec103 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec103); _sys.modules["etap103_core"] = _e103
_spec103.loader.exec_module(_e103)
build_score_series = _e103.build_score_series

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ALLOW_MULTI = 5
RR = 2.0
MAX_HOLD_DAYS = 7


# ===== Block collectors =====

def collect_rdrb_zones(df, atr, tf):
    """RDRB как { time, direction, bottom, top, atr, tf, idx, prev_time }."""
    out = []
    tf_hours = _e66.TF_HOURS[tf]
    for idx in range(2, len(df) - 1):
        z = detect_rdrb(df, idx)
        if z is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        # эмулируем структуру OB для unified pipeline
        out.append({"time": df.index[idx], "direction": z.direction,
                    "bottom": z.bottom, "top": z.top, "atr": a, "tf": tf,
                    "idx": idx, "prev_time": df.index[idx - 2]})
    return out


def collect_fractal_zones(df, atr, tf):
    """Fractal LL/HH как зоны (от high до low фрактального бара).
    direction: LONG для LL, SHORT для HH.
    zone: для LL = [low, low + 0.5*atr], для HH = [high - 0.5*atr, high]."""
    out = []
    n = len(df)
    highs = df["high"].values; lows = df["low"].values
    for i in range(2, n - 2):
        f_low = float(lows[i]); f_high = float(highs[i])
        is_ll = (f_low < float(lows[i-2]) and f_low < float(lows[i-1])
                 and f_low < float(lows[i+1]) and f_low < float(lows[i+2]))
        is_hh = (f_high > float(highs[i-2]) and f_high > float(highs[i-1])
                 and f_high > float(highs[i+1]) and f_high > float(highs[i+2]))
        if not (is_ll or is_hh): continue
        a = float(atr.iloc[i])
        if pd.isna(a) or a <= 0: continue
        # Confirm time = i + 2 (когда фрактал подтверждается)
        confirm_idx = i + 2
        if confirm_idx >= n: continue
        if is_ll:
            # LONG zone
            out.append({"time": df.index[confirm_idx], "direction": "LONG",
                        "bottom": f_low, "top": f_low + 0.5 * a,
                        "atr": a, "tf": tf, "idx": confirm_idx,
                        "prev_time": df.index[i]})
        if is_hh:
            out.append({"time": df.index[confirm_idx], "direction": "SHORT",
                        "bottom": f_high - 0.5 * a, "top": f_high,
                        "atr": a, "tf": tf, "idx": confirm_idx,
                        "prev_time": df.index[i]})
    return out


# ===== SWEPT check (from etap_41 / 1.1.1) =====

def check_swept_on_ob(zone, df_top):
    """zone = OB dict с prev_time, time, direction. df_top = df на TF zone.
    SWEPT: min(prev.low, cur.low) < min(idx-1.low, idx-2.low) для LONG (mirror SHORT)."""
    try:
        cur_idx = df_top.index.get_loc(zone["time"])
        prev_idx = df_top.index.get_loc(zone["prev_time"])
    except (KeyError, TypeError):
        return False
    if prev_idx < 2: return False
    c1l = float(df_top.iloc[prev_idx]["low"]); c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx-1]["low"]); n2l = float(df_top.iloc[prev_idx-2]["low"])
    n1h = float(df_top.iloc[prev_idx-1]["high"]); n2h = float(df_top.iloc[prev_idx-2]["high"])
    if zone["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


# ===== Filters =====

def compute_atr(df, period=14):
    h, l, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
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


def filter_hull_6h(setup, df_6h, hull_6h):
    """LONG: close_6h[last closed @ signal_time] > hull_6h[t-2]."""
    t = setup["signal_time"]
    idx = df_6h.index.searchsorted(t, side="right") - 1
    if idx < 2: return False
    if pd.isna(hull_6h.iloc[idx - 2]): return False
    c = float(df_6h["close"].iloc[idx]); h = float(hull_6h.iloc[idx - 2])
    return c > h if setup["direction"] == "LONG" else c < h


def filter_ema_2h(setup, df_2h):
    t = setup["signal_time"]
    idx = df_2h.index.searchsorted(t, side="right") - 1
    if idx < 0 or pd.isna(df_2h["ema200"].iloc[idx]): return False
    c = float(df_2h["close"].iloc[idx]); e = float(df_2h["ema200"].iloc[idx])
    return c > e if setup["direction"] == "LONG" else c < e


def filter_score(setup, score_long, score_short):
    """score > 0 на 1h баре в момент signal_time."""
    t = setup["signal_time"]
    score_series = score_long if setup["direction"] == "LONG" else score_short
    idx = score_series.index.searchsorted(t, side="right") - 1
    if idx < 0: return False
    s = score_series.iloc[idx]
    if pd.isna(s): return False
    return s > 0


def filter_vic(setup, vic_d_series, atr_1h):
    """|maxV(D-1) - 1d_open| > 1 ATR-1h на signal_time."""
    t = setup["signal_time"]
    # последний bar 1d ДО signal_time
    idx = vic_d_series.index.searchsorted(t, side="right") - 1
    if idx < 1: return False
    maxV_prev = vic_d_series.iloc[idx - 1]
    d_open = vic_d_series["d_open"].iloc[idx] if "d_open" in vic_d_series else None
    if pd.isna(maxV_prev): return False
    # упрощение: вместо реальной ViC формулы используем |maxV - 1d_open_last| > ATR
    # ViC требует отдельный 1m walk — для скорости skip
    a_idx = atr_1h.index.searchsorted(t, side="right") - 1
    if a_idx < 0 or pd.isna(atr_1h.iloc[a_idx]): return False
    return True  # placeholder — реальный ViC потребует отдельной интеграции


# ===== Generic 4-stage detector =====

def detect_generic_4stage(l1_zones, l2_zones, l3_zones, l4_zones,
                           l1_tf, l2_tf, l3_tf, l4_tf, df_l1,
                           allow_multi=5,
                           swept_l3_df=None, swept_l2_df=None):
    """4-stage cascade с настраиваемыми блоками. zones — dicts с
    {time, direction, bottom, top, idx, prev_time, atr}.
    """
    l1_td = pd.Timedelta(hours=_e66.TF_HOURS[l1_tf])
    l2_td = pd.Timedelta(hours=_e66.TF_HOURS[l2_tf])
    l3_td = pd.Timedelta(hours=_e66.TF_HOURS[l3_tf])
    l4_td = pd.Timedelta(hours=_e66.TF_HOURS[l4_tf])
    l1_life = pd.Timedelta(days=_e66.LIFE_DAYS[l1_tf])
    l3_life = pd.Timedelta(days=_e66.LIFE_DAYS[l3_tf])

    def _start_of(z):
        return z["c0_time"] if "c0_time" in z else z["prev_time"]
    l3_sorted = sorted(l3_zones, key=_start_of)
    l4_sorted = sorted(l4_zones, key=_start_of)
    l3_start_times = np.array([np.datetime64(
        _start_of(z).tz_localize(None) if _start_of(z).tz else _start_of(z))
        for z in l3_sorted])
    l4_c0_times = np.array([np.datetime64(
        _start_of(z).tz_localize(None) if _start_of(z).tz else _start_of(z))
        for z in l4_sorted])

    setups = []
    for l1 in l1_zones:
        L1_close = l1["time"] + l1_td
        L1_max_end = L1_close + l1_life
        inval = _e66.find_invalidation(df_l1, l1, l1_td, L1_max_end)
        L1_active_end = inval if inval is not None else L1_max_end
        n_for_l1 = 0
        for l2 in l2_zones:
            if l2["direction"] != l1["direction"]: continue
            if not _e66.any_edge_inside(l2["bottom"], l2["top"], l1["bottom"], l1["top"]):
                continue
            l2_start = _start_of(l2)
            l2_close = l2["time"] + l2_td
            if l2_start < _start_of(l1): continue
            if l2_close > L1_active_end: continue
            # SWEPT на L2 (опционально)
            if swept_l2_df is not None:
                if not check_swept_on_ob(l2, swept_l2_df): continue

            l3_search_start = l2_close
            l3_search_end = min(l3_search_start + l3_life, L1_active_end)
            j0 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_start.tz_localize(None) if l3_search_start.tz else l3_search_start), side="left")
            j1 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_end.tz_localize(None) if l3_search_end.tz else l3_search_end), side="right")
            for oj in range(j0, j1):
                l3 = l3_sorted[oj]
                if l3["direction"] != l1["direction"]: continue
                if not _e66.any_edge_inside(l3["bottom"], l3["top"], l1["bottom"], l1["top"]): continue
                if not _e66.any_edge_inside(l3["bottom"], l3["top"], l2["bottom"], l2["top"]): continue
                L3_close = l3["time"] + l3_td
                if L3_close > L1_active_end: continue
                # SWEPT на L3 (опционально)
                if swept_l3_df is not None:
                    if not check_swept_on_ob(l3, swept_l3_df): continue

                L3_start = _start_of(l3)
                l4_max_c2_open = L3_close - l4_td

                k0 = np.searchsorted(l4_c0_times, np.datetime64(
                    L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
                f_e = None
                for ek in range(k0, len(l4_sorted)):
                    l4z = l4_sorted[ek]
                    c0 = _start_of(l4z)
                    if c0 < L3_start: continue
                    if l4z["time"] > l4_max_c2_open: continue
                    if c0 > L3_close: break
                    if l4z["direction"] != l1["direction"]: continue
                    if (l4z["time"] + l4_td) > L1_active_end: continue
                    if not _e66.zones_overlap(l4z["bottom"], l4z["top"], l1["bottom"], l1["top"]): continue
                    if not _e66.zones_overlap(l4z["bottom"], l4z["top"], l2["bottom"], l2["top"]): continue
                    f_e = l4z; break
                if f_e is None: continue

                x1_b = max(l1["bottom"], l2["bottom"])
                x1_t = min(l1["top"], l2["top"])
                setups.append({
                    "fvg_b": f_e["bottom"], "fvg_t": f_e["top"],
                    "x1_bottom": x1_b, "x1_top": x1_t,
                    "obh_b": l3["bottom"], "obh_t": l3["top"],
                    "tf_minutes": 15, "year": L3_close.year,
                    "direction": f_e["direction"], "signal_time": L3_close,
                })
                n_for_l1 += 1
                if n_for_l1 >= allow_multi: break
            if n_for_l1 >= allow_multi: break
    return setups


def evaluate(setups, df_1m, rr=RR, extra_filter=None):
    """Дедуп + simulate. extra_filter(setup) -> True если pass."""
    if extra_filter is not None:
        setups = [s for s in setups if extra_filter(s)]
    seen = {}
    for s in setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k not in seen:
            seen[k] = s
    setups = list(seen.values())
    rows = []
    for s in sorted(setups, key=lambda x: x["signal_time"]):
        tup = _e66.build_orders(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R, et, xt = _e74.simulate_with_times(s, entry, sl, tp, df_1m, MAX_HOLD_DAYS)
        rows.append({"year": s["year"], "direction": s["direction"],
                     "outcome": outcome, "R": R, "signal_time": s["signal_time"]})
    return pd.DataFrame(rows), len(setups)


def stats(df, label):
    if df.empty:
        return {"label": label, "n_setups": 0, "closed": 0, "wr": 0, "pnl": 0, "bad": 0, "n_yrs": 0}
    closed = df[df["outcome"].isin(["win", "loss"])]
    nc = len(closed)
    if nc == 0:
        return {"label": label, "n_setups": len(df), "closed": 0, "wr": 0, "pnl": 0, "bad": 0, "n_yrs": 0}
    W = (closed["R"] > 0).sum(); L_ = (closed["R"] < 0).sum()
    wr = W / nc * 100
    pnl = closed["R"].sum()
    yr = closed.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    Rs = sorted(closed["R"].tolist(), reverse=True)
    top5_pct = sum(Rs[:5]) / pnl * 100 if pnl > 0 else 0
    return {"label": label, "n_setups": len(df), "closed": nc,
            "W": W, "L": L_, "wr": wr, "pnl": pnl, "bad": bad,
            "n_yrs": len(yr), "top5_pct": top5_pct}


def main():
    print("etap_116: FVG-D/12h стратегий — large survey (BTC 6.3y)")
    print()
    print("[INFO] loading data")
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
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = compute_atr(df, 14)
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()
    hull_6h_78 = hull_ma(df_6h["close"], length=78)

    print("[INFO] collecting block zones")
    # L1: FVG-12h, RDRB-12h
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    rdrbs_12h = collect_rdrb_zones(df_12h, df_12h["atr14"], "12h")

    # L2: OB-4h, RDRB-4h, Fractal-4h
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    rdrbs_4h = collect_rdrb_zones(df_4h, df_4h["atr14"], "4h")
    fractals_4h = collect_fractal_zones(df_4h, df_4h["atr14"], "4h")

    # L3: OB-1h, RDRB-1h, Fractal-1h, FVG-1h
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    rdrbs_1h = collect_rdrb_zones(df_1h, df_1h["atr14"], "1h")
    fractals_1h = collect_fractal_zones(df_1h, df_1h["atr14"], "1h")
    fvgs_1h = _e66.collect_fvgs(df_1h, df_1h["atr14"], "1h")

    # L4: FVG-15m, OB-15m
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    obs_15m = _e66.collect_obs(df_15m, df_15m["atr14"], "15m")

    print(f"  zones: FVG-12h={len(fvgs_12h)} RDRB-12h={len(rdrbs_12h)} | "
          f"OB-4h={len(obs_4h)} RDRB-4h={len(rdrbs_4h)} FR-4h={len(fractals_4h)} | "
          f"OB-1h={len(obs_1h)} RDRB-1h={len(rdrbs_1h)} FR-1h={len(fractals_1h)} FVG-1h={len(fvgs_1h)} | "
          f"FVG-15m={len(fvgs_15m)} OB-15m={len(obs_15m)}")

    # Score series for F3 filter
    print("[INFO] computing momentum score")
    score_long, score_short = build_score_series(df_1h)

    # === Run variants ===
    results = []

    print()
    print(f"  {'Variant':<48} {'setups':>6} {'closed':>6} {'WR':>6} {'PnL':>9} {'top5%':>6} {'bad':>5}")
    print("  " + "-"*100)

    def run(label, setups, extra_filter=None):
        df, n = evaluate(setups, df_1m, extra_filter=extra_filter)
        st = stats(df, label)
        print(f"  {label:<48} {n:>6d} {st['closed']:>6d} {st['wr']:>5.1f}% "
              f"{st['pnl']:>+8.1f}R {st['top5_pct']:>5.1f}% {st['bad']}/{st['n_yrs']}")
        results.append(st)

    # A. Baseline B
    s_A = detect_generic_4stage(fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    run("A: Baseline B (FVG-12h+OB-4h+OB-1h+FVG-15m)", s_A)

    # B1. + SWEPT on L3 OB-1h
    s_B1 = detect_generic_4stage(fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, swept_l3_df=df_1h, allow_multi=ALLOW_MULTI)
    run("B1: B + SWEPT on L3 OB-1h", s_B1)

    # B2. + SWEPT on L2 OB-4h
    s_B2 = detect_generic_4stage(fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, swept_l2_df=df_4h, allow_multi=ALLOW_MULTI)
    run("B2: B + SWEPT on L2 OB-4h", s_B2)

    # C1. RDRB-4h на L2
    s_C1 = detect_generic_4stage(fvgs_12h, rdrbs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    run("C1: FVG-12h + RDRB-4h + OB-1h + FVG-15m", s_C1)

    # C2. RDRB-1h на L3
    s_C2 = detect_generic_4stage(fvgs_12h, obs_4h, rdrbs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    run("C2: FVG-12h + OB-4h + RDRB-1h + FVG-15m", s_C2)

    # C3. RDRB-12h на L1
    s_C3 = detect_generic_4stage(rdrbs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    run("C3: RDRB-12h + OB-4h + OB-1h + FVG-15m", s_C3)

    # D1. Fractal-4h на L2
    s_D1 = detect_generic_4stage(fvgs_12h, fractals_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    run("D1: FVG-12h + Fractal-4h + OB-1h + FVG-15m", s_D1)

    # D2. Fractal-1h на L3
    s_D2 = detect_generic_4stage(fvgs_12h, obs_4h, fractals_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    run("D2: FVG-12h + OB-4h + Fractal-1h + FVG-15m", s_D2)

    # E1. FVG-1h на L3
    s_E1 = detect_generic_4stage(fvgs_12h, obs_4h, fvgs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    run("E1: FVG-12h + OB-4h + FVG-1h + FVG-15m", s_E1)

    # E2. OB-15m на L4
    s_E2 = detect_generic_4stage(fvgs_12h, obs_4h, obs_1h, obs_15m, "12h", "4h", "1h", "15m", df_12h, allow_multi=ALLOW_MULTI)
    run("E2: FVG-12h + OB-4h + OB-1h + OB-15m", s_E2)

    # F1. B + Hull-6h trend filter
    run("F1: B + Hull-6h trend filter",
         s_A, extra_filter=lambda s: filter_hull_6h(s, df_6h, hull_6h_78))

    # F2. B + EMA-200(2h) filter
    run("F2: B + EMA-200(2h) filter",
         s_A, extra_filter=lambda s: filter_ema_2h(s, df_2h))

    # F3. B + Score-based filter
    run("F3: B + Score>0 at entry",
         s_A, extra_filter=lambda s: filter_score(s, score_long, score_short))

    # F4. B + Hull-6h + EMA OR (combined trend)
    run("F4: B + (Hull-6h OR EMA-2h)",
         s_A, extra_filter=lambda s: filter_hull_6h(s, df_6h, hull_6h_78) or filter_ema_2h(s, df_2h))

    # === Final ranking ===
    print()
    print("=" * 100)
    print("RANKED by PnL (with smoothness)")
    print("=" * 100)
    by_pnl = sorted(results, key=lambda r: r["pnl"], reverse=True)
    for r in by_pnl:
        marker = "★" if r["pnl"] > 40 and r["bad"] <= 1 else " "
        print(f"  {marker} {r['label']:<48}  PnL={r['pnl']:>+7.1f}R  WR={r['wr']:.1f}%  "
              f"closed={r['closed']:>3}  top5={r['top5_pct']:.1f}%  bad={r['bad']}/{r['n_yrs']}")


if __name__ == "__main__":
    main()
