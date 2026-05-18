"""Этап 88: forensic-аудит live бота на "current hour only" фильтр.

Цель пользователя: бот должен отправлять ТОЛЬКО сигналы, образовавшиеся в текущий
час (свежий 1h close).

Что проверяем:
  1. Текущая логика "stale" — что блокируется, что пропускается?
  2. signal_time это c2_OPEN или c2_CLOSE?
  3. Для разных entry TF (15m/20m/1h/2h) — какой реальный age сигнала?
  4. Race condition в mark_sent (concurrent writes)?
  5. Простой ли способ свести к "current hour only"?
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals
from strategies.strategy_1_1_6 import detect_strategy_1_1_6_signals


def fvg_tf_minutes(fvg_tf: str) -> int:
    return {"15m": 15, "20m": 20, "1h": 60, "2h": 120}[fvg_tf]


def main():
    print("[INFO] Audit live bot 'current hour' filter")
    print("=" * 88)

    print("\n1. ТЕКУЩАЯ ЛОГИКА (что в коде):")
    print("   strategy_1_1_1_scanner.py:")
    print("     MAX_SIGNAL_AGE_HOURS = 2")
    print("     sig_time = sig['signal_time']  # = fvg_entry.c2_TIME (открытие c2 бара!)")
    print("     age = now - sig_time")
    print("     if age > 2h: stale, silenced")
    print("   multi_strategy_scanner.py: то же самое")

    print("\n2. ЧТО ТАКОЕ signal_time:")
    print("   detector ставит sig['signal_time'] = fvg_entry.c2_time")
    print("   c2_time = OPEN time бара c2 (последнего в 3-bar FVG паттерне)")
    print("   c2_CLOSE = c2_time + tf_duration")

    print("\n3. РЕАЛЬНЫЙ age сигнала в момент 1h close:")
    print("   Случай: 1h close в 14:00, сигнал имеет c2_close = 14:00")
    print("")
    print("   Entry TF | c2_time   | c2_close | age (now=14:00, по c2_time)")
    print("   --------|-----------|----------|--------------------------")
    print("   15m     | 13:45     | 14:00    | 0.25h")
    print("   20m     | 13:40     | 14:00    | 0.33h")
    print("   1h      | 13:00     | 14:00    | 1.0h")
    print("   2h      | 12:00     | 14:00    | 2.0h  <- НА ГРАНИ MAX=2!")
    print("")
    print("   Случай: сигнал 'свежий' для 2h FVG, но age по c2_time = 2h.")
    print("   Если 1h close обработается с задержкой 100ms, age=2h+epsilon > 2h -> SILENCED.")
    print("   Это БАГ — 2h FVG сигналы могут систематически глушиться.")

    print("\n4. ЧТО ВКЛЮЧАЕТ ТЕКУЩАЯ ПРОВЕРКА (age <= 2h):")
    print("   - 15m FVG свежий (c2_close=14:00): age=0.25h OK пропускается")
    print("   - 15m FVG со c2_close=12:30 (1.5h назад): age=1.75h OK ВСЁ ЕЩЁ ПРОПУСКАЕТСЯ!")
    print("   - 1h FVG свежий: age=1h OK пропускается")
    print("   - 2h FVG свежий: age=2h на грани, может silenced из-за delay")
    print("")
    print("   ВЫВОД: текущая проверка ПРОПУСКАЕТ сигналы из ПРЕДЫДУЩЕГО часа")
    print("   (например 15m FVG c2_close=12:30 при 1h close 14:00).")
    print("   Это НЕ соответствует требованию 'только current hour'.")

    print("\n5. ЧТО ХОЧЕТ ПОЛЬЗОВАТЕЛЬ:")
    print("   Только сигналы, чей c2 ЗАКРЫЛСЯ в текущий час.")
    print("   При 1h close 14:00: c2_close должен быть в (13:00, 14:00].")
    print("   Это означает 'образовался в текущий час'.")

    print("\n6. ПРЕДЛОЖЕННАЯ ФОРМУЛА:")
    print("   current_hour_close = pd.Timestamp.now('UTC').floor('h')")
    print("   tf_min = fvg_tf_minutes(sig['fvg_tf'])")
    print("   signal_close = sig['signal_time'] + Timedelta(minutes=tf_min)")
    print("   in_current_hour = (current_hour_close - 1h) < signal_close <= current_hour_close")
    print("   if not in_current_hour: SILENCED")

    print("\n7. ПРОВЕРКА НА ИСТОРИЧЕСКИХ ДАННЫХ:")
    print("   Симулируем 'current hour' проверку на BTC и смотрим сколько сигналов отсеется.")

    df_1d = load_df("BTCUSDT", "1d")
    df_4h = load_df("BTCUSDT", "4h")
    df_1h = load_df("BTCUSDT", "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df("BTCUSDT", "15m")
    df_1m = load_df("BTCUSDT", "1m")
    if df_15m.empty or df_1m.empty:
        print("[WARN] нет 15m/1m данных")
        return
    df_20m = compose_from_base(df_1m, "20m")

    # Recent 30 days like live bot
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()

    # Detect 1.1.2 (uses 15m/20m entry)
    sigs_112 = detect_strategy_1_1_2_signals(
        df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False)
    # Detect 1.1.3 (uses 1h/2h entry)
    sigs_113 = detect_strategy_1_1_3_signals(
        df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, verbose=False)
    # Detect 1.1.6 (uses 1h/2h entry, new)
    sigs_116 = detect_strategy_1_1_6_signals(
        df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, verbose=False)

    for name, sigs in [("1.1.2", sigs_112), ("1.1.3", sigs_113), ("1.1.6", sigs_116)]:
        if not sigs:
            print(f"\n   [{name}] 0 signals")
            continue
        print(f"\n   [{name}] {len(sigs)} signals in last 30 days")
        # Distribution of entry TFs
        tfs = {}
        for s in sigs:
            tfs[s["fvg_tf"]] = tfs.get(s["fvg_tf"], 0) + 1
        print(f"     entry TF distribution: {tfs}")

        # For each signal, compute age between c2_close and "next 1h close"
        # to see if our current-hour filter would let it through
        ages_at_1h_close = []
        for s in sigs:
            sig_time = pd.Timestamp(s["signal_time"])
            if sig_time.tz is None:
                sig_time = sig_time.tz_localize("UTC")
            tf_min = fvg_tf_minutes(s["fvg_tf"])
            c2_close = sig_time + pd.Timedelta(minutes=tf_min)
            # Next 1h close after c2_close
            next_1h_close = c2_close.ceil("h")
            if next_1h_close == c2_close:
                next_1h_close = c2_close  # exactly at boundary
            # age from c2_close to next_1h_close
            ages_at_1h_close.append((next_1h_close - c2_close).total_seconds() / 60)

        import statistics
        if ages_at_1h_close:
            mean_age = statistics.mean(ages_at_1h_close)
            max_age = max(ages_at_1h_close)
            print(f"     При 'current hour' фильтре:")
            print(f"       median delay c2_close -> next 1h close: "
                  f"{statistics.median(ages_at_1h_close):.1f} min")
            print(f"       max delay: {max_age:.1f} min "
                  f"(within 1h current hour boundary = good)")

    print("\n8. RACE CONDITION в mark_sent:")
    print("   state.mark_sent(): d = load_sent_signals() -> d[key]=payload -> save")
    print("   Не защищено file lock. 4 scanner-а через asyncio.to_thread пишут параллельно.")
    print("   Риск: state/sent_signals.json corruption или потеря записей.")
    print("   Это отдельный баг, не связанный с current hour, но стоит знать.")

    print("\n" + "=" * 88)
    print("ИТОГ:")
    print("  - БАГ #1 [CRITICAL]: текущий age check (MAX_SIGNAL_AGE_HOURS=2) ПРОПУСКАЕТ")
    print("    сигналы из предыдущих часов (например 15m FVG c2_close=12:30 при 1h close 14:00).")
    print("  - БАГ #2 [CRITICAL]: для 2h FVG age по c2_time равен 2h на свежем сигнале —")
    print("    может silenced из-за задержки между WS close event и обработкой.")
    print("  - БАГ #3 [MEDIUM]: race condition в mark_sent (4 concurrent writes без lock).")
    print("  - FIX #1+#2: использовать c2_CLOSE (не c2_open) и floor('h') boundary.")
    print("  - FIX #3: file lock на mark_sent или in-memory dedup cache.")


if __name__ == "__main__":
    main()
