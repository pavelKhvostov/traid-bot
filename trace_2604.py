"""Трассировка alt-списка фракталов для 26.04.2026."""
import pandas as pd
from data_manager import load_df
from backtest_vic_bos import resample_3m, is_swing_high, is_swing_low, _add_to_alt, FRACTAL_N


def main():
    df_1m = load_df("BTCUSDT", "1m")
    df_3m = resample_3m(df_1m)

    day = pd.Timestamp("2026-04-26", tz="UTC")
    start = day + pd.Timedelta(hours=2)
    end = day + pd.Timedelta(hours=10)
    window = df_3m[(df_3m.index >= start) & (df_3m.index <= end)]
    print(f"3m свечей в окне 02:00-10:00: {len(window)}")
    print()

    highs = window["high"].values
    lows = window["low"].values
    times = window.index

    print("Все фракталы (FRACTAL_N=2) в окне:")
    for k in range(FRACTAL_N, len(window) - FRACTAL_N):
        t = times[k]
        if is_swing_high(highs, lows, k, FRACTAL_N):
            print(f"  H {t}: {highs[k]:.2f}")
        if is_swing_low(highs, lows, k, FRACTAL_N):
            print(f"  L {t}: {lows[k]:.2f}")
    print()

    print("Динамика alt-списка:")
    alt = []
    for k in range(FRACTAL_N, len(window) - FRACTAL_N):
        new_f = None
        if is_swing_high(highs, lows, k, FRACTAL_N):
            new_f = {"idx": k, "type": "H", "price": float(highs[k]), "time": times[k]}
        if is_swing_low(highs, lows, k, FRACTAL_N):
            new_f = {"idx": k, "type": "L", "price": float(lows[k]), "time": times[k]}
        if new_f is None:
            continue
        _add_to_alt(new_f, alt)
        last3 = alt[-3:] if len(alt) >= 3 else alt
        descr = []
        for a in last3:
            descr.append(f"{a['type']}@{a['price']:.2f}@{str(a['time'])[11:16]}")
        cond = ""
        if len(alt) >= 3:
            f1, f2, f3 = alt[-3], alt[-2], alt[-1]
            if f1["type"] == "L" and f2["type"] == "H" and f3["type"] == "L":
                if f1["price"] > f3["price"]:
                    cond = "  <-- BEARISH triple (LONG sweep H={:.2f})".format(f2["price"])
                elif f1["price"] < f3["price"]:
                    cond = "  <-- BULLISH triple (SHORT sweep L={:.2f})".format(f3["price"])
        print(f"  +{new_f['type']} {str(new_f['time'])[11:16]}={new_f['price']:.2f}: " + " | ".join(descr) + cond)


if __name__ == "__main__":
    main()
