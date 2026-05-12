"""Этап 17: расширенный grid — добавлены sweep filter и fractal-sweep anchors.

Что нового по сравнению с etap_14 v2:

A) SWEPT-фильтр на OB-anchor (по логике strategy_1_1_1):
   LONG  OB: ob_low  < min(n1.low, n2.low)   — низ OB сняли 2 предыдущих lows
   SHORT OB: ob_high > max(n1.high, n2.high)
   Каждый OB-anchor получает 2 варианта: all / swept-only.

B) Fractal-sweep как ОТДЕЛЬНЫЙ anchor:
   1. Detect fractal: FH (high>4 neighbors) или FL (low<4 neighbors) на HTF
   2. После подтверждения (i+2) ищем sweep candle:
      FL→LONG: candle с low <= FL.level И close > FL.level
      FH→SHORT: candle с high >= FH.level И close < FH.level
   3. Anchor confirmed at sweep_candle close
   4. Anchor zone = sweep candle range (low..close для LONG / close..high для SHORT)

Anchor-confirm timing: уже исправлен (a_start = a["time"] + a_tf_td).
EMA200 lookahead: для pro filter — известная мелкая deviation, не критична.
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
import time
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR_LIST = [1.0, 1.5, 2.0]
MIN_SL_PCT = 1.0
SL_BUF_ATR = 0.3
RDRB_SL_BUF_ATR = 0.5
FRACTAL_SWEEP_LOOKAHEAD = 30  # сколько баров после фрактал-конформации искать sweep
FRACTAL_SWEEP_LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 5, "4h": 3}

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                "2h": 3, "1h": 2, "15m": 1}

OUT_DIR = Path("research/elements_study/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ANCHOR_TFS = ["1d", "12h", "6h", "4h"]
TRIGGER_TFS = ["2h", "1h", "15m"]
ALL_TFS = sorted(set(ANCHOR_TFS + TRIGGER_TFS), key=lambda t: pd.Timedelta(t))

ANCHOR_KINDS = {
    "OB":      ["1d", "12h", "6h", "4h"],
    "FVG":     ["1d", "12h", "6h", "4h"],
    "RDRB":    ["1d", "12h", "4h"],
    "FRSWEEP": ["1d", "12h", "4h"],   # NEW: fractal + sweep candle
}
TRIGGER_KINDS = {
    "OB":   ["2h", "1h"],
    "FVG":  ["2h", "1h", "15m"],
    "RDRB": ["1h"],
}
TF_ORDER = {"15m": 1, "1h": 2, "2h": 3, "4h": 4, "6h": 5, "12h": 6, "1d": 7}


# ---------------- helpers ----------------

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
        if zt <= zb:
            return None
        return ("LONG", zb, zt, c_l, c_h)
    if m_c < a_l and c_h > a_l and c_c < a_l:
        zb = max(a_l, max(c_o, c_c)); zt = min(c_h, min(a_o, a_c))
        if zt <= zb:
            return None
        return ("SHORT", zb, zt, c_l, c_h)
    return None


def is_hh_at(highs, i):
    if i < 2 or i+2 >= len(highs):
        return False
    h = highs[i]
    return h > highs[i-2] and h > highs[i-1] and h > highs[i+1] and h > highs[i+2]


def is_ll_at(lows, i):
    if i < 2 or i+2 >= len(lows):
        return False
    l = lows[i]
    return l < lows[i-2] and l < lows[i-1] and l < lows[i+1] and l < lows[i+2]


# ---------------- vectorized simulate ----------------

class FastSim:
    def __init__(self, df_1m):
        self.ts = df_1m.index.values
        self.high = df_1m["high"].to_numpy(dtype=float)
        self.low = df_1m["low"].to_numpy(dtype=float)

    def simulate(self, direction, entry, sl, tp, start_time, timeout_days):
        end_time = start_time + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(self.ts, np.datetime64(start_time.tz_localize(None) if start_time.tz else start_time))
        i1 = np.searchsorted(self.ts, np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time))
        if i1 <= i0:
            return ("no_data", 0.0)
        h = self.high[i0:i1]; l = self.low[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0:
            return ("invalid", 0.0)
        if direction == "LONG":
            act_mask = l <= entry
            if not act_mask.any():
                return ("not_filled", 0.0)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2):
                return ("open", 0.0)
            if sl_idx <= tp_idx:
                return ("loss", -1.0)
            return ("win", (tp - entry) / risk)
        else:
            act_mask = h >= entry
            if not act_mask.any():
                return ("not_filled", 0.0)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2):
                return ("open", 0.0)
            if sl_idx <= tp_idx:
                return ("loss", -1.0)
            return ("win", (entry - tp) / risk)


# ---------------- zone collection ----------------

def collect_obs(df, atr_series, tf_label):
    """Сбор OB + флаг swept_2bar."""
    out = []
    lows = df["low"].to_numpy()
    highs = df["high"].to_numpy()
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None:
            continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        # swept check: cur OB extreme против n1, n2 баров до prev OB
        # OB.cur_idx это idx, prev = idx-1. Проверяем против idx-2, idx-3.
        if idx < 3:
            swept = False
        else:
            n1_low, n2_low = lows[idx-2], lows[idx-3]
            n1_high, n2_high = highs[idx-2], highs[idx-3]
            ob_low = min(lows[idx-1], lows[idx])
            ob_high = max(highs[idx-1], highs[idx])
            if ob.direction == "LONG":
                swept = ob_low < min(n1_low, n2_low)
            else:
                swept = ob_high > max(n1_high, n2_high)
        out.append({"kind": "OB", "tf": tf_label, "direction": ob.direction,
                    "bottom": ob.bottom, "top": ob.top, "atr": atr,
                    "time": ob.cur_time, "idx": idx, "swept": swept})
    return out


def collect_fvgs_or_rdrbs(df, kind, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        if kind == "FVG":
            f = detect_fvg(df, idx)
            if f is None:
                continue
            zb, zt, dirn = f.bottom, f.top, f.direction
            extra = {}
            zone_time = f.c2_time
        elif kind == "RDRB":
            r = detect_rdrb(df, idx)
            if r is None:
                continue
            dirn, zb, zt, tlow, thigh = r
            extra = {"trigger_low": tlow, "trigger_high": thigh}
            zone_time = df.index[idx]
        else:
            continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        out.append({"kind": kind, "tf": tf_label, "direction": dirn,
                    "bottom": zb, "top": zt, "atr": atr,
                    "time": zone_time, "idx": idx, **extra})
    return out


def collect_fractal_sweeps(df, atr_series, tf_label):
    """FH/FL → ждём первую candle, которая снимает уровень и закрывается обратно.

    Anchor подтверждается = open этой sweep candle + tf (т.е. её close).
    Anchor zone = диапазон самой sweep свечи.
    """
    out = []
    lows = df["low"].to_numpy()
    highs = df["high"].to_numpy()
    closes = df["close"].to_numpy()
    times = df.index
    for i in range(2, len(df) - 2 - FRACTAL_SWEEP_LOOKAHEAD):
        is_fl = is_ll_at(lows, i)
        is_fh = is_hh_at(highs, i)
        if not (is_fl or is_fh) or (is_fl and is_fh):
            continue
        # Confirmation бар = i+2 (фрактал виден после i+2)
        confirm_idx = i + 2
        if is_fl:
            level = lows[i]
            for j in range(confirm_idx + 1, min(confirm_idx + 1 + FRACTAL_SWEEP_LOOKAHEAD, len(df) - 1)):
                if lows[j] <= level and closes[j] > level:
                    atr = float(atr_series.iloc[j])
                    if pd.isna(atr) or atr <= 0:
                        break
                    # zone — диапазон sweep candle (low..close)
                    zb = float(lows[j])
                    zt = float(closes[j])
                    if zt <= zb:
                        break
                    out.append({"kind": "FRSWEEP", "tf": tf_label, "direction": "LONG",
                                "bottom": zb, "top": zt, "atr": atr,
                                "time": times[j], "idx": j,
                                "fractal_idx": i, "level": level})
                    break
        else:
            level = highs[i]
            for j in range(confirm_idx + 1, min(confirm_idx + 1 + FRACTAL_SWEEP_LOOKAHEAD, len(df) - 1)):
                if highs[j] >= level and closes[j] < level:
                    atr = float(atr_series.iloc[j])
                    if pd.isna(atr) or atr <= 0:
                        break
                    zb = float(closes[j])
                    zt = float(highs[j])
                    if zt <= zb:
                        break
                    out.append({"kind": "FRSWEEP", "tf": tf_label, "direction": "SHORT",
                                "bottom": zb, "top": zt, "atr": atr,
                                "time": times[j], "idx": j,
                                "fractal_idx": i, "level": level})
                    break
    return out


# ---------------- setup builders ----------------

def build_setup_from_trigger(trig, sl_buf, min_sl_pct, rr):
    entry = (trig["bottom"] + trig["top"]) / 2
    atr = trig["atr"]; direction = trig["direction"]
    if trig["kind"] == "RDRB":
        if direction == "LONG":
            atr_sl = trig["trigger_low"] - sl_buf * atr
        else:
            atr_sl = trig["trigger_high"] + sl_buf * atr
    else:
        if direction == "LONG":
            atr_sl = trig["bottom"] - sl_buf * atr
        else:
            atr_sl = trig["top"] + sl_buf * atr
    min_dist = entry * min_sl_pct / 100
    if direction == "LONG":
        pct_sl = entry - min_dist
        sl = min(atr_sl, pct_sl)
    else:
        pct_sl = entry + min_dist
        sl = max(atr_sl, pct_sl)
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    if direction == "LONG":
        tp = entry + rr * risk
    else:
        tp = entry - rr * risk
    return entry, sl, tp


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


# ---------------- main grid ----------------

def main():
    t0 = time.time()
    print(f"[INFO] loading data START={START_DATE}")
    dfs = {}
    for tf in ALL_TFS:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        df["atr14"] = compute_atr(df, 14)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        dfs[tf] = df
        print(f"  {tf}: {len(df)} bars")
    df_1m = load_df(SYMBOL, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    sim = FastSim(df_1m)
    years = (dfs["1d"].index[-1] - dfs["1d"].index[0]).days / 365
    print(f"  years coverage: {years:.2f}")

    # ----- collect anchors -----
    print("\n[INFO] collecting anchors")
    anchors = {}
    for tf in ANCHOR_KINDS["OB"]:
        zs = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
        anchors[("OB", tf)] = zs
        n_swept = sum(1 for z in zs if z["swept"])
        print(f"  OB-{tf}: {len(zs)} (swept: {n_swept})")
    for tf in ANCHOR_KINDS["FVG"]:
        zs = collect_fvgs_or_rdrbs(dfs[tf], "FVG", dfs[tf]["atr14"], tf)
        anchors[("FVG", tf)] = zs
        print(f"  FVG-{tf}: {len(zs)}")
    for tf in ANCHOR_KINDS["RDRB"]:
        zs = collect_fvgs_or_rdrbs(dfs[tf], "RDRB", dfs[tf]["atr14"], tf)
        anchors[("RDRB", tf)] = zs
        print(f"  RDRB-{tf}: {len(zs)}")
    for tf in ANCHOR_KINDS["FRSWEEP"]:
        zs = collect_fractal_sweeps(dfs[tf], dfs[tf]["atr14"], tf)
        anchors[("FRSWEEP", tf)] = zs
        print(f"  FRSWEEP-{tf}: {len(zs)}")

    triggers = {}
    for kind, tfs in TRIGGER_KINDS.items():
        for tf in tfs:
            zs = collect_fvgs_or_rdrbs(dfs[tf], kind, dfs[tf]["atr14"], tf) if kind in ("FVG", "RDRB") \
                else collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
            triggers[(kind, tf)] = zs
            print(f"  trigger {kind}-{tf}: {len(zs)}")
    print(f"[TIME] anchors+triggers in {time.time()-t0:.1f}s")

    # ----- build all candidate combos -----
    combos = []  # list of (anchor_key, swept_variant, trigger_key)
    for a_key in anchors.keys():
        a_kind, a_tf = a_key
        # variations: 'all'  + 'swept' (only for OB)
        anchor_variants = ["all"]
        if a_kind == "OB":
            anchor_variants.append("swept")
        for av in anchor_variants:
            for t_key in triggers.keys():
                t_kind, t_tf = t_key
                if TF_ORDER[a_tf] <= TF_ORDER[t_tf]:
                    continue
                combos.append((a_key, av, t_key))
    print(f"\n[INFO] valid combos: {len(combos)}")

    # ----- evaluate each combo × RR × pro/all -----
    results = []
    for ci, (a_key, av, t_key) in enumerate(combos, 1):
        a_kind, a_tf = a_key
        t_kind, t_tf = t_key
        a_list_full = anchors[a_key]
        if av == "swept":
            a_list = [a for a in a_list_full if a.get("swept")]
        else:
            a_list = a_list_full
        if not a_list:
            continue
        t_list = triggers[t_key]
        if not t_list:
            continue

        a_tf_td = pd.Timedelta(a_tf)
        # для FRSWEEP анкора жизнь короче — ловим момент
        if a_kind == "FRSWEEP":
            a_life = pd.Timedelta(days=FRACTAL_SWEEP_LIFE_DAYS.get(a_tf, 5))
        else:
            a_life = pd.Timedelta(days=TF_LIFE_DAYS.get(a_tf, 5))
        df_t = dfs[t_tf]
        ema_arr = df_t["ema200"].to_numpy()
        close_arr = df_t["close"].to_numpy()

        t_sorted = sorted(t_list, key=lambda x: x["time"])
        base_setups = []
        t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                             for t in t_sorted])
        for a in a_list:
            a_start = a["time"] + a_tf_td   # cur_close
            a_end = a["time"] + a_life
            if a_end <= a_start:
                continue
            i_start = np.searchsorted(t_times,
                                       np.datetime64(a_start.tz_localize(None) if a_start.tz else a_start),
                                       side="right")
            i_end = np.searchsorted(t_times,
                                     np.datetime64(a_end.tz_localize(None) if a_end.tz else a_end),
                                     side="right")
            for ti in range(i_start, i_end):
                t = t_sorted[ti]
                if t["direction"] != a["direction"]:
                    continue
                if not zones_overlap(t["bottom"], t["top"], a["bottom"], a["top"]):
                    continue
                em = float(ema_arr[t["idx"]])
                cl = float(close_arr[t["idx"]])
                pro = ((t["direction"] == "LONG" and cl > em) or
                       (t["direction"] == "SHORT" and cl < em))
                base_setups.append({"trigger": t, "pro": pro})
                break  # dedup first
        if not base_setups:
            continue
        for rr in RR_LIST:
            for filt_name, filt_pred in [("all", lambda s: True),
                                           ("pro", lambda s: s["pro"])]:
                rows_eval = []
                for s in base_setups:
                    if not filt_pred(s):
                        continue
                    trig = s["trigger"]
                    sl_buf = RDRB_SL_BUF_ATR if trig["kind"] == "RDRB" else SL_BUF_ATR
                    tup = build_setup_from_trigger(trig, sl_buf, MIN_SL_PCT, rr)
                    if tup is None:
                        continue
                    entry, sl, tp = tup
                    start = trig["time"] + pd.Timedelta(t_tf)
                    outcome, R = sim.simulate(trig["direction"], entry, sl, tp,
                                              start, TF_LIFE_DAYS.get(t_tf, 5))
                    rows_eval.append({"outcome": outcome, "R": R})
                if not rows_eval:
                    continue
                df_e = pd.DataFrame(rows_eval)
                closed = df_e[df_e["outcome"].isin(["win", "loss"])]
                nc = len(closed)
                n_total = len(df_e)
                if nc == 0:
                    continue
                w = (closed["outcome"] == "win").sum()
                results.append({
                    "anchor": f"{a_kind}-{a_tf}",
                    "anchor_filter": av,
                    "trigger": f"{t_kind}-{t_tf}",
                    "filter": filt_name,
                    "RR": rr,
                    "n_total": n_total,
                    "n_per_week": round(n_total / years / 52, 2),
                    "n_closed": nc,
                    "WR%": round(w / nc * 100, 1),
                    "total_R": round(closed["R"].sum(), 1),
                    "R/trade": round(closed["R"].mean(), 3),
                })
        if ci % 20 == 0 or ci == len(combos):
            print(f"  [{ci}/{len(combos)}] done | elapsed={time.time()-t0:.0f}s")

    summary = pd.DataFrame(results)
    summary.to_csv(OUT_DIR / "etap17_grid.csv", index=False)
    print(f"\n[TIME] total {time.time()-t0:.1f}s, candidates={len(summary)}")

    print("\n=== FILTER: WR>=55, n/week>=1, sorted by total_R ===")
    p1 = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 1)]
    if len(p1):
        print(p1.sort_values("total_R", ascending=False).head(25).to_string(index=False))
    else:
        print("  empty")

    print("\n=== FILTER: WR>=55, n/week>=0.5, top-25 by total_R ===")
    p2 = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 0.5)]
    if len(p2):
        print(p2.sort_values("total_R", ascending=False).head(25).to_string(index=False))

    print("\n=== TOP-15 by R/trade (n/week>=0.5) ===")
    rt = summary[summary["n_per_week"] >= 0.5]
    if len(rt):
        print(rt.sort_values("R/trade", ascending=False).head(15).to_string(index=False))

    print("\n=== ONLY anchor_filter=swept (WR>=55, n/week>=0.3) ===")
    sw = summary[(summary["anchor_filter"] == "swept") &
                 (summary["WR%"] >= 55) & (summary["n_per_week"] >= 0.3)]
    if len(sw):
        print(sw.sort_values("R/trade", ascending=False).head(15).to_string(index=False))
    else:
        print("  empty")

    print("\n=== ONLY anchor_kind=FRSWEEP (WR>=50, n/week>=0.3) ===")
    fr = summary[(summary["anchor"].str.startswith("FRSWEEP")) &
                 (summary["WR%"] >= 50) & (summary["n_per_week"] >= 0.3)]
    if len(fr):
        print(fr.sort_values("R/trade", ascending=False).head(15).to_string(index=False))
    else:
        print("  empty")


if __name__ == "__main__":
    main()
