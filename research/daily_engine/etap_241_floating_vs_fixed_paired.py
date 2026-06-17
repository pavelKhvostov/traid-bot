"""etap_241 — Floating TP vs Fixed RR=2.2: ПАРНОЕ честное сравнение (дедуп, BTC 6.44y).

Сделки идентичны (один детект, один дедуп, один fill) — отличаются только выходы.
Значит сравнивать надо ПОПАРНО: ΔR = R_float − R_fixed на каждой сделке.

Метрики:
  - ΣR, WR, medR, R/tr — по обеим веткам
  - paired ΔR: mean/median, bootstrap 95% CI суммы ΔR (10k ресемплов)
  - equity: max drawdown (R), σ/сделку, t-стат парной разницы
  - разбор exit_reason floating: где он выигрывает/проигрывает у fixed
  - по годам

Запуск: venv/Scripts/python.exe research/daily_engine/etap_241_floating_vs_fixed_paired.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1_floating import (
    FLOATING_TP_CONFIG, build_score_series, check_swept,
    detect_signals_111, simulate_floating,
)

SYMBOL = "BTCUSDT"
RNG = np.random.RandomState(42)


def equity_stats(rs):
    eq = np.cumsum(rs)
    peak = np.maximum.accumulate(eq)
    mdd = float((peak - eq).max())
    return mdd, float(np.std(rs))


def main():
    df_1d = load_df(SYMBOL, "1d"); df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h"); df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m"); df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")

    signals = detect_signals_111(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    swept = [s for s in signals if check_swept(s, df_1h, df_2h)]
    seen, dedup = set(), []
    for s in swept:
        key = (pd.Timestamp(s["signal_time"]).isoformat(), s["direction"], tuple(s["fvg_zone"]))
        if key in seen: continue
        seen.add(key); dedup.append(s)
    print(f"уникальных SWEPT-сигналов: {len(dedup)}")

    score_long, score_short = build_score_series(df_1h)
    cfg = FLOATING_TP_CONFIG[SYMBOL]

    rows = []
    for s in dedup:
        rf = simulate_floating(s, df_1m, df_1h, score_long, score_short,
                               R_cap=cfg["R_cap"], threshold=cfg["threshold"], confirm=cfg["confirm"])
        rb = simulate_floating(s, df_1m, df_1h, score_long, score_short,
                               R_cap=2.2, threshold=-1e9, confirm=10**6, max_hold_days=3650)
        if rf is None or rb is None: continue
        if rf.outcome not in ("win", "loss", "flat") or rb.outcome not in ("win", "loss", "flat"):
            continue
        rows.append(dict(signal_time=pd.Timestamp(s["signal_time"]), direction=s["direction"],
                         Rf=rf.R, Rb=rb.R, exf=rf.exit_reason, exb=rb.exit_reason,
                         year=pd.Timestamp(s["signal_time"]).year))
    d = pd.DataFrame(rows).sort_values("signal_time").reset_index(drop=True)
    print(f"парных закрытых сделок: {len(d)}")

    # ---------- сводка ----------
    print("\n" + "=" * 76)
    print("ПАРНОЕ СРАВНЕНИЕ (одни сделки, разные выходы)")
    print("=" * 76)
    for col, name in [("Rf", "FLOATING"), ("Rb", "FIXED RR2.2")]:
        rs = d[col].values
        mdd, sd = equity_stats(rs)
        wr = (rs > 0).mean() * 100
        print(f"  {name:<12} ΣR={rs.sum():>+7.1f}  WR={wr:>5.1f}%  medR={np.median(rs):>+5.2f}  "
              f"R/tr={rs.mean():>+5.2f}  σ={sd:.2f}  maxDD={mdd:.1f}R  ΣR/maxDD={rs.sum()/mdd:.2f}")

    dr = (d.Rf - d.Rb).values
    print(f"\n  ΔR (float − fixed): mean {dr.mean():+.3f}  median {np.median(dr):+.3f}  "
          f"сделок с Δ>0: {(dr>0).mean()*100:.0f}%  Δ<0: {(dr<0).mean()*100:.0f}%  Δ=0: {(dr==0).mean()*100:.0f}%")
    # t-стат парной разницы
    t = dr.mean() / (dr.std(ddof=1) / np.sqrt(len(dr)))
    print(f"  paired t-stat: {t:.2f}")
    # bootstrap CI для ΣΔR
    sums = [dr[RNG.randint(0, len(dr), len(dr))].sum() for _ in range(10000)]
    lo, hi = np.percentile(sums, [2.5, 97.5])
    print(f"  bootstrap 95% CI для ΣΔR: [{lo:+.1f}R … {hi:+.1f}R]  (точка: {dr.sum():+.1f}R)")

    # ---------- по годам ----------
    print("\n  по годам (ΣR):")
    for y, g in d.groupby("year"):
        print(f"    {y}: float {g.Rf.sum():>+6.1f} | fixed {g.Rb.sum():>+6.1f} | Δ {g.Rf.sum()-g.Rb.sum():>+6.1f}  (n={len(g)})")

    # ---------- механизм: exit_reason floating ----------
    print("\n  механизм (exit_reason floating, ΔR против fixed на тех же сделках):")
    for ex, g in d.groupby("exf"):
        print(f"    {ex:<12} n={len(g):>3}  ΣRf={g.Rf.sum():>+7.1f}  ΣRb={g.Rb.sum():>+7.1f}  Δ={g.Rf.sum()-g.Rb.sum():>+7.1f}")

    out = HERE / "output" / "etap_241_paired.csv"
    d.to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
