"""
today_signals.py
Проходит по всем 5 стратегиям × 3 символам × 9-10 ТФ за СЕГОДНЯ
(с 00:00 UTC) и печатает все найденные сигналы в терминал.

Это скрипт-наблюдатель. Ничего не отправляет, не помечает, не трогает
state. Просто показывает что НАШЛОСЬ бы за сегодня по логике.

Запуск:
    python today_signals.py
"""
from __future__ import annotations

import pandas as pd

from config import SYMBOLS
from data_manager import load_df
from strategies import fractal, fvg, hammer, marubozu, ob_htf, obx4, rdrb
from strategies.ob1h_core import find_first_ob1h_in_zone
from strategies.obx4 import to_ref_format

STRATEGY_TFS = ["12h", "1d", "2d", "3d"]

STRATEGY_MAP = {
    "OBX4":     (obx4.detect_zones,     STRATEGY_TFS),
    "FVG":      (fvg.detect_zones,      STRATEGY_TFS),
    "OB_HTF":   (ob_htf.detect_zones,   STRATEGY_TFS),
    "RDRB":     (rdrb.detect_zones,     STRATEGY_TFS),
    "FRACTAL":  (fractal.detect_zones,  STRATEGY_TFS),
    "MARUBOZU": (marubozu.detect_zones, STRATEGY_TFS),
    "HAMMER":   (hammer.detect_zones,   STRATEGY_TFS),
}

ASSET_ICON = {"BTCUSDT": "₿", "ETHUSDT": "Ξ", "SOLUSDT": "◎"}
STRAT_ICON = {
    "OBX4": "⚡", "FVG": "〰️", "OB_HTF": "📦",
    "RDRB": "↩️", "FRACTAL": "❄️", "MARUBOZU": "🟩", "HAMMER": "🔨",
}
DIR_ICON = {"LONG": "📈", "SHORT": "📉"}


def fmt_num(x: float) -> str:
    if x >= 1000:
        s = f"{x:.2f}"
    else:
        s = f"{x:.4f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_time(ts) -> str:
    return pd.to_datetime(ts, utc=True).strftime("%Y-%m-%d %H:%M UTC")


def main():
    today_start = pd.Timestamp.utcnow().floor("D")
    if today_start.tz is None:
        today_start = today_start.tz_localize("UTC")

    print()
    print(f"=== Сигналы за сегодня (с {today_start.isoformat()}) ===")
    print()

    all_signals = []

    for symbol in SYMBOLS:
        df_1h_raw = load_df(symbol, "1h")
        if df_1h_raw.empty:
            print(f"[!] {symbol}: пустой 1h DataFrame, пропускаю")
            continue
        df_1h = to_ref_format(df_1h_raw)

        for strategy_name, (detect_fn, applicable_tfs) in STRATEGY_MAP.items():
            for tf in applicable_tfs:
                df_tf = load_df(symbol, tf)
                if df_tf.empty or len(df_tf) < 5:
                    continue

                zones = detect_fn(df_tf, symbol, tf)
                if not zones:
                    continue

                # только зоны, родившиеся сегодня
                today_zones = [
                    z for z in zones
                    if pd.to_datetime(z.trigger_time, utc=True) >= today_start
                ]

                for z in today_zones:
                    hit = find_first_ob1h_in_zone(z, df_1h)
                    if hit is None:
                        continue
                    ob_time = pd.to_datetime(hit["ob1h_cur_time"], utc=True)
                    if ob_time < today_start:
                        continue

                    all_signals.append({
                        "strategy": strategy_name,
                        "symbol": symbol,
                        "source_tf": tf,
                        "direction": z.direction,
                        "zone_bottom": float(z.zone_bottom),
                        "zone_top": float(z.zone_top),
                        "trigger_time": pd.to_datetime(z.trigger_time, utc=True),
                        "ob1h_time": ob_time,
                        "ob1h_close": float(hit["ob1h_cur_close"]),
                    })

    if not all_signals:
        print("Нет сигналов за сегодня.")
        print()
        return

    # сортировка по времени OB-1h, новые сверху
    all_signals.sort(key=lambda s: s["ob1h_time"], reverse=True)

    print(f"Всего найдено: {len(all_signals)} сигналов")
    print()

    # сводка по стратегиям
    by_strategy = {}
    for s in all_signals:
        by_strategy[s["strategy"]] = by_strategy.get(s["strategy"], 0) + 1
    print("По стратегиям:")
    for k in ["OBX4", "FVG", "OB_HTF", "RDRB", "FRACTAL", "MARUBOZU", "HAMMER"]:
        if k in by_strategy:
            print(f"  {STRAT_ICON.get(k, '?')} {k}: {by_strategy[k]}")
    print()

    # сводка по символам
    by_symbol = {}
    for s in all_signals:
        by_symbol[s["symbol"]] = by_symbol.get(s["symbol"], 0) + 1
    print("По символам:")
    for k in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        if k in by_symbol:
            print(f"  {ASSET_ICON.get(k, '?')} {k}: {by_symbol[k]}")
    print()

    # детальный список
    print("=" * 80)
    print(f"{'OB 1h время':<22} {'Символ':<10} {'TF':<5} {'Стратегия':<10} {'Напр.':<7} {'Цена':<12} Зона")
    print("=" * 80)
    for s in all_signals:
        zone_str = f"{fmt_num(s['zone_bottom'])} – {fmt_num(s['zone_top'])}"
        print(
            f"{fmt_time(s['ob1h_time']):<22} "
            f"{s['symbol']:<10} "
            f"{s['source_tf']:<5} "
            f"{s['strategy']:<10} "
            f"{s['direction']:<7} "
            f"{fmt_num(s['ob1h_close']):<12} "
            f"{zone_str}"
        )
    print("=" * 80)
    print()


if __name__ == "__main__":
    main()
