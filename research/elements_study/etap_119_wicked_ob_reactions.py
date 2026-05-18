"""etap_119: Wicked OB-D/12h + 5 типов реакций после возврата в зону.

Wicked OB filter:
  LONG: prev медвежья + cur бычья + cur.close > prev.open
        + нижний фитиль cur < нижний фитиль prev / 2 (decisive reversal)
  SHORT: зеркально (верхний фитиль cur < верхний фитиль prev / 2)

Trigger: цена возвращается в зону OB-D ПОСЛЕ закрытия cur этой OB.

Реакции (5 вариантов внутри зоны, после touch):
  V1: Standard — OB-1h/2h + FVG-15m/20m inside OB-htf (canonical 1.1.1-like)
  V2: FVG-only — FVG-15m/20m в зоне напрямую (skip HTF)
  V3: RDRB-htf — RDRB-1h/2h как реакция
  V4: OB-htf only — OB-1h/2h без entry FVG, entry = mid OB-htf
  V5: Marubozu-15m — тело ≥95%, импульсная свеча в направлении OB-D

Также baseline без wick filter (control group).
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
from dataclasses import dataclass
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg, OBZone, FVGZone
from strategies.strategy_rdrb import detect_rdrb

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ENTRY_PCT = 0.70
SL_PCT = 0.35
RR = 2.0
MIN_SL_PCT = 1.0
MAX_HOLD_DAYS = 7


@dataclass
class WickedOB:
    direction: str
    bottom: float
    top: float
    prev_time: pd.Timestamp
    cur_time: pd.Timestamp
    cur_close: pd.Timestamp
    tf_hours: int
    wick_ratio: float  # cur_wick / prev_wick


def detect_wicked_ob(df, idx, tf_hours):
    """OB-пара с фильтром: фитиль i < фитиль i-1 / 2."""
    if idx < 1 or idx >= len(df): return None
    prev = df.iloc[idx - 1]
    cur = df.iloc[idx]
    po, pc = float(prev["open"]), float(prev["close"])
    pl, ph = float(prev["low"]), float(prev["high"])
    co, cc = float(cur["open"]), float(cur["close"])
    cl, ch = float(cur["low"]), float(cur["high"])

    # LONG OB
    if pc < po and cc > po:
        # prev bearish: lower wick = pc - pl  (от тела вниз)
        prev_wick = pc - pl
        # cur (любого тела): lower wick = min(co, cc) - cl
        cur_wick = min(co, cc) - cl
        if prev_wick <= 0: return None
        ratio = cur_wick / prev_wick if prev_wick > 0 else 999
        if cur_wick >= prev_wick / 2: return None
        return WickedOB(direction="LONG", bottom=min(pl, cl), top=po,
                        prev_time=df.index[idx - 1], cur_time=df.index[idx],
                        cur_close=df.index[idx] + pd.Timedelta(hours=tf_hours),
                        tf_hours=tf_hours, wick_ratio=ratio)
    # SHORT OB
    if pc > po and cc < po:
        prev_wick = ph - pc  # prev bullish: upper wick = ph - pc
        cur_wick = ch - max(co, cc)
        if prev_wick <= 0: return None
        ratio = cur_wick / prev_wick if prev_wick > 0 else 999
        if cur_wick >= prev_wick / 2: return None
        return WickedOB(direction="SHORT", bottom=po, top=max(ph, ch),
                        prev_time=df.index[idx - 1], cur_time=df.index[idx],
                        cur_close=df.index[idx] + pd.Timedelta(hours=tf_hours),
                        tf_hours=tf_hours, wick_ratio=ratio)
    return None


def find_first_touch_and_invalidation(ob_d, df_l1):
    """Найти момент когда цена впервые ВЕРНУЛАСЬ в зону после cur_close.
    Также найти момент invalidation (close прошёл через дальний край).
    Возвращает (touch_time, inval_time)."""
    df_after = df_l1[df_l1.index >= ob_d.cur_close]
    touch_time = None
    inval_time = None
    for ts, row in df_after.iterrows():
        rl = float(row["low"]); rh = float(row["high"]); rc = float(row["close"])
        if ob_d.direction == "LONG":
            # touch: low <= top (any wick enters zone from above)
            if touch_time is None and rl <= ob_d.top:
                touch_time = ts
            # inval: close < bottom (price closed below far edge)
            if rc < ob_d.bottom:
                inval_time = ts + pd.Timedelta(hours=ob_d.tf_hours)
                break
        else:
            if touch_time is None and rh >= ob_d.bottom:
                touch_time = ts
            if rc > ob_d.top:
                inval_time = ts + pd.Timedelta(hours=ob_d.tf_hours)
                break
    return touch_time, inval_time


def collect_wicked_obs(df, tf_hours):
    out = []
    for idx in range(2, len(df) - 1):
        w = detect_wicked_ob(df, idx, tf_hours)
        if w is not None:
            out.append(w)
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


# === Reaction detectors ===

def react_v1_ob_fvg(ob_d, touch_t, inval_t, df_1h, df_2h, df_15m, df_20m):
    """V1: OB-1h/2h + FVG-15m/20m inside OB-htf. Reaction time >= touch_t.
    Returns dict with entry/sl/tp_proxy/signal_time or None."""
    # Try OB-1h first, then OB-2h
    for df_htf, htf_hours, htf_label in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
        df_w = df_htf[(df_htf.index >= touch_t) & (df_htf.index < inval_t)]
        if len(df_w) < 2: continue
        for i in range(1, len(df_w)):
            cand = detect_ob_pair(df_w, i)
            if cand is None or cand.direction != ob_d.direction: continue
            if not zones_overlap(cand.bottom, cand.top, ob_d.bottom, ob_d.top): continue
            # Find entry FVG inside cand's time range (cand.prev_time to cand.cur_time + htf_min - tf_min)
            for df_ltf, tf_min, tf_label in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
                end_t = cand.cur_time + pd.Timedelta(minutes=htf_hours * 60 - tf_min)
                df_l = df_ltf[(df_ltf.index >= cand.prev_time) & (df_ltf.index <= end_t)]
                for k in range(2, len(df_l)):
                    fvg = detect_fvg(df_l, k)
                    if fvg is None or fvg.direction != ob_d.direction: continue
                    if not zones_overlap(fvg.bottom, fvg.top, cand.bottom, cand.top): continue
                    # Found entry
                    fb, ft = fvg.bottom, fvg.top
                    obb, obt = cand.bottom, cand.top
                    if ob_d.direction == "LONG":
                        entry = fb + ENTRY_PCT * (ft - fb)
                        sl = obb + SL_PCT * (fb - obb)
                    else:
                        entry = ft - ENTRY_PCT * (ft - fb)
                        sl = obt - SL_PCT * (obt - ft)
                    risk = abs(entry - sl)
                    if MIN_SL_PCT > 0:
                        min_dist = entry * MIN_SL_PCT / 100
                        if ob_d.direction == "LONG":
                            sl = min(sl, entry - min_dist)
                        else:
                            sl = max(sl, entry + min_dist)
                        risk = abs(entry - sl)
                    if risk <= 0: continue
                    if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                        continue
                    return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                            "signal_time": fvg.c2_time + pd.Timedelta(minutes=tf_min),
                            "reaction_tf": f"OB-{htf_label}+FVG-{tf_label}"}
    return None


def react_v2_fvg_only(ob_d, touch_t, inval_t, df_15m, df_20m):
    """V2: только FVG-15m/20m в зоне."""
    for df_ltf, tf_min, tf_label in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
        df_w = df_ltf[(df_ltf.index >= touch_t) & (df_ltf.index < inval_t)]
        for k in range(2, len(df_w)):
            fvg = detect_fvg(df_w, k)
            if fvg is None or fvg.direction != ob_d.direction: continue
            if not zones_overlap(fvg.bottom, fvg.top, ob_d.bottom, ob_d.top): continue
            fb, ft = fvg.bottom, fvg.top
            if ob_d.direction == "LONG":
                entry = fb + ENTRY_PCT * (ft - fb)
                sl = ob_d.bottom + SL_PCT * (fb - ob_d.bottom)
            else:
                entry = ft - ENTRY_PCT * (ft - fb)
                sl = ob_d.top - SL_PCT * (ob_d.top - ft)
            risk = abs(entry - sl)
            if MIN_SL_PCT > 0:
                min_dist = entry * MIN_SL_PCT / 100
                if ob_d.direction == "LONG":
                    sl = min(sl, entry - min_dist)
                else:
                    sl = max(sl, entry + min_dist)
                risk = abs(entry - sl)
            if risk <= 0: continue
            if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                continue
            return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                    "signal_time": fvg.c2_time + pd.Timedelta(minutes=tf_min),
                    "reaction_tf": f"FVG-{tf_label}"}
    return None


def react_v3_rdrb_htf(ob_d, touch_t, inval_t, df_1h, df_2h):
    """V3: RDRB-1h/2h pattern as reaction."""
    for df_htf, htf_h, label in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
        df_w = df_htf[(df_htf.index >= touch_t) & (df_htf.index < inval_t)]
        for k in range(2, len(df_w)):
            r = detect_rdrb(df_w, k)
            if r is None or r.direction != ob_d.direction: continue
            if not zones_overlap(r.bottom, r.top, ob_d.bottom, ob_d.top): continue
            # entry = mid RDRB
            entry = (r.bottom + r.top) / 2
            if ob_d.direction == "LONG":
                sl = ob_d.bottom + SL_PCT * (entry - ob_d.bottom)
            else:
                sl = ob_d.top - SL_PCT * (ob_d.top - entry)
            risk = abs(entry - sl)
            if MIN_SL_PCT > 0:
                min_dist = entry * MIN_SL_PCT / 100
                if ob_d.direction == "LONG":
                    sl = min(sl, entry - min_dist)
                else:
                    sl = max(sl, entry + min_dist)
                risk = abs(entry - sl)
            if risk <= 0: continue
            if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                continue
            return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                    "signal_time": df_w.index[k] + pd.Timedelta(hours=htf_h),
                    "reaction_tf": f"RDRB-{label}"}
    return None


def react_v4_ob_only(ob_d, touch_t, inval_t, df_1h, df_2h):
    """V4: OB-1h/2h as reaction, entry = mid OB-htf (no inner FVG)."""
    for df_htf, htf_h, label in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
        df_w = df_htf[(df_htf.index >= touch_t) & (df_htf.index < inval_t)]
        for k in range(1, len(df_w)):
            cand = detect_ob_pair(df_w, k)
            if cand is None or cand.direction != ob_d.direction: continue
            if not zones_overlap(cand.bottom, cand.top, ob_d.bottom, ob_d.top): continue
            entry = (cand.bottom + cand.top) / 2
            if ob_d.direction == "LONG":
                sl = ob_d.bottom + SL_PCT * (entry - ob_d.bottom)
            else:
                sl = ob_d.top - SL_PCT * (ob_d.top - entry)
            risk = abs(entry - sl)
            if MIN_SL_PCT > 0:
                min_dist = entry * MIN_SL_PCT / 100
                if ob_d.direction == "LONG":
                    sl = min(sl, entry - min_dist)
                else:
                    sl = max(sl, entry + min_dist)
                risk = abs(entry - sl)
            if risk <= 0: continue
            if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                continue
            return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                    "signal_time": cand.cur_time + pd.Timedelta(hours=htf_h),
                    "reaction_tf": f"OB-{label}_only"}
    return None


def react_v5_marubozu(ob_d, touch_t, inval_t, df_15m):
    """V5: marubozu-15m в зоне (тело >=95% от диапазона)."""
    df_w = df_15m[(df_15m.index >= touch_t) & (df_15m.index < inval_t)]
    for k in range(len(df_w)):
        row = df_w.iloc[k]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        rng = h - l
        if rng <= 0: continue
        body = abs(c - o)
        if body / rng < 0.95: continue
        direction = "LONG" if c > o else ("SHORT" if c < o else None)
        if direction != ob_d.direction: continue
        if direction == "LONG":
            zone_b, zone_t = o, c
        else:
            zone_b, zone_t = c, o
        if not zones_overlap(zone_b, zone_t, ob_d.bottom, ob_d.top): continue
        entry = (zone_b + zone_t) / 2
        if ob_d.direction == "LONG":
            sl = ob_d.bottom + SL_PCT * (entry - ob_d.bottom)
        else:
            sl = ob_d.top - SL_PCT * (ob_d.top - entry)
        risk = abs(entry - sl)
        if MIN_SL_PCT > 0:
            min_dist = entry * MIN_SL_PCT / 100
            if ob_d.direction == "LONG":
                sl = min(sl, entry - min_dist)
            else:
                sl = max(sl, entry + min_dist)
            risk = abs(entry - sl)
        if risk <= 0: continue
        if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
            continue
        return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                "signal_time": df_w.index[k] + pd.Timedelta(minutes=15),
                "reaction_tf": "Marubozu-15m"}
    return None


# === Simulator (1m walk) ===

def simulate(setup, df_1m, rr=RR, max_hold_days=MAX_HOLD_DAYS):
    direction = setup["direction"]
    entry = setup["entry"]; sl = setup["sl"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    tp_proxy = entry + rr*risk if direction == "LONG" else entry - rr*risk  # same

    start = setup["signal_time"]
    end = start + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1]
    l = df_1m["low"].values[i0:i1]

    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre = np.where(h >= tp)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre = np.where(l <= tp)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else len(h) + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else len(h) + 1
    if tp_pre_i < ent_i: return ("no_entry", 0.0)
    if ent_i >= len(h): return ("not_filled", 0.0)
    post_h = h[ent_i:]; post_l = l[ent_i:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1: return ("open", 0.0)
    if sl_f == -1: return ("win", rr)
    if tp_f == -1: return ("loss", -1.0)
    if tp_f < sl_f: return ("win", rr)
    return ("loss", -1.0)


# === Driver ===

def main():
    print("etap_119: Wicked OB-D/12h + 5 reactions (BTC 6.3y)")
    print()
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    # Wicked OB collection
    print("[INFO] collecting wicked OBs")
    wicked_1d = collect_wicked_obs(df_1d, 24)
    wicked_12h = collect_wicked_obs(df_12h, 12)
    # Also collect ALL OBs (без wick filter) для контрольной группы
    all_1d = []
    all_12h = []
    for idx in range(2, len(df_1d) - 1):
        ob = detect_ob_pair(df_1d, idx)
        if ob is not None:
            all_1d.append(WickedOB(direction=ob.direction, bottom=ob.bottom, top=ob.top,
                                    prev_time=ob.prev_time, cur_time=ob.cur_time,
                                    cur_close=ob.cur_time + pd.Timedelta(hours=24),
                                    tf_hours=24, wick_ratio=0))
    for idx in range(2, len(df_12h) - 1):
        ob = detect_ob_pair(df_12h, idx)
        if ob is not None:
            all_12h.append(WickedOB(direction=ob.direction, bottom=ob.bottom, top=ob.top,
                                     prev_time=ob.prev_time, cur_time=ob.cur_time,
                                     cur_close=ob.cur_time + pd.Timedelta(hours=12),
                                     tf_hours=12, wick_ratio=0))
    print(f"  wicked 1d: {len(wicked_1d)} (of {len(all_1d)} total = {len(wicked_1d)/len(all_1d)*100:.1f}%)")
    print(f"  wicked 12h: {len(wicked_12h)} (of {len(all_12h)} total = {len(wicked_12h)/len(all_12h)*100:.1f}%)")
    print()

    # Run reactions
    reactions = [
        ("V1: OB-htf + FVG-entry (standard)", lambda od, tt, it: react_v1_ob_fvg(od, tt, it, df_1h, df_2h, df_15m, df_20m)),
        ("V2: FVG-entry only",                 lambda od, tt, it: react_v2_fvg_only(od, tt, it, df_15m, df_20m)),
        ("V3: RDRB-htf",                       lambda od, tt, it: react_v3_rdrb_htf(od, tt, it, df_1h, df_2h)),
        ("V4: OB-htf only (no inner FVG)",     lambda od, tt, it: react_v4_ob_only(od, tt, it, df_1h, df_2h)),
        ("V5: Marubozu-15m",                   lambda od, tt, it: react_v5_marubozu(od, tt, it, df_15m)),
    ]

    print(f"  {'OB-filter':<15} {'Reaction':<42} {'sigs':>4} {'closed':>6} {'WR':>5} {'PnL':>8} {'bad':>4}")
    print("  " + "-"*100)
    results = []
    for filter_name, ob_list_1d, ob_list_12h in [
        ("wicked", wicked_1d, wicked_12h),
        ("all", all_1d, all_12h),
    ]:
        for r_label, r_fn in reactions:
            trades = []
            for ob_list, df_l1 in [(ob_list_1d, df_1d), (ob_list_12h, df_12h)]:
                for ob_d in ob_list:
                    touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
                    if touch_t is None: continue
                    if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)  # 3-week max
                    setup = r_fn(ob_d, touch_t, inval_t)
                    if setup is None: continue
                    outcome, R = simulate(setup, df_1m)
                    setup["outcome"] = outcome; setup["R"] = R
                    setup["year"] = setup["signal_time"].year
                    trades.append(setup)
            # Dedup
            seen = {}
            for t in trades:
                k = (t["signal_time"], t["direction"], round(t["entry"], 2))
                if k not in seen: seen[k] = t
            unique = list(seen.values())
            closed = [t for t in unique if t["outcome"] in ("win", "loss")]
            n = len(closed)
            if n == 0:
                print(f"  {filter_name:<15} {r_label:<42} {len(unique):>4d} {n:>6d}  no_data")
                continue
            W = sum(1 for t in closed if t["R"] > 0)
            L_ = sum(1 for t in closed if t["R"] < 0)
            wr = W / n * 100
            pnl = sum(t["R"] for t in closed)
            yr_map = defaultdict(float)
            for t in closed: yr_map[t["year"]] += t["R"]
            bad = sum(1 for v in yr_map.values() if v < 0)
            n_yrs = len(yr_map)
            print(f"  {filter_name:<15} {r_label:<42} {len(unique):>4d} {n:>6d} {wr:>4.1f}% {pnl:>+7.1f}R {bad}/{n_yrs}")
            results.append({"filter": filter_name, "react": r_label, "sigs": len(unique),
                            "n": n, "wr": wr, "pnl": pnl, "bad": bad, "n_yrs": n_yrs})

    # Ranking
    print()
    print("=" * 100)
    print("RANKED by PnL (closed >= 15)")
    print("=" * 100)
    valid = [r for r in results if r["n"] >= 15]
    by_pnl = sorted(valid, key=lambda r: r["pnl"], reverse=True)
    for r in by_pnl:
        print(f"  {r['filter']:<10} | {r['react']:<42} | n={r['n']:>3d}  WR={r['wr']:>4.1f}%  "
              f"PnL={r['pnl']:>+6.1f}R  bad={r['bad']}/{r['n_yrs']}")


if __name__ == "__main__":
    main()
