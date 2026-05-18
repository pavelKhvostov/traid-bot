"""Этап 76: семейство стратегий 1.1.5 — FH/FL фрактал-d/12h как L1.

Структура каскада:
  L1: фрактал FH/FL на 1d или 12h (точка/уровень, не зона)
      └─ ждём sweep: первая свеча, чей high > FH (для SHORT) или low < FL (для LONG)
          с отклонением (close < FH / close > FL) = "failed breakout" / liquidity grab
  L2: OB-4h или OB-6h обратного направления, после sweep_close,
      в окне cascade_window, midpoint в 2×ATR от swept extreme
  L3: OB-1h или OB-2h обратного направления, после L2.close
  L4: FVG-15m или FVG-20m в синхронизации с L3 (c2 до L3 close)

SL = swept extreme (deepest low / highest high) с буфером.
Entry = 0.7 deep FVG, RR=2.0, min_sl=1%, allow_multi=5.

Применяется fix L1-invalidation (по аналогии с 1.1.4 etap_74):
  - L2_close ≤ cascade_window_end
  - L3_close ≤ cascade_window_end
  - L4 c2_close ≤ cascade_window_end

Те же критерии:
  - ≥ 26 сделок/год (1 раз в 1-2 недели)
  - WR > 45%
  - RR > 1.5
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "etap66_core", str(_Path(__file__).parent / "etap_66_114_chains_survey.py")
)
_e66 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_e66)

_e66.TF_HOURS["20m"] = 20/60
_e66.LIFE_DAYS["20m"] = 0.5

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
N_YEARS = 6.3

ENTRY_PCT = 0.70
USER_SL_LONG = 0.35
USER_SL_SHORT = 0.65
MIN_SL_PCT = 1.0
SWEEP_BUFFER_PCT = 0.1  # 0.1% буфер за swept extreme

# Cascade windows (после sweep_close — за сколько ищем каскад)
CASCADE_DAYS = {"1d": 5, "12h": 3}
MAX_SWEEP_BARS = {"1d": 10, "12h": 14}  # за сколько баров TF можно ожидать sweep

ATR_PROXIMITY = 3.0  # L2 midpoint в 3×ATR_TOP от swept extreme


def collect_fractals_with_sweep(df, atr, tf):
    """Bill Williams fractals + first-touch sweep with rejection.

    FH: high[i] > high[i±1], high[i±2] — strict 5-bar local max.
    Sweep: first j>i+2 such that high[j] > FH price.
      - если close[j] >= FH: фрактал пропущен (price broke through)
      - если close[j] < FH: успешный sweep (failed breakout / liquidity grab)
    Confirmed at i+2 (Bill Williams), но мы используем sweep_time как стартовую точку каскада.
    """
    tf_td = pd.Timedelta(hours=_e66.TF_HOURS[tf])
    max_sweep = MAX_SWEEP_BARS[tf]
    fractals = []
    n = len(df)
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    times = df.index

    for i in range(2, n - 2):
        h = highs[i]; l = lows[i]
        is_fh = (h > highs[i-2] and h > highs[i-1]
                  and h > highs[i+1] and h > highs[i+2])
        is_fl = (l < lows[i-2] and l < lows[i-1]
                  and l < lows[i+1] and l < lows[i+2])

        if is_fh:
            a = float(atr.iloc[i+2]) if not pd.isna(atr.iloc[i+2]) else 0
            if a <= 0: continue
            # Find sweep
            for j in range(i+3, min(n, i+3+max_sweep)):
                if highs[j] <= h: continue
                if closes[j] >= h:
                    break  # broke through, fractal missed
                # Sweep with rejection
                fractals.append({
                    "tf": tf, "kind": "FH", "direction": "SHORT",
                    "level": h, "atr": a,
                    "fractal_time": times[i],
                    "confirm_time": times[i+2],
                    "sweep_time": times[j],
                    "sweep_close_time": times[j] + tf_td,
                    "sweep_high": highs[j],
                    "sweep_close": closes[j],
                    "sweep_extreme": highs[j],
                })
                break

        if is_fl:
            a = float(atr.iloc[i+2]) if not pd.isna(atr.iloc[i+2]) else 0
            if a <= 0: continue
            for j in range(i+3, min(n, i+3+max_sweep)):
                if lows[j] >= l: continue
                if closes[j] <= l:
                    break
                fractals.append({
                    "tf": tf, "kind": "FL", "direction": "LONG",
                    "level": l, "atr": a,
                    "fractal_time": times[i],
                    "confirm_time": times[i+2],
                    "sweep_time": times[j],
                    "sweep_close_time": times[j] + tf_td,
                    "sweep_low": lows[j],
                    "sweep_close": closes[j],
                    "sweep_extreme": lows[j],
                })
                break

    return fractals


def detect_4stage_fractal(fractals, l2_zones, l3_zones, fvgs_entry,
                            top_tf, l2_tf, l3_tf, entry_tf,
                            allow_multi=5):
    """Каскад: фрактал+sweep → OB-L2 → OB-L3 → FVG-L4.
    SL anchor = swept extreme."""
    l2_td = pd.Timedelta(hours=_e66.TF_HOURS[l2_tf])
    l3_td = pd.Timedelta(hours=_e66.TF_HOURS[l3_tf])
    entry_td = pd.Timedelta(hours=_e66.TF_HOURS[entry_tf])
    cascade_window = pd.Timedelta(days=CASCADE_DAYS[top_tf])
    l3_life = pd.Timedelta(days=_e66.LIFE_DAYS[l3_tf])

    l3_sorted = sorted(l3_zones, key=lambda x: x.get("prev_time", x.get("c0_time", x["time"])))
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["c0_time"])
    l3_start_times = np.array([np.datetime64(
        z["prev_time"].tz_localize(None) if z["prev_time"].tz else z["prev_time"])
        for z in l3_sorted])
    fvgs_entry_c0_times = np.array([np.datetime64(
        z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
        for z in fvgs_entry_sorted])

    setups = []

    for fr in fractals:
        sweep_close = fr["sweep_close_time"]
        cascade_end = sweep_close + cascade_window
        sweep_ext = fr["sweep_extreme"]

        n_setups = 0
        for l2 in l2_zones:
            if l2["direction"] != fr["direction"]: continue
            l2_start = l2["prev_time"]
            l2_close = l2["time"] + l2_td
            if l2_start < sweep_close: continue
            if l2_close > cascade_end: continue
            # Proximity: L2 midpoint near sweep extreme
            l2_mid = (l2["bottom"] + l2["top"]) / 2
            if abs(l2_mid - sweep_ext) > ATR_PROXIMITY * fr["atr"]: continue

            l3_search_start = l2_close
            # Apply L1-invalidation fix: clamp by cascade_end
            l3_search_end = min(l3_search_start + l3_life, cascade_end)

            j0 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_start.tz_localize(None) if l3_search_start.tz else l3_search_start), side="left")
            j1 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_end.tz_localize(None) if l3_search_end.tz else l3_search_end), side="right")

            for oj in range(j0, j1):
                l3 = l3_sorted[oj]
                if l3["direction"] != fr["direction"]: continue

                L3_start = l3["prev_time"]
                L3_close = l3["time"] + l3_td
                # FIX: L3 should close within cascade window
                if L3_close > cascade_end: continue
                # L3 proximity to sweep
                l3_mid = (l3["bottom"] + l3["top"]) / 2
                if abs(l3_mid - sweep_ext) > ATR_PROXIMITY * fr["atr"]: continue

                l4_max_c2_open = L3_close - entry_td

                k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                    L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
                f_e = None
                for ek in range(k0, len(fvgs_entry_sorted)):
                    f_entry = fvgs_entry_sorted[ek]
                    if f_entry["c0_time"] < L3_start: continue
                    if f_entry["time"] > l4_max_c2_open: continue
                    if f_entry["c0_time"] > L3_close: break
                    if f_entry["direction"] != fr["direction"]: continue
                    # FIX: L4 c2 close within cascade window
                    if (f_entry["time"] + entry_td) > cascade_end: continue
                    f_e = f_entry; break

                if f_e is None: continue

                # SL anchor for fractal: swept extreme + buffer
                # For LONG: SL = swept_low - buffer
                # For SHORT: SL = swept_high + buffer
                setups.append({
                    "fvg_b": f_e["bottom"], "fvg_t": f_e["top"],
                    "obh_b": l3["bottom"], "obh_t": l3["top"],
                    "x1_bottom": sweep_ext,  # for compat with build_orders
                    "x1_top": sweep_ext,
                    "sweep_extreme": sweep_ext,
                    "tf_minutes": int(_e66.TF_HOURS[entry_tf] * 60),
                    "year": L3_close.year,
                    "direction": fr["direction"],
                    "signal_time": L3_close,
                    "fractal_kind": fr["kind"],
                    "fractal_level": fr["level"],
                    "sweep_time": fr["sweep_time"],
                    "atr": fr["atr"],
                })
                n_setups += 1
                if n_setups >= allow_multi: break
            if n_setups >= allow_multi: break

    return setups


def build_orders_fractal(s):
    """SL anchored to sweep extreme + buffer (overrides etap_66.build_orders)."""
    direction = s["direction"]
    fb, ft = s["fvg_b"], s["fvg_t"]
    sweep_ext = s["sweep_extreme"]

    if direction == "LONG":
        entry = fb + ENTRY_PCT * (ft - fb)
        # SL below sweep extreme with buffer
        sl_anchor = sweep_ext * (1 - SWEEP_BUFFER_PCT / 100)
        # Asymmetric: SL between sweep_ext_buffered and FVG bottom
        if sl_anchor < fb:
            sl = sl_anchor + USER_SL_LONG * (fb - sl_anchor)
        else:
            # Fallback: use OB-1h bottom
            obb = s["obh_b"]
            sl = obb + USER_SL_LONG * (fb - obb) if obb < fb else fb * (1 - MIN_SL_PCT/100)
        if MIN_SL_PCT > 0:
            sl = min(sl, entry - entry * MIN_SL_PCT / 100)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * (ft - fb)
        sl_anchor = sweep_ext * (1 + SWEEP_BUFFER_PCT / 100)
        if sl_anchor > ft:
            sl = sl_anchor - USER_SL_SHORT * (sl_anchor - ft)
        else:
            obt = s["obh_t"]
            sl = obt - USER_SL_SHORT * (obt - ft) if obt > ft else ft * (1 + MIN_SL_PCT/100)
        if MIN_SL_PCT > 0:
            sl = max(sl, entry + entry * MIN_SL_PCT / 100)
        if sl <= entry: return None
    return entry, sl


def evaluate(setups, rr, df_1m, df_1d, only_dom=False):
    rows = []
    for s in setups:
        tup = build_orders_fractal(s)
        if tup is None: continue
        entry, sl = tup
        if only_dom and not _e66.do_match_aligned(s, entry, df_1d): continue
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = _e66.simulate_safe(s, entry, sl, tp, df_1m)
        rows.append({"outcome": outcome, "R": R, "year": s["year"], "direction": s["direction"]})
    return pd.DataFrame(rows)


def metrics(df, n_years=N_YEARS):
    if df.empty or "outcome" not in df.columns: return None
    cl = df[df["outcome"].isin(["win", "loss"])]
    if cl.empty: return None
    nc = len(cl); wins = (cl["R"] > 0).sum()
    wr = wins/nc*100; tot = cl["R"].sum()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    return {"n": nc, "wr": wr, "total": tot, "bad": bad,
             "n_yrs": len(yr), "tpy": nc/n_years, "avg_R": tot/nc}


def dedup(setups):
    seen = set(); out = []
    for s in setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k in seen: continue
        seen.add(k); out.append(s)
    return out


def main():
    t0 = time.time()
    print("[INFO] load")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m), ("20m", df_20m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    print("[INFO] collect fractals + sweeps")
    fractals_1d = collect_fractals_with_sweep(df_1d, df_1d["atr14"], "1d")
    fractals_12h = collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    print(f"  fractals_1d: {len(fractals_1d)} (FH={sum(1 for f in fractals_1d if f['kind']=='FH')}, FL={sum(1 for f in fractals_1d if f['kind']=='FL')})")
    print(f"  fractals_12h: {len(fractals_12h)} (FH={sum(1 for f in fractals_12h if f['kind']=='FH')}, FL={sum(1 for f in fractals_12h if f['kind']=='FL')})")

    print("[INFO] collect OBs and FVGs")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")
    print(f"  OB-4h={len(obs_4h)}, OB-6h={len(obs_6h)}, OB-2h={len(obs_2h)}, OB-1h={len(obs_1h)}")
    print(f"  FVG-15m={len(fvgs_15m)}, FVG-20m={len(fvgs_20m)}")

    # Survey 8 chains
    chains = {
        "B5": ("12h", fractals_12h, obs_4h, obs_1h, fvgs_15m, "4h", "1h", "15m"),
        "A5": ("1d", fractals_1d, obs_4h, obs_1h, fvgs_15m, "4h", "1h", "15m"),
        "F5": ("1d", fractals_1d, obs_6h, obs_2h, fvgs_15m, "6h", "2h", "15m"),
        "K5": ("12h", fractals_12h, obs_4h, obs_1h, fvgs_20m, "4h", "1h", "20m"),
        "J5": ("1d", fractals_1d, obs_4h, obs_1h, fvgs_20m, "4h", "1h", "20m"),
        "L5": ("1d", fractals_1d, obs_6h, obs_2h, fvgs_20m, "6h", "2h", "20m"),
        "E5": ("1d", fractals_1d, obs_4h, obs_2h, fvgs_15m, "4h", "2h", "15m"),
        "I5": ("12h", fractals_12h, obs_4h, obs_2h, fvgs_15m, "4h", "2h", "15m"),
    }

    setups_by_chain = {}
    print(f"\n[INFO] detect 8 fractal-based chains, allow_multi=5")
    for name, (top_tf, frs, l2_z, l3_z, fvg_e, l2_tf, l3_tf, e_tf) in chains.items():
        s = detect_4stage_fractal(frs, l2_z, l3_z, fvg_e, top_tf, l2_tf, l3_tf, e_tf,
                                    allow_multi=5)
        setups_by_chain[name] = dedup(s)
        print(f"  {name} ({top_tf}/{l2_tf}/{l3_tf}/{e_tf}): {len(setups_by_chain[name])} setups")

    # Single-chain evaluation
    print(f"\n{'='*88}")
    print(f"SINGLE-CHAIN EVALUATION (RR>1.5, WR>45%, tpy>=26)")
    print(f"{'='*88}")
    print(f"  {'chain':<6} {'RR':<5} {'dom':<8} {'n':>4} {'tpy':>5} {'WR':>6} {'total':>8} {'avg':>7} {'bad':>5} {'pass':>5}")

    rows = []
    for name, setups in setups_by_chain.items():
        for rr in [1.8, 2.0, 2.5]:
            for dom in [False, True]:
                df = evaluate(setups, rr, df_1m, df_1d, only_dom=dom)
                m = metrics(df)
                if not m: continue
                passes = (m["tpy"] >= 26 and m["wr"] > 45 and rr > 1.5)
                rows.append({"chain": name, "rr": rr, "dom": dom, **m, "pass": passes})

    passing = [r for r in rows if r["pass"]]
    print(f"\n--- CHAINS PASSING ALL CRITERIA ---")
    if not passing:
        print("  (none — single chains insufficient as expected)")
    for r in sorted(passing, key=lambda x: x["total"], reverse=True):
        dom_lbl = "+dom" if r["dom"] else "no_dom"
        print(f"  {r['chain']:<6} RR={r['rr']:<3} {dom_lbl:<8} n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- TOP 12 by total R ---")
    by_total = sorted(rows, key=lambda x: x["total"], reverse=True)[:12]
    for r in by_total:
        dom_lbl = "+dom" if r["dom"] else "no_dom"
        mark = "PASS" if r["pass"] else " - "
        print(f"  {mark} {r['chain']:<6} RR={r['rr']:<3} {dom_lbl:<8} n={r['n']:>3} tpy={r['tpy']:5.1f} "
              f"WR={r['wr']:5.1f}% total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R bad={r['bad']}/{r['n_yrs']}")

    # Portfolio
    print(f"\n\n{'='*88}\nPORTFOLIO COMBINATIONS\n{'='*88}")
    def merge(*lst):
        all_s = []
        for L in lst: all_s.extend(L)
        return dedup(all_s)

    portfolios = {
        "B5+F5+J5+K5 (4-stage analog of 1.1.4 BFJK)":
            merge(setups_by_chain["B5"], setups_by_chain["F5"],
                  setups_by_chain["J5"], setups_by_chain["K5"]),
        "A5+B5+F5 (3 anchors)":
            merge(setups_by_chain["A5"], setups_by_chain["B5"], setups_by_chain["F5"]),
        "B5+K5 (12h anchor)":
            merge(setups_by_chain["B5"], setups_by_chain["K5"]),
        "All 8 chains":
            merge(*[setups_by_chain[c] for c in chains.keys()]),
    }

    portfolio_rows = []
    for pname, setups in portfolios.items():
        print(f"\n  {pname} (raw={len(setups)})")
        for rr in [1.8, 2.0, 2.5]:
            for dom in [False, True]:
                df = evaluate(setups, rr, df_1m, df_1d, only_dom=dom)
                m = metrics(df)
                if not m: continue
                passes = (m["tpy"] >= 26 and m["wr"] > 45 and rr > 1.5)
                if passes or m["tpy"] >= 15:
                    dom_lbl = "+dom" if dom else "no_dom"
                    mark = "PASS" if passes else " - "
                    print(f"    {mark} RR={rr:<3} {dom_lbl:<8} n={m['n']:>3} tpy={m['tpy']:5.1f} "
                          f"WR={m['wr']:5.1f}% total={m['total']:+6.1f}R avg={m['avg_R']:+5.2f}R "
                          f"bad={m['bad']}/{m['n_yrs']}")
                    portfolio_rows.append({"portfolio": pname, "rr": rr, "dom": dom,
                                            "pass": passes, **m})

    print(f"\n\n{'='*88}")
    print(f"FINAL: PORTFOLIOS PASSING ALL CRITERIA")
    print(f"{'='*88}")
    pp = sorted([r for r in portfolio_rows if r["pass"]],
                key=lambda x: x["total"], reverse=True)
    if not pp:
        print("  (none)")
    else:
        for r in pp:
            dom_lbl = "+dom" if r["dom"] else "no_dom"
            print(f"  {r['portfolio'][:48]:<48} RR={r['rr']:<3} {dom_lbl:<8} "
                  f"n={r['n']:>3} tpy={r['tpy']:5.1f} WR={r['wr']:5.1f}% "
                  f"total={r['total']:+6.1f}R avg={r['avg_R']:+5.2f}R bad={r['bad']}/{r['n_yrs']}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
