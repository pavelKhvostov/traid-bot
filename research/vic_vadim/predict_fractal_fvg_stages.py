"""FVG: разбивка взаимодействия по этапам — first touch, second touch,
fill > 40%, fill > 50%, fill = 100%. Каждый этап = событие первого
достижения. Цель: HH/LL фрактал на 12h BTC.

Fill (доля проникновения цены в зону FVG):
  LONG FVG  : fill = clamp((zone.top - low(i))  / width, 0, 1)
  SHORT FVG : fill = clamp((high(i) - zone.bottom) / width, 0, 1)
  fill=1 — цена дошла до противоположной границы (или прошла её).

Touch — overlap: low(i) ≤ zone.top AND high(i) ≥ zone.bottom.
First touch — первая такая свеча после ready_time.
Second touch — overlap-свеча после уже состоявшегося выхода (no-overlap
   bar между ними).

События привязываются к свече, на которой этап достигнут впервые в
истории конкретной зоны.

Direction: SHORT FVG → HH прогноз, LONG FVG → LL прогноз.
ТФ: 12h, 1d, 2d, 3d, W (Mon-Mon).
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
STAGES = ["first_touch", "second_touch", "fill_40", "fill_50", "fill_100"]


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
    out: list[dict] = []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 2):
        if h[k] < l[k+2]:
            out.append({"tf": tf_label, "dir": "LONG", "zone_bottom": float(h[k]),
                        "zone_top": float(l[k+2]), "ready_time": idx[k+2] + tf_dur})
        if l[k] > h[k+2]:
            out.append({"tf": tf_label, "dir": "SHORT", "zone_bottom": float(h[k+2]),
                        "zone_top": float(l[k]), "ready_time": idx[k+2] + tf_dur})
    return out


def stage_flags(df_12h: pd.DataFrame, zones: list[dict], direction: str) -> dict[str, np.ndarray]:
    """Возвращает 5 bool-массивов по 12h свечам, по одному на каждый STAGE."""
    n = len(df_12h)
    flags = {s: np.zeros(n, dtype=bool) for s in STAGES}
    idx = df_12h.index
    h = df_12h["high"].to_numpy()
    l = df_12h["low"].to_numpy()

    for z in zones:
        if z["dir"] != direction:
            continue
        rt = pd.Timestamp(z["ready_time"])
        if rt.tz is None:
            rt = rt.tz_localize("UTC")
        sp = int(idx.searchsorted(rt, side="left"))
        if sp >= n:
            continue
        zt = z["zone_top"]; zb = z["zone_bottom"]
        width = zt - zb
        if width <= 0:
            continue
        # per-zone state
        touch_count = 0
        state = "untouched"
        max_fill = 0.0
        done_40 = done_50 = done_100 = False
        for i in range(sp, n):
            overlap = (l[i] <= zt) and (h[i] >= zb)
            if not overlap:
                if state == "in_zone":
                    state = "exited"
                continue
            # overlap
            entering = state in ("untouched", "exited")
            if entering:
                touch_count += 1
                if touch_count == 1:
                    flags["first_touch"][i] = True
                elif touch_count == 2:
                    flags["second_touch"][i] = True
                state = "in_zone"
            # вычислить fill для этой свечи
            if direction == "LONG":
                fill = (zt - l[i]) / width
            else:  # SHORT
                fill = (h[i] - zb) / width
            fill = max(0.0, min(1.0, fill))
            if fill > 0.40 and not done_40:
                flags["fill_40"][i] = True
                done_40 = True
            if fill > 0.50 and not done_50:
                flags["fill_50"][i] = True
                done_50 = True
            if fill >= 1.0 and not done_100:
                flags["fill_100"][i] = True
                done_100 = True
            if fill > max_fill:
                max_fill = fill
    return flags


def main() -> None:
    df_15m = load_15m()
    df_12h = compose(df_15m, "12h").sort_index()
    print(f"12h BTC: {len(df_12h)} баров")

    all_fvg: list[dict] = []
    for tf, freq in HTF_LIST:
        df_tf = compose(df_15m, freq).sort_index()
        z = find_fvg(df_tf, tf)
        all_fvg += z
        n_l = sum(1 for q in z if q["dir"] == "LONG")
        n_s = sum(1 for q in z if q["dir"] == "SHORT")
        print(f"  {tf}: FVG LONG={n_l}, SHORT={n_s}")
    print(f"всего FVG: {len(all_fvg)}")

    n = len(df_12h); valid = np.arange(2, n - 2)
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy()
    hh = ((h[valid] > h[valid-2]) & (h[valid] > h[valid-1])
          & (h[valid] > h[valid+1]) & (h[valid] > h[valid+2]))
    ll = ((l[valid] < l[valid-2]) & (l[valid] < l[valid-1])
          & (l[valid] < l[valid+1]) & (l[valid] < l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nP(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%  ({n_total} valid bars)")

    flags_short = stage_flags(df_12h, all_fvg, "SHORT")
    flags_long = stage_flags(df_12h, all_fvg, "LONG")

    def report(label: str, target: np.ndarray, cond: np.ndarray, base: float) -> None:
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        cov = n_c / n_total
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        print(f"  {label:<32} cov={cov*100:5.2f}%  prec={prec*100:6.2f}%  "
              f"lift=×{lift:.2f}  ({(prec-base)*100:+6.2f}pp)  rec={rec*100:5.2f}%  n={n_c}")

    print("\n=== HH | SHORT FVG этапы (на свече i) ===")
    for stage in STAGES:
        report(f"HH | FVG {stage}[i]", hh, flags_short[stage][valid], base_hh)

    print("\n=== LL | LONG FVG этапы (на свече i) ===")
    for stage in STAGES:
        report(f"LL | FVG {stage}[i]", ll, flags_long[stage][valid], base_ll)

    # Per-TF разбивка по этапам (best stage per TF)
    print("\n=== Per-TF (HH SHORT, LL LONG) — этапы ===")
    for tf, freq in HTF_LIST:
        df_tf = compose(df_15m, freq).sort_index()
        z_tf = find_fvg(df_tf, tf)
        f_short = stage_flags(df_12h, z_tf, "SHORT")
        f_long = stage_flags(df_12h, z_tf, "LONG")
        n_s = sum(1 for q in z_tf if q["dir"] == "SHORT")
        n_l = sum(1 for q in z_tf if q["dir"] == "LONG")
        print(f"\n--- {tf} (SHORT FVG={n_s}, LONG FVG={n_l}) ---")
        for stage in STAGES:
            report(f"HH {tf} {stage}", hh, f_short[stage][valid], base_hh)
        for stage in STAGES:
            report(f"LL {tf} {stage}", ll, f_long[stage][valid], base_ll)


if __name__ == "__main__":
    main()
