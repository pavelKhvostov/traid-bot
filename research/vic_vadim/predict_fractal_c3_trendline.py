"""C3 кандидат: ASVK Trend Line (Hull MA) поверх Core (mlt=45, LTF=16m maxV) на BTC.

Hull MA настройки (canon [[asvk-trend-line-hull]]): length=49 × mult=1.6 = 78
(swing-entry). Цвет: close > SHULL → GREEN, иначе RED, где SHULL = HULL[2].

Формы C3 (направление = что ожидаем):
  HH (SHORT-прогноз): RED (close < SHULL) — тренд вниз / разворот вниз виден
  LL (LONG-прогноз):  GREEN (close > SHULL) — тренд вверх

Проверка на LTF {1h, 2h, 4h, 6h, 1d}.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.asvk_trend_line.plot_asvk_trend_line import hma
from research.vic_vadim.optimize_mlt import (
    load_1m, compose_htf, find_ob_zones, find_fractals,
    zone_sweep_flags, fractal_sweep_flags, maxv_all_12h, HTF_LIST,
)

HULL_LEN = 78  # effective default (49 × 1.6)
C3_LTFS = [("1h", "60min"), ("2h", "120min"), ("4h", "240min"),
           ("6h", "360min"), ("1d", "1D")]


def compose_ltf(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum",
    }).dropna(subset=["close"])


def hull_color_at_12h(df_ltf: pd.DataFrame, close_times_12h: pd.DatetimeIndex) -> np.ndarray:
    """Возвращает (n_12h, 3): [hull, shull, color_is_green]
    на last closed LTF bar до close_time."""
    print(f"  computing HMA-{HULL_LEN}...", flush=True)
    hull = hma(df_ltf["close"], HULL_LEN)
    shull = hull.shift(2)
    close = df_ltf["close"]
    is_green = (close > shull).values  # numpy bool array

    idx_ltf = df_ltf.index
    tf_dur = (idx_ltf[1] - idx_ltf[0]) if len(idx_ltf) > 1 else pd.Timedelta("1h")
    close_times_ltf = idx_ltf + tf_dur

    out = np.full((len(close_times_12h), 3), np.nan)
    hull_arr = hull.values; shull_arr = shull.values
    for k, t in enumerate(close_times_12h):
        pos = close_times_ltf.searchsorted(t, side="right") - 1
        if pos < 0: continue
        out[k] = [hull_arr[pos], shull_arr[pos], 1.0 if is_green[pos] else 0.0]
    return out  # columns: hull, shull, is_green


def main() -> None:
    df_1m = load_1m()
    df_1m_naive = df_1m.copy(); df_1m_naive.index.name = None

    htf_dfs = {tf: compose_htf(df_1m, freq) for tf, freq in HTF_LIST}
    df_12h = htf_dfs["12h"]

    print("compute Core (mlt=45, LTF=16m)...")
    maxv = maxv_all_12h(df_1m_naive, df_12h, 16)
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy(); c = df_12h["close"].to_numpy()
    sw_s = np.zeros(len(df_12h), dtype=bool); sw_l = np.zeros(len(df_12h), dtype=bool)
    for i in range(1, len(df_12h)):
        if np.isnan(maxv[i-1]): continue
        if h[i] > maxv[i-1] and c[i] < maxv[i-1]: sw_s[i] = True
        if l[i] < maxv[i-1] and c[i] > maxv[i-1]: sw_l[i] = True

    all_ob, all_fract = [], []
    for tf, df_tf in htf_dfs.items():
        all_ob += find_ob_zones(df_tf)
        all_fract += find_fractals(df_tf)
    c1_fh = fractal_sweep_flags(df_12h, all_fract, "FH")
    c1_fl = fractal_sweep_flags(df_12h, all_fract, "FL")
    c1_obs = zone_sweep_flags(df_12h, all_ob, "SHORT")
    c1_obl = zone_sweep_flags(df_12h, all_ob, "LONG")

    hh_core = (c1_fh | c1_obs) & sw_s
    ll_core = (c1_fl | c1_obl) & sw_l

    close_times_12h = df_12h.index + pd.Timedelta(hours=12)

    hull_data: dict[str, np.ndarray] = {}
    for tf, freq in C3_LTFS:
        print(f"compute Hull on {tf}...", flush=True)
        df_ltf = compose_ltf(df_1m, freq).sort_index()
        hull_data[tf] = hull_color_at_12h(df_ltf, close_times_12h)

    n = len(df_12h); valid = np.arange(2, n - 2)
    hh = ((h[valid]>h[valid-2])&(h[valid]>h[valid-1])&(h[valid]>h[valid+1])&(h[valid]>h[valid+2]))
    ll = ((l[valid]<l[valid-2])&(l[valid]<l[valid-1])&(l[valid]<l[valid+1])&(l[valid]<l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    n_core_hh = int(hh_core[valid].sum()); n_core_ll = int(ll_core[valid].sum())
    print(f"\nbaseline P(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%")
    print(f"Core: HH n={n_core_hh}, prec={(hh & hh_core[valid]).sum()/max(1,n_core_hh)*100:.2f}%; "
          f"LL n={n_core_ll}, prec={(ll & ll_core[valid]).sum()/max(1,n_core_ll)*100:.2f}%\n")

    def report(label, target, cond, base, parent_n):
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        keep = n_c / parent_n if parent_n else 0
        print(f"  {label:<38} n={n_c:3d} hits={n_tc:3d} prec={prec*100:6.2f}% "
              f"lift=×{lift:.2f} keep={keep*100:5.1f}%")

    for tf, _ in C3_LTFS:
        ad = hull_data[tf]
        is_green = ad[:, 2] == 1.0
        is_red = ad[:, 2] == 0.0
        valid_mask = ~np.isnan(ad[:, 0]) & ~np.isnan(ad[:, 1])
        red_v = is_red & valid_mask
        grn_v = is_green & valid_mask

        print(f"=== Hull-{HULL_LEN} на LTF {tf} ===")
        # direct
        report(f"HH ∩ Hull RED ({tf})", hh, hh_core[valid] & red_v[valid], base_hh, n_core_hh)
        report(f"LL ∩ Hull GREEN ({tf})", ll, ll_core[valid] & grn_v[valid], base_ll, n_core_ll)
        # anti
        report(f"HH ∩ Hull GREEN ({tf}) [anti]", hh, hh_core[valid] & grn_v[valid], base_hh, n_core_hh)
        report(f"LL ∩ Hull RED ({tf}) [anti]", ll, ll_core[valid] & red_v[valid], base_ll, n_core_ll)
        print()


if __name__ == "__main__":
    main()
