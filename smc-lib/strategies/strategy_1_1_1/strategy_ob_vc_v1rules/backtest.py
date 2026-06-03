"""Backtest ob_vc(1h+2h) BTC 6y с правилами etap108 разработчика.

7 правил из strategy_1_1_1_floating.py (без SWEPT, confluence, cascade):

1. Entry  = fvg.bottom + 0.80 * fvg_width                   [LONG]
2. SL     = ob.bottom + 0.35 * (fvg.bottom - ob.bottom)     symmetric
3. Exit#1: SL hit                  → R = -1
4. Exit#2: R-cap (BTC=4.5)         → R = +R_cap
5. Exit#3: Floating TP (4-ind score ≤ -0.25, confirm=2)
6. Exit#4: Max-hold 7d             → mark-to-market
7. No-entry filter (TP_proxy reached before entry → cancel)

ob_vc canon:
  HTF=1h: LTF ∈ {15m, 20m}
  HTF=2h: LTF ∈ {15m, 20m}
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path.home() / "smc-lib"
TRAID_BOT = Path.home() / "traid-bot"
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "projects"))
sys.path.insert(0, str(SMC_LIB / "strategies" / "strategy_1_1_1"))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))
sys.path.insert(0, str(TRAID_BOT))   # strategy_1_1_1_floating imports strategies.*

from candle import Candle
from elements.ob.code import detect_ob
from elements.fvg.code import detect_fvg
from elements.ob_vc.code import detect_ob_vc, HTF_TO_LTF
from data import load_btc_1m
from resample import resample_one
from strategy_1_1_1_floating import (
    build_score_series, simulate_floating, FLOATING_TP_CONFIG,
)


TFS = ("15m", "20m", "1h", "2h")
HTFS = ("1h", "2h")


def df_to_candles(df: pd.DataFrame) -> list[Candle]:
    return [
        Candle(
            open=float(o), high=float(h), low=float(lo), close=float(c),
            open_time=int(ts.value // 1_000_000),
        )
        for ts, o, h, lo, c in zip(
            df.index, df["open"], df["high"], df["low"], df["close"],
        )
    ]


def find_fvgs(candles: list[Candle]) -> list:
    fvgs = []
    for i in range(2, len(candles)):
        f = detect_fvg(candles[i - 2], candles[i - 1], candles[i])
        if f is not None:
            fvgs.append(f)
    return fvgs


def scan_ob_vc_events(resampled: dict, df_1m: pd.DataFrame, htf: str) -> list[dict]:
    """Скан ob_vc на одном HTF. Возвращает sig-dicts для simulate_floating."""
    allowed_ltfs = HTF_TO_LTF.get(htf, ())
    if not allowed_ltfs:
        return []
    df_htf = resampled[htf]
    ltf_candles = {ltf: df_to_candles(resampled[ltf]) for ltf in allowed_ltfs if ltf in resampled}
    ltf_fvgs = {ltf: find_fvgs(ltf_candles[ltf]) for ltf in ltf_candles}

    events: list[dict] = []
    seen_keys: set = set()

    n_ob = 0
    n_obvc = 0
    n_with_fvg = 0

    for i in range(1, len(df_htf)):
        prev_row = df_htf.iloc[i - 1]
        cur_row = df_htf.iloc[i]
        prev_c = Candle(
            open=float(prev_row["open"]), high=float(prev_row["high"]),
            low=float(prev_row["low"]), close=float(prev_row["close"]),
            open_time=int(df_htf.index[i - 1].value // 1_000_000),
        )
        cur_c = Candle(
            open=float(cur_row["open"]), high=float(cur_row["high"]),
            low=float(cur_row["low"]), close=float(cur_row["close"]),
            open_time=int(df_htf.index[i].value // 1_000_000),
        )
        ob = detect_ob(prev_c, cur_c)
        if ob is None:
            continue
        n_ob += 1
        ob_cur_ms = cur_c.open_time
        ltf_bars_after = {
            ltf: [c for c in ltf_candles[ltf] if (c.open_time or 0) >= ob_cur_ms]
            for ltf in ltf_candles
        }
        ob_vc = detect_ob_vc(
            ob, htf=htf,
            ltf_bars_after_ob=ltf_bars_after,
            ltf_fvgs=ltf_fvgs,
            n_fractal=2,
            df_1m=df_1m,
        )
        if ob_vc is None:
            continue
        n_obvc += 1
        if not ob_vc.fvg_components:
            continue
        n_with_fvg += 1

        # FIRST fvg by c2.open_time = момент VC подтверждения
        first_fvg_ltf, first_fvg = min(
            ob_vc.fvg_components,
            key=lambda kv: kv[1].c2.open_time or 0,
        )
        signal_time = pd.Timestamp(first_fvg.c2.open_time, unit="ms", tz="UTC")

        key = (htf, ob_cur_ms, ob_vc.direction)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        # Strict lookahead-safe detection time (canon ob_vc):
        # Earliest moment we can SAY "это ob_vc" using only closed bars
        #   = max(cur_HTF.close, c3.close, opposite_fractal_n2_confirm.close)
        htf_minutes = {"1h": 60, "2h": 120, "4h": 240, "6h": 360,
                       "8h": 480, "12h": 720, "1d": 1440}.get(htf, 60)
        ob_cur_close_ts = pd.Timestamp(ob_cur_ms, unit="ms", tz="UTC") + pd.Timedelta(minutes=htf_minutes)
        ltf_minutes = 15 if first_fvg_ltf == "15m" else 20
        c3_close_ts = signal_time + pd.Timedelta(minutes=2 * ltf_minutes)

        # Find opposite-fractal Williams n=2 confirm time on LTF.
        # opposite_fractal_level — найдём bar in any LTF candle list whose low/high == level
        # confirm_ts = pivot.open + 3 * ltf_minutes (n=2 = 2 bars right close)
        opp_level = ob_vc.first_opposite_fractal_level
        is_short = (ob_vc.direction == "short")
        fractal_confirm_ts = None
        for ltf_name in ("15m", "20m"):
            if ltf_name not in ltf_candles:
                continue
            ltf_min = 15 if ltf_name == "15m" else 20
            for c in ltf_candles[ltf_name]:
                # For SHORT ob_vc: opposite FL with this low
                # For LONG: opposite FH with this high
                target_attr = c.low if is_short else c.high
                if abs(target_attr - opp_level) < 0.01 and c.open_time is not None:
                    pivot_open = pd.Timestamp(c.open_time, unit="ms", tz="UTC")
                    candidate_confirm = pivot_open + pd.Timedelta(minutes=3 * ltf_min)
                    if fractal_confirm_ts is None or candidate_confirm < fractal_confirm_ts:
                        fractal_confirm_ts = candidate_confirm
                    break

        strict_detection_ts = max(filter(None, [ob_cur_close_ts, c3_close_ts, fractal_confirm_ts]))

        events.append({
            "direction": ob_vc.direction.upper(),
            "ob_htf_zone": (ob.zone[0], ob.zone[1]),
            "ob_htf_tf": htf,
            "fvg_zone": (first_fvg.zone[0], first_fvg.zone[1]),
            "fvg_tf": first_fvg_ltf,
            "signal_time": signal_time,
            "ob_cur_time": pd.Timestamp(ob_cur_ms, unit="ms", tz="UTC"),
            # Strict lookahead-safe additions:
            "ob_cur_close_ts": ob_cur_close_ts,
            "c3_close_ts": c3_close_ts,
            "fractal_confirm_ts": fractal_confirm_ts,
            "strict_detection_ts": strict_detection_ts,
            # Multi-FVG info (fix to n_fvg_components bug):
            "n_fvg_components": len(ob_vc.fvg_components),
            "fvg_components_LTFs": [ltf for ltf, _ in ob_vc.fvg_components],
        })

    print(f"  htf={htf}: OB={n_ob}, ob_vc={n_obvc}, with_fvg={n_with_fvg}, unique events={len(events)}")
    return events


def print_stats(df: pd.DataFrame, label: str):
    if df.empty:
        print(f"  [{label}] n=0")
        return
    closed = df[df["outcome"].isin(["win", "loss", "flat"])]
    if closed.empty:
        print(f"  [{label}] n={len(df)} but no closed trades")
        return
    n = len(closed)
    wins = (closed["R"] > 0).sum()
    losses = (closed["R"] < 0).sum()
    flats = (closed["R"] == 0).sum()
    total_R = closed["R"].sum()
    med_R = closed["R"].median()
    mean_R = closed["R"].mean()
    wr = wins / n * 100
    exits = df["exit_reason"].value_counts().head(6).to_dict()
    print(f"  [{label}] n={n}  WR={wr:.1f}%  total_R={total_R:+.1f}  R/tr_mean={mean_R:+.2f}  median_R={med_R:+.2f}")
    print(f"    breakdown: wins={wins} losses={losses} flats={flats}  exits={exits}")


def main():
    t0 = time.time()
    print("[bt] loading 1m BTC...")
    df_1m = load_btc_1m()
    print(f"  {len(df_1m):,} bars, {df_1m.index[0]} -> {df_1m.index[-1]}")

    end_ts = df_1m.index[-1] + pd.Timedelta(minutes=1)
    print("[bt] resampling 4 TFs...")
    t1 = time.time()
    resampled = {tf: resample_one(df_1m, tf, end_ts) for tf in TFS}
    print(f"  done in {time.time()-t1:.1f}s")

    print("[bt] building 4-indicator score series on 1h...")
    t1 = time.time()
    score_long, score_short = build_score_series(resampled["1h"])
    print(f"  done in {time.time()-t1:.1f}s")

    all_events = []
    for htf in HTFS:
        print(f"[bt] scanning ob_vc HTF={htf}...")
        t1 = time.time()
        events = scan_ob_vc_events(resampled, df_1m, htf)
        all_events.extend(events)
        print(f"  scan done in {time.time()-t1:.1f}s, total events on htf={htf}: {len(events)}")
    print(f"\n[bt] grand total: {len(all_events)} ob_vc events to simulate\n")

    cfg = FLOATING_TP_CONFIG["BTCUSDT"]
    print(f"[bt] simulating with BTCUSDT config: {cfg}\n")

    trades = []
    t1 = time.time()
    for i, sig in enumerate(all_events):
        result = simulate_floating(
            sig, df_1m, resampled["1h"], score_long, score_short,
            R_cap=cfg["R_cap"],
            threshold=cfg["threshold"],
            confirm=cfg["confirm"],
        )
        if result is None:
            continue
        trades.append({
            "signal_time": sig["signal_time"],
            "direction": sig["direction"],
            "htf": sig["ob_htf_tf"],
            "ltf": sig["fvg_tf"],
            "outcome": result.outcome,
            "R": result.R,
            "exit_reason": result.exit_reason,
            "hold_h": result.hold_h,
            "max_R": result.max_R,
        })
        if (i + 1) % 500 == 0:
            print(f"  [progress] {i+1}/{len(all_events)} processed, {len(trades)} valid so far")
    print(f"[bt] simulation done in {(time.time()-t1)/60:.1f} min")

    trades_df = pd.DataFrame(trades)
    out_dir = SMC_LIB / "strategies" / "strategy_1_1_1" / "strategy_ob_vc_v1rules"
    out_csv = out_dir / "trades.csv"
    trades_df.to_csv(out_csv, index=False)
    print(f"\n[bt] saved {len(trades_df)} trades to {out_csv}\n")

    print("=" * 70)
    print("AGGREGATE STATS")
    print("=" * 70)
    print_stats(trades_df, "ALL")
    for htf in HTFS:
        sub = trades_df[trades_df["htf"] == htf]
        print_stats(sub, f"htf={htf}")
    for direction in ("LONG", "SHORT"):
        sub = trades_df[trades_df["direction"] == direction]
        print_stats(sub, f"{direction}")
    for htf in HTFS:
        for direction in ("LONG", "SHORT"):
            sub = trades_df[(trades_df["htf"] == htf) & (trades_df["direction"] == direction)]
            print_stats(sub, f"{direction} htf={htf}")

    # By-year breakdown — критерий #1 (стабильность по годам)
    if not trades_df.empty:
        closed = trades_df[trades_df["outcome"].isin(["win", "loss", "flat"])].copy()
        if not closed.empty:
            closed["year"] = pd.to_datetime(closed["signal_time"]).dt.year
            print("\n" + "=" * 70)
            print("BY YEAR (criterion #1: zero bad years)")
            print("=" * 70)
            for year, g in closed.groupby("year"):
                wr = (g["R"] > 0).sum() / len(g) * 100
                print(f"  {year}: n={len(g)}  WR={wr:.1f}%  total_R={g['R'].sum():+.1f}  median_R={g['R'].median():+.2f}")

    print(f"\n[bt] TOTAL elapsed: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
