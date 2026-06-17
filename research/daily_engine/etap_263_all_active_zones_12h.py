"""etap_263 - ВСЕ активные зоны интереса на BTC 12h: OB / FVG / iFVG / RDRB.

Активная = немитигированная (после формации дальний край НЕ пробит фитилём:
demand — low не уходил ниже bottom; supply — high не уходил выше top) И в пределах
±band от текущей цены. Канон детекторов:
  OB   — пара свечей (strategy_1_1_1.detect_ob_pair)
  FVG  — 3 свечи c0-c2 (high[i]<low[i+2] bull / low[i]>high[i+2] bear)
  iFVG — FVG-B противоположного направления, первым перекрывший зону untouched FVG-A
         (etap_93); активная зона = инвертированная (новая полярность B)
  RDRB — 3-свечной (anchor i-2 / mid / trigger), зона = пересечение (strategies/rdrb.py)

Данные СВЕЖИЕ (Binance, etap_225.fetch), 1h->12h, незакрытый 12h-бар отрезан.
Печать: отчёт + JSON для отрисовки на TV.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_263_all_active_zones_12h.py BTCUSDT
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
import etap_225_dual_dashboard as D
from strategies.strategy_1_1_1 import detect_ob_pair

BAND = 0.15
CAP_PER_TYPE = 5


def detect_ob(d):
    out = []
    for i in range(1, len(d)):
        ob = detect_ob_pair(d, i)
        if ob is None: continue
        out.append(dict(type="OB", direction="LONG" if ob.direction == "LONG" else "SHORT",
                        bottom=float(ob.bottom), top=float(ob.top), form_idx=i))
    return out


def detect_fvg(d):
    h = d["high"].values; l = d["low"].values; out = []
    for i in range(len(d) - 2):
        if h[i] < l[i + 2]:
            out.append(dict(type="FVG", direction="LONG", bottom=float(h[i]), top=float(l[i + 2]), form_idx=i + 2))
        elif l[i] > h[i + 2]:
            out.append(dict(type="FVG", direction="SHORT", bottom=float(h[i + 2]), top=float(l[i]), form_idx=i + 2))
    return out


def detect_ifvg(d):
    """iFVG (etap_93): FVG-B противоп. направления, первым перекрывший untouched FVG-A.
    Активная зона = зона B с новой полярностью."""
    h = d["high"].values; l = d["low"].values
    fvgs = []
    for i in range(len(d) - 2):
        if h[i] < l[i + 2]: fvgs.append(("LONG", float(h[i]), float(l[i + 2]), i, i + 2))
        elif l[i] > h[i + 2]: fvgs.append(("SHORT", float(h[i + 2]), float(l[i]), i, i + 2))
    n = len(d); out = []
    for (adir, abot, atop, ac0, ac2) in fvgs:
        # первое касание зоны A после c2
        touch = None
        for j in range(ac2 + 1, n):
            if adir == "LONG" and l[j] <= atop: touch = j; break
            if adir == "SHORT" and h[j] >= abot: touch = j; break
        if touch is None: continue
        for (bdir, bbot, btop, bc0, bc2) in fvgs:
            if bdir == adir or bc0 <= ac2: continue
            if bc0 <= touch <= bc2 and not (btop < abot or atop < bbot):
                out.append(dict(type="iFVG", direction=bdir, bottom=bbot, top=btop, form_idx=bc2))
                break
    return out


def detect_rdrb(d):
    o = d["open"].values; h = d["high"].values; l = d["low"].values; c = d["close"].values
    out = []
    for i in range(2, len(d)):
        ao, ac, ah, al = o[i - 2], c[i - 2], h[i - 2], l[i - 2]
        mc = c[i - 1]; co, ch, cl, cc = o[i], h[i], l[i], c[i]
        direction = bottom = top = None
        if mc > ah and cl < ah and cc > ah:
            direction = "LONG"; bottom = max(cl, max(ao, ac)); top = min(ah, min(co, cc))
        elif mc < al and ch > al and cc < al:
            direction = "SHORT"; bottom = max(al, max(co, cc)); top = min(ch, min(ao, ac))
        if direction and top > bottom:
            out.append(dict(type="RDRB", direction=direction, bottom=float(bottom), top=float(top), form_idx=i))
    return out


def is_active(z, h, l):
    """дальний край не пробит фитилём после формации."""
    fi = z["form_idx"]
    if z["direction"] == "LONG":   # demand: low не уходил ниже bottom
        return (l[fi + 1:] >= z["bottom"]).all() if fi + 1 < len(l) else True
    return (h[fi + 1:] <= z["top"]).all() if fi + 1 < len(h) else True


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    df1h = D.fetch(sym, days=days)
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    d = df1h.resample("12h", origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    now = pd.Timestamp.utcnow()
    if d.index[-1] + pd.Timedelta(hours=12) > now:
        d = d.iloc[:-1]
    ref_t = d.index[-1]; price = float(d["close"].iloc[-1])
    h = d["high"].values; l = d["low"].values

    allz = detect_ob(d) + detect_fvg(d) + detect_ifvg(d) + detect_rdrb(d)
    # активные + в band
    act = [z for z in allz if is_active(z, h, l) and abs((z["bottom"] + z["top"]) / 2 / price - 1) <= BAND]
    # дедуп почти совпадающих (тип+направление, перекрытие >70%) — оставляем ближе к цене
    act.sort(key=lambda z: abs((z["bottom"] + z["top"]) / 2 - price))
    kept = []
    for z in act:
        dup = False
        for k in kept:
            if k["type"] == z["type"] and k["direction"] == z["direction"]:
                ov = max(0, min(k["top"], z["top"]) - max(k["bottom"], z["bottom"]))
                if ov > 0.6 * min(k["top"] - k["bottom"], z["top"] - z["bottom"]):
                    dup = True; break
        if not dup: kept.append(z)
    # cap per type
    final = []
    for t in ("OB", "FVG", "iFVG", "RDRB"):
        final += [z for z in kept if z["type"] == t][:CAP_PER_TYPE]

    def fmt(x): return f"{x:,.0f}"

    def invalidated_at(z):
        fi = z["form_idx"]
        if z["direction"] == "LONG":
            for j in range(fi + 1, len(l)):
                if l[j] < z["bottom"]: return d.index[j]
        else:
            for j in range(fi + 1, len(h)):
                if h[j] > z["top"]: return d.index[j]
        return None

    print(f"\n{'='*70}\n {sym} 12h — ВСЕ АКТИВНЫЕ ЗОНЫ (немитигированные)\n"
          f" данные {d.index[0]:%Y-%m-%d}..{ref_t:%Y-%m-%d %H:%M}Z = {fmt(price)} | "
          f"band +-{BAND*100:.0f}% | баров {len(d)}\n{'='*70}")
    for t in ("OB", "FVG", "iFVG", "RDRB"):
        zs = sorted([z for z in final if z["type"] == t], key=lambda z: -(z["bottom"] + z["top"]) / 2)
        print(f"\n {t}  (всего активных в band: {sum(1 for z in kept if z['type']==t)}, рисуем {len(zs)})")
        for z in zs:
            side = "demand" if z["direction"] == "LONG" else "supply"
            mid = (z["bottom"] + z["top"]) / 2
            print(f"   {fmt(z['bottom'])}-{fmt(z['top'])}  {z['direction']:<5} {side}  "
                  f"{(mid/price-1)*100:+.1f}%  сформ. {d.index[z['form_idx']]:%Y-%m-%d}")

    # ДИАГНОСТИКА зоны ~60k (вопрос пользователя про Sep-2024): что детектор нашёл там
    print(f"\n{'-'*70}\n ДИАГНОСТИКА региона 58-63k (все детект-зоны, активна ли):")
    region = sorted([z for z in allz if 58000 <= (z["bottom"] + z["top"]) / 2 <= 63000],
                    key=lambda z: d.index[z["form_idx"]])
    if not region:
        print("   зон не найдено в 58-63k во всём окне")
    for z in region:
        inv = invalidated_at(z)
        st = "АКТИВНА" if inv is None else f"инвалид. {inv:%Y-%m-%d} (пробит дальний край)"
        print(f"   {z['type']:<4} {z['direction']:<5} {fmt(z['bottom'])}-{fmt(z['top'])}  "
              f"сформ. {d.index[z['form_idx']]:%Y-%m-%d}  -> {st}")

    print("\n@@JSON@@" + json.dumps(dict(symbol=sym, ref_time=str(ref_t), price=price, zones=final)))


if __name__ == "__main__":
    main()
