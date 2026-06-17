"""etap_209 — НОВЫЕ варианты взаимодействия Bulkowski × дневной анализатор.

Прорабатываем после провала conf-суммы (etap_208). Каждый сигнал получает богатый
дневной read; проверяем дискриминативность по busted/ult РАЗДЕЛЬНО:

  V2  realized-режим дня (big/flat) — работает ли разворот по-разному на трендовом/флэт дне
  V8  непрерывная bias-инверсия (aligned_bias: + = daily структура «за» паттерн)
  V9  тип зоны на breakout (OB / FVG / HVN / POC / DOL — раздельно)
  V5  room-to-DOL: запас до ближайшей ликвидности-цели (в ATR) → масштаб хода

Запуск: venv/Scripts/python.exe research/daily_engine/etap_209_bulkowski_interactions.py
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


def read_rich(d, f, atr14, ema20, ema50, big_series, day, price, side):
    day = pd.Timestamp(day)
    day = (day.tz_localize("UTC") if day.tzinfo is None else day.tz_convert("UTC")).normalize()
    if day not in d.index:
        prev = d.index[d.index <= day]
        if len(prev) == 0: return None
        day = prev[-1]
    di = d.index.get_loc(day)
    if di < 65: return None
    o, h, l, c, v = (d[x].values for x in ["open", "high", "low", "close", "volume"])
    a14 = float(atr14.iloc[di-1])
    if not np.isfinite(a14) or a14 <= 0: return None
    w = slice(max(0, di-60), di)
    hvn, _ = A.hvn_lvn(h[w], l[w], v[w], price)
    vpoc, vah, val = A.vpoc_va(h[w], l[w], v[w])
    zz = A.ict_zones(o[w], h[w], l[w], c[w], price, a14)
    fh = [h[i] for i in range(di-60, di-2) if h[i] > max(h[i-2:i].max(), h[i+1:i+3].max())]
    fl = [l[i] for i in range(di-60, di-2) if l[i] < min(l[i-2:i].min(), l[i+1:i+3].min())]
    bsl = min([x for x in fh if x > price], default=None)
    ssl = max([x for x in fl if x < price], default=None)
    e20 = float(ema20.iloc[di-1]); e50 = float(ema50.iloc[di-1])
    vpoc_prev, _, _ = A.vpoc_va(h[max(0, di-65):di-5], l[max(0, di-65):di-5], v[max(0, di-65):di-5])
    val_migr = 1 if vpoc > vpoc_prev*1.002 else (-1 if vpoc < vpoc_prev*0.998 else 0)
    pos_va = (price - val)/(vah - val) if vah > val else 0.5
    delta_d = float(f.loc[day, "delta_norm"]) if "delta_norm" in f.columns and day in f.index else 0.0
    score = 0
    score += 1 if price > e20 else -1
    score += 1 if e20 > e50 else -1
    score += val_migr
    score += -1 if pos_va > 0.8 else (1 if pos_va < 0.2 else 0)
    score += 1 if delta_d > 0 else -1

    long = side == "long"
    sgn = 1 if long else -1
    # V8: aligned_bias (+ => дневная структура согласна со стороной паттерна)
    aligned_bias = sgn * score
    # V9: тип зоны на breakout (в 0.5 ATR)
    def near(levels):
        levels = [x for x in levels if x is not None]
        return (min(abs(price - x) for x in levels) <= 0.5 * a14) if levels else False
    ob = near([zz['ob_bull'][1] if zz['ob_bull'] else None, zz['ob_bear'][0] if zz['ob_bear'] else None,
               zz['ob_bull'][0] if zz['ob_bull'] else None, zz['ob_bear'][1] if zz['ob_bear'] else None])
    fvg = near([zz['fvg_bull'][1] if zz['fvg_bull'] else None, zz['fvg_bear'][0] if zz['fvg_bear'] else None])
    hvn_n = near(hvn); poc_n = near([vpoc]); dol_n = near([bsl, ssl])
    # V5: room-to-DOL (в ATR) к цели по стороне (long→BSL сверху, short→SSL снизу)
    if long and bsl is not None: room = (bsl - price)/a14
    elif (not long) and ssl is not None: room = (price - ssl)/a14
    else: room = np.nan
    return dict(aligned_bias=aligned_bias, big=int(big_series.iloc[di]),
                ob=int(ob), fvg=int(fvg), hvn=int(hvn_n), poc=int(poc_n), dol=int(dol_n),
                room=room, pos_va=pos_va)


def split(r, mask, label):
    a, b = r[mask], r[~mask]
    print(f"  {label:<34} | да: n={len(a):>3} ult {a['ult'].mean():>+6.1f}% bust {(a['busted']==True).mean()*100:>3.0f}% "
          f"| нет: n={len(b):>3} ult {b['ult'].mean():>+6.1f}% bust {(b['busted']==True).mean()*100:>3.0f}%")


def main():
    geom = pd.read_csv(SIG_GEOM)
    out = pd.read_csv(SIG_OUT)[["time", "pattern", "side", "ult_move_pct", "busted"]]
    df = geom.merge(out, on=["time", "pattern", "side"], how="left")
    df["day"] = pd.to_datetime(df["time"], utc=True).dt.normalize()
    df["year"] = pd.to_datetime(df["time"], utc=True).dt.year

    d = A.daily_from_flow("BTCUSDT")
    f = A.build_features(d).shift(1)
    atr14 = A.atr(d, 14); ema20 = A.ema(d["close"], 20); ema50 = A.ema(d["close"], 50)
    rng = (d["high"] - d["low"]) / d["close"].shift(1)
    big_series = (rng > rng.rolling(30).median()).astype(int)

    rows = []
    for _, s in df.iterrows():
        if pd.isna(s["ult_move_pct"]): continue
        st = read_rich(d, f, atr14, ema20, ema50, big_series, s["day"], s["breakout_price"], s["side"])
        if st is None: continue
        st.update(year=int(s["year"]), side=s["side"], ult=s["ult_move_pct"], busted=s["busted"])
        rows.append(st)
    r = pd.DataFrame(rows)
    print("="*100); print(f"etap_209 — варианты взаимодействия, {len(r)} сигналов"); print("="*100)

    print("\n■ V2 — РЕЖИМ ДНЯ (realized big vs flat)")
    split(r, r["big"] == 1, "big-day (широкий)")

    print("\n■ V8 — bias-инверсия (aligned_bias: + = структура ЗА паттерн)")
    for lo, hi, lab in [(-99, -1, "aligned≤-1 (структура ПРОТИВ)"), (0, 0, "aligned=0"), (1, 99, "aligned≥+1 (структура ЗА)")]:
        s = r[(r["aligned_bias"] >= lo) & (r["aligned_bias"] <= hi)]
        if len(s): print(f"  {lab:<34} | n={len(s):>3} ult {s['ult'].mean():>+6.1f}% bust {(s['busted']==True).mean()*100:>3.0f}%")
    print(f"  corr(aligned_bias, ult) = {r['aligned_bias'].corr(r['ult']):+.3f} | corr(aligned_bias, busted) = {r['aligned_bias'].corr(r['busted'].astype(float)):+.3f}")

    print("\n■ V9 — ТИП ЗОНЫ на breakout (≤0.5 ATR)")
    for z in ["ob", "fvg", "hvn", "poc", "dol"]:
        split(r, r[z] == 1, f"breakout у {z.upper()}")

    print("\n■ V5 — ROOM-to-DOL (запас до ликвидности-цели, ATR)")
    rr = r.dropna(subset=["room"])
    for lo, hi, lab in [(-99, 1, "room<1 ATR (близко)"), (1, 3, "room 1-3"), (3, 99, "room>3 (далеко)")]:
        s = rr[(rr["room"] >= lo) & (rr["room"] < hi)]
        if len(s): print(f"  {lab:<34} | n={len(s):>3} ult {s['ult'].mean():>+6.1f}% bust {(s['busted']==True).mean()*100:>3.0f}%")
    print(f"  corr(room, ult) = {rr['room'].corr(rr['ult']):+.3f}")

    print("\n" + "="*100)
    print("■ СТЭКИНГ: лучший robust признак (aligned<0) + ортогональный")
    print("="*100)
    base = r[r["aligned_bias"] < 0]
    print(f"  base: aligned<0                    | n={len(base):>3} ult {base['ult'].mean():+6.1f}% bust {(base['busted']==True).mean()*100:.0f}%")
    for z, lab in [("big", "+ big-day"), ("dol", "+ breakout у DOL"), ("ob", "+ breakout у OB"), ("poc", "+ breakout у POC")]:
        s = base[base[z] == 1]
        if len(s): print(f"  aligned<0 & {lab:<22} | n={len(s):>3} ult {s['ult'].mean():+6.1f}% bust {(s['busted']==True).mean()*100:.0f}%")

    # повтор V8 только на 2026 (sanity свежего года)
    print("\n■ V8 на 2026 (sanity)")
    r26 = r[r["year"] == 2026]
    for lo, hi, lab in [(-99, -1, "против"), (1, 99, "за")]:
        s = r26[(r26["aligned_bias"] >= lo) & (r26["aligned_bias"] <= hi)]
        if len(s): print(f"  {lab:<10} n={len(s):>2} ult {s['ult'].mean():+6.1f}% bust {(s['busted']==True).mean()*100:.0f}%")

    r.to_csv(A.OUT / "etap_209_interactions.csv", index=False)
    print(f"\nSaved: {A.OUT / 'etap_209_interactions.csv'}")


if __name__ == "__main__":
    main()
