"""MAKER-исполнение для Магнитуды — честно, с риском незаполнения лимитки.
Сравнение по комбо (①8h long RR2.5-4 + ②12h short RR1.5-4):
- TAKER: вход=close (market), кост RT 10/10 bps.
- MAKER cost-only: вход=close, всегда залит, кост 2/10 (вход+TP maker, стоп taker) — ОПТИМИСТИЧНЫЙ потолок.
- MAKER limit off%: лимит лучше close на off, залит только если цена коснулась за F баров (иначе сделка ПРОПУЩЕНА);
  залит → лучше вход (выше RR) но adverse-selection (наливают когда цена идёт против). off ∈ {0.10%, 0.20%}.
TP=абсолютный close*(1±3%), стоп=свой low/high. Метрики: n, fill%, net-R/сделку, ΣR, Sharpe(мес), 2024/2025 ΣR.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/maker_exec.py
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
from reversal_analysis import load, feats, THR, CAP  # noqa: E402
from reversal_module import FEATS  # noqa: E402
from ev_rescue import wf_raw  # noqa: E402
from rr_native import native  # noqa: E402
HERE = Path(__file__).resolve().parent
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
F = 3  # окно заполнения лимитки (баров)


def positions(tf, direction, rlo, rhi):
    out = []
    for s in SYMS:
        df = load(s, tf); X = feats(df); y, R, risk = native(df, direction, 0.0010, 0.0010)
        m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
        posall = np.where(m)[0]
        Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
        proba, foldid = wf_raw(Xf, yf); uu = foldid >= 0
        pr = proba[uu]; thr = np.quantile(pr, 0.70); RRv = THR / risk[m][uu]
        fl = (pr >= thr) & (RRv >= rlo) & (RRv < rhi)
        sel = posall[uu][fl]
        out.append((s, df, direction, sel))
    return out


def simulate(packs, mode, off=0.0, win_rt=0.0010, loss_rt=0.0010):
    rows = []
    for (s, df, direction, sel) in packs:
        c = df.close.values; h = df.high.values; lo = df.low.values; n = len(c); idx = df.index
        lng = direction == "long"
        for i in sel:
            stop = lo[i] if lng else h[i]
            target = c[i] * (1 + THR) if lng else c[i] * (1 - THR)
            end = min(i + 1 + CAP, n)
            res_fill = 0; jf = None
            if mode in ("taker", "maker_close"):
                entry = c[i]; fbar = i; filled = True
            else:  # maker_limit — единый честный скан: заполнение + стоп/цель консистентно
                limit = c[i] * (1 - off) if lng else c[i] * (1 + off)
                filled = False; entry = None; fbar = None; res_fill = 0; jf = None
                for k in range(i + 1, end):
                    if (k - i) > F:           # окно заполнения истекло без филла
                        break
                    touched = (lo[k] <= limit) if lng else (h[k] >= limit)
                    if touched:
                        filled = True; entry = limit; fbar = k
                        # тот же бар: консервативно стоп-первым
                        if lng:
                            if lo[k] < stop: res_fill = -1; jf = k
                            elif h[k] >= target: res_fill = 1; jf = k
                        else:
                            if h[k] > stop: res_fill = -1; jf = k
                            elif lo[k] <= target: res_fill = 1; jf = k
                        break
                    # не залит на этом баре: если цель достигнута ДО филла -> промах винёра, сделки нет
                    reached = (h[k] >= target) if lng else (lo[k] <= target)
                    if reached:
                        filled = False; break
                if not filled:
                    continue
            risk = (entry - stop) / entry if lng else (stop - entry) / entry
            if risk <= 1e-5:
                continue
            # исход
            res = 0; j = end - 1
            if res_fill != 0:
                res = res_fill; j = jf
            else:
                for k in range(fbar + 1, end):
                    if lng:
                        if lo[k] < stop: res = -1; j = k; break
                        if h[k] >= target: res = 1; j = k; break
                    else:
                        if h[k] > stop: res = -1; j = k; break
                        if lo[k] <= target: res = 1; j = k; break
            if res == 1:
                R = (abs(target - entry) / entry) / risk - win_rt / risk
            elif res == -1:
                R = -1 - loss_rt / risk
            else:
                ret = (c[j] - entry) / entry * (1 if lng else -1)
                R = ret / risk - loss_rt / risk
            rows.append((idx[j], float(R)))
    return rows


def report(name, taker_n, rows, out):
    if not rows:
        out.append(f"  {name:22} нет сделок"); return
    ser = pd.Series([r for _, r in rows], index=pd.DatetimeIndex([t for t, _ in rows]))
    M = ser.resample("MS").sum()
    sh = M.mean() / (M.std() + 1e-9) * np.sqrt(12)
    yr = ser.groupby(ser.index.year).sum()
    fill = 100 * len(rows) / taker_n
    out.append(f"  {name:22} n={len(rows):4} fill={fill:5.0f}% net-R={ser.mean():+.3f} ΣR={ser.sum():+5.0f} "
               f"Sharpe={sh:.2f} | 2024:{yr.get(2024,0):+.0f} 2025:{yr.get(2025,0):+.0f}")


def main():
    out = ["="*82, " MAKER vs TAKER для Магнитуды (с риском незаполнения лимитки, комбо ①+②)", "="*82,
           f" TP=±{THR*100:.0f}% абс, стоп=свой low/high, окно филла={F} бара"]
    packs = positions("8h", "long", 2.5, 4.0) + positions("12h", "short", 1.5, 4.0)
    base = simulate(packs, "taker", win_rt=0.0010, loss_rt=0.0010)
    tn = len(base)
    report("TAKER 10/10", tn, base, out)
    report("MAKER cost-only 2/10", tn, simulate(packs, "maker_close", win_rt=0.0002, loss_rt=0.0010), out)
    report("MAKER limit 0.10% 2/10", tn, simulate(packs, "maker_limit", off=0.0010, win_rt=0.0002, loss_rt=0.0010), out)
    report("MAKER limit 0.20% 2/10", tn, simulate(packs, "maker_limit", off=0.0020, win_rt=0.0002, loss_rt=0.0010), out)
    out.append("\n  -> MAKER 'живой', если net-R/Sharpe ВЫШЕ taker ПОСЛЕ просадки fill% (limit-варианты). "
               "cost-only = недостижимый потолок (без риска незаполнения).")
    o = "\n".join(out); (HERE / "maker_exec_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
