"""Этап 78: финальный portfolio 1.1.5 с лучшими параметрами из etap_77.

Конфиг (из etap_77 PASS):
  AM=3, proximity_atr=1.0, min_sweep_depth_atr=0.0, RR=2.0, both directions

Тестируем 4 цепочки (B5/F5/J5/K5 — аналог 1.1.4 BFJK) + portfolio union.
CSV финального портфеля.
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
_spec76 = importlib.util.spec_from_file_location(
    "etap76_core", str(_Path(__file__).parent / "etap_76_115_fractal_chains_survey.py")
)
_e76 = importlib.util.module_from_spec(_spec76)
_spec76.loader.exec_module(_e76)
_spec77 = importlib.util.spec_from_file_location(
    "etap77_core", str(_Path(__file__).parent / "etap_77_115_fractal_tightened.py")
)
_e77 = importlib.util.module_from_spec(_spec77)
_spec77.loader.exec_module(_e77)
_e66 = _e76._e66

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ALLOW_MULTI = 3
PROXIMITY = 1.0
SWEEP_DEPTH = 0.0
RR = 2.0
OUTPUT_CSV = _Path("research/elements_study/output/etap78_BFJK5_fractal_portfolio.csv")


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
    post_h = h[ent_idx:]; post_l = l[ent_idx:]; post_t = times[ent_idx:]
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

    fractals_1d = _e76.collect_fractals_with_sweep(df_1d, df_1d["atr14"], "1d")
    fractals_12h = _e76.collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")

    chains = {
        "B5": (fractals_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m"),
        "F5": (fractals_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m"),
        "J5": (fractals_1d, obs_4h, obs_1h, fvgs_20m, "1d", "4h", "1h", "20m"),
        "K5": (fractals_12h, obs_4h, obs_1h, fvgs_20m, "12h", "4h", "1h", "20m"),
    }

    print(f"\n[INFO] detect with strict params (AM={ALLOW_MULTI}, prox={PROXIMITY}, depth={SWEEP_DEPTH})")
    raw_setups = []
    for name, args in chains.items():
        s = _e77.detect_strict(*args, allow_multi=ALLOW_MULTI,
                                 proximity_atr=PROXIMITY,
                                 min_sweep_depth_atr=SWEEP_DEPTH)
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

    # Build CSV
    rows = []
    for idx, s in enumerate(sorted(setups, key=lambda x: x["signal_time"])):
        tup = _e76.build_orders_fractal(s)
        if tup is None:
            continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + RR * risk if s["direction"] == "LONG" else entry - RR * risk
        outcome, R, et, xt = simulate_with_times(s, entry, sl, tp, df_1m)
        rows.append({"idx": idx,
                      "chain": "+".join(sorted(s["chains"])),
                      "signal_time": s["signal_time"],
                      "year": s["year"],
                      "direction": s["direction"],
                      "fractal_kind": s["fractal_kind"],
                      "sweep_extreme": round(s["sweep_extreme"], 2),
                      "fvg_b": round(s["fvg_b"], 2), "fvg_t": round(s["fvg_t"], 2),
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
    print(f"\n{'='*80}\nFRACTAL PORTFOLIO B5+F5+J5+K5 SUMMARY (allow_multi={ALLOW_MULTI}, RR={RR})")
    print(f"{'='*80}")
    print(f"Total rows: {len(df_out)}")
    for outc, n in df_out["outcome"].value_counts().items():
        print(f"  {outc:<22} {n:>4} ({n/len(df_out)*100:5.1f}%)")

    closed = df_out[df_out["outcome"].isin(["win", "loss"])]
    if len(closed):
        wins = (closed["outcome"] == "win").sum()
        wr = wins/len(closed)*100
        tot = closed["R"].sum()
        avg = closed["R"].mean()
        print(f"\n  closed: {len(closed)}")
        print(f"  WR: {wr:.1f}% ({wins}/{len(closed)})")
        print(f"  total R: {tot:+.2f}")
        print(f"  avg R/trade: {avg:+.3f}")
        print(f"  tpy: {len(closed)/6.3:.1f}")

        print(f"\n  Year-by-year:")
        for yr in sorted(closed["year"].unique()):
            yc = closed[closed["year"] == yr]
            yw = (yc["outcome"] == "win").sum()
            print(f"    {yr}: n={len(yc):>3} WR={yw/len(yc)*100:5.1f}% total={yc['R'].sum():+6.1f}R")

        print(f"\n  Direction:")
        for d in ["LONG", "SHORT"]:
            dc = closed[closed["direction"] == d]
            if len(dc):
                dw = (dc["outcome"] == "win").sum()
                print(f"    {d:<6} n={len(dc):>3} WR={dw/len(dc)*100:5.1f}% "
                      f"total={dc['R'].sum():+6.1f}R avg={dc['R'].mean():+5.2f}R")

        print(f"\n  Fractal kind:")
        for fk in ["FH", "FL"]:
            fc = closed[closed["fractal_kind"] == fk]
            if len(fc):
                fw = (fc["outcome"] == "win").sum()
                print(f"    {fk:<3} n={len(fc):>3} WR={fw/len(fc)*100:5.1f}% "
                      f"total={fc['R'].sum():+6.1f}R")

        print(f"\n  Chain source:")
        for cs in closed["chain"].value_counts().index[:10]:
            cc = closed[closed["chain"] == cs]
            cw = (cc["outcome"] == "win").sum()
            print(f"    {cs:<10} n={len(cc):>3} WR={cw/len(cc)*100:5.1f}% "
                  f"total={cc['R'].sum():+6.1f}R")

    # Compare with single chain B5
    print(f"\n--- Single-chain B5 vs Portfolio ---")
    b5_only = closed[closed["chain"].str.contains("B5")] if len(closed) else pd.DataFrame()
    print(f"  B5-related: n={len(b5_only)}")

    # Also evaluate LONG-only variant
    long_only = closed[closed["direction"] == "LONG"] if len(closed) else pd.DataFrame()
    if len(long_only):
        lw = (long_only["outcome"] == "win").sum()
        print(f"\n  LONG-only filter: n={len(long_only)} WR={lw/len(long_only)*100:.1f}% "
              f"total={long_only['R'].sum():+.1f}R avg={long_only['R'].mean():+.2f}R "
              f"tpy={len(long_only)/6.3:.1f}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
