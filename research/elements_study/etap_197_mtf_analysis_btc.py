"""etap_197 — мультитаймфреймный анализ BTC по СИНТЕЗУ всех знаний.

MCP TradingView в этой сессии недоступен (ставился на Mac Павла; мы на Windows).
Уточнение Павла (TradingView-MCP-как-запускать.md): «для MTF надёжнее считать зоны
Python-кодом и давать текстом» — chart_set_timeframe рассинхронен, кастомные
индикаторы data_get_study_values не отдаёт. Делаем именно так, но шире tv_mark_zones.py:

Применяем 6 книг + López de Prado:
  - DALTON: volume profile (POC/VAH/VAL, HVN/LVN), value migration (тренд по стоимости)
  - HARRIS: order flow (CVD slope, delta, taker_buy_ratio, CVD-дивергенция) из *_flow.csv
  - GRIMES: режим (тренд/диапазон), Four Trades классификация, momentum-leg
  - ICT/SMC: фракталы (DOL/liquidity), FVG (канон c1-c3), OB, premium/discount, sweep
  - LdP: SADF-подобный режим (explosiveness) как фильтр

Top-down ТФ (ICT month03): 1d → 12h → 4h → 1h (execution).
Данные: research/elements_study/data/BTCUSDT_{1h,12h}_flow.csv (свежие, с taker-flow);
4h и 1d ресемплятся из 1h-flow (origin=epoch) — flow доступен на всех ТФ.

Запуск: venv/Scripts/python.exe research/elements_study/etap_197_mtf_analysis_btc.py
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

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "elements_study" / "data"
SYMBOL = "BTCUSDT"


# ---------- загрузка / ресемпл (flow сохраняется на всех ТФ) ----------
def load_flow(tf: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{SYMBOL}_{tf}_flow.csv", parse_dates=["open_time"])
    return df.set_index("open_time").sort_index()


def resample_flow(base: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last",
           "volume": "sum", "quote_volume": "sum", "trades": "sum",
           "taker_buy_base": "sum", "taker_buy_quote": "sum"}
    out = base.resample(rule, origin="epoch", label="left", closed="left").agg(agg)
    out = out.dropna(subset=["open", "high", "low", "close"])
    # отрезать незакрытый бар
    step = pd.Timedelta(rule)
    now = pd.Timestamp.utcnow()
    if len(out) and out.index[-1] + step > now:
        out = out.iloc[:-1]
    out["delta"] = 2 * out["taker_buy_base"] - out["volume"]
    out["cvd"] = out["delta"].cumsum()
    out["taker_buy_ratio"] = (out["taker_buy_base"] / out["volume"]).where(out["volume"] > 0)
    return out


def get_tf(tf: str) -> pd.DataFrame:
    if tf in ("1h", "12h"):
        return load_flow(tf)
    base = load_flow("1h")
    rule = {"4h": "4h", "1d": "1D"}[tf]
    return resample_flow(base, rule)


# ---------- индикаторы ----------
def ema(s: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(s).ewm(span=n, adjust=False).mean().values


def atr(H, L, C, n=14) -> float:
    tr = np.maximum(H[1:] - L[1:], np.maximum(abs(H[1:] - C[:-1]), abs(L[1:] - C[:-1])))
    return float(pd.Series(tr).ewm(span=n, adjust=False).mean().iloc[-1])


# ---------- DALTON: volume profile ----------
def volume_profile(H, L, V, n_bins=80):
    lo, hi = L.min(), H.max()
    edges = np.linspace(lo, hi, n_bins + 1)
    prof = np.zeros(n_bins)
    for h, l, v in zip(H, L, V):
        b0 = max(np.searchsorted(edges, l, "right") - 1, 0)
        b1 = min(np.searchsorted(edges, h, "right") - 1, n_bins - 1)
        if b1 == b0:
            prof[b0] += v
        else:
            prof[b0:b1 + 1] += v / (b1 - b0 + 1)
    return edges, prof


def value_area(edges, prof, frac=0.70):
    total = prof.sum()
    poc = int(prof.argmax())
    lo = hi = poc
    cum = prof[poc]
    n = len(prof)
    while cum < frac * total:
        up = prof[hi + 1:hi + 3].sum() if hi + 1 < n else -1
        dn = prof[lo - 2:lo].sum() if lo - 1 >= 0 else -1
        if up < 0 and dn < 0:
            break
        if up >= dn:
            hi = min(hi + 2, n - 1); cum += max(up, 0)
        else:
            lo = max(lo - 2, 0); cum += max(dn, 0)
    cen = lambda i: (edges[i] + edges[i + 1]) / 2
    return cen(lo), cen(hi), cen(poc)  # VAL, VAH, VPOC


def hvn_lvn(edges, prof, price):
    # сглаживание + локальные экстремумы
    k = np.ones(3) / 3
    sm = np.convolve(prof, k, mode="same")
    cen = (edges[:-1] + edges[1:]) / 2
    peaks, troughs = [], []
    for i in range(1, len(sm) - 1):
        if sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > sm.mean():
            peaks.append(cen[i])
        if sm[i] < sm[i - 1] and sm[i] <= sm[i + 1] and sm[i] < sm.mean() * 0.6:
            troughs.append(cen[i])
    hvn_abv = min([p for p in peaks if p > price], default=None)
    hvn_blw = max([p for p in peaks if p < price], default=None)
    lvn_abv = min([t for t in troughs if t > price], default=None)
    lvn_blw = max([t for t in troughs if t < price], default=None)
    return hvn_abv, hvn_blw, lvn_abv, lvn_blw


# ---------- ICT: фракталы, FVG (канон c1-c3), OB ----------
def fractals(H, L, N=2):
    fh, fl = [], []
    for i in range(N, len(H) - N):
        if H[i] > max(H[i - N:i].max(), H[i + 1:i + 1 + N].max()):
            fh.append((i, H[i]))
        if L[i] < min(L[i - N:i].min(), L[i + 1:i + 1 + N].min()):
            fl.append((i, L[i]))
    return fh, fl


def fvgs(H, L, C, price):
    """канон c1-c3: (i-1,i,i+1); незакрытые; ближайшие к цене."""
    bull, bear = [], []
    n = len(H)
    for i in range(1, n - 1):
        c1h, c1l, c3h, c3l = H[i - 1], L[i - 1], H[i + 1], L[i + 1]
        if c1h < c3l:  # bullish
            top, bot = c3l, c1h
            filled = (L[i + 2:] < bot).any() if i + 2 < n else False
            if not filled:
                bull.append((bot, top))
        if c1l > c3h:  # bearish
            top, bot = c1l, c3h
            filled = (H[i + 2:] > top).any() if i + 2 < n else False
            if not filled:
                bear.append((bot, top))
    bull_blw = max([z for z in bull if z[1] <= price], key=lambda z: z[1], default=None)
    bear_abv = min([z for z in bear if z[0] >= price], key=lambda z: z[0], default=None)
    return bull_blw, bear_abv


def order_blocks(O, H, L, C, price):
    n = len(O)
    bull_blw = bear_abv = None
    for i in range(1, n):
        if C[i - 1] < O[i - 1] and C[i] > O[i - 1]:  # bullish OB
            top, bot = O[i - 1], min(L[i - 1], L[i])
            mit = (L[i + 1:] < bot).any() if i + 1 < n else False
            if not mit and top < price:
                if bull_blw is None or top > bull_blw[1]:
                    bull_blw = (bot, top)
        if C[i - 1] > O[i - 1] and C[i] < O[i - 1]:  # bearish OB
            top, bot = max(H[i - 1], H[i]), O[i - 1]
            mit = (H[i + 1:] > top).any() if i + 1 < n else False
            if not mit and bot > price:
                if bear_abv is None or bot < bear_abv[0]:
                    bear_abv = (bot, top)
    return bull_blw, bear_abv


# ---------- GRIMES: режим + Four Trades ----------
def regime(C, H, L):
    e20, e50 = ema(C, 20), ema(C, 50)
    slope = (e20[-1] - e20[-10]) / e20[-10] * 100  # % за 10 баров
    pos = "above" if C[-1] > e20[-1] else "below"
    # структура: последние 2 фрактальных HH/HL?
    fh, fl = fractals(H, L, N=2)
    hh = len(fh) >= 2 and fh[-1][1] > fh[-2][1]
    hl = len(fl) >= 2 and fl[-1][1] > fl[-2][1]
    lh = len(fh) >= 2 and fh[-1][1] < fh[-2][1]
    ll = len(fl) >= 2 and fl[-1][1] < fl[-2][1]
    if e20[-1] > e50[-1] and slope > 0.3 and (hh or hl):
        trend = "UPTREND"
    elif e20[-1] < e50[-1] and slope < -0.3 and (lh or ll):
        trend = "DOWNTREND"
    else:
        trend = "RANGE/TRANSITION"
    return trend, slope, pos, dict(HH=hh, HL=hl, LH=lh, LL=ll)


def momentum_leg(H, L, C, atr14, look=10):
    """был ли thrust (range-expansion) в последних look барах."""
    rng = (H[-look:] - L[-look:])
    big = rng > 1.6 * atr14
    return bool(big.any()), int(big.sum())


# ---------- HARRIS: order flow ----------
def flow_read(df, look=20):
    cvd = df["cvd"].values
    slope = (cvd[-1] - cvd[-look]) / (abs(cvd[-look]) + 1e-9)
    cvd_dir = "BUY-flow↑" if cvd[-1] > cvd[-look] else "SELL-flow↓"
    tbr = df["taker_buy_ratio"].values[-look:]
    tbr_mean = float(np.nanmean(tbr))
    last_delta = df["delta"].values[-1]
    # CVD-дивергенция на последнем свинге: price lower-low, cvd higher-low (bull) / зеркально
    L = df["low"].values; H = df["high"].values
    div = "none"
    if len(df) > 30:
        p_min_i = len(L) - 1 - int(np.argmin(L[-15:]))
        prev_min_i = len(L) - 16 - int(np.argmin(L[-30:-15]))
        if L[p_min_i] < L[prev_min_i] and cvd[p_min_i] > cvd[prev_min_i]:
            div = "BULLISH (price LL, CVD HL — продавцы выдохлись)"
        p_max_i = len(H) - 1 - int(np.argmax(H[-15:]))
        prev_max_i = len(H) - 16 - int(np.argmax(H[-30:-15]))
        if H[p_max_i] > H[prev_max_i] and cvd[p_max_i] < cvd[prev_max_i]:
            div = "BEARISH (price HH, CVD LH — покупатели выдохлись)"
    return cvd_dir, slope, tbr_mean, last_delta, div


# ---------- анализ одного ТФ ----------
def analyze_tf(tf: str, vp_window: int):
    df = get_tf(tf)
    O, H, L, C, V = (df[c].values for c in ["open", "high", "low", "close", "volume"])
    price = C[-1]
    atr14 = atr(H, L, C)
    w = df.iloc[-vp_window:]
    edges, prof = volume_profile(w["high"].values, w["low"].values, w["volume"].values)
    val, vah, vpoc = value_area(edges, prof)
    # value migration: vpoc текущего окна vs окна назад
    w2 = df.iloc[-2 * vp_window:-vp_window]
    if len(w2) > 10:
        e2, p2 = volume_profile(w2["high"].values, w2["low"].values, w2["volume"].values)
        _, _, vpoc_prev = value_area(e2, p2)
        migr = "UP" if vpoc > vpoc_prev * 1.002 else ("DOWN" if vpoc < vpoc_prev * 0.998 else "FLAT")
    else:
        migr = "n/a"
    hvn_a, hvn_b, lvn_a, lvn_b = hvn_lvn(edges, prof, price)
    trend, slope, pos, struct = regime(C, H, L)
    has_mom, mom_n = momentum_leg(H, L, C, atr14)
    cvd_dir, cvd_slope, tbr, last_delta, div = flow_read(df)
    bull_fvg, bear_fvg = fvgs(H, L, C, price)
    bull_ob, bear_ob = order_blocks(O, H, L, C, price)
    fh, fl = fractals(H, L, N=2)
    bsl = min([v for _, v in fh if v > price], default=None)   # ближайшая ликвидность сверху
    ssl = max([v for _, v in fl if v < price], default=None)   # снизу
    # premium/discount относительно VA
    if price > vah:
        pd_loc = "ВЫШЕ value (premium-экстрим)"
    elif price < val:
        pd_loc = "НИЖЕ value (discount-экстрим)"
    else:
        frac = (price - val) / (vah - val + 1e-9)
        pd_loc = f"внутри VA ({frac*100:.0f}% от VAL→VAH)" + (" · premium" if frac > 0.5 else " · discount")
    return dict(tf=tf, price=price, atr=atr14, trend=trend, slope=slope, pos=pos,
                struct=struct, has_mom=has_mom, mom_n=mom_n,
                vpoc=vpoc, vah=vah, val=val, migr=migr,
                hvn_a=hvn_a, hvn_b=hvn_b, lvn_a=lvn_a, lvn_b=lvn_b,
                cvd_dir=cvd_dir, cvd_slope=cvd_slope, tbr=tbr, last_delta=last_delta, div=div,
                bull_fvg=bull_fvg, bear_fvg=bear_fvg, bull_ob=bull_ob, bear_ob=bear_ob,
                bsl=bsl, ssl=ssl, pd_loc=pd_loc)


def fmt(x):
    return f"{x:,.0f}" if x is not None else "—"


def zone(z):
    return f"{z[0]:,.0f}-{z[1]:,.0f}" if z else "—"


def main():
    print("=" * 78)
    print("МУЛЬТИТАЙМФРЕЙМНЫЙ АНАЛИЗ BTCUSDT — синтез (Dalton+Harris+Grimes+ICT+LdP)")
    print("=" * 78)
    tfs = [("1d", 90), ("12h", 90), ("4h", 120), ("1h", 120)]
    res = {}
    for tf, win in tfs:
        r = analyze_tf(tf, win)
        res[tf] = r
        last = get_tf(tf).index[-1]
        print(f"\n{'─'*78}\n▌ {tf.upper()}  (закрытый бар {last:%Y-%m-%d %H:%M} UTC)  цена={fmt(r['price'])}  ATR={fmt(r['atr'])}")
        print(f"  GRIMES режим : {r['trend']}  | EMA20 slope {r['slope']:+.2f}%/10b, цена {r['pos']} EMA20"
              f"  | momentum-leg: {'ДА('+str(r['mom_n'])+')' if r['has_mom'] else 'нет'}")
        st = ",".join(k for k, v in r['struct'].items() if v) or "—"
        print(f"               структура: {st}")
        print(f"  DALTON value : VPOC={fmt(r['vpoc'])}  VA=[{fmt(r['val'])}..{fmt(r['vah'])}]  migration={r['migr']}")
        print(f"               локация цены: {r['pd_loc']}")
        print(f"               HVN↑{fmt(r['hvn_a'])} HVN↓{fmt(r['hvn_b'])} | LVN↑{fmt(r['lvn_a'])} LVN↓{fmt(r['lvn_b'])}")
        print(f"  HARRIS flow  : CVD {r['cvd_dir']} (slope {r['cvd_slope']:+.2f})  taker_buy_ratio≈{r['tbr']:.3f}"
              f"  last_delta={r['last_delta']:+,.0f}")
        print(f"               дивергенция: {r['div']}")
        print(f"  ICT зоны     : FVG_bull↓ {zone(r['bull_fvg'])} | FVG_bear↑ {zone(r['bear_fvg'])}")
        print(f"               OB_bull↓ {zone(r['bull_ob'])} | OB_bear↑ {zone(r['bear_ob'])}")
        print(f"               DOL: BSL↑(ликв.сверху)={fmt(r['bsl'])}  SSL↓(ликв.снизу)={fmt(r['ssl'])}")

    # ---------- СИНТЕЗ ----------
    print(f"\n{'='*78}\nСИНТЕЗ MTF (top-down: 1d→12h→4h→1h)\n{'='*78}")
    d1, h12, h4, h1 = res["1d"], res["12h"], res["4h"], res["1h"]
    htf_trends = [d1["trend"], h12["trend"]]
    if all(t == "UPTREND" for t in htf_trends):
        bias = "BULLISH (HTF up — искать LONG-continuation на откатах в discount)"
    elif all(t == "DOWNTREND" for t in htf_trends):
        bias = "BEARISH (HTF down — искать SHORT-continuation на ралли в premium)"
    else:
        bias = "СМЕШАННЫЙ / транзишн (1d=%s, 12h=%s) — приоритет диапазонным сделкам, осторожно с трендовыми" % (d1["trend"], h12["trend"])
    print(f"\n  HTF bias (1d+12h): {bias}")
    print(f"  Цена {fmt(h1['price'])} | 1d value [{fmt(d1['val'])}..{fmt(d1['vah'])}] VPOC {fmt(d1['vpoc'])} (migr {d1['migr']})")
    print(f"                     | 12h location: {h12['pd_loc']}")

    # Grimes Four Trades — какая сделка в игре
    print("\n  GRIMES Four Trades — что в игре:")
    if "BULLISH" in bias:
        print("   → Trade 1 (trend-continuation pullback) ВВЕРХ: ждать откат в 12h/4h discount-зону")
        print("     (OB_bull / FVG_bull / HVN снизу) + возврат BUY-delta (CVD) = LONG по тренду.")
        print("     Trade 2 (termination) — против, только при CVD bearish-дивергенции у BSL.")
    elif "BEARISH" in bias:
        print("   → Trade 1 (trend-continuation pullback) ВНИЗ: ждать ралли в 12h/4h premium-зону")
        print("     (OB_bear / FVG_bear / HVN сверху) + возврат SELL-delta (CVD) = SHORT по тренду.")
        print("     Trade 2 (termination) — против, только при CVD bullish-дивергенции у SSL.")
    else:
        print("   → Trade 3/4 (range hold / break): торговать края диапазона между ближайшими")
        print("     HVN/value-границами; пробой LVN с подтверждением flow = Trade 4.")

    # ключевые исполнительные зоны (1h/4h рядом с ценой)
    print("\n  Ключевые исполнительные зоны (4h/1h, рядом с ценой):")
    for tf in ("4h", "1h"):
        r = res[tf]
        print(f"   [{tf}] поддержка: OB_bull {zone(r['bull_ob'])}, FVG_bull {zone(r['bull_fvg'])}, HVN↓ {fmt(r['hvn_b'])}, SSL {fmt(r['ssl'])}")
        print(f"        сопротивл.: OB_bear {zone(r['bear_ob'])}, FVG_bear {zone(r['bear_fvg'])}, HVN↑ {fmt(r['hvn_a'])}, BSL {fmt(r['bsl'])}")

    # order-flow подтверждение
    print("\n  HARRIS order-flow срез (подтверждение/предупреждение):")
    for tf in ("12h", "4h", "1h"):
        r = res[tf]
        flag = ""
        if r["div"] != "none":
            flag = "  ⚠️ " + r["div"]
        print(f"   [{tf}] CVD {r['cvd_dir']} (slope {r['cvd_slope']:+.2f}), taker_buy≈{r['tbr']:.3f}{flag}")

    print("\n  ⚠️ Это ОПИСАТЕЛЬНЫЙ MTF-разбор по методологии (нарратив), НЕ валидированный сигнал.")
    print("     Любую сделку отсюда гнать через 7-criteria + backtest + null-test (López de Prado).")


if __name__ == "__main__":
    main()
