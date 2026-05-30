"""Confluence-прогон: условие 1 (sweep/FT зон на ТФ ≥ 12h) AND условие 2
(FVG/iFVG на LTF 15m-4h внутри 12h свечи i) для предсказания HH/LL
фрактала на 12h BTC.

Условие 1 (HH): SHORT sweep[i] от одной из зон —
  sweep_FH, sweep OB, sweep OB-liq, sweep FVG (HTF ≥ 12h).
Условие 1 (LL): зеркально с LONG.

Условие 2: внутри 12h свечи i есть LTF-сигнал —
  C2.FVG = сформировалась SHORT/LONG FVG (c2_close в i)
  C2.iFVG = iFVG event (bull→bear для HH, bear→bull для LL) с touch_close в i
  C2.iFVG.1h2h = тот же сигнал, но только на LTF 1h или 2h (peak LTF)

Метрики: precision, lift, coverage, n. Сравнение C1 vs C1∩C2.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb  # noqa: F401 (на будущее)

CACHE_15M = ROOT / "data" / "BTCUSDT_15m_vic_vadim.csv"
HTF_LIST: list[tuple[str, str]] = [("12h", "12h"), ("1d", "1D"), ("2d", "2D"), ("3d", "3D"), ("W", "7D")]
LTF_LIST: list[tuple[str, str]] = [
    ("15m", "15min"), ("30m", "30min"), ("45m", "45min"),
    ("1h", "60min"), ("2h", "120min"), ("3h", "180min"), ("4h", "240min"),
]
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


def compose_ltf(df_15m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_15m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


# === HTF zones (условие 1) ===

def find_ob_zones(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    out = []
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 1):
        if c[k] < o[k] and c[k+1] > o[k+1] and c[k+1] > o[k]:
            zb, zt = float(min(l[k], l[k+1])), float(o[k])
            if zt > zb:
                out.append({"tf": tf_label, "dir": "LONG", "kind": "OB",
                            "zone_bottom": zb, "zone_top": zt, "ready_time": idx[k+1] + tf_dur})
        if c[k] > o[k] and c[k+1] < o[k+1] and c[k+1] < o[k]:
            zb, zt = float(o[k]), float(max(h[k], h[k+1]))
            if zt > zb:
                out.append({"tf": tf_label, "dir": "SHORT", "kind": "OB",
                            "zone_bottom": zb, "zone_top": zt, "ready_time": idx[k+1] + tf_dur})
    return out


def find_ob_liq_zones(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    out = []
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    n = len(df_tf)
    for k in range(2, n - 2):
        po, ph, pl, pc = o[k], h[k], l[k], c[k]
        co, ch, cl, cc = o[k+1], h[k+1], l[k+1], c[k+1]
        body_prev = abs(po - pc)
        # LONG OB-liq
        if pc < po and cc > co and cc > po:
            lw_prev = min(po, pc) - pl; lw_cur = min(co, cc) - cl
            if lw_prev > 3*lw_cur and lw_prev > body_prev and (
                pl < l[k-2] and pl < l[k-1] and pl < l[k+1] and pl < l[k+2]
            ):
                out.append({"tf": tf_label, "dir": "LONG", "kind": "OB-liq",
                            "zone_bottom": float(pl), "zone_top": float(cl),
                            "ready_time": idx[k+1] + tf_dur})
        # SHORT OB-liq
        if pc > po and cc < co and cc < po:
            uw_prev = ph - max(po, pc); uw_cur = ch - max(co, cc)
            if uw_prev > 3*uw_cur and uw_prev > body_prev and (
                ph > h[k-2] and ph > h[k-1] and ph > h[k+1] and ph > h[k+2]
            ):
                out.append({"tf": tf_label, "dir": "SHORT", "kind": "OB-liq",
                            "zone_bottom": float(ch), "zone_top": float(ph),
                            "ready_time": idx[k+1] + tf_dur})
    return out


def find_fvg_htf(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    out = []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 2):
        if h[k] < l[k+2]:
            out.append({"tf": tf_label, "dir": "LONG", "kind": "FVG",
                        "zone_bottom": float(h[k]), "zone_top": float(l[k+2]),
                        "ready_time": idx[k+2] + tf_dur})
        if l[k] > h[k+2]:
            out.append({"tf": tf_label, "dir": "SHORT", "kind": "FVG",
                        "zone_bottom": float(h[k+2]), "zone_top": float(l[k]),
                        "ready_time": idx[k+2] + tf_dur})
    return out


def find_fractals(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    out = []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    n = len(df_tf)
    for i in range(2, n-2):
        if (h[i] > h[i-2]) and (h[i] > h[i-1]) and (h[i] > h[i+1]) and (h[i] > h[i+2]):
            out.append({"tf": tf_label, "kind": "FH", "level": float(h[i]),
                        "ready_time": idx[i+2] + tf_dur})
        if (l[i] < l[i-2]) and (l[i] < l[i-1]) and (l[i] < l[i+1]) and (l[i] < l[i+2]):
            out.append({"tf": tf_label, "kind": "FL", "level": float(l[i]),
                        "ready_time": idx[i+2] + tf_dur})
    return out


def zone_sweep_flags(df_12h: pd.DataFrame, zones: list[dict], direction: str) -> np.ndarray:
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


def fractal_sweep_flags(df_12h: pd.DataFrame, fractals: list[dict], kind: str) -> np.ndarray:
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


# === LTF FVG / iFVG (условие 2) ===

def find_fvgs_indexed(df_tf: pd.DataFrame) -> list[dict]:
    out = []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("15min")
    for k in range(len(df_tf) - 2):
        if h[k] < l[k+2]:
            out.append({"dir": "LONG", "c0_pos": k, "c2_pos": k+2,
                        "zone_bottom": float(h[k]), "zone_top": float(l[k+2]),
                        "c2_close_time": idx[k+2] + tf_dur})
        if l[k] > h[k+2]:
            out.append({"dir": "SHORT", "c0_pos": k, "c2_pos": k+2,
                        "zone_bottom": float(h[k+2]), "zone_top": float(l[k]),
                        "c2_close_time": idx[k+2] + tf_dur})
    return out


def find_ifvg_events(df_tf: pd.DataFrame, fvgs: list[dict]) -> list[dict]:
    if not fvgs: return []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("15min")
    n = len(df_tf)
    fvgs_sorted = sorted(fvgs, key=lambda x: x["c2_pos"])
    out = []
    for a in fvgs:
        a_start = a["c2_pos"] + 1
        if a_start >= n: continue
        first_touch = -1
        for i in range(a_start, n):
            if l[i] <= a["zone_top"] and h[i] >= a["zone_bottom"]:
                first_touch = i; break
        if first_touch < 0: continue
        for b in fvgs_sorted:
            if b["dir"] == a["dir"]: continue
            if b["c0_pos"] <= a["c2_pos"]: continue
            if not (b["c0_pos"] <= first_touch <= b["c2_pos"]): continue
            if not (b["zone_top"] >= a["zone_bottom"] and b["zone_bottom"] <= a["zone_top"]): continue
            out.append({"dir_a": a["dir"], "dir_b": b["dir"],
                        "event_time": idx[first_touch] + tf_dur})
            break
    return out


def flags_in_12h(df_12h: pd.DataFrame, ts_list: list[pd.Timestamp]) -> np.ndarray:
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

    htf_dfs = {tf: compose_htf(df_15m, freq).sort_index() for tf, freq in HTF_LIST}

    # === Условие 1 — флаги для HH и LL ===
    all_ob: list[dict] = []; all_ob_liq: list[dict] = []
    all_fvg_htf: list[dict] = []; all_fract: list[dict] = []
    for tf, df_tf in htf_dfs.items():
        all_ob += find_ob_zones(df_tf, tf)
        all_ob_liq += find_ob_liq_zones(df_tf, tf)
        all_fvg_htf += find_fvg_htf(df_tf, tf)
        all_fract += find_fractals(df_tf, tf)

    c1_hh = {
        "sweep_FH":     fractal_sweep_flags(df_12h, all_fract, "FH"),
        "OB_sweep":     zone_sweep_flags(df_12h, all_ob, "SHORT"),
        "OB_liq_sweep": zone_sweep_flags(df_12h, all_ob_liq, "SHORT"),
        "FVG_sweep":    zone_sweep_flags(df_12h, all_fvg_htf, "SHORT"),
    }
    c1_ll = {
        "sweep_FL":     fractal_sweep_flags(df_12h, all_fract, "FL"),
        "OB_sweep":     zone_sweep_flags(df_12h, all_ob, "LONG"),
        "OB_liq_sweep": zone_sweep_flags(df_12h, all_ob_liq, "LONG"),
        "FVG_sweep":    zone_sweep_flags(df_12h, all_fvg_htf, "LONG"),
    }

    # === Условие 2 — LTF OB ===
    ob_short_all: list[pd.Timestamp] = []; ob_long_all: list[pd.Timestamp] = []
    ob_short_1h2h: list[pd.Timestamp] = []; ob_long_1h2h: list[pd.Timestamp] = []
    ob_short_15m30m: list[pd.Timestamp] = []; ob_long_15m30m: list[pd.Timestamp] = []

    for tf, freq in LTF_LIST:
        df_tf = compose_ltf(df_15m, freq).sort_index()
        obs = find_ob_zones(df_tf, tf)  # уже определена выше
        idx_tf = df_tf.index
        tf_dur = (idx_tf[1] - idx_tf[0]) if len(idx_tf) > 1 else pd.Timedelta("15min")
        for ob in obs:
            # ready_time = cur close = idx[cur_pos] + tf_dur — это уже выставлено в find_ob_zones
            t = pd.Timestamp(ob["ready_time"])
            if t.tz is None: t = t.tz_localize("UTC")
            if ob["dir"] == "SHORT":
                ob_short_all.append(t)
                if tf in ("1h", "2h"): ob_short_1h2h.append(t)
                if tf in ("15m", "30m"): ob_short_15m30m.append(t)
            else:
                ob_long_all.append(t)
                if tf in ("1h", "2h"): ob_long_1h2h.append(t)
                if tf in ("15m", "30m"): ob_long_15m30m.append(t)
    print(f"\nLTF OB total: SHORT={len(ob_short_all)}, LONG={len(ob_long_all)}")
    print(f"LTF OB 1h-2h: SHORT={len(ob_short_1h2h)}, LONG={len(ob_long_1h2h)}")
    print(f"LTF OB 15m-30m: SHORT={len(ob_short_15m30m)}, LONG={len(ob_long_15m30m)}")

    c2_hh = {
        "LTF OB (any)":         flags_in_12h(df_12h, ob_short_all),
        "LTF OB (1h-2h)":       flags_in_12h(df_12h, ob_short_1h2h),
        "LTF OB (15m-30m)":     flags_in_12h(df_12h, ob_short_15m30m),
    }
    c2_ll = {
        "LTF OB (any)":         flags_in_12h(df_12h, ob_long_all),
        "LTF OB (1h-2h)":       flags_in_12h(df_12h, ob_long_1h2h),
        "LTF OB (15m-30m)":     flags_in_12h(df_12h, ob_long_15m30m),
    }

    # === target и валидные ===
    n = len(df_12h); valid = np.arange(2, n - 2)
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy()
    hh = ((h[valid] > h[valid-2]) & (h[valid] > h[valid-1])
          & (h[valid] > h[valid+1]) & (h[valid] > h[valid+2]))
    ll = ((l[valid] < l[valid-2]) & (l[valid] < l[valid-1])
          & (l[valid] < l[valid+1]) & (l[valid] < l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nbaseline: P(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%  (n_valid={n_total})\n")

    def metrics(target: np.ndarray, cond: np.ndarray) -> tuple[float, float, float, int, int]:
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        cov = n_c / n_total
        prec = n_tc / n_c if n_c else float("nan")
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        return prec, cov, rec, n_tc, n_c

    def print_table(direction: str, c1: dict, c2: dict, target: np.ndarray, base: float) -> None:
        print(f"=== {direction} ===")
        print(f"{'C1':<14} {'C2':<22} {'precision':>10} {'lift':>6} "
              f"{'Δpp':>7} {'coverage':>9} {'recall':>8} {'n':>5}")
        for c1_name, c1_flag in c1.items():
            # baseline для C1 only
            prec, cov, rec, _, n_c = metrics(target, c1_flag[valid])
            lift = prec / base if base else float("nan")
            print(f"  {c1_name:<12} {'—':<22} {prec*100:9.2f}% ×{lift:4.2f} "
                  f"{(prec-base)*100:+6.2f} {cov*100:8.2f}% {rec*100:7.2f}% {n_c:5d}")
            for c2_name, c2_flag in c2.items():
                joint = c1_flag[valid] & c2_flag[valid]
                prec, cov, rec, _, n_c = metrics(target, joint)
                lift = prec / base if base else float("nan")
                print(f"  {'+':<12} {c2_name:<22} {prec*100:9.2f}% ×{lift:4.2f} "
                      f"{(prec-base)*100:+6.2f} {cov*100:8.2f}% {rec*100:7.2f}% {n_c:5d}")
        print()

    print_table("HH (вершина → SHORT)", c1_hh, c2_hh, hh, base_hh)
    print_table("LL (дно → LONG)",      c1_ll, c2_ll, ll, base_ll)


if __name__ == "__main__":
    main()
