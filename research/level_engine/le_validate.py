"""le_validate — ЧЕСТНЫЙ тест: предсказывает ли сила уровня удержание vs пробой?

Дизайн (overfit/lookahead register):
  - Каждая РЕАКЦИЯ уровня = тест. y=1 если REJECT (удержал), y=0 если BREAK (пробит).
    FLIP пропускаем (двусмысленно). НИКАКОГО survivorship: тестируем ВСЕ реакции,
    включая пробои (они и есть негативы).
  - Фича = strength_raw, посчитанная belief'ом СТРОГО ДО теста (interactions
    t_resolved < I.t_touch; members form_time <= I.t_touch). Причинно по построению.
  - Метрики: AUC(strength_raw -> y) общий + по годам; hold-rate по бакетам силы.
  - НЕТ прокс-гейта (window_usd=inf): популяция = все протестированные уровни.

Это БАЗОВЫЙ прогон (BTC). Density-matched permutation-null, ATR-режим бакеты,
кросс-ассет ETH/SOL и абляции — отдельной адверс-фазой (workflow).

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/level_engine/le_validate.py BTCUSDT
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import le_zones as LZ
import le_cluster as LC
import le_interact as LI
import le_belief as LB
from data_manager import load_df

try:
    from sklearn.metrics import roc_auc_score
except Exception:
    roc_auc_score = None


def _atr1d(base, T):
    d1 = base[base.index <= T].resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pc = d1["close"].shift(1)
    tr = pd.concat([d1.high - d1.low, (d1.high - pc).abs(), (d1.low - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(14).mean().iloc[-1])


def collect_tests(symbol: str, start="2020-06-01") -> pd.DataFrame:
    df = load_df(symbol, "1h")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    T_end = df.index[-1]
    price = float(df["close"].iloc[-1])
    atr1d = _atr1d(df, T_end)
    atr_d = LI.daily_atr(df)
    # популяция уровней: БЕЗ прокс-гейта (no survivorship)
    raws = LZ.build_raw_zones(df, T_end, price=price, window_usd=float("inf"), atr_d=atr_d)
    levels = LC.cluster(raws, price, atr1d)
    daily_hl = df.resample("1D").agg({"high": "max", "low": "min"}).dropna()
    import le_engine as LE
    flow = LE._load_flow(symbol)   # order-flow (volume, signed delta) для absorption-фичи
    start_ts = pd.Timestamp(start, tz="UTC")
    rows = []
    for L in levels:
        t0 = min(pd.Timestamp(m.form_time) for m in L.members)
        inter = sorted(LI.replay_interactions(L.bottom, L.top, t0, df, atr_d),
                       key=lambda x: x.t_touch)
        for I in inter:
            if I.cls == "FLIP":
                continue
            Tt = pd.Timestamp(I.t_touch)
            if Tt < start_ts:
                continue
            prior = [J for J in inter if pd.Timestamp(J.t_resolved) < Tt]
            c_at = float(df["close"].asof(Tt))                  # цена на момент теста
            bel = LB.belief(L.members, prior, Tt, df1h=df, atr_d=atr_d,
                            price=c_at, level=L, daily_hl=daily_hl, flow=flow)
            if bel is None:
                continue
            s10, raw, conf = LB.strength10(bel)
            dist_rel = abs(L.center - c_at) / c_at if c_at else float("nan")
            atr_rel = I.sigma / c_at if c_at else float("nan")  # волатильность-регим
            rows.append(dict(sym=symbol, t=Tt, year=Tt.year, y=1 if I.cls == "REJECT" else 0,
                             raw=raw, s10=s10, conf=conf, n_prior=len(prior),
                             sumw=bel["sumw"], has_liq=int(bel["has_liquidity"]),
                             has_mag=int(bel["has_magnet"]),
                             dist_rel=dist_rel, atr_rel=atr_rel,
                             absorp_effort=bel["absorp_effort"], absorp_delta=bel["absorp_delta"],
                             role=bel["role"]))
    return pd.DataFrame(rows)


def _auc(y, x):
    y = np.asarray(y); x = np.asarray(x)
    if len(set(y)) < 2:
        return float("nan")
    if roc_auc_score is not None:
        return float(roc_auc_score(y, x))
    # ранговый AUC fallback
    order = np.argsort(x); ranks = np.empty(len(x)); ranks[order] = np.arange(1, len(x) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def report(df: pd.DataFrame):
    n = len(df); base = df.y.mean()
    print(f"\n{'='*64}\n {df.sym.iloc[0]} — сила -> удержание/пробой (тестов {n}, base hold {base:.1%})\n{'='*64}")
    print(f"  AUC(strength_raw): {_auc(df.y, df.raw):.3f}   (0.50=монетка)")
    print(f"  AUC(confluence sumw): {_auc(df.y, df.sumw):.3f}   (контроль: конфлюэнс=dwell?)")
    print(f"  AUC(has_liquidity): {_auc(df.y, df.has_liq):.3f}")
    print("\n  hold-rate по силе:")
    for lo, hi in [(1, 3), (4, 7), (8, 10)]:
        s = df[(df.s10 >= lo) & (df.s10 <= hi)]
        if len(s):
            print(f"   сила {lo}-{hi}: n={len(s):>5} hold={s.y.mean():.1%}")
    print("\n  по годам (AUC strength_raw, нужно стабильно >0.5 и 0 инверсий):")
    inv = 0
    for yr, g in df.groupby("year"):
        if len(g) < 30:
            continue
        a = _auc(g.y, g.raw)
        hi = g[g.s10 >= 8].y.mean() if len(g[g.s10 >= 8]) else float("nan")
        lo = g[g.s10 <= 3].y.mean() if len(g[g.s10 <= 3]) else float("nan")
        bad = (hi == hi and lo == lo and hi < lo)
        inv += int(bad)
        print(f"   {yr}: n={len(g):>5} AUC={a:.3f} hold(8-10)={hi:.2f} hold(1-3)={lo:.2f}{'  <-ИНВЕРСИЯ' if bad else ''}")
    print(f"\n  инверсий по годам: {inv}  ->  {'KILL предиктивного слоя' if inv>0 or _auc(df.y,df.raw)<0.55 else 'кандидат, нужен null+cross-asset'}")


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    df = collect_tests(sym)
    if df.empty:
        print("нет тестов"); return
    report(df)
    out = Path(__file__).resolve().parent / f"_val_{sym}.csv"
    df.to_csv(out, index=False)
    print(f"\nsaved {out.name} ({len(df)} rows)")


if __name__ == "__main__":
    main()
