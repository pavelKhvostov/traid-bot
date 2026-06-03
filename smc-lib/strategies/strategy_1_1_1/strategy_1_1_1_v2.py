"""Strategy 1.1.1 V2 — nested ob_vc cascade + Floating TP (etap108 reuse).

V2 vs v1:
  v1 macro:  OB-{1d,12h} ∩ FVG-{4h,6h}    (ad-hoc geometric overlap)
  v1 entry:  OB-{1h,2h} ∩ FVG-{15m,20m}   (+ SWEPT)
  ───────────────────────────────────────────────────────────────────
  V2 macro:  ob_vc(HTF=D/12h, LTF=4h/6h)     ← canon 9 conditions
  V2 entry:  ob_vc(HTF=1h/2h, LTF=15m/20m)   (+ SWEPT как v1)

  + те же confluence + Floating TP (импортируется из strategy_1_1_1_floating.py).

Hypothesis: canon ob_vc отбирает blocks строже (sonaprav, spatial overlap,
temporal bounds, FVG actionable) → меньше signals, выше WR / R/trade.

См. ~/smc-lib/projects/strategy-1-1-1-v2.md (spec).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path.home() / "smc-lib"
sys.path.insert(0, str(SMC_LIB))
# Для импорта strategies.* (использует strategy_1_1_1_floating)
sys.path.insert(0, str(Path.home() / "traid-bot"))

from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob, OB  # noqa: E402
from elements.fvg.code import detect_fvg, FVG  # noqa: E402
from elements.ob_vc.code import detect_ob_vc, OBVC, HTF_TO_LTF  # noqa: E402


# Импортируем готовые куски из reference impl разработчика
sys.path.insert(0, str(SMC_LIB / "strategies" / "strategy_1_1_1"))
from strategy_1_1_1_floating import (  # noqa: E402
    check_swept, build_score_series, simulate_floating, aggregate_stats,
    FLOATING_TP_CONFIG,
)


# ============================================================
# Helpers
# ============================================================

def df_to_candles(df: pd.DataFrame) -> list[Candle]:
    """pandas df → list[Candle] для использования в ob_vc/ob/fvg детекторах."""
    return [
        Candle(
            open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close),
            open_time=int(df.index[i].value // 1_000_000),
        )
        for i, r in enumerate(df.itertuples())
    ]


def zones_overlap(lo1: float, hi1: float, lo2: float, hi2: float) -> bool:
    return max(lo1, lo2) <= min(hi1, hi2)


# ============================================================
# Расширенный scanner: возвращает full data (ob_zone + fvg + times)
# ============================================================

def scan_obvc_full(
    resampled: dict[str, pd.DataFrame],
    df_1m: pd.DataFrame,
    htf_to_ltf: dict[str, tuple[str, ...]],
    n_fractal: int = 2,
) -> list[dict]:
    """Скан ob_vc по заданному htf_to_ltf mapping. Возвращает list[event] с full data.

    Each event dict:
        direction: "long" | "short"
        htf: str (TF-строка)
        ob_prev_time, ob_cur_time: pd.Timestamp (UTC) — для SWEPT и signal meta
        ob_zone: (lo, hi) — full ZoI per OB canon (= ob.zone)
        fvg_zone: (lo, hi) — первая (earliest) валидирующая FVG из ob_vc.fvg_components
        fvg_tf: str — LTF-строка FVG
        fvg_c1_time, fvg_c3_time: pd.Timestamp — для temporal проверок
    """
    events: list[dict] = []
    for htf, allowed_ltfs in htf_to_ltf.items():
        df_htf = resampled.get(htf)
        if df_htf is None or df_htf.empty:
            continue

        # Подготовка LTF данных
        ltf_all_candles: dict[str, list[Candle]] = {}
        ltf_all_fvgs: dict[str, list[FVG]] = {}
        for ltf in allowed_ltfs:
            df_ltf = resampled.get(ltf)
            if df_ltf is None or df_ltf.empty:
                continue
            ltf_all_candles[ltf] = df_to_candles(df_ltf)
            cs = ltf_all_candles[ltf]
            ltf_all_fvgs[ltf] = [
                f for f in (detect_fvg(cs[i - 2], cs[i - 1], cs[i]) for i in range(2, len(cs)))
                if f is not None
            ]
        if not ltf_all_candles:
            continue

        # Итерация по OB парам в HTF
        for i in range(1, len(df_htf)):
            prev_c = Candle(
                open=float(df_htf.iloc[i - 1]["open"]),
                high=float(df_htf.iloc[i - 1]["high"]),
                low=float(df_htf.iloc[i - 1]["low"]),
                close=float(df_htf.iloc[i - 1]["close"]),
                open_time=int(df_htf.index[i - 1].value // 1_000_000),
            )
            cur_c = Candle(
                open=float(df_htf.iloc[i]["open"]),
                high=float(df_htf.iloc[i]["high"]),
                low=float(df_htf.iloc[i]["low"]),
                close=float(df_htf.iloc[i]["close"]),
                open_time=int(df_htf.index[i].value // 1_000_000),
            )
            ob = detect_ob(prev_c, cur_c)
            if ob is None:
                continue

            ob_cur_ms = cur_c.open_time or 0
            # LTF bars начиная с открытия OB cur
            ltf_bars_after = {
                ltf: [c for c in ltf_all_candles[ltf] if (c.open_time or 0) >= ob_cur_ms]
                for ltf in ltf_all_candles
            }

            ob_vc = detect_ob_vc(
                ob, htf=htf, ltf_bars_after_ob=ltf_bars_after,
                ltf_fvgs=ltf_all_fvgs, n_fractal=n_fractal, df_1m=df_1m,
            )
            if ob_vc is None or not ob_vc.fvg_components:
                continue

            # Берём earliest FVG component (= наиболее ранний trigger)
            earliest_ltf, earliest_fvg = min(
                ob_vc.fvg_components,
                key=lambda x: x[1].c3.open_time or 0,
            )

            events.append({
                "direction": ob_vc.direction,
                "htf": htf,
                "ob_prev_time": pd.Timestamp(prev_c.open_time, unit="ms", tz="UTC"),
                "ob_cur_time":  pd.Timestamp(cur_c.open_time,  unit="ms", tz="UTC"),
                "ob_zone": ob.zone,            # (lo, hi) — full OB ZoI
                "fvg_zone": earliest_fvg.zone, # (lo, hi)
                "fvg_tf": earliest_ltf,
                "fvg_c1_time": pd.Timestamp(earliest_fvg.c1.open_time, unit="ms", tz="UTC"),
                "fvg_c3_time": pd.Timestamp(earliest_fvg.c3.open_time, unit="ms", tz="UTC"),
            })
    return events


# ============================================================
# V2 CASCADE: macro_obvc → entry_obvc внутри macro_zone
# ============================================================

def _fractal_invalidation_time(
    df_htf: pd.DataFrame,
    search_start: pd.Timestamp,
    direction: str,
    fvg_bottom: float,
    fvg_top: float,
) -> pd.Timestamp | None:
    """Найти время первого Williams 5-bar фрактала ВНЕ macro FVG.zone (= invalidation).

    LONG: ищем LL-фрактал с low < fvg_bottom (макрозона снизу пробита).
    SHORT: ищем HH-фрактал с high > fvg_top (макрозона сверху пробита).

    Возвращает confirmation time (= i+2 bar, когда фрактал подтвердился).
    """
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 5:
        return None
    highs = df_window["high"].values.astype(float)
    lows = df_window["low"].values.astype(float)
    for i in range(4, n):
        j = i - 2  # центр потенциального фрактала
        if direction.lower() == "long":
            is_ll = (
                lows[j] < lows[j - 2] and lows[j] < lows[j - 1]
                and lows[j] < lows[j + 1] and lows[j] < lows[j + 2]
            )
            if is_ll and lows[j] < fvg_bottom:
                return df_window.index[i]  # confirmation на i-м баре
        else:
            is_hh = (
                highs[j] > highs[j - 2] and highs[j] > highs[j - 1]
                and highs[j] > highs[j + 1] and highs[j] > highs[j + 2]
            )
            if is_hh and highs[j] > fvg_top:
                return df_window.index[i]
    return None


def detect_signals_v2(
    resampled: dict[str, pd.DataFrame],
    df_1m: pd.DataFrame,
) -> list[dict]:
    """Cascade: macro ob_vc (D/12h, LTF 4h/6h) → entry ob_vc (1h/2h, LTF 15m/20m).

    Логика (соответствует v1 разработчика):
      1. macro формируется в момент M.ob_cur_time
      2. search_start = M.ob_cur_time + HTF_duration (сразу после закрытия macro-cur bar)
      3. invalidation = first Williams 5-fractal внутри macro.FVG.zone (LL ниже / HH выше)
      4. Окно поиска entry = [search_start, invalidation]  (open-ended если нет invalidation)
      5. Entry: ob_vc(1h/2h + 15m/20m) с:
            - direction == macro.direction
            - entry.ob_cur_time ∈ window
            - entry.ob_zone overlap macro.ob_zone (внутри ZoI верхнего ob_vc)
    """
    macro_map = {"1d": ("4h", "6h"), "12h": ("4h", "6h")}
    entry_map = {"1h": ("15m", "20m"), "2h": ("15m", "20m")}

    macros = scan_obvc_full(resampled, df_1m, macro_map)
    entries = scan_obvc_full(resampled, df_1m, entry_map)

    htf_hours = {"1d": 24, "12h": 12}

    signals: list[dict] = []
    for macro in macros:
        macro_htf_hours = htf_hours[macro["htf"]]
        search_start = macro["ob_cur_time"] + pd.Timedelta(hours=macro_htf_hours)

        # invalidation для этой macro — ищем на её же HTF (= 1d или 12h)
        df_htf_for_invalid = resampled[macro["htf"]]
        invalidation_ts = _fractal_invalidation_time(
            df_htf_for_invalid, search_start,
            macro["direction"],
            macro["ob_zone"][0],   # используем границы OB-зоны (= macro ob_vc.zone)
            macro["ob_zone"][1],
        )

        for entry in entries:
            if entry["direction"] != macro["direction"]:
                continue
            # entry должен быть в окне [search_start, invalidation]
            if entry["ob_cur_time"] < search_start:
                continue
            if invalidation_ts is not None and entry["ob_cur_time"] > invalidation_ts:
                continue
            # entry внутри macro.ob_zone (spatial constraint)
            if not zones_overlap(*entry["ob_zone"], *macro["ob_zone"]):
                continue

            direction_upper = entry["direction"].upper()
            signals.append({
                "direction": direction_upper,
                "signal_time": entry["fvg_c3_time"],
                "top_tf": macro["htf"],
                "ob_d_cur_time": macro["ob_cur_time"],
                "ob_d_zone": macro["ob_zone"],
                "fvg_macro_tf": macro["fvg_tf"],
                "fvg_macro_zone": macro["fvg_zone"],
                "ob_htf_tf": entry["htf"],
                "ob_htf_prev_time": entry["ob_prev_time"],
                "ob_htf_cur_time": entry["ob_cur_time"],
                "ob_htf_zone": entry["ob_zone"],
                "fvg_tf": entry["fvg_tf"],
                "fvg_c2_time": entry["fvg_c3_time"],
                "fvg_zone": entry["fvg_zone"],
            })
    return signals


# ============================================================
# END-TO-END runner (BTC focus; multi-symbol сделать тривиально)
# ============================================================

def run_v2_backtest(
    symbol: str,
    df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m,
    apply_swept: bool = True,
) -> list[dict]:
    """End-to-end: V2 detect → SWEPT → score → Floating TP simulate."""
    cfg = FLOATING_TP_CONFIG[symbol]

    resampled = {
        "1d": df_1d, "12h": df_12h, "6h": df_6h, "4h": df_4h,
        "2h": df_2h, "1h": df_1h, "20m": df_20m, "15m": df_15m,
    }

    signals = detect_signals_v2(resampled, df_1m)
    score_long, score_short = build_score_series(df_1h)

    trades: list[dict] = []
    for sig in signals:
        if apply_swept:
            swept = check_swept(sig, df_1h, df_2h)
            if not swept:
                continue
        result = simulate_floating(
            sig, df_1m, df_1h, score_long, score_short,
            R_cap=cfg["R_cap"], threshold=cfg["threshold"], confirm=cfg["confirm"],
        )
        if result is None:
            continue
        trades.append({
            **sig,
            "outcome": result.outcome, "R": result.R,
            "exit_time": result.exit_time, "exit_reason": result.exit_reason,
            "hold_h": result.hold_h, "max_R": result.max_R,
        })
    return trades


if __name__ == "__main__":
    import time

    # Сам-runner для BTC (см. /tmp/run_111_floating_btc.py для v1 эквивалента)
    DATA = Path.home() / "traid-bot" / "data" / "BTCUSDT_1m_vic_vadim.csv"
    print(f"[v2] loading 1m BTC...")
    t = time.time()
    df_1m = pd.read_csv(DATA, parse_dates=["open_time"], index_col="open_time")
    df_1m.index = pd.DatetimeIndex(df_1m.index)
    if df_1m.index.tz is None:
        df_1m.index = df_1m.index.tz_localize("UTC")
    print(f"  {len(df_1m):,} bars in {time.time()-t:.1f}s")

    def rs(tf):
        rule = {"15m":"15min","20m":"20min","1h":"1h","2h":"2h","4h":"4h",
                "6h":"6h","12h":"12h","1d":"1D"}[tf]
        return df_1m.resample(rule, label="left", closed="left").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        }).dropna()

    print("[v2] resampling...")
    t = time.time()
    dfs = {tf: rs(tf) for tf in ("1d","12h","6h","4h","2h","1h","20m","15m")}
    print(f"  done in {time.time()-t:.1f}s")

    print("[v2] running V2 cascade (nested ob_vc) + SWEPT + Floating TP on BTCUSDT...")
    t = time.time()
    trades = run_v2_backtest(
        "BTCUSDT",
        dfs["1d"], dfs["12h"], dfs["4h"], dfs["6h"],
        dfs["1h"], dfs["2h"], dfs["15m"], dfs["20m"], df_1m,
    )
    print(f"  finished in {(time.time()-t)/60:.1f} min")
    print(f"  raw trades: {len(trades)}")

    stats = aggregate_stats(trades)
    print(f"\n=== STATS: BTCUSDT V2 (nested ob_vc + Floating TP) ===")
    for k, v in stats.items():
        if k in ("by_exit_reason", "by_year"): continue
        print(f"  {k:>14}: {v}")
    print(f"\n  by_exit_reason:")
    for r, d in stats.get("by_exit_reason", {}).items():
        print(f"    {r:>14}: n={d['n']:>4}, R={d['R']:+.2f}")
    print(f"\n  by_year:")
    for y, R in sorted(stats.get("by_year", {}).items()):
        print(f"    {y}: {R:+8.2f}R")

    print(f"\n=== Comparison ===")
    print(f"  v1 (ad-hoc) replication:  +196.9R / WR 51.45% / 379 trades / medR +0.08")
    closed = [t for t in trades if t["outcome"] in ("win","loss","flat")]
    if closed:
        med = float(np.median([t["R"] for t in closed]))
        print(f"  V2 (nested ob_vc):        {stats['total_R']:+.1f}R / WR {stats['WR']}% / "
              f"{stats['n']} trades / medR {med:+.2f}")
