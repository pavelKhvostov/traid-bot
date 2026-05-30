"""Влияние RDRB V2 (зона эффективности, canon) на предсказание HH/LL
фрактала на 12h BTC.

RDRB V2 формула (canon vault/knowledge/smc/что такое rdrb.md):
  LONG zone:  top    = min(anchor.high, trigger.close)
              bottom = max(anchor.open, anchor.close)   # верх тела anchor
  SHORT zone: top    = min(anchor.open, anchor.close)   # низ тела anchor
              bottom = max(anchor.low,  trigger.close)
Условие паттерна одинаковое для V1 и V2 (детектор в strategies/strategy_rdrb.py).

ready_time = close trigger (trigger_time + tf_duration).
Direction: LONG-zone → предсказание LL фрактала, SHORT-zone → HH фрактала.

Сигналы свечой i:
  HH | FT SHORT RDRB V2 на i
  HH | sweep SHORT RDRB V2: high(i)>zone.top AND close(i)<zone.top
  LL | FT LONG RDRB V2 на i
  LL | sweep LONG RDRB V2: low(i)<zone.bottom AND close(i)>zone.bottom

ТФ: 12h, 1d, 2d, 3d, W (Mon-Mon).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.strategy_rdrb import detect_rdrb

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


def find_rdrb_v2(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    out: list[dict] = []
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for i in range(2, len(df_tf)):
        z = detect_rdrb(df_tf, i, zone_version="V2")
        if z is None:
            continue
        out.append({
            "tf": tf_label, "dir": z.direction,
            "zone_bottom": float(z.bottom), "zone_top": float(z.top),
            "ready_time": z.trigger_time + tf_dur,
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

    all_z: list[dict] = []
    per_tf: dict[str, list[dict]] = {}
    for tf, df_tf in htf_dfs.items():
        z = find_rdrb_v2(df_tf, tf)
        per_tf[tf] = z
        all_z += z
        n_long = sum(1 for q in z if q["dir"] == "LONG")
        n_short = sum(1 for q in z if q["dir"] == "SHORT")
        print(f"  {tf}: RDRB V2 LONG={n_long}, SHORT={n_short}, всего {len(z)}")
    print(f"\nвсего RDRB V2 на 5 ТФ: {len(all_z)}")

    n = len(df_12h); valid = np.arange(2, n - 2)
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy()
    hh = ((h[valid] > h[valid-2]) & (h[valid] > h[valid-1])
          & (h[valid] > h[valid+1]) & (h[valid] > h[valid+2]))
    ll = ((l[valid] < l[valid-2]) & (l[valid] < l[valid-1])
          & (l[valid] < l[valid+1]) & (l[valid] < l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nP(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%")

    short_z = [z for z in all_z if z["dir"] == "SHORT"]
    long_z = [z for z in all_z if z["dir"] == "LONG"]
    ft_s = first_touch_flags(df_12h, short_z)
    ft_l = first_touch_flags(df_12h, long_z)
    sw_s = sweep_flags(df_12h, all_z, "SHORT")
    sw_l = sweep_flags(df_12h, all_z, "LONG")

    def report(label: str, target: np.ndarray, cond: np.ndarray, base: float) -> None:
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        cov = n_c / n_total
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        print(f"  {label:<48} cov={cov*100:5.2f}%  prec={prec*100:6.2f}%  "
              f"lift=×{lift:.2f}  ({(prec-base)*100:+6.2f}pp)  rec={rec*100:5.2f}%")

    print("\n=== RDRB V2 общее ===")
    report("HH | RDRB V2 ft[i]",       hh, ft_s[valid], base_hh)
    report("HH | RDRB V2 ft[i-1]",     hh, ft_s[valid-1], base_hh)
    report("HH | RDRB V2 sweep[i]",    hh, sw_s[valid], base_hh)
    report("LL | RDRB V2 ft[i]",       ll, ft_l[valid], base_ll)
    report("LL | RDRB V2 ft[i-1]",     ll, ft_l[valid-1], base_ll)
    report("LL | RDRB V2 sweep[i]",    ll, sw_l[valid], base_ll)

    print("\n=== Per-TF RDRB V2 (на свече i) ===")
    for tf, _ in HTF_LIST:
        z_tf = per_tf[tf]
        if not z_tf:
            print(f"\n--- {tf}: 0 RDRB V2, пропускаем ---")
            continue
        ft_s_tf = first_touch_flags(df_12h, [z for z in z_tf if z["dir"] == "SHORT"])
        ft_l_tf = first_touch_flags(df_12h, [z for z in z_tf if z["dir"] == "LONG"])
        sw_s_tf = sweep_flags(df_12h, z_tf, "SHORT")
        sw_l_tf = sweep_flags(df_12h, z_tf, "LONG")
        n_s = sum(1 for q in z_tf if q["dir"] == "SHORT")
        n_l = sum(1 for q in z_tf if q["dir"] == "LONG")
        print(f"\n--- {tf} (SHORT={n_s}, LONG={n_l}) ---")
        report(f"HH | RDRB V2 ft[i] ({tf} SHORT)",    hh, ft_s_tf[valid], base_hh)
        report(f"HH | RDRB V2 sweep[i] ({tf} SHORT)", hh, sw_s_tf[valid], base_hh)
        report(f"LL | RDRB V2 ft[i] ({tf} LONG)",     ll, ft_l_tf[valid], base_ll)
        report(f"LL | RDRB V2 sweep[i] ({tf} LONG)",  ll, sw_l_tf[valid], base_ll)


if __name__ == "__main__":
    main()
