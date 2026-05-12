"""Этап 9: GRID SEARCH комбинаций элементов.

Подход: pre-compute все элементы (zones, fractals) на всех TF с size_filter.
Затем перебираем pairs (HTF element × LTF element) — LTF в зоне HTF.

Препараты-элементы:
  Zones: OB, FVG, RDRB на TF ∈ {1d, 4h, 1h}, фильтр size_atr<0.3 (small only)
  Levels: FH, FL на TF ∈ {1d, 4h}

Combinations:
  1. Single-element: 9 zones + 4 levels = 13 candidates
  2. Pair (HTF zone × LTF zone): zone_HTF ∈ {1d, 4h}, zone_LTF ∈ {4h, 1h}
     - LTF zone того же direction внутри HTF zone и в её активный период
  3. Pair (HTF zone × LTF fractal sweep): фрактал в зоне HTF zone, sweep на LTF

RR: 1.0, 1.5, 2.0
SL: расширенный (за zone границу + 0.3·ATR; для RDRB за trigger)

Output: топ комбинаций по R/trade с фильтром WR>=55%, n/week>=1.
Если такого нет — топ-10 по комбинированной метрике (WR + R/trade).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from itertools import product
from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR_LIST = [1.0, 1.5, 2.0]
SIZE_THRESHOLD = 0.3
HTF_LIFE_DAYS = {"1d": 30, "4h": 5, "1h": 1}

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_rdrb(df, idx):
    if idx < 2:
        return None
    a = df.iloc[idx-2]; m = df.iloc[idx-1]; c = df.iloc[idx]
    a_o, a_c, a_h, a_l = float(a["open"]), float(a["close"]), float(a["high"]), float(a["low"])
    m_c = float(m["close"])
    c_o, c_h, c_l, c_c = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    if m_c > a_h and c_l < a_h and c_c > a_h:
        zb = max(c_l, max(a_o, a_c)); zt = min(a_h, min(c_o, c_c))
        if zt <= zb: return None
        return ("LONG", zb, zt, c_l, c_h)
    if m_c < a_l and c_h > a_l and c_c < a_l:
        zb = max(a_l, max(c_o, c_c)); zt = min(c_h, min(a_o, a_c))
        if zt <= zb: return None
        return ("SHORT", zb, zt, c_l, c_h)
    return None


def is_hh(df, i):
    if i < 2 or i+2 >= len(df): return False
    h = float(df["high"].iloc[i])
    return all(h > float(df["high"].iloc[k]) for k in (i-2,i-1,i+1,i+2))


def is_ll(df, i):
    if i < 2 or i+2 >= len(df): return False
    l = float(df["low"].iloc[i])
    return all(l < float(df["low"].iloc[k]) for k in (i-2,i-1,i+1,i+2))


def collect_zones(df, kind, atr_series, size_filter=lambda s: s < SIZE_THRESHOLD,
                   tf_label=""):
    """Собрать все zones того типа на TF, с size_filter."""
    out = []
    for idx in range(2, len(df)-1):
        if kind == "OB":
            ob = detect_ob_pair(df, idx)
            if ob is None: continue
            zb, zt, dirn = ob.bottom, ob.top, ob.direction
            extra = {}
            zone_time = ob.cur_time
        elif kind == "FVG":
            f = detect_fvg(df, idx)
            if f is None: continue
            zb, zt, dirn = f.bottom, f.top, f.direction
            extra = {}
            zone_time = f.c2_time
        elif kind == "RDRB":
            r = detect_rdrb(df, idx)
            if r is None: continue
            dirn, zb, zt, tlow, thigh = r
            extra = {"trigger_low": tlow, "trigger_high": thigh}
            zone_time = df.index[idx]
        else:
            continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        size_atr = (zt - zb) / atr
        if size_filter and not size_filter(size_atr):
            continue
        out.append({"kind": kind, "tf": tf_label, "direction": dirn,
                     "bottom": zb, "top": zt, "size_atr": size_atr,
                     "atr": atr, "time": zone_time, "idx": idx, **extra})
    return out


def collect_fractals(df, atr_series, tf_label=""):
    out = []
    for i in range(2, len(df)-2):
        ll = is_ll(df, i); hh = is_hh(df, i)
        if not (ll or hh) or (ll and hh):
            continue
        atr = float(atr_series.iloc[i])
        if pd.isna(atr) or atr <= 0:
            continue
        if ll:
            level = float(df["low"].iloc[i])
            ftype = "FL"; direction = "LONG"
        else:
            level = float(df["high"].iloc[i])
            ftype = "FH"; direction = "SHORT"
        confirm_time = df.index[i+2]
        out.append({"kind": "Fractal", "ftype": ftype, "tf": tf_label,
                     "direction": direction, "level": level, "atr": atr,
                     "time": confirm_time, "idx": i})
    return out


def simulate(direction, entry, sl, tp, df_1m, start_time, timeout_days=14):
    sim = df_1m[df_1m.index >= start_time]
    if sim.empty:
        return ("no_data", 0.0)
    end_time = start_time + pd.Timedelta(days=timeout_days)
    sim = sim[sim.index <= end_time]
    if sim.empty:
        return ("no_data", 0.0)
    activation = None
    for ts, row in sim.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG" and l <= entry:
            activation = ts; break
        if direction == "SHORT" and h >= entry:
            activation = ts; break
    if activation is None:
        return ("not_filled", 0.0)
    risk = abs(entry - sl)
    if risk <= 0:
        return ("invalid", 0.0)
    sim2 = sim[sim.index >= activation]
    for ts, row in sim2.iterrows():
        h, l = float(row["high"]), float(row["low"])
        if direction == "LONG":
            if l <= sl: return ("loss", -1.0)
            if h >= tp:
                return ("win", (tp-entry)/risk)
        else:
            if h >= sl: return ("loss", -1.0)
            if l <= tp:
                return ("win", (entry-tp)/risk)
    return ("open", 0.0)


def setup_from_zone(z, sl_buf):
    """Returns (entry, sl) для zone-based setup."""
    entry = (z["bottom"] + z["top"]) / 2
    if z["kind"] == "RDRB":
        # SL за trigger
        if z["direction"] == "LONG":
            sl = z["trigger_low"] - sl_buf * z["atr"]
        else:
            sl = z["trigger_high"] + sl_buf * z["atr"]
    else:
        if z["direction"] == "LONG":
            sl = z["bottom"] - sl_buf * z["atr"]
        else:
            sl = z["top"] + sl_buf * z["atr"]
    return entry, sl


def setup_from_fractal(f, sl_buf):
    if f["direction"] == "LONG":
        sl = f["level"] - sl_buf * f["atr"]
    else:
        sl = f["level"] + sl_buf * f["atr"]
    return f["level"], sl


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def is_inside(price, b, t):
    return b <= price <= t


def main():
    print("[INFO] loading data")
    dfs = {}
    for tf in ["1d", "4h", "1h"]:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        df["atr14"] = compute_atr(df, 14)
        dfs[tf] = df
    df_1m = load_df(SYMBOL, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    print(f"  loaded 1d/4h/1h/1m")

    # Pre-compute elements
    print("[INFO] collecting elements")
    elements = {}  # key: (kind, tf), value: list of element dicts
    for tf, df in dfs.items():
        for kind in ("OB", "FVG", "RDRB"):
            elements[(kind, tf)] = collect_zones(df, kind, df["atr14"], tf_label=tf)
            print(f"  {kind}-{tf}: {len(elements[(kind,tf)])} (size<0.3·ATR)")
    for tf, df in dfs.items():
        if tf == "1h":
            continue
        elements[("Fractal", tf)] = collect_fractals(df, df["atr14"], tf_label=tf)
        print(f"  Fractal-{tf}: {len(elements[(kind,tf)])}")

    # Запуск всех candidates
    print("\n[INFO] generating candidates")
    candidates = []  # list of (name, list of setups)
    years = (dfs["1d"].index[-1] - dfs["1d"].index[0]).days / 365

    # === SINGLE ELEMENT ===
    for (kind, tf), elems in elements.items():
        if not elems:
            continue
        cname = f"{kind}-{tf}"
        for rr in RR_LIST:
            setups = []
            for e in elems:
                if kind == "Fractal":
                    entry, sl = setup_from_fractal(e, sl_buf=0.3)
                else:
                    sl_buf = 0.5 if kind == "RDRB" else 0.3
                    entry, sl = setup_from_zone(e, sl_buf=sl_buf)
                if e["direction"] == "LONG":
                    tp = entry + rr * (entry - sl)
                else:
                    tp = entry - rr * (sl - entry)
                tf_td = pd.Timedelta(tf if tf != "1d" else "1d")
                start = e["time"] + tf_td
                outcome, R = simulate(e["direction"], entry, sl, tp, df_1m, start,
                                       timeout_days=HTF_LIFE_DAYS.get(tf, 14))
                setups.append({"outcome": outcome, "R": R})
            candidates.append((f"{cname} | RR={rr}", setups, len(elems)))

    # === PAIRS: HTF zone × LTF zone (LTF inside HTF, both zones small) ===
    htf_zones = [(k, t) for (k, t) in elements.keys() if k != "Fractal" and t in ("1d", "4h")]
    ltf_zones = [(k, t) for (k, t) in elements.keys() if k != "Fractal" and t in ("4h", "1h")]
    for h_key, l_key in product(htf_zones, ltf_zones):
        if h_key == l_key:
            continue
        # HTF must be larger TF
        tf_order = {"1d": 3, "4h": 2, "1h": 1}
        if tf_order[h_key[1]] <= tf_order[l_key[1]]:
            continue
        h_elems = elements[h_key]
        l_elems = elements[l_key]
        if not h_elems or not l_elems:
            continue
        h_kind, h_tf = h_key
        l_kind, l_tf = l_key
        h_life = pd.Timedelta(days=HTF_LIFE_DAYS.get(h_tf, 5))
        cname_base = f"[{h_kind}-{h_tf}] + [{l_kind}-{l_tf}]"
        for rr in RR_LIST:
            setups = []
            l_idx_pos = 0
            for h in h_elems:
                h_start = h["time"]
                h_end = h["time"] + h_life
                # Find ltf elements в окне H + same direction + zone overlap
                for l in l_elems:
                    if l["time"] <= h_start or l["time"] > h_end:
                        continue
                    if l["direction"] != h["direction"]:
                        continue
                    if not zones_overlap(l["bottom"], l["top"], h["bottom"], h["top"]):
                        continue
                    sl_buf_l = 0.5 if l_kind == "RDRB" else 0.3
                    entry, sl = setup_from_zone(l, sl_buf=sl_buf_l)
                    if l["direction"] == "LONG":
                        tp = entry + rr * (entry - sl)
                    else:
                        tp = entry - rr * (sl - entry)
                    tf_td_l = pd.Timedelta(l_tf)
                    start = l["time"] + tf_td_l
                    outcome, R = simulate(l["direction"], entry, sl, tp, df_1m, start,
                                            timeout_days=HTF_LIFE_DAYS.get(l_tf, 5))
                    setups.append({"outcome": outcome, "R": R})
            if setups:
                candidates.append((f"{cname_base} | RR={rr}", setups, len(setups)))

    # === Aggregate ===
    print(f"\n[INFO] candidates: {len(candidates)}")
    rows = []
    for name, setups, n_total in candidates:
        if not setups:
            continue
        df_s = pd.DataFrame(setups)
        nc = (df_s["outcome"].isin(["win", "loss"])).sum()
        if nc == 0:
            continue
        closed = df_s[df_s["outcome"].isin(["win", "loss"])]
        w = (closed["outcome"] == "win").sum()
        wr = w / nc * 100
        total_R = closed["R"].sum()
        mean_R = closed["R"].mean()
        rows.append({
            "candidate": name,
            "n_total": n_total,
            "n_per_week": round(n_total / years / 52, 2),
            "n_closed": nc,
            "WR%": round(wr, 1),
            "total_R": round(total_R, 1),
            "R/trade": round(mean_R, 3),
        })
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_DIR / "grid_search_summary.csv", index=False)

    print(f"\n=== ВСЕГО комбинаций: {len(summary)} ===")

    # Filters
    pass_strict = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 1)]
    print(f"\n=== ПРОШЛИ STRICT (WR>=55, n/week>=1): {len(pass_strict)} ===")
    if len(pass_strict):
        print(pass_strict.sort_values("R/trade", ascending=False).to_string(index=False))

    pass_55 = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 0.3)]
    print(f"\n=== WR>=55, n/week>=0.3: {len(pass_55)} ===")
    if len(pass_55):
        print(pass_55.sort_values("R/trade", ascending=False).head(20).to_string(index=False))

    print("\n=== ТОП-15 по R/trade (любые n) ===")
    top_rt = summary[summary["n_per_week"] >= 0.3].sort_values("R/trade", ascending=False).head(15)
    print(top_rt.to_string(index=False))

    print("\n=== ТОП-10 по WR (n_per_week>=0.5) ===")
    top_wr = summary[summary["n_per_week"] >= 0.5].sort_values("WR%", ascending=False).head(10)
    print(top_wr.to_string(index=False))


if __name__ == "__main__":
    main()
