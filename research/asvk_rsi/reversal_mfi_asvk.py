"""MFI + ASVK above/below как ДЕТЕКТОР РАЗВОРОТОВ — по методологии Магнитуды.
Reversal-лейбл (как Магнитуда): от close +3% раньше пробоя своего low (long) / -3% раньше пробоя high (short).
Фичи из комбинации: pos=(mfi-below)/(above-below), d_os=mfi-below, d_ob=mfi-above, mfi, bw=above-below.
Метрики: Cohen's d + decile-lift (какие значения отделяют развороты) + net-R лучшего бакета + cross-asset (BTC/ETH/SOL).
long на 8h, short на 12h. Запуск: venv/Scripts/python.exe research/asvk_rsi/reversal_mfi_asvk.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "smc-lib"))
sys.path.insert(0, str(ROOT / "research" / "reversal_cb"))
from indicators.rsi_asvk import adjusted_rsi  # noqa: E402
from rr_native import native  # noqa: E402 (entry close, TP±3%, SL свой low/high -> y, R, risk)

THR = 0.03
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
SPECS = {"long": "8h", "short": "12h"}


def load(sym, tf):
    d = pd.read_csv(ROOT / "data" / f"{sym}_{tf}.csv")
    tc = [c for c in d.columns if "time" in c.lower()][0]
    d[tc] = pd.to_datetime(d[tc], utc=True)
    return d.set_index(tc).sort_index()


def mfi(df, period=14):
    tp = (df.high + df.low + df.close) / 3.0
    rmf = tp * df.volume
    pos = rmf.where(tp > tp.shift(1), 0.0).rolling(period).sum()
    neg = rmf.where(tp < tp.shift(1), 0.0).rolling(period).sum()
    return (100 - 100 / (1 + pos / neg.replace(0, np.nan))).values


def cohend(a, b):
    if len(a) < 5 or len(b) < 5:
        return np.nan
    s = np.sqrt(((len(a) - 1) * np.var(a) + (len(b) - 1) * np.var(b)) / (len(a) + len(b) - 2)) + 1e-12
    return (np.mean(a) - np.mean(b)) / s


def build(direction, tf):
    rows = []
    for sym in SYMS:
        df = load(sym, tf)
        y, R, risk = native(df, direction, 0.0010, 0.0010)
        ar = adjusted_rsi(df.close.tolist())
        above = np.array([np.nan if x is None else x for x in ar["above"]], float)
        below = np.array([np.nan if x is None else x for x in ar["below"]], float)
        mm = mfi(df)
        bw = above - below
        pos = (mm - below) / (bw + 1e-9)
        X = pd.DataFrame({"mfi": mm, "above": above, "below": below, "bw": bw,
                          "pos": pos, "d_os": mm - below, "d_ob": mm - above,
                          "y": y, "R": R, "sym": sym})
        rows.append(X)
    P = pd.concat(rows, ignore_index=True)
    return P[(P.y >= 0) & P[["mfi", "above", "below"]].notna().all(axis=1)].reset_index(drop=True)


def analyze(direction, tf, out):
    P = build(direction, tf)
    y = P.y.values.astype(int); base = y.mean()
    out.append(f"\n{'='*64}\n  {direction.upper()} ({tf}) — n={len(P)}, base reversal-rate={base:.3f}, "
               f"ср.net-R={P.R.mean():+.3f}\n{'='*64}")
    feats = ["pos", "d_os", "d_ob", "mfi", "below", "above", "bw"]
    out.append(f"  {'фича':8}{'Cohen d':>9}{'lift_hi':>9}{'lift_lo':>9}  (lift=P(rev|дециль)/base)")
    rk = []
    for f in feats:
        x = P[f].values
        d = cohend(x[y == 1], x[y == 0])
        hi = x >= np.nanquantile(x, 0.9); lo = x <= np.nanquantile(x, 0.1)
        lh = y[hi].mean() / base if hi.sum() > 20 else np.nan
        ll = y[lo].mean() / base if lo.sum() > 20 else np.nan
        rk.append((f, d, lh, ll))
    for f, d, lh, ll in sorted(rk, key=lambda r: -abs(r[1]) if not np.isnan(r[1]) else 0):
        out.append(f"  {f:8}{d:>+9.3f}{lh:>9.2f}{ll:>9.2f}")

    # ЛУЧШАЯ комбинация: для long ждём низкий pos (глубокий OS), для short — высокий pos (глубокий OB)
    out.append("\n  ЛУЧШИЕ ЗНАЧЕНИЯ-КОМБО (бакет pos) — reversal-rate, lift, net-R, cross-asset:")
    q = P.pos.values
    buckets = [("pos<10%", q <= np.nanquantile(q, 0.1)),
               ("pos 10-25%", (q > np.nanquantile(q, 0.1)) & (q <= np.nanquantile(q, 0.25))),
               ("pos 25-75%", (q > np.nanquantile(q, 0.25)) & (q <= np.nanquantile(q, 0.75))),
               ("pos 75-90%", (q > np.nanquantile(q, 0.75)) & (q <= np.nanquantile(q, 0.9))),
               ("pos>90%", q >= np.nanquantile(q, 0.9))]
    for name, mb in buckets:
        s = P[mb]
        if len(s) < 30:
            continue
        per = s.groupby("sym").apply(lambda g: (g.y > 0).mean(), include_groups=False)
        cross = "/".join(f"{k[:3]}{v:.2f}" for k, v in per.items())
        out.append(f"    {name:12} n={len(s):5} rev-rate={(s.y>0).mean():.3f} (lift {(s.y>0).mean()/base:.2f}) "
                   f"net-R={s.R.mean():+.3f}  per-asset {cross}")
    # явная OS/OB-комбинация (mfi относительно полос)
    out.append("\n  ЯВНО (mfi vs полосы):")
    for name, mb in [("mfi<below (OS)", P.mfi < P.below), ("mfi>above (OB)", P.mfi > P.above),
                     ("глубокий OS d_os<10%", P.d_os <= np.nanquantile(P.d_os, 0.1)),
                     ("глубокий OB d_ob>90%", P.d_ob >= np.nanquantile(P.d_ob, 0.9))]:
        s = P[mb]
        if len(s) >= 30:
            out.append(f"    {name:22} n={len(s):5} rev-rate={(s.y>0).mean():.3f} (lift {(s.y>0).mean()/base:.2f}) net-R={s.R.mean():+.3f}")


def main():
    out = ["="*64, " MFI×ASVK above/below как детектор разворотов (методология Магнитуды)", "="*64]
    for direction, tf in SPECS.items():
        analyze(direction, tf, out)
    out.append("\n  Сравнение с Магнитудой: там CatBoost на 22 фичах дал reversal cross-asset, но net-R≈0 (вола-RR).")
    out.append("  Здесь смотрим, добавляет ли MFI×ASVK-комбо selectivity/net-R сверх базы — и cross-asset ли это.")
    o = "\n".join(out); (Path(__file__).resolve().parent / "reversal_mfi_asvk_report.txt").write_text(o, encoding="utf-8")
    print(o)


if __name__ == "__main__":
    main()
