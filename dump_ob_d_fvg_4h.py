"""Дамп всех валидных пар OB-D + FVG-4h на 3 года BTC."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg, FVGZone

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
OUTPUT_PATH = Path("signals/strategy_1_1_1_ob_d_fvg_4h.csv")


def main():
    print(f"[INFO] {SYMBOL} {DAYS_BACK}d, FVG-4h строго в time range OB-D")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d = df_1d[df_1d.index >= cutoff]
    print(f"  1d candles after cutoff: {len(df_1d)}")

    rows = []
    for d_idx in range(1, len(df_1d)):
        ob_d = detect_ob_pair(df_1d, d_idx)
        if ob_d is None:
            continue

        # Поиск FVG-4h: строго в time range OB-D = [prev_time, cur_time+20h]
        # (так чтобы FVG-4h.c2 закрылась до конца cur_day).
        fvg_search_start = ob_d.prev_time
        fvg_search_end = ob_d.cur_time + pd.Timedelta(hours=20)
        df_4h_window = df_4h[
            (df_4h.index >= fvg_search_start) & (df_4h.index <= fvg_search_end)
        ]
        if len(df_4h_window) < 3:
            continue

        # Все валидные FVG-4h — каждая отдельная ситуация.
        for j in range(2, len(df_4h_window)):
            f = detect_fvg(df_4h_window, j)
            if f is None or f.direction != ob_d.direction:
                continue
            # c2 (= i) должна быть в cur day OB-D.
            if not (ob_d.cur_time <= f.c2_time < ob_d.cur_time + pd.Timedelta(days=1)):
                continue
            if ob_d.direction == "LONG":
                if not (ob_d.bottom <= f.bottom <= ob_d.top):
                    continue
            else:
                if not (ob_d.bottom <= f.top <= ob_d.top):
                    continue

            zone_bottom = max(ob_d.bottom, f.bottom)
            zone_top = min(ob_d.top, f.top)

            rows.append({
                "direction": ob_d.direction,
                "ob_d_prev_time": ob_d.prev_time.isoformat(),
                "ob_d_cur_time": ob_d.cur_time.isoformat(),
                "ob_d_bottom": round(ob_d.bottom, 2),
                "ob_d_top": round(ob_d.top, 2),
                "fvg_4h_c0_time": f.c0_time.isoformat(),
                "fvg_4h_c2_time": f.c2_time.isoformat(),
                "fvg_4h_bottom": round(f.bottom, 2),
                "fvg_4h_top": round(f.top, 2),
                "intersection_bottom": round(zone_bottom, 2),
                "intersection_top": round(zone_top, 2),
            })

    df_out = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_PATH, index=False)

    print(f"\n[INFO] Записано {len(rows)} пар OB-D + FVG-4h в {OUTPUT_PATH}")
    print(f"  LONG:  {(df_out['direction']=='LONG').sum()}")
    print(f"  SHORT: {(df_out['direction']=='SHORT').sum()}")
    print(f"\nПо годам:")
    df_out["year"] = pd.to_datetime(df_out["ob_d_cur_time"]).dt.year
    print(df_out.groupby(["year", "direction"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()
