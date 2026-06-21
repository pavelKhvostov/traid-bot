"""Применение выведенных законов к ТЕКУЩЕМУ графику BTC 1h.

Тянет свежие 1h с Binance (fallback: CSV). Находит последние импульс-коррекция архетипы,
применяет FADE-закон + факторную силу + цель, рисует:
  - чёрный флагшток, оранжевые линии коррекции
  - ЗЕЛЁНАЯ стрелка = ЗАКОН (fade, против импульса) к +1.5ATR
  - СЕРЫЙ пунктир = учебник (континуация по measured-move) — помечен ФОЛЬКЛОР
+ текстовый разбор каждого сетапа по факторам.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/apply_current.py
Вывод: research/ta_laws/btc_current_lawread.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402

TB_ATR = 1.5


def fetch(symbol, interval, limit):
    import requests
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=20)
    r.raise_for_status()
    d = r.json()
    df = pd.DataFrame(d, columns=["t", "open", "high", "low", "close", "volume",
                                  "ct", "qv", "n", "tb", "tq", "ig"])
    df["open_time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.set_index("open_time")[["open", "high", "low", "close", "volume"]].astype(float)
    return df


def from_csv(sym, freq):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index().resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def trend(series, ts, td):
    a = series.asof(ts); b = series.asof(ts - td)
    return "UP" if (pd.notna(a) and pd.notna(b) and a > b) else "DOWN"


def candles(ax, sub, x0):
    for i, (_, r) in enumerate(sub.iterrows()):
        x = x0 + i
        up = r["close"] >= r["open"]
        col = "#e8a33d" if up else "#222"
        ax.plot([x, x], [r["low"], r["high"]], color=col, lw=0.7, zorder=2)
        a, b = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.32, a), 0.64, max(b - a, 1e-9), facecolor=col, edgecolor=col, zorder=3))


def main():
    src = "Binance (live)"
    try:
        df = fetch("BTCUSDT", "1h", 1000)
        d1d = fetch("BTCUSDT", "1d", 60)["close"]
    except Exception as ex:
        print(f"[live fetch fail: {ex}] -> CSV", flush=True)
        src = "CSV (до 11.06, live недоступен)"
        df = from_csv("BTCUSDT", "1h")
        d1d = from_csv("BTCUSDT", "1d")["close"]
    print(f"источник: {src}; 1h баров {len(df)}; последний {df.index[-1]}", flush=True)

    atr = G.compute_atr(df)
    c4 = df["close"].resample("4h", origin="epoch", label="left", closed="left").last().dropna()
    c1h = df["close"]
    arts = G.find_archetypes(df)
    # последние 3 завершённых архетипа (conf в пределах данных)
    arts = [a for a in arts if a.correction.pivots[-1].conf_i < len(df) - 1][-3:]

    fig, ax = plt.subplots(figsize=(19, 9))
    start = max(len(df) - 220, 0)
    sub = df.iloc[start:]
    candles(ax, sub, start)

    reads = []
    for a in arts:
        ai = a.correction.pivots[-1].conf_i
        arm_ts = df.index[ai]
        a_atr = atr[ai]
        d = a.impulse.direction
        fade_dir = "UP" if d == "DOWN" else "DOWN"
        # факторы
        depth = a.correction.depth_pct
        corrb = a.correction.bars
        mag = a.impulse.atr_mag
        against = a.correction.against_impulse
        mtf = sum(int(trend(s, arm_ts, td) == d) for s, td in
                  [(c1h, pd.Timedelta(hours=10)), (c4, pd.Timedelta(hours=40)), (d1d, pd.Timedelta(days=10))])
        cond = [corrb <= 10, mtf <= 1, against, depth < 50, mag < 4]
        score = sum(cond)
        strength = "СИЛЬНЫЙ" if score >= 4 else ("средний" if score >= 2 else "слабый")
        base = df["close"].values[ai]
        fade_tgt = base + TB_ATR * a_atr if fade_dir == "UP" else base - TB_ATR * a_atr
        fade_stop = base - TB_ATR * a_atr if fade_dir == "UP" else base + TB_ATR * a_atr
        mm = a.measured_move_tp  # учебник (континуация)

        # рисунок
        ax.plot([a.impulse.i0, a.impulse.i1], [a.impulse.p0, a.impulse.p1], color="#000", lw=1.4, zorder=5)
        col = "#c0392b" if against else "#f5a623"
        cu, cl = a.correction.upper, a.correction.lower
        ce = a.correction.pivots[-1].i
        for ln in (cu, cl):
            m = (ln[3] - ln[1]) / (ln[2] - ln[0]) if ln[2] != ln[0] else 0
            ax.plot([a.correction.pivots[0].i, ce], [ln[1], ln[1] + m * (ce - ln[0])], color=col, lw=1.5, zorder=5)
        # ЗАКОН: fade-стрелка
        ax.annotate("", xy=(ai + 14, fade_tgt), xytext=(ai, base),
                    arrowprops=dict(arrowstyle="-|>", color="#1a9850", lw=2.6,
                                    connectionstyle="arc3,rad=0.15"), zorder=7)
        ax.hlines(fade_tgt, ai + 8, ai + 18, color="#1a9850", lw=2, zorder=6)
        ax.hlines(fade_stop, ai + 2, ai + 10, color="#777", lw=1, ls=":", zorder=6)
        # учебник (фольклор)
        ax.annotate("", xy=(ai + 12, mm), xytext=(ai, base),
                    arrowprops=dict(arrowstyle="-|>", color="#999", lw=1.4, ls="--",
                                    connectionstyle="arc3,rad=-0.1"), zorder=4)
        ax.text(a.impulse.i0, a.impulse.p0, f" {a.correction.kind}", fontsize=7, color=col, fontweight="bold")

        reads.append({
            "time": arm_ts, "imp": d, "kind": a.correction.kind, "fade_dir": fade_dir,
            "score": score, "strength": strength, "base": base, "fade_tgt": fade_tgt,
            "fade_stop": fade_stop, "mm": mm, "depth": depth, "corrb": corrb, "mag": mag,
            "against": against, "mtf": mtf, "cond": cond,
        })

    ax.set_title(f"BTC 1h — применение законов исследования к ТЕКУЩЕМУ графику [{src}]\n"
                 f"зелёная стрелка=ЗАКОН (fade против импульса, ±1.5ATR), серый пунктир=учебная континуация (ФОЛЬКЛОР)",
                 fontsize=10)
    ax.set_xlim(start - 2, len(df) + 22)
    ax.grid(alpha=0.15)
    xt = list(range(start, len(df), max((len(df) - start) // 10, 1)))
    ax.set_xticks(xt)
    ax.set_xticklabels([df.index[t].strftime("%m-%d\n%H:%M") for t in xt], fontsize=7)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    out = HERE / "btc_current_lawread.png"
    fig.savefig(out, dpi=120)
    print(f"saved {out}\n")

    print("=" * 96)
    print("РАЗБОР ПОСЛЕДНИХ СЕТАПОВ ПО ЗАКОНАМ:")
    for r in reads:
        print(f"\n--- {r['time']:%Y-%m-%d %H:%M}  импульс {r['imp']} {r['mag']:.1f}ATR -> {r['kind']}")
        print(f"  ЗАКОН (fade): ожидаем ход {r['fade_dir']} от {r['base']:.0f} к ~{r['fade_tgt']:.0f} (+1.5ATR), "
              f"стоп {r['fade_stop']:.0f}")
        print(f"  Сила сетапа: {r['strength']} ({r['score']}/5 усилителей)")
        names = ["коррекция короткая(<=10)", "против мульти-ТФ тренда(<=1/3)", "коррекция-против(флаг)",
                 "мелкая глубина(<50%)", "слабый импульс(<4ATR)"]
        for nm, ok in zip(names, r["cond"]):
            print(f"     [{'X' if ok else ' '}] {nm}")
        print(f"  факты: corr_bars={r['corrb']} mtf_align={r['mtf']}/3 depth={r['depth']:.0f}% against={r['against']}")
        print(f"  УЧЕБНИК (фольклор): продолжение {r['imp']} к measured-move {r['mm']:.0f} — статистически проигрышно "
              f"(WR 35%, -212R на истории)")


if __name__ == "__main__":
    main()
