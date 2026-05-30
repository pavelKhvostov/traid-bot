"""maxV (ViC ASVK) как C3 confluence для предсказания HH/LL фрактала на 12h BTC.

maxV для каждой 12h свечи: close одной 15m-свечи (LTF) с максимальным
dirVolume среди bull/bear внутри 12h бара (см. calculate_vic_d).

ПРИБЛИЖЕНИЕ: на D-chart Pine использует LTF=15m, на 12h-chart Pine бы
использовал ~5m (closest valid от 432s). У нас в кеше только 15m —
используем как ближайшее доступное, числа могут отличаться от точного
Pine на 12h.

Сигналы (HH = вершина → SHORT):
  sweep_maxV(i-1) свечой i: high(i)>maxV(i-1) AND close(i)<maxV(i-1)
  sweep_maxV(i-2) свечой i-1: те же условия со сдвигом на 1
LL — зеркально с low<maxV AND close>maxV.

Confluence с C1 (HTF sweep) и C2 (LTF OB ∩ FVG (1h-2h)).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vic_levels import calculate_vic_d  # noqa: F401 (для справки)

CACHE_15M = ROOT / "data" / "BTCUSDT_15m_vic_vadim.csv"
HTF_LIST: list[tuple[str, str]] = [("12h", "12h"), ("1d", "1D"), ("2d", "2D"), ("3d", "3D"), ("W", "7D")]
WEEKLY_ANCHOR = pd.Timestamp("1970-01-05", tz="UTC")


def load_15m() -> pd.DataFrame:
    df = pd.read_csv(CACHE_15M, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df


def compose_htf(df_15m: pd.DataFrame, freq: str) -> pd.DataFrame:
    origin = WEEKLY_ANCHOR if freq == "7D" else "epoch"
    return df_15m.resample(freq, origin=origin, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def calculate_maxv_12h_bar(df_15m: pd.DataFrame, bar_open: pd.Timestamp) -> float | None:
    """maxV одного 12h бара: close 15m свечи с макс объёмом среди bull/bear,
    выбираем ту группу, у которой максимум выше. Полная аналогия calculate_vic_d,
    но окно 12h, не 24h."""
    bar_end = bar_open + pd.Timedelta(hours=12)
    mask = (df_15m.index >= bar_open) & (df_15m.index < bar_end)
    sub = df_15m.loc[mask]
    if sub.empty:
        return None
    bull = sub[sub["close"] > sub["open"]]
    bear = sub[sub["close"] < sub["open"]]
    max_bull = bull["volume"].max() if not bull.empty else 0
    max_bear = bear["volume"].max() if not bear.empty else 0
    if max_bull == 0 and max_bear == 0:
        return None
    if max_bull > max_bear:
        return float(bull.loc[bull["volume"].idxmax(), "close"])
    return float(bear.loc[bear["volume"].idxmax(), "close"])


# === C1 helpers (копия из confluence script) ===

def find_ob_zones(df_tf, tf_label):
    out = []
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 1):
        if c[k] < o[k] and c[k+1] > o[k+1] and c[k+1] > o[k]:
            zb, zt = float(min(l[k], l[k+1])), float(o[k])
            if zt > zb:
                out.append({"dir":"LONG","zone_bottom":zb,"zone_top":zt,"ready_time":idx[k+1]+tf_dur})
        if c[k] > o[k] and c[k+1] < o[k+1] and c[k+1] < o[k]:
            zb, zt = float(o[k]), float(max(h[k], h[k+1]))
            if zt > zb:
                out.append({"dir":"SHORT","zone_bottom":zb,"zone_top":zt,"ready_time":idx[k+1]+tf_dur})
    return out


def find_ob_liq_zones(df_tf, tf_label):
    out = []
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(2, len(df_tf) - 2):
        po,ph,pl,pc = o[k],h[k],l[k],c[k]
        co,ch,cl,cc = o[k+1],h[k+1],l[k+1],c[k+1]
        bp = abs(po - pc)
        if pc < po and cc > co and cc > po:
            lwp = min(po,pc) - pl; lwc = min(co,cc) - cl
            if lwp > 3*lwc and lwp > bp and (
                pl < l[k-2] and pl < l[k-1] and pl < l[k+1] and pl < l[k+2]):
                out.append({"dir":"LONG","zone_bottom":float(pl),"zone_top":float(cl),
                            "ready_time":idx[k+1]+tf_dur})
        if pc > po and cc < co and cc < po:
            uwp = ph - max(po,pc); uwc = ch - max(co,cc)
            if uwp > 3*uwc and uwp > bp and (
                ph > h[k-2] and ph > h[k-1] and ph > h[k+1] and ph > h[k+2]):
                out.append({"dir":"SHORT","zone_bottom":float(ch),"zone_top":float(ph),
                            "ready_time":idx[k+1]+tf_dur})
    return out


def find_fractals(df_tf, tf_label):
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


# === C2 helpers ===

def compose_ltf(df_15m, freq):
    return df_15m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum",
    }).dropna(subset=["close"])


def find_fvgs_for_ltf(df_tf):
    out = []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1]-idx[0]) if len(idx) > 1 else pd.Timedelta("15min")
    for k in range(len(df_tf)-2):
        if h[k] < l[k+2]:
            out.append({"dir":"LONG","c2_close_time":idx[k+2]+tf_dur})
        if l[k] > h[k+2]:
            out.append({"dir":"SHORT","c2_close_time":idx[k+2]+tf_dur})
    return out


def flags_in_12h(df_12h, ts_list):
    n = len(df_12h); flag = np.zeros(n, dtype=bool); idx = df_12h.index
    if not ts_list: return flag
    times = pd.DatetimeIndex(ts_list)
    if times.tz is None: times = times.tz_localize("UTC")
    for t in times:
        pos = int(idx.searchsorted(t, side="right")) - 1
        if 0 <= pos < n:
            flag[pos] = True
    return flag


def main() -> None:
    df_15m = load_15m()
    df_12h = compose_htf(df_15m, "12h").sort_index()
    print(f"12h BTC: {len(df_12h)} баров")

    # maxV для каждой 12h свечи
    df_15m_naive = df_15m.copy()
    df_15m_naive.index.name = None
    maxv = np.full(len(df_12h), np.nan, dtype=float)
    for k, t in enumerate(df_12h.index):
        v = calculate_maxv_12h_bar(df_15m_naive, t)
        if v is not None:
            maxv[k] = v
    nan_n = int(np.isnan(maxv).sum())
    print(f"maxV рассчитан для {len(maxv) - nan_n} 12h свечей (NaN: {nan_n})")

    # Сигналы maxV
    h = df_12h["high"].to_numpy()
    l = df_12h["low"].to_numpy()
    c = df_12h["close"].to_numpy()

    sweep_short_at_i = np.zeros(len(df_12h), dtype=bool)
    sweep_long_at_i = np.zeros(len(df_12h), dtype=bool)
    for i in range(1, len(df_12h)):
        m_prev = maxv[i-1]
        if np.isnan(m_prev): continue
        if h[i] > m_prev and c[i] < m_prev: sweep_short_at_i[i] = True
        if l[i] < m_prev and c[i] > m_prev: sweep_long_at_i[i] = True

    # сигналы на свече i-1 (sweep maxV(i-2) свечой i-1) — для confluence на "i или i-1"
    sweep_short_at_im1 = np.zeros(len(df_12h), dtype=bool)
    sweep_long_at_im1 = np.zeros(len(df_12h), dtype=bool)
    sweep_short_at_im1[1:] = sweep_short_at_i[:-1]
    sweep_long_at_im1[1:] = sweep_long_at_i[:-1]

    print(f"\nsweep_maxV SHORT на i: {sweep_short_at_i.sum()}")
    print(f"sweep_maxV LONG  на i: {sweep_long_at_i.sum()}")
    print(f"sweep_maxV SHORT на i-1: {sweep_short_at_im1.sum()}")
    print(f"sweep_maxV LONG  на i-1: {sweep_long_at_im1.sum()}")

    # === C1 ===
    htf_dfs = {tf: compose_htf(df_15m, freq).sort_index() for tf, freq in HTF_LIST}
    all_ob, all_ob_liq, all_fract, all_fvg = [], [], [], []
    for tf, df_tf in htf_dfs.items():
        all_ob += find_ob_zones(df_tf, tf)
        all_ob_liq += find_ob_liq_zones(df_tf, tf)
        all_fract += find_fractals(df_tf, tf)
        # FVG-HTF
        h_ = df_tf["high"].to_numpy(); l_ = df_tf["low"].to_numpy()
        idx_ = df_tf.index
        tf_dur_ = (idx_[1] - idx_[0]) if len(idx_) > 1 else pd.Timedelta("12h")
        for k in range(len(df_tf) - 2):
            if h_[k] < l_[k+2]:
                all_fvg.append({"dir":"LONG","zone_bottom":float(h_[k]),"zone_top":float(l_[k+2]),
                                "ready_time":idx_[k+2]+tf_dur_})
            if l_[k] > h_[k+2]:
                all_fvg.append({"dir":"SHORT","zone_bottom":float(h_[k+2]),"zone_top":float(l_[k]),
                                "ready_time":idx_[k+2]+tf_dur_})

    c1_hh = {
        "sweep_FH":     fractal_sweep_flags(df_12h, all_fract, "FH"),
        "OB_sweep":     zone_sweep_flags(df_12h, all_ob, "SHORT"),
        "OB_liq_sweep": zone_sweep_flags(df_12h, all_ob_liq, "SHORT"),
        "FVG_sweep":    zone_sweep_flags(df_12h, all_fvg, "SHORT"),
    }
    c1_ll = {
        "sweep_FL":     fractal_sweep_flags(df_12h, all_fract, "FL"),
        "OB_sweep":     zone_sweep_flags(df_12h, all_ob, "LONG"),
        "OB_liq_sweep": zone_sweep_flags(df_12h, all_ob_liq, "LONG"),
        "FVG_sweep":    zone_sweep_flags(df_12h, all_fvg, "LONG"),
    }

    # === C2: OB(1h-2h) ∩ FVG(1h-2h) ===
    ob_short_12, ob_long_12 = [], []
    fvg_short_12, fvg_long_12 = [], []
    for tf, freq in [("1h","60min"), ("2h","120min")]:
        df_tf = compose_ltf(df_15m, freq).sort_index()
        for ob in find_ob_zones(df_tf, tf):
            t = pd.Timestamp(ob["ready_time"])
            if t.tz is None: t = t.tz_localize("UTC")
            (ob_short_12 if ob["dir"] == "SHORT" else ob_long_12).append(t)
        for f in find_fvgs_for_ltf(df_tf):
            t = pd.Timestamp(f["c2_close_time"])
            if t.tz is None: t = t.tz_localize("UTC")
            (fvg_short_12 if f["dir"] == "SHORT" else fvg_long_12).append(t)
    f_ob_s_12 = flags_in_12h(df_12h, ob_short_12)
    f_ob_l_12 = flags_in_12h(df_12h, ob_long_12)
    f_fvg_s_12 = flags_in_12h(df_12h, fvg_short_12)
    f_fvg_l_12 = flags_in_12h(df_12h, fvg_long_12)
    c2_hh = f_ob_s_12 & f_fvg_s_12
    c2_ll = f_ob_l_12 & f_fvg_l_12
    print(f"\nC2 HH (OB∩FVG 1h-2h): {c2_hh.sum()}")
    print(f"C2 LL (OB∩FVG 1h-2h): {c2_ll.sum()}")

    # === target ===
    n = len(df_12h); valid = np.arange(2, n - 2)
    hh = ((h[valid] > h[valid-2]) & (h[valid] > h[valid-1])
          & (h[valid] > h[valid+1]) & (h[valid] > h[valid+2]))
    ll = ((l[valid] < l[valid-2]) & (l[valid] < l[valid-1])
          & (l[valid] < l[valid+1]) & (l[valid] < l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nbaseline P(HH)={base_hh*100:.2f}%, P(LL)={base_ll*100:.2f}%\n")

    def metrics(target, cond):
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        cov = n_c / n_total
        prec = n_tc / n_c if n_c else float("nan")
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        return prec, cov, rec, n_c

    def report(label, target, cond, base):
        prec, cov, rec, n_c = metrics(target, cond)
        lift = prec / base if base else float("nan")
        print(f"  {label:<55} prec={prec*100:6.2f}% lift=×{lift:4.2f} "
              f"cov={cov*100:5.2f}% rec={rec*100:5.2f}% n={n_c}")

    # maxV само по себе
    print("=== maxV — соло ===")
    report("HH | sweep_maxV[i]",          hh, sweep_short_at_i[valid], base_hh)
    report("HH | sweep_maxV[i-1]",        hh, sweep_short_at_im1[valid], base_hh)
    report("HH | sweep_maxV[i] | [i-1]",  hh, (sweep_short_at_i | sweep_short_at_im1)[valid], base_hh)
    report("LL | sweep_maxV[i]",          ll, sweep_long_at_i[valid], base_ll)
    report("LL | sweep_maxV[i-1]",        ll, sweep_long_at_im1[valid], base_ll)
    report("LL | sweep_maxV[i] | [i-1]",  ll, (sweep_long_at_i | sweep_long_at_im1)[valid], base_ll)

    # C1 + maxV
    print("\n=== C1 + maxV[i] ===")
    for name, c1 in c1_hh.items():
        cond_hh = c1[valid] & sweep_short_at_i[valid]
        report(f"HH | {name} ∩ sweep_maxV[i]", hh, cond_hh, base_hh)
    for name, c1 in c1_ll.items():
        cond_ll = c1[valid] & sweep_long_at_i[valid]
        report(f"LL | {name} ∩ sweep_maxV[i]", ll, cond_ll, base_ll)

    print("\n=== C1 + maxV[i] OR maxV[i-1] ===")
    for name, c1 in c1_hh.items():
        cond_hh = c1[valid] & (sweep_short_at_i | sweep_short_at_im1)[valid]
        report(f"HH | {name} ∩ sweep_maxV[i,i-1]", hh, cond_hh, base_hh)
    for name, c1 in c1_ll.items():
        cond_ll = c1[valid] & (sweep_long_at_i | sweep_long_at_im1)[valid]
        report(f"LL | {name} ∩ sweep_maxV[i,i-1]", ll, cond_ll, base_ll)

    # C1 + C2 + maxV
    print("\n=== C1 ∩ C2 ∩ maxV[i,i-1] (полный confluence) ===")
    for name, c1 in c1_hh.items():
        cond_hh = c1[valid] & c2_hh[valid] & (sweep_short_at_i | sweep_short_at_im1)[valid]
        report(f"HH | {name} ∩ C2 ∩ maxV[i,i-1]", hh, cond_hh, base_hh)
    for name, c1 in c1_ll.items():
        cond_ll = c1[valid] & c2_ll[valid] & (sweep_long_at_i | sweep_long_at_im1)[valid]
        report(f"LL | {name} ∩ C2 ∩ maxV[i,i-1]", ll, cond_ll, base_ll)

    # === Union по нескольким C1 одновременно (∩ maxV[i]) ===
    print("\n=== UNION C1 (OR) ∩ maxV[i] ===")
    # HH unions
    u_hh_2 = (c1_hh["sweep_FH"] | c1_hh["OB_sweep"]) & sweep_short_at_i
    u_hh_3 = (c1_hh["sweep_FH"] | c1_hh["OB_sweep"] | c1_hh["OB_liq_sweep"]) & sweep_short_at_i
    u_hh_4 = (c1_hh["sweep_FH"] | c1_hh["OB_sweep"] | c1_hh["OB_liq_sweep"] | c1_hh["FVG_sweep"]) & sweep_short_at_i
    report("HH | FVG_sweep ∩ maxV[i] (solo)",                       hh, (c1_hh["FVG_sweep"] & sweep_short_at_i)[valid], base_hh)
    report("HH | (sweep_FH | OB_sweep) ∩ maxV[i]",                  hh, u_hh_2[valid], base_hh)
    report("HH | (sweep_FH | OB_sweep | OB_liq) ∩ maxV[i]",          hh, u_hh_3[valid], base_hh)
    report("HH | (sweep_FH | OB_sweep | OB_liq | FVG) ∩ maxV[i]",    hh, u_hh_4[valid], base_hh)
    # LL unions
    u_ll_2 = (c1_ll["sweep_FL"] | c1_ll["OB_sweep"]) & sweep_long_at_i
    u_ll_3 = (c1_ll["sweep_FL"] | c1_ll["OB_sweep"] | c1_ll["OB_liq_sweep"]) & sweep_long_at_i
    u_ll_4 = (c1_ll["sweep_FL"] | c1_ll["OB_sweep"] | c1_ll["OB_liq_sweep"] | c1_ll["FVG_sweep"]) & sweep_long_at_i
    report("LL | FVG_sweep ∩ maxV[i] (solo)",                       ll, (c1_ll["FVG_sweep"] & sweep_long_at_i)[valid], base_ll)
    report("LL | (sweep_FL | OB_sweep) ∩ maxV[i]",                  ll, u_ll_2[valid], base_ll)
    report("LL | (sweep_FL | OB_sweep | OB_liq) ∩ maxV[i]",          ll, u_ll_3[valid], base_ll)
    report("LL | (sweep_FL | OB_sweep | OB_liq | FVG) ∩ maxV[i]",    ll, u_ll_4[valid], base_ll)

    # Union с расширением maxV[i,i-1]
    print("\n=== UNION C1 (OR) ∩ maxV[i,i-1] ===")
    maxv_any_short = sweep_short_at_i | sweep_short_at_im1
    maxv_any_long  = sweep_long_at_i  | sweep_long_at_im1
    u_hh_2_w = (c1_hh["sweep_FH"] | c1_hh["OB_sweep"]) & maxv_any_short
    u_hh_3_w = (c1_hh["sweep_FH"] | c1_hh["OB_sweep"] | c1_hh["OB_liq_sweep"]) & maxv_any_short
    u_ll_2_w = (c1_ll["sweep_FL"] | c1_ll["OB_sweep"]) & maxv_any_long
    u_ll_3_w = (c1_ll["sweep_FL"] | c1_ll["OB_sweep"] | c1_ll["OB_liq_sweep"]) & maxv_any_long
    report("HH | (sweep_FH | OB_sweep) ∩ maxV[i,i-1]",              hh, u_hh_2_w[valid], base_hh)
    report("HH | (sweep_FH | OB_sweep | OB_liq) ∩ maxV[i,i-1]",     hh, u_hh_3_w[valid], base_hh)
    report("LL | (sweep_FL | OB_sweep) ∩ maxV[i,i-1]",              ll, u_ll_2_w[valid], base_ll)
    report("LL | (sweep_FL | OB_sweep | OB_liq) ∩ maxV[i,i-1]",     ll, u_ll_3_w[valid], base_ll)

    # Раздельный учёт пересечения двух C1 (где оба сработали → super-confluence)
    print("\n=== Super-confluence: ОБА C1 одновременно ∩ maxV[i] ===")
    both_hh = c1_hh["sweep_FH"] & c1_hh["OB_sweep"] & sweep_short_at_i
    both_ll = c1_ll["sweep_FL"] & c1_ll["OB_sweep"] & sweep_long_at_i
    report("HH | sweep_FH AND OB_sweep ∩ maxV[i]", hh, both_hh[valid], base_hh)
    report("LL | sweep_FL AND OB_sweep ∩ maxV[i]", ll, both_ll[valid], base_ll)


if __name__ == "__main__":
    main()
