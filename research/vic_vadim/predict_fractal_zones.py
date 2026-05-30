"""Гипотеза: вероятность HH/LL-фрактала на 12h BTC повышается, если свеча i
или i-1 first-touch'ит немитигированную зону (FVG или OB) или снимает
фрактальную ликвидность (wick-sweep + close назад) на ТФ ≥ 12h.

Зоны (canon OB/FVG):
  LONG OB: prev bear, cur bull, cur.close > prev.open
           zone = [min(prev.low, cur.low), prev.open]
  SHORT OB: симметрично, zone = [prev.open, max(prev.high, cur.high)]
  LONG FVG: high(i-2) < low(i), zone = [high(i-2), low(i)]
  SHORT FVG: low(i-2) > high(i), zone = [high(i), low(i-2)]

Sweep (wick + close назад):
  FH sweep: high(i) > FH_level AND close(i) < FH_level
  FL sweep: low(i) < FL_level AND close(i) > FL_level

Direction:
  HH prediction → SHORT FVG/OB first-touch  OR FH sweep
  LL prediction → LONG FVG/OB first-touch   OR FL sweep

Все ТФ ≥ 12h: 12h, 1d, 2d, 3d (composeятся из 15m с origin=epoch).
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


def load_15m() -> pd.DataFrame:
    df = pd.read_csv(CACHE_15M, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df


WEEKLY_ANCHOR = pd.Timestamp("1970-01-05", tz="UTC")  # понедельник (TV-стандарт W)


def compose(df_15m: pd.DataFrame, freq: str) -> pd.DataFrame:
    origin = WEEKLY_ANCHOR if freq == "7D" else "epoch"
    return df_15m.resample(freq, origin=origin, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def find_ob_zones(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    """Список (LONG и SHORT) OB-зон на одном ТФ.
    `ready_time` — момент close `cur` (когда зона известна)."""
    out: list[dict] = []
    o = df_tf["open"].to_numpy()
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    c = df_tf["close"].to_numpy()
    idx = df_tf.index.to_numpy()
    tf_dur = pd.Timedelta(idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 1):
        prev_bear = c[k] < o[k]
        prev_bull = c[k] > o[k]
        cur_bull = c[k+1] > o[k+1]
        cur_bear = c[k+1] < o[k+1]
        # LONG OB
        if prev_bear and cur_bull and c[k+1] > o[k]:
            zb = min(l[k], l[k+1])
            zt = o[k]
            if zt > zb:
                out.append({
                    "tf": tf_label, "dir": "LONG", "kind": "OB",
                    "zone_bottom": float(zb), "zone_top": float(zt),
                    "ready_time": idx[k+1] + tf_dur,
                })
        # SHORT OB
        if prev_bull and cur_bear and c[k+1] < o[k]:
            zb = o[k]
            zt = max(h[k], h[k+1])
            if zt > zb:
                out.append({
                    "tf": tf_label, "dir": "SHORT", "kind": "OB",
                    "zone_bottom": float(zb), "zone_top": float(zt),
                    "ready_time": idx[k+1] + tf_dur,
                })
    return out


def find_fvg_zones(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    out: list[dict] = []
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    idx = df_tf.index.to_numpy()
    tf_dur = pd.Timedelta(idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 2):
        # LONG FVG: high(i-2) < low(i)
        if h[k] < l[k+2]:
            out.append({
                "tf": tf_label, "dir": "LONG", "kind": "FVG",
                "zone_bottom": float(h[k]), "zone_top": float(l[k+2]),
                "ready_time": idx[k+2] + tf_dur,
            })
        # SHORT FVG: low(i-2) > high(i)
        if l[k] > h[k+2]:
            out.append({
                "tf": tf_label, "dir": "SHORT", "kind": "FVG",
                "zone_bottom": float(h[k+2]), "zone_top": float(l[k]),
                "ready_time": idx[k+2] + tf_dur,
            })
    return out


def find_fractals(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    """FH и FL по canon: high(i) > всех в i±2, low(i) < всех в i±2."""
    out: list[dict] = []
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    idx = df_tf.index.to_numpy()
    tf_dur = pd.Timedelta(idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    n = len(df_tf)
    for i in range(2, n - 2):
        if (h[i] > h[i-2]) and (h[i] > h[i-1]) and (h[i] > h[i+1]) and (h[i] > h[i+2]):
            out.append({
                "tf": tf_label, "kind": "FH", "level": float(h[i]),
                "ready_time": idx[i+2] + tf_dur,
            })
        if (l[i] < l[i-2]) and (l[i] < l[i-1]) and (l[i] < l[i+1]) and (l[i] < l[i+2]):
            out.append({
                "tf": tf_label, "kind": "FL", "level": float(l[i]),
                "ready_time": idx[i+2] + tf_dur,
            })
    return out


def compute_first_touch_flags(
    df_12h: pd.DataFrame, zones: list[dict],
) -> np.ndarray:
    """Возвращает bool-вектор по 12h свечам: True если эта свеча — первый
    touch хотя бы одной немитигированной зоны (после её ready_time)."""
    n = len(df_12h)
    flag = np.zeros(n, dtype=bool)
    idx = df_12h.index
    h = df_12h["high"].to_numpy()
    l = df_12h["low"].to_numpy()
    for z in zones:
        rt = pd.Timestamp(z["ready_time"])
        if rt.tz is None:
            rt = rt.tz_localize("UTC")
        start_pos = int(idx.searchsorted(rt, side="left"))
        if start_pos >= n:
            continue
        sub_l = l[start_pos:]
        sub_h = h[start_pos:]
        overlap = (sub_l <= z["zone_top"]) & (sub_h >= z["zone_bottom"])
        if not overlap.any():
            continue
        first_rel = int(np.argmax(overlap))
        flag[start_pos + first_rel] = True
    return flag


def compute_sweep_flags(
    df_12h: pd.DataFrame, fractals: list[dict], kind: str,
) -> np.ndarray:
    """Sweep свечой `i` фрактала, который был активен на момент i.
    Активен = ready_time <= i_time AND ещё не sweep'нут другой свечой."""
    n = len(df_12h)
    flag = np.zeros(n, dtype=bool)
    idx = df_12h.index
    h_arr = df_12h["high"].to_numpy()
    l_arr = df_12h["low"].to_numpy()
    c_arr = df_12h["close"].to_numpy()
    fr_ks = [f for f in fractals if f["kind"] == kind]
    for f in fr_ks:
        rt = pd.Timestamp(f["ready_time"])
        if rt.tz is None:
            rt = rt.tz_localize("UTC")
        start_pos = int(idx.searchsorted(rt, side="left"))
        if start_pos >= n:
            continue
        lvl = f["level"]
        for i in range(start_pos, n):
            if kind == "FH":
                # wick выше lvl, close ниже lvl → sweep
                if h_arr[i] > lvl and c_arr[i] < lvl:
                    flag[i] = True
                    break  # фрактал считается снятым
                # фрактал не снят но цена ушла выше навсегда (close > lvl без wick-only)
                # → больше не релевантен — выходим
                if c_arr[i] > lvl:
                    break
            else:  # FL
                if l_arr[i] < lvl and c_arr[i] > lvl:
                    flag[i] = True
                    break
                if c_arr[i] < lvl:
                    break
    return flag


def main() -> None:
    df_15m = load_15m()
    df_12h = compose(df_15m, "12h").sort_index()
    print(f"12h: {len(df_12h)} баров с {(df_12h.index.min() + pd.Timedelta(hours=3)):%Y-%m-%d %H:%M} "
          f"→ {(df_12h.index.max() + pd.Timedelta(hours=3)):%Y-%m-%d %H:%M} UTC+3")

    htf_dfs = {tf: compose(df_15m, freq).sort_index() for tf, freq in HTF_LIST}
    for tf, df_tf in htf_dfs.items():
        print(f"  {tf}: {len(df_tf)} bars")

    # 1) Все зоны и фракталы на всех ТФ ≥ 12h
    all_zones: list[dict] = []
    all_fractals: list[dict] = []
    for tf, df_tf in htf_dfs.items():
        all_zones += find_ob_zones(df_tf, tf)
        all_zones += find_fvg_zones(df_tf, tf)
        all_fractals += find_fractals(df_tf, tf)
    print(f"\nвсего зон (OB+FVG на 4 ТФ): {len(all_zones)}")
    print(f"всего фракталов (FH+FL на 4 ТФ): {len(all_fractals)}")

    # 2) First-touch флаги по 12h свечам, отдельно по направлению зоны
    short_zones = [z for z in all_zones if z["dir"] == "SHORT"]
    long_zones = [z for z in all_zones if z["dir"] == "LONG"]
    ft_short = compute_first_touch_flags(df_12h, short_zones)
    ft_long = compute_first_touch_flags(df_12h, long_zones)
    print(f"first-touch SHORT-зон: {ft_short.sum()} 12h свечей")
    print(f"first-touch LONG-зон:  {ft_long.sum()} 12h свечей")

    # 3) Sweep флаги
    sweep_fh = compute_sweep_flags(df_12h, all_fractals, "FH")
    sweep_fl = compute_sweep_flags(df_12h, all_fractals, "FL")
    print(f"FH-sweep: {sweep_fh.sum()} свечей")
    print(f"FL-sweep: {sweep_fl.sum()} свечей")

    # 4) Базовый scan фракталов на 12h
    n = len(df_12h)
    valid = np.arange(2, n - 2)
    h = df_12h["high"].to_numpy()
    l = df_12h["low"].to_numpy()
    hh = (
        (h[valid] > h[valid-2]) & (h[valid] > h[valid-1])
        & (h[valid] > h[valid+1]) & (h[valid] > h[valid+2])
    )
    ll = (
        (l[valid] < l[valid-2]) & (l[valid] < l[valid-1])
        & (l[valid] < l[valid+1]) & (l[valid] < l[valid+2])
    )

    # 5) Условия для HH: ft_short ИЛИ sweep_fh на i ИЛИ i-1
    # сдвиг i-1 = shift(1)
    ft_short_or_prev = ft_short[valid] | ft_short[valid - 1]
    ft_long_or_prev = ft_long[valid] | ft_long[valid - 1]
    sw_fh_or_prev = sweep_fh[valid] | sweep_fh[valid - 1]
    sw_fl_or_prev = sweep_fl[valid] | sweep_fl[valid - 1]

    cond_hh = ft_short_or_prev | sw_fh_or_prev
    cond_ll = ft_long_or_prev | sw_fl_or_prev

    def report(label: str, target: np.ndarray, cond: np.ndarray) -> None:
        n_total = len(target)
        n_t = int(target.sum())
        n_c = int(cond.sum())
        n_tc = int((target & cond).sum())
        base = n_t / n_total
        cov = n_c / n_total
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        rec = n_tc / n_t if n_t else float("nan")
        print(f"\n=== {label} ===")
        print(f"baseline P = {base*100:.2f}%  ({n_t}/{n_total})")
        print(f"coverage   = {cov*100:.1f}%  ({n_c} свечей с cond)")
        print(f"precision  = {prec*100:.2f}%  ({n_tc}/{n_c})")
        print(f"lift       = ×{lift:.2f}   ({(prec-base)*100:+.2f} pp)")
        print(f"recall     = {rec*100:.2f}%")

    report("HH | (ft_short[i] | ft_short[i-1] | sweep_FH[i] | sweep_FH[i-1])", hh, cond_hh)
    report("LL | (ft_long[i]  | ft_long[i-1]  | sweep_FL[i] | sweep_FL[i-1])", ll, cond_ll)

    # Разбивка по компонентам
    print("\n=== Компоненты HH (по отдельности) ===")
    report("HH | ft_short[i] only", hh, ft_short[valid])
    report("HH | ft_short[i-1] only", hh, ft_short[valid - 1])
    report("HH | sweep_FH[i] only", hh, sweep_fh[valid])
    report("HH | sweep_FH[i-1] only", hh, sweep_fh[valid - 1])

    print("\n=== Компоненты LL (по отдельности) ===")
    report("LL | ft_long[i] only", ll, ft_long[valid])
    report("LL | ft_long[i-1] only", ll, ft_long[valid - 1])
    report("LL | sweep_FL[i] only", ll, sweep_fl[valid])
    report("LL | sweep_FL[i-1] only", ll, sweep_fl[valid - 1])

    # Breakdown по ТФ фракталов
    print("\n=== Sweep per-TF (на свече i) ===")
    counts: dict[str, dict[str, int]] = {}
    for tf, _ in HTF_LIST:
        fr_tf = [f for f in all_fractals if f["tf"] == tf]
        counts[tf] = {
            "FH_n": sum(1 for f in fr_tf if f["kind"] == "FH"),
            "FL_n": sum(1 for f in fr_tf if f["kind"] == "FL"),
        }
        sw_fh_tf = compute_sweep_flags(df_12h, fr_tf, "FH")
        sw_fl_tf = compute_sweep_flags(df_12h, fr_tf, "FL")
        print(f"\n--- ТФ фрактала {tf} (FH={counts[tf]['FH_n']}, FL={counts[tf]['FL_n']}) ---")
        report(f"HH | sweep_FH({tf})[i]", hh, sw_fh_tf[valid])
        report(f"LL | sweep_FL({tf})[i]", ll, sw_fl_tf[valid])


if __name__ == "__main__":
    main()
