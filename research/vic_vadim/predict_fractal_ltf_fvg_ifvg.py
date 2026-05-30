"""Условие 2: внутри 12h свечи i на LTF {15m, 30m, 45m, 1h, 2h, 3h, 4h}
наличие FVG и/или iFVG (inverse FVG).

FVG canon ([[универсальные определения OB и FVG]]):
  LONG  FVG: high(k-2) < low(k),  zone=[high(k-2), low(k)]
  SHORT FVG: low(k-2) > high(k),  zone=[high(k), low(k-2)]

iFVG canon ([[inverse-fvg-definition]]):
  FVG-A нем., цена возвращается, формируется FVG-B противоположного
  направления, чьи c0..c2 первыми перекрывают зону A → iFVG event.
  Continuation в направлении B.

«Внутри 12h свечи i»:
  FVG  — c2_close ∈ (i.open, i.close] (т.е. третья свеча FVG закрылась в i)
  iFVG — touch_time свечи, первой коснувшейся A, ∈ (i.open, i.close]

Direction для предсказания:
  HH (вершина) → SHORT FVG  и  bear-continuation iFVG (A=LONG → B=SHORT)
  LL (дно)     → LONG FVG   и  bull-continuation iFVG (A=SHORT → B=LONG)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_15M = ROOT / "data" / "BTCUSDT_15m_vic_vadim.csv"
LTF_LIST: list[tuple[str, str]] = [
    ("15m", "15min"), ("30m", "30min"), ("45m", "45min"),
    ("1h", "60min"), ("2h", "120min"), ("3h", "180min"), ("4h", "240min"),
]
WEEKLY_ANCHOR = pd.Timestamp("1970-01-05", tz="UTC")


def load_15m() -> pd.DataFrame:
    df = pd.read_csv(CACHE_15M, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df


def compose(df_15m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_15m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def find_fvgs_indexed(df_tf: pd.DataFrame) -> list[dict]:
    """FVG со ссылкой на индексы — нужно для iFVG."""
    out: list[dict] = []
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("15min")
    n = len(df_tf)
    for k in range(n - 2):
        if h[k] < l[k+2]:
            out.append({
                "dir": "LONG", "c0_pos": k, "c2_pos": k+2,
                "zone_bottom": float(h[k]), "zone_top": float(l[k+2]),
                "c2_close_time": idx[k+2] + tf_dur,
            })
        if l[k] > h[k+2]:
            out.append({
                "dir": "SHORT", "c0_pos": k, "c2_pos": k+2,
                "zone_bottom": float(h[k+2]), "zone_top": float(l[k]),
                "c2_close_time": idx[k+2] + tf_dur,
            })
    return out


def find_ifvg_events(df_tf: pd.DataFrame, fvgs: list[dict]) -> list[dict]:
    """Возвращает iFVG-события: для каждой untouched FVG-A находим первую
    свечу, коснувшуюся её зоны. Если эта свеча лежит внутри FVG-B
    противоположного направления (по позициям c0..c2), и B сформирована
    позже A, и зоны A и B перекрываются — это iFVG event."""
    out: list[dict] = []
    if not fvgs:
        return out
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("15min")
    n = len(df_tf)

    # отсортируем FVG по c2_pos для эффективного поиска B
    fvgs_sorted = sorted(fvgs, key=lambda x: x["c2_pos"])
    # индекс по c0_pos для поиска B
    c0_array = np.array([f["c0_pos"] for f in fvgs_sorted])

    for a in fvgs:
        a_start = a["c2_pos"] + 1
        if a_start >= n:
            continue
        # first touch
        first_touch = -1
        for i in range(a_start, n):
            if l[i] <= a["zone_top"] and h[i] >= a["zone_bottom"]:
                first_touch = i
                break
        if first_touch < 0:
            continue
        # ищем B: dir(B) != dir(A), c0_pos(B) > c2_pos(A), c0_pos(B) <= first_touch <= c2_pos(B)
        # zones overlap
        for b in fvgs_sorted:
            if b["dir"] == a["dir"]:
                continue
            if b["c0_pos"] <= a["c2_pos"]:
                continue
            if not (b["c0_pos"] <= first_touch <= b["c2_pos"]):
                continue
            # zones overlap
            if not (b["zone_top"] >= a["zone_bottom"] and b["zone_bottom"] <= a["zone_top"]):
                continue
            # event
            event_time = idx[first_touch] + tf_dur  # close of touch candle
            out.append({
                "dir_a": a["dir"], "dir_b": b["dir"],
                "touch_pos": first_touch,
                "event_time": event_time,
            })
            break
    return out


def flags_in_12h(
    df_12h: pd.DataFrame, ltf_events: list[pd.Timestamp],
) -> np.ndarray:
    """Bool по 12h свечам: True если хоть одно событие event_time ∈ (i.open, i.open + 12h]."""
    n = len(df_12h)
    flag = np.zeros(n, dtype=bool)
    idx = df_12h.index
    if not ltf_events:
        return flag
    times = pd.DatetimeIndex(ltf_events)
    if times.tz is None:
        times = times.tz_localize("UTC")
    # for each event find 12h bar it belongs to
    for t in times:
        # bar i содержит close-time c2 если idx[i] < t <= idx[i] + 12h
        pos = int(idx.searchsorted(t, side="right")) - 1
        if 0 <= pos < n:
            flag[pos] = True
    return flag


def main() -> None:
    df_15m = load_15m()
    df_12h = compose(df_15m, "12h").sort_index()
    print(f"12h BTC: {len(df_12h)} баров")

    fvg_short_times: list[pd.Timestamp] = []
    fvg_long_times: list[pd.Timestamp] = []
    ifvg_bull2bear_times: list[pd.Timestamp] = []  # continuation вниз → HH прогноз
    ifvg_bear2bull_times: list[pd.Timestamp] = []  # continuation вверх → LL прогноз

    per_tf_counts: dict[str, dict[str, int]] = {}
    for tf, freq in LTF_LIST:
        df_tf = compose(df_15m, freq).sort_index()
        fvgs = find_fvgs_indexed(df_tf)
        ifvg_events = find_ifvg_events(df_tf, fvgs)
        n_short = sum(1 for f in fvgs if f["dir"] == "SHORT")
        n_long = sum(1 for f in fvgs if f["dir"] == "LONG")
        n_b2s = sum(1 for e in ifvg_events if e["dir_a"] == "LONG" and e["dir_b"] == "SHORT")
        n_s2b = sum(1 for e in ifvg_events if e["dir_a"] == "SHORT" and e["dir_b"] == "LONG")
        per_tf_counts[tf] = {"SHORT": n_short, "LONG": n_long, "iFVG_b2s": n_b2s, "iFVG_s2b": n_s2b}
        print(f"  {tf}: FVG SHORT={n_short} LONG={n_long}  iFVG bull→bear={n_b2s} bear→bull={n_s2b}")
        for f in fvgs:
            t = pd.Timestamp(f["c2_close_time"])
            if t.tz is None: t = t.tz_localize("UTC")
            if f["dir"] == "SHORT": fvg_short_times.append(t)
            else: fvg_long_times.append(t)
        for e in ifvg_events:
            t = pd.Timestamp(e["event_time"])
            if t.tz is None: t = t.tz_localize("UTC")
            if e["dir_a"] == "LONG" and e["dir_b"] == "SHORT":
                ifvg_bull2bear_times.append(t)
            elif e["dir_a"] == "SHORT" and e["dir_b"] == "LONG":
                ifvg_bear2bull_times.append(t)

    print(f"\nTotal: SHORT FVG={len(fvg_short_times)}, LONG FVG={len(fvg_long_times)}")
    print(f"       iFVG bull→bear={len(ifvg_bull2bear_times)}, bear→bull={len(ifvg_bear2bull_times)}")

    f_short = flags_in_12h(df_12h, fvg_short_times)
    f_long = flags_in_12h(df_12h, fvg_long_times)
    f_ib2s = flags_in_12h(df_12h, ifvg_bull2bear_times)
    f_is2b = flags_in_12h(df_12h, ifvg_bear2bull_times)

    n = len(df_12h); valid = np.arange(2, n - 2)
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy()
    hh = ((h[valid] > h[valid-2]) & (h[valid] > h[valid-1])
          & (h[valid] > h[valid+1]) & (h[valid] > h[valid+2]))
    ll = ((l[valid] < l[valid-2]) & (l[valid] < l[valid-1])
          & (l[valid] < l[valid+1]) & (l[valid] < l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nP(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%")

    def report(label: str, target: np.ndarray, cond: np.ndarray, base: float) -> None:
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        cov = n_c / n_total
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        print(f"  {label:<40} cov={cov*100:5.2f}%  prec={prec*100:6.2f}%  "
              f"lift=×{lift:.2f}  ({(prec-base)*100:+6.2f}pp)  rec={rec*100:5.2f}%  n={n_c}")

    print("\n=== Условие 2: FVG/iFVG на LTF {15m..4h} внутри i ===")
    report("HH | SHORT FVG в i",       hh, f_short[valid], base_hh)
    report("HH | iFVG bull→bear в i",  hh, f_ib2s[valid], base_hh)
    report("HH | OR (FVG | iFVG)",     hh, (f_short | f_ib2s)[valid], base_hh)
    report("LL | LONG FVG в i",        ll, f_long[valid], base_ll)
    report("LL | iFVG bear→bull в i",  ll, f_is2b[valid], base_ll)
    report("LL | OR (FVG | iFVG)",     ll, (f_long | f_is2b)[valid], base_ll)

    # Per-LTF
    print("\n=== Per-LTF (FVG/iFVG раздельно) ===")
    for tf, freq in LTF_LIST:
        df_tf = compose(df_15m, freq).sort_index()
        fvgs = find_fvgs_indexed(df_tf)
        ifvg_events = find_ifvg_events(df_tf, fvgs)

        t_short = [pd.Timestamp(f["c2_close_time"]).tz_localize("UTC") if pd.Timestamp(f["c2_close_time"]).tz is None else pd.Timestamp(f["c2_close_time"])
                   for f in fvgs if f["dir"] == "SHORT"]
        t_long = [pd.Timestamp(f["c2_close_time"]).tz_localize("UTC") if pd.Timestamp(f["c2_close_time"]).tz is None else pd.Timestamp(f["c2_close_time"])
                  for f in fvgs if f["dir"] == "LONG"]
        t_b2s = [pd.Timestamp(e["event_time"]).tz_localize("UTC") if pd.Timestamp(e["event_time"]).tz is None else pd.Timestamp(e["event_time"])
                 for e in ifvg_events if e["dir_a"] == "LONG" and e["dir_b"] == "SHORT"]
        t_s2b = [pd.Timestamp(e["event_time"]).tz_localize("UTC") if pd.Timestamp(e["event_time"]).tz is None else pd.Timestamp(e["event_time"])
                 for e in ifvg_events if e["dir_a"] == "SHORT" and e["dir_b"] == "LONG"]

        ff_short = flags_in_12h(df_12h, t_short)
        ff_long = flags_in_12h(df_12h, t_long)
        ff_b2s = flags_in_12h(df_12h, t_b2s)
        ff_s2b = flags_in_12h(df_12h, t_s2b)

        print(f"\n--- {tf} ---")
        report(f"HH | SHORT FVG ({tf})",      hh, ff_short[valid], base_hh)
        report(f"HH | iFVG bull→bear ({tf})", hh, ff_b2s[valid], base_hh)
        report(f"LL | LONG FVG ({tf})",       ll, ff_long[valid], base_ll)
        report(f"LL | iFVG bear→bull ({tf})", ll, ff_s2b[valid], base_ll)


if __name__ == "__main__":
    main()
