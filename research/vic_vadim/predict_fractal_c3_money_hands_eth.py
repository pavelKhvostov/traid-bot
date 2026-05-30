"""C3 кандидат: Money Hands ASVK (bw2 + SMA-state machine + MF) на LTF
{1h, 2h, 4h, 6h} поверх Core (mlt=45, LTF=16m maxV) для BTC.

Формы проверки:
  A1 (узкая):     HH=🔴 (bw2<0 AND bw2<=SMA14), LL=🟢 (bw2>0 AND bw2>=SMA14)
  A2 (широкая):   HH=bw2<SMA, LL=bw2>SMA
  A3 (затухание): HH=⚪after🟢 (bw2>0 AND bw2<SMA), LL=⚪after🔴 (bw2<0 AND bw2>SMA)
  B (extremum):   HH=bw2≥+60, LL=bw2≤-60
  C (MF знак):    HH=MF<0, LL=MF>0
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.money_hands.plot_money_hands import (
    wavetrend_blueWaves, sma, heikin_ashi, money_flow,
)
from research.vic_vadim.optimize_mlt_eth import (
    load_1m, compose_htf, find_ob_zones, find_fractals,
    zone_sweep_flags, fractal_sweep_flags, maxv_all_12h, HTF_LIST,
)

C3_LTFS = [("1h", "60min"), ("2h", "120min"), ("4h", "240min"), ("6h", "360min")]
BW2_SMA_LEN = 14


def compose_ltf(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum",
    }).dropna(subset=["close"])


def mh_signals_at_12h(df_ltf: pd.DataFrame, close_times_12h: pd.DatetimeIndex):
    """Возвращает массив (n_12h, 5): [bw2, sma14, mf, ha?dummy, n/a]
    на last closed LTF bar до каждого close_time_12h."""
    hlc3 = (df_ltf["high"] + df_ltf["low"] + df_ltf["close"]) / 3
    _, bw2, _ = wavetrend_blueWaves(hlc3)
    bw2_sma = sma(bw2, BW2_SMA_LEN)

    ha_o, ha_h, ha_l, ha_c = heikin_ashi(df_ltf["open"], df_ltf["high"],
                                          df_ltf["low"], df_ltf["close"])
    mf = money_flow(ha_o, ha_h, ha_l, ha_c)

    idx_ltf = df_ltf.index
    tf_dur = (idx_ltf[1] - idx_ltf[0]) if len(idx_ltf) > 1 else pd.Timedelta("1h")
    close_times_ltf = idx_ltf + tf_dur

    out = np.full((len(close_times_12h), 3), np.nan)
    bw2_arr = bw2.values; sma_arr = bw2_sma.values; mf_arr = mf.values
    for k, t in enumerate(close_times_12h):
        pos = close_times_ltf.searchsorted(t, side="right") - 1
        if pos < 0: continue
        out[k] = [bw2_arr[pos], sma_arr[pos], mf_arr[pos]]
    return out  # columns: bw2, sma14, mf


def main() -> None:
    df_1m = load_1m()
    df_1m_naive = df_1m.copy(); df_1m_naive.index.name = None

    htf_dfs = {tf: compose_htf(df_1m, freq) for tf, freq in HTF_LIST}
    df_12h = htf_dfs["12h"]

    # Core
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

    mh_data: dict[str, np.ndarray] = {}
    for tf, freq in C3_LTFS:
        print(f"compute MH on {tf}...", flush=True)
        df_ltf = compose_ltf(df_1m, freq).sort_index()
        mh_data[tf] = mh_signals_at_12h(df_ltf, close_times_12h)

    # target
    n = len(df_12h); valid = np.arange(2, n - 2)
    hh = ((h[valid]>h[valid-2])&(h[valid]>h[valid-1])&(h[valid]>h[valid+1])&(h[valid]>h[valid+2]))
    ll = ((l[valid]<l[valid-2])&(l[valid]<l[valid-1])&(l[valid]<l[valid+1])&(l[valid]<l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nbaseline P(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%")
    n_core_hh = int(hh_core[valid].sum()); n_core_ll = int(ll_core[valid].sum())
    print(f"Core: HH n={n_core_hh}, hits={int((hh & hh_core[valid]).sum())} "
          f"({(hh & hh_core[valid]).sum()/max(1,n_core_hh)*100:.2f}%); "
          f"LL n={n_core_ll}, hits={int((ll & ll_core[valid]).sum())} "
          f"({(ll & ll_core[valid]).sum()/max(1,n_core_ll)*100:.2f}%)\n")

    def report(label, target, cond, base, parent_n):
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        keep = n_c / parent_n if parent_n else 0
        print(f"  {label:<32} n={n_c:3d} hits={n_tc:3d} prec={prec*100:6.2f}% "
              f"lift=×{lift:.2f} keep={keep*100:5.1f}%")

    for tf, _ in C3_LTFS:
        ad = mh_data[tf]; bw2 = ad[:,0]; smav = ad[:,1]; mf = ad[:,2]
        valid_mh = ~np.isnan(bw2) & ~np.isnan(smav)
        valid_mf = ~np.isnan(mf)

        # формы
        # A1 (узкая)
        red = (bw2 < 0) & (bw2 <= smav) & valid_mh
        grn = (bw2 > 0) & (bw2 >= smav) & valid_mh
        # A2 (широкая)
        bw_below_sma = (bw2 < smav) & valid_mh
        bw_above_sma = (bw2 > smav) & valid_mh
        # A3 (затухание)
        white_after_g = (bw2 > 0) & (bw2 < smav) & valid_mh
        white_after_r = (bw2 < 0) & (bw2 > smav) & valid_mh
        # B
        ob60 = (bw2 >= 60) & valid_mh
        os60 = (bw2 <= -60) & valid_mh
        # C (MF)
        mf_neg = (mf < 0) & valid_mf
        mf_pos = (mf > 0) & valid_mf

        print(f"=== Money Hands LTF {tf} ===")
        # HH формы
        report(f"HH ∩ A1 🔴 ({tf})", hh, hh_core[valid] & red[valid], base_hh, n_core_hh)
        report(f"HH ∩ A2 bw2<SMA ({tf})", hh, hh_core[valid] & bw_below_sma[valid], base_hh, n_core_hh)
        report(f"HH ∩ A3 ⚪after🟢 ({tf})", hh, hh_core[valid] & white_after_g[valid], base_hh, n_core_hh)
        report(f"HH ∩ B bw2≥+60 ({tf})", hh, hh_core[valid] & ob60[valid], base_hh, n_core_hh)
        report(f"HH ∩ C MF<0 ({tf})", hh, hh_core[valid] & mf_neg[valid], base_hh, n_core_hh)
        # LL формы
        report(f"LL ∩ A1 🟢 ({tf})", ll, ll_core[valid] & grn[valid], base_ll, n_core_ll)
        report(f"LL ∩ A2 bw2>SMA ({tf})", ll, ll_core[valid] & bw_above_sma[valid], base_ll, n_core_ll)
        report(f"LL ∩ A3 ⚪after🔴 ({tf})", ll, ll_core[valid] & white_after_r[valid], base_ll, n_core_ll)
        report(f"LL ∩ B bw2≤-60 ({tf})", ll, ll_core[valid] & os60[valid], base_ll, n_core_ll)
        report(f"LL ∩ C MF>0 ({tf})", ll, ll_core[valid] & mf_pos[valid], base_ll, n_core_ll)
        print()


if __name__ == "__main__":
    main()
