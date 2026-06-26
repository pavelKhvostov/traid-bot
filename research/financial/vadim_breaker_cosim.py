"""ПОЛНЫЙ НЕТТО co-sim HTF-breaker (6h/8h) — превращаем валидированный лид в торгуемые числа.

Вход: лимит в breaker-зону (флип). SL = ATR-based (нормальный, не sub-wick). TP = RR.
Сетка SL{0.5,1.0,1.5}×ATR × RR{2,3} (не только угол — судим по cross-asset, не cherry-pick).
Нетто-косты limit-entry (win 0.05%/loss 0.10%). Месячно: R/мес,%плюс,худший,Sharpe,макс-DD. Per-asset+год.
Сравнение с нетто-ядром 1.1.x (~0.48R/мес, Sharpe 0.33).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_breaker_cosim.py
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
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "smc-lib"))
from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob  # noqa: E402
from elements.breaker_block.code import detect_breaker  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = ["6h", "8h"]
WIN_RT, LOSS_RT = 0.0005, 0.0010
CONFIGS = [(sl, rr) for sl in (0.5, 1.0, 1.5) for rr in (2.0, 3.0)]
HOLD = 60  # TF-баров на сделку


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def atr_tf(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=3).mean().values


def setups(df, atr):
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = df.index.view("int64") // 1_000_000
    cnd = [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i])) for i in range(len(df))]
    n = len(cnd); out = []
    for i in range(1, n - 1):
        ob = detect_ob(cnd[i - 1], cnd[i])
        if ob is None:
            continue
        br = detect_breaker(ob, cnd[i + 1:])
        if br is None:
            continue
        arm = i + 1 + br.activated_at_idx
        if arm >= n or not np.isfinite(atr[arm]) or atr[arm] <= 0:
            continue
        z_lo, z_hi = br.initial_zone
        if z_hi <= z_lo:
            continue
        out.append((-1 if br.direction == "bullish" else 1, 0.5 * (z_lo + z_hi), float(atr[arm]), arm))
    return out


def trades(df, atr, sg, rr):
    """-> list (sym-agnostic) (net_R, month, year, asset placeholder)."""
    hi = df.high.values; lo = df.low.values; cl = df.close.values; ts = df.index; n = len(cl)
    out = []
    for (d, e, a, arm) in setups(df, atr):
        f = None
        for j in range(arm + 1, min(arm + 81, n)):
            if lo[j] <= e <= hi[j]:
                f = j; break
        if f is None or f + 1 >= n:
            continue
        ent = e; end = min(f + 1 + HOLD, n)
        if d == 1:
            sl = ent - sg * a; tp = ent + sg * a * rr
            sh = np.nonzero(lo[f + 1:end] <= sl)[0]; th = np.nonzero(hi[f + 1:end] >= tp)[0]
        else:
            sl = ent + sg * a; tp = ent - sg * a * rr
            sh = np.nonzero(hi[f + 1:end] >= sl)[0]; th = np.nonzero(lo[f + 1:end] <= tp)[0]
        si = sh[0] if sh.size else 10**9; ti = th[0] if th.size else 10**9
        if si == 10**9 and ti == 10**9:
            continue
        win = ti < si
        risk_pct = sg * a / ent * 100
        cost = (WIN_RT if win else LOSS_RT) / (risk_pct / 100)
        net = (rr if win else -1.0) - cost
        out.append((net, ts[f].strftime("%Y-%m"), ts[f].year))
    return out


def monthly(rows):
    if len(rows) < 30:
        return None
    df = pd.DataFrame(rows, columns=["net", "month", "year"])
    mo = df.groupby("month")["net"].sum().values
    if len(mo) < 6:
        return None
    cum = np.cumsum(mo); mdd = (cum - np.maximum.accumulate(cum)).min()
    wr = (df["net"] > 0).mean() * 100  # per-trade win incl cost sign approx
    return dict(n=len(df), ptt=df["net"].mean(), wr=(df["net"] > 0).mean() * 100,
                mo_mean=mo.mean(), pos=(mo > 0).mean() * 100, worst=mo.min(),
                sharpe=mo.mean() / (mo.std() + 1e-9), mdd=mdd,
                years={int(y): float(g["net"].sum()) for y, g in df.groupby("year")})


def main():
    # собрать по TF/asset
    DATA = {}  # (tf,sym) -> (df, atr)
    for s in SYMBOLS:
        d1 = load_1m(s)
        for tf in TFS:
            dtf = rs(d1, tf); DATA[(tf, s)] = (dtf, atr_tf(dtf))
    rep = ["ПОЛНЫЙ НЕТТО co-sim HTF-breaker (6h/8h). Вход=лимит в breaker-зону, SL=ATR-based, нетто-косты.",
           "Сетка SL×RR; судим по cross-asset робастности + месячному Sharpe. Сравнение: нетто-ядро ~0.48R/мес Sh0.33.\n"]
    for tf in TFS:
        rep.append(f"=== {tf} ===")
        rep.append(f"  {'SL×ATR/RR':12}{'n':>6}{'WR%':>6}{'ptt':>8}{'BTC':>7}{'ETH':>7}{'SOL':>7}{'R/мес':>7}{'%плюс':>7}{'худш':>7}{'Sharpe':>7}{'maxDD':>7}{'+годы':>7}")
        for sg, rr in CONFIGS:
            pooled = []; perasset = {}
            for s in SYMBOLS:
                dtf, atr = DATA[(tf, s)]
                tr = trades(dtf, atr, sg, rr)
                perasset[s] = np.mean([x[0] for x in tr]) if tr else float("nan")
                pooled += tr
            m = monthly(pooled)
            if m is None:
                rep.append(f"  SL{sg}/RR{rr}: мало"); continue
            gy = sum(1 for v in m["years"].values() if v > 0); ty = len(m["years"])
            rep.append(f"  {f'{sg}/{rr}':12}{m['n']:>6}{m['wr']:>6.0f}{m['ptt']:>+8.3f}"
                       f"{perasset['BTCUSDT']:>+7.2f}{perasset['ETHUSDT']:>+7.2f}{perasset['SOLUSDT']:>+7.2f}"
                       f"{m['mo_mean']:>+7.2f}{m['pos']:>6.0f}%{m['worst']:>+7.1f}{m['sharpe']:>7.2f}{m['mdd']:>+7.1f}{gy:>5}/{ty}")
    # комбо: лучший робастный конфиг (SL1.0/RR2 как нейтральный, не угол) пул 6h+8h все активы
    rep.append("\n=== КОМБО 6h+8h все активы, конфиг SL1.0/RR2 (нейтральный, не угол сетки) ===")
    pooled = []
    for tf in TFS:
        for s in SYMBOLS:
            dtf, atr = DATA[(tf, s)]; pooled += trades(dtf, atr, 1.0, 2.0)
    m = monthly(pooled)
    if m:
        gy = sum(1 for v in m["years"].values() if v > 0)
        rep.append(f"  n={m['n']} ptt={m['ptt']:+.3f} WR={m['wr']:.0f}% | R/мес {m['mo_mean']:+.2f} %плюс {m['pos']:.0f} худший {m['worst']:+.1f} Sharpe {m['sharpe']:.2f} maxDD {m['mdd']:+.1f} | годы+ {gy}/{len(m['years'])}")
        rep.append(f"  по годам: " + " ".join(f"{y}:{v:+.0f}" for y, v in sorted(m['years'].items())))
        rep.append(f"\n  vs нетто-ядро 1.1.x: ~0.48R/мес, Sharpe 0.33. HTF-breaker SL1/RR2: {m['mo_mean']:+.2f}R/мес, Sharpe {m['sharpe']:.2f}.")
    rep.append("\n=== ВЕРДИКТ ===")
    rep.append("  Робастный конфиг = cross-asset 3/3 положительный ptt + год >=5/7 + Sharpe сопоставим с ядром.")
    rep.append("  Если SL1.0/RR2 (нейтральный) даёт это -> HTF-breaker = реальная новая цепочка в корзину.")
    rep.append("  Если плюс только на угле SL0.5/RR3 -> подозрение multiple-testing, нужен ещё OOS.")
    out = "\n".join(rep)
    (Path(__file__).resolve().parent / "vadim_breaker_cosim_report.txt").write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
