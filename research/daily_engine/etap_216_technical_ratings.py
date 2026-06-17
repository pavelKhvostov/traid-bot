"""etap_216 — Technicals Pro (TradingView Recommend.All) как усилитель direction-модуля.

Индикатор у юзера = TradingView Technical Ratings "All" (MA-рейтинг + осцилляторы → −1..+1).
Реплицируем алгоритм в Python (no talib) и проверяем ЧЕСТНО на разных ТФ и порогах:
  1) AUC: рейтинг предсказывает направление СЛЕДУЮЩЕГО бара?
  2) Forward-return по бакетам (StrongSell..StrongBuy) — есть ли edge на краях?
  3) Усиливает ли рейтинг (и его FLIP — «смена лонг/шорт») day-direction over price?

Запуск: venv/Scripts/python.exe research/daily_engine/etap_216_technical_ratings.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

DATA = Path(__file__).resolve().parent.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")


def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()
def wma(s, n):
    w = np.arange(1, n+1)
    return s.rolling(n).apply(lambda x: np.dot(x, w)/w.sum(), raw=True)


def rsi(c, n=14):
    d = c.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / dn.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1+rs)


def technical_rating(df):
    """TradingView Recommend.All (−1..+1). Реплика с малыми упрощениями осцилляторов."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    hl2 = (h+l)/2
    # --- MA рейтинг ---
    ma_votes = []
    for n in [10, 20, 30, 50, 100, 200]:
        for f in (sma, ema):
            m = f(c, n); ma_votes.append(np.sign(c - m))
    vwma = sma(c*v, 20)/sma(v, 20); ma_votes.append(np.sign(c - vwma))
    hull = wma(2*wma(c, 4)-wma(c, 9), 3); ma_votes.append(np.sign(hull - hull.shift(1)))
    base = (h.rolling(26).max()+l.rolling(26).min())/2; ma_votes.append(np.sign(c - base))  # Ichimoku base
    ratingMA = pd.concat(ma_votes, axis=1).mean(axis=1)

    # --- Осцилляторы (1/0/-1 по правилам TV, с упрощениями) ---
    ov = []
    r = rsi(c, 14); ov.append(np.where((r < 30) & (r > r.shift(1)), 1, np.where((r > 70) & (r < r.shift(1)), -1, 0)))
    ln, hn = l.rolling(14).min(), h.rolling(14).max()
    k = 100*(c-ln)/(hn-ln); dd = sma(k, 3)
    ov.append(np.where((k < 20) & (dd < 20) & (k > dd), 1, np.where((k > 80) & (dd > 80) & (k < dd), -1, 0)))
    tp = (h+l+c)/3; cci = (tp - sma(tp, 20))/(0.015*tp.rolling(20).apply(lambda x: np.abs(x-x.mean()).mean(), raw=True))
    ov.append(np.where((cci < -100) & (cci > cci.shift(1)), 1, np.where((cci > 100) & (cci < cci.shift(1)), -1, 0)))
    mom = c - c.shift(10); ov.append(np.where(mom > mom.shift(1), 1, np.where(mom < mom.shift(1), -1, 0)))
    macd = ema(c, 12)-ema(c, 26); sig = ema(macd, 9); ov.append(np.sign(macd - sig))
    wpr = -100*(hn-c)/(hn-ln); ov.append(np.where((wpr < -80) & (wpr > wpr.shift(1)), 1, np.where((wpr > -20) & (wpr < wpr.shift(1)), -1, 0)))
    ao = sma(hl2, 5)-sma(hl2, 34); ov.append(np.where((ao > 0) & (ao > ao.shift(1)), 1, np.where((ao < 0) & (ao < ao.shift(1)), -1, 0)))
    # UO
    bp = c - pd.concat([l, c.shift(1)], axis=1).min(axis=1)
    tr = pd.concat([h, c.shift(1)], axis=1).max(axis=1) - pd.concat([l, c.shift(1)], axis=1).min(axis=1)
    avg = lambda n: bp.rolling(n).sum()/tr.rolling(n).sum()
    uo = 100*(4*avg(7)+2*avg(14)+avg(28))/7; ov.append(np.where(uo > 70, 1, np.where(uo < 30, -1, 0)))
    # Stoch RSI
    rr = r; rmin, rmax = rr.rolling(14).min(), rr.rolling(14).max()
    sk = sma(100*(rr-rmin)/(rmax-rmin), 3); sdd = sma(sk, 3)
    ov.append(np.where((sk < 20) & (sk > sdd), 1, np.where((sk > 80) & (sk < sdd), -1, 0)))
    # Bull Bear Power
    bbp = (h-ema(c, 13))+(l-ema(c, 13)); ov.append(np.where((bbp > 0) & (bbp > bbp.shift(1)), 1, np.where((bbp < 0) & (bbp < bbp.shift(1)), -1, 0)))
    ratingOsc = pd.DataFrame(np.array(ov).T, index=c.index).mean(axis=1)
    return ((ratingMA + ratingOsc)/2).rename("rating")


def resample(df, rule):
    o = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return o.dropna()


def main():
    d1 = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if d1.index.tz is None: d1.index = d1.index.tz_localize("UTC")
    print("="*78); print("Technicals Pro (TV Recommend.All) — честная проверка direction-edge"); print("="*78)

    for tf, rule in [("1h", "1h"), ("4h", "4h"), ("12h", "12h"), ("1d", "1D")]:
        df = resample(d1, rule) if rule != "1h" else d1[["open", "high", "low", "close", "volume"]]
        df = df.copy(); df["rating"] = technical_rating(df)
        df["fwd"] = df["close"].shift(-1)/df["close"] - 1          # доход след. бара
        df["up"] = (df["fwd"] > 0).astype(int)
        x = df.dropna(subset=["rating", "fwd"])
        te = x[x.index >= CUTOFF]
        auc = roc_auc_score(te["up"], te["rating"]) if te["up"].nunique() > 1 else float("nan")
        # forward-return по бакетам
        te = te.assign(bk=pd.cut(te["rating"], [-1.01, -0.5, -0.1, 0.1, 0.5, 1.01],
                                 labels=["StrongSell", "Sell", "Neutral", "Buy", "StrongBuy"]))
        print(f"\n■ {tf}: AUC(rating→next bar)={auc:.3f}  (OOS 2023+, n={len(te)})")
        print(f"   {'бакет':<11} {'n':>6} {'avg_fwd%':>9} {'P(up)':>6}")
        for b, g in te.groupby("bk", observed=True):
            print(f"   {str(b):<11} {len(g):>6} {g['fwd'].mean()*100:>+8.3f}% {g['up'].mean():>6.2f}")

    # --- усиливает ли рейтинг day-direction (close>open) over price? ---
    print("\n" + "="*78)
    print("■ Усиливает ли рейтинг МОДУЛЬ направления дня (1d) над ценой?")
    print("="*78)
    dd = resample(d1, "1D").copy()
    dd["rating"] = technical_rating(dd)
    dd["rating_prev"] = dd["rating"].shift(1)                       # as-of вчера (без утечки)
    dd["rating_flip"] = np.sign(dd["rating"].shift(1)) - np.sign(dd["rating"].shift(2))  # смена знака вчера
    dd["ret1"] = dd["close"].shift(1)/dd["close"].shift(2)-1
    dd["green"] = (dd["close"] > dd["open"]).astype(int)
    X = dd.dropna(subset=["rating_prev", "ret1", "green"])
    tr, te = X[X.index < CUTOFF], X[X.index >= CUTOFF]
    for feats, lab in [(["ret1"], "price-only (ret вчера)"),
                       (["ret1", "rating_prev"], "+ рейтинг"),
                       (["ret1", "rating_prev", "rating_flip"], "+ рейтинг + FLIP")]:
        m = LogisticRegression(max_iter=300).fit(tr[feats], tr["green"])
        a = roc_auc_score(te["green"], m.predict_proba(te[feats])[:, 1])
        print(f"   {lab:<26} AUC={a:.3f}")
    print(f"   (цель=цвет дня ВПЕРЁД as-of вчера; ожидаем ≈монетку — это прогноз, не nowcast)")

    print(f"\n   Текущий рейтинг (1d, посл. бар): {dd['rating'].iloc[-1]:+.2f}  "
          f"(на TV Pump-Wave Plot=−7 ≈ Sell-зона)")


if __name__ == "__main__":
    main()
