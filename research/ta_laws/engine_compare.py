"""СРАВНЕНИЕ 3 движков монетизации — что каждый даёт нетто на фьючах (BTC/ETH/SOL, общий cost/sim/zone).

Дв.1  RANGE-FADE + магнит-ФИЛЬТР: дневной anchor, fade у anchor±0.5·ATR_d, фильтр clear-path (нет магнита
       дальше против) — добавляет проверенный механизм (+0.309R на арках) к тонкому v1 (+0.04R).
Дв.2  REVERSAL в сильную HTF block-зону: касание сильнейшей block-зоны (OB/RDRB 12h/1d) в полосе → fade к
       anchor (force/зона-сила Вадима как самостоятельный разворот).
Дв.3  HTF-СВИНГ sweep-reversal (12h): свип fractal-пивота + закрытие обратно → свинг-вход, RR2.5. Высокий ТФ
       (наш cost-закон: косты не съедают).

Все каузально, нетто косты 0.14%RT + funding, разбивки sym/год. Знаки уровней/стопов сверены (pitfall).
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/engine_compare.py
Выход: research/ta_laws/engine_compare_report.txt
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
from research.smc_adapter import (precompute_zone_events, snapshot_from_events,  # noqa: E402
                                  zone_confluence, ROLE, TF_W)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RT_FEE = 2 * (0.0005 + 0.0002)
FUND_8H = 0.0001


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def sim(h, l, c, ei, n, direction, entry, sl, tp, horizon, tf_h):
    """direction +1 long / -1 short. Вход на ei (цена уже на entry). net_R или None."""
    risk = abs(entry - sl)
    if risk <= 0 or entry <= 0:
        return None
    end = min(ei + horizon, n - 1); exitp = c[end]; held = end - ei
    for x in range(ei + 1, end + 1):   # вход на баре ei (close/level); управление со следующего (без entry-bar lookahead)
        if direction > 0:
            if l[x] <= sl:
                exitp = sl; held = x - ei; break
            if h[x] >= tp:
                exitp = tp; held = x - ei; break
        else:
            if h[x] >= sl:
                exitp = sl; held = x - ei; break
            if l[x] <= tp:
                exitp = tp; held = x - ei; break
    gross = (exitp - entry) / entry * direction
    net = gross - RT_FEE - (held * tf_h / 8) * FUND_8H
    return net / (risk / entry)


def first_touch(h, l, lo_i, hi_i, level, side):
    """первый бар в [lo_i,hi_i] касающийся level. side='short'(high>=level)/'long'(low<=level)."""
    for x in range(lo_i, hi_i + 1):
        if (side == "short" and h[x] >= level) or (side == "long" and l[x] <= level):
            return x
    return None


def stat(s):
    if len(s) < 15:
        return f"n={len(s):>4} (мало)"
    R = s.net.values
    pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if R[R <= 0].sum() != 0 else 9.9
    sy = int((s.groupby('sym').net.mean() > 0).sum())
    yr = s.groupby('year').net.mean(); yp = int((yr > 0).sum())
    return (f"n={len(s):>5} exp={R.mean():>+6.3f}R WR={(R>0).mean()*100:>4.0f}% PF={pf:>4.2f} "
            f"tot={R.sum():>+7.1f}R sym{sy}/3 год{yp}/{yr.size}")


def main():
    rows1, rows2, rows3 = [], [], []
    for sym in SYMBOLS:
        print(f"[{sym}] load+precompute...", flush=True)
        d1 = load_1m(sym)
        h1 = rs(d1, "1h"); dd = rs(d1, "1d"); d12 = rs(d1, "12h")
        H = {"h": h1["high"].values, "l": h1["low"].values, "c": h1["close"].values, "idx": h1.index}
        atr_d = pd.Series(G.compute_atr(dd), index=dd.index).shift(1)
        ev, resampled = precompute_zone_events(d1, tfs=("12h", "1d"), types=("OB", "RDRB", "ob_liq", "FVG", "fractal"))

        # ── Дв.1 + Дв.2: по дням ──
        for day_open, drow in dd.iterrows():
            a = atr_d.get(day_open)
            if a is None or not (a > 0):
                continue
            anchor = drow["open"]
            mask = (h1.index >= day_open) & (h1.index < day_open + pd.Timedelta(days=1))
            di = np.where(mask)[0]
            if len(di) < 6:
                continue
            lo_i, hi_i = di[0], di[-1]
            zones = snapshot_from_events(ev, resampled, d1, day_open)

            # Дв.1: LONG fade у anchor-0.5ATR (рабочая сторона), фильтр clear-path
            lvl = anchor - 0.5 * a; sl = lvl - 0.5 * a; tp = anchor   # лонг: уровень/стоп НИЖЕ, tp выше ✓
            ti = first_touch(H["h"], H["l"], lo_i, hi_i, lvl, "long")
            if ti is not None:
                r = sim(H["h"], H["l"], H["c"], ti, len(H["c"]), +1, lvl, sl, tp, hi_i - ti, 1.0)
                if r is not None:
                    mag = zone_confluence(zones, anchor, "UP")["score"]   # магнит СНИЗУ против лонга
                    rows1.append({"sym": sym, "year": day_open.year, "net": r,
                                  "clear": mag < 20, "mag": mag})

            # Дв.2: reversal в СИЛЬНУЮ block-зону (выше→short, ниже→long), сильнейшая за день
            block = [z for z in zones if ROLE.get(z.type) == "block" and 0.3 * a <= z.distance_pct / 100 * anchor <= 1.6 * a]
            def zstr(z):
                return TF_W.get(z.tf, 1) * max(0, 1 - z.distance_pct / 6)
            for side, zside, d in [("short", "above", -1), ("long", "below", +1)]:
                cand = [z for z in block if z.side == zside]
                if not cand:
                    continue
                z = max(cand, key=zstr)
                edge = z.lo if side == "short" else z.hi    # первое касание зоны
                if side == "short" and not (anchor < edge):
                    continue
                if side == "long" and not (edge < anchor):
                    continue
                slz = (z.hi + 0.3 * a) if side == "short" else (z.lo - 0.3 * a)  # стоп за зоной
                ti = first_touch(H["h"], H["l"], lo_i, hi_i, edge, side)
                if ti is None:
                    continue
                r = sim(H["h"], H["l"], H["c"], ti, len(H["c"]), d, edge, slz, anchor, hi_i - ti, 1.0)
                if r is not None:
                    rows2.append({"sym": sym, "year": day_open.year, "net": r, "side": side})

        # ── Дв.3: HTF-свинг sweep-reversal на 12h ──
        c12 = d12["close"].values; h12 = d12["high"].values; l12 = d12["low"].values
        atr12 = G.compute_atr(d12); piv = G.zigzag(d12)
        n12 = len(d12)
        for p in piv:
            if p.conf_i >= n12 - 1 or p.conf_i < 5:
                continue
            ci = p.conf_i; aa = atr12[ci]
            if not (aa > 0):
                continue
            # свип: пивот-low пробит вниз и закрытие обратно выше → LONG; пивот-high → SHORT
            if p.kind == "L" and l12[ci] < p.price and c12[ci] > p.price:
                entry = c12[ci]; sl = l12[ci] - 0.2 * aa; risk = entry - sl
                if risk <= 0:
                    continue
                tp = entry + 2.5 * risk
                r = sim(h12, l12, c12, ci, n12, +1, entry, sl, tp, 30, 12.0)
                if r is not None:
                    rows3.append({"sym": sym, "year": d12.index[ci].year, "net": r, "side": "long"})
            elif p.kind == "H" and h12[ci] > p.price and c12[ci] < p.price:
                entry = c12[ci]; sl = h12[ci] + 0.2 * aa; risk = sl - entry
                if risk <= 0:
                    continue
                tp = entry - 2.5 * risk
                r = sim(h12, l12, c12, ci, n12, -1, entry, sl, tp, 30, 12.0)
                if r is not None:
                    rows3.append({"sym": sym, "year": d12.index[ci].year, "net": r, "side": "short"})

    T1 = pd.DataFrame(rows1); T2 = pd.DataFrame(rows2); T3 = pd.DataFrame(rows3)
    out = []
    out.append("СРАВНЕНИЕ 3 ДВИЖКОВ МОНЕТИЗАЦИИ — BTC/ETH/SOL, фьюч нетто (0.14%RT+funding), каузально.\n")
    out.append("=== Дв.1 RANGE-FADE (LONG откуп низа) + магнит-ФИЛЬТР ===")
    out.append(f"  все:            {stat(T1)}")
    out.append(f"  clear-path:     {stat(T1[T1.clear])}")
    out.append(f"  магнит-против:  {stat(T1[~T1.clear])}")
    out.append("\n=== Дв.2 REVERSAL в сильную HTF block-зону ===")
    out.append(f"  все:            {stat(T2)}")
    if len(T2):
        out.append(f"  SHORT (в зону сверху): {stat(T2[T2.side=='short'])}")
        out.append(f"  LONG  (в зону снизу):  {stat(T2[T2.side=='long'])}")
    out.append("\n=== Дв.3 HTF-СВИНГ sweep-reversal (12h, RR2.5) ===")
    out.append(f"  все:            {stat(T3)}")
    if len(T3):
        out.append(f"  LONG  (свип low):  {stat(T3[T3.side=='long'])}")
        out.append(f"  SHORT (свип high): {stat(T3[T3.side=='short'])}")
    out.append("\n=== ЧТО КАЖДЫЙ ДАЁТ (сводка) ===")
    for nm, T, extra in [("Дв.1 range-fade+фильтр", T1[T1.clear] if len(T1) else T1, "много сделок, тонкий edge"),
                         ("Дв.2 reversal-zone", T2, "реже, разворот у зон"),
                         ("Дв.3 HTF-свинг", T3, "редко, крупный RR, низкий cost-drag")]:
        s = stat(T) if len(T) else "n=0"
        out.append(f"  {nm:28} {s}  [{extra}]")

    rep = HERE / "engine_compare_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[cmp] -> {rep.name}")


if __name__ == "__main__":
    main()
