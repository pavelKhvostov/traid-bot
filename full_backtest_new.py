"""Полный бэктест 5 стратегий (OBX4, FVG, OB_HTF, RDRB, FRACTAL) через ob1h-ядро."""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from config import SIGNALS_DIR, SYMBOLS
from data_manager import compose_from_base, load_df, save_df, update_df_incrementally
from strategies import fractal, fvg, ob_htf, obx4, rdrb
from strategies.ob1h_core import scan_zones_to_signals
from strategies.obx4 import to_ref_format

OBX4_TFS = ["1h", "2h", "3h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]
HTF_TFS = ["2h", "3h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]

NATIVE = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d"]
COMPOSED = {"3h": "1h", "2d": "1d"}

STRATEGIES = [
    ("OBX4",    obx4,    OBX4_TFS),
    ("FVG",     fvg,     HTF_TFS),
    ("OB_HTF",  ob_htf,  HTF_TFS),
    ("RDRB",    rdrb,    HTF_TFS),
    ("FRACTAL", fractal, HTF_TFS),
]

CSV_COLUMNS = [
    "strategy", "symbol", "source_tf", "direction",
    "trigger_time_utc", "zone_bottom", "zone_top",
    "first_return_time_utc", "ob1h_prev_time_utc", "ob1h_cur_time_utc",
    "ob1h_cur_close",
    "zone_age_hours",
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


def _signal_to_row(s) -> dict:
    m = s.meta
    trigger = pd.to_datetime(m["trigger_time"], utc=True)
    cur = pd.to_datetime(m["ob1h_cur_time"], utc=True)
    age_hours = (cur - trigger).total_seconds() / 3600.0
    return {
        "strategy": s.strategy,
        "symbol": s.symbol,
        "source_tf": m["source_tf"],
        "direction": s.direction,
        "trigger_time_utc": trigger.isoformat(),
        "zone_bottom": m["zone_bottom"],
        "zone_top": m["zone_top"],
        "first_return_time_utc": pd.to_datetime(m["first_return_time"], utc=True).isoformat(),
        "ob1h_prev_time_utc": pd.to_datetime(m["ob1h_prev_time"], utc=True).isoformat(),
        "ob1h_cur_time_utc": cur.isoformat(),
        "ob1h_cur_close": m["ob1h_cur_close"],
        "zone_age_hours": round(age_hours, 2),
    }


def _save_csv(rows: list[dict], path) -> None:
    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    if not df.empty:
        df["_sort"] = pd.to_datetime(df["ob1h_cur_time_utc"], utc=True)
        df = df.sort_values("_sort", ascending=False).drop(columns=["_sort"]).reset_index(drop=True)
    df.to_csv(path, index=False)


def main() -> None:
    rows_by_strat: dict[str, list[dict]] = {name: [] for name, _, _ in STRATEGIES}
    bysym_by_strat: dict[str, dict[str, int]] = {name: defaultdict(int) for name, _, _ in STRATEGIES}

    for symbol in SYMBOLS:
        print(f"\n==== {symbol} ====")
        _prep_history(symbol)

        df_1h_raw = load_df(symbol, "1h")
        df_1h = to_ref_format(df_1h_raw)
        if df_1h.empty:
            print(f"[WARN] {symbol}: пустой 1h, skip")
            continue

        for name, module, tfs in STRATEGIES:
            for tf in tfs:
                df_htf = load_df(symbol, tf)
                if df_htf.empty:
                    print(f"[{name}] {symbol} {tf}: нет данных, skip")
                    continue
                zones = module.detect_zones(df_htf, symbol, tf)
                signals = scan_zones_to_signals(zones, df_1h)
                print(f"[{name}] {symbol} {tf}: {len(zones)} зон -> {len(signals)} OB-сигналов")
                for s in signals:
                    rows_by_strat[name].append(_signal_to_row(s))
                bysym_by_strat[name][symbol] += len(signals)

    paths: dict[str, object] = {}
    for name in rows_by_strat:
        p = SIGNALS_DIR / f"backtest_{name.lower()}.csv"
        _save_csv(rows_by_strat[name], p)
        paths[name] = p

    def _by_sym_str(d: dict[str, int]) -> str:
        return ", ".join(f"{sym}={d.get(sym, 0)}" for sym in SYMBOLS)

    print("\n========== ИТОГО ==========")
    for name in rows_by_strat:
        total = len(rows_by_strat[name])
        print(f"{name:<8}: {total} ({_by_sym_str(bysym_by_strat[name])})")

    print()
    for name, p in paths.items():
        print(f"CSV: {p}")


if __name__ == "__main__":
    main()
