"""Годовой бэктест 5 стратегий по новой логике подтверждения
(OB-1h | FVG-1h | RDRB-1h). Окно: последние 365 дней."""
from __future__ import annotations


# --- repo-root injection (Phase 3 refactor) ---
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
# --- end repo-root injection ---

from collections import defaultdict

import pandas as pd

from config import SIGNALS_DIR, SYMBOLS
from data_manager import compose_from_base, load_df, save_df, update_df_incrementally
from strategies import fractal, fvg, hammer, marubozu, ob_htf, obx4, rdrb
from strategies.ob1h_core import find_first_confirmation_in_zone
from strategies.obx4 import to_ref_format

STRATEGY_TFS = ["12h", "1d", "2d", "3d"]

NATIVE = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d"]
COMPOSED = {"3h": "1h", "2d": "1d"}

STRATEGIES = [
    ("OBX4",     obx4,     STRATEGY_TFS),
    ("FVG",      fvg,      STRATEGY_TFS),
    ("OB_HTF",   ob_htf,   STRATEGY_TFS),
    ("RDRB",     rdrb,     STRATEGY_TFS),
    ("FRACTAL",  fractal,  STRATEGY_TFS),
    ("MARUBOZU", marubozu, STRATEGY_TFS),
    ("HAMMER",   hammer,   STRATEGY_TFS),
]

CONFIRM_TYPES = ["OB-1h", "FVG-1h", "RDRB-1h"]

CSV_COLUMNS = [
    "strategy",
    "symbol",
    "source_tf",
    "direction",
    "zone_trigger_time",
    "zone_bottom",
    "zone_top",
    "confirm_type",
    "confirm_time",
    "confirm_price",
    "confirm_zone_bottom",
    "confirm_zone_top",
    "hours_to_confirm",
]


def _prep_history(symbol: str) -> None:
    for tf in NATIVE:
        print(f"[DATA] {symbol} {tf}: update...")
        update_df_incrementally(symbol, tf)
    for tf, base_tf in COMPOSED.items():
        base = load_df(symbol, base_tf)
        composed = compose_from_base(base, tf)
        if not composed.empty:
            save_df(composed, symbol, tf)
        print(f"[DATA] {symbol} {tf}: composed {len(composed)} bars from {base_tf}")


def _slice_tf(df_tf: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    if df_tf.empty:
        return df_tf
    if isinstance(df_tf.index, pd.DatetimeIndex):
        return df_tf[df_tf.index >= cutoff]
    return df_tf[pd.to_datetime(df_tf["Open time"], utc=True) >= cutoff]


def _slice_1h(df_1h_ref: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    if df_1h_ref.empty:
        return df_1h_ref
    return df_1h_ref[
        pd.to_datetime(df_1h_ref["Open time"], utc=True) >= cutoff
    ].reset_index(drop=True)


def _row_from_zone(strategy: str, z, confirmation: dict) -> dict:
    trigger = pd.to_datetime(z.trigger_time, utc=True)
    confirm_time = pd.to_datetime(confirmation["confirm_time"], utc=True)
    age_hours = (confirm_time - trigger).total_seconds() / 3600.0
    return {
        "strategy": strategy,
        "symbol": z.symbol,
        "source_tf": z.source_tf,
        "direction": z.direction,
        "zone_trigger_time": trigger.isoformat(),
        "zone_bottom": float(z.zone_bottom),
        "zone_top": float(z.zone_top),
        "confirm_type": confirmation["type"],
        "confirm_time": confirm_time.isoformat(),
        "confirm_price": float(confirmation["confirm_close"]),
        "confirm_zone_bottom": float(confirmation["confirm_zone_bottom"]),
        "confirm_zone_top": float(confirmation["confirm_zone_top"]),
        "hours_to_confirm": round(age_hours, 1),
    }


def _save_csv(rows: list[dict], path) -> None:
    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    if not df.empty:
        df["_sort"] = pd.to_datetime(df["confirm_time"], utc=True)
        df = df.sort_values("_sort", ascending=False).drop(columns=["_sort"]).reset_index(drop=True)
    df.to_csv(path, index=False)


def main() -> None:
    cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=365)
    if cutoff.tz is None:
        cutoff = cutoff.tz_localize("UTC")
    print(f"[INFO] Окно бэктеста: с {cutoff.isoformat()} по сейчас")

    rows_by_strat: dict[str, list[dict]] = {name: [] for name, _, _ in STRATEGIES}
    bysym_by_strat: dict[str, dict[str, int]] = {
        name: defaultdict(int) for name, _, _ in STRATEGIES
    }
    bytype_by_strat: dict[str, dict[str, int]] = {
        name: defaultdict(int) for name, _, _ in STRATEGIES
    }

    for symbol in SYMBOLS:
        print(f"\n==== {symbol} ====")
        _prep_history(symbol)

        df_1h_raw = load_df(symbol, "1h")
        if df_1h_raw.empty:
            print(f"[WARN] {symbol}: пустой 1h, skip")
            continue
        df_1h_full = to_ref_format(df_1h_raw)
        df_1h = _slice_1h(df_1h_full, cutoff)
        if df_1h.empty:
            print(f"[WARN] {symbol}: 1h после cutoff пуст, skip")
            continue

        for name, module, tfs in STRATEGIES:
            for tf in tfs:
                df_tf_full = load_df(symbol, tf)
                if df_tf_full.empty:
                    print(f"[{name}] {symbol} {tf}: нет данных, skip")
                    continue
                df_tf = _slice_tf(df_tf_full, cutoff)
                if df_tf.empty or len(df_tf) < 5:
                    print(f"[{name}] {symbol} {tf}: меньше 5 свечей в окне, skip")
                    continue

                zones = module.detect_zones(df_tf, symbol, tf)
                # подстраховка: оставляем только зоны с trigger_time в окне
                zones = [
                    z for z in zones
                    if pd.to_datetime(z.trigger_time, utc=True) >= cutoff
                ]

                confirmations = 0
                for z in zones:
                    confirmation = find_first_confirmation_in_zone(z, df_1h)
                    if confirmation is None:
                        continue
                    row = _row_from_zone(name, z, confirmation)
                    rows_by_strat[name].append(row)
                    bysym_by_strat[name][symbol] += 1
                    bytype_by_strat[name][confirmation["type"]] += 1
                    confirmations += 1

                print(f"[{name}] {symbol} {tf}: {len(zones)} zones -> {confirmations} confirmations")

    # сохраняем по стратегиям + общий
    paths: dict[str, object] = {}
    all_rows: list[dict] = []
    for name in rows_by_strat:
        rows = rows_by_strat[name]
        p = SIGNALS_DIR / f"backtest_year_{name.lower()}.csv"
        _save_csv(rows, p)
        paths[name] = p
        all_rows.extend(rows)

    all_path = SIGNALS_DIR / "backtest_year_all.csv"
    _save_csv(all_rows, all_path)

    def _by_sym_str(d: dict[str, int]) -> str:
        return ", ".join(f"{sym}={d.get(sym, 0)}" for sym in SYMBOLS)

    def _by_type_str(d: dict[str, int]) -> str:
        return ", ".join(f"{t}: {d.get(t, 0)}" for t in CONFIRM_TYPES)

    print("\n========== ИТОГО за последний год ==========")
    for name in rows_by_strat:
        total = len(rows_by_strat[name])
        print(f"{name:<8}: {total} ({_by_sym_str(bysym_by_strat[name])})")
        print(f"    {_by_type_str(bytype_by_strat[name])}")

    print("\nФайлы:")
    for name, p in paths.items():
        print(f"    {p}")
    print(f"    {all_path}")


if __name__ == "__main__":
    main()
