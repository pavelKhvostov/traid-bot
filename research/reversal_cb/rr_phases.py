"""ФАЗЫ РЫНКА для Магнитуды: когда стратегия работает хорошо/плохо + walk-forward детектор «выключиться заранее».
Дескрипторы (известны в начале месяца): BTC тренд90, вола-перцентиль, вола-волы(30d), кросс-актив дисперсия,
+ СОБСТВЕННАЯ трейлинг-эквити стратегии (3 мес).
A) терцили месяцев по net-R -> средние дескрипторов («почему»).
B) walk-forward гейт по каждому дескриптору (решение только по прошлому) -> Sharpe/ΣR/год vs база.
КАВЕАТ: 2 плохих периода -> детектор почти невалидируем OOS. Если ни один не бьёт базу робастно -> фаза не детектируется.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_phases.py
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
from reversal_analysis import load  # noqa: E402
from vol_gate import collect  # noqa: E402  (reversal-комбо сделки)
HERE = Path(__file__).resolve().parent


def btc_descriptors():
    b = load("BTCUSDT", "1d"); e = load("ETHUSDT", "1d"); s = load("SOLUSDT", "1d")
    c = b.close; rb = c.pct_change(); re = e.close.pct_change(); rs = s.close.pct_change()
    h, l, pc = b.high, b.low, c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    atr = pd.Series(tr).rolling(14).mean()
    df = pd.DataFrame({
        "trend90": (c / c.shift(90) - 1).values,                  # тренд (бык/медв, сила)
        "volp": atr.rolling(200).rank(pct=True).values,           # уровень волы
        "volofvol": rb.rolling(30).std().rolling(30).std().values,  # нестабильность волы
        "vol30": rb.rolling(30).std().values,
    }, index=c.index)
    disp = pd.concat([rb, re, rs], axis=1).std(axis=1).rolling(30).mean()  # кросс-актив дисперсия
    df["dispersion"] = disp.reindex(df.index).values
    df["ym"] = df.index.to_period("M")
    monthly = df.groupby("ym").last().drop(columns=[]) if False else df.groupby("ym").last()
    return monthly.shift(1)   # значение на КОНЕЦ прошлого месяца = известно в начале текущего


def sharpe(x):
    x = np.asarray(x, float)
    return x.mean() / (x.std() + 1e-9) * np.sqrt(12)


def wf_gate(M, desc, n_min=14):
    """walk-forward: в месяц t делим прошлые месяцы по медиане дескриптора, выключаемся если текущий в ХУДШЕЙ половине."""
    g = M.copy().astype(float); paused = 0
    for i in range(len(M)):
        if i < n_min or np.isnan(desc.iloc[i]):
            continue
        pd_ = desc.iloc[:i].dropna(); pm = M.iloc[:i].reindex(pd_.index)
        if len(pd_) < 8:
            continue
        med = pd_.median()
        hi = pm[pd_ >= med].mean(); lo = pm[pd_ < med].mean()
        bad_high = hi < lo
        cur = desc.iloc[i]
        in_bad = (cur >= med) if bad_high else (cur < med)
        if in_bad:
            g.iloc[i] = 0.0; paused += 1
    return g, paused


def main():
    out = ["="*74, " ФАЗЫ РЫНКА для Магнитуды: когда хорошо/плохо + walk-forward детектор фазы", "="*74]
    A = out.append
    rows = collect("8h", "long", 2.5, 4.0) + collect("12h", "short", 1.5, 4.0)
    df = pd.DataFrame(rows); df["exit"] = pd.to_datetime(df.exit, utc=True)
    df["ym"] = df.exit.dt.to_period("M")
    M = df.groupby("ym")["R"].sum().sort_index()           # месячный net-R стратегии
    desc = btc_descriptors().reindex(M.index)
    desc["own_trail"] = M.shift(1).rolling(3).sum()        # собственная трейлинг-эквити (3 мес, известна)

    A(f"\n  база: {len(M)} мес, ΣR={M.sum():+.0f}, Sharpe={sharpe(M):.2f}, плюс-мес={100*(M>0).mean():.0f}%")
    A(f"  худшие 5 мес: " + ", ".join(f"{ym}:{r:+.0f}" for ym, r in M.nsmallest(5).items()))
    A(f"  лучшие 5 мес: " + ", ".join(f"{ym}:{r:+.0f}" for ym, r in M.nlargest(5).items()))

    A("\n  [A] ТЕРЦИЛИ месяцев по net-R -> средние дескрипторов (почему хорошо/плохо):")
    q1, q2 = M.quantile(1/3), M.quantile(2/3)
    grp = pd.cut(M, [-1e9, q1, q2, 1e9], labels=["ХУДШИЕ", "средн", "ЛУЧШИЕ"])
    cols = ["trend90", "volp", "volofvol", "dispersion", "own_trail"]
    A(f"    {'терциль':10}" + "".join(f"{c:>12}" for c in cols))
    for lab in ["ХУДШИЕ", "средн", "ЛУЧШИЕ"]:
        m = grp == lab
        A(f"    {lab:10}" + "".join(f"{desc[c][m.values].mean():>12.3f}" for c in cols))

    A("\n  [B] WALK-FORWARD ГЕЙТ по дескриптору (выкл в исторически-худшей половине, решение по прошлому):")
    A(f"    {'дескриптор':14}{'Sharpe':>8}{'ΣR':>7}{'пауз':>6}{'2023':>7}{'2024':>7}{'2025':>7}  (база Sh {sharpe(M):.2f} ΣR{M.sum():+.0f})")
    yrs = M.index.year if hasattr(M.index, "year") else M.index.to_timestamp().year
    yidx = M.index.to_timestamp()
    for c in cols:
        g, paused = wf_gate(M, desc[c])
        ys = pd.Series(g.values, index=yidx).groupby(yidx.year).sum()
        A(f"    {c:14}{sharpe(g):>8.2f}{g.sum():>+7.0f}{paused:>6}"
          + "".join(f"{ys.get(y, 0):>+7.0f}" for y in [2023, 2024, 2025]))
    A("\n  ВЕРДИКТ: гейт «живой» только если Sharpe ВЫШЕ базы И ΣR не обвалился И тянет 2023-24 вверх, БЕЗ обнуления.")
    A("  Кавеат: 2 плохих периода -> даже walk-forward почти невалидируем; доверять только если эффект крупный и согласованный.")
    o = "\n".join(out); (HERE / "rr_phases_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
