"""ГЛУБОКИЙ анализ связки MFI×ASVK: сложные взаимодействия (динамика/кроссы/дивергенции/сжатие/развороты-из-глубины),
индикатор-ТФ 1h..12h, trade фикс Магнитуды 8h(long)/12h(short). As-of маппинг (без утечки). Метрика: net-R + cross-asset + lift.
Правила, без CatBoost. Запуск: venv/Scripts/python.exe research/asvk_rsi/tf_complex_sweep.py
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
IND_TFS = ["1h", "2h", "3h", "4h", "6h", "8h", "12h"]
TF_HOURS = {"1h": 1, "2h": 2, "3h": 3, "4h": 4, "6h": 6, "8h": 8, "12h": 12}
L = 10  # lookback для дивергенции


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


def ind_features(sym, itf):
    df = load(sym, itf)
    ar = adjusted_rsi(df.close.tolist())
    above = pd.Series([np.nan if x is None else x for x in ar["above"]], index=df.index)
    below = pd.Series([np.nan if x is None else x for x in ar["below"]], index=df.index)
    m = pd.Series(mfi(df), index=df.index)
    c = df.close
    bw = above - below
    pos = (m - below) / (bw + 1e-9)
    F = pd.DataFrame(index=df.index)
    F["mfi"] = m; F["above"] = above; F["below"] = below; F["bw"] = bw; F["pos"] = pos
    F["mfi_sl"] = m.diff()
    F["pos_sl"] = pos.diff()
    F["pos_prev"] = pos.shift(1)
    F["os"] = (m < below); F["os_prev"] = F["os"].shift(1)
    F["ob"] = (m > above); F["ob_prev"] = F["ob"].shift(1)
    F["d_os"] = m - below; F["d_ob"] = m - above
    F["bw_med"] = bw.rolling(50).median()
    F["c"] = c; F["c_L"] = c.shift(L); F["mfi_L"] = m.shift(L)
    F["avail"] = df.index + pd.Timedelta(hours=TF_HOURS[itf])
    return F.dropna(subset=["mfi", "above", "below"])


def conditions(P, direction):
    """возвращает dict имя->boolean Series на P (after as-of). Сложные взаимодействия."""
    mfi = P["mfi"]; pos = P["pos"]; sl = P["mfi_sl"]; psl = P["pos_sl"]
    if direction == "long":
        return {
            "spring(OS-exit+rise)": P["os_prev"].astype(bool) & (~P["os"].astype(bool)) & (sl > 0),
            "mom-OB(ob+rise)": P["ob"].astype(bool) & (sl > 0),
            "div-bull": (mfi < 50) & (P["c"] < P["c_L"]) & (mfi > P["mfi_L"]),
            "squeeze-up": (P["bw"] < P["bw_med"]) & (pos > 0.5) & (P["pos_prev"] <= 0.5),
            "deepOS-turn": (P["d_os"] < -3) & (sl > 0),
            "pos-mom(>0.5,+)": (pos > 0.5) & (psl > 0),
        }
    else:
        return {
            "spring(OB-exit+fall)": P["ob_prev"].astype(bool) & (~P["ob"].astype(bool)) & (sl < 0),
            "mom-OS(os+fall)": P["os"].astype(bool) & (sl < 0),
            "div-bear": (mfi > 50) & (P["c"] > P["c_L"]) & (mfi < P["mfi_L"]),
            "squeeze-dn": (P["bw"] < P["bw_med"]) & (pos < 0.5) & (P["pos_prev"] >= 0.5),
            "deepOB-turn": (P["d_ob"] > 3) & (sl < 0),
            "pos-mom(<0.5,-)": (pos < 0.5) & (psl < 0),
        }


def build(direction, itf):
    ttf = TRADE_TF[direction]; rows = []
    for sym in SYMS:
        tdf = load(sym, ttf)
        y, R, risk = native(tdf, direction, 0.0010, 0.0010)
        base = pd.DataFrame({"topen": tdf.index, "y": y, "R": R, "sym": sym})
        base = base[base.y >= 0].copy()
        base["tclose"] = base["topen"] + pd.Timedelta(hours=TF_HOURS[ttf])
        F = ind_features(sym, itf).sort_values("avail")
        merged = pd.merge_asof(base.sort_values("tclose"), F, left_on="tclose", right_on="avail", direction="backward")
        rows.append(merged.dropna(subset=["mfi"]))
    return pd.concat(rows, ignore_index=True)


def main():
    out = ["="*92, " ГЛУБОКАЯ связка MFI×ASVK — сложные взаимодействия × ind-ТФ 1h..12h (trade 8h long/12h short)", "="*92]
    for direction in ["long", "short"]:
        out.append(f"\n{'#'*70}\n## {direction.upper()} (trade {TRADE_TF[direction]}) — net-R по (условие × ind-ТФ), ★=net-R>0 & cross≥2/3\n{'#'*70}")
        # собрать P для всех tf
        Ps = {}
        for itf in IND_TFS:
            try:
                Ps[itf] = build(direction, itf)
            except Exception as e:
                print(f"{direction} {itf}: {e!r}")
        cond_names = list(conditions(next(iter(Ps.values())), direction).keys())
        hdr = f"  {'условие':22}" + "".join(f"{t:>9}" for t in IND_TFS)
        out.append(hdr)
        best = None
        for cn in cond_names:
            line = f"  {cn:22}"
            for itf in IND_TFS:
                P = Ps.get(itf)
                if P is None:
                    line += f"{'—':>9}"; continue
                base = P.y.mean()
                mask = conditions(P, direction)[cn]
                s = P[mask.fillna(False).values]
                if len(s) < 30:
                    line += f"{'·':>9}"; continue
                netR = s.R.mean()
                per = s.groupby("sym")["R"].mean()
                cross = int((per > 0).sum())
                good = netR > 0 and cross >= 2
                cell = f"{netR:+.2f}/{cross}" + ("★" if good else "")
                line += f"{cell:>9}"
                if good and (best is None or netR > best[0]):
                    best = (netR, cn, itf, cross, len(s))
            out.append(line)
        if best:
            out.append(f"  >>> ЛУЧШЕЕ {direction}: «{best[1]}» на {best[2]} — net-R={best[0]:+.3f} cross{best[3]}/3 n={best[4]}")
        else:
            out.append(f"  >>> {direction}: ни одной ячейки net-R>0 & cross≥2/3")
        out.append("  (ячейка = net-R/cross; · = мало сделок)")
    o = "\n".join(out); (Path(__file__).resolve().parent / "tf_complex_sweep_report.txt").write_text(o, encoding="utf-8")
    print(o)


if __name__ == "__main__":
    main()
