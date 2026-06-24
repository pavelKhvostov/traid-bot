"""RR-АНАЛИТИКА монетизации разворотного модуля: развязать RR от геометрии (ATR-стоп вместо своего low).
Селектор = доказанный навык модели (reversal-likelihood, walk-forward OOS). Сделка = ATR-брекет:
вход close, стоп = k*ATR, цель = RR*k*ATR (фикс. RR, развязан от c2l). Сетка (k × RR) -> net-R/wr/ΣR.
КОНТРОЛИ: matched-random-null (тот же брекет на НЕ-флагнутых свечах) + cross-asset(per-asset) + год-стабильность.
Косты: taker 10bps RT (рыночный вход) и maker 2bps. long & short, 8h/12h.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_analytics.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from reversal_analysis import load, feats  # noqa: E402
from reversal_module import FEATS, label_and_outcome  # noqa: E402
from ev_rescue import wf_raw  # noqa: E402
HERE = Path(__file__).resolve().parent
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RNG = np.random.default_rng(7)
K_GRID = [1.0, 1.5, 2.0]
RR_GRID = [1.5, 2.0, 2.5, 3.0]
CAP = 120


def atr_arr(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=5).mean().values


def bracket_R(df, atr, positions, direction, k, RR, cost):
    c = df.close.values; h = df.high.values; lo = df.low.values; n = len(c)
    Rs = []; tt = []
    for i in positions:
        a = atr[i]
        if i + 2 >= n or not np.isfinite(a) or a <= 0:
            continue
        risk = k * a; rp = risk / c[i]
        if direction == "long":
            stop = c[i] - risk; tgt = c[i] + RR * risk
        else:
            stop = c[i] + risk; tgt = c[i] - RR * risk
        res = 0; end = min(i + 1 + CAP, n)
        for j in range(i + 1, end):
            if direction == "long":
                if lo[j] <= stop:
                    res = -1; break
                if h[j] >= tgt:
                    res = 1; break
            else:
                if h[j] >= stop:
                    res = -1; break
                if lo[j] <= tgt:
                    res = 1; break
        cost_R = cost / rp
        if res == 1:
            Rs.append(RR - cost_R); tt.append(i)
        elif res == -1:
            Rs.append(-1 - cost_R); tt.append(i)
        else:
            jx = end - 1; ret = (c[jx] - c[i]) / c[i] * (1 if direction == "long" else -1)
            Rs.append(ret / rp - cost_R); tt.append(i)
    return np.array(Rs), np.array(tt)


def selector_positions(sym, tf, direction, flag_pct=0.70):
    """walk-forward OOS reversal-likelihood -> позиции df флагнутых (top) и не-флагнутых."""
    df = load(sym, tf); X = feats(df); y, R, kind = label_and_outcome(df, direction)
    m = (y >= 0) & X[FEATS].notna().all(axis=1).values
    posall = np.where(m)[0]
    Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
    proba, foldid = wf_raw(Xf, yf)
    uu = foldid >= 0
    pos_oos = posall[uu]; pr = proba[uu]
    thr = np.quantile(pr, flag_pct)
    flagged = pos_oos[pr >= thr]
    unflag = pos_oos[pr < thr]
    return df, atr_arr(df), flagged, unflag


def main():
    out = ["="*78, " RR-АНАЛИТИКА монетизации (ATR-стоп, селектор=reversal-модель) — long & short", "="*78,
           " вход close, стоп=k*ATR, цель=RR*k*ATR; косты taker 10bps; CAP=120 баров; флаг=top30% уверенности"]
    A = out.append
    COST = 0.0010
    for tf in ["12h", "8h"]:
        for direction in ["long", "short"]:
            A(f"\n{'='*70}\n  TF {tf} · {direction.upper()}\n{'='*70}")
            sel = {s: selector_positions(s, tf, direction) for s in SYMS}
            A(f"  {'k×RR':>8}{'n':>7}{'win%':>7}{'netR':>8}{'ΣR':>8}{'cross':>7}{'null_netR':>10}{'edge':>7}")
            best = None
            for k in K_GRID:
                for RR in RR_GRID:
                    per = {}; nulls = []; allR = []
                    for s in SYMS:
                        df, atr, fl, un = sel[s]
                        Rf, _ = bracket_R(df, atr, fl, direction, k, RR, COST)
                        if len(Rf) < 20:
                            continue
                        per[s] = float(np.mean(Rf)); allR.append(Rf)
                        # matched-random-null: столько же случайных НЕ-флагнутых
                        rs = RNG.choice(un, size=min(len(fl), len(un)), replace=False)
                        Rn, _ = bracket_R(df, atr, rs, direction, k, RR, COST)
                        if len(Rn):
                            nulls.append(float(np.mean(Rn)))
                    if not allR:
                        continue
                    pooled = np.concatenate(allR)
                    netR = float(np.mean(pooled)); wr = float(np.mean(pooled > 0))
                    cross = sum(1 for v in per.values() if v > 0)
                    null_net = float(np.mean(nulls)) if nulls else float("nan")
                    edge = netR - null_net
                    A(f"  {k}×{RR:>3}{len(pooled):>7}{wr*100:>6.1f}{netR:>+8.3f}{np.sum(pooled):>+8.0f}"
                      f"{cross:>5}/3{null_net:>+10.3f}{edge:>+7.3f}")
                    score = (netR, cross, edge)
                    if best is None or (cross >= 2 and edge > 0 and netR > best[0]):
                        best = (netR, cross, edge, k, RR)
            if best and best[1] >= 2 and best[2] > 0:
                A(f"  >>> ЛУЧШИЙ: k={best[3]}×RR{best[4]} netR={best[0]:+.3f} cross{best[1]}/3 edge_над_null={best[2]:+.3f}")
            else:
                A("  >>> робастного (cross>=2 И edge>null>0) конфига НЕТ")
        (HERE / "rr_analytics_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
