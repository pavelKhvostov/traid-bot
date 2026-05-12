"""Этап 71: CSV портфеля B+F+J+K (RR=2.0 no_dom, allow_multi=5).

Цель: полный список 167 позиций с деталями для ручной проверки.

Колонки:
  idx, chain (B/F/J/K), signal_time, year, direction,
  fvg_b, fvg_t, x1_b, x1_t, obh_b, obh_t,
  entry, sl, tp, risk_abs, risk_pct,
  outcome (win/loss/no_entry/not_filled/open),
  R, exit_time (если есть),
  daily_open (для do_match диагностики),
  do_match (would pass premium/discount filter)
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
_spec66 = importlib.util.spec_from_file_location(
    "etap66_core", str(_Path(__file__).parent / "etap_66_114_chains_survey.py")
)
_e66 = importlib.util.module_from_spec(_spec66)
_spec66.loader.exec_module(_e66)

_spec69 = importlib.util.spec_from_file_location(
    "etap69_core", str(_Path(__file__).parent / "etap_69_114_funnel_and_multi.py")
)
_e69 = importlib.util.module_from_spec(_spec69)
_spec69.loader.exec_module(_e69)

for mod in [_e66, _e69._e66]:
    mod.TF_HOURS["20m"] = 20/60
    mod.TF_HOURS["30m"] = 0.5
    mod.LIFE_DAYS["20m"] = 0.5
    mod.LIFE_DAYS["30m"] = 0.75

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ALLOW_MULTI = 5
RR = 2.0
OUTPUT_CSV = Path = _Path("research/elements_study/output/etap71_BFJK_portfolio.csv")


def simulate_with_times(s, entry, sl, tp, df_1m, max_hold_days=7):
    """Same as etap_66.simulate_safe but returns exit_time too."""
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
        ent_mask = l <= entry
        tp_pre_mask = h >= tp
    else:
        ent_mask = h >= entry
        tp_pre_mask = l <= tp
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
    if sl_first == -1:
        return ("win", abs(tp - entry) / risk, entry_time, pd.Timestamp(post_t[tp_first]))
    if tp_first == -1:
        return ("loss", -1.0, entry_time, pd.Timestamp(post_t[sl_first]))
    if tp_first < sl_first:
        return ("win", abs(tp - entry) / risk, entry_time, pd.Timestamp(post_t[tp_first]))
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

    print("[INFO] collect zones")
    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")

    print(f"[INFO] detect 4 chains with allow_multi={ALLOW_MULTI}")
    chain_defs = {
        "B": (fvgs_12h, obs_4h, obs_1h, fvgs_15m, "12h", "4h", "1h", "15m", df_12h),
        "F": (fvgs_1d, obs_6h, obs_2h, fvgs_15m, "1d", "6h", "2h", "15m", df_1d),
        "J": (fvgs_1d, obs_4h, obs_1h, fvgs_20m, "1d", "4h", "1h", "20m", df_1d),
        "K": (fvgs_12h, obs_4h, obs_1h, fvgs_20m, "12h", "4h", "1h", "20m", df_12h),
    }

    # Detect + tag chain source
    raw_setups = []
    for chain, args in chain_defs.items():
        setups, _ = _e69.detect_with_funnel(*args, allow_multi=ALLOW_MULTI)
        for s in setups:
            s["chain"] = chain
            raw_setups.append(s)
        print(f"  {chain}: {len(setups)} raw setups")

    # Dedup, but track which chains generated each setup
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

    # Build orders + simulate + extract features
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
                          "entry_time": None, "exit_time": None,
                          "daily_open": None, "do_match": None})
            continue
        entry, sl = tup
        risk = abs(entry - sl)
        risk_pct = risk / entry * 100
        tp = entry + RR * risk if s["direction"] == "LONG" else entry - RR * risk
        outcome, R, entry_time, exit_time = simulate_with_times(s, entry, sl, tp, df_1m)
        # daily open at signal_time
        idx_d = df_1d.index.searchsorted(s["signal_time"], side="right") - 1
        do = float(df_1d["open"].iloc[idx_d]) if idx_d >= 0 else None
        do_match = None
        if do is not None:
            if s["direction"] == "LONG": do_match = entry < do
            else: do_match = entry > do
        rows.append({"idx": idx,
                      "chain": "+".join(sorted(s["chains"])),
                      "signal_time": s["signal_time"],
                      "year": s["year"],
                      "direction": s["direction"],
                      "fvg_b": round(s["fvg_b"], 2), "fvg_t": round(s["fvg_t"], 2),
                      "x1_b": round(s["x1_bottom"], 2), "x1_t": round(s["x1_top"], 2),
                      "obh_b": round(s["obh_b"], 2), "obh_t": round(s["obh_t"], 2),
                      "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp, 2),
                      "risk_abs": round(risk, 2),
                      "risk_pct": round(risk_pct, 3),
                      "outcome": outcome,
                      "R": round(R, 3),
                      "entry_time": entry_time,
                      "exit_time": exit_time,
                      "daily_open": round(do, 2) if do else None,
                      "do_match": do_match})

    df_out = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[INFO] CSV saved: {OUTPUT_CSV}")

    # ===== Summary =====
    print(f"\n{'='*80}\nSUMMARY")
    print(f"{'='*80}")
    print(f"Total rows: {len(df_out)}")
    print(f"  outcome distribution:")
    for outc, n in df_out["outcome"].value_counts().items():
        pct = n / len(df_out) * 100
        print(f"    {outc:<22} {n:>4}  ({pct:5.1f}%)")

    closed = df_out[df_out["outcome"].isin(["win", "loss"])]
    print(f"\n  closed: {len(closed)}")
    wins = (closed["outcome"] == "win").sum()
    wr = wins / len(closed) * 100
    total_R = closed["R"].sum()
    avg_R = closed["R"].mean()
    print(f"  WR: {wr:.1f}% ({wins}/{len(closed)})")
    print(f"  total R: {total_R:+.2f}")
    print(f"  avg R per trade: {avg_R:+.3f}")

    # Year breakdown
    print(f"\n  Year-by-year (closed):")
    for yr in sorted(closed["year"].unique()):
        yc = closed[closed["year"] == yr]
        yw = (yc["outcome"] == "win").sum()
        ywr = yw / len(yc) * 100
        ytot = yc["R"].sum()
        print(f"    {yr}: n={len(yc):>3} wins={yw:>3} WR={ywr:5.1f}% total={ytot:+6.1f}R")

    # Chain-source breakdown
    print(f"\n  Chain-source breakdown (closed):")
    for cs in closed["chain"].value_counts().index[:15]:
        cc = closed[closed["chain"] == cs]
        ww = (cc["outcome"] == "win").sum()
        wwr = ww / len(cc) * 100
        ttt = cc["R"].sum()
        print(f"    {cs:<20} n={len(cc):>3} WR={wwr:5.1f}% total={ttt:+6.1f}R")

    # Direction breakdown
    print(f"\n  Direction breakdown (closed):")
    for d in ["LONG", "SHORT"]:
        dc = closed[closed["direction"] == d]
        if len(dc):
            dw = (dc["outcome"] == "win").sum()
            dwr = dw / len(dc) * 100
            dtot = dc["R"].sum()
            print(f"    {d:<6} n={len(dc):>3} WR={dwr:5.1f}% total={dtot:+6.1f}R")

    # do_match diagnostic
    print(f"\n  do_match diagnostic (closed):")
    for dm in [True, False]:
        dc = closed[closed["do_match"] == dm]
        if len(dc):
            dw = (dc["outcome"] == "win").sum()
            dwr = dw / len(dc) * 100
            dtot = dc["R"].sum()
            print(f"    do_match={dm}: n={len(dc):>3} WR={dwr:5.1f}% total={dtot:+6.1f}R")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
