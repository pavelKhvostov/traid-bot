"""НЕТТО co-симуляция корзины — честный месячный P&L с РЕАЛИСТИЧНОЙ косто-моделью.

Эти стратегии входят ЛИМИТОМ (ждут касания entry = maker) и выходят TP-лимитом (maker) / SL-маркетом (taker).
Поэтому кост зависит от исхода:
  win  (TP):  entry maker + exit maker  -> WIN_RT
  loss (SL):  entry maker + exit taker+slip -> LOSS_RT
cost_R = RT(side) / (risk_pct/100); net_R = gross_R - cost_R - funding.
3 сценария исполнения: maker(лучший) / realistic / taker-pessim(all-market).

Сайзинг: equal-RISK ПО ЦЕПОЧКЕ (декорр-корзина) — в каждом месяце каждая цепочка = 1 риск-юнит = её средний
net_R/сделку за месяц; basket месячный R = СУММА по 5 цепочкам (frequency не доминирует). Доп: equal-per-trade
для сравнения (показывает перекос частотой). Метрики: R/мес, %плюс, худший, Sharpe, макс-DD. + выживание per-trade.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/cosim_net.py
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
HERE = Path(__file__).resolve().parent
FUND_8H = 0.0001
KEYS = {"A_irdrb": "A i-RDRB+FVG", "112": "1.1.2", "115": "1.1.5", "32": "3.2", "111": "1.1.1"}
# (win_RT, loss_RT) в долях
SCEN = {"maker(0.04/0.07)": (0.0004, 0.0007),
        "realistic(0.05/0.10)": (0.0005, 0.0010),
        "taker-pessim(0.10/0.14)": (0.0010, 0.0014)}


def load_all():
    fr = []
    for k, name in KEYS.items():
        p = HERE / f"trades_{k}.csv"
        if not p.exists():
            print(f"[MISS] {p.name}"); continue
        d = pd.read_csv(p); d.columns = [c.lower() for c in d.columns]; d["strat"] = name
        d["signal_time"] = pd.to_datetime(d["signal_time"], utc=True, errors="coerce")
        d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True, errors="coerce") if "exit_time" in d.columns else pd.NaT
        d = d.dropna(subset=["signal_time", "gross_r", "risk_pct"])
        d = d[d["risk_pct"] > 0.05]
        fr.append(d[["strat", "sym", "signal_time", "exit_time", "gross_r", "risk_pct"]])
    return pd.concat(fr, ignore_index=True)


def net_R(df, win_rt, loss_rt):
    rp = df["risk_pct"].values / 100.0
    rt = np.where(df["gross_r"].values > 0, win_rt, loss_rt)
    cost = rt / rp
    hold = (df["exit_time"] - df["signal_time"]).dt.total_seconds().values / 3600.0
    hold = np.where(np.isfinite(hold) & (hold > 0), hold, 24.0)
    fund = FUND_8H * (hold / 8.0) / rp
    return df["gross_r"].values - cost - fund


def metrics(monthly):
    m = np.asarray(monthly, float)
    if len(m) < 6:
        return dict(n=len(m), mean=np.nan, pos=np.nan, worst=np.nan, sh=np.nan, mdd=np.nan)
    cum = np.cumsum(m); mdd = (cum - np.maximum.accumulate(cum)).min()
    return dict(n=len(m), mean=m.mean(), pos=(m > 0).mean() * 100, worst=m.min(),
                sh=m.mean() / (m.std() + 1e-9), mdd=mdd)


def basket_monthly_eqstrat(df, col):
    """equal-risk по цепочке: в месяце каждая цепочка = mean(net/сделку); basket = сумма по цепочкам."""
    g = df.groupby([df["signal_time"].dt.to_period("M").astype(str), "strat"])[col].mean().reset_index()
    return g.groupby("signal_time")[col].sum()


def main():
    df = load_all()
    df["month"] = df["signal_time"].dt.to_period("M").astype(str)
    out = []; A = out.append
    A("НЕТТО CO-СИМ КОРЗИНЫ — реалистичная косто-модель (limit-entry: maker вход+TP, taker SL)")
    A(f"Цепочки: {', '.join(sorted(df.strat.unique()))}. Сделок {len(df)}. Funding {FUND_8H*100:.3f}%/8h.\n")

    # per-trade выживание по сценариям (sizing-независимо — главный честный сигнал)
    A("=== ВЫЖИВАНИЕ EDGE per-trade (net R/сделку по сценариям исполнения) ===")
    A(f"{'цепочка':16}{'n':>6}{'med_risk%':>10}{'gross':>8}" + "".join(f"{s.split('(')[0]:>12}" for s in SCEN))
    surv = {}
    for name in sorted(df.strat.unique()):
        s = df[df.strat == name]; row = f"{name:16}{len(s):>6}{s.risk_pct.median():>10.2f}{s.gross_r.mean():>+8.3f}"
        surv[name] = {}
        for sc, (w, l) in SCEN.items():
            nr = net_R(s, w, l).mean(); surv[name][sc] = nr; row += f"{nr:>+12.3f}"
        A(row)
    A("  (>0 = edge переживает косты; тугой стоп/тонкий edge -> отрицателен)")

    # КОРЗИНА: месячный net, equal-strategy сайзинг, по сценариям
    A("\n=== КОРЗИНА месячный P&L — EQUAL-RISK ПО ЦЕПОЧКЕ (декорр-корзина) ===")
    A(f"{'сценарий':24}{'R/мес':>8}{'%плюс':>8}{'худший':>9}{'Sharpe':>8}{'макс-DD':>9}")
    for sc, (w, l) in SCEN.items():
        df["nr"] = net_R(df, w, l)
        mm = metrics(basket_monthly_eqstrat(df, "nr").values)
        A(f"{sc:24}{mm['mean']:>+8.2f}{mm['pos']:>7.0f}%{mm['worst']:>+9.2f}{mm['sh']:>8.2f}{mm['mdd']:>+9.1f}")
    # gross ref
    mg = metrics(basket_monthly_eqstrat(df, "gross_r").values)
    A(f"{'gross (0 костов)':24}{mg['mean']:>+8.2f}{mg['pos']:>7.0f}%{mg['worst']:>+9.2f}{mg['sh']:>8.2f}{mg['mdd']:>+9.1f}")

    # сравнение: equal-per-trade (показывает перекос A-частотой)
    A("\n=== для сравнения: EQUAL-PER-TRADE (частота доминирует, A=51% сделок) ===")
    for sc, (w, l) in SCEN.items():
        df["nr"] = net_R(df, w, l)
        mm = metrics(df.groupby("month")["nr"].sum().values)
        A(f"{sc:24}{mm['mean']:>+8.2f}{mm['pos']:>7.0f}%{mm['worst']:>+9.2f}{mm['sh']:>8.2f}{mm['mdd']:>+9.1f}")

    # ИТОГ на realistic
    w, l = SCEN["realistic(0.05/0.10)"]; df["nr"] = net_R(df, w, l)
    mm = metrics(basket_monthly_eqstrat(df, "nr").values)
    A("\n=== ИТОГ (realistic, equal-risk-по-цепочке) ===")
    A(f"  корзина NET: R/мес {mm['mean']:+.2f}, Sharpe {mm['sh']:.2f}, %плюс {mm['pos']:.0f}, худший {mm['worst']:+.2f}, макс-DD {mm['mdd']:+.1f}")
    A(f"  при 1% риска на цепочку-юнит: ~{mm['mean']:.2f}%/мес NET")
    A(f"  gross был R/мес {mg['mean']:+.2f} -> кост-драг {mg['mean']-mm['mean']:+.2f}R/мес ({(mg['mean']-mm['mean'])/abs(mg['mean'])*100:.0f}% gross)")
    surviving = [n for n in surv if surv[n]["realistic(0.05/0.10)"] > 0.02]
    fragile = [n for n in surv if surv[n]["realistic(0.05/0.10)"] <= 0.02]
    A(f"  переживают realistic-косты: {', '.join(surviving)}")
    A(f"  ХРУПКИЕ (edge ~съеден): {', '.join(fragile)}")

    rep = HERE / "cosim_net_report.txt"; rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
