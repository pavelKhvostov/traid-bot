"""Этап 22: расширенный grid с НОВЫМИ типами комбинаций.

Что НЕ было исследовано в etap_14/17/18:

A) SAME-TF ZONE CONFLUENCE
   OB-htf + FVG-htf same direction overlapping zone (на одном TF)
   Anchor = пересечение зон. Подтверждается на max(OB_confirm, FVG_confirm).
   Trigger: LTF FVG.

B) HTF ZONE + LTF FRACTAL-LEVEL TRIGGER (single fractal, не sweep)
   Anchor: OB/FVG/RDRB-{1d,12h,6h,4h}
   Trigger: FH/FL свеча на LTF (1h/2h) с уровнем внутри anchor zone, same direction.

C) TRIPLE-TF STACK
   Anchor: OB-1d, Mid-zone: OB/FVG-{4h,2h} в зоне anchor, Trigger: FVG-1h в зоне mid.
   Каскад: HTF → MID → LTF.

D) HTF FRACTAL RANGE AS ANCHOR (без sweep, как чистая фрактал-свеча)
   Anchor zone = candle range диапазон [low, high] фрактал-свечи.
   Trigger: LTF FVG.

E) ANTI-CONFLUENCE (опционально, контрольный)
   OB-htf anchor БЕЗ overlap с FVG-htf той же направления — одиночка.

Все: anchor-confirm fix, min_sl=1%, dedup first, RR variations.
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
RR_LIST = [1.0, 1.5, 2.0, 2.5]
MIN_SL_PCT = 1.0
SL_BUF_ATR = 0.3
RDRB_SL_BUF_ATR = 0.5

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                "2h": 3, "1h": 2, "15m": 1}
FRACT_LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 5, "4h": 3}

OUT_DIR = Path("research/elements_study/output")

ANCHOR_TFS = ["1d", "12h", "6h", "4h"]
TRIGGER_TFS = ["2h", "1h", "15m"]
ALL_TFS = sorted(set(ANCHOR_TFS + TRIGGER_TFS), key=lambda t: pd.Timedelta(t))
TF_ORDER = {"15m": 1, "1h": 2, "2h": 3, "4h": 4, "6h": 5, "12h": 6, "1d": 7}


# ---------------- helpers ----------------

def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_rdrb(df, idx):
    if idx < 2: return None
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
        if i1 <= i0: return ("no_data", 0.0)
        h = self.high[i0:i1]; l = self.low[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0: return ("invalid", 0.0)
        if direction == "LONG":
            act_mask = l <= entry
            if not act_mask.any(): return ("not_filled", 0.0)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0)
            if sl_idx <= tp_idx: return ("loss", -1.0)
            return ("win", (tp - entry) / risk)
        else:
            act_mask = h >= entry
            if not act_mask.any(): return ("not_filled", 0.0)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0)
            if sl_idx <= tp_idx: return ("loss", -1.0)
            return ("win", (entry - tp) / risk)


# ---------------- collectors ----------------

def collect_obs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"kind": "OB", "tf": tf_label, "direction": ob.direction,
                    "bottom": ob.bottom, "top": ob.top, "atr": atr,
                    "time": ob.cur_time, "idx": idx})
    return out


def collect_fvgs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"kind": "FVG", "tf": tf_label, "direction": f.direction,
                    "bottom": f.bottom, "top": f.top, "atr": atr,
                    "time": f.c2_time, "idx": idx})
    return out


def collect_rdrbs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        r = detect_rdrb(df, idx)
        if r is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        dirn, zb, zt, tlow, thigh = r
        out.append({"kind": "RDRB", "tf": tf_label, "direction": dirn,
                    "bottom": zb, "top": zt, "atr": atr,
                    "time": df.index[idx], "idx": idx,
                    "trigger_low": tlow, "trigger_high": thigh})
    return out


def collect_fractals_with_range(df, atr_series, tf_label):
    """FH/FL с zone = [low, high] candle range (для D)."""
    out = []
    lows = df["low"].to_numpy(); highs = df["high"].to_numpy()
    times = df.index
    for i in range(2, len(df) - 2):
        h = highs[i]; l = lows[i]
        is_fl = (l < lows[i-2] and l < lows[i-1] and
                 l < lows[i+1] and l < lows[i+2])
        is_fh = (h > highs[i-2] and h > highs[i-1] and
                 h > highs[i+1] and h > highs[i+2])
        if not (is_fl or is_fh) or (is_fl and is_fh): continue
        atr = float(atr_series.iloc[i])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"kind": "FRACT", "tf": tf_label,
                    "direction": "LONG" if is_fl else "SHORT",
                    "bottom": float(l), "top": float(h), "atr": atr,
                    "time": times[i], "idx": i,
                    "level": float(l) if is_fl else float(h)})
    return out


def collect_fractals_as_trigger(df, atr_series, tf_label):
    """FH/FL свечи для использования как TRIGGER. Time = candle confirm = i+2 close."""
    out = []
    lows = df["low"].to_numpy(); highs = df["high"].to_numpy()
    closes = df["close"].to_numpy()
    times = df.index
    for i in range(2, len(df) - 2):
        h = highs[i]; l = lows[i]
        is_fl = (l < lows[i-2] and l < lows[i-1] and
                 l < lows[i+1] and l < lows[i+2])
        is_fh = (h > highs[i-2] and h > highs[i-1] and
                 h > highs[i+1] and h > highs[i+2])
        if not (is_fl or is_fh) or (is_fl and is_fh): continue
        atr = float(atr_series.iloc[i])
        if pd.isna(atr) or atr <= 0: continue
        # entry на уровне фрактала, zone size = atr * 0.1 для целей entry/SL
        if is_fl:
            level = l
            direction = "LONG"
        else:
            level = h
            direction = "SHORT"
        # confirmed at close of i+2
        confirm_time = times[i+2]
        out.append({"kind": "FRACT_TRIG", "tf": tf_label, "direction": direction,
                    "bottom": float(level - 0.1 * atr) if direction == "LONG" else float(level),
                    "top": float(level) if direction == "LONG" else float(level + 0.1 * atr),
                    "atr": atr, "time": confirm_time, "idx": i+2, "level": float(level)})
    return out


# ---------------- A: same-TF zone confluence ----------------

def collect_zone_confluence(zones1, zones2, max_offset_bars=10):
    """Для каждого z1 ищем z2 того же direction с zone overlap в окне ±max_offset_bars индекса.
    Anchor = overlap zone, time = max(z1.time, z2.time)."""
    out = []
    z2_sorted = sorted(zones2, key=lambda x: x["idx"])
    z2_idxs = np.array([z["idx"] for z in z2_sorted])
    for z1 in zones1:
        i_lo = np.searchsorted(z2_idxs, z1["idx"] - max_offset_bars, side="left")
        i_hi = np.searchsorted(z2_idxs, z1["idx"] + max_offset_bars, side="right")
        for ti in range(i_lo, i_hi):
            z2 = z2_sorted[ti]
            if z2["direction"] != z1["direction"]: continue
            zb = max(z1["bottom"], z2["bottom"])
            zt = min(z1["top"], z2["top"])
            if zt <= zb: continue
            out.append({"kind": f"{z1['kind']}+{z2['kind']}", "tf": z1["tf"],
                        "direction": z1["direction"],
                        "bottom": zb, "top": zt, "atr": z1["atr"],
                        "time": max(z1["time"], z2["time"])})
    return out


# ---------------- C: triple-TF stack ----------------

def collect_triple_stack(htf_anchors, mid_zones, htf_tf, mid_tf):
    """Для каждого htf_anchor ищем mid_zone в его зоне, same direction.
    Возвращает list of mid_zones с пометкой что они сидят в HTF anchor."""
    out = []
    htf_tf_td = pd.Timedelta(htf_tf)
    mid_sorted = sorted(mid_zones, key=lambda x: x["time"])
    mid_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                           for z in mid_sorted])
    for a in htf_anchors:
        a_start = a["time"] + htf_tf_td  # confirmed at cur_close
        a_life = pd.Timedelta(days=TF_LIFE_DAYS.get(htf_tf, 5))
        a_end = a["time"] + a_life
        if a_end <= a_start: continue
        i_start = np.searchsorted(mid_times,
                                    np.datetime64(a_start.tz_localize(None) if a_start.tz else a_start),
                                    side="right")
        i_end = np.searchsorted(mid_times,
                                  np.datetime64(a_end.tz_localize(None) if a_end.tz else a_end),
                                  side="right")
        for ti in range(i_start, i_end):
            m = mid_sorted[ti]
            if m["direction"] != a["direction"]: continue
            if not (m["top"] >= a["bottom"] and m["bottom"] <= a["top"]):
                continue
            # mid zone restricted by HTF anchor (берём intersection)
            zb = max(m["bottom"], a["bottom"])
            zt = min(m["top"], a["top"])
            if zt <= zb: continue
            # confirmed at mid cur_close
            mid_confirm = m["time"] + pd.Timedelta(mid_tf)
            out.append({"kind": f"OB-{htf_tf}+{m['kind']}-{mid_tf}",
                        "tf": mid_tf, "direction": m["direction"],
                        "bottom": zb, "top": zt, "atr": m["atr"],
                        "time": mid_confirm})
            break  # dedup: первый mid в HTF
    return out


# ---------------- setup builder ----------------

def build_setup(trig, sl_buf, min_sl_pct, rr):
    entry = (trig["bottom"] + trig["top"]) / 2
    atr = trig["atr"]; direction = trig["direction"]
    if trig["kind"] == "RDRB":
        if direction == "LONG":
            atr_sl = trig["trigger_low"] - sl_buf * atr
        else:
            atr_sl = trig["trigger_high"] + sl_buf * atr
    elif trig.get("kind") == "FRACT_TRIG":
        # SL за уровнем фрактала
        if direction == "LONG":
            atr_sl = trig["level"] - sl_buf * atr
        else:
            atr_sl = trig["level"] + sl_buf * atr
        entry = trig["level"]
    else:
        if direction == "LONG":
            atr_sl = trig["bottom"] - sl_buf * atr
        else:
            atr_sl = trig["top"] + sl_buf * atr
    min_dist = entry * min_sl_pct / 100
    if direction == "LONG":
        sl = min(atr_sl, entry - min_dist)
    else:
        sl = max(atr_sl, entry + min_dist)
    risk = abs(entry - sl)
    if risk <= 0: return None
    if direction == "LONG":
        tp = entry + rr * risk
    else:
        tp = entry - rr * risk
    return entry, sl, tp


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


# ---------------- evaluate combo ----------------

def evaluate_combo(anchors, triggers, dfs, sim, t_tf, anchor_confirm_offset,
                    rr, filt, life_days):
    """Generic: anchor (с уже выставленным time = confirm time) + LTF triggers."""
    if not anchors or not triggers: return None
    a_life = pd.Timedelta(days=life_days)
    df_t = dfs[t_tf]
    ema_arr = df_t["ema200"].to_numpy()
    close_arr = df_t["close"].to_numpy()
    t_sorted = sorted(triggers, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                         for t in t_sorted])
    rows = []
    for a in anchors:
        a_start = a["time"] + anchor_confirm_offset
        a_end = a["time"] + a_life
        if a_end <= a_start: continue
        i_start = np.searchsorted(t_times,
                                   np.datetime64(a_start.tz_localize(None) if a_start.tz else a_start),
                                   side="right")
        i_end = np.searchsorted(t_times,
                                 np.datetime64(a_end.tz_localize(None) if a_end.tz else a_end),
                                 side="right")
        for ti in range(i_start, i_end):
            t = t_sorted[ti]
            if t["direction"] != a["direction"]: continue
            if not zones_overlap(t["bottom"], t["top"], a["bottom"], a["top"]):
                continue
            em = float(ema_arr[t["idx"]]) if t.get("idx", -1) >= 0 else 0
            cl = float(close_arr[t["idx"]]) if t.get("idx", -1) >= 0 else 0
            pro = ((t["direction"] == "LONG" and cl > em) or
                   (t["direction"] == "SHORT" and cl < em))
            if filt == "pro" and not pro: continue
            sl_buf = (RDRB_SL_BUF_ATR if t["kind"] == "RDRB" else SL_BUF_ATR)
            tup = build_setup(t, sl_buf, MIN_SL_PCT, rr)
            if tup is None: continue
            entry, sl, tp = tup
            start = t["time"] + pd.Timedelta(t_tf)
            outcome, R = sim.simulate(t["direction"], entry, sl, tp,
                                       start, TF_LIFE_DAYS.get(t_tf, 5))
            rows.append({"outcome": outcome, "R": R})
            break
    if not rows: return None
    df_e = pd.DataFrame(rows)
    closed = df_e[df_e["outcome"].isin(["win", "loss"])]
    if closed.empty: return None
    w = (closed["outcome"] == "win").sum()
    return {"n_total": len(df_e), "n_closed": len(closed),
            "WR": round(w/len(closed)*100, 1),
            "total_R": round(closed["R"].sum(), 1),
            "R_tr": round(closed["R"].mean(), 3)}


# ---------------- main ----------------

def main():
    t0 = time.time()
    print("[INFO] loading data")
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
    print(f"  years: {years:.2f}")

    # ----- collect base zones -----
    print("\n[INFO] collecting base zones")
    obs = {}; fvgs = {}; rdrbs = {}; fracts = {}
    for tf in ALL_TFS:
        obs[tf] = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
        fvgs[tf] = collect_fvgs(dfs[tf], dfs[tf]["atr14"], tf)
        if tf in ANCHOR_TFS:
            rdrbs[tf] = collect_rdrbs(dfs[tf], dfs[tf]["atr14"], tf)
            fracts[tf] = collect_fractals_with_range(dfs[tf], dfs[tf]["atr14"], tf)
        print(f"  {tf}: OB={len(obs[tf])}, FVG={len(fvgs[tf])}", end="")
        if tf in ANCHOR_TFS:
            print(f", RDRB={len(rdrbs[tf])}, FRACT={len(fracts[tf])}")
        else:
            print()

    # LTF fractal triggers (для B)
    fract_triggers = {}
    for tf in ["2h", "1h"]:
        fract_triggers[tf] = collect_fractals_as_trigger(dfs[tf], dfs[tf]["atr14"], tf)
        print(f"  FRACT_TRIG-{tf}: {len(fract_triggers[tf])}")

    print(f"[TIME] collected in {time.time()-t0:.1f}s")

    # ----- run combinations -----
    results = []

    def add(family, anchor_label, trigger_label, filt, rr, r):
        if r is None: return
        results.append({
            "family": family, "anchor": anchor_label, "trigger": trigger_label,
            "filter": filt, "RR": rr,
            "n_total": r["n_total"], "n_per_week": round(r["n_total"]/years/52, 2),
            "n_closed": r["n_closed"], "WR%": r["WR"],
            "total_R": r["total_R"], "R/trade": r["R_tr"],
        })

    # ===== A: SAME-TF ZONE CONFLUENCE =====
    print("\n[A] OB+FVG same-TF confluence")
    for tf in ANCHOR_TFS:
        confl = collect_zone_confluence(obs[tf], fvgs[tf], max_offset_bars=10)
        # confirmed: max(OB cur_close, FVG c2_close) — anchor.time уже max(z1, z2),
        # offset нужен дополнительно: для OB это +tf, для FVG это +tf тоже.
        # Чтобы быть честным используем max anchor.time + tf
        offset = pd.Timedelta(tf)
        life = TF_LIFE_DAYS.get(tf, 5)
        for t_tf in [t for t in TRIGGER_TFS if TF_ORDER[tf] > TF_ORDER[t]]:
            for rr in RR_LIST:
                for filt in ("all", "pro"):
                    r = evaluate_combo(confl, fvgs[t_tf], dfs, sim, t_tf,
                                         offset, rr, filt, life)
                    add("A_OB+FVG_confl", f"OB+FVG-{tf}", f"FVG-{t_tf}", filt, rr, r)
        print(f"  OB+FVG-{tf}: {len(confl)} confluence anchors")

    # ===== B: HTF ZONE + LTF FRACTAL-LEVEL TRIGGER =====
    print("\n[B] HTF zone + LTF FRACT-trigger")
    for a_tf in ANCHOR_TFS:
        for a_kind, a_list in [("OB", obs[a_tf]), ("FVG", fvgs[a_tf]),
                                ("RDRB", rdrbs[a_tf])]:
            offset = pd.Timedelta(a_tf)
            life = TF_LIFE_DAYS.get(a_tf, 5)
            for t_tf in ["2h", "1h"]:
                if TF_ORDER[a_tf] <= TF_ORDER[t_tf]: continue
                for rr in RR_LIST:
                    for filt in ("all", "pro"):
                        r = evaluate_combo(a_list, fract_triggers[t_tf], dfs, sim, t_tf,
                                             offset, rr, filt, life)
                        add("B_zone+FRACTtr", f"{a_kind}-{a_tf}",
                              f"FRACT_TRIG-{t_tf}", filt, rr, r)

    # ===== C: TRIPLE-TF STACK =====
    print("\n[C] Triple stack OB-1d -> mid -> FVG-1h")
    for mid_tf in ["4h", "2h"]:
        for mid_kind, mid_list in [("OB", obs[mid_tf]), ("FVG", fvgs[mid_tf])]:
            triple = collect_triple_stack(obs["1d"], mid_list, "1d", mid_tf)
            offset = pd.Timedelta(0)  # уже учтено в triple time
            life = TF_LIFE_DAYS.get(mid_tf, 3)
            for t_tf in [t for t in TRIGGER_TFS if TF_ORDER[mid_tf] > TF_ORDER[t]]:
                for rr in RR_LIST:
                    for filt in ("all", "pro"):
                        r = evaluate_combo(triple, fvgs[t_tf], dfs, sim, t_tf,
                                             offset, rr, filt, life)
                        add("C_triple", f"OB-1d+{mid_kind}-{mid_tf}",
                              f"FVG-{t_tf}", filt, rr, r)
            print(f"  OB-1d -> {mid_kind}-{mid_tf}: {len(triple)} mid anchors")

    # Также OB-12h triple stack
    for mid_tf in ["4h", "2h"]:
        for mid_kind, mid_list in [("OB", obs[mid_tf]), ("FVG", fvgs[mid_tf])]:
            triple = collect_triple_stack(obs["12h"], mid_list, "12h", mid_tf)
            offset = pd.Timedelta(0)
            life = TF_LIFE_DAYS.get(mid_tf, 3)
            for t_tf in [t for t in TRIGGER_TFS if TF_ORDER[mid_tf] > TF_ORDER[t]]:
                for rr in RR_LIST:
                    for filt in ("all", "pro"):
                        r = evaluate_combo(triple, fvgs[t_tf], dfs, sim, t_tf,
                                             offset, rr, filt, life)
                        add("C_triple", f"OB-12h+{mid_kind}-{mid_tf}",
                              f"FVG-{t_tf}", filt, rr, r)
            print(f"  OB-12h -> {mid_kind}-{mid_tf}: {len(triple)}")

    # ===== D: HTF FRACTAL RANGE AS ANCHOR =====
    print("\n[D] HTF FRACT range as anchor + LTF FVG/OB")
    for a_tf in ANCHOR_TFS:
        # confirmed at fractal_time + 3*tf (i+2 close)
        offset = 3 * pd.Timedelta(a_tf)
        life = FRACT_LIFE_DAYS.get(a_tf, 5)
        for t_kind, t_dict in [("FVG", fvgs), ("OB", obs)]:
            for t_tf in TRIGGER_TFS:
                if TF_ORDER[a_tf] <= TF_ORDER[t_tf]: continue
                if t_kind == "OB" and t_tf == "15m": continue  # OB-15m не в triggers
                for rr in RR_LIST:
                    for filt in ("all", "pro"):
                        r = evaluate_combo(fracts[a_tf], t_dict[t_tf], dfs, sim, t_tf,
                                             offset, rr, filt, life)
                        add("D_FRACT_range", f"FRACT-{a_tf}",
                              f"{t_kind}-{t_tf}", filt, rr, r)

    # ----- save and report -----
    summary = pd.DataFrame(results)
    summary.to_csv(OUT_DIR / "etap22_grid.csv", index=False)
    print(f"\n[TIME] total {time.time()-t0:.1f}s, candidates={len(summary)}")

    print("\n" + "="*70)
    print("GLOBAL: WR>=55, n/wk>=1, sorted by total_R")
    print("="*70)
    g = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 1)]
    if len(g):
        print(g.sort_values("total_R", ascending=False).head(20).to_string(index=False))
    else:
        print("  empty")

    print("\n" + "="*70)
    print("GLOBAL TOP-15 by R/trade (n/wk>=0.5)")
    print("="*70)
    g2 = summary[summary["n_per_week"] >= 0.5]
    print(g2.sort_values("R/trade", ascending=False).head(15).to_string(index=False))

    print("\n" + "="*70)
    print("BY FAMILY: лучшие в каждом")
    print("="*70)
    for fam in summary["family"].unique():
        sub = summary[summary["family"] == fam]
        sub_pass = sub[(sub["WR%"] >= 50) & (sub["n_per_week"] >= 0.3)]
        if not sub_pass.empty:
            top = sub_pass.sort_values("total_R", ascending=False).head(5)
            print(f"\n--- {fam} ---")
            print(top.to_string(index=False))


if __name__ == "__main__":
    main()
