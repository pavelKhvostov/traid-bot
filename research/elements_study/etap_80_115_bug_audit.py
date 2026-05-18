"""Этап 80: forensic bug audit стратегии 1.1.5 B5 strict + hull_1h_L49.

Проверки (как в etap_72 для 1.1.4):
  1. Sweep detection lookahead — детектор смотрит вперёд?
  2. Cascade window analog L1-invalidation — корректно ли ограничено окно?
  3. Hull filter — использует idx-1 (last closed bar)?
  4. Time consistency: signal_time < entry_time < exit_time
  5. SL geometry: sweep extreme buffer корректно
  6. RR consistency: все wins ровно +RR, losses -1
  7. Direction matching: все 4 уровня одного direction
  8. Sweep candle correctness: high > FH AND close < FH (rejection)
  9. Proximity ATR: правильный момент времени для ATR (на момент фрактала, не на момент OB)
  10. Multi-row signal_time — корреляция

Также проверяем доп. специфичные для фракталов:
  - First-touch rule: sweep — это ПЕРВАЯ касающаяся свеча после i+2?
  - ATR используется на момент confirm (i+2), не на момент sweep?
  - Cascade window не уходит за лимит данных?
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
    "etap76_core", str(_Path(__file__).parent / "etap_76_115_fractal_chains_survey.py"))
_e76 = importlib.util.module_from_spec(_spec76); _spec76.loader.exec_module(_e76)
_spec77 = importlib.util.spec_from_file_location(
    "etap77_core", str(_Path(__file__).parent / "etap_77_115_fractal_tightened.py"))
_e77 = importlib.util.module_from_spec(_spec77); _spec77.loader.exec_module(_e77)
_spec67 = importlib.util.spec_from_file_location(
    "etap67_core", str(_Path(__file__).parent / "etap_67_114_filter_grid_BF.py"))
_e67 = importlib.util.module_from_spec(_spec67); _spec67.loader.exec_module(_e67)
_e66 = _e76._e66

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR = 2.0


def audit_sweep_correctness(fractals, df_12h):
    """1. Проверка sweep detection: high > FH AND close < FH (для FH-rejection)."""
    print(f"\n{'='*80}\n1. SWEEP CORRECTNESS\n{'='*80}")
    print(f"  Всего fractals: {len(fractals)}")
    fh_count = sum(1 for f in fractals if f["kind"] == "FH")
    fl_count = sum(1 for f in fractals if f["kind"] == "FL")
    print(f"    FH: {fh_count}, FL: {fl_count}")

    errs = 0
    for fr in fractals:
        # Sweep candle = bar at fr['sweep_time']
        idx = df_12h.index.searchsorted(fr["sweep_time"], side="left")
        if idx >= len(df_12h):
            errs += 1; continue
        bar = df_12h.iloc[idx]
        if fr["kind"] == "FH":
            # Sweep must have high > FH price AND close < FH price (rejection)
            if not (bar["high"] > fr["level"] and bar["close"] < fr["level"]):
                errs += 1
        else:  # FL
            if not (bar["low"] < fr["level"] and bar["close"] > fr["level"]):
                errs += 1
    print(f"  Sweep candles failing high/close conditions: {errs}/{len(fractals)} (must be 0)")


def audit_first_touch(fractals, df_12h):
    """2. Sweep — первая касающаяся свеча? Не должно быть свечи между фракталом (i+2) и sweep_time, которая раньше касалась уровня."""
    print(f"\n{'='*80}\n2. FIRST-TOUCH RULE\n{'='*80}")

    errs = 0
    examples = []
    for fr in fractals:
        confirm_idx = df_12h.index.searchsorted(fr["confirm_time"], side="left") + 1
        sweep_idx = df_12h.index.searchsorted(fr["sweep_time"], side="left")
        if confirm_idx >= sweep_idx: continue
        # Check bars between confirm_idx and sweep_idx — none should touch the fractal level
        between = df_12h.iloc[confirm_idx:sweep_idx]
        if fr["kind"] == "FH":
            touched = (between["high"] > fr["level"]).any()
        else:
            touched = (between["low"] < fr["level"]).any()
        if touched:
            errs += 1
            if len(examples) < 3:
                examples.append((fr["sweep_time"], fr["kind"], fr["level"]))
    print(f"  Fractals where sweep wasn't first touch: {errs}/{len(fractals)} (must be 0)")
    for e in examples[:3]:
        print(f"    {e[0]} {e[1]} level={e[2]:.2f}")


def audit_cascade_window_clamp(setups):
    """3. Cascade window: signal_time (=L3_close) должен быть в окне после sweep_close."""
    print(f"\n{'='*80}\n3. CASCADE WINDOW (L3 within cascade_end?)\n{'='*80}")
    errs = 0
    examples = []
    for s in setups:
        sweep_time = s.get("sweep_time")
        if sweep_time is None: continue
        # Cascade window for 12h = 3 days from sweep_close
        # We need sweep_close, not sweep_time
        # Approximate: signal_time should be reasonably within 3-4 days from sweep_time
        delta = (s["signal_time"] - sweep_time).total_seconds() / 86400
        if delta > 5:  # more than 5 days = something wrong
            errs += 1
            if len(examples) < 3:
                examples.append((sweep_time, s["signal_time"], delta))
    print(f"  Setups with cascade > 5 days from sweep: {errs}/{len(setups)}")
    for e in examples[:3]:
        print(f"    sweep={e[0]} signal={e[1]} delta={e[2]:.1f}d")


def audit_lookahead_sweep_atr(fractals, df_12h):
    """4. ATR at confirm time (i+2), not at sweep time — is it correct?"""
    print(f"\n{'='*80}\n4. ATR LOOKAHEAD CHECK\n{'='*80}")
    print(f"  ATR используется на момент confirm_time (i+2). Проверяем что i+2 < sweep_time.")
    errs = 0
    for fr in fractals:
        if fr["confirm_time"] >= fr["sweep_time"]:
            errs += 1
    print(f"  Cases where confirm_time >= sweep_time: {errs}/{len(fractals)} (must be 0 by design)")


def audit_time_consistency(df):
    """5. signal_time < entry_time < exit_time."""
    print(f"\n{'='*80}\n5. TIME CONSISTENCY\n{'='*80}")
    df_c = df.copy()
    df_c["st"] = pd.to_datetime(df_c["signal_time"], errors="coerce", utc=True).dt.tz_localize(None)
    df_c["et"] = pd.to_datetime(df_c["entry_time"], errors="coerce", utc=True).dt.tz_localize(None)
    df_c["xt"] = pd.to_datetime(df_c["exit_time"], errors="coerce", utc=True).dt.tz_localize(None)

    has_entry = df_c[df_c["et"].notna()]
    pre_signal = has_entry[has_entry["et"] < has_entry["st"]]
    has_exit = df_c[df_c["xt"].notna()]
    pre_entry = has_exit[has_exit["xt"] < has_exit["et"]]
    print(f"  rows with entry_time: {len(has_entry)}")
    print(f"  entries BEFORE signal (LOOKAHEAD!): {len(pre_signal)}")
    print(f"  rows with exit_time: {len(has_exit)}")
    print(f"  exits BEFORE entry: {len(pre_entry)}")

    if len(has_entry):
        dur = (has_entry["et"] - has_entry["st"])
        print(f"  signal -> entry wait: mean={dur.mean()}, median={dur.median()}, max={dur.max()}")


def audit_sl_geometry(df):
    """6. SL geometry: sweep extreme buffer, RR consistency."""
    print(f"\n{'='*80}\n6. SL GEOMETRY + RR\n{'='*80}")
    valid = df[df["entry"].notna()]
    longs = valid[valid["direction"] == "LONG"]
    shorts = valid[valid["direction"] == "SHORT"]
    print(f"  LONG with sl >= entry: {(longs['sl'] >= longs['entry']).sum()} (BUG if > 0)")
    print(f"  SHORT with sl <= entry: {(shorts['sl'] <= shorts['entry']).sum()} (BUG if > 0)")

    rr_actual = abs(valid["tp"] - valid["entry"]) / abs(valid["entry"] - valid["sl"])
    print(f"  Actual RR: mean={rr_actual.mean():.3f}, min={rr_actual.min():.3f}, max={rr_actual.max():.3f}")
    rr_off = ((rr_actual - RR).abs() > 0.01).sum()
    print(f"  rows with |RR - {RR}| > 0.01: {rr_off}")

    risk_pct = (abs(valid["entry"] - valid["sl"]) / valid["entry"] * 100)
    print(f"  risk_pct: mean={risk_pct.mean():.2f}%, min={risk_pct.min():.2f}%, max={risk_pct.max():.2f}%")
    print(f"  rows with risk < 0.99% (MIN_SL fail?): {(risk_pct < 0.99).sum()}")

    # SL distance from sweep_extreme
    long_sl_below_sweep = longs[longs["sl"] < longs["sweep_extreme"]]
    print(f"  LONG SL < sweep_extreme: {len(long_sl_below_sweep)}/{len(longs)} (should be ~100%)")
    short_sl_above_sweep = shorts[shorts["sl"] > shorts["sweep_extreme"]]
    print(f"  SHORT SL > sweep_extreme: {len(short_sl_above_sweep)}/{len(shorts)} (should be ~100%)")


def audit_direction_matching(setups):
    """7. Direction match: fractal direction == setup direction."""
    print(f"\n{'='*80}\n7. DIRECTION MATCHING\n{'='*80}")
    errs = 0
    for s in setups:
        expected = "LONG" if s["fractal_kind"] == "FL" else "SHORT"
        if s["direction"] != expected:
            errs += 1
    print(f"  setups where direction != fractal_implied_direction: {errs}/{len(setups)} (must be 0)")


def audit_outcome_logic(df):
    """8. WIN R = +RR, LOSS R = -1."""
    print(f"\n{'='*80}\n8. OUTCOME LOGIC\n{'='*80}")
    wins = df[df["outcome"] == "win"]
    losses = df[df["outcome"] == "loss"]
    print(f"  WIN R distribution: min={wins['R'].min():.3f}, max={wins['R'].max():.3f}, mean={wins['R'].mean():.3f}")
    print(f"  expected WIN R = {RR}")
    odd_wins = wins[(wins["R"] - RR).abs() > 0.01]
    print(f"  WIN rows with R != {RR}: {len(odd_wins)}")
    odd_losses = losses[losses["R"] != -1.0]
    print(f"  LOSS rows with R != -1: {len(odd_losses)}")

    no_entry = df[df["outcome"] == "no_entry"]
    bad_ne = no_entry[no_entry["entry_time"].notna()]
    print(f"  no_entry with entry_time set: {len(bad_ne)} (BUG if > 0)")


def audit_hull_filter(setups, hulls):
    """9. Hull filter timing: idx-1 lookup."""
    print(f"\n{'='*80}\n9. HULL FILTER (idx-1 last closed bar?)\n{'='*80}")
    # Simulate: for each setup, what idx does safe_label_at return?
    sample = setups[:3]
    for s in sample:
        ts = s["signal_time"]
        ser = hulls["1h_L49"]
        # idx = searchsorted right-1
        idx = ser.index.searchsorted(ts, side="right") - 1
        if 0 <= idx < len(ser):
            actual_bar_time = ser.index[idx]
            delta_to_signal = (ts - actual_bar_time).total_seconds() / 60
            print(f"  signal={ts}, hull bar used={actual_bar_time}, delta={delta_to_signal:.0f}min before signal")


def audit_dedup(df):
    """10. Multi-row signal_time analysis."""
    print(f"\n{'='*80}\n10. DEDUP + MULTI-ROW PER SIGNAL_TIME\n{'='*80}")
    dup_keys = df.duplicated(subset=["signal_time", "direction", "fvg_b", "fvg_t"], keep=False)
    print(f"  rows with full-key duplicates (BUG): {dup_keys.sum()}")
    st_counts = df["signal_time"].value_counts()
    print(f"  signal_times with >1 row: {(st_counts > 1).sum()}")
    print(f"  max rows per signal_time: {st_counts.max()}")


def main():
    t0 = time.time()
    print("[INFO] load")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("4h", df_4h),
                    ("1h", df_1h), ("15m", df_15m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    print("[INFO] compute hulls")
    hulls = {}
    for tf, df, L in [("1h", df_1h, 49)]:
        h = _e67.hull_ma(df["close"], L)
        hulls[f"{tf}_L{L}"] = _e67.hull_label_series(df["close"], h)

    print("[INFO] detect")
    fractals_12h = _e76.collect_fractals_with_sweep(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")

    setups = _e77.detect_strict(fractals_12h, obs_4h, obs_1h, fvgs_15m,
                                  "12h", "4h", "1h", "15m",
                                  allow_multi=3, proximity_atr=1.0,
                                  min_sweep_depth_atr=0.0)
    print(f"  setups: {len(setups)}")

    # Run audits that don't need CSV
    audit_sweep_correctness(fractals_12h, df_12h)
    audit_first_touch(fractals_12h, df_12h)
    audit_cascade_window_clamp(setups)
    audit_lookahead_sweep_atr(fractals_12h, df_12h)
    audit_direction_matching(setups)
    audit_hull_filter(setups, hulls)

    # Build CSV for remaining audits
    print(f"\n[INFO] simulating for CSV-based audits...")
    rows = []
    for idx, s in enumerate(setups):
        tup = _e76.build_orders_fractal(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + RR * risk if s["direction"] == "LONG" else entry - RR * risk
        et64 = np.datetime64(s["signal_time"].tz_localize(None) if s["signal_time"].tz else s["signal_time"])
        end_time = s["signal_time"] + pd.Timedelta(days=7)
        ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
        i0 = np.searchsorted(df_1m.index.values, et64)
        i1 = np.searchsorted(df_1m.index.values, ee64)
        if i1 <= i0:
            rows.append({"idx": idx, "direction": s["direction"], "sweep_extreme": s["sweep_extreme"],
                          "fvg_b": s["fvg_b"], "fvg_t": s["fvg_t"], "entry": entry, "sl": sl, "tp": tp,
                          "outcome": "no_data", "R": 0.0, "signal_time": s["signal_time"],
                          "entry_time": None, "exit_time": None, "fractal_kind": s["fractal_kind"]})
            continue
        h = df_1m["high"].values[i0:i1].astype(np.float64)
        l = df_1m["low"].values[i0:i1].astype(np.float64)
        times = df_1m.index.values[i0:i1]
        if s["direction"] == "LONG":
            ent_mask = l <= entry; tp_pre_mask = h >= tp
        else:
            ent_mask = h >= entry; tp_pre_mask = l <= tp
        ent_idxs = np.where(ent_mask)[0]
        tp_pre_idxs = np.where(tp_pre_mask)[0]
        ent_idx = int(ent_idxs[0]) if ent_idxs.size else len(h) + 1
        tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else len(h) + 1
        outcome = "open"; R = 0.0; et = None; xt = None
        if tp_pre < ent_idx:
            outcome = "no_entry"
        elif ent_idx >= len(h):
            outcome = "not_filled"
        else:
            et = pd.Timestamp(times[ent_idx])
            post_h = h[ent_idx:]; post_l = l[ent_idx:]; post_t = times[ent_idx:]
            if s["direction"] == "LONG":
                sl_m = post_l <= sl; tp_m = post_h >= tp
            else:
                sl_m = post_h >= sl; tp_m = post_l <= tp
            sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
            tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
            if sl_first == -1 and tp_first == -1: outcome = "open"
            elif sl_first == -1: outcome = "win"; R = RR; xt = pd.Timestamp(post_t[tp_first])
            elif tp_first == -1: outcome = "loss"; R = -1.0; xt = pd.Timestamp(post_t[sl_first])
            elif tp_first < sl_first: outcome = "win"; R = RR; xt = pd.Timestamp(post_t[tp_first])
            else: outcome = "loss"; R = -1.0; xt = pd.Timestamp(post_t[sl_first])

        rows.append({"idx": idx, "direction": s["direction"], "sweep_extreme": s["sweep_extreme"],
                      "fvg_b": s["fvg_b"], "fvg_t": s["fvg_t"], "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R, "signal_time": s["signal_time"],
                      "entry_time": et, "exit_time": xt, "fractal_kind": s["fractal_kind"],
                      "year": s["year"]})

    df_csv = pd.DataFrame(rows)
    audit_time_consistency(df_csv)
    audit_sl_geometry(df_csv)
    audit_outcome_logic(df_csv)
    audit_dedup(df_csv)

    # Summary
    print(f"\n\n{'='*80}\nFINAL SUMMARY\n{'='*80}")
    closed = df_csv[df_csv["outcome"].isin(["win", "loss"])]
    if len(closed):
        wr = (closed["outcome"] == "win").mean() * 100
        tot = closed["R"].sum()
        bad = (closed.groupby("year")["R"].sum() < 0).sum()
        print(f"  n_total: {len(df_csv)}, closed: {len(closed)}")
        print(f"  WR: {wr:.1f}%, total: {tot:+.1f}R, bad: {bad}/{len(closed.groupby('year'))}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
