"""Brute-force перебор делителя mlt (Pine ASVK ViC параметр) от 30 до 200
с шагом 5. Для каждого mlt:
  - rs = 43200 / mlt
  - LTF = ceil(rs/60) минут (Pine round-up logic, как для mlt=100→8m)
  - Пересчёт maxV для всех 12h-свечей
  - Запуск стратегии Core (sweep_FH ∪ OB_sweep) ∩ maxV[i]
  - Метрики: precision HH, LL, Σ
Цель: найти mlt с максимальной общей precision (или n×precision = hits).

⚠ Это in-sample optimization → overfitting risk.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_1M = ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"
HTF_LIST = [("12h", "12h"), ("1d", "1D"), ("2d", "2D"), ("3d", "3D"), ("W", "7D")]
WEEKLY_ANCHOR = pd.Timestamp("1970-01-05", tz="UTC")


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE_1M, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def compose_htf(df_base, freq):
    origin = WEEKLY_ANCHOR if freq == "7D" else "epoch"
    return df_base.resample(freq, origin=origin, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def find_ob_zones(df_tf):
    out = []
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 1):
        if c[k] < o[k] and c[k+1] > o[k+1] and c[k+1] > o[k]:
            zb, zt = float(min(l[k], l[k+1])), float(o[k])
            if zt > zb: out.append({"dir":"LONG","zone_bottom":zb,"zone_top":zt,"ready_time":idx[k+1]+tf_dur})
        if c[k] > o[k] and c[k+1] < o[k+1] and c[k+1] < o[k]:
            zb, zt = float(o[k]), float(max(h[k], h[k+1]))
            if zt > zb: out.append({"dir":"SHORT","zone_bottom":zb,"zone_top":zt,"ready_time":idx[k+1]+tf_dur})
    return out


def find_fractals(df_tf):
    out = []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for i in range(2, len(df_tf) - 2):
        if h[i] > h[i-2] and h[i] > h[i-1] and h[i] > h[i+1] and h[i] > h[i+2]:
            out.append({"kind":"FH","level":float(h[i]),"ready_time":idx[i+2]+tf_dur})
        if l[i] < l[i-2] and l[i] < l[i-1] and l[i] < l[i+1] and l[i] < l[i+2]:
            out.append({"kind":"FL","level":float(l[i]),"ready_time":idx[i+2]+tf_dur})
    return out


def zone_sweep_flags(df_12h, zones, direction):
    n = len(df_12h); flag = np.zeros(n, dtype=bool); idx = df_12h.index
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy(); c = df_12h["close"].to_numpy()
    for z in zones:
        if z["dir"] != direction: continue
        rt = pd.Timestamp(z["ready_time"])
        if rt.tz is None: rt = rt.tz_localize("UTC")
        sp = int(idx.searchsorted(rt, side="left"))
        if sp >= n: continue
        level = z["zone_top"] if direction == "SHORT" else z["zone_bottom"]
        for i in range(sp, n):
            if direction == "SHORT":
                if h[i] > level and c[i] < level: flag[i] = True; break
                if c[i] > level: break
            else:
                if l[i] < level and c[i] > level: flag[i] = True; break
                if c[i] < level: break
    return flag


def fractal_sweep_flags(df_12h, fractals, kind):
    n = len(df_12h); flag = np.zeros(n, dtype=bool); idx = df_12h.index
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy(); c = df_12h["close"].to_numpy()
    for f in fractals:
        if f["kind"] != kind: continue
        rt = pd.Timestamp(f["ready_time"])
        if rt.tz is None: rt = rt.tz_localize("UTC")
        sp = int(idx.searchsorted(rt, side="left"))
        if sp >= n: continue
        lvl = f["level"]
        for i in range(sp, n):
            if kind == "FH":
                if h[i] > lvl and c[i] < lvl: flag[i] = True; break
                if c[i] > lvl: break
            else:
                if l[i] < lvl and c[i] > lvl: flag[i] = True; break
                if c[i] < lvl: break
    return flag


def maxv_all_12h(df_1m_naive, df_12h, ltf_min):
    """Вычислить maxV для каждой 12h свечи на заданном LTF (epoch-aligned)."""
    out = np.full(len(df_12h), np.nan)
    for k, t in enumerate(df_12h.index):
        end = t + pd.Timedelta(hours=12)
        sub = df_1m_naive[(df_1m_naive.index >= t) & (df_1m_naive.index < end)]
        if sub.empty: continue
        if ltf_min == 1:
            s = sub
        else:
            s = sub.resample(f'{ltf_min}min', origin='epoch', label='left', closed='left').agg({
                "open":"first","high":"max","low":"min","close":"last","volume":"sum"
            }).dropna(subset=["close"])
        if s.empty: continue
        bull = s[s["close"] > s["open"]]
        bear = s[s["close"] < s["open"]]
        mb = bull["volume"].max() if not bull.empty else 0
        mr = bear["volume"].max() if not bear.empty else 0
        if mb == 0 and mr == 0: continue
        if mb > mr:
            out[k] = float(bull.loc[bull["volume"].idxmax(), "close"])
        else:
            out[k] = float(bear.loc[bear["volume"].idxmax(), "close"])
    return out


def main() -> None:
    print("loading 1m...")
    df_1m = load_1m()
    df_1m_naive = df_1m.copy(); df_1m_naive.index.name = None

    htf_dfs = {tf: compose_htf(df_1m, freq) for tf, freq in HTF_LIST}
    df_12h = htf_dfs["12h"]

    # Подготовим C1 (общие для всех mlt)
    print("compute C1 flags...")
    all_ob, all_fract = [], []
    for tf, df_tf in htf_dfs.items():
        all_ob += find_ob_zones(df_tf)
        all_fract += find_fractals(df_tf)
    c1_fh = fractal_sweep_flags(df_12h, all_fract, "FH")
    c1_fl = fractal_sweep_flags(df_12h, all_fract, "FL")
    c1_obs = zone_sweep_flags(df_12h, all_ob, "SHORT")
    c1_obl = zone_sweep_flags(df_12h, all_ob, "LONG")

    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy(); c = df_12h["close"].to_numpy()
    n_bars = len(df_12h); valid = np.arange(2, n_bars - 2)
    hh = ((h[valid]>h[valid-2])&(h[valid]>h[valid-1])&(h[valid]>h[valid+1])&(h[valid]>h[valid+2]))
    ll = ((l[valid]<l[valid-2])&(l[valid]<l[valid-1])&(l[valid]<l[valid+1])&(l[valid]<l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()

    # Перебор mlt
    results = []
    print(f"\n{'mlt':>4} {'rs_s':>6} {'LTF':>4} {'HH_n':>5} {'HH_p%':>6} {'LL_n':>5} {'LL_p%':>6} "
          f"{'Σn':>5} {'Σh':>5} {'Σp%':>6}")
    seen_ltf = {}  # cache by LTF (different mlts can map to same LTF)
    for mlt in range(30, 205, 5):
        rs = 43200 / mlt
        rs = max(60, rs)  # non-premium
        ltf_min = math.ceil(rs / 60)
        if ltf_min not in seen_ltf:
            seen_ltf[ltf_min] = maxv_all_12h(df_1m_naive, df_12h, ltf_min)
        maxv = seen_ltf[ltf_min]
        sw_s = np.zeros(n_bars, dtype=bool); sw_l = np.zeros(n_bars, dtype=bool)
        for i in range(1, n_bars):
            if np.isnan(maxv[i-1]): continue
            if h[i] > maxv[i-1] and c[i] < maxv[i-1]: sw_s[i] = True
            if l[i] < maxv[i-1] and c[i] > maxv[i-1]: sw_l[i] = True
        hh_core = (c1_fh | c1_obs) & sw_s
        ll_core = (c1_fl | c1_obl) & sw_l
        hh_n = int(hh_core[valid].sum()); hh_h = int((hh & hh_core[valid]).sum())
        ll_n = int(ll_core[valid].sum()); ll_h = int((ll & ll_core[valid]).sum())
        hh_p = hh_h / hh_n * 100 if hh_n else 0
        ll_p = ll_h / ll_n * 100 if ll_n else 0
        sum_n = hh_n + ll_n; sum_h = hh_h + ll_h
        sum_p = sum_h / sum_n * 100 if sum_n else 0
        print(f"{mlt:>4} {rs:>6.0f} {ltf_min:>3}m {hh_n:>5} {hh_p:>6.2f} {ll_n:>5} {ll_p:>6.2f} "
              f"{sum_n:>5} {sum_h:>5} {sum_p:>6.2f}")
        results.append({
            "mlt": mlt, "ltf": ltf_min, "hh_n": hh_n, "hh_p": hh_p,
            "ll_n": ll_n, "ll_p": ll_p, "sum_n": sum_n, "sum_h": sum_h, "sum_p": sum_p,
        })

    # Топ по разным критериям
    print("\n=== TOP-5 по Σ precision ===")
    for r in sorted(results, key=lambda x: -x["sum_p"])[:5]:
        print(f"  mlt={r['mlt']:>3} LTF={r['ltf']}m  Σ prec={r['sum_p']:.2f}% (HH={r['hh_p']:.2f}%/{r['hh_n']}, LL={r['ll_p']:.2f}%/{r['ll_n']})  Σn={r['sum_n']}")
    print("\n=== TOP-5 по HH precision ===")
    for r in sorted(results, key=lambda x: -x["hh_p"])[:5]:
        print(f"  mlt={r['mlt']:>3} LTF={r['ltf']}m  HH={r['hh_p']:.2f}%/{r['hh_n']}  LL={r['ll_p']:.2f}%/{r['ll_n']}")
    print("\n=== TOP-5 по LL precision ===")
    for r in sorted(results, key=lambda x: -x["ll_p"])[:5]:
        print(f"  mlt={r['mlt']:>3} LTF={r['ltf']}m  LL={r['ll_p']:.2f}%/{r['ll_n']}  HH={r['hh_p']:.2f}%/{r['hh_n']}")
    print("\n=== TOP-5 по Σ hits (precision × n) ===")
    for r in sorted(results, key=lambda x: -x["sum_h"])[:5]:
        print(f"  mlt={r['mlt']:>3} LTF={r['ltf']}m  Σ hits={r['sum_h']}/Σn={r['sum_n']}  prec={r['sum_p']:.2f}%")


if __name__ == "__main__":
    main()
