"""TF-sweep ИНДИКАТОРОВ (MFI + ASVK above/below) на ФИКС-ТФ Магнитуды (trade: 8h long / 12h short).
Индикатор считаем на разных ind-TF {4h,6h,8h,12h,1d,3d}, мапим на trade-бары через as-of (БЕЗ утечки:
только ind-бары, закрытые к моменту close trade-бара). Reversal-лейбл/R Магнитуды (entry close, TP±3%, SL свой low/high).
Метрика: для OS (mfi<below) и OB (mfi>above) — reversal-rate, lift над base, net-R, cross-asset. Какой ind-TF лучший.

Запуск: venv/Scripts/python.exe research/asvk_rsi/tf_indicator_sweep.py
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
from rr_native import native  # noqa: E402

THR = 0.03
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TRADE_TF = {"long": "8h", "short": "12h"}
IND_TFS = ["4h", "6h", "8h", "12h", "1d", "3d"]
TF_HOURS = {"4h": 4, "6h": 6, "8h": 8, "12h": 12, "1d": 24, "3d": 72}


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


def ind_frame(sym, ind_tf):
    df = load(sym, ind_tf)
    ar = adjusted_rsi(df.close.tolist())
    above = np.array([np.nan if x is None else x for x in ar["above"]], float)
    below = np.array([np.nan if x is None else x for x in ar["below"]], float)
    m = mfi(df)
    avail = df.index + pd.Timedelta(hours=TF_HOURS[ind_tf])      # ind-бар известен только после закрытия
    return pd.DataFrame({"avail": avail, "mfi": m, "above": above, "below": below}).dropna().sort_values("avail")


def build(direction, ind_tf):
    ttf = TRADE_TF[direction]; rows = []
    for sym in SYMS:
        tdf = load(sym, ttf)
        y, R, risk = native(tdf, direction, 0.0010, 0.0010)
        base = pd.DataFrame({"topen": tdf.index, "y": y, "R": R, "risk": risk, "sym": sym})
        base = base[(base.y >= 0) & np.isfinite(base.risk)].copy()
        base["tclose"] = base["topen"] + pd.Timedelta(hours=TF_HOURS[ttf])
        ind = ind_frame(sym, ind_tf)
        merged = pd.merge_asof(base.sort_values("tclose"), ind, left_on="tclose", right_on="avail", direction="backward")
        merged = merged.dropna(subset=["mfi", "above", "below"])
        rows.append(merged)
    return pd.concat(rows, ignore_index=True)


def stats(P, mask):
    s = P[mask]
    if len(s) < 30:
        return None
    per = s.groupby("sym").apply(lambda g: (g.y > 0).mean(), include_groups=False)
    return dict(n=len(s), rate=(s.y > 0).mean(), netR=s.R.mean(),
                cross=int((per > P.y.mean()).sum()), per=per)


def main():
    out = ["="*80, " TF-SWEEP ИНДИКАТОРОВ (MFI+ASVK) на фикс-ТФ Магнитуды (trade 8h long / 12h short)", "="*80]
    for direction in ["long", "short"]:
        out.append(f"\n{'#'*64}\n## {direction.upper()} — trade {TRADE_TF[direction]} · индикатор на разных ТФ\n{'#'*64}")
        out.append(f"  {'ind-TF':>7}{'базовый':>9}  | OS (mfi<below): rate/lift/netR/cross | OB (mfi>above): rate/lift/netR/cross")
        for itf in IND_TFS:
            try:
                P = build(direction, itf)
            except Exception as e:
                out.append(f"  {itf:>7}  err {str(e)[:50]}"); continue
            base = P.y.mean()
            os_ = stats(P, P.mfi < P.below)
            ob = stats(P, P.mfi > P.above)
            def fmt(st):
                if st is None:
                    return "  —мало—"
                return f"{st['rate']:.3f}/{st['rate']/base:.2f}/{st['netR']:+.3f}/{st['cross']}/3"
            mark_os = " ★" if (os_ and os_["netR"] > 0 and os_["cross"] >= 2) else ""
            mark_ob = " ★" if (ob and ob["netR"] > 0 and ob["cross"] >= 2) else ""
            out.append(f"  {itf:>7}{base:>9.3f}  | OS {fmt(os_)}{mark_os}  | OB {fmt(ob)}{mark_ob}")
        out.append("  (★ = net-R>0 И cross-asset>=2/3 vs base; формат rate/lift/netR/cross)")
    o = "\n".join(out); (Path(__file__).resolve().parent / "tf_indicator_sweep_report.txt").write_text(o, encoding="utf-8")
    print(o)


if __name__ == "__main__":
    main()
