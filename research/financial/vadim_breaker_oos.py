"""#1 Config-робастность HTF-breaker на ЧИСТОМ OOS — снять кавеат «favorable SL0.5/RR3».

Конфиг SL×RR выбираем ТОЛЬКО на train (2020-2023) по train-Sharpe (с cross-asset>=2/3 на train),
затем БЕЗ доступа к нему применяем на test (2024-2026). Если train сам выбирает RR3 И test держится -> RR3
не подгонка. Breaker-цепочка = 6h+8h пул, вход=лимит в зону, ATR-SL, нетто-косты.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_breaker_oos.py
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
SLS = [0.5, 1.0, 1.5]; RRS = [2.0, 2.5, 3.0]


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


def fills(dtf, atr):
    o, h, lo, c = (dtf[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = dtf.index.view("int64") // 1_000_000
    cnd = [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i])) for i in range(len(dtf))]
    ts = dtf.index; n = len(cnd); out = []
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
        d = -1 if br.direction == "bullish" else 1; e = 0.5 * (z_lo + z_hi); a = float(atr[arm])
        f = None
        for j in range(arm + 1, min(arm + 81, n)):
            if lo[j] <= e <= h[j]:
                f = j; break
        if f is None or f + 1 >= n:
            continue
        out.append((d, e, a, f, ts[f].year, ts[f].strftime("%Y-%m")))
    return out, h, lo, c


CACHE = {}
def get_fills(sym, tf):
    if (sym, tf) not in CACHE:
        d1 = load_1m(sym); dtf = rs(d1, tf)
        CACHE[(sym, tf)] = fills(dtf, atr_tf(dtf))
    return CACHE[(sym, tf)]


def trades_cfg(sg, rr, year_filter=None):
    """pooled 6h+8h × assets; -> dict asset->list(net), and pooled list(net,month)."""
    per_asset = {s: [] for s in SYMBOLS}; pooled = []
    for s in SYMBOLS:
        for tf in TFS:
            fl, h, lo, c = get_fills(s, tf); n = len(c)
            for (d, e, a, f, yr, mo) in fl:
                if year_filter and not year_filter(yr):
                    continue
                end = min(f + 61, n)
                if d == 1:
                    sl = e - sg * a; tp = e + sg * a * rr
                    sh = np.nonzero(lo[f + 1:end] <= sl)[0]; th = np.nonzero(h[f + 1:end] >= tp)[0]
                else:
                    sl = e + sg * a; tp = e - sg * a * rr
                    sh = np.nonzero(h[f + 1:end] >= sl)[0]; th = np.nonzero(lo[f + 1:end] <= tp)[0]
                si = sh[0] if sh.size else 10**9; ti = th[0] if th.size else 10**9
                if si == 10**9 and ti == 10**9:
                    continue
                win = ti < si; rp = sg * a / e * 100
                net = (rr if win else -1.0) - (WIN_RT if win else LOSS_RT) / (rp / 100)
                per_asset[s].append(net); pooled.append((net, mo))
    return per_asset, pooled


def sharpe_monthly(pooled):
    if len(pooled) < 30:
        return -9, 0, 0
    df = pd.DataFrame(pooled, columns=["net", "mo"]); mo = df.groupby("mo")["net"].sum().values
    if len(mo) < 6:
        return -9, 0, 0
    return float(mo.mean() / (mo.std() + 1e-9)), float(mo.mean()), float((mo > 0).mean() * 100)


def main():
    out = []; A = out.append
    A("#1 BREAKER config-робастность на чистом OOS (train 2020-2023 -> test 2024-2026)\n")
    # TRAIN: выбрать (sg,rr) по train-Sharpe с cross-asset>=2/3
    A("=== TRAIN (2020-2023): выбор конфига ===")
    A(f"  {'SL/RR':10}{'trN':>6}{'trSharpe':>9}{'trR/мес':>8}{'cross(BTC/ETH/SOL)':>22}")
    best = (-9, None)
    for sg in SLS:
        for rr in RRS:
            pa, pooled = trades_cfg(sg, rr, lambda y: y <= 2023)
            sh, mm, pos = sharpe_monthly(pooled)
            ca = [np.mean(pa[s]) if pa[s] else float("nan") for s in SYMBOLS]
            npos = sum(1 for x in ca if x > 0)
            ok = npos >= 2
            A(f"  {f'{sg}/{rr}':10}{len(pooled):>6}{sh:>9.2f}{mm:>+8.2f}   {ca[0]:+.2f}/{ca[1]:+.2f}/{ca[2]:+.2f} {'✓' if ok else ''}")
            if ok and sh > best[0]:
                best = (sh, (sg, rr))
    sg, rr = best[1]
    A(f"  -> ВЫБРАН на train: SL{sg}/RR{rr} (train Sharpe {best[0]:.2f}). RR3? {'ДА' if rr==3.0 else 'НЕТ -> '+str(rr)}")
    # TEST: применить без подглядывания
    A("\n=== TEST (2024-2026): применяем train-конфиг ===")
    pa, pooled = trades_cfg(sg, rr, lambda y: y >= 2024)
    sh, mm, pos = sharpe_monthly(pooled)
    ca = [np.mean(pa[s]) if pa[s] else float("nan") for s in SYMBOLS]
    A(f"  SL{sg}/RR{rr}: n={len(pooled)} OOS-Sharpe={sh:.2f} R/мес={mm:+.2f} %плюс={pos:.0f} cross={ca[0]:+.2f}/{ca[1]:+.2f}/{ca[2]:+.2f}")
    A("\n=== ВЕРДИКТ #1 ===")
    robust = sh > 0.15 and sum(1 for x in ca if x > 0) >= 2
    A(f"  {'РОБАСТНО: train-выбранный конфиг держится OOS (Sharpe %.2f, cross %d/3) -> RR3 НЕ подгонка.' % (sh, sum(1 for x in ca if x>0)) if robust else 'НЕ робастно OOS (Sharpe %.2f) -> конфиг был частично подгонкой.' % sh}")
    o = "\n".join(out); (Path(__file__).resolve().parent / "vadim_breaker_oos_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
