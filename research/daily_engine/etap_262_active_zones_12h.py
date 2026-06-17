"""etap_262 - АКТИВНЫЕ зоны по закрытию ПРЕДЫДУЩЕЙ 12h свечи (live).

Канон зон (как etap_205, но горизонт 12h): на момент закрытия последней ЗАКРЫТОЙ
12h-свечи считаем то, что детектор видит «активным» = НЕОТРАБОТАННЫМ:
  - unmitigated OB (бычьи/медвежьи), канон пары
  - unmitigated FVG (канон c1-c3)
  - untested swing-ликвидность (несн. BSL сверху / SSL снизу, фрактал N=2)
  - Volume Profile: POC / VA[VAL..VAH], HVN (магниты) / LVN (быстрый проход)
Фильтр актуальности: зона не закрыта последующими барами И в пределах ±band от цены.

Данные — СВЕЖИЕ с Binance (через etap_225.fetch), ресемпл 1h->12h, незакрытый
последний 12h-бар отрезаем. Печать = человеческий отчёт + JSON для отрисовки на TV.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_262_active_zones_12h.py BTCUSDT
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_225_dual_dashboard as D

BAND = 0.12          # ±12% от цены — актуальный диапазон для 12h
VP_LOOKBACK = 180    # 12h-баров на профиль (~90 дней)


def vp(H, L, V, n_bins=60, frac=0.7):
    lo, hi = L.min(), H.max()
    edges = np.linspace(lo, hi, n_bins + 1); prof = np.zeros(n_bins)
    for h, l, v in zip(H, L, V):
        b0 = max(np.searchsorted(edges, l, "right") - 1, 0)
        b1 = min(np.searchsorted(edges, h, "right") - 1, n_bins - 1)
        if b1 == b0: prof[b0] += v
        else: prof[b0:b1 + 1] += v / (b1 - b0 + 1)
    poc = int(prof.argmax()); cen = lambda i: (edges[i] + edges[i + 1]) / 2
    tot = prof.sum(); lo_i = hi_i = poc; cum = prof[poc]
    while cum < frac * tot:
        up = prof[hi_i + 1:hi_i + 3].sum() if hi_i + 1 < n_bins else -1
        dn = prof[lo_i - 2:lo_i].sum() if lo_i - 1 >= 0 else -1
        if up < 0 and dn < 0: break
        if up >= dn: hi_i = min(hi_i + 2, n_bins - 1); cum += max(up, 0)
        else: lo_i = max(lo_i - 2, 0); cum += max(dn, 0)
    sm = np.convolve(prof, np.ones(3) / 3, mode="same"); cc = (edges[:-1] + edges[1:]) / 2
    hvn = [cc[i] for i in range(1, n_bins - 1) if sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > sm.mean()]
    lvn = [cc[i] for i in range(1, n_bins - 1) if sm[i] < sm[i - 1] and sm[i] <= sm[i + 1] and sm[i] < sm.mean() * 0.5]
    return cen(poc), cen(hi_i), cen(lo_i), hvn, lvn


def unmitigated_fvg(o, h, l, c, price, band):
    n = len(c); bull = []; bear = []
    for i in range(1, n - 1):
        if h[i - 1] < l[i + 1]:
            top, bot = l[i + 1], h[i - 1]
            filled = (l[i + 2:] < bot).any() if i + 2 < n else False
            if not filled and abs((top + bot) / 2 / price - 1) <= band: bull.append((bot, top))
        if l[i - 1] > h[i + 1]:
            top, bot = l[i - 1], h[i + 1]
            filled = (h[i + 2:] > top).any() if i + 2 < n else False
            if not filled and abs((top + bot) / 2 / price - 1) <= band: bear.append((bot, top))
    return bull, bear


def unmitigated_ob(o, h, l, c, price, band):
    n = len(c); bull = []; bear = []
    for i in range(1, n):
        if c[i - 1] < o[i - 1] and c[i] > o[i - 1]:
            top, bot = o[i - 1], min(l[i - 1], l[i])
            if not ((l[i + 1:] < bot).any() if i + 1 < n else False) and abs((top + bot) / 2 / price - 1) <= band:
                bull.append((bot, top))
        if c[i - 1] > o[i - 1] and c[i] < o[i - 1]:
            top, bot = max(h[i - 1], h[i]), o[i - 1]
            if not ((h[i + 1:] > top).any() if i + 1 < n else False) and abs((top + bot) / 2 / price - 1) <= band:
                bear.append((bot, top))
    return bull, bear


def untested_swings(h, l, price, band, N=2):
    n = len(h); bsl = []; ssl = []
    for i in range(N, n - N - 1):
        if h[i] > max(h[i - N:i].max(), h[i + 1:i + 1 + N].max()):
            if not (h[i + N + 1:] > h[i]).any() and abs(h[i] / price - 1) <= band: bsl.append(float(h[i]))
        if l[i] < min(l[i - N:i].min(), l[i + 1:i + 1 + N].min()):
            if not (l[i + N + 1:] < l[i]).any() and abs(l[i] / price - 1) <= band: ssl.append(float(l[i]))
    return bsl, ssl


def fmt(x): return f"{x:,.0f}"
def zr(z): return f"{fmt(z[0])}-{fmt(z[1])}"


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    df1h = D.fetch(sym, days=400)
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    d = df1h.resample("12h", origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    now = pd.Timestamp.utcnow()
    if d.index[-1] + pd.Timedelta(hours=12) > now:
        d = d.iloc[:-1]               # отрезаем незакрытый 12h-бар
    ref_t = d.index[-1]; ref_close = float(d["close"].iloc[-1])
    price = ref_close
    o, h, l, c, v = (d[x].values for x in ["open", "high", "low", "close", "volume"])
    w = slice(max(0, len(d) - VP_LOOKBACK), len(d))
    poc, vah, val, hvn, lvn = vp(h[w], l[w], v[w])
    fb, fbe = unmitigated_fvg(o, h, l, c, price, BAND)
    ob, obe = unmitigated_ob(o, h, l, c, price, BAND)
    bsl, ssl = untested_swings(h, l, price, BAND)

    print(f"\n{'='*70}")
    print(f" {sym} · АКТИВНЫЕ ЗОНЫ по закрытию ПРЕДЫДУЩЕЙ 12h свечи")
    print(f" ref 12h close: {ref_t:%Y-%m-%d %H:%M} UTC = {fmt(ref_close)} (закрыта)")
    print(f" баров 12h: {len(d)} | окно VP {VP_LOOKBACK} | band +-{BAND*100:.0f}%")
    print(f"{'='*70}")
    print(f"  VP: POC {fmt(poc)} | VA [{fmt(val)} .. {fmt(vah)}]")
    near = lambda xs: sorted(set(round(x, -1) for x in xs), key=lambda x: abs(x - price))
    print(f"  HVN (магниты): {', '.join(fmt(x) for x in near(hvn)[:6]) or '-'}")
    print(f"  LVN (быстрый проход): {', '.join(fmt(x) for x in near(lvn)[:5]) or '-'}")
    above = lambda zs: [z for z in zs if (z[0] + z[1]) / 2 > price]
    below = lambda zs: [z for z in zs if (z[0] + z[1]) / 2 <= price]
    res = sorted(above(fbe) + above(obe), key=lambda z: (z[0] + z[1]) / 2)
    sup = sorted(below(fb) + below(ob), key=lambda z: -(z[0] + z[1]) / 2)
    print(f"\n  СОПРОТИВЛЕНИЕ (неотработанные, выше {fmt(price)}):")
    for z in res[:6]:
        print(f"     {zr(z)}  ({'FVG' if z in fbe else 'OB'} bear)  {(((z[0]+z[1])/2/price-1)*100):+.1f}%")
    print(f"  ПОДДЕРЖКА (неотработанные, ниже {fmt(price)}):")
    for z in sup[:6]:
        print(f"     {zr(z)}  ({'FVG' if z in fb else 'OB'} bull)  {(((z[0]+z[1])/2/price-1)*100):+.1f}%")
    print(f"\n  Несн. ликвидность BSL (магнит сверху): {', '.join(fmt(x) for x in sorted(set(round(b,-1) for b in bsl))) or '-'}")
    print(f"  Несн. ликвидность SSL (магнит снизу):  {', '.join(fmt(x) for x in sorted(set(round(s,-1) for s in ssl), reverse=True)) or '-'}")

    out = dict(symbol=sym, ref_time=str(ref_t), ref_close=ref_close, price=price,
               poc=poc, vah=vah, val=val, hvn=near(hvn)[:6], lvn=near(lvn)[:5],
               resistance=res[:6], support=sup[:6], bsl=bsl, ssl=ssl,
               first_bar_ts=int(d.index[0].timestamp()))
    print("\n@@JSON@@" + json.dumps(out))


if __name__ == "__main__":
    main()
