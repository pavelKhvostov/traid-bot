"""etap_208 — ОБЪЕДИНЕНИЕ Bulkowski (etap_172) × дневной анализатор (etap_201).

Для каждого Bulkowski 12h reversal-сигнала берём структурный read дня (та же логика,
что в etap_201: EMA-тренд + value-migration + premium/discount + дневной delta = bias;
+ VP/HVN/POC + ICT OB/FVG + DOL) и считаем conf-факторы:
  - bias_agree    : дневной bias совпал со стороной паттерна
  - loc_agree     : short у premium (posVA>0.6) / long у discount (posVA<0.4)
  - migr_agree    : value-migration по стороне
  - zone_at_break : breakout рядом (≤0.5·ATR) с сильной зоной/DOL
conf 0..4. Смотрим исход (ult_move_pct, half-target, busted) vs conf — ПО ГОДАМ.

Полная история 2020-2026 (520 сигналов). Фокус: 2020 (ранний) vs 2026 (свежий).
Запуск: venv/Scripts/python.exe research/daily_engine/etap_208_bulkowski_x_daily.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_201_daily_analyzer as A

ROOT = HERE.parent.parent
SIG_GEOM = ROOT / "research/elements_study/output/etap_172_all_signals_geom.csv"
SIG_OUT  = ROOT / "research/elements_study/output/etap_172_signals.csv"


def daily_struct(d, f, atr14, ema20, ema50, day, price):
    """Структурный read дня (deterministic часть etap_201), на предрасчитанных сериях."""
    day = pd.Timestamp(day)
    day = (day.tz_localize("UTC") if day.tzinfo is None else day.tz_convert("UTC")).normalize()
    if day not in d.index:
        prev = d.index[d.index <= day]
        if len(prev) == 0: return None
        day = prev[-1]
    di = d.index.get_loc(day)
    if di < 65: return None
    o, h, l, c, v = (d[x].values for x in ["open", "high", "low", "close", "volume"])
    a14 = atr14.iloc[di-1]
    w = slice(max(0, di-60), di)
    hvn, lvn = A.hvn_lvn(h[w], l[w], v[w], price)
    vpoc, vah, val = A.vpoc_va(h[w], l[w], v[w])
    zz = A.ict_zones(o[w], h[w], l[w], c[w], price, a14)
    fh = [h[i] for i in range(di-60, di-2) if h[i] > max(h[i-2:i].max(), h[i+1:i+3].max())]
    fl = [l[i] for i in range(di-60, di-2) if l[i] < min(l[i-2:i].min(), l[i+1:i+3].min())]
    bsl = min([x for x in fh if x > price], default=None)
    ssl = max([x for x in fl if x < price], default=None)
    e20 = ema20.iloc[di-1]; e50 = ema50.iloc[di-1]
    vpoc_prev, _, _ = A.vpoc_va(h[max(0, di-65):di-5], l[max(0, di-65):di-5], v[max(0, di-65):di-5])
    val_migr = "up" if vpoc > vpoc_prev*1.002 else ("down" if vpoc < vpoc_prev*0.998 else "flat")
    pos_va = (price - val)/(vah - val) if vah > val else 0.5
    delta_d = float(f.loc[day, "delta_norm"]) if "delta_norm" in f.columns and day in f.index else 0.0
    score = 0
    score += 1 if price > e20 else -1
    score += 1 if e20 > e50 else -1
    score += 1 if val_migr == "up" else (-1 if val_migr == "down" else 0)
    score += -1 if pos_va > 0.8 else (1 if pos_va < 0.2 else 0)
    score += 1 if delta_d > 0 else -1
    bias = "LONG" if score >= 2 else ("SHORT" if score <= -2 else "NEUTRAL")
    strong = [x for x in [vpoc, vah, val, bsl, ssl] if x is not None] + list(hvn)
    for z in zz.values():
        if z: strong += [z[0], z[1]]
    return dict(bias=bias, score=score, pos_va=pos_va, val_migr=val_migr, atr=a14, strong=strong)


def agg_block(r, title):
    print(f"\n{title}  (n={len(r)})")
    print(f"  {'conf':>6} {'n':>4} {'avg_ult':>8} {'half%':>6} {'busted%':>8}")
    for lvl in sorted(r["conf"].unique()):
        s = r[r["conf"] == lvl]
        print(f"  {lvl:>6} {len(s):>4} {s['ult'].mean():>+7.2f}% {s['win_half'].mean()*100:>5.0f}% "
              f"{(s['busted']==True).mean()*100:>7.0f}%")
    hi, lo = r[r["conf"] >= 2], r[r["conf"] <= 1]
    if len(hi) and len(lo):
        print(f"  {'≥2':>6} {len(hi):>4} {hi['ult'].mean():>+7.2f}% {hi['win_half'].mean()*100:>5.0f}% {(hi['busted']==True).mean()*100:>7.0f}%   (усилены)")
        print(f"  {'≤1':>6} {len(lo):>4} {lo['ult'].mean():>+7.2f}% {lo['win_half'].mean()*100:>5.0f}% {(lo['busted']==True).mean()*100:>7.0f}%   (нет)")
    ba1, ba0 = r[r.bias_agree == 1], r[r.bias_agree == 0]
    if len(ba1) and len(ba0):
        print(f"  bias_agree=1: n={len(ba1):>3} ult {ba1['ult'].mean():+.2f}%  |  bias_agree=0: n={len(ba0):>3} ult {ba0['ult'].mean():+.2f}%")


def main():
    geom = pd.read_csv(SIG_GEOM)
    out = pd.read_csv(SIG_OUT)[["time", "pattern", "side", "ult_move_pct", "busted"]]
    df = geom.merge(out, on=["time", "pattern", "side"], how="left")
    df["reached_half_target"] = df["ult_move_pct"] >= df["height_pct"] / 2
    df["day"] = pd.to_datetime(df["time"], utc=True).dt.normalize()
    df["year"] = pd.to_datetime(df["time"], utc=True).dt.year

    # предрасчёт дневных серий один раз
    d = A.daily_from_flow("BTCUSDT")
    f = A.build_features(d).shift(1)
    atr14 = A.atr(d, 14); ema20 = A.ema(d["close"], 20); ema50 = A.ema(d["close"], 50)

    rows = []
    for _, s in df.iterrows():
        st = daily_struct(d, f, atr14, ema20, ema50, s["day"], s["breakout_price"])
        if st is None or pd.isna(s["ult_move_pct"]):
            continue
        long = s["side"] == "long"
        bias_agree = (long and st["bias"] == "LONG") or ((not long) and st["bias"] == "SHORT")
        loc_agree = ((not long) and st["pos_va"] > 0.6) or (long and st["pos_va"] < 0.4)
        migr_agree = (long and st["val_migr"] == "up") or ((not long) and st["val_migr"] == "down")
        near = min((abs(s["breakout_price"] - z) for z in st["strong"]), default=1e9)
        zone = near <= 0.5 * st["atr"]
        conf = int(bias_agree) + int(loc_agree) + int(migr_agree) + int(zone)
        rows.append(dict(year=int(s["year"]), pattern=s["pattern"], side=s["side"],
                         bias_agree=int(bias_agree), loc_agree=int(loc_agree),
                         migr_agree=int(migr_agree), zone=int(zone), conf=conf,
                         ult=s["ult_move_pct"], win_half=bool(s["reached_half_target"]),
                         busted=s["busted"]))
    r = pd.DataFrame(rows)
    print("="*72)
    print(f"Bulkowski × дневной анализатор — конфлюэнс, {len(r)} сигналов, BTC 12h")
    print("="*72)

    agg_block(r, "■ ВСЯ ИСТОРИЯ 2020-2026")
    print("\n" + "="*72)
    print("ПО ГОДАМ (avg_ult / busted% для усилённых ≥2 vs нет ≤1)")
    print("="*72)
    print(f"  {'year':>4} {'n':>4} | {'≥2 n':>5} {'≥2 ult':>8} {'≥2 bust':>8} | {'≤1 n':>5} {'≤1 ult':>8} {'≤1 bust':>8}")
    for y in sorted(r["year"].unique()):
        ry = r[r["year"] == y]; hi, lo = ry[ry.conf >= 2], ry[ry.conf <= 1]
        hib = f"{hi['ult'].mean():+.1f}%" if len(hi) else "—"
        hbust = f"{(hi['busted']==True).mean()*100:.0f}%" if len(hi) else "—"
        lob = f"{lo['ult'].mean():+.1f}%" if len(lo) else "—"
        lbust = f"{(lo['busted']==True).mean()*100:.0f}%" if len(lo) else "—"
        print(f"  {y:>4} {len(ry):>4} | {len(hi):>5} {hib:>8} {hbust:>8} | {len(lo):>5} {lob:>8} {lbust:>8}")

    agg_block(r[r["year"] == 2020], "■ ФОКУС 2020 (ранний, COVID-режим)")
    agg_block(r[r["year"] == 2026], "■ ФОКУС 2026 (свежий)")

    r.to_csv(A.OUT / "etap_208_bulkowski_x_daily_full.csv", index=False)
    print(f"\nSaved: {A.OUT / 'etap_208_bulkowski_x_daily_full.csv'}")


if __name__ == "__main__":
    main()
