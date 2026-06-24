"""RR-монетизация НА НАТУРАЛЬНОМ барьере (стоп=свой low/high → RR=3%/риск варьируется).
Поправка к ошибке: ATR-стоп сплющивал RR; деньги — в тугостопных (низко-c2l) высоко-RR сигналах.
Тест: НЕ отсеивать, а ОТБИРАТЬ по RR-бакетам; net-R flagged vs matched-random-null в ТОМ ЖЕ бакете.
Косты: TAKER(вход+TP+стоп market 10/10bps) и MAKER(вход+TP лимит 2bps, стоп market 10bps) — тугой стоп чувствителен.
long & short, 12h/8h. Селектор = reversal-likelihood (walk-forward OOS).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_native.py
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
HERE = Path(__file__).resolve().parent
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RNG = np.random.default_rng(7)
RR_BUCKETS = [(0, 1.5), (1.5, 2.5), (2.5, 4), (4, 7), (7, 999)]


def native(df, direction, win_rt, loss_rt):
    """первопроход на натуральном барьере, R с cost-split. Возвращает y, R, risk(=c2l)."""
    c = df.close.values; h = df.high.values; lo = df.low.values; n = len(c)
    y = np.full(n, -1); R = np.full(n, np.nan); risk = np.full(n, np.nan)
    for i in range(n - 2):
        if direction == "long":
            stop = lo[i]; tgt = c[i] * (1 + THR); rk = (c[i] - stop) / c[i]
        else:
            stop = h[i]; tgt = c[i] * (1 - THR); rk = (stop - c[i]) / c[i]
        if rk <= 1e-5:
            continue
        risk[i] = rk; RR = THR / rk
        res = 0; end = min(i + 1 + CAP, n)
        for j in range(i + 1, end):
            if direction == "long":
                if lo[j] < stop:
                    res = -1; break
                if h[j] >= tgt:
                    res = 1; break
            else:
                if h[j] > stop:
                    res = -1; break
                if lo[j] <= tgt:
                    res = 1; break
        if res == 1:
            y[i] = 1; R[i] = RR - win_rt / rk
        elif res == -1:
            y[i] = 0; R[i] = -1 - loss_rt / rk
        else:
            y[i] = 0; jx = end - 1
            ret = (c[jx] - c[i]) / c[i] * (1 if direction == "long" else -1)
            R[i] = ret / rk - loss_rt / rk
    return y, R, risk


def run(direction, tf, win_rt, loss_rt, out):
    A = out.append
    # селектор + натуральные R по активам
    data = {}
    for s in SYMS:
        df = load(s, tf); X = feats(df)
        y, R, risk = native(df, direction, win_rt, loss_rt)
        m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
        Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
        proba, foldid = wf_raw(Xf, yf)
        uu = foldid >= 0
        data[s] = dict(p=proba[uu], y=yf[uu], R=R[m][uu], risk=risk[m][uu])
    # порог флага = top30% уверенности (per asset)
    for s in data:
        data[s]["thr"] = np.quantile(data[s]["p"], 0.70)
    A(f"\n  {'RR-бакет':>10}{'n_flag':>8}{'win%':>7}{'netR_flag':>11}{'netR_null':>11}{'edge':>8}{'cross':>7}")
    for lo_rr, hi_rr in RR_BUCKETS:
        fR = []; nR = []; per = {}
        for s, d in data.items():
            RRv = THR / d["risk"]
            inb = (RRv >= lo_rr) & (RRv < hi_rr)
            fl = inb & (d["p"] >= d["thr"])
            nu = inb & (d["p"] < d["thr"])
            if fl.sum() >= 15:
                fR.append(d["R"][fl]); per[s] = float(np.mean(d["R"][fl]))
                if nu.sum() >= 15:
                    rs = RNG.choice(np.where(nu)[0], size=min(fl.sum(), nu.sum()), replace=False)
                    nR.append(d["R"][rs])
        if not fR:
            A(f"  {f'{lo_rr}-{hi_rr}':>10}{'мало':>8}"); continue
        pooled = np.concatenate(fR); nulls = np.concatenate(nR) if nR else np.array([np.nan])
        netf = float(np.mean(pooled)); netn = float(np.nanmean(nulls))
        wr = float(np.mean(pooled > 0)); cross = sum(1 for v in per.values() if v > 0)
        A(f"  {f'{lo_rr}-{hi_rr}':>10}{len(pooled):>8}{wr*100:>6.1f}{netf:>+11.3f}{netn:>+11.3f}"
          f"{netf-netn:>+8.3f}{cross:>5}/3")


def main():
    out = ["="*80, " RR-МОНЕТИЗАЦИЯ НА НАТУРАЛЬНОМ БАРЬЕРЕ (стоп=свой low/high, RR=3%/риск)", "="*80]
    for tf in ["12h", "8h"]:
        for direction in ["long", "short"]:
            for cost_name, wr_, lr_ in [("TAKER 10/10bps", 0.0010, 0.0010), ("MAKER 2/10bps", 0.0002, 0.0010)]:
                out.append(f"\n{'='*64}\n  TF {tf} · {direction.upper()} · косты {cost_name}\n{'='*64}")
                run(direction, tf, wr_, lr_, out)
            (HERE / "rr_native_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
