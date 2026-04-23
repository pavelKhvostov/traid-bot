"""Проверка FVG: зоны на 4h + OB 1h через общее ядро."""
from __future__ import annotations

from data_manager import update_df_incrementally
from strategies import fvg
from strategies.base import format_signal_telegram
from strategies.ob1h_core import scan_zones_to_signals
from strategies.obx4 import to_ref_format


def main() -> None:
    symbol, source_tf = "BTCUSDT", "4h"

    print(f"[FVG] загружаем историю {symbol} {source_tf}...")
    df_htf = update_df_incrementally(symbol, source_tf)
    print(f"[FVG] {source_tf}: {len(df_htf)} свечей")
    if df_htf.empty:
        raise RuntimeError("Пустой df_htf")

    zones = fvg.detect_zones(df_htf, symbol, source_tf)
    print(f"[FVG] зон FVG найдено: {len(zones)} "
          f"(LONG={sum(1 for z in zones if z.direction == 'LONG')}, "
          f"SHORT={sum(1 for z in zones if z.direction == 'SHORT')})")

    print(f"[FVG] загружаем историю {symbol} 1h для ob1h-ядра...")
    df_1h_raw = update_df_incrementally(symbol, "1h")
    df_1h = to_ref_format(df_1h_raw)
    print(f"[FVG] 1h: {len(df_1h)} свечей")

    signals = scan_zones_to_signals(zones, df_1h)
    print(f"[FVG] сработавших OB 1h сигналов: {len(signals)} из {len(zones)} зон")

    last5 = sorted(signals, key=lambda s: s.confirm_time)[-5:]
    if last5:
        print("\n---- последние 5 сигналов ----")
        for s in last5:
            print(f"{s.confirm_time.isoformat()}  {s.direction:<5}  "
                  f"zone={s.meta['zone_bottom']:.2f}-{s.meta['zone_top']:.2f}  "
                  f"price={s.price}")
        print("\n---- preview telegram (последний) ----")
        print(format_signal_telegram(last5[-1]))
        print("--------------------------------------")
    else:
        print("[FVG] сигналов нет.")


if __name__ == "__main__":
    main()
