"""Этап 74: Исправленный детектор BFJK с фильтрацией L3 против L1 invalidation.

Фикс bug #1 из etap_73:
  - L3 (OB-1h/2h) должен закрыться ДО L1 invalidation
  - Также L4 (FVG-15m) c2_time должно быть < L1_active_end

Сравнение:
  Old (etap_71): n=167 closed, WR 59.9%, +133R, avg +0.80R
  Expected new: n~148 closed, WR ~65%, +140R, avg ~+0.95R
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

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
ALLOW_MULTI = 5
RR = 2.0
OUTPUT_CSV = _Path("research/elements_study/output/etap74_BFJK_fixed_portfolio.csv")


def detect_fixed(fvgs_top, l2_zones, l3_zones, fvgs_entry,
                  top_tf, l2_tf, l3_tf, entry_tf, df_top, allow_multi):
    """4-stage cascade with L1 invalidation filter on L2, L3, AND L4."""
    top_td = pd.Timedelta(hours=_e66.TF_HOURS[top_tf])
    l2_td = pd.Timedelta(hours=_e66.TF_HOURS[l2_tf])
    l3_td = pd.Timedelta(hours=_e66.TF_HOURS[l3_tf])
    entry_td = pd.Timedelta(hours=_e66.TF_HOURS[entry_tf])
    top_life = pd.Timedelta(days=_e66.LIFE_DAYS[top_tf])
    l3_life = pd.Timedelta(days=_e66.LIFE_DAYS[l3_tf])

    l3_sorted = sorted(l3_zones, key=lambda x: x.get("prev_time", x.get("c0_time", x["time"])))
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["c0_time"])
    l3_start_times = np.array([np.datetime64(
        (z.get("prev_time", z.get("c0_time", z["time"]))).tz_localize(None)
        if (z.get("prev_time", z.get("c0_time", z["time"]))).tz else
        z.get("prev_time", z.get("c0_time", z["time"])))
        for z in l3_sorted])
    fvgs_entry_c0_times = np.array([np.datetime64(z["c0_time"].tz_localize(None) if z["c0_time"].tz else z["c0_time"])
                                      for z in fvgs_entry_sorted])

    setups = []
    for fvg_top in fvgs_top:
        L1_close = fvg_top["time"] + top_td
        L1_max_end = L1_close + top_life
        inval = _e66.find_invalidation(df_top, fvg_top, top_td, L1_max_end)
        L1_active_end = inval if inval is not None else L1_max_end

        n_for_l1 = 0
        for l2 in l2_zones:
            if l2["direction"] != fvg_top["direction"]: continue
            if not _e66.any_edge_inside(l2["bottom"], l2["top"], fvg_top["bottom"], fvg_top["top"]):
                continue
            l2_start = l2["prev_time"]
            l2_close = l2["time"] + l2_td
            if l2_start < fvg_top["c0_time"]: continue
            if l2_close > L1_active_end: continue

            l3_search_start = l2_close
            # Clip L3 window by L1 invalidation (FIX)
            l3_search_end = min(l3_search_start + l3_life, L1_active_end)

            j0 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_start.tz_localize(None) if l3_search_start.tz else l3_search_start), side="left")
            j1 = np.searchsorted(l3_start_times, np.datetime64(
                l3_search_end.tz_localize(None) if l3_search_end.tz else l3_search_end), side="right")

            for oj in range(j0, j1):
                l3 = l3_sorted[oj]
                if l3["direction"] != fvg_top["direction"]: continue
                if not _e66.any_edge_inside(l3["bottom"], l3["top"], fvg_top["bottom"], fvg_top["top"]): continue
                if not _e66.any_edge_inside(l3["bottom"], l3["top"], l2["bottom"], l2["top"]): continue

                L3_start = l3["prev_time"]
                L3_close = l3["time"] + l3_td
                # FIX: L3 must close before L1 dies
                if L3_close > L1_active_end: continue

                l4_max_c2_open = L3_close - entry_td

                k0 = np.searchsorted(fvgs_entry_c0_times, np.datetime64(
                    L3_start.tz_localize(None) if L3_start.tz else L3_start), side="left")
                f_e = None
                for ek in range(k0, len(fvgs_entry_sorted)):
                    f_entry = fvgs_entry_sorted[ek]
                    if f_entry["c0_time"] < L3_start: continue
                    if f_entry["time"] > l4_max_c2_open: continue
                    if f_entry["c0_time"] > L3_close: break
                    if f_entry["direction"] != fvg_top["direction"]: continue
                    # FIX: L4 c2 close must be before L1 dies
                    if (f_entry["time"] + entry_td) > L1_active_end: continue
                    if not _e66.zones_overlap(f_entry["bottom"], f_entry["top"],
                                                fvg_top["bottom"], fvg_top["top"]): continue
                    if not _e66.zones_overlap(f_entry["bottom"], f_entry["top"],
                                                l2["bottom"], l2["top"]): continue
                    f_e = f_entry; break
                if f_e is None: continue

                x1_b = max(fvg_top["bottom"], l2["bottom"])
                x1_t = min(fvg_top["top"], l2["top"])

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


def simulate_with_times(s, entry, sl, tp, df_1m, max_hold_days=7):
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0, None, None)
    start = s["signal_time"]
    end = start + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0, None, None)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    times = df_1m.index.values[i0:i1]

    if direction == "LONG":
        ent_mask = l <= entry; tp_pre_mask = h >= tp
    else:
        ent_mask = h >= entry; tp_pre_mask = l <= tp
    ent_idxs = np.where(ent_mask)[0]
    tp_pre_idxs = np.where(tp_pre_mask)[0]
    ent_idx = int(ent_idxs[0]) if ent_idxs.size else len(h) + 1
    tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else len(h) + 1
    if tp_pre < ent_idx: return ("no_entry", 0.0, None, None)
    if ent_idx >= len(h): return ("not_filled", 0.0, None, None)

    entry_time = pd.Timestamp(times[ent_idx])
    post_h = h[ent_idx:]; post_l = l[ent_idx:]
    post_t = times[ent_idx:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_first == -1 and tp_first == -1: return ("open", 0.0, entry_time, None)
    if sl_first == -1: return ("win", abs(tp - entry) / risk, entry_time, pd.Timestamp(post_t[tp_first]))
    if tp_first == -1: return ("loss", -1.0, entry_time, pd.Timestamp(post_t[sl_first]))
    if tp_first < sl_first: return ("win", abs(tp - entry) / risk, entry_time, pd.Timestamp(post_t[tp_first]))
    return ("loss", -1.0, entry_time, pd.Timestamp(post_t[sl_first]))


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

    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")

    chains = {
        "B": (fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h),
        "F": (fvgs_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m", df_1d),
        "J": (fvgs_1d, obs_4h, obs_1h, fvgs_20m, "1d", "4h", "1h", "20m", df_1d),
        "K": (fvgs_12h, obs_4h, obs_1h, fvgs_20m, "12h", "4h", "1h", "20m", df_12h),
    }

    print(f"\n[INFO] detect with FIX (allow_multi={ALLOW_MULTI})")
    raw_setups = []
    for name, args in chains.items():
        s = detect_fixed(*args, allow_multi=ALLOW_MULTI)
        for ss in s: ss["chain"] = name
        raw_setups.extend(s)
        print(f"  {name}: {len(s)} setups")

    # Dedup with chain attribution
    seen = {}
    for s in raw_setups:
        k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if k not in seen:
            seen[k] = {**s, "chains": [s["chain"]]}
        else:
            if s["chain"] not in seen[k]["chains"]:
                seen[k]["chains"].append(s["chain"])
    setups = list(seen.values())
    print(f"[INFO] after dedup: {len(setups)} unique")

    rows = []
    for idx, s in enumerate(sorted(setups, key=lambda x: x["signal_time"])):
        tup = _e66.build_orders(s)
        if tup is None:
            rows.append({"idx": idx, "chain": "+".join(s["chains"]),
                          "signal_time": s["signal_time"], "year": s["year"],
                          "direction": s["direction"],
                          "fvg_b": s["fvg_b"], "fvg_t": s["fvg_t"],
                          "x1_b": s["x1_bottom"], "x1_t": s["x1_top"],
                          "obh_b": s["obh_b"], "obh_t": s["obh_t"],
                          "entry": None, "sl": None, "tp": None,
                          "risk_abs": None, "risk_pct": None,
                          "outcome": "skip_invalid_order", "R": 0.0,
                          "entry_time": None, "exit_time": None})
            continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + RR * risk if s["direction"] == "LONG" else entry - RR * risk
        outcome, R, et, xt = simulate_with_times(s, entry, sl, tp, df_1m)
        rows.append({"idx": idx,
                      "chain": "+".join(sorted(s["chains"])),
                      "signal_time": s["signal_time"], "year": s["year"],
                      "direction": s["direction"],
                      "fvg_b": round(s["fvg_b"], 2), "fvg_t": round(s["fvg_t"], 2),
                      "x1_b": round(s["x1_bottom"], 2), "x1_t": round(s["x1_top"], 2),
                      "obh_b": round(s["obh_b"], 2), "obh_t": round(s["obh_t"], 2),
                      "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp, 2),
                      "risk_abs": round(risk, 2),
                      "risk_pct": round(risk/entry*100, 3),
                      "outcome": outcome, "R": round(R, 3),
                      "entry_time": et, "exit_time": xt})

    df_out = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[INFO] CSV saved: {OUTPUT_CSV}")

    # Summary
    print(f"\n{'='*80}\nFIXED STRATEGY SUMMARY")
    print(f"{'='*80}")
    print(f"Total rows: {len(df_out)}")
    print(f"  outcome distribution:")
    for outc, n in df_out["outcome"].value_counts().items():
        print(f"    {outc:<22} {n:>4}  ({n/len(df_out)*100:5.1f}%)")

    closed = df_out[df_out["outcome"].isin(["win", "loss"])]
    if len(closed):
        wins = (closed["outcome"] == "win").sum()
        wr = wins / len(closed) * 100
        tot = closed["R"].sum()
        avg = closed["R"].mean()
        print(f"\n  closed: {len(closed)}")
        print(f"  WR: {wr:.1f}% ({wins}/{len(closed)})")
        print(f"  total R: {tot:+.2f}")
        print(f"  avg R/trade: {avg:+.3f}")

        print(f"\n  Year-by-year:")
        for yr in sorted(closed["year"].unique()):
            yc = closed[closed["year"] == yr]
            yw = (yc["outcome"] == "win").sum()
            yr_wr = yw/len(yc)*100
            yr_tot = yc["R"].sum()
            print(f"    {yr}: n={len(yc):>3} WR={yr_wr:5.1f}% total={yr_tot:+6.1f}R")

        print(f"\n  Direction:")
        for d in ["LONG", "SHORT"]:
            dc = closed[closed["direction"] == d]
            if len(dc):
                dw = (dc["outcome"] == "win").sum()
                dwr = dw/len(dc)*100
                dtot = dc["R"].sum()
                print(f"    {d:<6} n={len(dc):>3} WR={dwr:5.1f}% total={dtot:+6.1f}R")

        print(f"\n  Chain source:")
        for cs in closed["chain"].value_counts().index[:10]:
            cc = closed[closed["chain"] == cs]
            cw = (cc["outcome"] == "win").sum()
            cwr = cw/len(cc)*100
            ctot = cc["R"].sum()
            print(f"    {cs:<10} n={len(cc):>3} WR={cwr:5.1f}% total={ctot:+6.1f}R")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
