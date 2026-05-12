"""Этап 15: deep-dive топ-3 победителей grid'а из etap_14.

Кандидаты (без size-фильтра, dedup first, min_sl=1%):
  T1 — OB-6h  + FVG-15m, all, RR=1.5  (WR 58.7%, +559.5R, 5.61/нед, R/tr 0.467) [max total]
  T2 — OB-12h + FVG-15m, all, RR=1.0  (WR 77.7%, +329R,   2.76/нед, R/tr 0.555) [max WR]
  T3 — OB-1d  + FVG-15m, all, RR=2.0  (WR 67.4%, +285R,   1.45/нед, R/tr 1.022) [max R/tr]

Что проверяем:
  1. Year-by-year breakdown — выгорает ли edge в 2024-2025 (как было с OB-4h+FVG-1h)
  2. Outlier robustness: убрать топ-1 R и топ-3 R, посмотреть деградацию
  3. Direction split: LONG vs SHORT — у одного направления может быть весь edge
  4. Distribution of R: сколько трейдов больше 5R / -1R, доля больших побед
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
MIN_SL_PCT = 1.0
SL_BUF_ATR = 0.3

TF_LIFE_DAYS = {"1d": 30, "12h": 14, "6h": 10, "4h": 5,
                "2h": 3, "1h": 2, "15m": 1}
FRSWEEP_LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 5, "4h": 3}
FRACT2X_LIFE_DAYS = 14

OUT_DIR = Path("research/elements_study/output")

CANDIDATES = [
    # После фикса lookahead — реальные топ-кандидаты:
    {"id": "C1", "anchor_kind": "OB", "anchor_tf": "4h",
     "trigger_kind": "FVG", "trigger_tf": "1h",
     "rr": 1.0, "filter": "pro"},  # winner: WR 58%, 3.43/нед, +116R
    {"id": "C2", "anchor_kind": "OB", "anchor_tf": "6h",
     "trigger_kind": "FVG", "trigger_tf": "2h",
     "rr": 1.0, "filter": "pro"},  # WR 56.1%, 2.33/нед, +57R
    {"id": "C3", "anchor_kind": "OB", "anchor_tf": "12h",
     "trigger_kind": "FVG", "trigger_tf": "2h",
     "rr": 1.0, "filter": "pro"},  # WR 60.3%, 1.11/нед, +49R
    {"id": "C4", "anchor_kind": "OB", "anchor_tf": "12h",
     "trigger_kind": "FVG", "trigger_tf": "2h",
     "rr": 1.5, "filter": "pro"},  # max R/trade: WR 51.7%, +68.5R, R/tr 0.293
    {"id": "C5", "anchor_kind": "FRSWEEP", "anchor_tf": "4h",
     "trigger_kind": "FVG", "trigger_tf": "15m",
     "rr": 1.0, "filter": "pro"},  # NEW: fractal+sweep anchor, WR 56.2%, +46R
    {"id": "C6", "anchor_kind": "FRACT2X", "anchor_tf": "1d+4h",
     "trigger_kind": "FVG", "trigger_tf": "2h",
     "rr": 1.0, "filter": "pro"},  # NEW best WR: multi-TF confluence, WR 64.6%, +61R, R/tr 0.292
    {"id": "C7", "anchor_kind": "FRACT2X", "anchor_tf": "1d+4h",
     "trigger_kind": "FVG", "trigger_tf": "2h",
     "rr": 1.5, "filter": "pro"},  # NEW: same setup RR=1.5: 51.7% WR, +59.5R, R/tr 0.293
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
        if i1 <= i0:
            return ("no_data", 0.0, None)
        h = self.high[i0:i1]; l = self.low[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0:
            return ("invalid", 0.0, None)
        if direction == "LONG":
            act_mask = l <= entry
            if not act_mask.any():
                return ("not_filled", 0.0, None)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = l2 <= sl; tp_hits = h2 >= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2):
                return ("open", 0.0, None)
            close_ts = pd.Timestamp(self.ts[i0 + act_idx + min(sl_idx, tp_idx)])
            if sl_idx <= tp_idx:
                return ("loss", -1.0, close_ts)
            return ("win", (tp - entry) / risk, close_ts)
        else:
            act_mask = h >= entry
            if not act_mask.any():
                return ("not_filled", 0.0, None)
            act_idx = int(np.argmax(act_mask))
            h2 = h[act_idx:]; l2 = l[act_idx:]
            sl_hits = h2 >= sl; tp_hits = l2 <= tp
            sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(h2)
            tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(h2)
            if sl_idx == len(h2) and tp_idx == len(h2):
                return ("open", 0.0, None)
            close_ts = pd.Timestamp(self.ts[i0 + act_idx + min(sl_idx, tp_idx)])
            if sl_idx <= tp_idx:
                return ("loss", -1.0, close_ts)
            return ("win", (entry - tp) / risk, close_ts)


def collect_obs(df_anchor, atr_series, tf_label):
    out = []
    for idx in range(2, len(df_anchor) - 1):
        ob = detect_ob_pair(df_anchor, idx)
        if ob is None:
            continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        out.append({"time": ob.cur_time, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": atr,
                     "tf": tf_label, "idx": idx})
    return out


def collect_fvgs(df_trig, atr_series, tf_label):
    out = []
    for idx in range(2, len(df_trig) - 1):
        f = detect_fvg(df_trig, idx)
        if f is None:
            continue
        atr = float(atr_series.iloc[idx])
        if pd.isna(atr) or atr <= 0:
            continue
        out.append({"time": f.c2_time, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": atr,
                     "tf": tf_label, "idx": idx})
    return out


def collect_fractals(df, atr_series, tf_label):
    """FH/FL по правилу Bill Williams i±2."""
    out = []
    lows = df["low"].to_numpy(); highs = df["high"].to_numpy()
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
        out.append({"time": times[i], "idx": i,
                    "direction": "LONG" if is_fl else "SHORT",
                    "bottom": float(l), "top": float(h),
                    "level": float(l) if is_fl else float(h),
                    "atr": atr, "tf": tf_label})
    return out


def collect_fract2x(frs1d, frs4h):
    """Multi-TF fractal confluence: 1d-фрактал + 4h-фрактал того же направления
    с levels близки (within 1×ATR_4h) И активны одновременно (4h в окне 14d после 1d).
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
            if f2["direction"] != f1["direction"]: continue
            if abs(f1["level"] - f2["level"]) > f2["atr"]: continue
            zb = max(f1["bottom"], f2["bottom"])
            zt = min(f1["top"], f2["top"])
            if zt <= zb:
                zb = min(f1["bottom"], f2["bottom"])
                zt = max(f1["top"], f2["top"])
            f2_confirm = f2["time"] + 3 * pd.Timedelta("4h")
            anchor_time = max(f1_confirm, f2_confirm)
            out.append({"time": anchor_time, "idx": -1,
                        "direction": f1["direction"],
                        "bottom": zb, "top": zt, "atr": f2["atr"],
                        "tf": "1d+4h"})
    return out


def collect_frsweep(df, atr_series, tf_label, lookahead=30):
    """Fractal + sweep candle (как в etap_17). Anchor = sweep candle close."""
    out = []
    lows = df["low"].to_numpy()
    highs = df["high"].to_numpy()
    closes = df["close"].to_numpy()
    times = df.index
    for i in range(2, len(df) - 2 - lookahead):
        h = highs[i]; l = lows[i]
        is_fl = (l < lows[i-2] and l < lows[i-1] and
                 l < lows[i+1] and l < lows[i+2])
        is_fh = (h > highs[i-2] and h > highs[i-1] and
                 h > highs[i+1] and h > highs[i+2])
        if not (is_fl or is_fh) or (is_fl and is_fh):
            continue
        confirm_idx = i + 2
        if is_fl:
            level = l
            for j in range(confirm_idx + 1, min(confirm_idx + 1 + lookahead, len(df) - 1)):
                if lows[j] <= level and closes[j] > level:
                    atr = float(atr_series.iloc[j])
                    if pd.isna(atr) or atr <= 0: break
                    zb = float(lows[j]); zt = float(closes[j])
                    if zt <= zb: break
                    out.append({"time": times[j], "direction": "LONG",
                                "bottom": zb, "top": zt, "atr": atr,
                                "tf": tf_label, "idx": j})
                    break
        else:
            level = h
            for j in range(confirm_idx + 1, min(confirm_idx + 1 + lookahead, len(df) - 1)):
                if highs[j] >= level and closes[j] < level:
                    atr = float(atr_series.iloc[j])
                    if pd.isna(atr) or atr <= 0: break
                    zb = float(closes[j]); zt = float(highs[j])
                    if zt <= zb: break
                    out.append({"time": times[j], "direction": "SHORT",
                                "bottom": zb, "top": zt, "atr": atr,
                                "tf": tf_label, "idx": j})
                    break
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def build_setups(anchors, triggers, df_trig, anchor_tf, trigger_tf, filt,
                  anchor_kind="OB"):
    """Dedup first-trigger-per-anchor + опционально pro-trend.
    FIX: anchor confirmed at cur_close = cur_open + tf_anchor."""
    if anchor_kind == "FRSWEEP":
        a_tf_td = pd.Timedelta(anchor_tf)
        a_life = pd.Timedelta(days=FRSWEEP_LIFE_DAYS.get(anchor_tf, 3))
    elif anchor_kind == "FRACT2X":
        a_tf_td = pd.Timedelta(0)  # уже учтён в a["time"] при collect_fract2x
        a_life = pd.Timedelta(days=FRACT2X_LIFE_DAYS)
    else:
        a_tf_td = pd.Timedelta(anchor_tf)
        a_life = pd.Timedelta(days=TF_LIFE_DAYS.get(anchor_tf, 5))
    t_sorted = sorted(triggers, key=lambda x: x["time"])
    t_times = np.array([np.datetime64(t["time"].tz_localize(None) if t["time"].tz else t["time"])
                         for t in t_sorted])
    ema_arr = df_trig["ema200"].to_numpy()
    close_arr = df_trig["close"].to_numpy()
    setups = []
    for a in anchors:
        a_start = a["time"] + a_tf_td  # cur_close
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
            if filt == "pro" and not pro:
                continue
            setups.append({"anchor_time": a["time"], "trigger_time": t["time"],
                            "direction": t["direction"],
                            "fvg_bottom": t["bottom"], "fvg_top": t["top"],
                            "fvg_atr": t["atr"], "year": t["time"].year, "pro": pro})
            break  # dedup first
    return setups


def evaluate(setups, sim, trigger_tf, rr, min_sl_pct):
    rows = []
    for s in setups:
        direction = s["direction"]
        entry = (s["fvg_bottom"] + s["fvg_top"]) / 2
        atr = s["fvg_atr"]
        if direction == "LONG":
            atr_sl = s["fvg_bottom"] - SL_BUF_ATR * atr
        else:
            atr_sl = s["fvg_top"] + SL_BUF_ATR * atr
        min_dist = entry * min_sl_pct / 100
        if direction == "LONG":
            pct_sl = entry - min_dist
            sl = min(atr_sl, pct_sl)
        else:
            pct_sl = entry + min_dist
            sl = max(atr_sl, pct_sl)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        if direction == "LONG":
            tp = entry + rr * risk
        else:
            tp = entry - rr * risk
        start = s["trigger_time"] + pd.Timedelta(trigger_tf)
        outcome, R, close_ts = sim.simulate(direction, entry, sl, tp, start,
                                              TF_LIFE_DAYS.get(trigger_tf, 5))
        rows.append({**s, "entry": entry, "sl": sl, "tp": tp, "risk": risk,
                      "outcome": outcome, "R": R, "close_ts": close_ts})
    return pd.DataFrame(rows)


def report_year(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if closed.empty:
        return None
    rows = []
    for year in sorted(closed["year"].unique()):
        yr = closed[closed["year"] == year]
        n = len(yr); w = (yr["outcome"] == "win").sum()
        rows.append({"year": int(year), "n": n,
                      "WR%": round(w/n*100, 1) if n else 0,
                      "total_R": round(yr["R"].sum(), 1),
                      "R/tr": round(yr["R"].mean(), 3)})
    yr_df = pd.DataFrame(rows)
    print(f"\n--- {label}: year-by-year ---")
    print(yr_df.to_string(index=False))
    return yr_df


def report_outlier(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if closed.empty:
        return None
    n = len(closed); w = (closed["outcome"] == "win").sum()
    total = closed["R"].sum()
    sorted_R = closed["R"].sort_values(ascending=False).to_numpy()
    top1 = sorted_R[0] if len(sorted_R) > 0 else 0
    top3 = sorted_R[:3].sum() if len(sorted_R) >= 3 else sorted_R.sum()
    top5 = sorted_R[:5].sum() if len(sorted_R) >= 5 else sorted_R.sum()
    big_wins = (closed["R"] >= 1.5).sum()
    losses = (closed["R"] < 0).sum()
    print(f"\n--- {label}: outlier check ---")
    print(f"  total R={total:.1f}, n={n}, WR={w/n*100:.1f}%")
    print(f"  top-1 R={top1:.2f}  ->  без него total={total-top1:.1f}")
    print(f"  top-3 sum={top3:.2f}  ->  без них total={total-top3:.1f}")
    print(f"  top-5 sum={top5:.2f}  ->  без них total={total-top5:.1f}")
    print(f"  трейдов >=1.5R: {big_wins}, <0: {losses}")


def report_direction(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if closed.empty:
        return None
    rows = []
    for d in ("LONG", "SHORT"):
        sub = closed[closed["direction"] == d]
        if sub.empty:
            continue
        w = (sub["outcome"] == "win").sum()
        rows.append({"dir": d, "n": len(sub),
                      "WR%": round(w/len(sub)*100, 1),
                      "total_R": round(sub["R"].sum(), 1),
                      "R/tr": round(sub["R"].mean(), 3)})
    print(f"\n--- {label}: LONG vs SHORT ---")
    print(pd.DataFrame(rows).to_string(index=False))


def main():
    t0 = time.time()
    print("[INFO] loading data")
    raw_tfs = {c["anchor_tf"] for c in CANDIDATES} | {c["trigger_tf"] for c in CANDIDATES}
    if any(c["anchor_kind"] == "FRACT2X" for c in CANDIDATES):
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

    # collect zones once per (kind, tf)
    print("\n[INFO] collecting zones")
    anchors_cache = {}
    triggers_cache = {}
    for c in CANDIDATES:
        ak = (c["anchor_kind"], c["anchor_tf"])
        tk = (c["trigger_kind"], c["trigger_tf"])
        if ak not in anchors_cache:
            if c["anchor_kind"] == "OB":
                df_a = dfs[c["anchor_tf"]]
                anchors_cache[ak] = collect_obs(df_a, df_a["atr14"], c["anchor_tf"])
            elif c["anchor_kind"] == "FRSWEEP":
                df_a = dfs[c["anchor_tf"]]
                anchors_cache[ak] = collect_frsweep(df_a, df_a["atr14"], c["anchor_tf"])
            elif c["anchor_kind"] == "FRACT2X":
                df_1d = dfs["1d"]; df_4h = dfs["4h"]
                frs1d = collect_fractals(df_1d, df_1d["atr14"], "1d")
                frs4h = collect_fractals(df_4h, df_4h["atr14"], "4h")
                anchors_cache[ak] = collect_fract2x(frs1d, frs4h)
            print(f"  anchor {ak}: {len(anchors_cache[ak])}")
        if tk not in triggers_cache:
            df_t = dfs[c["trigger_tf"]]
            if c["trigger_kind"] == "FVG":
                triggers_cache[tk] = collect_fvgs(df_t, df_t["atr14"], c["trigger_tf"])
            print(f"  trigger {tk}: {len(triggers_cache[tk])}")

    # evaluate each candidate
    print(f"\n[INFO] evaluating {len(CANDIDATES)} candidates")
    all_results = {}
    for c in CANDIDATES:
        cid = c["id"]
        label = f"{cid}: {c['anchor_kind']}-{c['anchor_tf']} x {c['trigger_kind']}-{c['trigger_tf']} | RR={c['rr']} | filt={c['filter']}"
        print(f"\n{'='*70}\n{label}\n{'='*70}")
        anchors = anchors_cache[(c["anchor_kind"], c["anchor_tf"])]
        triggers = triggers_cache[(c["trigger_kind"], c["trigger_tf"])]
        df_trig = dfs[c["trigger_tf"]]
        setups = build_setups(anchors, triggers, df_trig,
                                c["anchor_tf"], c["trigger_tf"], c["filter"],
                                anchor_kind=c["anchor_kind"])
        df = evaluate(setups, sim, c["trigger_tf"], c["rr"], MIN_SL_PCT)
        all_results[cid] = df
        # save raw
        save_path = OUT_DIR / f"etap15_{cid}_trades.csv"
        df.to_csv(save_path, index=False)
        # reports
        closed = df[df["outcome"].isin(["win", "loss"])]
        if closed.empty:
            print("  no closed")
            continue
        n_total = len(df); nc = len(closed)
        w = (closed["outcome"] == "win").sum()
        print(f"  totals: n_total={n_total}, n_closed={nc}, WR={w/nc*100:.1f}%, "
                f"total_R={closed['R'].sum():.1f}, R/tr={closed['R'].mean():.3f}")
        report_year(df, label)
        report_direction(df, label)
        report_outlier(df, label)

    print(f"\n[TIME] total {time.time()-t0:.1f}s")
    print(f"\n=== Summary saved to {OUT_DIR} ===")


if __name__ == "__main__":
    main()
