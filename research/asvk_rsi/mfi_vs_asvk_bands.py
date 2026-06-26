"""MFI(14) наложенный на адаптивные above/below из RSI-ASVK.
above/below — динамические OB/OS уровни ASVK (rolling-200), берём их как пороги для MFI вместо фикс. 80/20.
BTC 1d. Сохраняет PNG. Запуск: venv/Scripts/python.exe research/asvk_rsi/mfi_vs_asvk_bands.py [TF]
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

TF = sys.argv[1] if len(sys.argv) > 1 else "1d"
START = sys.argv[2] if len(sys.argv) > 2 else None   # напр. 2026-02-01; иначе последние PLOT_BARS
SYM = "BTCUSDT"
PLOT_BARS = 260


def load(sym, tf):
    d = pd.read_csv(ROOT / "data" / f"{sym}_{tf}.csv")
    tc = [c for c in d.columns if "time" in c.lower()][0]
    d[tc] = pd.to_datetime(d[tc], utc=True)
    return d.set_index(tc).sort_index()


def mfi(df, period=14):
    tp = (df.high + df.low + df.close) / 3.0
    rmf = tp * df.volume
    up = tp > tp.shift(1); dn = tp < tp.shift(1)
    pos = rmf.where(up, 0.0).rolling(period).sum()
    neg = rmf.where(dn, 0.0).rolling(period).sum()
    mfr = pos / neg.replace(0, np.nan)
    return (100 - 100 / (1 + mfr)).values


def main():
    df = load(SYM, TF)
    res = adjusted_rsi(df.close.tolist())
    above = np.array([np.nan if x is None else x for x in res["above"]], dtype=float)
    below = np.array([np.nan if x is None else x for x in res["below"]], dtype=float)
    m = mfi(df)

    if START:
        msk = df.index >= pd.Timestamp(START, tz="UTC")
        x = df.index[msk]; mm = m[msk]; ab = above[msk]; bl = below[msk]
        rng = f"с {START}"
    else:
        s = slice(-PLOT_BARS, None)
        x = df.index[s]; mm = m[s]; ab = above[s]; bl = below[s]
        rng = f"последние {PLOT_BARS} баров"

    fig, ax = plt.subplots(figsize=(16, 6))
    # зоны OB (MFI выше above) и OS (MFI ниже below)
    ax.fill_between(x, ab, 100, color="#ef5350", alpha=0.06)
    ax.fill_between(x, 0, bl, color="#26a69a", alpha=0.06)
    # адаптивные пороги ASVK
    ax.plot(x, ab, color="#ef5350", lw=1.3, ls="--", label="ASVK above (адапт. OB)")
    ax.plot(x, bl, color="#26a69a", lw=1.3, ls="--", label="ASVK below (адапт. OS)")
    ax.axhline(50, color="#888", lw=0.6, ls=":")
    # MFI
    ax.plot(x, mm, color="#2962ff", lw=1.6, label="MFI(14)")
    # точки пробоя
    ob = mm > ab; os_ = mm < bl
    ax.scatter(x[ob], mm[ob], s=18, color="#ef5350", zorder=5)
    ax.scatter(x[os_], mm[os_], s=18, color="#26a69a", zorder=5)

    ax.set_ylim(0, 100)
    ax.set_title(f"MFI(14) на адаптивных ASVK-порогах above/below — {SYM} {TF} ({rng})", fontsize=12)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.15)
    fig.autofmt_xdate()
    sfx = f"_{TF}" + (f"_from{START}" if START else "")
    out = Path(__file__).resolve().parent / f"mfi_vs_asvk_bands{sfx}.png"
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)
    # сводка пробоев
    nb = int(np.nansum(ob)); no = int(np.nansum(os_))
    print(f"{SYM} {TF}: баров на графике {len(x)}, MFI>above (OB) {nb}, MFI<below (OS) {no}")
    print(f"текущий: MFI={mm[-1]:.1f}  above={ab[-1]:.1f}  below={bl[-1]:.1f}  "
          f"-> {'OB(красная)' if mm[-1] > ab[-1] else 'OS(зелёная)' if mm[-1] < bl[-1] else 'нейтрально'}")
    print(f"PNG -> {out}")


if __name__ == "__main__":
    main()
