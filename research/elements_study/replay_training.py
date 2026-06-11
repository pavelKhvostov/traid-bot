"""replay_training.py — «обучение как нейро»: forward-walk разметка зон реакции за год.

Идея пользователя: каждый день размечать ТОЛЬКО потенциальные зоны реакции,
шагать вперёд, проверять сработала ли зона → накапливать насмотренность.

Этот движок делает то же САМО для всего года сразу (без подглядывания в будущее):
для КАЖДОГО дня (12h-бара) считает зоны реакции по канону проекта, видимые НА ТОТ
момент, потом проверяет дала ли зона реакцию в следующих барах. Накапливает
статистику: какие типы зон реально работают, с какой вероятностью.

Зоны реакции (потенциальные — где цена МОЖЕТ отбиться):
- FVG (канон c1-c3) незакрытые — неэффективность, магнит
- OB незатронутые — Order Block
- BSL/SSL фракталы — ликвидность (цель свипа по ICT)

Реакция = после касания зоны цена развернулась на >= REACT_PCT в сторону зоны
в течение REACT_BARS баров (без пробоя зоны насквозь).

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/replay_training.py
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
_sys.path.insert(0, str(_ROOT))

import json
import numpy as np
import pandas as pd
from data_manager import load_df

SYMBOL = "BTCUSDT"
TF = "12h"
N = 2                # Williams fractal
REACT_PCT = 1.5      # реакция = разворот >=1.5% от зоны
REACT_BARS = 4       # в течение 4 баров (2 дня) после касания
LOOKBACK = 40        # сколько баров истории видит "трейдер" на каждый день

# период обучения: последний год
TRAIN_START = pd.Timestamp("2025-06-01", tz="UTC")
TRAIN_END = pd.Timestamp("2026-06-01", tz="UTC")


def detect_zones_at(df, end_i):
    """Зоны реакции, видимые НА момент бара end_i (только прошлое <= end_i).

    Возвращает список зон: dict(kind, dir, top, bottom, born_i).
    """
    O, H, L, C = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    zones = []
    lo = max(N, end_i - LOOKBACK)

    # FVG канон c1-c3 (i-1, i, i+1), незакрытые на момент end_i
    for i in range(lo + 1, end_i):
        c1h, c1l, c3h, c3l = H[i-1], L[i-1], H[i+1], L[i+1]
        if c1h < c3l:  # bullish FVG
            top, bot = c3l, c1h
            filled = (L[i+2:end_i+1] < bot).any() if i+2 <= end_i else False
            if not filled:
                zones.append(dict(kind="FVG_bull", dir="LONG", top=top, bottom=bot, born_i=i))
        if c1l > c3h:  # bearish FVG
            top, bot = c1l, c3h
            filled = (H[i+2:end_i+1] > top).any() if i+2 <= end_i else False
            if not filled:
                zones.append(dict(kind="FVG_bear", dir="SHORT", top=top, bottom=bot, born_i=i))

    # OB незатронутые
    for i in range(lo + 1, end_i):
        if C[i-1] < O[i-1] and C[i] > O[i-1]:  # bull OB
            top, bot = O[i-1], min(L[i-1], L[i])
            mit = (L[i+1:end_i+1] < bot).any() if i+1 <= end_i else False
            if not mit:
                zones.append(dict(kind="OB_bull", dir="LONG", top=top, bottom=bot, born_i=i))
        if C[i-1] > O[i-1] and C[i] < O[i-1]:  # bear OB
            top, bot = max(H[i-1], H[i]), O[i-1]
            mit = (H[i+1:end_i+1] > top).any() if i+1 <= end_i else False
            if not mit:
                zones.append(dict(kind="OB_bear", dir="SHORT", top=top, bottom=bot, born_i=i))

    # BSL/SSL фракталы (ликвидность)
    for i in range(lo, end_i - N):
        if H[i] > max(H[i-N:i].max(), H[i+1:i+1+N].max()):
            zones.append(dict(kind="BSL", dir="SHORT", top=H[i], bottom=H[i], born_i=i))
        if L[i] < min(L[i-N:i].min(), L[i+1:i+1+N].min()):
            zones.append(dict(kind="SSL", dir="LONG", top=L[i], bottom=L[i], born_i=i))
    return zones


def check_reaction(df, zone, touch_i):
    """Дала ли зона реакцию после касания на баре touch_i.

    LONG-зона: цена коснулась снизу (low <= top) → ждём рост >= REACT_PCT.
    SHORT-зона: цена коснулась сверху (high >= bottom) → ждём падение.
    Возвращает (reacted: bool, move_pct: float).
    """
    H, L, C = df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    e = min(n, touch_i + 1 + REACT_BARS)
    entry = (zone["top"] + zone["bottom"]) / 2
    if zone["dir"] == "LONG":
        mv = (H[touch_i+1:e].max() / entry - 1) * 100 if e > touch_i+1 else 0
        # пробой вниз = зона не сработала
        broke = (C[touch_i+1:e] < zone["bottom"] * 0.99).any() if e > touch_i+1 else False
        return (mv >= REACT_PCT and not broke), round(mv, 2)
    else:
        mv = (entry / L[touch_i+1:e].min() - 1) * 100 if e > touch_i+1 else 0
        broke = (C[touch_i+1:e] > zone["top"] * 1.01).any() if e > touch_i+1 else False
        return (mv >= REACT_PCT and not broke), round(mv, 2)


def main():
    df = load_df(SYMBOL, TF).sort_index()
    df = df[(df.index >= TRAIN_START - pd.Timedelta(days=30)) & (df.index <= TRAIN_END)]
    df = df.reset_index(drop=False)
    tcol = df.columns[0]
    H, L = df["high"].values, df["low"].values
    n = len(df)
    print(f"[replay] {SYMBOL} {TF}: {n} баров, обучение {TRAIN_START.date()}..{TRAIN_END.date()}", flush=True)

    # для каждого дня: какие зоны были активны, какие коснулись, какие сработали
    stats = {}  # kind → [reacted_count, touched_count, sum_move]
    examples = []
    start_i = max(LOOKBACK, df.index[df[tcol] >= TRAIN_START][0] if (df[tcol] >= TRAIN_START).any() else LOOKBACK)

    for i in range(start_i, n - 1):
        zones = detect_zones_at(df, i)
        bar_h, bar_l = H[i], L[i]
        for z in zones:
            # касание текущим баром i
            if z["dir"] == "LONG":
                touched = bar_l <= z["top"] and bar_h >= z["bottom"] * 0.995
            else:
                touched = bar_h >= z["bottom"] and bar_l <= z["top"] * 1.005
            if not touched:
                continue
            reacted, mv = check_reaction(df, z, i)
            k = z["kind"]
            if k not in stats:
                stats[k] = [0, 0, 0.0]
            stats[k][1] += 1
            if reacted:
                stats[k][0] += 1
            stats[k][2] += mv
            examples.append(dict(date=str(df[tcol].iloc[i].date()), kind=k, dir=z["dir"],
                                 zone=f"{z['bottom']:.0f}-{z['top']:.0f}", reacted=bool(reacted), move=float(mv)))

    print("\n=== СТАТИСТИКА ЗОН РЕАКЦИИ (год BTC 12h) ===", flush=True)
    print(f"{'тип зоны':<12}{'касаний':<10}{'сработало':<12}{'% реакции':<12}{'ср.движение'}", flush=True)
    rows = []
    for k, (r, t, sm) in sorted(stats.items(), key=lambda x: -x[1][0]/max(x[1][1],1)):
        pct = r/t*100 if t else 0
        avg = sm/t if t else 0
        rows.append((k, t, r, pct, avg))
        print(f"  {k:<12}{t:<10}{r:<12}{pct:.0f}%{'':<8}{avg:+.2f}%", flush=True)

    # сводка
    tot_t = sum(s[1] for s in stats.values()); tot_r = sum(s[0] for s in stats.values())
    print(f"\n  ИТОГО: {tot_t} касаний зон, {tot_r} сработали ({tot_r/tot_t*100:.0f}%)", flush=True)
    print(f"\n  ВЫВОД (чему 'научился'): зоны с лучшей реакцией =", flush=True)
    for k, t, r, pct, avg in sorted(rows, key=lambda x: -x[3])[:3]:
        if t >= 5:
            print(f"    • {k}: {pct:.0f}% реакции (n={t}, ср {avg:+.1f}%)", flush=True)

    out = _ROOT / "research/elements_study/output/replay_training_year.json"
    json.dump({"stats": {k: {"touched": v[1], "reacted": v[0], "pct": v[0]/v[1]*100 if v[1] else 0,
                             "avg_move": v[2]/v[1] if v[1] else 0} for k, v in stats.items()},
               "examples": examples[-50:]}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\n[saved] {out}", flush=True)


if __name__ == "__main__":
    main()
