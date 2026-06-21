"""etap_264b — permutation-null для double-FVG continuation (#2): edge или мираж?

Вопрос: фильтр (disp>=2.9 ATR + по тренду) реально ОТБИРАЕТ лучше случайного, или
плюс — артефакт малого n / cherry-pick RR? Тест: берём ВСЕ double-FVG (без фильтра),
симулируем; real = подмножество (disp>=2.9 & trend); null = случайные подмножества того
же размера из всех filled double-FVG. p = доля null с R/сд >= real. Плюс RR-робастность.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_264b_null.py BTCUSDT
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from data_manager import load_df, compose_from_base
import zone_harness as ZH
import etap_264_double_fvg_continuation as E

RNG = np.random.default_rng(11); N = 2000


def gen_all(d, atr, ema):
    """ВСЕ double-FVG (без disp/trend фильтра) + мета disp/trend_ok."""
    c = d["close"].values; idx = d.index
    fvgs = E.find_fvgs(d); out = []
    for a in range(len(fvgs)):
        Ad, Ab, At, Ac0, Ac2 = fvgs[a]
        for b in range(a + 1, len(fvgs)):
            Bd, Bb, Bt, Bc0, Bc2 = fvgs[b]
            if Bd != Ad: continue
            if Bc2 - Ac2 > E.PAIR_K: break
            j = Bc2; s = atr[j]
            if not (s > 0): continue
            disp = (c[j] - c[Ac0]) / s if Ad == "LONG" else (c[Ac0] - c[j]) / s
            trend_ok = (c[j] > ema[j]) if Ad == "LONG" else (c[j] < ema[j])
            mid = (Bb + Bt) / 2
            sl = Bb * (1 - E.BUF) if Ad == "LONG" else Bt * (1 + E.BUF)
            out.append(dict(time=idx[j], direction=Ad, entry=float(mid), sl=float(sl),
                            disp=float(disp), trend=bool(trend_ok)))
            break
    seen, dd = set(), []
    for sx in sorted(out, key=lambda x: x["time"]):
        k = (sx["time"], sx["direction"], round(sx["entry"], 1))
        if k in seen: continue
        seen.add(k); dd.append(sx)
    return dd


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    df1h = load_df(sym, "1h")
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    d = compose_from_base(df1h, "12h")
    if d.index.tz is None: d.index = d.index.tz_localize("UTC")
    ema = d["close"].ewm(span=50, adjust=False).mean().values
    pc = d["close"].shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().values
    allsig = gen_all(d, atr, ema)
    print(f"\n{sym}: всех double-FVG {len(allsig)}")
    for rr in (1.5, 2.0, 2.5, 3.0):
        book = ZH.simulate(allsig, df1h, rr=rr, wait_bars=240, hold_bars=720)
        # выровнять meta к книге по (time,direction)
        meta = {(pd.Timestamp(s["time"]), s["direction"]): s for s in allsig}
        book["disp"] = [meta[(pd.Timestamp(t), dr)]["disp"] for t, dr in zip(book.time, book.direction)]
        book["trend"] = [meta[(pd.Timestamp(t), dr)]["trend"] for t, dr in zip(book.time, book.direction)]
        cl = book[book.outcome.isin(["win", "loss"])].copy()
        if len(cl) < 20: continue
        R = cl.R.values
        real_mask = (cl.disp.values >= E.DISP) & (cl.trend.values)
        nf = int(real_mask.sum())
        if nf < 10:
            print(f"  RR={rr}: real подвыборка мала ({nf})"); continue
        real = R[real_mask].mean()
        comp = R[~real_mask].mean()
        # null: случайные подмножества размера nf из всех filled
        null = np.array([R[RNG.choice(len(R), nf, replace=False)].mean() for _ in range(N)])
        p = (null >= real).mean()
        print(f"  RR={rr}: filled {len(cl)} | HQ n={nf} R/сд={real:+.3f} | компл n={len(cl)-nf} R/сд={comp:+.3f} | "
              f"null mean {null.mean():+.3f} 95%={np.quantile(null,0.95):+.3f} -> p={p:.3f}"
              + ("  <<бьёт случай" if p < 0.05 else "  (в нуле)"))


if __name__ == "__main__":
    main()
