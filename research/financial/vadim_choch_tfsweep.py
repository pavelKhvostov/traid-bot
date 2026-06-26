"""#2 TF-sweep CHoCH/BOS -> OB (ядро C4/C5) — живёт ли структурный слом Вадима на HTF, как breaker?

На каждом ТФ: scan_market_structure -> события CHoCH(разворот)/BOS(продолжение). На break_idx ищем первый OB
той же стороны в ближайшие ~12 баров -> вход в зону OB. Батарея bracket-independent: signed@6 ATR + null + сетка SL×RR.
Раздельно CHoCH и BOS, по всем ТФ. Флаг HTF-инфы.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_choch_tfsweep.py
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
from elements.choch_bos.code import scan_market_structure  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ALL_TFS = ["1h", "2h", "4h", "6h", "8h", "12h", "1d"]
WIN_RT, LOSS_RT = 0.0005, 0.0010
SL_GRID = [0.5, 1.0, 1.5, 2.0]; RR_GRID = [1.5, 2.0, 3.0]
GRID_CAP = 1500
RNG = np.random.default_rng(7)


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


def setups(dtf, atr, want):
    """want in {'CHoCH','BOS'} -> list (d, entry, atr, fill_idx) using OB after structure break."""
    o, h, lo, c = (dtf[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = dtf.index.view("int64") // 1_000_000
    cnd = [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i])) for i in range(len(dtf))]
    n = len(cnd)
    try:
        evs = scan_market_structure(cnd)
    except Exception:
        return []
    out = []
    for ev in evs:
        if ev.type != want:
            continue
        bi = ev.break_idx
        if bi is None or bi >= n - 2 or not np.isfinite(atr[bi]) or atr[bi] <= 0:
            continue
        d = 1 if ev.side == "bullish" else -1
        wantdir = "long" if d == 1 else "short"
        # первый OB той же стороны в ближайшие 12 баров после слома
        e = None
        for k in range(bi + 1, min(bi + 13, n)):
            ob = detect_ob(cnd[k - 1], cnd[k])
            if ob is not None and ob.direction == wantdir:
                zlo, zhi = ob.zone
                if zhi > zlo:
                    e = 0.5 * (zlo + zhi); ob_k = k; break
        if e is None:
            continue
        # fill = первый бар после OB, касающийся entry
        f = None
        for j in range(ob_k + 1, min(ob_k + 41, n)):
            if lo[j] <= e <= h[j]:
                f = j; break
        if f is None or f + 1 >= n:
            continue
        out.append((d, float(e), float(atr[bi]), f))
    return out


def battery(rows, h, lo, c):
    if len(rows) < 50:
        return None
    n = len(c)
    sr = [d * (c[f + 6] - e) / a for (d, e, a, f) in rows if f + 6 < n]
    real = float(np.mean(sr))
    uns = np.abs(np.array(sr))
    nulls = [float(np.mean(RNG.choice([-1, 1], len(uns)) * uns)) for _ in range(250)]
    null_p = float((np.array(nulls) >= real).mean())
    gr = rows if len(rows) <= GRID_CAP else [rows[i] for i in RNG.choice(len(rows), GRID_CAP, replace=False)]
    best = -9
    for sg in SL_GRID:
        for rr in RR_GRID:
            w = l = 0
            for (d, e, a, f) in gr:
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
                w += int(ti < si); l += int(si <= ti)
            nn = w + l
            if nn < 30:
                continue
            rp = sg * np.median([r[2] for r in gr]) / np.median([r[1] for r in gr]) * 100
            ptt = (w * rr - l) / nn - (WIN_RT * w + LOSS_RT * l) / nn / (rp / 100)
            best = max(best, ptt)
    return dict(n=len(rows), signed=real, null_p=null_p, best=best)


def main():
    out = []; A = out.append
    A("#2 TF-sweep CHoCH/BOS -> OB (структурный слом Вадима на всех ТФ)\n")
    for want in ("CHoCH", "BOS"):
        A(f"=== {want} -> OB (pooled BTC+ETH+SOL) ===")
        for tf in ALL_TFS:
            allrows = []; HI = LO = CL = None; sr_all = []; bests = []; ns = 0
            for s in SYMBOLS:
                d1 = load_1m(s); dtf = rs(d1, tf); atr = atr_tf(dtf)
                rows = setups(dtf, atr, want)
                if not rows:
                    continue
                h = dtf.high.values; lo = dtf.low.values; c = dtf.close.values
                b = battery(rows, h, lo, c)
                if b:
                    sr_all += [d * (c[f + 6] - e) / a for (d, e, a, f) in rows if f + 6 < len(c)]
                    bests.append(b["best"]); ns += b["n"]
            if ns < 80 or len(sr_all) < 50:
                A(f"  {tf:>4}: мало ({ns})"); continue
            real = float(np.mean(sr_all)); uns = np.abs(np.array(sr_all))
            nulls = [float(np.mean(RNG.choice([-1, 1], len(uns)) * uns)) for _ in range(250)]
            null_p = float((np.array(nulls) >= real).mean())
            info = null_p < 0.10 and max(bests) > 0.05
            A(f"  {tf:>4}: n={ns:>5} signed@6={real:+.3f} null_p={null_p:.2f} best_grid(max-asset)={max(bests):+.3f} {'ИНФА?' if info else 'пусто'}")
        A("")
    A("=== ВЕРДИКТ #2 ===")
    A("  Если CHoCH/BOS->OB даёт signed бьёт null + плюс-grid на HTF (как breaker) -> ещё кандидат-диверсификатор.")
    A("  Если пусто/анти на HTF -> только breaker из структурных элементов Вадима живой.")
    o = "\n".join(out); (Path(__file__).resolve().parent / "vadim_choch_tfsweep_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
