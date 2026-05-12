"""Этап 18: глубокое исследование фракталов в комбинации с нашими элементами.

4 семейства тестов:

A) FRACT-only anchor (БЕЗ sweep):
   FH/FL на HTF, zone = диапазон фрактал-свечи [low, high].
   Direction LONG (FL) / SHORT (FH).
   Anchor confirmed at fractal_time + 3*tf (i+2 close).

B) FRSWEEP расширен на 6h (был только 1d/12h/4h).
   Логика как в etap_17/etap_15.

C) HTF anchor × LTF fractal-sweep TRIGGER (новая комбинация):
   Anchor: OB-{1d, 12h, 6h, 4h}, no swept-фильтр
   Trigger: на LTF (1h, 2h) — фрактал i±2 → sweep candle (см. FRSWEEP)
   В отличие от обычного trigger (FVG/OB), это «снятие LTF фрактала
   внутри HTF OB-зоны». Concept: HTF дает зону, LTF дает «реальный sweep».

D) Multi-TF fractal CONFLUENCE anchor:
   Фрактал на 1d + фрактал на 4h ТОГО ЖЕ направления, levels близки
   (within 1×ATR_4h proximity), активны одновременно.
   Anchor zone = пересечение фрактал-свеч диапазонов (или small union).
   Trigger: LTF FVG/OB.

Все: min_sl=1%, anchor-confirm fix, dedup first qualifying trigger.
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
FRACTAL_SWEEP_LOOKAHEAD = 30   # баров после i+2 искать sweep candle

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                "2h": 3, "1h": 2, "15m": 1}
FRACT_LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 5, "4h": 3}
FRSWEEP_LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 5, "4h": 3}

OUT_DIR = Path("research/elements_study/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

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


# ---------------- collectors: zones ----------------

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


def collect_fvgs_or_rdrbs(df, kind, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        if kind == "FVG":
            f = detect_fvg(df, idx)
            if f is None: continue
            zb, zt, dirn = f.bottom, f.top, f.direction
            extra = {}; zone_time = f.c2_time
        elif kind == "RDRB":
            r = detect_rdrb(df, idx)
            if r is None: continue
            dirn, zb, zt, tlow, thigh = r
            extra = {"trigger_low": tlow, "trigger_high": thigh}
            zone_time = df.index[idx]
        else: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"kind": kind, "tf": tf_label, "direction": dirn,
                    "bottom": zb, "top": zt, "atr": atr,
                    "time": zone_time, "idx": idx, **extra})
    return out


# ---------------- collectors: fractals ----------------

def collect_fractals(df, atr_series, tf_label):
    """Чистые фракталы FH/FL по правилу Bill Williams i±2.
    Anchor zone = диапазон фрактал-свечи [low, high].
    Anchor confirmed at i+2 close = fractal_time + 3*tf."""
    out = []
    lows = df["low"].to_numpy()
    highs = df["high"].to_numpy()
    times = df.index
    for i in range(2, len(df) - 2):
        h = highs[i]; l = lows[i]
        is_fl = (l < lows[i-2] and l < lows[i-1] and
                 l < lows[i+1] and l < lows[i+2])
        is_fh = (h > highs[i-2] and h > highs[i-1] and
                 h > highs[i+1] and h > highs[i+2])
        if not (is_fl or is_fh) or (is_fl and is_fh):
            continue
        atr = float(atr_series.iloc[i])
        if pd.isna(atr) or atr <= 0: continue
        if is_fl:
            direction = "LONG"; level = l
        else:
            direction = "SHORT"; level = h
        out.append({"kind": "FRACT", "tf": tf_label, "direction": direction,
                    "bottom": float(l), "top": float(h), "atr": atr,
                    "time": times[i], "idx": i, "level": level})
    return out


def collect_frsweep(df, atr_series, tf_label, lookahead=FRACTAL_SWEEP_LOOKAHEAD):
    """FH/FL → ждём первую sweep candle и берём её диапазон как zone.
    Anchor confirmed at sweep_candle close = sweep_time + tf."""
    out = []
    lows = df["low"].to_numpy(); highs = df["high"].to_numpy()
    closes = df["close"].to_numpy(); times = df.index
    for i in range(2, len(df) - 2 - lookahead):
        h = highs[i]; l = lows[i]
        is_fl = (l < lows[i-2] and l < lows[i-1] and
                 l < lows[i+1] and l < lows[i+2])
        is_fh = (h > highs[i-2] and h > highs[i-1] and
                 h > highs[i+1] and h > highs[i+2])
        if not (is_fl or is_fh) or (is_fl and is_fh): continue
        confirm_idx = i + 2
        if is_fl:
            level = l
            for j in range(confirm_idx + 1, min(confirm_idx + 1 + lookahead, len(df) - 1)):
                if lows[j] <= level and closes[j] > level:
                    atr = float(atr_series.iloc[j])
                    if pd.isna(atr) or atr <= 0: break
                    zb = float(lows[j]); zt = float(closes[j])
                    if zt <= zb: break
                    out.append({"kind": "FRSWEEP", "tf": tf_label, "direction": "LONG",
                                "bottom": zb, "top": zt, "atr": atr,
                                "time": times[j], "idx": j, "level": level})
                    break
        else:
            level = h
            for j in range(confirm_idx + 1, min(confirm_idx + 1 + lookahead, len(df) - 1)):
                if highs[j] >= level and closes[j] < level:
                    atr = float(atr_series.iloc[j])
                    if pd.isna(atr) or atr <= 0: break
                    zb = float(closes[j]); zt = float(highs[j])
                    if zt <= zb: break
                    out.append({"kind": "FRSWEEP", "tf": tf_label, "direction": "SHORT",
                                "bottom": zb, "top": zt, "atr": atr,
                                "time": times[j], "idx": j, "level": level})
                    break
    return out


def collect_multi_fractal_confluence(frs1d, frs4h):
    """Multi-TF confluence: для каждого FRACT-1d ищем FRACT-4h того же направления
    с levels близки (within 1×ATR_4h) И активным одновременно (4h фрактал
    подтвержден в окне 14 дней после 1d).
    Anchor confirmed at later of (1d_confirm, 4h_confirm)."""
    out = []
    frs4h_sorted = sorted(frs4h, key=lambda x: x["time"])
    f4h_times = np.array([np.datetime64(f["time"].tz_localize(None) if f["time"].tz else f["time"])
                           for f in frs4h_sorted])
    for f1 in frs1d:
        f1_confirm = f1["time"] + 3 * pd.Timedelta("1d")
        win_end = f1["time"] + pd.Timedelta(days=14)
        i_start = np.searchsorted(f4h_times,
                                    np.datetime64(f1_confirm.tz_localize(None) if f1_confirm.tz else f1_confirm),
                                    side="right")
        i_end = np.searchsorted(f4h_times,
                                  np.datetime64(win_end.tz_localize(None) if win_end.tz else win_end),
                                  side="right")
        for fi in range(i_start, i_end):
            f2 = frs4h_sorted[fi]
            if f2["direction"] != f1["direction"]:
                continue
            # proximity: |level1 - level2| < 1 × ATR_4h
            if abs(f1["level"] - f2["level"]) > f2["atr"]:
                continue
            # zone = пересечение candle ranges или union if disjoint
            zb = max(f1["bottom"], f2["bottom"])
            zt = min(f1["top"], f2["top"])
            if zt <= zb:
                # disjoint → union (small zone)
                zb = min(f1["bottom"], f2["bottom"])
                zt = max(f1["top"], f2["top"])
            # anchor confirmed at later confirm
            f2_confirm = f2["time"] + 3 * pd.Timedelta("4h")
            anchor_time = max(f1_confirm, f2_confirm)
            out.append({"kind": "FRACT2X", "tf": "1d+4h",
                        "direction": f1["direction"],
                        "bottom": zb, "top": zt, "atr": f2["atr"],
                        "time": anchor_time, "idx": -1,
                        "f1_idx": f1["idx"], "f2_idx": f2["idx"]})
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


def evaluate_combo(anchors, triggers, dfs, sim, t_tf, anchor_kind, anchor_tf,
                    rr, filt, anchor_confirm_offset_fn, life_days):
    """Универсальная функция: для списка anchors ищем первый qualifying trigger."""
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
        a_start = anchor_confirm_offset_fn(a)  # cur_close-equivalent
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
            em = float(ema_arr[t["idx"]])
            cl = float(close_arr[t["idx"]])
            pro = ((t["direction"] == "LONG" and cl > em) or
                   (t["direction"] == "SHORT" and cl < em))
            if filt == "pro" and not pro: continue
            sl_buf = RDRB_SL_BUF_ATR if t["kind"] == "RDRB" else SL_BUF_ATR
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
            "WR%": round(w/len(closed)*100, 1),
            "total_R": round(closed["R"].sum(), 1),
            "R/trade": round(closed["R"].mean(), 3)}


# ---------------- LTF fractal-sweep TRIGGER (для C) ----------------

def collect_ltf_frsweep_triggers(df, atr_series, tf_label,
                                   lookahead=FRACTAL_SWEEP_LOOKAHEAD):
    """То же что collect_frsweep но для использования как TRIGGER (любой TF)."""
    return collect_frsweep(df, atr_series, tf_label, lookahead)


# ---------------- main ----------------

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
    print("\n[INFO] collecting fractal anchors")
    fract_anchors = {}; frsweep_anchors = {}; ob_anchors = {}
    for tf in ANCHOR_TFS:
        fract_anchors[tf] = collect_fractals(dfs[tf], dfs[tf]["atr14"], tf)
        print(f"  FRACT-{tf}: {len(fract_anchors[tf])}")
    for tf in ANCHOR_TFS:
        frsweep_anchors[tf] = collect_frsweep(dfs[tf], dfs[tf]["atr14"], tf)
        print(f"  FRSWEEP-{tf}: {len(frsweep_anchors[tf])}")
    for tf in ANCHOR_TFS:
        ob_anchors[tf] = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
        print(f"  OB-{tf}: {len(ob_anchors[tf])}")
    fract2x = collect_multi_fractal_confluence(fract_anchors["1d"],
                                                  fract_anchors["4h"])
    print(f"  FRACT2X (1d+4h confluence): {len(fract2x)}")

    # ----- collect zone triggers -----
    print("\n[INFO] collecting zone triggers")
    zone_triggers = {}
    for kind, tfs in [("OB", ["2h", "1h"]),
                       ("FVG", ["2h", "1h", "15m"]),
                       ("RDRB", ["1h"])]:
        for tf in tfs:
            zs = (collect_obs(dfs[tf], dfs[tf]["atr14"], tf) if kind == "OB"
                  else collect_fvgs_or_rdrbs(dfs[tf], kind, dfs[tf]["atr14"], tf))
            zone_triggers[(kind, tf)] = zs
            print(f"  {kind}-{tf}: {len(zs)}")

    # ----- collect LTF fractal-sweep triggers -----
    print("\n[INFO] collecting LTF FRSWEEP triggers (для C)")
    frsweep_triggers = {}
    for tf in ["2h", "1h"]:
        zs = collect_ltf_frsweep_triggers(dfs[tf], dfs[tf]["atr14"], tf)
        frsweep_triggers[tf] = zs
        print(f"  FRSWEEP-trigger-{tf}: {len(zs)}")
    print(f"[TIME] collected in {time.time()-t0:.1f}s")

    # ----- evaluate -----
    print("\n[INFO] running combinations")
    results = []

    def add_result(family, anchor_label, trigger_label, filt, rr, r):
        if r is None: return
        results.append({
            "family": family, "anchor": anchor_label, "trigger": trigger_label,
            "filter": filt, "RR": rr,
            "n_total": r["n_total"], "n_per_week": round(r["n_total"]/years/52, 2),
            "n_closed": r["n_closed"], "WR%": r["WR%"],
            "total_R": r["total_R"], "R/trade": r["R/trade"],
        })

    # ===== A) FRACT-only anchor =====
    print("  [A] FRACT-only anchor variants")
    for a_tf in ANCHOR_TFS:
        anchors = fract_anchors[a_tf]
        if not anchors: continue
        # confirmed at fractal_time + 3*tf (i+2 close)
        offset_td = 3 * pd.Timedelta(a_tf)
        confirm_fn = lambda a, td=offset_td: a["time"] + td
        life_days = FRACT_LIFE_DAYS.get(a_tf, 5)
        for (t_kind, t_tf), trigs in zone_triggers.items():
            if TF_ORDER[a_tf] <= TF_ORDER[t_tf]: continue
            for rr in RR_LIST:
                for filt in ("all", "pro"):
                    r = evaluate_combo(anchors, trigs, dfs, sim, t_tf,
                                         "FRACT", a_tf, rr, filt,
                                         confirm_fn, life_days)
                    add_result("A_FRACT", f"FRACT-{a_tf}",
                                f"{t_kind}-{t_tf}", filt, rr, r)

    # ===== B) FRSWEEP (включая 6h) =====
    print("  [B] FRSWEEP anchor variants (на всех 4 TF)")
    for a_tf in ANCHOR_TFS:
        anchors = frsweep_anchors[a_tf]
        if not anchors: continue
        offset_td = pd.Timedelta(a_tf)  # confirmed at sweep candle close
        confirm_fn = lambda a, td=offset_td: a["time"] + td
        life_days = FRSWEEP_LIFE_DAYS.get(a_tf, 5)
        for (t_kind, t_tf), trigs in zone_triggers.items():
            if TF_ORDER[a_tf] <= TF_ORDER[t_tf]: continue
            for rr in RR_LIST:
                for filt in ("all", "pro"):
                    r = evaluate_combo(anchors, trigs, dfs, sim, t_tf,
                                         "FRSWEEP", a_tf, rr, filt,
                                         confirm_fn, life_days)
                    add_result("B_FRSWEEP", f"FRSWEEP-{a_tf}",
                                f"{t_kind}-{t_tf}", filt, rr, r)

    # ===== C) HTF OB anchor × LTF fractal-sweep TRIGGER =====
    print("  [C] OB-anchor x LTF FRSWEEP-trigger")
    for a_tf in ANCHOR_TFS:
        anchors = ob_anchors[a_tf]
        if not anchors: continue
        offset_td = pd.Timedelta(a_tf)
        confirm_fn = lambda a, td=offset_td: a["time"] + td
        life_days = TF_LIFE_DAYS.get(a_tf, 5)
        for t_tf, trigs in frsweep_triggers.items():
            if TF_ORDER[a_tf] <= TF_ORDER[t_tf]: continue
            for rr in RR_LIST:
                for filt in ("all", "pro"):
                    r = evaluate_combo(anchors, trigs, dfs, sim, t_tf,
                                         "OB", a_tf, rr, filt,
                                         confirm_fn, life_days)
                    add_result("C_OB+FRSWEEPtr", f"OB-{a_tf}",
                                f"FRSWEEP-{t_tf}", filt, rr, r)

    # ===== D) Multi-TF fractal confluence =====
    print("  [D] FRACT2X (1d+4h) anchor")
    if fract2x:
        confirm_fn = lambda a: a["time"]  # уже later confirm
        life_days = 14
        for (t_kind, t_tf), trigs in zone_triggers.items():
            for rr in RR_LIST:
                for filt in ("all", "pro"):
                    r = evaluate_combo(fract2x, trigs, dfs, sim, t_tf,
                                         "FRACT2X", "1d+4h", rr, filt,
                                         confirm_fn, life_days)
                    add_result("D_FRACT2X", "FRACT2X-1d+4h",
                                f"{t_kind}-{t_tf}", filt, rr, r)

    summary = pd.DataFrame(results)
    summary.to_csv(OUT_DIR / "etap18_fractal_grid.csv", index=False)
    print(f"\n[TIME] total {time.time()-t0:.1f}s, candidates={len(summary)}")

    # ----- reports -----
    for fam in ["A_FRACT", "B_FRSWEEP", "C_OB+FRSWEEPtr", "D_FRACT2X"]:
        sub = summary[summary["family"] == fam]
        print(f"\n{'='*70}\n{fam}: {len(sub)} candidates\n{'='*70}")
        if sub.empty: continue
        # WR>=55, n/wk>=0.3
        pass_ = sub[(sub["WR%"] >= 55) & (sub["n_per_week"] >= 0.3)]
        print(f"  WR>=55, n/wk>=0.3:  {len(pass_)} pass")
        if len(pass_):
            print(pass_.sort_values("total_R", ascending=False).head(15).to_string(index=False))
        # top R/tr
        top_rt = sub[sub["n_per_week"] >= 0.3].sort_values("R/trade", ascending=False).head(10)
        if len(top_rt):
            print(f"\n  TOP-10 by R/trade (n/wk>=0.3):")
            print(top_rt.to_string(index=False))

    # ----- combined cross-family WR>=55, n/wk>=1 -----
    print(f"\n{'='*70}\nGLOBAL: WR>=55, n/wk>=1, sorted by total_R\n{'='*70}")
    g = summary[(summary["WR%"] >= 55) & (summary["n_per_week"] >= 1)]
    if len(g):
        print(g.sort_values("total_R", ascending=False).head(20).to_string(index=False))

    print(f"\n{'='*70}\nGLOBAL TOP-15 by R/trade (n/wk>=0.5)\n{'='*70}")
    g2 = summary[summary["n_per_week"] >= 0.5]
    print(g2.sort_values("R/trade", ascending=False).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
