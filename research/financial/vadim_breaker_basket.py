"""HTF-breaker -> член корзины? OOS + декорреляция vs ядро + вставка в нетто-корзину.

(1) breaker (6h+8h, SL0.5/RR3 — favorable конфиг, помечаю честно) -> месячный нетто; раскол OOS 2020-23 / 2024-26.
(2) ядро 1.1.1/1.1.2/1.1.5 из trades_*.csv (их оптимальный RR) -> месячный нетто; корреляция месячных серий.
(3) корзина {ядро} vs {ядро+breaker} equal-strategy-weight -> Sharpe/просадка вверх или вниз?

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_breaker_basket.py
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
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "smc-lib"))
from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob  # noqa: E402
from elements.breaker_block.code import detect_breaker  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
WIN_RT, LOSS_RT = 0.0005, 0.0010
FUND_8H = 0.0001
SL_ATR, RR = 0.5, 3.0   # favorable breaker config (honest flag)


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def atr_tf(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=3).mean().values


def breaker_trades():
    rows = []
    for s in SYMBOLS:
        d1 = load_1m(s)
        for tf in ("6h", "8h"):
            dtf = rs(d1, tf); atr = atr_tf(dtf)
            o, h, lo, c = (dtf[k].to_numpy() for k in ("open", "high", "low", "close"))
            t = dtf.index.view("int64") // 1_000_000
            cnd = [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i])) for i in range(len(dtf))]
            ts = dtf.index; n = len(cnd)
            for i in range(1, n - 1):
                ob = detect_ob(cnd[i - 1], cnd[i])
                if ob is None:
                    continue
                br = detect_breaker(ob, cnd[i + 1:])
                if br is None:
                    continue
                arm = i + 1 + br.activated_at_idx
                if arm >= n or not np.isfinite(atr[arm]) or atr[arm] <= 0:
                    continue
                z_lo, z_hi = br.initial_zone
                if z_hi <= z_lo:
                    continue
                d = -1 if br.direction == "bullish" else 1; e = 0.5 * (z_lo + z_hi); a = float(atr[arm])
                f = None
                for j in range(arm + 1, min(arm + 81, n)):
                    if lo[j] <= e <= h[j]:
                        f = j; break
                if f is None or f + 1 >= n:
                    continue
                end = min(f + 61, n)
                if d == 1:
                    sl = e - SL_ATR * a; tp = e + SL_ATR * a * RR
                    sh = np.nonzero(lo[f + 1:end] <= sl)[0]; th = np.nonzero(h[f + 1:end] >= tp)[0]
                else:
                    sl = e + SL_ATR * a; tp = e - SL_ATR * a * RR
                    sh = np.nonzero(h[f + 1:end] >= sl)[0]; th = np.nonzero(lo[f + 1:end] <= tp)[0]
                si = sh[0] if sh.size else 10**9; ti = th[0] if th.size else 10**9
                if si == 10**9 and ti == 10**9:
                    continue
                win = ti < si; rp = SL_ATR * a / e * 100
                net = (RR if win else -1.0) - (WIN_RT if win else LOSS_RT) / (rp / 100)
                rows.append({"net": net, "month": ts[f].strftime("%Y-%m"), "year": ts[f].year})
    return pd.DataFrame(rows)


def core_trades(key, rr):
    p = HERE / f"trades_{key}.csv"
    d = pd.read_csv(p); d.columns = [c.lower() for c in d.columns]
    d["signal_time"] = pd.to_datetime(d["signal_time"], utc=True, errors="coerce")
    et = pd.to_datetime(d["exit_time"], utc=True, errors="coerce") if "exit_time" in d.columns else pd.NaT
    rp = d["risk_pct"].values / 100.0
    rt = np.where(d["gross_r"].values > 0, WIN_RT, LOSS_RT)
    hold = (et - d["signal_time"]).dt.total_seconds().values / 3600.0
    hold = np.where(np.isfinite(hold) & (hold > 0), hold, 24.0)
    net = d["gross_r"].values - rt / rp - FUND_8H * (hold / 8) / rp
    return pd.DataFrame({"net": net, "month": d["signal_time"].dt.strftime("%Y-%m"), "year": d["signal_time"].dt.year})


def monthly_mean(df):
    return df.groupby("month")["net"].mean()


def mets(series):
    m = series.values
    cum = np.cumsum(m); mdd = (cum - np.maximum.accumulate(cum)).min()
    return f"R/мес {m.mean():+.3f} | Sharpe {m.mean()/(m.std()+1e-9):.2f} | %плюс {(m>0).mean()*100:.0f} | худший {m.min():+.2f} | maxDD {mdd:+.2f} | мес {len(m)}"


def main():
    out = []; A = out.append
    bt = breaker_trades()
    A(f"HTF-breaker 6h+8h SL{SL_ATR}/RR{RR} (favorable конфиг). Сделок {len(bt)}.\n")

    # (1) OOS split
    A("=== (1) WALK-FORWARD OOS (breaker) ===")
    for lbl, sub in [("2020-2023 (in-sample)", bt[bt.year <= 2023]), ("2024-2026 (OOS)", bt[bt.year >= 2024])]:
        mm = monthly_mean(sub)
        A(f"  {lbl:24}: {mets(mm)}")
    A("  -> edge держится OOS, если 2024-26 Sharpe>0 и %плюс>50.")

    # (2) core series + correlation
    A("\n=== (2) ДЕКОРРЕЛЯЦИЯ месячных серий (mean-net/сделку) ===")
    core = {"1.1.1": core_trades("111", 1.5), "1.1.2": core_trades("112", 2.2), "1.1.5": core_trades("115", 3.0)}
    ser = {k: monthly_mean(v) for k, v in core.items()}
    ser["breaker"] = monthly_mean(bt)
    allm = pd.DataFrame(ser).dropna(how="all")
    corr = allm.corr()
    A("  корреляция breaker vs:")
    for k in ["1.1.1", "1.1.2", "1.1.5"]:
        A(f"    {k}: {corr.loc['breaker', k]:+.2f}")
    A(f"  средняя |corr| breaker-ядро: {np.nanmean([abs(corr.loc['breaker',k]) for k in ['1.1.1','1.1.2','1.1.5']]):.2f} (низкая=хороший диверсификатор)")

    # (3) basket sharpe core vs core+breaker (equal-strategy-weight = sum mean-net per month)
    A("\n=== (3) КОРЗИНА: ядро vs ядро+breaker (equal-strategy-weight) ===")
    def basket(keys):
        sub = allm[keys]
        # equal-weight: сумма mean-net по присутствующим цепочкам в месяце
        return sub.sum(axis=1, min_count=1).dropna()
    b_core = basket(["1.1.1", "1.1.2", "1.1.5"])
    b_all = basket(["1.1.1", "1.1.2", "1.1.5", "breaker"])
    A(f"  ядро (3):        {mets(b_core)}")
    A(f"  ядро+breaker (4):{mets(b_all)}")
    sh_c = b_core.mean() / (b_core.std() + 1e-9); sh_a = b_all.mean() / (b_all.std() + 1e-9)
    A(f"\n  Sharpe {sh_c:.2f} -> {sh_a:.2f} ({'ВВЕРХ — breaker диверсифицирует' if sh_a > sh_c + 0.02 else 'не помогает/вниз'})")

    A("\n=== ВЕРДИКТ ===")
    oos = monthly_mean(bt[bt.year >= 2024])
    oos_ok = oos.mean() > 0 and (oos.values > 0).mean() > 0.5
    A(f"  OOS 2024-26: {'держится' if oos_ok else 'НЕ держится'}; "
      f"декорр средн|corr| {np.nanmean([abs(corr.loc['breaker',k]) for k in ['1.1.1','1.1.2','1.1.5']]):.2f}; "
      f"Sharpe корзины {sh_c:.2f}->{sh_a:.2f}.")
    if oos_ok and sh_a > sh_c + 0.02:
        A("  -> HTF-breaker = РЕАЛЬНЫЙ член корзины (OOS держится + диверсифицирует + Sharpe растёт). Кавеат: favorable конфиг SL0.5/RR3.")
    else:
        A("  -> лид НЕ конвертируется в твёрдого члена корзины при этих критериях; см. что отвалилось.")
    o = "\n".join(out); (HERE / "vadim_breaker_basket_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
