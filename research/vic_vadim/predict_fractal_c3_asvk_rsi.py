"""C3 кандидат: ASVK Custom RSI zone (OB/OS) на разных LTF (1h, 2h, 4h, 6h)
поверх Core (mlt=45, LTF=16m maxV).

Логика C3 (form A — ASVK-зона на момент close i):
  HH (SHORT): ema_3(last closed LTF bar до close i) > current_value_above
  LL (LONG):  ema_3(last closed LTF bar до close i) < current_value_below

Где ema_3 — adjusted_rsi и above/below — адаптивные уровни ASVK
(rolling 200 баров) — см. plot_asvk_rsi.py / [[asvk-custom-rsi]].

Применяется на BTC 12h Core stratу (mlt=45, LTF=16m).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Импорт ASVK RSI функций
from research.asvk_rsi.plot_asvk_rsi import adjusted_rsi, dynamic_levels
from research.vic_vadim.optimize_mlt import (
    load_1m, compose_htf, find_ob_zones, find_fractals,
    zone_sweep_flags, fractal_sweep_flags, maxv_all_12h, HTF_LIST,
)

C3_LTFS = [("1h", "60min"), ("2h", "120min"), ("4h", "240min"), ("6h", "360min")]


def compose_ltf(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum",
    }).dropna(subset=["close"])


def asvk_zone_at_12h(df_ltf: pd.DataFrame, close_times_12h: pd.DatetimeIndex):
    """Для каждого close-времени 12h-свечи вернуть (ema_3, above, below) на
    last closed LTF bar (т.е. бар, чей close ≤ close 12h-свечи).

    close_times_12h должна быть отсортирована."""
    close = df_ltf["close"]
    ema_3 = adjusted_rsi(close)
    above, below = dynamic_levels(ema_3)
    # LTF bar c open_time = t, close_time = t + tf_dur. last closed для
    # 12h-close_time T = последний LTF bar с (open_time + tf) ≤ T.
    idx_ltf = df_ltf.index
    tf_dur = (idx_ltf[1] - idx_ltf[0]) if len(idx_ltf) > 1 else pd.Timedelta("1h")
    close_times_ltf = idx_ltf + tf_dur  # closing times of LTF bars
    result = []
    for t in close_times_12h:
        pos = close_times_ltf.searchsorted(t, side="right") - 1
        if pos < 0:
            result.append((np.nan, np.nan, np.nan))
        else:
            result.append((float(ema_3.iloc[pos]), float(above.iloc[pos]), float(below.iloc[pos])))
    return np.array(result)  # shape (n_12h, 3): [ema_3, above, below]


def main() -> None:
    df_1m = load_1m()
    df_1m_naive = df_1m.copy(); df_1m_naive.index.name = None

    htf_dfs = {tf: compose_htf(df_1m, freq) for tf, freq in HTF_LIST}
    df_12h = htf_dfs["12h"]

    # Core (mlt=45 → LTF=16m for maxV)
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

    # close times 12h
    close_times_12h = df_12h.index + pd.Timedelta(hours=12)

    # ASVK на каждом LTF
    asvk_data: dict[str, np.ndarray] = {}
    for tf, freq in C3_LTFS:
        print(f"compute ASVK RSI on {tf}...", flush=True)
        df_ltf = compose_ltf(df_1m, freq).sort_index()
        asvk_data[tf] = asvk_zone_at_12h(df_ltf, close_times_12h)

    # target
    n = len(df_12h); valid = np.arange(2, n - 2)
    hh = ((h[valid]>h[valid-2])&(h[valid]>h[valid-1])&(h[valid]>h[valid+1])&(h[valid]>h[valid+2]))
    ll = ((l[valid]<l[valid-2])&(l[valid]<l[valid-1])&(l[valid]<l[valid+1])&(l[valid]<l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nbaseline P(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%\n")

    def report(label, target, cond, base, parent_n):
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        keep = n_c / parent_n if parent_n else float("nan")
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        print(f"  {label:<45} n={n_c:3d}  hits={n_tc:3d}  prec={prec*100:6.2f}%  "
              f"lift=×{lift:.2f}  keep={keep*100:5.1f}%  rec={rec*100:5.2f}%")

    n_core_hh = int(hh_core[valid].sum())
    n_core_ll = int(ll_core[valid].sum())
    print(f"=== Core (BTC, mlt=45) ===")
    print(f"  HH Core: n={n_core_hh}, hits={int((hh & hh_core[valid]).sum())}, "
          f"prec={(hh & hh_core[valid]).sum()/max(1,n_core_hh)*100:.2f}%")
    print(f"  LL Core: n={n_core_ll}, hits={int((ll & ll_core[valid]).sum())}, "
          f"prec={(ll & ll_core[valid]).sum()/max(1,n_core_ll)*100:.2f}%")
    print()

    for tf, _ in C3_LTFS:
        ad = asvk_data[tf]
        # ad — shape (n_12h, 3)
        ema_3 = ad[:, 0]; above = ad[:, 1]; below = ad[:, 2]
        zone_ob = (ema_3 > above) & ~np.isnan(ema_3) & ~np.isnan(above)
        zone_os = (ema_3 < below) & ~np.isnan(ema_3) & ~np.isnan(below)
        print(f"=== C3 = ASVK zone на LTF {tf} ===")
        # HH ∩ OB
        cond_hh = hh_core[valid] & zone_ob[valid]
        report(f"HH Core ∩ ASVK OB ({tf})", hh, cond_hh, base_hh, n_core_hh)
        # LL ∩ OS
        cond_ll = ll_core[valid] & zone_os[valid]
        report(f"LL Core ∩ ASVK OS ({tf})", ll, cond_ll, base_ll, n_core_ll)
        # обратные (для отрицательного контроля)
        report(f"HH Core ∩ ASVK OS ({tf}) [anti]", hh, hh_core[valid] & zone_os[valid], base_hh, n_core_hh)
        report(f"LL Core ∩ ASVK OB ({tf}) [anti]", ll, ll_core[valid] & zone_ob[valid], base_ll, n_core_ll)
        print()


if __name__ == "__main__":
    main()
