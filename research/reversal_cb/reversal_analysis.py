"""АНАЛИЗ ЗАДАЧИ перед CatBoost-модулем разворотов (6/8/12h).
Label (определение юзера): свеча i = бычий разворот, если от close[i] цена дала +3% (любой later high>=close*1.03)
РАНЬШЕ, чем появилась свеча с low<low[i] (обновила минимум). Зеркально для медвежьего (-3% раньше high>high[i]).
Цель анализа: (1) базовая частота, (2) сила КАЖДОГО фактора данными (Cohen's d + decile-lift),
(3) КОНФАУНД-КОНТРОЛЬ: дают ли факторы lift СВЕРХ механического «расстояние close->low» (add-тест).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/reversal_analysis.py
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
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = ["6h", "8h", "12h"]
THR = 0.03
CAP = 120          # макс. баров вперёд на разрешение first-passage


def load(sym, tf):
    d = pd.read_csv(ROOT / "data" / f"{sym}_{tf}.csv")
    tc = [c for c in d.columns if "time" in c.lower()][0]
    d[tc] = pd.to_datetime(d[tc], utc=True)
    return d.set_index(tc).sort_index()


def label_long(df):
    c = df.close.values; h = df.high.values; lo = df.low.values; n = len(c)
    y = np.full(n, -1)  # -1 = не разрешилось в CAP
    for i in range(n - 2):
        tgt = c[i] * (1 + THR); stop = lo[i]
        y[i] = 0
        end = min(i + 1 + CAP, n)
        for j in range(i + 1, end):
            if lo[j] < stop:
                y[i] = 0; break
            if h[j] >= tgt:
                y[i] = 1; break
    return y


def ema(x, span):
    return pd.Series(x).ewm(span=span, adjust=False).mean().values


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.clip(d, 0, None); dn = np.clip(-d, 0, None)
    ru = pd.Series(up).ewm(alpha=1/n, adjust=False).mean().values
    rd = pd.Series(dn).ewm(alpha=1/n, adjust=False).mean().values
    return 100 - 100 / (1 + ru / (rd + 1e-12))


def feats(df):
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c); rng = (h - l); rng[rng == 0] = np.nan
    pc = np.roll(c, 1); pc[0] = c[0]
    X = pd.DataFrame(index=df.index)
    # геометрия / отвержение
    X["clv"] = ((c - l) - (h - c)) / rng
    X["lwick"] = (np.minimum(o, c) - l) / rng
    X["body"] = np.abs(c - o) / rng
    X["c2l"] = (c - l) / c                      # МЕХАНИЧЕСКИЙ конфаунд (расстояние close->low)
    # моментум / экстеншн (падение перед дном)
    for k in (1, 3, 6):
        X[f"ret{k}"] = c / np.roll(c, k) - 1
    X["dd20"] = c / pd.Series(h).rolling(20).max().values - 1
    rmin = pd.Series(l).rolling(20).min().values; rmax = pd.Series(h).rolling(20).max().values
    X["posrange20"] = (c - rmin) / (rmax - rmin + 1e-12)
    X["dist_ema20"] = c / ema(c, 20) - 1
    X["dist_ema50"] = c / ema(c, 50) - 1
    X["dist_ema100"] = c / ema(c, 100) - 1
    X["rsi"] = rsi(c)
    # экстрим/истощение
    dnc = (c < pc).astype(int)
    X["consec_dn"] = pd.Series(dnc).groupby((dnc != pd.Series(dnc).shift()).cumsum()).cumcount().values * dnc
    # волатильность / режим
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).rolling(14).mean().values
    X["atr_pct"] = atr / c
    X["atr_ptile"] = pd.Series(atr).rolling(100).rank(pct=True).values
    X["range_exp"] = rng / pd.Series(rng).rolling(20).mean().values
    # объём
    X["vol_z"] = (v - pd.Series(v).rolling(96).mean().values) / (pd.Series(v).rolling(96).std().values + 1e-12)
    X["vol_climax"] = v / pd.Series(v).rolling(20).mean().values
    # ликвидность / sweep / pivot
    rmin5 = pd.Series(l).rolling(5).min().shift(1).values
    X["swept"] = (l < rmin5).astype(float)
    X["sweep_depth"] = np.clip((rmin5 - l) / c, 0, None)
    X["left_pivot"] = ((l <= np.roll(l, 1)) & (l <= np.roll(l, 2))).astype(float)
    return X


def cohend(a, b):
    na, nb = len(a), len(b)
    if na < 5 or nb < 5:
        return np.nan
    s = np.sqrt(((na - 1) * np.var(a) + (nb - 1) * np.var(b)) / (na + nb - 2)) + 1e-12
    return (np.mean(a) - np.mean(b)) / s


def main():
    out = ["="*70, " АНАЛИЗ ЗАДАЧИ РАЗВОРОТОВ (бычий low), label = +3% раньше пробоя low", "="*70]
    A = out.append
    pooled_X = []; pooled_y = []
    A(f"\nБАЗОВАЯ ЧАСТОТА разворотов по TF/активу (label=1, исключая -1 неразрешённые):")
    for tf in TFS:
        line = f"  {tf}: "
        for sym in SYMS:
            df = load(sym, tf); y = label_long(df); X = feats(df)
            m = (y >= 0)
            Xv = X[m].copy(); yv = y[m]
            base = yv.mean()
            line += f"{sym[:3]} {base:.3f} (n={len(yv)})  "
            Xv["_y"] = yv; Xv["_tf"] = tf; Xv["_sym"] = sym
            pooled_X.append(Xv); pooled_y.append(yv)
        A(line)
    P = pd.concat(pooled_X, ignore_index=True).dropna()
    y = P["_y"].values.astype(int)
    feat_cols = [c for c in P.columns if not c.startswith("_")]
    base = y.mean()
    A(f"\nПУЛ: n={len(P)}  базовая частота разворота={base:.3f}")

    # сила фактора: Cohen's d (разворот vs нет) + decile-lift (топ-дециль фактора -> P(разворот)/base)
    A(f"\n{'фактор':14}{'Cohen d':>9}{'lift_hi':>9}{'lift_lo':>9}  (lift = P(rev|дециль)/base; hi=верх.дециль, lo=ниж.)")
    rows = []
    for f in feat_cols:
        x = P[f].values
        d = cohend(x[y == 1], x[y == 0])
        hi = x >= np.nanquantile(x, 0.9); lo = x <= np.nanquantile(x, 0.1)
        lift_hi = y[hi].mean() / base if hi.sum() > 20 else np.nan
        lift_lo = y[lo].mean() / base if lo.sum() > 20 else np.nan
        rows.append((f, d, lift_hi, lift_lo))
    for f, d, lh, ll in sorted(rows, key=lambda r: -abs(r[1]) if not np.isnan(r[1]) else 0):
        A(f"{f:14}{d:>+9.3f}{lh:>9.2f}{ll:>9.2f}")

    # ADD-ТЕСТ: дают ли факторы lift СВЕРХ механического c2l?
    # внутри ВЕРХНЕГО дециля c2l (длинный хвост, механически высокий шанс) — ещё работает фактор?
    A(f"\nADD-ТЕСТ (контроль механики close->low): внутри подвыборки c2l>медианы — lift факторов сверх c2l")
    c2l = P["c2l"].values
    sub = c2l >= np.nanmedian(c2l)               # уже «выгодная» геометрия
    ys = y[sub]; bsub = ys.mean()
    A(f"  подвыборка c2l>med: n={sub.sum()} base={bsub:.3f} (vs общий {base:.3f})")
    rows2 = []
    for f in feat_cols:
        if f == "c2l":
            continue
        x = P[f].values[sub]
        hi = x >= np.nanquantile(x, 0.9)
        lift = ys[hi].mean() / bsub if hi.sum() > 20 else np.nan
        rows2.append((f, lift))
    for f, lift in sorted(rows2, key=lambda r: -(r[1] if not np.isnan(r[1]) else 0))[:10]:
        A(f"  {f:14} lift_hi(сверх c2l)={lift:>5.2f}")

    o = "\n".join(out)
    (Path(__file__).resolve().parent / "reversal_analysis_report.txt").write_text(o, encoding="utf-8")
    print(o)


if __name__ == "__main__":
    main()
