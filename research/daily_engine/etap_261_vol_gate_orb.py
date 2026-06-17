"""etap_261 - BLOCK 3: Vol-regime gate на opening-range breakout (ORB).

Идея: НЕ ставим на направление (стена), ставим на РАСШИРЕНИЕ хода (доказанный edge:
range/big_day предсказуемы, eff_ratio AUC 0.735). IB = первые 3 часа UTC. На пробое IB
входим В СТОРОНУ ПРОБОЯ (stop), SL = противоположный край IB, fixed RR=2.2. ГЕЙТ:
берём пробой только когда УТРО НАПРАВЛЕННОЕ (morning eff_ratio высокий -> трендовый
день), иначе пропуск. Сравниваем с baseline (ORB без гейта).

Честно: ORB на 24ч-крипте (UTC-полночь как 'открытие') — условность; гейт обязан давать
ПРИРОСТ над baseline, иначе KILL. Судим общим zone_harness, BTC->ETH/SOL, по годам.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_261_vol_gate_orb.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from data_manager import load_df
import zone_harness as ZH

RR = 2.2
IB_H = 3   # часов на opening range


def morning_eff(df15, day):
    """eff_ratio первых IB_H часов дня по 15m закрытиям (|net|/path)."""
    g = df15[(df15.index.normalize() == day) & (df15.index < day + pd.Timedelta(hours=IB_H))]
    c = g["close"].values
    if len(c) < 4:
        return np.nan
    d = np.diff(c); path = np.sum(np.abs(d))
    return float(abs(c[-1] - c[0]) / path) if path > 0 else np.nan


def gen_orb(df1h, df15, eff_min=None):
    """Один ORB-сигнал на день (первый пробой IB), опц. гейт по morning eff_ratio."""
    sig = []
    for day, g in df1h.groupby(df1h.index.normalize()):
        if len(g) < IB_H + 3:
            continue
        H = g["high"].values; Lo = g["low"].values; idx = g.index
        ib_h = H[:IB_H].max(); ib_l = Lo[:IB_H].min()
        if ib_h <= ib_l:
            continue
        if eff_min is not None:
            e = morning_eff(df15, day)
            if not (e >= eff_min):
                continue
        # первый пробой IB после часа IB_H
        for k in range(IB_H, len(g)):
            up = H[k] > ib_h; dn = Lo[k] < ib_l
            if not (up or dn):
                continue
            if up and dn:    # бар пробил обе стороны — берём по большей экскурсии
                direction = "LONG" if (H[k] - ib_h) >= (ib_l - Lo[k]) else "SHORT"
            else:
                direction = "LONG" if up else "SHORT"
            entry = ib_h if direction == "LONG" else ib_l
            sl = ib_l if direction == "LONG" else ib_h
            sig.append(dict(time=idx[k - 1], direction=direction, entry=float(entry), sl=float(sl)))
            break
    return sig


def run_symbol(sym, eff_min, label):
    df1h = load_df(sym, "1h"); df15 = load_df(sym, "15m")
    if df1h.empty:
        print(f"{sym}: нет данных"); return None
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    if not df15.empty and df15.index.tz is None: df15.index = df15.index.tz_localize("UTC")
    sigs = gen_orb(df1h, df15, eff_min=eff_min)
    book = ZH.simulate(sigs, df1h, rr=RR, wait_bars=24, hold_bars=120, entry_type="stop")
    return ZH.report(book, rr=RR, title=f"{sym} ORB {label} | сигналов {len(sigs)}")


def main():
    for eff_min, label in ((None, "BASELINE (без гейта)"),
                           (0.35, "ГЕЙТ eff>=0.35 (утро направленное)"),
                           (0.50, "ГЕЙТ eff>=0.50 (утро очень гладкое)")):
        print("\n" + "#" * 76)
        print(f"#  {label}")
        print("#" * 76)
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            run_symbol(sym, eff_min, label)


if __name__ == "__main__":
    main()
