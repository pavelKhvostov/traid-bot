"""Влияние FVG (зона неэффективности) на предсказание HH/LL фрактала на 12h BTC.

Тестируем отдельно от OB/FH/FL:
  HH | first-touch SHORT FVG на свече i (ТФ ≥ 12h)
  HH | sweep SHORT FVG: high(i)>FVG.top AND close(i)<FVG.top
  LL | first-touch LONG FVG на i
  LL | sweep LONG FVG: low(i)<FVG.bottom AND close(i)>FVG.bottom

ТФ: 12h, 1d, 2d, 3d, W (W=Mon-Mon).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_15M = ROOT / "data" / "BTCUSDT_15m_vic_vadim.csv"
HTF_LIST: list[tuple[str, str]] = [("12h", "12h"), ("1d", "1D"), ("2d", "2D"), ("3d", "3D"), ("W", "7D")]
WEEKLY_ANCHOR = pd.Timestamp("1970-01-05", tz="UTC")


def load_15m() -> pd.DataFrame:
    df = pd.read_csv(CACHE_15M, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df


def compose(df_15m: pd.DataFrame, freq: str) -> pd.DataFrame:
    origin = WEEKLY_ANCHOR if freq == "7D" else "epoch"
    return df_15m.resample(freq, origin=origin, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def find_fvg(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    """Canon FVG: LONG = high(i-2)<low(i), zone=[high(i-2), low(i)].
    SHORT = low(i-2)>high(i), zone=[high(i), low(i-2)]. ready_time = i+1*tf_dur."""
    out: list[dict] = []
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 2):
        if h[k] < l[k+2]:
            out.append({
                "tf": tf_label, "dir": "LONG", "zone_bottom": float(h[k]),
                "zone_top": float(l[k+2]), "ready_time": idx[k+2] + tf_dur,
            })
        if l[k] > h[k+2]:
            out.append({
                "tf": tf_label, "dir": "SHORT", "zone_bottom": float(h[k+2]),
                "zone_top": float(l[k]), "ready_time": idx[k+2] + tf_dur,
            })
    return out


def first_touch_flags(df_12h: pd.DataFrame, zones: list[dict]) -> np.ndarray:
    n = len(df_12h); flag = np.zeros(n, dtype=bool); idx = df_12h.index
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy()
    for z in zones:
        rt = pd.Timestamp(z["ready_time"])
        if rt.tz is None: rt = rt.tz_localize("UTC")
        sp = int(idx.searchsorted(rt, side="left"))
        if sp >= n: continue
        overlap = (l[sp:] <= z["zone_top"]) & (h[sp:] >= z["zone_bottom"])
        if not overlap.any(): continue
        flag[sp + int(np.argmax(overlap))] = True
    return flag


def sweep_flags(df_12h: pd.DataFrame, zones: list[dict], direction: str) -> np.ndarray:
    """Sweep FVG: для SHORT — high>zone.top AND close<zone.top; для LONG — low<zone.bottom AND close>zone.bottom.
    Зона считается «снятой» после первого sweep'а или после прохода close через границу."""
    n = len(df_12h); flag = np.zeros(n, dtype=bool); idx = df_12h.index
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy()
    c = df_12h["close"].to_numpy()
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


def main() -> None:
    df_15m = load_15m()
    df_12h = compose(df_15m, "12h").sort_index()
    print(f"12h BTC: {len(df_12h)} баров")

    htf_dfs = {tf: compose(df_15m, freq).sort_index() for tf, freq in HTF_LIST}

    all_fvg: list[dict] = []
    per_tf: dict[str, list[dict]] = {}
    for tf, df_tf in htf_dfs.items():
        z = find_fvg(df_tf, tf)
        per_tf[tf] = z
        all_fvg += z
        n_long = sum(1 for q in z if q["dir"] == "LONG")
        n_short = sum(1 for q in z if q["dir"] == "SHORT")
        print(f"  {tf}: FVG LONG={n_long}, SHORT={n_short}, всего {len(z)}")
    print(f"\nвсего FVG на 5 ТФ: {len(all_fvg)}")

    n = len(df_12h)
    valid = np.arange(2, n - 2)
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy()
    hh = ((h[valid] > h[valid-2]) & (h[valid] > h[valid-1])
          & (h[valid] > h[valid+1]) & (h[valid] > h[valid+2]))
    ll = ((l[valid] < l[valid-2]) & (l[valid] < l[valid-1])
          & (l[valid] < l[valid+1]) & (l[valid] < l[valid+2]))
    n_total = len(valid)
    base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nP(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%  (на {n_total} валидных)")

    short_fvg = [z for z in all_fvg if z["dir"] == "SHORT"]
    long_fvg = [z for z in all_fvg if z["dir"] == "LONG"]
    ft_s = first_touch_flags(df_12h, short_fvg)
    ft_l = first_touch_flags(df_12h, long_fvg)
    sw_s = sweep_flags(df_12h, all_fvg, "SHORT")
    sw_l = sweep_flags(df_12h, all_fvg, "LONG")

    def report(label: str, target: np.ndarray, cond: np.ndarray, base: float) -> None:
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        cov = n_c / n_total
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        print(f"  {label:<45} cov={cov*100:5.2f}%  prec={prec*100:6.2f}%  "
              f"lift=×{lift:.2f}  ({(prec-base)*100:+6.2f}pp)  rec={rec*100:5.2f}%")

    print("\n=== FVG общее (объединение всех ТФ) ===")
    report("HH | FVG ft[i]",       hh, ft_s[valid], base_hh)
    report("HH | FVG ft[i-1]",     hh, ft_s[valid-1], base_hh)
    report("HH | FVG sweep[i]",    hh, sw_s[valid], base_hh)
    report("LL | FVG ft[i]",       ll, ft_l[valid], base_ll)
    report("LL | FVG ft[i-1]",     ll, ft_l[valid-1], base_ll)
    report("LL | FVG sweep[i]",    ll, sw_l[valid], base_ll)

    print("\n=== Per-TF FVG (на свече i) ===")
    for tf, _ in HTF_LIST:
        z_tf = per_tf[tf]
        ft_s_tf = first_touch_flags(df_12h, [z for z in z_tf if z["dir"] == "SHORT"])
        ft_l_tf = first_touch_flags(df_12h, [z for z in z_tf if z["dir"] == "LONG"])
        sw_s_tf = sweep_flags(df_12h, z_tf, "SHORT")
        sw_l_tf = sweep_flags(df_12h, z_tf, "LONG")
        n_s = sum(1 for q in z_tf if q["dir"] == "SHORT")
        n_l = sum(1 for q in z_tf if q["dir"] == "LONG")
        print(f"\n--- {tf} (SHORT FVG={n_s}, LONG FVG={n_l}) ---")
        report(f"HH | FVG ft[i] ({tf} SHORT)",    hh, ft_s_tf[valid], base_hh)
        report(f"HH | FVG sweep[i] ({tf} SHORT)", hh, sw_s_tf[valid], base_hh)
        report(f"LL | FVG ft[i] ({tf} LONG)",     ll, ft_l_tf[valid], base_ll)
        report(f"LL | FVG sweep[i] ({tf} LONG)",  ll, sw_l_tf[valid], base_ll)


if __name__ == "__main__":
    main()
