"""БАЛЛЬНАЯ СИСТЕМА СИМБИОЗА ASVK-индикаторов: тренд, направление, исчерпание.

Синтез 5 индикаторов в прозрачный балл (каждый вклад явный):
  • RSI ASVK         -> импульс + OB/OS (исчерпание)        [читается live]
  • MoneyHands ASVK  -> волна/денежный поток + экстремум     [читается live: Plot/BlueWave/MnyFlow]
  • TrendLine ASVK   -> наклон тренда (прокси: лин.регрессия) [считаем из цены]
  • VWAP ASVK        -> цена vs VWAP + полосы (перерастяжение) [считаем из цены]
  • ViC (EVoT) ASVK  -> цена vs объёмный POC                  [считаем из цены]
  + Technical Ratings (бонус)

ВЫХОД: Направление (-10..+10), Сила (0..6 согласованность), Исчерпание (0..10 + сторона).
ЧЕСТНО: это ОПИСАНИЕ текущего состояния + confluence-контекст. Прогноз стороны вперёд = монетка (стена) —
балл НЕ оракул разворота; «исчерпание» = перегрев/риск паузы, не «развернётся». Применять как фильтр/сайзер.

Live-значения (BTC 4h, считаны с TV) задаются ниже; рыночные части считаются из data/BTCUSDT_4h.csv.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/confluence_score.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[2]

# --- LIVE-значения с TV (BTC 4h) ---
RSI = 35.29; RSI_OB = 69.0; RSI_OS = 20.62
MH_PLOT = -103.0; MH_BW = -3.04; MH_FLOW = 2.22       # MoneyHands
TECH = -55.76                                          # Technical Ratings %, [-100..100]
TF = "4h"


def load(sym, tf):
    df = pd.read_csv(ROOT / "data" / f"{sym}_{tf}.csv")
    df.columns = [c.lower() for c in df.columns]
    tcol = "open_time" if "open_time" in df.columns else df.columns[0]
    df[tcol] = pd.to_datetime(df[tcol], utc=True)
    return df.sort_values(tcol).reset_index(drop=True)


def main():
    df = load("BTCUSDT", TF)
    C = df.close.values; H = df.high.values; L = df.low.values; V = df.volume.values
    px = C[-1]
    tp = (H + L + C) / 3
    # VWAP недельный (42 4h-бара) + полоса
    n = 42
    vwap = np.sum(tp[-n:] * V[-n:]) / (np.sum(V[-n:]) + 1e-9)
    vstd = np.std(C[-n:])
    vwap_z = (px - vwap) / (vstd + 1e-9)
    # ViC = объёмный POC за 30 баров
    seg_tp, seg_v = tp[-30:], V[-30:]
    lo, hi = seg_tp.min(), seg_tp.max()
    bins = np.clip(((seg_tp - lo) / (hi - lo + 1e-9) * 23).astype(int), 0, 23)
    agg = np.zeros(24); np.add.at(agg, bins, seg_v)
    vic = lo + (agg.argmax() + 0.5) / 24 * (hi - lo)
    # наклон тренда (лин.регрессия 20 баров, %/бар)
    y = C[-20:]; x = np.arange(20)
    slope = np.polyfit(x, y, 1)[0] / px * 100
    # дивергенция RSI (грубо): цена ниже-лоу за 10 баров?
    price_ll = C[-1] <= np.min(C[-10:])
    price_hh = C[-1] >= np.max(C[-10:])

    # ===== НАПРАВЛЕНИЕ (каждый вклад в [-2..+2]) =====
    comp = {}
    comp["TrendLine(наклон)"] = float(np.clip(slope / 0.3, -2, 2))
    comp["VWAP(цена vs value)"] = (1.5 if px > vwap else -1.5) + (0.5 if vwap_z > 1.5 else (-0.5 if vwap_z < -1.5 else 0))
    comp["ViC(цена vs POC)"] = 1.2 if px > vic else -1.2
    comp["RSI(импульс)"] = (1.0 if RSI > 50 else -1.0) + (0.7 if RSI > 60 else (-0.7 if RSI < 40 else 0))
    comp["MoneyHands(волна)"] = (1.0 if MH_PLOT > 0 else -1.0) + (1.0 if MH_PLOT > 75 else (-1.0 if MH_PLOT < -75 else 0))
    comp["TechRatings"] = float(np.clip(TECH / 50, -2, 2))
    direction = sum(comp.values())
    agree = sum(1 for v in comp.values() if np.sign(v) == np.sign(direction) and v != 0)

    # ===== ИСЧЕРПАНИЕ (0..10) + сторона =====
    ex = {}
    ex["RSI экстремум"] = 3.0 if (RSI >= RSI_OB or RSI <= RSI_OS) else (1.5 if (RSI >= RSI_OB - 6 or RSI <= RSI_OS + 6) else 0)
    ex["MoneyHands |Plot|>100"] = 2.0 if abs(MH_PLOT) > 100 else (1.0 if abs(MH_PLOT) > 75 else 0)
    ex["перерастяжение VWAP"] = 2.0 if abs(vwap_z) > 2 else (1.0 if abs(vwap_z) > 1.5 else 0)
    # дивергенция потока: цена на новом лоу, а MnyFlow положителен (или наоборот)
    ex["дивергенция потока"] = 2.0 if (price_ll and MH_FLOW > 0) or (price_hh and MH_FLOW < 0) else 0
    ex["дивергенция RSI"] = 1.5 if (price_ll and RSI > 38) or (price_hh and RSI < 62) else 0
    exhaustion = sum(ex.values())
    # сторона исчерпания = против текущего направления (перегрет тот тренд, что идёт)
    ex_side = "ВНИЗ-исчерпание (риск отскока вверх)" if direction < 0 else "ВВЕРХ-исчерпание (риск отката вниз)"

    def lbl_dir(d):
        if d >= 6:
            return "СИЛЬНЫЙ БЫЧИЙ"
        if d >= 2:
            return "бычий"
        if d > -2:
            return "нейтральный/флэт"
        if d > -6:
            return "медвежий"
        return "СИЛЬНЫЙ МЕДВЕЖИЙ"

    out = []
    A = out.append
    A(f"БАЛЛЬНАЯ СИСТЕМА СИМБИОЗА — BTC {TF}, цена {px:,.0f}")
    A("=" * 60)
    A(f"VWAP(нед)={vwap:,.0f} (z={vwap_z:+.2f})  ViC-POC={vic:,.0f}  наклон={slope:+.2f}%/бар")
    A("\n--- НАПРАВЛЕНИЕ ТРЕНДА (вклады) ---")
    for k, v in sorted(comp.items(), key=lambda x: x[1]):
        A(f"  {k:24} {v:+.2f}")
    A(f"  {'ИТОГО НАПРАВЛЕНИЕ':24} {direction:+.2f}  -> {lbl_dir(direction)}")
    A(f"  СИЛА (согласованность): {agree}/6 индикаторов в сторону тренда")
    A("\n--- ИСЧЕРПАНИЕ (перегрев/риск паузы, НЕ прогноз разворота) ---")
    for k, v in sorted(ex.items(), key=lambda x: -x[1]):
        A(f"  {k:24} +{v:.1f}")
    A(f"  {'ИТОГО ИСЧЕРПАНИЕ':24} {exhaustion:.1f}/10  ({'ВЫСОКОЕ' if exhaustion>=6 else 'среднее' if exhaustion>=3 else 'низкое'})")
    A(f"  Сторона: {ex_side}")
    A("\n--- ВЕРДИКТ (описательно) ---")
    A(f"  Тренд: {lbl_dir(direction)} (балл {direction:+.1f}, сила {agree}/6). Исчерпание {exhaustion:.1f}/10 — {ex_side}.")
    A("  Применение: балл = КОНТЕКСТ/фильтр (вход по тренду при высокой силе; осторожнее/меньше сайз при высоком")
    A("  исчерпании). НЕ оракул разворота — сторона вперёд статистически монетка (наша стена).")

    rep = Path(__file__).resolve().parent / "confluence_score_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")
    # вернём числа для отрисовки
    print(f"\nSCORE_JSON dir={direction:.1f} strength={agree} exh={exhaustion:.1f} vwap={vwap:.0f} vic={vic:.0f}")


if __name__ == "__main__":
    main()
