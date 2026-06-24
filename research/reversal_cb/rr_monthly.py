"""ПОМЕСЯЧНАЯ прибыль 2 кандидатов: ①8h LONG RR[2.5,4) + ②12h SHORT RR[1.5,4).
Сделки OOS (walk-forward селектор), книжим net-R по месяцу ВЫХОДА. Пул BTC/ETH/SOL.
Вывод: месячный R (по годам), summary (avg/med/%плюс/Sharpe/maxDD), и % при риске 1%/сделку. Косты TAKER 10/10 и MAKER 2/10.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_monthly.py
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


def native_ex(df, direction, win_rt, loss_rt):
    c = df.close.values; h = df.high.values; lo = df.low.values; n = len(c)
    y = np.full(n, -1); R = np.full(n, np.nan); risk = np.full(n, np.nan); ex = np.full(n, -1)
    for i in range(n - 2):
        if direction == "long":
            stop = lo[i]; tgt = c[i] * (1 + THR); rk = (c[i] - stop) / c[i]
        else:
            stop = h[i]; tgt = c[i] * (1 - THR); rk = (stop - c[i]) / c[i]
        if rk <= 1e-5:
            continue
        risk[i] = rk; RR = THR / rk; res = 0; end = min(i + 1 + CAP, n); j = end - 1
        for jj in range(i + 1, end):
            if direction == "long":
                if lo[jj] < stop:
                    res = -1; j = jj; break
                if h[jj] >= tgt:
                    res = 1; j = jj; break
            else:
                if h[jj] > stop:
                    res = -1; j = jj; break
                if lo[jj] <= tgt:
                    res = 1; j = jj; break
        ex[i] = j
        if res == 1:
            y[i] = 1; R[i] = RR - win_rt / rk
        elif res == -1:
            y[i] = 0; R[i] = -1 - loss_rt / rk
        else:
            y[i] = 0; ret = (c[j] - c[i]) / c[i] * (1 if direction == "long" else -1); R[i] = ret / rk - loss_rt / rk
    return y, R, risk, ex


def trades(tf, direction, rlo, rhi, win_rt, loss_rt, flag_pct=0.70):
    rows = []
    for s in SYMS:
        df = load(s, tf); X = feats(df)
        y, R, risk, ex = native_ex(df, direction, win_rt, loss_rt)
        m = (y >= 0) & X[FEATS].notna().all(axis=1).values & np.isfinite(risk)
        Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
        proba, foldid = wf_raw(Xf, yf); uu = foldid >= 0
        pr = proba[uu]; thr = np.quantile(pr, flag_pct)
        RRv = (THR / risk[m][uu])
        fl = (RRv >= rlo) & (RRv < rhi) & (pr >= thr)
        exp = ex[m][uu][fl]; Rs = R[m][uu][fl]
        ext = df.index[exp]
        for t, r in zip(ext, Rs):
            rows.append((t, float(r), s, direction))
    return rows


def stats(monthly, tag, out, risk_pct=1.0):
    if len(monthly) == 0:
        out.append(f"  {tag}: нет сделок"); return
    avg = monthly.mean(); med = monthly.median(); pos = (monthly > 0).mean()
    sh = avg / (monthly.std() + 1e-9) * np.sqrt(12)
    cum = monthly.cumsum(); dd = (cum - cum.cummax()).min()
    out.append(f"  {tag}: мес.R avg={avg:+.2f} med={med:+.2f} | плюс-мес {pos*100:.0f}% | "
               f"Sharpe(год)={sh:.2f} | maxDD={dd:+.1f}R | ΣR={monthly.sum():+.0f} ({len(monthly)} мес)")
    out.append(f"     при риске {risk_pct:.0f}%/сделку: ~{avg*risk_pct:+.2f}%/мес  (год ~{avg*risk_pct*12:+.1f}%)")


def main():
    out = ["="*78, " ПОМЕСЯЧНАЯ ПРИБЫЛЬ: ①8h LONG RR2.5-4 + ②12h SHORT RR1.5-4 (OOS, пул 3 актива)", "="*78]
    for cost_name, wr_, lr_ in [("TAKER 10/10bps", 0.0010, 0.0010), ("MAKER 2/10bps", 0.0002, 0.0010)]:
        out.append(f"\n{'='*64}\n  КОСТЫ {cost_name}\n{'='*64}")
        t1 = trades("8h", "long", 2.5, 4.0, wr_, lr_)
        t2 = trades("12h", "short", 1.5, 4.0, wr_, lr_)
        df1 = pd.DataFrame(t1, columns=["t", "R", "sym", "dir"]).set_index("t").sort_index()
        df2 = pd.DataFrame(t2, columns=["t", "R", "sym", "dir"]).set_index("t").sort_index()
        dfc = pd.concat([df1, df2]).sort_index()
        m1 = df1.R.resample("MS").sum(); m2 = df2.R.resample("MS").sum()
        mc = dfc.R.resample("MS").sum()
        # выровнять на общий период
        idx = pd.date_range(min(mc.index.min(), m1.index.min()), mc.index.max(), freq="MS")
        m1 = m1.reindex(idx, fill_value=0); m2 = m2.reindex(idx, fill_value=0); mc = mc.reindex(idx, fill_value=0)
        out.append(f"\n  период: {idx.min():%Y-%m} … {idx.max():%Y-%m}  (сделок: long {len(df1)}, short {len(df2)})")
        stats(m1, "① 8h LONG ", out)
        stats(m2, "② 12h SHORT", out)
        stats(mc, "КОМБО ①+②", out)
        # помесячно по годам (комбо)
        out.append("\n  КОМБО — месячный R по годам:")
        tb = mc.copy(); tb.index = pd.MultiIndex.from_arrays([tb.index.year, tb.index.month])
        for yr in sorted({i[0] for i in tb.index}):
            vals = {mo: tb.get((yr, mo), 0.0) for mo in range(1, 13)}
            line = " ".join(f"{vals[mo]:+5.1f}" if (yr, mo) in tb.index else "    ." for mo in range(1, 13))
            tot = sum(v for (y_, mo), v in tb.items() if y_ == yr)
            out.append(f"    {yr}: {line}  | Σ{tot:+.1f}R")
    out.append("\n  * R = в единицах риска сделки; %/мес = R×(риск/сделку). Косты учтены. OOS walk-forward.")
    o = "\n".join(out); (HERE / "rr_monthly_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
