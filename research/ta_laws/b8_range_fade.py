"""МОНЕТИЗАЦИЯ Движка-1 (B8 принцип): range-fade у ДОСТИЖИМЫХ уровней vs наивных физических.

Принцип B8/Realistic-Target Вадима: «достижимый» внутренний уровень (realistic HIGH/LOW) фейдится
надёжнее физического экстремума («дельта недоступности» из-за хаоса). Тест монетизации БЕЗ его нейросети
(весов нет, torch=CPU): дневной anchor (1d open 00:00 UTC) + трейлинг ATR_d (каузально) → forecast
HIGH/LOW = anchor ± R·ATR_d. Внутридневной fade: первое касание уровня → контр-вход, TP=возврат к anchor,
SL=за уровнем (buffer·ATR_d). Грид R: внутренние R<1 (realistic) vs внешние R>=1 (физические).
Если внутренние бьют по нетто-R/PF — премиса B8 монетизируема. Косты фьюч: 0.14%RT + funding.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/b8_range_fade.py
Выход: research/ta_laws/b8_range_fade_report.txt
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
R_GRID = [0.5, 0.7, 0.9, 1.1, 1.3]     # множитель ATR_d уровня (внутр. realistic <1 vs физич. >=1)
BUFFER = 0.5                            # стоп за уровнем = BUFFER·ATR_d (риск)
RT_FEE = 2 * (0.0005 + 0.0002)         # 0.14% round-trip
FUND_8H = 0.0001
RNG = np.random.default_rng(41)


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def fade_day(day1h, anchor, level, side, sl, tp, atr_d):
    """side='short' (fade у HIGH) или 'long' (fade у LOW). Внутри дня: касание level → вход, TP/SL/таймаут.
    Возврат net_R или None (не коснулись)."""
    h = day1h["high"].values; l = day1h["low"].values; c = day1h["close"].values
    n = len(day1h)
    ei = None
    for x in range(n):
        if (side == "short" and h[x] >= level) or (side == "long" and l[x] <= level):
            ei = x; break
    if ei is None:
        return None
    risk = BUFFER * atr_d
    exitp = c[-1]; out = "to"
    for x in range(ei + 1, n):   # вход=level на баре ei; управление со следующего (без entry-bar lookahead)
        if side == "short":
            if h[x] >= sl:
                exitp = sl; out = "L"; break
            if l[x] <= tp:
                exitp = tp; out = "W"; break
        else:
            if l[x] <= sl:
                exitp = sl; out = "L"; break
            if h[x] >= tp:
                exitp = tp; out = "W"; break
    d = -1 if side == "short" else 1
    gross = (exitp - level) / level * d
    held_h = n - ei
    net = gross - RT_FEE - (held_h / 8) * FUND_8H
    return net / (risk / level)


def run(sym, R):
    d1 = load_1m(sym)
    h1 = rs(d1, "1h")
    dd = rs(d1, "1d")
    atr_d = pd.Series(G.compute_atr(dd), index=dd.index).shift(1)   # ТРЕЙЛИНГ (каузально)
    rows = []
    for day_open, drow in dd.iterrows():
        a = atr_d.get(day_open)
        if a is None or not (a > 0):
            continue
        anchor = drow["open"]
        day1h = h1.loc[(h1.index >= day_open) & (h1.index < day_open + pd.Timedelta(days=1))]
        if len(day1h) < 6:
            continue
        # SHORT fade у HIGH
        hi = anchor + R * a; sl_h = hi + BUFFER * a; tp_h = anchor
        rs_ = fade_day(day1h, anchor, hi, "short", sl_h, tp_h, a)
        if rs_ is not None:
            rows.append({"sym": sym, "year": day_open.year, "side": "short", "R": R, "net": rs_})
        # LONG fade у LOW
        lo = anchor - R * a; sl_l = lo - BUFFER * a; tp_l = anchor
        rl = fade_day(day1h, anchor, lo, "long", sl_l, tp_l, a)
        if rl is not None:
            rows.append({"sym": sym, "year": day_open.year, "side": "long", "R": R, "net": rl})
    return rows


def stat(s):
    if len(s) < 20:
        return f"n={len(s)} (мало)"
    R = s.net.values
    pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if R[R <= 0].sum() != 0 else 9.9
    sy = int((s.groupby('sym').net.mean() > 0).sum())
    yr = s.groupby('year').net.mean(); yp = int((yr > 0).sum())
    fill = len(s)
    return (f"n={fill:>5} exp={R.mean():>+6.3f}R WR={ (R>0).mean()*100:>4.0f}% PF={pf:>4.2f} "
            f"tot={R.sum():>+7.1f}R sym{sy}/3 год{yp}/{yr.size}")


def main():
    allrows = []
    for sym in SYMBOLS:
        print(f"[{sym}]...", flush=True)
        for R in R_GRID:
            allrows += run(sym, R)
    T = pd.DataFrame(allrows)
    out = []
    out.append("МОНЕТИЗАЦИЯ B8-принципа: range-fade у достижимых vs физических уровней — BTC/ETH/SOL, фьюч нетто.")
    out.append("Anchor=1d open, ATR_d трейлинг (каузально). Fade: касание anchor±R·ATR_d → контр, TP=anchor, SL=buffer.")
    out.append(f"Косты {RT_FEE*100:.2f}%RT + funding. Buffer стоп {BUFFER}·ATR_d.\n")
    out.append("=== ПО R (внутр. realistic <1 vs физич. >=1) — нетто-R/сделку ===")
    out.append(f"{'R·ATR':>7}  {'тип':<10} | результат")
    for R in R_GRID:
        s = T[T.R == R]
        typ = "realistic" if R < 1.0 else "физич."
        out.append(f"{R:>7}  {typ:<10} | {stat(s)}")
    out.append("\n=== fill-rate (как часто уровень коснут за день) ===")
    for R in R_GRID:
        # fill = сколько сделок vs макс возможных (2/день). Грубо: n / (дней×2)
        s = T[T.R == R]
        out.append(f"  R={R}: сделок {len(s)} (внутр. уровни ближе → чаще касание)")
    out.append("\n=== ЛУЧШИЙ R: разбивки ===")
    best = max(R_GRID, key=lambda R: T[T.R == R].net.mean() if len(T[T.R == R]) > 20 else -9)
    b = T[T.R == best]
    out.append(f"Лучший R={best} ({'realistic' if best<1 else 'физич.'}):")
    out.append(f"  SHORT (fade HIGH): {stat(b[b.side=='short'])}")
    out.append(f"  LONG  (fade LOW):  {stat(b[b.side=='long'])}")
    for sym in SYMBOLS:
        out.append(f"  {sym}: {stat(b[b.sym==sym])}")
    out.append("\n=== ВЕРДИКТ ===")
    inner = T[T.R < 1.0].net.mean(); outer = T[T.R >= 1.0].net.mean()
    out.append(f"  Внутренние (realistic, R<1) exp={inner:+.3f}R vs физические (R>=1) exp={outer:+.3f}R "
               f"-> {'B8-премиса ПОДТВЕРЖДЕНА (внутр. лучше)' if inner > outer else 'внутр. НЕ лучше'}")
    bb = T[T.R == best]; bex = bb.net.mean(); bsy = int((bb.groupby('sym').net.mean() > 0).sum())
    yr = bb.groupby('year').net.mean(); byp = int((yr > 0).sum())
    verdict = ("МОНЕТИЗИРУЕМО (с оговорками)" if bex > 0 and bsy >= 2 and byp / yr.size >= 0.6
               else "НЕ монетизируемо нетто как есть")
    out.append(f"  Лучший R={best}: нетто {bex:+.3f}R, sym {bsy}/3, год {byp}/{yr.size} -> {verdict}")

    rep = HERE / "b8_range_fade_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[b8] -> {rep.name}")


if __name__ == "__main__":
    main()
