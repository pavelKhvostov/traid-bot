"""B8 range-fade v2 — УМНЫЙ уровень: ближайшая канон-зона Вадима как граница диапазона (vs плоский ATR).

v1 подтвердил премису (внутр. realistic > физич.), но плоский anchor±0.5·ATR тонок. Реальный edge B8 —
прогноз ДОСТИЖИМОГО уровня через ЗОНЫ: дневной диапазон упирается в канон-зоны (12h/1d block/liquidity/
inefficiency). Уровень fade = ближайшая зона в полосе [anchor+0.2·ATR_d, anchor+1.3·ATR_d] (и зеркально вниз).
Сравниваем нетто-R: ZONE-уровень vs плоский ATR=0.5 (v1-бейзлайн). Каузально (snapshot на anchor).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/b8_range_fade_v2.py
Выход: research/ta_laws/b8_range_fade_v2_report.txt
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
from research.smc_adapter import precompute_zone_events, snapshot_from_events, ROLE  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ZONE_TFS = ("12h", "1d")               # дневные границы диапазона
ZTYPES = ("OB", "FVG", "RDRB", "ob_liq", "fractal")
BAND_LO, BAND_HI = 0.2, 1.3            # полоса поиска зоны в ATR_d от anchor
BUFFER = 0.5
RT_FEE = 2 * (0.0005 + 0.0002)
FUND_8H = 0.0001


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def nearest_zone_level(zones, anchor, a, side):
    """Ближайшая зона-граница в полосе. side='above'(для SHORT) / 'below'(для LONG)."""
    lo_b = anchor + (BAND_LO * a if side == "above" else -BAND_HI * a)
    hi_b = anchor + (BAND_HI * a if side == "above" else -BAND_LO * a)
    cand = []
    for z in zones:
        lvl = z.level if z.level is not None else (z.hi if side == "below" else z.lo)
        # для SHORT (above) берём НИЖНЮЮ грань зоны (первое касание), для LONG — верхнюю
        edge = z.lo if side == "above" else z.hi
        if lo_b <= edge <= hi_b:
            cand.append((abs(edge - anchor), edge))
    if not cand:
        return None
    return min(cand)[1]


def fade_day(day1h, level, side, sl, tp):
    h = day1h["high"].values; l = day1h["low"].values; c = day1h["close"].values
    n = len(day1h); ei = None
    for x in range(n):
        if (side == "short" and h[x] >= level) or (side == "long" and l[x] <= level):
            ei = x; break
    if ei is None:
        return None
    exitp = c[-1]
    for x in range(ei, n):
        if side == "short":
            if h[x] >= sl:
                exitp = sl; break
            if l[x] <= tp:
                exitp = tp; break
        else:
            if l[x] <= sl:
                exitp = sl; break
            if h[x] >= tp:
                exitp = tp; break
    d = -1 if side == "short" else 1
    gross = (exitp - level) / level * d
    return gross, (n - ei)


def run(sym):
    d1 = load_1m(sym)
    h1 = rs(d1, "1h"); dd = rs(d1, "1d")
    atr_d = pd.Series(G.compute_atr(dd), index=dd.index).shift(1)
    ev, resampled = precompute_zone_events(d1, tfs=ZONE_TFS, types=ZTYPES)
    rows = []
    for day_open, drow in dd.iterrows():
        a = atr_d.get(day_open)
        if a is None or not (a > 0):
            continue
        anchor = drow["open"]
        day1h = h1.loc[(h1.index >= day_open) & (h1.index < day_open + pd.Timedelta(days=1))]
        if len(day1h) < 6:
            continue
        zones = snapshot_from_events(ev, resampled, d1, day_open)
        for side, zside in [("short", "above"), ("long", "below")]:
            d = -1 if side == "short" else 1
            # ZONE-уровень
            zl = nearest_zone_level(zones, anchor, a, zside)
            # ATR-бейзлайн R=0.5 (шорт d=-1 → уровень ВЫШЕ anchor; лонг → НИЖЕ)
            atrl = anchor - d * 0.5 * a
            for tag, lvl in [("zone", zl), ("atr", atrl)]:
                if lvl is None:
                    continue
                risk = BUFFER * a
                sl = lvl - d * BUFFER * a; tp = anchor   # шорт(d=-1)→стоп ВЫШЕ; лонг(d=1)→стоп НИЖЕ
                res = fade_day(day1h, lvl, side, sl, tp)
                if res is None:
                    continue
                gross, held = res
                net = gross - RT_FEE - (held / 8) * FUND_8H
                rows.append({"sym": sym, "year": day_open.year, "side": side, "tag": tag,
                             "net": net / (risk / lvl)})
    return rows


def stat(s):
    if len(s) < 20:
        return f"n={len(s)} (мало)"
    R = s.net.values
    pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if R[R <= 0].sum() != 0 else 9.9
    sy = int((s.groupby('sym').net.mean() > 0).sum())
    yr = s.groupby('year').net.mean(); yp = int((yr > 0).sum())
    return (f"n={len(s):>5} exp={R.mean():>+6.3f}R WR={ (R>0).mean()*100:>4.0f}% PF={pf:>4.2f} "
            f"tot={R.sum():>+7.1f}R sym{sy}/3 год{yp}/{yr.size}")


def main():
    rows = []
    for sym in SYMBOLS:
        print(f"[{sym}] precompute+fade...", flush=True)
        rows += run(sym)
    T = pd.DataFrame(rows)
    out = []
    out.append("B8 range-fade v2: УМНЫЙ уровень (канон-зона Вадима) vs плоский ATR=0.5 — BTC/ETH/SOL, фьюч нетто.")
    out.append(f"Зоны {ZONE_TFS} {ZTYPES}, полоса [{BAND_LO},{BAND_HI}]·ATR_d, каузально. Косты {RT_FEE*100:.2f}%RT.\n")
    out.append("=== ZONE-уровень vs ATR-уровень (нетто-R/сделку) ===")
    out.append(f"  ZONE все:          {stat(T[T.tag=='zone'])}")
    out.append(f"  ATR  все (v1-база): {stat(T[T.tag=='atr'])}")
    out.append("\n=== по стороне ===")
    for tag in ("zone", "atr"):
        out.append(f"  [{tag}] SHORT (fade HIGH): {stat(T[(T.tag==tag)&(T.side=='short')])}")
        out.append(f"  [{tag}] LONG  (fade LOW):  {stat(T[(T.tag==tag)&(T.side=='long')])}")
    out.append("\n=== ZONE LONG (откуп низа у зоны) — по символам/годам ===")
    zl = T[(T.tag=='zone') & (T.side=='long')]
    for sym in SYMBOLS:
        out.append(f"  {sym}: {stat(zl[zl.sym==sym])}")
    out.append("\n=== ВЕРДИКТ ===")
    z = T[T.tag=='zone'].net.mean(); atr = T[T.tag=='atr'].net.mean()
    out.append(f"  ZONE-уровень exp={z:+.3f}R vs ATR-уровень exp={atr:+.3f}R -> "
               f"{'зоны Вадима ЛУЧШЕ (его слой даёт лифт)' if z > atr else 'зоны НЕ лучше плоского ATR'}")
    rep = HERE / "b8_range_fade_v2_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[b8v2] -> {rep.name}")


if __name__ == "__main__":
    main()
