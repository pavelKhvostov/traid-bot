"""Этап 25: deepdive новых high-freq кандидатов из etap_24 анализа.

E1 = OB-4h x FVG-1h ALL RR=1.0  (без pro-filter)
       Цифры: WR 54.5%, +124R, 6.38/нед, R/tr 0.090, R/year 19.6 (max в гриде)
       vs C1 (pro): WR 58%, +103R — pro меньший total
E2 = FRSWEEP-6h x FVG-15m ALL RR=1.0
       Цифры: WR 54.2%, +72R, 3.18/нед, R/tr 0.085, R/year 11.4
       vs C5 (FRSWEEP-4h ×FVG-15m pro): WR 53%, +51R, 3.20/нед, R/tr 0.064 — 6h лучше

Год-by-год + LONG/SHORT + outlier для проверки стабильности.
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
SL_BUF_ATR = 0.3
MIN_SL_PCT = 1.0

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                "2h": 3, "1h": 2, "15m": 1}
FRSWEEP_LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 5, "4h": 3}
OUT_DIR = Path("research/elements_study/output")

CANDIDATES = [
    {"id": "E1", "name": "OB-4h x FVG-1h ALL (no pro filter) RR=1.0",
     "anchor_kind": "OB", "anchor_tf": "4h",
     "trigger_kind": "FVG", "trigger_tf": "1h",
     "filter": "all", "rr": 1.0},
    {"id": "E2", "name": "FRSWEEP-6h x FVG-15m ALL RR=1.0",
     "anchor_kind": "FRSWEEP", "anchor_tf": "6h",
     "trigger_kind": "FVG", "trigger_tf": "15m",
     "filter": "all", "rr": 1.0},
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


def collect_frsweep(df, atr_series, tf_label, lookahead=30):
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
                    out.append({"time": times[j], "idx": j,
                                "direction": "LONG",
                                "bottom": zb, "top": zt, "atr": atr,
                                "tf": tf_label})
                    break
        else:
            level = h
            for j in range(confirm_idx + 1, min(confirm_idx + 1 + lookahead, len(df) - 1)):
                if highs[j] >= level and closes[j] < level:
                    atr = float(atr_series.iloc[j])
                    if pd.isna(atr) or atr <= 0: break
                    zb = float(closes[j]); zt = float(highs[j])
                    if zt <= zb: break
                    out.append({"time": times[j], "idx": j,
                                "direction": "SHORT",
                                "bottom": zb, "top": zt, "atr": atr,
                                "tf": tf_label})
                    break
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def evaluate(c, anchors, triggers, df_trig, sim):
    if c["anchor_kind"] == "FRSWEEP":
        a_tf_td = pd.Timedelta(c["anchor_tf"])
        a_life = pd.Timedelta(days=FRSWEEP_LIFE_DAYS.get(c["anchor_tf"], 5))
    else:
        a_tf_td = pd.Timedelta(c["anchor_tf"])
        a_life = pd.Timedelta(days=TF_LIFE_DAYS.get(c["anchor_tf"], 5))
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
            if c["filter"] == "pro" and not pro: continue
            entry = (t["bottom"] + t["top"]) / 2
            atr = t["atr"]; direction = t["direction"]
            if direction == "LONG":
                atr_sl = t["bottom"] - SL_BUF_ATR * atr
                sl = min(atr_sl, entry - entry * MIN_SL_PCT / 100)
            else:
                atr_sl = t["top"] + SL_BUF_ATR * atr
                sl = max(atr_sl, entry + entry * MIN_SL_PCT / 100)
            risk = abs(entry - sl)
            if risk <= 0: break
            if direction == "LONG":
                tp = entry + c["rr"] * risk
            else:
                tp = entry - c["rr"] * risk
            start = t["time"] + pd.Timedelta(c["trigger_tf"])
            outcome, R = sim.simulate(direction, entry, sl, tp, start,
                                        TF_LIFE_DAYS.get(c["trigger_tf"], 5))
            rows.append({"trigger_time": t["time"], "direction": direction,
                          "entry": entry, "sl": sl, "tp": tp,
                          "outcome": outcome, "R": R,
                          "year": t["time"].year})
            break
    return pd.DataFrame(rows)


def report(label, df):
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if closed.empty:
        print(f"  no closed for {label}"); return
    n_total = len(df); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    print(f"  totals: n={n_total}, closed={nc}, WR={w/nc*100:.1f}%, "
            f"total_R={closed['R'].sum():.1f}, R/tr={closed['R'].mean():.3f}")
    print(f"  --- year-by-year ---")
    yr_g = closed.groupby("year").agg(n=("R", "size"),
                                         wins=("outcome", lambda x: (x == "win").sum()),
                                         total_R=("R", "sum"))
    yr_g["WR"] = yr_g["wins"] / yr_g["n"] * 100
    yr_g["R_tr"] = yr_g["total_R"] / yr_g["n"]
    print(yr_g[["n", "WR", "total_R", "R_tr"]].round(2).to_string())
    print(f"  --- direction split ---")
    for d in ("LONG", "SHORT"):
        sub = closed[closed["direction"] == d]
        if not sub.empty:
            sub_w = (sub["outcome"] == "win").sum()
            print(f"    {d}: n={len(sub)}, WR={sub_w/len(sub)*100:.1f}%, "
                    f"total_R={sub['R'].sum():.1f}, R/tr={sub['R'].mean():.3f}")
    R_sorted = closed["R"].sort_values(ascending=False).to_numpy()
    total = R_sorted.sum()
    if len(R_sorted) >= 5:
        print(f"  --- outlier check ---")
        print(f"    total={total:.1f}, без top-5: {total-R_sorted[:5].sum():.1f}")


def main():
    t0 = time.time()
    print("[INFO] loading")
    needed = ["1h", "4h", "6h", "15m"]
    dfs = {}
    for tf in needed:
        df = load_df(SYMBOL, tf)
        df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")].copy()
        df["atr14"] = compute_atr(df, 14)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        dfs[tf] = df
        print(f"  {tf}: {len(df)} bars")
    df_1m = load_df(SYMBOL, "1m")
    df_1m = df_1m[df_1m.index >= pd.Timestamp(START_DATE, tz="UTC")]
    sim = FastSim(df_1m)

    obs_4h = collect_obs(dfs["4h"], dfs["4h"]["atr14"], "4h")
    fvgs_1h = collect_fvgs(dfs["1h"], dfs["1h"]["atr14"], "1h")
    frs_6h = collect_frsweep(dfs["6h"], dfs["6h"]["atr14"], "6h")
    fvgs_15m = collect_fvgs(dfs["15m"], dfs["15m"]["atr14"], "15m")
    print(f"  OB-4h: {len(obs_4h)}, FVG-1h: {len(fvgs_1h)}")
    print(f"  FRSWEEP-6h: {len(frs_6h)}, FVG-15m: {len(fvgs_15m)}")

    for c in CANDIDATES:
        print(f"\n{'='*70}\n{c['id']}: {c['name']}\n{'='*70}")
        if c["anchor_kind"] == "OB":
            anchors = obs_4h
        else:
            anchors = frs_6h
        triggers = fvgs_1h if c["trigger_tf"] == "1h" else fvgs_15m
        df = evaluate(c, anchors, triggers, dfs[c["trigger_tf"]], sim)
        df.to_csv(OUT_DIR / f"etap25_{c['id']}_trades.csv", index=False)
        report(c["name"], df)

    print(f"\n[TIME] total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
