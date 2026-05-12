"""Этап 20: deepdive финальных оптимизированных конфигов из etap_19.

После 3-stage оптимизации появились новые кандидаты с RR в твоём диапазоне 1.8-2.5:

  D1 = B3 OB-12h x FVG-2h pro, entry=0.5, sl_buf=0.15, min_sl=1.0, RR=2.5
       → 37.8% WR, +93.5R, R/tr 0.325 (max R/tr в диапазоне)
  D2 = B3 OB-12h x FVG-2h pro, entry=0.5, sl_buf=0.15, min_sl=1.0, RR=1.75
       → 47.2% WR, +89.5R, R/tr 0.297 (max total_R в диапазоне 1.5-2.0)
  D3 = B1 OB-4h x FVG-1h pro, entry=0.5, sl_buf=0.3, min_sl=1.0, RR=2.5
       → 33.0% WR, +116R, R/tr 0.154 (max total_R по всем)
  D4 = B1 OB-4h x FVG-1h pro, entry=0.5, sl_buf=0.3, min_sl=1.0, RR=2.0
       → 37.9% WR, +107R, R/tr 0.136 (твой fav RR диапазон)
  D5 = B4 FRACT2X x FVG-2h pro, entry=0.5, sl_buf=0.3, min_sl=1.0, RR=2.0 (для теста)

Для каждого: year-by-year, LONG/SHORT, outlier robustness.
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

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                "2h": 3, "1h": 2, "15m": 1}
FRACT2X_LIFE_DAYS = 14

OUT_DIR = Path("research/elements_study/output")

CANDIDATES = [
    {"id": "D1", "name": "OB-12h x FVG-2h pro RR=2.5 (max R/tr)",
     "anchor_kind": "OB", "anchor_tf": "12h",
     "trigger_kind": "FVG", "trigger_tf": "2h", "filter": "pro",
     "entry_pct": 0.5, "sl_buf": 0.15, "min_sl_pct": 1.0, "rr": 2.5},
    {"id": "D2", "name": "OB-12h x FVG-2h pro RR=1.75 (balanced)",
     "anchor_kind": "OB", "anchor_tf": "12h",
     "trigger_kind": "FVG", "trigger_tf": "2h", "filter": "pro",
     "entry_pct": 0.5, "sl_buf": 0.15, "min_sl_pct": 1.0, "rr": 1.75},
    {"id": "D3", "name": "OB-4h x FVG-1h pro RR=2.5 (max total)",
     "anchor_kind": "OB", "anchor_tf": "4h",
     "trigger_kind": "FVG", "trigger_tf": "1h", "filter": "pro",
     "entry_pct": 0.5, "sl_buf": 0.3, "min_sl_pct": 1.0, "rr": 2.5},
    {"id": "D4", "name": "OB-4h x FVG-1h pro RR=2.0",
     "anchor_kind": "OB", "anchor_tf": "4h",
     "trigger_kind": "FVG", "trigger_tf": "1h", "filter": "pro",
     "entry_pct": 0.5, "sl_buf": 0.3, "min_sl_pct": 1.0, "rr": 2.0},
    {"id": "D5", "name": "FRACT2X-1d+4h x FVG-2h pro RR=2.0",
     "anchor_kind": "FRACT2X", "anchor_tf": "1d+4h",
     "trigger_kind": "FVG", "trigger_tf": "2h", "filter": "pro",
     "entry_pct": 0.5, "sl_buf": 0.3, "min_sl_pct": 1.0, "rr": 2.0},
]


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


def build_and_eval(anchors, triggers, df_trig, anchor_tf, trigger_tf, filt,
                    anchor_kind, entry_pct, sl_buf, min_sl_pct, rr, sim):
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
    rows = []
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
            direction = t["direction"]
            zb = t["bottom"]; zt = t["top"]; atr = t["atr"]
            size = zt - zb
            if direction == "LONG":
                entry = zb + entry_pct * size
                atr_sl = zb - sl_buf * atr
                sl = min(atr_sl, entry - entry * min_sl_pct / 100)
            else:
                entry = zt - entry_pct * size
                atr_sl = zt + sl_buf * atr
                sl = max(atr_sl, entry + entry * min_sl_pct / 100)
            risk = abs(entry - sl)
            if risk <= 0: break
            if direction == "LONG":
                tp = entry + rr * risk
            else:
                tp = entry - rr * risk
            start = t["time"] + pd.Timedelta(trigger_tf)
            outcome, R = sim.simulate(direction, entry, sl, tp, start,
                                        TF_LIFE_DAYS.get(trigger_tf, 5))
            rows.append({"trigger_time": t["time"], "direction": direction,
                          "entry": entry, "sl": sl, "tp": tp, "risk": risk,
                          "outcome": outcome, "R": R,
                          "year": t["time"].year})
            break
    return pd.DataFrame(rows)


def report(label, df):
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if closed.empty:
        print(f"  no closed for {label}")
        return
    n_total = len(df); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    print(f"  totals: n={n_total}, closed={nc}, WR={w/nc*100:.1f}%, "
            f"total_R={closed['R'].sum():.1f}, R/tr={closed['R'].mean():.3f}")
    # year
    print(f"  --- year-by-year ---")
    yr_g = closed.groupby("year").agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"))
    yr_g["WR"] = yr_g["wins"] / yr_g["n"] * 100
    yr_g["R_tr"] = yr_g["total_R"] / yr_g["n"]
    print(yr_g[["n", "WR", "total_R", "R_tr"]].round(2).to_string())
    # direction
    print(f"  --- direction split ---")
    for d in ("LONG", "SHORT"):
        sub = closed[closed["direction"] == d]
        if not sub.empty:
            sub_w = (sub["outcome"] == "win").sum()
            print(f"    {d}: n={len(sub)}, WR={sub_w/len(sub)*100:.1f}%, "
                    f"total_R={sub['R'].sum():.1f}, R/tr={sub['R'].mean():.3f}")
    # outlier
    R_sorted = closed["R"].sort_values(ascending=False).to_numpy()
    total = R_sorted.sum()
    if len(R_sorted) >= 5:
        print(f"  --- outlier check ---")
        print(f"    total={total:.1f}, без top-1: {total-R_sorted[0]:.1f}, "
                f"без top-3: {total-R_sorted[:3].sum():.1f}, "
                f"без top-5: {total-R_sorted[:5].sum():.1f}")
    big_wins = (closed["R"] >= 1.8).sum()
    losses = (closed["R"] < 0).sum()
    print(f"    wins>=1.8R: {big_wins}, losses: {losses}")


def main():
    t0 = time.time()
    print("[INFO] loading")
    needed_tfs = {c["anchor_tf"] for c in CANDIDATES} | {c["trigger_tf"] for c in CANDIDATES}
    needed_tfs.discard("1d+4h")
    if any(c["anchor_kind"] == "FRACT2X" for c in CANDIDATES):
        needed_tfs.update({"1d", "4h"})
    needed_tfs = sorted(needed_tfs, key=lambda x: pd.Timedelta(x))
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

    obs_cache = {}; fvgs_cache = {}; fract2x = None
    for c in CANDIDATES:
        if c["anchor_kind"] == "OB" and c["anchor_tf"] not in obs_cache:
            tf = c["anchor_tf"]
            obs_cache[tf] = collect_obs(dfs[tf], dfs[tf]["atr14"], tf)
        if c["trigger_tf"] not in fvgs_cache:
            tf = c["trigger_tf"]
            fvgs_cache[tf] = collect_fvgs(dfs[tf], dfs[tf]["atr14"], tf)
    if any(c["anchor_kind"] == "FRACT2X" for c in CANDIDATES):
        frs1d = collect_fractals(dfs["1d"], dfs["1d"]["atr14"], "1d")
        frs4h = collect_fractals(dfs["4h"], dfs["4h"]["atr14"], "4h")
        fract2x = collect_fract2x(frs1d, frs4h)

    for c in CANDIDATES:
        print(f"\n{'='*70}\n{c['id']}: {c['name']}")
        print(f"  entry={c['entry_pct']}, sl_buf={c['sl_buf']}, "
                f"min_sl={c['min_sl_pct']}%, RR={c['rr']}")
        print(f"{'='*70}")
        anchors = (obs_cache[c["anchor_tf"]] if c["anchor_kind"] == "OB"
                   else fract2x)
        triggers = fvgs_cache[c["trigger_tf"]]
        df = build_and_eval(anchors, triggers, dfs[c["trigger_tf"]],
                              c["anchor_tf"], c["trigger_tf"], c["filter"],
                              c["anchor_kind"],
                              c["entry_pct"], c["sl_buf"], c["min_sl_pct"],
                              c["rr"], sim)
        df.to_csv(OUT_DIR / f"etap20_{c['id']}_trades.csv", index=False)
        report(c["name"], df)

    print(f"\n[TIME] total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
