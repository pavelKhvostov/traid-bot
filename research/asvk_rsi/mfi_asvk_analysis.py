"""Анализ комбинации MFI×ASVK-полосы + рынок: 2-панель (цена / MFI+полосы) + forward-return событий.
События: вход/выход OS (MFI vs below), вход/выход OB (MFI vs above). fwd-return 6/12/24 бара vs дрейф периода.
BTC 4h с указанной даты. Запуск: venv/Scripts/python.exe research/asvk_rsi/mfi_asvk_analysis.py [TF] [START]
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "smc-lib"))
from indicators.rsi_asvk import adjusted_rsi  # noqa: E402

TF = sys.argv[1] if len(sys.argv) > 1 else "4h"
START = sys.argv[2] if len(sys.argv) > 2 else "2026-02-01"
SYM = "BTCUSDT"


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


def main():
    df = load(SYM, TF)
    res = adjusted_rsi(df.close.tolist())
    above = np.array([np.nan if x is None else x for x in res["above"]], float)
    below = np.array([np.nan if x is None else x for x in res["below"]], float)
    m = mfi(df)
    c = df.close.values
    n = len(c)
    idx = df.index
    mask = np.asarray(idx >= pd.Timestamp(START, tz="UTC"))

    in_os = m < below
    in_ob = m > above
    os_enter = in_os & ~np.r_[False, in_os[:-1]]
    os_exit = (~in_os) & np.r_[False, in_os[:-1]]
    ob_enter = in_ob & ~np.r_[False, in_ob[:-1]]
    ob_exit = (~in_ob) & np.r_[False, in_ob[:-1]]

    def fwd(i, k):
        return (c[i + k] / c[i] - 1) if i + k < n else np.nan

    KS = [6, 12, 24]
    print(f"=== MFI×ASVK анализ {SYM} {TF} c {START} (4h: 6/12/24 бара = 1/2/4 дня) ===")
    base = {k: np.nanmean([fwd(i, k) for i in np.where(mask)[0]]) for k in KS}
    print(f"дрейф периода (база) fwd: " + "  ".join(f"{k}б {base[k]*100:+.2f}%" for k in KS))
    print(f"{'событие':14}{'n':>5}" + "".join(f"{'fwd'+str(k):>10}" for k in KS) + "   (avg fwd-return после события)")
    rows = [("OS-вход", os_enter), ("OS-выход", os_exit), ("OB-вход", ob_enter), ("OB-выход", ob_exit)]
    ev_for_plot = {}
    for name, ev in rows:
        ii = np.where(ev & mask)[0]
        ev_for_plot[name] = ii
        line = f"{name:14}{len(ii):>5}"
        for k in KS:
            vals = [fwd(i, k) for i in ii if i + k < n]
            line += f"{(np.nanmean(vals)*100 if vals else float('nan')):>+9.2f}%"
        print(line)

    # --- 2-панель ---
    s = mask
    x = idx[s]; px = c[s]; mm = m[s]; ab = above[s]; bl = below[s]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(16, 9), sharex=True, gridspec_kw={"height_ratios": [2, 1.4]})
    a1.plot(x, px, color="#222", lw=1.2)
    # маркеры на цене: OS-выход (бычий разворот-кандидат) и OB-вход (медвежий)
    oxe = ev_for_plot["OS-выход"]; obe = ev_for_plot["OB-вход"]
    a1.scatter(idx[oxe], c[oxe], marker="^", s=60, color="#26a69a", zorder=5, label="OS-выход (MFI вышел из OS)")
    a1.scatter(idx[obe], c[obe], marker="v", s=60, color="#ef5350", zorder=5, label="OB-вход (MFI вошёл в OB)")
    a1.set_title(f"{SYM} {TF} цена + события MFI×ASVK (c {START})", fontsize=12)
    a1.legend(loc="upper right", fontsize=9); a1.grid(alpha=0.15)
    # нижняя панель
    a2.fill_between(x, ab, 100, color="#ef5350", alpha=0.06)
    a2.fill_between(x, 0, bl, color="#26a69a", alpha=0.06)
    a2.plot(x, ab, color="#ef5350", lw=1.1, ls="--", label="ASVK above")
    a2.plot(x, bl, color="#26a69a", lw=1.1, ls="--", label="ASVK below")
    a2.plot(x, mm, color="#2962ff", lw=1.3, label="MFI(14)")
    a2.axhline(50, color="#888", lw=0.5, ls=":")
    a2.set_ylim(0, 100); a2.legend(loc="upper left", fontsize=8); a2.grid(alpha=0.15)
    fig.autofmt_xdate(); fig.tight_layout()
    out = Path(__file__).resolve().parent / f"mfi_asvk_analysis_{TF}_from{START}.png"
    fig.savefig(out, dpi=110); plt.close(fig)
    print(f"PNG -> {out}")


if __name__ == "__main__":
    main()
