"""Этап 39: Strategy 1.1.1 с оригинальными параметрами пользователя
+ применение safe-фильтров.

User-original params (из research/1_1_1/optimize/optimize_1_1_1_swept_stage3.py
+ asymmetric SL):
  - entry = 0.80 of FVG (deep, agressive)
      LONG:  entry = fvg.bottom + 0.80 × (fvg.top - fvg.bottom)
      SHORT: entry = fvg.top    - 0.80 × (fvg.top - fvg.bottom)
  - SL = в диапазоне [OB-htf edge -> FVG edge]
      LONG:  SL = ob_htf.bottom + 0.35 × (fvg.bottom - ob_htf.bottom)
             (0.35 = SL closer to OB = wider risk)
      SHORT: SL = ob_htf.top    - 0.65 × (ob_htf.top - fvg.top)
             (0.65 = SL closer to FVG = tighter risk)
  - RR = 2.0
  - TP = entry + 2.0 × (entry - SL) for LONG, similar for SHORT

Также для контекста: user's original SWEPT-optimized был entry=0.80,
sl_pct=0.40 (симметричный), RR=2.2 — давал заявленные +46.8R на 3y BTC
(до lookahead audit и data fix).

Тестируем:
  1. Honest baseline (etap_34 std: entry=0.5, SL=ATR-min1%, RR=1.0/1.5/2.0)
  2. User's params (entry=0.8, SL=0.35/0.65, RR=2.0) — без фильтров
  3. User's params + best SAFE single filter (hull_4h aligned)
  4. User's params + best SAFE combo (hull_4h + ICT london|ny)
  5. User's params + score >= 4
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"

# === USER's ORIGINAL PARAMS ===
USER_ENTRY_PCT = 0.80
USER_SL_PCT_LONG = 0.35
USER_SL_PCT_SHORT = 0.65
USER_RR = 2.0

# === HONEST baseline params (для сравнения) ===
HONEST_ENTRY_PCT = 0.5
HONEST_MIN_SL_PCT = 1.0
HONEST_SL_BUF_ATR = 0.3

LIFE_DAYS = {"1d": 14, "12h": 7, "4h": 3, "6h": 4,
              "1h": 1, "2h": 1.5, "15m": 0.5}
TF_HOURS = {"1d": 24, "12h": 12, "6h": 6, "4h": 4,
             "2h": 2, "1h": 1, "15m": 0.25}

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def hull_ma(close, length=78):
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


# ---------- 1.1.1 detector with anchor info preserved ----------

class FastSim:
    def __init__(self, df_1m):
        self.ts = df_1m.index.values
        self.high = df_1m["high"].to_numpy(dtype=float)
        self.low = df_1m["low"].to_numpy(dtype=float)

    def simulate(self, direction, entry, sl, tp, start_time, timeout_days,
                  no_entry=True):
        end_time = start_time + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(self.ts, np.datetime64(
            start_time.tz_localize(None) if start_time.tz else start_time))
        i1 = np.searchsorted(self.ts, np.datetime64(
            end_time.tz_localize(None) if end_time.tz else end_time))
        if i1 <= i0: return ("no_data", 0.0)
        h = self.high[i0:i1]; l = self.low[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0: return ("invalid", 0.0)
        if direction == "LONG":
            entry_mask = l <= entry
            tp_pre_mask = h >= tp
        else:
            entry_mask = h >= entry
            tp_pre_mask = l <= tp
        ent_idxs = np.where(entry_mask)[0]
        tp_pre_idxs = np.where(tp_pre_mask)[0]
        ent_idx = int(ent_idxs[0]) if ent_idxs.size else len(h) + 1
        tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else len(h) + 1
        # no_entry: если TP достигнут до entry, отмена
        if no_entry and tp_pre < ent_idx:
            return ("no_entry", 0.0)
        if ent_idx >= len(h):
            return ("not_filled", 0.0)
        h2 = h[ent_idx:]; l2 = l[ent_idx:]
        if direction == "LONG":
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
        else:
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
        sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
        tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
        if sl_idx == len(h2) and tp_idx == len(h2): return ("open", 0.0)
        if sl_idx <= tp_idx: return ("loss", -1.0)
        if direction == "LONG":
            return ("win", (tp - entry) / risk)
        return ("win", (entry - tp) / risk)


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": ob.cur_time, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": a, "tf": tf, "idx": idx})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"time": f.c2_time, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": a, "tf": tf, "idx": idx})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def detect_111_chains(obs_top, fvgs_macro, obs_mid, fvgs_entry,
                       top_tf, macro_tf, mid_tf, entry_tf):
    """Same as etap_38 but PRESERVE ob_top zone info for SL calculation."""
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    macro_life = pd.Timedelta(days=LIFE_DAYS[macro_tf])
    mid_life = pd.Timedelta(days=LIFE_DAYS[mid_tf])
    fms = sorted(fvgs_macro, key=lambda x: x["time"])
    oms = sorted(obs_mid, key=lambda x: x["time"])
    fes = sorted(fvgs_entry, key=lambda x: x["time"])
    fmt = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                     for z in fms])
    omt = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                     for z in oms])
    fet = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                     for z in fes])

    for ob_top in obs_top:
        l1c = ob_top["time"] + top_td
        l1e = ob_top["time"] + top_life
        if l1e <= l1c: continue
        i0 = np.searchsorted(fmt, np.datetime64(
            l1c.tz_localize(None) if l1c.tz else l1c), side="right")
        i1 = np.searchsorted(fmt, np.datetime64(
            l1e.tz_localize(None) if l1e.tz else l1e), side="right")
        for mi in range(i0, i1):
            f_macro = fms[mi]
            if f_macro["direction"] != ob_top["direction"]: continue
            if not zones_overlap(f_macro["bottom"], f_macro["top"],
                                  ob_top["bottom"], ob_top["top"]): continue
            l2c = f_macro["time"] + macro_td
            l2e = f_macro["time"] + macro_life
            if l2e <= l2c: continue
            j0 = np.searchsorted(omt, np.datetime64(
                l2c.tz_localize(None) if l2c.tz else l2c), side="right")
            j1 = np.searchsorted(omt, np.datetime64(
                l2e.tz_localize(None) if l2e.tz else l2e), side="right")
            ob_mid_found = None
            for oj in range(j0, j1):
                ob_mid = oms[oj]
                if ob_mid["direction"] != ob_top["direction"]: continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      ob_top["bottom"], ob_top["top"]): continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      f_macro["bottom"], f_macro["top"]): continue
                ob_mid_found = ob_mid; break
            if ob_mid_found is None: continue
            l3c = ob_mid_found["time"] + mid_td
            l3e = ob_mid_found["time"] + mid_life
            if l3e <= l3c: continue
            k0 = np.searchsorted(fet, np.datetime64(
                l3c.tz_localize(None) if l3c.tz else l3c), side="right")
            k1 = np.searchsorted(fet, np.datetime64(
                l3e.tz_localize(None) if l3e.tz else l3e), side="right")
            fvg_entry_found = None
            for ek in range(k0, k1):
                f_entry = fes[ek]
                if f_entry["direction"] != ob_top["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"], ob_mid_found["top"]):
                    continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue
            setups.append({
                "anchor_time": ob_top["time"],
                "trigger_time": fvg_entry_found["time"],
                "trigger": fvg_entry_found,
                "ob_htf": ob_top,   # preserved for user's SL formula
                "year": fvg_entry_found["time"].year,
            })
            break
    return setups


def build_user_setup(s, rr=USER_RR):
    """User's original entry/SL formula."""
    f = s["trigger"]
    ob = s["ob_htf"]
    direction = f["direction"]
    fb, ft = f["bottom"], f["top"]
    obb, obt = ob["bottom"], ob["top"]

    if direction == "LONG":
        entry = fb + USER_ENTRY_PCT * (ft - fb)
        # SL = ob.bottom + sl_pct × (fvg.bottom - ob.bottom)
        sl = obb + USER_SL_PCT_LONG * (fb - obb)
    else:
        entry = ft - USER_ENTRY_PCT * (ft - fb)
        # SL = ob.top - sl_pct × (ob.top - fvg.top)
        sl = obt - USER_SL_PCT_SHORT * (obt - ft)

    risk = abs(entry - sl)
    if risk <= 0: return None
    # Sanity: SL on correct side of entry?
    if direction == "LONG" and sl >= entry: return None
    if direction == "SHORT" and sl <= entry: return None

    if direction == "LONG":
        tp = entry + rr * risk
    else:
        tp = entry - rr * risk
    return entry, sl, tp


def build_honest_setup(s, rr):
    """Honest baseline: entry=0.5 FVG, SL=ATR-with-min-1%."""
    f = s["trigger"]
    direction = f["direction"]
    fb, ft = f["bottom"], f["top"]
    atr = f["atr"]
    if direction == "LONG":
        entry = fb + HONEST_ENTRY_PCT * (ft - fb)
        atr_sl = fb - HONEST_SL_BUF_ATR * atr
        sl = min(atr_sl, entry - entry * HONEST_MIN_SL_PCT / 100)
    else:
        entry = ft - HONEST_ENTRY_PCT * (ft - fb)
        atr_sl = ft + HONEST_SL_BUF_ATR * atr
        sl = max(atr_sl, entry + entry * HONEST_MIN_SL_PCT / 100)
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp = entry + rr * risk if direction == "LONG" else entry - rr * risk
    return entry, sl, tp


def evaluate_setups(setups, sim, build_fn, rr, no_entry=True):
    rows = []
    for s in setups:
        # build_fn signature: (s) for user (rr fixed), (s, rr) for honest
        if build_fn is build_user_setup:
            tup = build_fn(s, rr)
        else:
            tup = build_fn(s, rr)
        if tup is None: continue
        entry, sl, tp = tup
        f = s["trigger"]
        start = f["time"] + pd.Timedelta(hours=TF_HOURS["15m"])
        outcome, R = sim.simulate(f["direction"], entry, sl, tp, start,
                                    timeout_days=LIFE_DAYS["15m"],
                                    no_entry=no_entry)
        rows.append({"trigger_time": f["time"], "direction": f["direction"],
                      "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R, "year": s["year"]})
    return pd.DataFrame(rows)


# ---------- safe lookups (from etap_37) ----------

def hull_trend_safe(close, hull, ts):
    idx = hull.index.searchsorted(ts, side="right") - 1
    if idx < 3: return "na"
    last_closed = idx - 1
    c = close.iloc[last_closed]; h2 = hull.iloc[last_closed - 2]
    if pd.isna(c) or pd.isna(h2): return "na"
    return "up" if c > h2 else "down"


def aligned(direction, label):
    if label == "na": return "na"
    if direction == "LONG":
        return "aligned" if label == "up" else "counter"
    return "aligned" if label == "down" else "counter"


# ---------- report ----------

def report(label, df_e, years):
    cl = df_e[df_e["outcome"].isin(["win", "loss"])]
    if cl.empty:
        print(f"  {label}: no closed"); return
    n_total = len(df_e)
    n_closed = len(cl)
    n_no_entry = (df_e["outcome"] == "no_entry").sum()
    n_not_filled = (df_e["outcome"] == "not_filled").sum()
    wr = (cl["outcome"] == "win").mean() * 100
    tot = cl["R"].sum()
    rt = cl["R"].mean()
    bad_yrs = (cl.groupby("year")["R"].sum() < 0).sum()
    n_yrs = cl["year"].nunique()
    print(f"  {label}")
    print(f"    n_total={n_total}, no_entry={n_no_entry}, not_filled={n_not_filled}, "
          f"closed={n_closed}")
    print(f"    WR={wr:.1f}%, total_R={tot:+.1f}, R/tr={rt:+.3f}, "
          f"freq={n_total/years/52:.2f}/wk, bad_yrs={bad_yrs}/{n_yrs}")
    yr = cl.groupby("year").agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"))
    yr["WR"] = yr["wins"] / yr["n"] * 100
    for y, r in yr.iterrows():
        flag = " !" if r["total_R"] < 0 else ""
        print(f"      {int(y)}: n={int(r['n']):>3} WR={r['WR']:5.1f}% "
              f"total={r['total_R']:+5.1f}R{flag}")


def main():
    t0 = time.time()
    print(f"[INFO] loading data {START_DATE}+")
    tfs = ["1d", "12h", "6h", "4h", "2h", "1h", "15m"]
    dfs = {}
    for tf in tfs:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        df["atr14"] = compute_atr(df, 14)
        dfs[tf] = df
    df_1m = load_df(SYMBOL, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    sim = FastSim(df_1m)
    years = (dfs["1d"].index[-1] - dfs["1d"].index[0]).days / 365
    print(f"  years: {years:.2f}")

    print("[INFO] computing indicators")
    hull_4h = hull_ma(dfs["4h"]["close"], 78)

    print("[INFO] collecting zones")
    obs = {}; fvgs = {}
    for tf in ["1d", "12h", "2h", "1h"]:
        obs[tf] = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
    for tf in ["6h", "4h", "15m"]:
        fvgs[tf] = collect_fvgs(dfs[tf], dfs[tf]["atr14"], tf)

    print("[INFO] building 1.1.1 chains (full: 1d/12h x 4h/6h x 1h/2h x 15m)")
    all_setups = []
    for top_tf in ["1d", "12h"]:
        for macro_tf in ["4h", "6h"]:
            for mid_tf in ["1h", "2h"]:
                ss = detect_111_chains(obs[top_tf], fvgs[macro_tf],
                                        obs[mid_tf], fvgs["15m"],
                                        top_tf, macro_tf, mid_tf, "15m")
                all_setups.extend(ss)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["anchor_time"], s["trigger_time"], s["trigger"]["direction"])
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  unique setups: {len(unique)}")

    # Compute hull_4h labels for filtering
    df_4h = dfs["4h"]
    hull_labels = []
    ict_sessions = []
    for s in unique:
        ts = s["trigger_time"]
        h = hull_trend_safe(df_4h["close"], hull_4h, ts)
        hull_labels.append(aligned(s["trigger"]["direction"], h))
        if ts.hour < 7: ict_sessions.append("asia")
        elif ts.hour < 12: ict_sessions.append("london")
        elif ts.hour < 17: ict_sessions.append("ny")
        else: ict_sessions.append("off-hours")

    setups_hull4h = [s for s, h in zip(unique, hull_labels) if h == "aligned"]
    setups_hull4h_ict = [s for s, h, ict in zip(unique, hull_labels, ict_sessions)
                          if h == "aligned" and ict in ("london", "ny")]
    setups_ict_only = [s for s, ict in zip(unique, ict_sessions)
                        if ict in ("london", "ny")]

    print(f"  setups after hull_4h filter: {len(setups_hull4h)}")
    print(f"  setups after hull_4h+ICT filter: {len(setups_hull4h_ict)}")
    print(f"  setups after ICT only: {len(setups_ict_only)}")

    # ============================================================
    print(f"\n{'='*70}")
    print(f"PART 1: HONEST baseline (entry=0.5, SL=ATR-min1%)")
    print(f"{'='*70}")
    for rr in [1.0, 1.5, 2.0]:
        df_e = evaluate_setups(unique, sim, build_honest_setup, rr,
                                no_entry=False)
        report(f"HONEST RR={rr}, no filter", df_e, years)

    # ============================================================
    print(f"\n{'='*70}")
    print(f"PART 2: USER's params (entry=0.80, SL=0.35L/0.65S, RR=2.0, no_entry=on)")
    print(f"{'='*70}")
    for rr in [1.5, 2.0, 2.5, 3.0]:
        df_e = evaluate_setups(unique, sim, build_user_setup, rr,
                                no_entry=True)
        report(f"USER params RR={rr}, no filter", df_e, years)

    # ============================================================
    print(f"\n{'='*70}")
    print(f"PART 3: USER's params + Hull-4h aligned filter (SAFE)")
    print(f"{'='*70}")
    for rr in [1.5, 2.0, 2.5, 3.0]:
        df_e = evaluate_setups(setups_hull4h, sim, build_user_setup, rr,
                                no_entry=True)
        report(f"USER + hull_4h RR={rr}", df_e, years)

    # ============================================================
    print(f"\n{'='*70}")
    print(f"PART 4: USER's params + Hull-4h + ICT(london|ny) (best combo)")
    print(f"{'='*70}")
    for rr in [1.5, 2.0, 2.5, 3.0]:
        df_e = evaluate_setups(setups_hull4h_ict, sim, build_user_setup, rr,
                                no_entry=True)
        report(f"USER + hull_4h + ICT RR={rr}", df_e, years)

    # ============================================================
    print(f"\n{'='*70}")
    print(f"PART 5: USER's params + ICT(london|ny) only")
    print(f"{'='*70}")
    for rr in [1.5, 2.0, 2.5, 3.0]:
        df_e = evaluate_setups(setups_ict_only, sim, build_user_setup, rr,
                                no_entry=True)
        report(f"USER + ICT RR={rr}", df_e, years)

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
