"""Гипотеза: «OB с явно выраженной зоной ликвидности» (canon) даёт edge
сильнее обычного OB. Тестируем как first-touch и как sweep liq_zone.

OB-with-liq (LONG, по canon vault/knowledge/smc/что такое OB с явно выраженной зоной ликвидности.md):
  prev bearish, cur bullish, cur.close > prev.open
  + нижний фитиль prev > 3× нижнего фитиля cur
  + нижний фитиль prev > тело prev
  + prev — LL-фрактал (low строго ниже low в {prev-2, prev-1, cur, cur+1})
  liq_zone = [prev.low, cur.low]

OB-with-liq (SHORT): зеркально, liq_zone = [cur.high, prev.high]

ТФ: 12h, 1d, 2d, 3d. Цель: 12h фрактал HH/LL.
Сигналы свечой i:
  HH | first-touch liq_zone(SHORT OB-liq, ТФ ≥ 12h) на i или i-1
  HH | sweep liq_zone(SHORT): high(i)>liq_top AND close(i)<liq_top
  LL | symmetric
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


def find_ob_with_liq(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    """OB с явно выраженным маркером ликвидности по canon.
    ready_time = открытие свечи cur+2 (т.е. close cur+1)."""
    out: list[dict] = []
    o = df_tf["open"].to_numpy()
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    c = df_tf["close"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    n = len(df_tf)
    # prev=k, cur=k+1. Нужны индексы k-2, k-1, k+1=cur, k+2=cur+1
    for k in range(2, n - 2):
        prev_open, prev_high, prev_low, prev_close = o[k], h[k], l[k], c[k]
        cur_open, cur_high, cur_low, cur_close = o[k+1], h[k+1], l[k+1], c[k+1]
        body_prev = abs(prev_open - prev_close)

        # LONG OB-liq
        long_ob_cond = (prev_close < prev_open) and (cur_close > cur_open) and (cur_close > prev_open)
        if long_ob_cond:
            lw_prev = min(prev_open, prev_close) - prev_low
            lw_cur = min(cur_open, cur_close) - cur_low
            cond1 = lw_prev > 3 * lw_cur
            cond2 = lw_prev > body_prev
            # LL-фрактал на prev: low строго ниже low соседей
            cond3 = (
                prev_low < l[k-2] and prev_low < l[k-1]
                and prev_low < l[k+1] and prev_low < l[k+2]
            )
            if cond1 and cond2 and cond3:
                out.append({
                    "tf": tf_label, "dir": "LONG", "kind": "OB-liq",
                    "liq_bottom": float(prev_low), "liq_top": float(cur_low),
                    "ready_time": idx[k+1] + tf_dur,  # close cur+1
                })

        # SHORT OB-liq
        short_ob_cond = (prev_close > prev_open) and (cur_close < cur_open) and (cur_close < prev_open)
        if short_ob_cond:
            uw_prev = prev_high - max(prev_open, prev_close)
            uw_cur = cur_high - max(cur_open, cur_close)
            cond1 = uw_prev > 3 * uw_cur
            cond2 = uw_prev > body_prev
            # HH-фрактал на prev: high строго выше high соседей
            cond3 = (
                prev_high > h[k-2] and prev_high > h[k-1]
                and prev_high > h[k+1] and prev_high > h[k+2]
            )
            if cond1 and cond2 and cond3:
                out.append({
                    "tf": tf_label, "dir": "SHORT", "kind": "OB-liq",
                    "liq_bottom": float(cur_high), "liq_top": float(prev_high),
                    "ready_time": idx[k+1] + tf_dur,
                })
    return out


def first_touch_flags(df_12h: pd.DataFrame, zones: list[dict]) -> np.ndarray:
    n = len(df_12h)
    flag = np.zeros(n, dtype=bool)
    idx = df_12h.index
    h = df_12h["high"].to_numpy()
    l = df_12h["low"].to_numpy()
    for z in zones:
        rt = pd.Timestamp(z["ready_time"])
        if rt.tz is None:
            rt = rt.tz_localize("UTC")
        sp = int(idx.searchsorted(rt, side="left"))
        if sp >= n:
            continue
        sl = l[sp:]
        sh = h[sp:]
        overlap = (sl <= z["liq_top"]) & (sh >= z["liq_bottom"])
        if not overlap.any():
            continue
        first_rel = int(np.argmax(overlap))
        flag[sp + first_rel] = True
    return flag


def sweep_flags(df_12h: pd.DataFrame, zones: list[dict], direction: str) -> np.ndarray:
    """Sweep liq_zone: для SHORT — high(i)>liq_top AND close(i)<liq_top,
    для LONG — low(i)<liq_bottom AND close(i)>liq_bottom.
    Зона считается «снятой» после первого sweep'а или после прохода close внутрь."""
    n = len(df_12h)
    flag = np.zeros(n, dtype=bool)
    idx = df_12h.index
    h = df_12h["high"].to_numpy()
    l = df_12h["low"].to_numpy()
    c = df_12h["close"].to_numpy()
    for z in zones:
        if z["dir"] != direction:
            continue
        rt = pd.Timestamp(z["ready_time"])
        if rt.tz is None:
            rt = rt.tz_localize("UTC")
        sp = int(idx.searchsorted(rt, side="left"))
        if sp >= n:
            continue
        # для SHORT тест проводим на верхней границе liq_top (prev.high)
        # для LONG — на нижней границе liq_bottom (prev.low)
        level = z["liq_top"] if direction == "SHORT" else z["liq_bottom"]
        for i in range(sp, n):
            if direction == "SHORT":
                if h[i] > level and c[i] < level:
                    flag[i] = True
                    break
                if c[i] > level:
                    break
            else:
                if l[i] < level and c[i] > level:
                    flag[i] = True
                    break
                if c[i] < level:
                    break
    return flag


def main() -> None:
    df_15m = load_15m()
    df_12h = compose(df_15m, "12h").sort_index()
    print(f"12h BTC: {len(df_12h)} баров")

    htf_dfs = {tf: compose(df_15m, freq).sort_index() for tf, freq in HTF_LIST}

    all_zones: list[dict] = []
    per_tf: dict[str, list[dict]] = {}
    for tf, df_tf in htf_dfs.items():
        z = find_ob_with_liq(df_tf, tf)
        per_tf[tf] = z
        all_zones += z
        n_long = sum(1 for q in z if q["dir"] == "LONG")
        n_short = sum(1 for q in z if q["dir"] == "SHORT")
        print(f"  {tf}: OB-liq LONG={n_long}, SHORT={n_short}, всего {len(z)}")
    print(f"\nвсего OB-liq на 4 ТФ: {len(all_zones)}")

    # Базовые фракталы 12h
    n = len(df_12h)
    valid = np.arange(2, n - 2)
    h = df_12h["high"].to_numpy()
    l = df_12h["low"].to_numpy()
    hh = ((h[valid] > h[valid-2]) & (h[valid] > h[valid-1])
          & (h[valid] > h[valid+1]) & (h[valid] > h[valid+2]))
    ll = ((l[valid] < l[valid-2]) & (l[valid] < l[valid-1])
          & (l[valid] < l[valid+1]) & (l[valid] < l[valid+2]))
    n_total = len(valid)
    base_hh = hh.mean()
    base_ll = ll.mean()
    print(f"\nP(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%  (на {n_total} валидных)")

    short_zones = [z for z in all_zones if z["dir"] == "SHORT"]
    long_zones = [z for z in all_zones if z["dir"] == "LONG"]

    ft_short = first_touch_flags(df_12h, short_zones)
    ft_long = first_touch_flags(df_12h, long_zones)
    sw_short = sweep_flags(df_12h, all_zones, "SHORT")
    sw_long = sweep_flags(df_12h, all_zones, "LONG")

    print(f"\nflags по 12h: ft_short={ft_short.sum()}, ft_long={ft_long.sum()}, "
          f"sw_short={sw_short.sum()}, sw_long={sw_long.sum()}")

    def report(label: str, target: np.ndarray, cond: np.ndarray, base: float) -> None:
        n_c = int(cond.sum())
        n_tc = int((target & cond).sum())
        cov = n_c / n_total
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        print(f"  {label:<48} cov={cov*100:5.2f}%  prec={prec*100:6.2f}%  "
              f"lift=×{lift:.2f}  ({(prec-base)*100:+6.2f}pp)  rec={rec*100:5.2f}%")

    print("\n=== HH (SHORT OB-liq) ===")
    report("HH | ft[i]",    hh, ft_short[valid], base_hh)
    report("HH | ft[i-1]",  hh, ft_short[valid-1], base_hh)
    report("HH | ft[i,i-1]", hh, ft_short[valid] | ft_short[valid-1], base_hh)
    report("HH | sweep[i]", hh, sw_short[valid], base_hh)
    report("HH | sweep[i-1]", hh, sw_short[valid-1], base_hh)

    print("\n=== LL (LONG OB-liq) ===")
    report("LL | ft[i]",    ll, ft_long[valid], base_ll)
    report("LL | ft[i-1]",  ll, ft_long[valid-1], base_ll)
    report("LL | ft[i,i-1]", ll, ft_long[valid] | ft_long[valid-1], base_ll)
    report("LL | sweep[i]", ll, sw_long[valid], base_ll)
    report("LL | sweep[i-1]", ll, sw_long[valid-1], base_ll)

    # Per-TF breakdown
    print("\n=== Per-TF (sweep на свече i) ===")
    for tf in [t for t, _ in HTF_LIST]:
        z_tf = per_tf[tf]
        sw_sh = sweep_flags(df_12h, z_tf, "SHORT")
        sw_lo = sweep_flags(df_12h, z_tf, "LONG")
        n_sh = sum(1 for q in z_tf if q["dir"] == "SHORT")
        n_lo = sum(1 for q in z_tf if q["dir"] == "LONG")
        print(f"\n--- {tf} (SHORT OB-liq={n_sh}, LONG OB-liq={n_lo}) ---")
        report(f"HH | sweep[i] ({tf} SHORT)", hh, sw_sh[valid], base_hh)
        report(f"LL | sweep[i] ({tf} LONG)",  ll, sw_lo[valid], base_ll)


if __name__ == "__main__":
    main()
