"""etap_221 — #6 Activity (dollar) bars vs time bars (AFML / Lopez de Prado).

AFML: time-бары статистически плохи (нестационарны, тяжёлые хвосты, vol-clustering).
Dollar-бары (равный $-объём/бар) → returns ближе к IID/нормали. Проверяем на BTC из 1m:
  - эксцесс (kurtosis), Jarque-Bera (нормальность)
  - autocorr |ret| lag1 (vol-clustering — у dollar должно быть НИЖЕ)
  - autocorr ret lag1 (mean-reversion/momentum)
Затем честно: помогает ли это НАШЕМУ day-direction модулю (он привязан к календарному дню)?

Запуск: venv/Scripts/python.exe research/daily_engine/etap_221_dollar_bars.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from scipy import stats as st

ONEMIN = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1m.csv"
START = pd.Timestamp("2023-01-01", tz="UTC")


def describe(ret, name):
    ret = ret.dropna().values
    k = st.kurtosis(ret)                      # 0 = нормаль (Fisher)
    jb = st.jarque_bera(ret)
    ac1 = pd.Series(ret).autocorr(1)
    acabs = pd.Series(np.abs(ret)).autocorr(1)
    print(f"  {name:<16} n={len(ret):>6} kurt={k:>7.2f} JB_p={jb.pvalue:<7.1e} "
          f"AC(ret)={ac1:>+.3f} AC(|ret|)={acabs:>+.3f}")
    return dict(kurt=k, acabs=acabs)


def main():
    print("Загрузка 1m (slice 2023+)...")
    df = pd.read_csv(ONEMIN)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df[df["open_time"] >= START].set_index("open_time").sort_index()
    print(f"  1m баров: {len(df)}  {df.index[0]} → {df.index[-1]}")

    # time-бары: 1h
    tb = df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

    # dollar-бары: равный $-объём, ~то же число баров что 1h
    dv = (df["close"] * df["volume"]).values
    cum = np.cumsum(dv)
    thr = cum[-1] / len(tb)                    # порог под равное кол-во баров
    binid = np.floor(cum / thr).astype(np.int64)
    g = pd.DataFrame({"bin": binid, "open": df["open"].values, "high": df["high"].values,
                      "low": df["low"].values, "close": df["close"].values, "t": df.index})
    dbar = g.groupby("bin").agg(open=("open", "first"), high=("high", "max"),
                                low=("low", "min"), close=("close", "last"), t=("t", "last"))
    print(f"\n  time-баров (1h): {len(tb)} | dollar-баров: {len(dbar)} (порог ${thr:,.0f})")

    print("\n■ СТАТ-СВОЙСТВА ДОХОДНОСТЕЙ (AFML-тезис: dollar лучше)")
    print(f"  {'тип':<16} {'n':>8} {'kurtosis':>9} {'JB_p':>9} {'AC(ret)':>9} {'AC(|ret|)':>10}")
    s_t = describe(np.log(tb["close"]).diff(), "TIME (1h)")
    s_d = describe(np.log(dbar["close"]).diff(), "DOLLAR")

    print("\n■ ВЕРДИКТ")
    print(f"  эксцесс (тяжесть хвостов): time {s_t['kurt']:.1f} → dollar {s_d['kurt']:.1f} "
          f"({'лучше' if s_d['kurt'] < s_t['kurt'] else 'хуже'})")
    print(f"  vol-clustering AC(|ret|): time {s_t['acabs']:+.3f} → dollar {s_d['acabs']:+.3f} "
          f"({'меньше=лучше' if s_d['acabs'] < s_t['acabs'] else 'больше=хуже'})")

    print("\n■ РЕЛЕВАНТНОСТЬ НАШЕМУ МОДУЛЮ (честно)")
    print("  Наш day-direction слой привязан к КАЛЕНДАРНОМУ дню (close>open за UTC-сутки),")
    print("  а dollar-бары к суткам не выравниваются → прямо в слой не вставить.")
    print("  Польза dollar-баров = чище статистика для ML на ПОСЛЕДОВАТЕЛЬНОСТЯХ (не дневной цвет).")

    dbar.to_csv(Path(__file__).resolve().parent / "output" / "etap_221_dollar_bars.csv", index=False)
    print("\nSaved: output/etap_221_dollar_bars.csv")


if __name__ == "__main__":
    main()
