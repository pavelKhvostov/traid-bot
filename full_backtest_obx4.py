"""Полный исторический прогон OBX4 по всем символам и таймфреймам."""
from __future__ import annotations

import pandas as pd

from config import ALL_TIMEFRAMES, SIGNALS_DIR, SYMBOLS, TIMEFRAMES_COMPOSED
from data_manager import compose_from_base, load_df, save_df, update_df_incrementally
from strategies.obx4 import detect_all_obx4, to_ref_format


def _load_for_tf(symbol: str, tf: str) -> pd.DataFrame:
    if tf in TIMEFRAMES_COMPOSED:
        base_tf = TIMEFRAMES_COMPOSED[tf]
        base = update_df_incrementally(symbol, base_tf)
        composed = compose_from_base(base, tf)
        if not composed.empty:
            save_df(composed, symbol, tf)
        return composed
    return update_df_incrementally(symbol, tf)


def main() -> None:
    rows = []
    all_signals: list[pd.DataFrame] = []

    for symbol in SYMBOLS:
        for tf in ALL_TIMEFRAMES:
            print(f"[BT] {symbol} {tf}: loading history...")
            df = _load_for_tf(symbol, tf)
            if df.empty:
                print(f"[BT] {symbol} {tf}: пусто, skip")
                rows.append({"symbol": symbol, "tf": tf, "n": 0, "last_c5": None})
                continue

            ref = to_ref_format(df)
            patterns = detect_all_obx4(ref)
            n = len(patterns)
            last_c5 = None
            if n > 0:
                last_c5 = pd.to_datetime(patterns["c5_time"].max(), utc=True)
                patterns = patterns.copy()
                patterns["symbol"] = symbol
                patterns["tf"] = tf
                all_signals.append(patterns[[
                    "symbol", "tf", "direction", "pattern_time", "c5_time",
                    "ob_top", "ob_bottom", "fvg_top", "fvg_bottom",
                ]])

            print(f"[BT] {symbol} {tf}: found {n} signals"
                  + (f", last c5={last_c5.isoformat()}" if last_c5 is not None else ""))
            rows.append({"symbol": symbol, "tf": tf, "n": n, "last_c5": last_c5})

    # --- таблица ---
    print()
    header = f"{'SYMBOL':<10}{'TF':<6}{'N_signals':<12}{'last_c5_time':<25}"
    print(header)
    print("-" * len(header))
    for r in rows:
        last_str = r["last_c5"].strftime("%Y-%m-%d %H:%M") if r["last_c5"] is not None else "-"
        print(f"{r['symbol']:<10}{r['tf']:<6}{r['n']:<12}{last_str:<25}")

    # --- итог ---
    total = sum(r["n"] for r in rows)
    print()
    print(f"TOTAL signals across all symbols/TFs: {total}")

    best = max((r for r in rows if r["last_c5"] is not None), key=lambda r: r["last_c5"], default=None)
    if best is not None:
        print(f"Last signal overall: {best['last_c5'].strftime('%Y-%m-%d %H:%M UTC')} "
              f"on {best['symbol']} {best['tf']}")
    else:
        print("Last signal overall: none")

    # --- CSV ---
    out_path = SIGNALS_DIR / "obx4_backtest_full.csv"
    if all_signals:
        full = pd.concat(all_signals, ignore_index=True)
        full["c5_time"] = pd.to_datetime(full["c5_time"], utc=True)
        full["pattern_time"] = pd.to_datetime(full["pattern_time"], utc=True)
        full = full.sort_values("c5_time", ascending=False).reset_index(drop=True)
        full.to_csv(out_path, index=False)
        print(f"\nSaved {len(full)} signals to {out_path}")
    else:
        pd.DataFrame(columns=[
            "symbol", "tf", "direction", "pattern_time", "c5_time",
            "ob_top", "ob_bottom", "fvg_top", "fvg_bottom",
        ]).to_csv(out_path, index=False)
        print(f"\nNo signals. Empty CSV written to {out_path}")


if __name__ == "__main__":
    main()
