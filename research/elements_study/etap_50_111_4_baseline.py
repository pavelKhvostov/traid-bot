"""Этап 50: Strategy 1.1.4 (новое определение) — baseline.

Cascade:
  L1 anchor:  FVG-{1d, 12h}      ← макро-FVG как «контейнер» (vs 1.1.1 где OB)
  L2 macro:   OB-{4h, 6h}         ← внутри L1, same direction
  L3 mid:     OB-{1h, 2h}         ← внутри L2 ∩ L1
  L4 trigger: FVG-{15m, 20m}     ← внутри L3, same direction

Эталон 1.1.1: OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m}
1.1.4 (новая): FVG-{1d,12h} + OB-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m}
                ^^ макро поменян ^^

Параметры (как в 1.1.2 USER):
  entry = 0.70 of FVG-15m, sl_pct_long=0.35 / sl_pct_short=0.65
  min_sl = 1%, RR varies

Сценарии:
  V1: 6.33y baseline, RR=1.0/1.5/1.8/2.0/2.5
  V2: + SWEPT filter
  V3: comparison ALL vs SWEPT
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ENTRY_PCT = 0.70
USER_SL_LONG = 0.35
USER_SL_SHORT = 0.65
MIN_SL_PCT = 1.0

# TF lifetimes (max distance between cascade levels in days)
LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 4, "4h": 3,
              "2h": 1.5, "1h": 1, "15m": 0.5, "20m": 0.5}

TF_HOURS = {"1d": 24, "12h": 12, "6h": 6, "4h": 4,
             "2h": 2, "1h": 1, "20m": 1/3, "15m": 0.25}

OUT_DIR = Path("research/elements_study/output")


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ---------- zone collectors ----------

def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"kind": "OB", "tf": tf, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": a,
                     "time": ob.cur_time, "idx": idx,
                     "prev_time": ob.prev_time})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"kind": "FVG", "tf": tf, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": a,
                     "time": f.c2_time, "idx": idx, "c0_time": f.c0_time})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


# ---------- 1.1.4 chain detection ----------

def detect_114_chain(fvgs_top, obs_macro, obs_mid, fvgs_entry,
                       top_tf, macro_tf, mid_tf, entry_tf):
    """1.1.4 cascade: FVG-top → OB-macro → OB-mid → FVG-entry.

    All same direction, all zones overlap, with anchor-confirm fix:
      L1 FVG-top confirmed at c2_time + top_tf
      L2 OB-macro confirmed at cur_time + macro_tf
      L3 OB-mid confirmed at cur_time + mid_tf
      L4 FVG-entry trigger at c2_time
    """
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    entry_td = pd.Timedelta(hours=TF_HOURS[entry_tf])

    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    macro_life = pd.Timedelta(days=LIFE_DAYS[macro_tf])
    mid_life = pd.Timedelta(days=LIFE_DAYS[mid_tf])

    obs_macro_sorted = sorted(obs_macro, key=lambda x: x["time"])
    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["time"])

    obs_macro_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                  for z in obs_macro_sorted])
    obs_mid_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                for z in obs_mid_sorted])
    fvgs_entry_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                   for z in fvgs_entry_sorted])

    for fvg_top in fvgs_top:
        # L1 anchor: FVG-top подтверждён в c2_time + top_tf (= c2 close)
        l1_confirm = fvg_top["time"] + top_td
        l1_end = fvg_top["time"] + top_life
        if l1_end <= l1_confirm: continue

        # L2 search: OB-macro в окне [l1_confirm, l1_end] same dir, overlap with L1
        i0 = np.searchsorted(obs_macro_times, np.datetime64(
            l1_confirm.tz_localize(None) if l1_confirm.tz else l1_confirm),
            side="right")
        i1 = np.searchsorted(obs_macro_times, np.datetime64(
            l1_end.tz_localize(None) if l1_end.tz else l1_end), side="right")

        for mi in range(i0, i1):
            ob_macro = obs_macro_sorted[mi]
            if ob_macro["direction"] != fvg_top["direction"]: continue
            if not zones_overlap(ob_macro["bottom"], ob_macro["top"],
                                  fvg_top["bottom"], fvg_top["top"]):
                continue

            l2_confirm = ob_macro["time"] + macro_td
            l2_end = ob_macro["time"] + macro_life
            if l2_end <= l2_confirm: continue

            # L3: OB-mid в [l2_confirm, l2_end] same dir, overlap with L1 AND L2
            j0 = np.searchsorted(obs_mid_times, np.datetime64(
                l2_confirm.tz_localize(None) if l2_confirm.tz else l2_confirm),
                side="right")
            j1 = np.searchsorted(obs_mid_times, np.datetime64(
                l2_end.tz_localize(None) if l2_end.tz else l2_end), side="right")
            ob_mid_found = None
            for oj in range(j0, j1):
                ob_mid = obs_mid_sorted[oj]
                if ob_mid["direction"] != fvg_top["direction"]: continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      ob_macro["bottom"], ob_macro["top"]): continue
                ob_mid_found = ob_mid; break
            if ob_mid_found is None: continue

            l3_confirm = ob_mid_found["time"] + mid_td
            l3_end = ob_mid_found["time"] + mid_life
            if l3_end <= l3_confirm: continue

            # L4: FVG-entry в [l3_confirm, l3_end] same dir, overlap with ob_mid
            k0 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_confirm.tz_localize(None) if l3_confirm.tz else l3_confirm),
                side="right")
            k1 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_end.tz_localize(None) if l3_end.tz else l3_end), side="right")
            fvg_entry_found = None
            for ek in range(k0, k1):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["direction"] != fvg_top["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"], ob_mid_found["top"]):
                    continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue

            tf_minutes = 15 if entry_tf == "15m" else 20
            setups.append({
                "anchor_time": fvg_top["time"],
                "anchor_kind": "FVG",
                "anchor_tf": top_tf,
                "macro_tf": macro_tf,
                "mid_tf": mid_tf,
                "entry_tf": entry_tf,
                "trigger_time": fvg_entry_found["time"],
                "trigger": fvg_entry_found,
                "ob_mid": ob_mid_found,    # для SWEPT-check позже
                "tf_minutes": tf_minutes,
                "year": fvg_entry_found["time"].year,
                "direction": fvg_entry_found["direction"],
                "fvg_b": fvg_entry_found["bottom"],
                "fvg_t": fvg_entry_found["top"],
                "obh_b": ob_mid_found["bottom"],
                "obh_t": ob_mid_found["top"],
                "signal_time": fvg_entry_found["time"],
            })
            break  # dedup: первая FVG-entry на каждый OB-mid → первый OB-mid на каждый OB-macro → первый OB-macro на каждый FVG-top
    return setups


def build_orders_user(s):
    direction = s["direction"]
    fb, ft = s["fvg_b"], s["fvg_t"]
    obb, obt = s["obh_b"], s["obh_t"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl_lo = obb; sl_hi = fb
        sl = sl_lo + USER_SL_LONG * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = min(sl, entry - entry * MIN_SL_PCT / 100)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl_hi = obt; sl_lo = ft
        sl = sl_hi - USER_SL_SHORT * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = max(sl, entry + entry * MIN_SL_PCT / 100)
        if sl <= entry: return None
    return entry, sl


def simulate_safe(s, entry, sl, tp, df_1m, max_hold_days=7):
    """SAFE simulator с no_entry и not_filled."""
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tf_min = s["tf_minutes"]
    entry_window_start = s["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = entry_window_start + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_window_start.tz_localize(None)
                          if entry_window_start.tz else entry_window_start)
    ee64 = np.datetime64(end_time.tz_localize(None)
                          if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre_idxs = np.where(h >= tp)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre_idxs = np.where(l <= tp)[0]
    ent_idx = int(ent_idxs[0]) if ent_idxs.size else len(h) + 1
    tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else len(h) + 1
    if tp_pre < ent_idx:
        return ("no_entry", 0.0)
    if ent_idx >= len(h): return ("not_filled", 0.0)
    post_h = h[ent_idx:]; post_l = l[ent_idx:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_first == -1 and tp_first == -1: return ("open", 0.0)
    if sl_first == -1: return ("win", abs(tp - entry) / risk)
    if tp_first == -1: return ("loss", -1.0)
    if tp_first < sl_first:
        return ("win", abs(tp - entry) / risk)
    return ("loss", -1.0)


def evaluate(setups, rr, df_1m):
    rows = []
    for s in setups:
        tup = build_orders_user(s)
        if tup is None: continue
        entry, sl = tup
        risk = abs(entry - sl)
        tp = entry + rr * risk if s["direction"] == "LONG" else entry - rr * risk
        outcome, R = simulate_safe(s, entry, sl, tp, df_1m)
        rows.append({**s, "entry": entry, "sl": sl, "tp": tp,
                      "outcome": outcome, "R": R})
    return pd.DataFrame(rows)


def report(label, df):
    cl = df[df["outcome"].isin(["win", "loss"])]
    n_total = len(df)
    n_no_entry = (df["outcome"] == "no_entry").sum()
    n_not_filled = (df["outcome"] == "not_filled").sum()
    if cl.empty:
        print(f"  {label}: no closed (n_total={n_total}, no_entry={n_no_entry})"); return
    nc = len(cl)
    wins = (cl["R"] > 0).sum()
    wr = wins / nc * 100
    tot = cl["R"].sum()
    rt = cl["R"].mean()
    yr = cl.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    print(f"  {label}")
    print(f"    n_total={n_total}, no_entry={n_no_entry}, not_filled={n_not_filled}, closed={nc}")
    print(f"    WR={wr:.1f}%  total={tot:+.1f}R  R/tr={rt:+.3f}  bad_yrs={bad}/{len(yr)}  "
          f"freq={n_total/6.33/52:.2f}/wk")


def main():
    t0 = time.time()
    print(f"[INFO] загружаем данные с {START_DATE}")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")

    for df in [df_1d, df_4h, df_1h, df_12h, df_6h, df_2h, df_15m, df_20m]:
        df = df.copy()  # avoid SettingWithCopy

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("20m", df_20m), ("15m", df_15m)]:
        df["atr14"] = compute_atr(df, 14)
    years = (df_1d.index[-1] - df_1d.index[0]).days / 365
    print(f"  лет: {years:.2f}")

    print(f"\n[INFO] собираем зоны для 1.1.4 cascade")
    fvgs = {}
    obs = {}
    for tf, df in [("1d", df_1d), ("12h", df_12h)]:
        fvgs[tf] = collect_fvgs(df, df["atr14"], tf)
        print(f"  FVG-{tf}: {len(fvgs[tf])}")
    for tf, df in [("6h", df_6h), ("4h", df_4h)]:
        obs[tf] = collect_obs(df, df["atr14"], tf)
        print(f"  OB-{tf}: {len(obs[tf])}")
    for tf, df in [("2h", df_2h), ("1h", df_1h)]:
        obs[tf] = collect_obs(df, df["atr14"], tf)
        print(f"  OB-{tf}: {len(obs[tf])}")
    for tf, df in [("20m", df_20m), ("15m", df_15m)]:
        fvgs[tf] = collect_fvgs(df, df["atr14"], tf)
        print(f"  FVG-{tf}: {len(fvgs[tf])}")

    print(f"\n[INFO] detect 1.1.4 chains (8 combos)")
    all_setups = []
    chain_count = {}
    for top_tf in ["1d", "12h"]:
        for macro_tf in ["4h", "6h"]:
            for mid_tf in ["1h", "2h"]:
                for entry_tf in ["15m"]:  # 20m тоже можно, но для скорости 15m only
                    chains = detect_114_chain(
                        fvgs[top_tf], obs[macro_tf], obs[mid_tf], fvgs[entry_tf],
                        top_tf, macro_tf, mid_tf, entry_tf)
                    key = f"{top_tf}-{macro_tf}-{mid_tf}-{entry_tf}"
                    chain_count[key] = len(chains)
                    all_setups.extend(chains)
    print(f"  chains:")
    for k, v in chain_count.items():
        print(f"    {k}: {v}")

    # Dedup by (signal_time, direction, fvg_b, fvg_t)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  total chains: {len(all_setups)}, deduped: {len(unique)}")

    # ============================================================
    print(f"\n{'='*70}\n1.1.4 BASELINE — USER params (entry=0.7, sl=0.35/0.65, min_sl=1%)")
    print(f"{'='*70}")
    print(f"  Frequency: {len(unique)/years/52:.2f} setups/нед\n")
    for rr in [1.0, 1.5, 1.8, 2.0, 2.5, 3.0]:
        df = evaluate(unique, rr, df_1m)
        report(f"RR={rr}", df)

    # Year-by-year for RR=1.8 (best baseline candidate)
    print(f"\n{'='*70}\n1.1.4 YEAR-BY-YEAR @ RR=1.8")
    print(f"{'='*70}")
    df_18 = evaluate(unique, 1.8, df_1m)
    cl_18 = df_18[df_18["outcome"].isin(["win", "loss"])]
    yr = cl_18.groupby("year").agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"))
    yr["WR"] = yr["wins"] / yr["n"] * 100
    yr["R_tr"] = yr["total_R"] / yr["n"]
    for y, r in yr.iterrows():
        flag = "  !" if r["total_R"] < 0 else ""
        print(f"  {int(y)}: n={int(r['n']):>3} WR={r['WR']:5.1f}% "
              f"total={r['total_R']:+5.1f}R R/tr={r['R_tr']:+.3f}{flag}")

    # LONG vs SHORT split
    print(f"\n{'='*70}\nLONG vs SHORT split @ RR=1.8")
    print(f"{'='*70}")
    for direction in ["LONG", "SHORT"]:
        sub = cl_18[cl_18["direction"] == direction]
        if sub.empty: continue
        wr = (sub["R"] > 0).mean() * 100
        print(f"  {direction}: n={len(sub):>3} WR={wr:5.1f}% "
              f"total={sub['R'].sum():+5.1f}R R/tr={sub['R'].mean():+.3f}")

    # Save trades
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_out = OUT_DIR / "etap50_114_baseline_trades_RR18.csv"
    df_18.to_csv(csv_out, index=False, encoding="utf-8-sig")
    print(f"\n[OK] CSV: {csv_out}")

    # ============================================================
    # COMPARE to 1.1.1 and 1.1.2 baselines
    # ============================================================
    print(f"\n{'='*70}\nСРАВНЕНИЕ С СОСЕДНИМИ СТРАТЕГИЯМИ (BTC 6.33y, USER params, RR=1.8)")
    print(f"{'='*70}")
    cl_18_n = len(cl_18)
    cl_18_wr = (cl_18["R"] > 0).mean() * 100 if cl_18_n else 0
    cl_18_R = cl_18["R"].sum()
    print(f"  Strategy 1.1.1 SWEPT (etap_40 V3):     RR=2.5  +45.5R / 7.2R/y")
    print(f"  Strategy 1.1.2 baseline (etap_45 V3):  RR=1.8  +78.4R / 12.4R/y / 0 bad yrs")
    print(f"  Strategy 1.1.4 (этот скрипт):          RR=1.8  {cl_18_R:+.1f}R / "
          f"{cl_18_R/years:+.1f}R/y  WR={cl_18_wr:.1f}%  n={cl_18_n}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
