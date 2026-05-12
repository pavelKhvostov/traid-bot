"""Этап 19: 3-stage оптимизация топ-кандидатов (аналог Strategy 1.1.1 stages).

Базы (дубликаты схлопнуты):
  B1 = C1 base = OB-4h × FVG-1h pro
  B2 = C2 base = OB-6h × FVG-2h pro
  B3 = C3/C4 base = OB-12h × FVG-2h pro
  B4 = C6 base = FRACT2X-1d+4h × FVG-2h pro

Stage 1 — vary entry_pct: [0.0, 0.25, 0.5, 0.75, 1.0]
  0.0 = дальний край FVG (глубже в зону, лучшая цена, реже fill)
  0.5 = mid (текущее baseline)
  1.0 = ближний край FVG (быстрая активация, худшая цена)
  Fix: sl_buf_atr=0.3, min_sl_pct=1.0, RR=1.5

Stage 2 — vary (sl_buf_atr, min_sl_pct):
  sl_buf_atr ∈ [0.0, 0.15, 0.3, 0.5, 0.7]
  min_sl_pct ∈ [0.5, 1.0, 1.5]
  Fix: best entry_pct from Stage 1, RR=1.5

Stage 3 — vary RR: [1.5, 1.75, 2.0, 2.25, 2.5, 3.0]
  Fix: best entry/SL config from Stages 1+2.

Selection criteria per stage:
  Primary: max total_R при WR >= 50% И min_sl_pct >= 1.0
  Tiebreak: max R/trade

Финал — per base: best_config (entry_pct, sl_buf, min_sl_pct, RR) + cifra.
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
RDRB_SL_BUF_ATR = 0.5

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                "2h": 3, "1h": 2, "15m": 1}
FRACT2X_LIFE_DAYS = 14

OUT_DIR = Path("research/elements_study/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- bases -----
BASES = [
    {"id": "B1", "name": "OB-4h x FVG-1h pro",
     "anchor_kind": "OB", "anchor_tf": "4h",
     "trigger_kind": "FVG", "trigger_tf": "1h", "filter": "pro"},
    {"id": "B2", "name": "OB-6h x FVG-2h pro",
     "anchor_kind": "OB", "anchor_tf": "6h",
     "trigger_kind": "FVG", "trigger_tf": "2h", "filter": "pro"},
    {"id": "B3", "name": "OB-12h x FVG-2h pro",
     "anchor_kind": "OB", "anchor_tf": "12h",
     "trigger_kind": "FVG", "trigger_tf": "2h", "filter": "pro"},
    {"id": "B4", "name": "FRACT2X-1d+4h x FVG-2h pro",
     "anchor_kind": "FRACT2X", "anchor_tf": "1d+4h",
     "trigger_kind": "FVG", "trigger_tf": "2h", "filter": "pro"},
]

ENTRY_PCTS = [0.0, 0.25, 0.5, 0.75, 1.0]
SL_BUFS    = [0.0, 0.15, 0.3, 0.5, 0.7]
MIN_SL_PCTS = [0.5, 1.0, 1.5]
RRS = [1.5, 1.75, 2.0, 2.25, 2.5, 3.0]


# ---------------- helpers ----------------

def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


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


# ---------------- collectors (минимум) ----------------

def collect_obs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"time": ob.cur_time, "direction": ob.direction,
                    "bottom": ob.bottom, "top": ob.top, "atr": atr,
                    "tf": tf_label, "idx": idx})
    return out


def collect_fvgs(df, atr_series, tf_label):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0: continue
        out.append({"time": f.c2_time, "direction": f.direction,
                    "bottom": f.bottom, "top": f.top, "atr": atr,
                    "tf": tf_label, "idx": idx})
    return out


def collect_fractals(df, atr_series, tf_label):
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
        out.append({"time": times[i], "idx": i,
                    "direction": "LONG" if is_fl else "SHORT",
                    "bottom": float(l), "top": float(h),
                    "level": float(l) if is_fl else float(h),
                    "atr": atr, "tf": tf_label})
    return out


def collect_fract2x(frs1d, frs4h):
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
            if f2["direction"] != f1["direction"]: continue
            if abs(f1["level"] - f2["level"]) > f2["atr"]: continue
            zb = max(f1["bottom"], f2["bottom"])
            zt = min(f1["top"], f2["top"])
            if zt <= zb:
                zb = min(f1["bottom"], f2["bottom"])
                zt = max(f1["top"], f2["top"])
            f2_confirm = f2["time"] + 3 * pd.Timedelta("4h")
            anchor_time = max(f1_confirm, f2_confirm)
            out.append({"time": anchor_time,
                        "direction": f1["direction"],
                        "bottom": zb, "top": zt, "atr": f2["atr"]})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


# ---------------- pre-build base setups ----------------

def build_base_setups(anchors, triggers, df_trig, anchor_tf, trigger_tf,
                       filt, anchor_kind="OB"):
    """Возвращает list of dict — {anchor, trigger, pro} с примененным filter.
    Один trigger на anchor (первый qualifying)."""
    if anchor_kind == "FRACT2X":
        a_tf_td = pd.Timedelta(0)
        a_life = pd.Timedelta(days=FRACT2X_LIFE_DAYS)
    else:
        a_tf_td = pd.Timedelta(anchor_tf)
        a_life = pd.Timedelta(days=TF_LIFE_DAYS.get(anchor_tf, 5))
    ema_arr = df_trig["ema200"].to_numpy()
    close_arr = df_trig["close"].to_numpy()
    t_sorted = sorted(triggers, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                         for t in t_sorted])
    setups = []
    for a in anchors:
        a_start = a["time"] + a_tf_td
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
            setups.append({"trigger_time": t["time"], "direction": t["direction"],
                            "fvg_bottom": t["bottom"], "fvg_top": t["top"],
                            "fvg_atr": t["atr"], "year": t["time"].year, "pro": pro})
            break
    return setups


# ---------------- evaluation with parametric entry/SL/RR ----------------

def evaluate_setups(base_setups, sim, trigger_tf, entry_pct, sl_buf_atr,
                     min_sl_pct, rr):
    """Эваулировать base setups с заданными параметрами entry/SL/RR.
    entry_pct: 0.0=far border, 1.0=near border.
      LONG:  entry = bottom + entry_pct * (top - bottom)
      SHORT: entry = top   - entry_pct * (top - bottom)
    """
    rows = []
    for s in base_setups:
        direction = s["direction"]
        zb = s["fvg_bottom"]; zt = s["fvg_top"]
        atr = s["fvg_atr"]
        size = zt - zb
        if direction == "LONG":
            entry = zb + entry_pct * size
            atr_sl = zb - sl_buf_atr * atr
            min_dist = entry * min_sl_pct / 100
            sl = min(atr_sl, entry - min_dist)
        else:
            entry = zt - entry_pct * size
            atr_sl = zt + sl_buf_atr * atr
            min_dist = entry * min_sl_pct / 100
            sl = max(atr_sl, entry + min_dist)
        risk = abs(entry - sl)
        if risk <= 0: continue
        if direction == "LONG":
            tp = entry + rr * risk
        else:
            tp = entry - rr * risk
        start = s["trigger_time"] + pd.Timedelta(trigger_tf)
        outcome, R = sim.simulate(direction, entry, sl, tp,
                                    start, TF_LIFE_DAYS.get(trigger_tf, 5))
        rows.append({"outcome": outcome, "R": R, "year": s["year"]})
    if not rows: return None
    df_e = pd.DataFrame(rows)
    closed = df_e[df_e["outcome"].isin(["win", "loss"])]
    if closed.empty: return None
    w = (closed["outcome"] == "win").sum()
    return {"n_total": len(df_e), "n_closed": len(closed),
            "WR": round(w/len(closed)*100, 1),
            "total_R": round(closed["R"].sum(), 1),
            "R_tr": round(closed["R"].mean(), 3)}


# ---------------- 3-stage optimize ----------------

def optimize_base(base_setups, sim, trigger_tf, label):
    print(f"\n{'='*70}\nOPTIMIZE: {label}\n{'='*70}")
    print(f"  base setups: {len(base_setups)}")

    all_results = []

    # --- Stage 1: entry sweep ---
    print(f"\n  [Stage 1] entry sweep (sl_buf=0.3, min_sl=1.0, RR=1.5)")
    s1_rows = []
    for ep in ENTRY_PCTS:
        r = evaluate_setups(base_setups, sim, trigger_tf,
                              entry_pct=ep, sl_buf_atr=0.3,
                              min_sl_pct=1.0, rr=1.5)
        if r:
            row = {"stage": 1, "entry_pct": ep, "sl_buf": 0.3,
                    "min_sl_pct": 1.0, "RR": 1.5, **r}
            s1_rows.append(row); all_results.append(row)
    s1_df = pd.DataFrame(s1_rows)
    print(s1_df[["entry_pct", "n_total", "n_closed", "WR", "total_R", "R_tr"]].to_string(index=False))
    # pick best — primary: max total_R при WR>=50
    s1_pass = s1_df[s1_df["WR"] >= 50]
    if s1_pass.empty: s1_pass = s1_df
    best_entry = s1_pass.sort_values("total_R", ascending=False).iloc[0]["entry_pct"]
    print(f"  -> best entry_pct = {best_entry}")

    # --- Stage 2: SL sweep ---
    print(f"\n  [Stage 2] SL sweep (entry={best_entry}, RR=1.5)")
    s2_rows = []
    for sl_buf, msp in product(SL_BUFS, MIN_SL_PCTS):
        r = evaluate_setups(base_setups, sim, trigger_tf,
                              entry_pct=best_entry, sl_buf_atr=sl_buf,
                              min_sl_pct=msp, rr=1.5)
        if r:
            row = {"stage": 2, "entry_pct": best_entry, "sl_buf": sl_buf,
                    "min_sl_pct": msp, "RR": 1.5, **r}
            s2_rows.append(row); all_results.append(row)
    s2_df = pd.DataFrame(s2_rows)
    # уважаем правило юзера: min_sl_pct >= 1.0
    s2_valid = s2_df[(s2_df["min_sl_pct"] >= 1.0) & (s2_df["WR"] >= 50)]
    if s2_valid.empty:
        s2_valid = s2_df[s2_df["min_sl_pct"] >= 1.0]
    if s2_valid.empty:
        s2_valid = s2_df
    print(s2_df.sort_values("total_R", ascending=False).head(8)[
        ["sl_buf", "min_sl_pct", "n_total", "n_closed", "WR", "total_R", "R_tr"]
    ].to_string(index=False))
    best_sl_row = s2_valid.sort_values("total_R", ascending=False).iloc[0]
    best_sl_buf = best_sl_row["sl_buf"]
    best_min_sl = best_sl_row["min_sl_pct"]
    print(f"  -> best sl_buf = {best_sl_buf}, min_sl_pct = {best_min_sl}")

    # --- Stage 3: RR sweep ---
    print(f"\n  [Stage 3] RR sweep (entry={best_entry}, sl_buf={best_sl_buf}, min_sl={best_min_sl})")
    s3_rows = []
    for rr in RRS:
        r = evaluate_setups(base_setups, sim, trigger_tf,
                              entry_pct=best_entry, sl_buf_atr=best_sl_buf,
                              min_sl_pct=best_min_sl, rr=rr)
        if r:
            row = {"stage": 3, "entry_pct": best_entry, "sl_buf": best_sl_buf,
                    "min_sl_pct": best_min_sl, "RR": rr, **r}
            s3_rows.append(row); all_results.append(row)
    s3_df = pd.DataFrame(s3_rows)
    print(s3_df[["RR", "n_total", "n_closed", "WR", "total_R", "R_tr"]].to_string(index=False))
    # pick best — учитываем диапазон 1.5-3.0 (любой из RRS), criterion: max total_R при WR>=45 (более мягко т.к. RR>2)
    s3_valid = s3_df[s3_df["WR"] >= 45]
    if s3_valid.empty: s3_valid = s3_df
    best_rr = s3_valid.sort_values("total_R", ascending=False).iloc[0]["RR"]
    best_overall = s3_valid.sort_values("total_R", ascending=False).iloc[0]
    print(f"  -> best RR = {best_rr}")
    print(f"\n  *** FINAL CONFIG: entry_pct={best_entry}, sl_buf={best_sl_buf}, min_sl={best_min_sl}, RR={best_rr}")
    print(f"     Result: WR={best_overall['WR']}%, total_R={best_overall['total_R']}, "
            f"R/tr={best_overall['R_tr']}, n={best_overall['n_total']}")

    return pd.DataFrame(all_results), {
        "entry_pct": best_entry, "sl_buf": best_sl_buf,
        "min_sl_pct": best_min_sl, "RR": best_rr,
        "WR": best_overall["WR"], "total_R": best_overall["total_R"],
        "R_tr": best_overall["R_tr"], "n_total": best_overall["n_total"],
    }


# ---------------- main ----------------

def main():
    t0 = time.time()
    print(f"[INFO] loading data START={START_DATE}")
    raw_tfs = {b["anchor_tf"] for b in BASES} | {b["trigger_tf"] for b in BASES}
    raw_tfs.discard("1d+4h")
    raw_tfs.update({"1d", "4h"})
    needed_tfs = sorted(raw_tfs, key=lambda x: pd.Timedelta(x))
    dfs = {}
    for tf in needed_tfs:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        df["atr14"] = compute_atr(df, 14)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        dfs[tf] = df
        print(f"  {tf}: {len(df)} bars")
    df_1m = load_df(SYMBOL, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    sim = FastSim(df_1m)
    print(f"[TIME] data loaded in {time.time()-t0:.1f}s")

    print("\n[INFO] collecting zones")
    obs_cache = {}
    fvgs_cache = {}
    for b in BASES:
        if b["anchor_kind"] == "OB":
            tf = b["anchor_tf"]
            if tf not in obs_cache:
                obs_cache[tf] = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
                print(f"  OB-{tf}: {len(obs_cache[tf])}")
        if b["trigger_kind"] == "FVG":
            tf = b["trigger_tf"]
            if tf not in fvgs_cache:
                fvgs_cache[tf] = collect_fvgs(dfs[tf], dfs[tf]["atr14"], tf)
                print(f"  FVG-{tf}: {len(fvgs_cache[tf])}")
    fract2x = None
    if any(b["anchor_kind"] == "FRACT2X" for b in BASES):
        frs1d = collect_fractals(dfs["1d"], dfs["1d"]["atr14"], "1d")
        frs4h = collect_fractals(dfs["4h"], dfs["4h"]["atr14"], "4h")
        fract2x = collect_fract2x(frs1d, frs4h)
        print(f"  FRACT2X: {len(fract2x)}")

    # ---- per-base optimize ----
    summary = []
    for b in BASES:
        anchors = (obs_cache[b["anchor_tf"]] if b["anchor_kind"] == "OB"
                   else fract2x)
        triggers = fvgs_cache[b["trigger_tf"]]
        df_trig = dfs[b["trigger_tf"]]
        base_setups = build_base_setups(anchors, triggers, df_trig,
                                          b["anchor_tf"], b["trigger_tf"],
                                          b["filter"], b["anchor_kind"])
        all_df, best = optimize_base(base_setups, sim, b["trigger_tf"], b["name"])
        all_df.to_csv(OUT_DIR / f"etap19_{b['id']}_optimize.csv", index=False)
        summary.append({"base": b["id"], "name": b["name"], **best})

    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(OUT_DIR / "etap19_summary.csv", index=False)
    print(f"\n{'='*70}\n*** SUMMARY — best config per base ***\n{'='*70}")
    print(summary_df.to_string(index=False))
    print(f"\n[TIME] total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
