"""Тест: усиливает ли zone-strength Вадима (smc-канон) нетто-R наших arc-сетапов сверх простого mtf?

Для каждого arc-сетапа (fade конца дуги) считаем ДВА слоя аналитики:
  (наш)   mtf-контекст: сколько ТФ {1h,4h,1d} согласны с fade-направлением (aligned = >=2);
  (Вадим) zone-confluence: сила канон-зон у цены по fade-направлению (его детекторы+движок+законы силы),
          через research/smc_adapter (precompute_zone_events + snapshot_from_events, КАУЗАЛЬНО).
Симуляция фьюч-сделки (вход OPEN next bar, SL 1.5ATR, RR 2.0, косты 0.14%RT+funding). Сравниваем нетто-R:
  baseline / mtf-aligned / zone-high / (mtf-aligned ∩ zone-high) — даёт ли его слой ЛИФТ сверх нашего.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/zone_confluence_test.py
Выход: research/ta_laws/zone_confluence_report.txt + zone_conf_trades.csv
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
import curves as C    # noqa: E402
from research.smc_adapter import (  # noqa: E402
    precompute_zone_events, snapshot_from_events, zone_confluence, ZTYPES_FAST)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ZONE_TFS = ("4h", "12h", "1d")          # HTF-контекст зон (быстрее + сильнее по его закону)
ARC_TFS = [("1h", "1h", 1.0), ("4h", "4h", 4.0)]
TB_ATR_SL = 1.5
RR = 2.0
RT_FEE = 2 * (0.0005 + 0.0002)          # 0.14% round-trip
FUND_8H = 0.0001


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def trend(series, ts, td):
    a = series.asof(ts); b = series.asof(ts - td)
    return "UP" if (pd.notna(a) and pd.notna(b) and a > b) else "DOWN"


def simulate(o, h, l, c, ei, d, atr_a, tf_hours, n):
    if ei >= n or atr_a <= 0 or o[ei] <= 0:
        return None
    entry = o[ei]; risk = TB_ATR_SL * atr_a
    stop = entry - risk * d; tp = entry + RR * risk * d
    end = min(ei + 60, n - 1); exitp = c[end]; held = end - ei; out = "to"
    for x in range(ei, end + 1):
        sl = (l[x] <= stop) if d > 0 else (h[x] >= stop)
        tph = (h[x] >= tp) if d > 0 else (l[x] <= tp)
        if sl:
            exitp = stop; held = x - ei; out = "L"; break
        if tph:
            exitp = tp; held = x - ei; out = "W"; break
    gross = (exitp - entry) / entry * d
    net = gross - RT_FEE - (held * tf_hours / 8) * FUND_8H
    return net / (risk / entry)


def main():
    rows = []
    for sym in SYMBOLS:
        print(f"[{sym}] load 1m + precompute zones...", flush=True)
        d1 = load_1m(sym)
        ev, resampled = precompute_zone_events(d1, tfs=ZONE_TFS, types=ZTYPES_FAST)
        mtf = {"1h": (rs(d1, "1h")["close"], pd.Timedelta(hours=10)),
               "4h": (rs(d1, "4h")["close"], pd.Timedelta(hours=40)),
               "1d": (rs(d1, "1d")["close"], pd.Timedelta(days=10))}
        for tlabel, freq, tfh in ARC_TFS:
            df = rs(d1, freq); n = len(df)
            o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
            atr = G.compute_atr(df)
            arcs = C.find_arcs(df, atr=atr)
            print(f"  {sym} {tlabel}: arcs {len([a for a in arcs if 25<=a.i1<n-3])}", flush=True)
            for a in arcs:
                i1 = a.i1
                if i1 < 25 or i1 >= n - 3:
                    continue
                L = a.i1 - a.i0; aa, bb, _ = a.coeffs
                end_dir = "UP" if (2 * aa * L + bb) > 0 else "DOWN"
                fade = "UP" if end_dir == "DOWN" else "DOWN"
                apex = (a.apex_i - a.i0) / max(L, 1)
                if not (a.sagitta_atr >= 2.5 and apex >= 0.4):   # базовое условие формы (как раньше)
                    continue
                arm_ts = df.index[i1]; price = float(c[i1])
                # наш mtf-контекст по fade
                mtf_f = sum(int(trend(s, arm_ts, td) == fade) for s, (s_, td) in
                            [(mtf["1h"][0], mtf["1h"]), (mtf["4h"][0], mtf["4h"]), (mtf["1d"][0], mtf["1d"])])
                # его zone-confluence (каузально)
                zones = snapshot_from_events(ev, resampled, d1, arm_ts)
                zc = zone_confluence(zones, price, fade)
                d = 1 if fade == "UP" else -1
                R = simulate(o, h, l, c, i1 + 1, d, atr[i1], tfh, n)
                if R is None:
                    continue
                rows.append({"sym": sym, "tf": tlabel, "year": arm_ts.year, "fade": fade,
                             "mtf_f": mtf_f, "zscore": zc["score"], "nblock": zc["n_block"],
                             "ntot": zc["n_total"], "R": R})
    T = pd.DataFrame(rows)
    T.to_csv(HERE / "zone_conf_trades.csv", index=False)

    def st(s):
        if len(s) < 15:
            return f"n={len(s)} (мало)"
        R = s.R.values; pf = R[R > 0].sum() / abs(R[R <= 0].sum()) if (R <= 0).any() and R[R <= 0].sum() != 0 else 9.9
        sy = int((s.groupby('sym').R.mean() > 0).sum())
        yr = s.groupby('year').R.mean(); yp = int((yr > 0).sum())
        return f"n={len(s):>4} exp={R.mean():>+6.3f}R WR={ (R>0).mean()*100:>4.0f}% PF={pf:>4.2f} tot={R.sum():>+6.1f}R sym{sy}/3 год{yp}/{yr.size}"

    out = []
    out.append("ZONE-CONFLUENCE (Вадим) vs MTF (наш) на arc-сетапах — BTC/ETH/SOL, фьюч нетто, SL1.5/RR2.")
    out.append(f"Зоны: канон smc-lib (OB/FVG/fractal/RDRB/ob_liq/marubozu) на {ZONE_TFS}, каузально.")
    out.append(f"Всего сетапов: {len(T)}\n")
    zhi = T.zscore.quantile(0.66); zlo = T.zscore.quantile(0.33)
    out.append("=== СЛОИ АНАЛИТИКИ (нетто-R) ===")
    out.append(f"  baseline (все arc-сетапы)            {st(T)}")
    out.append(f"  наш MTF-aligned (fade в тренд >=2/3) {st(T[T.mtf_f >= 2])}")
    out.append(f"  наш MTF-против (<=1/3)               {st(T[T.mtf_f <= 1])}")
    out.append(f"  его ZONE-high (z>={zhi:.1f}, верх трети) {st(T[T.zscore >= zhi])}")
    out.append(f"  его ZONE-low  (z<={zlo:.1f}, низ трети)  {st(T[T.zscore <= zlo])}")
    out.append(f"  его ZONE block>=1 у цены             {st(T[T.nblock >= 1])}")
    out.append("\n=== ДАЁТ ЛИ ЕГО СЛОЙ ЛИФТ СВЕРХ НАШЕГО MTF? ===")
    base = T[T.mtf_f >= 2]
    out.append(f"  MTF-aligned ВСЕ                      {st(base)}")
    out.append(f"  MTF-aligned ∩ ZONE-high             {st(base[base.zscore >= zhi])}")
    out.append(f"  MTF-aligned ∩ ZONE-low              {st(base[base.zscore <= zlo])}")
    out.append(f"  MTF-aligned ∩ block>=1              {st(base[base.nblock >= 1])}")
    out.append("\n=== ОБРАТНО: даёт ли MTF лифт сверх его ZONE? ===")
    zbase = T[T.zscore >= zhi]
    out.append(f"  ZONE-high ВСЕ                        {st(zbase)}")
    out.append(f"  ZONE-high ∩ MTF-aligned             {st(zbase[zbase.mtf_f >= 2])}")
    out.append(f"  ZONE-high ∩ MTF-против              {st(zbase[zbase.mtf_f <= 1])}")

    rep = HERE / "zone_confluence_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[zone] -> {rep.name}")


if __name__ == "__main__":
    main()
