"""etap_124: Floating TP (from 1.1.1) применённый к V2 Wicked+Fractal OB-D.

Гипотеза: floating TP помогает strategies с baseline WR < 50%.
V2 baseline = 36.9%, F12 = 43.5%, F6 = 47.1% — все попадают в zone полезности.
F7 = 59.3% (>50%) — может навредить.

Тест: применить floating TP (4-indicator score + R_cap) к каждому filter варианту.
Config: BTC из 1.1.1 — R_cap=4.5, threshold=-0.25, confirm=2.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E122 = Path(__file__).parent / "etap_122_v2_forensic.py"
_spec122 = _ilu.spec_from_file_location("etap122_core", _E122)
_e122 = _ilu.module_from_spec(_spec122); _sys.modules["etap122_core"] = _e122
_spec122.loader.exec_module(_e122)
react_v2_detailed = _e122.react_v2_detailed

_E121 = Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_spec121 = _ilu.spec_from_file_location("etap121_core", _E121)
_e121 = _ilu.module_from_spec(_spec121); _sys.modules["etap121_core"] = _e121
_spec121.loader.exec_module(_e121)
collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
find_first_touch_and_invalidation = _e121.find_first_touch_and_invalidation

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec103 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec103); _sys.modules["etap103_core"] = _e103
_spec103.loader.exec_module(_e103)
build_score_series = _e103.build_score_series

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
RR_BASELINE = 2.0
MAX_HOLD_DAYS = 7
R_CAP = 4.5
THRESHOLD = -0.25
CONFIRM = 2


def simulate_baseline_rr(setup, df_1m, rr=RR_BASELINE):
    direction = setup["direction"]; entry = setup["entry"]; sl = setup["sl"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0, None)
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    start = setup["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0, None)
    h = df_1m["high"].values[i0:i1]; l = df_1m["low"].values[i0:i1]
    if direction == "LONG":
        ent = np.where(l <= entry)[0]; tp_pre = np.where(h >= tp)[0]
    else:
        ent = np.where(h >= entry)[0]; tp_pre = np.where(l <= tp)[0]
    ent_i = int(ent[0]) if ent.size else len(h) + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else len(h) + 1
    if tp_pre_i < ent_i: return ("no_entry", 0.0, None)
    if ent_i >= len(h): return ("not_filled", 0.0, None)
    post_h = h[ent_i:]; post_l = l[ent_i:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1: return ("open", 0.0, None)
    if sl_f == -1: return ("win", rr, None)
    if tp_f == -1: return ("loss", -1.0, None)
    if tp_f < sl_f: return ("win", rr, None)
    return ("loss", -1.0, None)


def simulate_floating(setup, df_1m, df_1h, score_long, score_short,
                       R_cap=R_CAP, threshold=THRESHOLD, confirm=CONFIRM):
    direction = setup["direction"]; entry = setup["entry"]; sl = setup["sl"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tp_cap = entry + R_cap*risk if direction == "LONG" else entry - R_cap*risk
    tp_proxy = entry + RR_BASELINE*risk if direction == "LONG" else entry - RR_BASELINE*risk
    score_series = score_long if direction == "LONG" else score_short

    start = setup["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    times = df_1m.index[i0:i1]
    n = len(h)
    if direction == "LONG":
        ent = np.where(l <= entry)[0]; tp_pre = np.where(h >= tp_proxy)[0]
    else:
        ent = np.where(h >= entry)[0]; tp_pre = np.where(l <= tp_proxy)[0]
    ent_i = int(ent[0]) if ent.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i: return ("no_entry", 0.0)
    if ent_i >= n: return ("not_filled", 0.0)
    activation = times[ent_i]
    post_h = h[ent_i:]; post_l = l[ent_i:]
    post_ts = times[ent_i:]
    end_time = activation + pd.Timedelta(days=MAX_HOLD_DAYS)

    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values

    consec = 0; sl_exit_idx = None; cap_hit = None
    floating_price = None
    prev_post_idx = 0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_post_idx = np.searchsorted(post_ts.values, cp64)
        if cur_post_idx > prev_post_idx:
            wl = post_l[prev_post_idx:cur_post_idx]
            wh = post_h[prev_post_idx:cur_post_idx]
            if direction == "LONG":
                if (wl <= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(wl <= sl)); break
                if (wh >= tp_cap).any():
                    cap_hit = prev_post_idx + int(np.argmax(wh >= tp_cap)); break
            else:
                if (wh >= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(wh >= sl)); break
                if (wl <= tp_cap).any():
                    cap_hit = prev_post_idx + int(np.argmax(wl <= tp_cap)); break
        prev_post_idx = cur_post_idx
        score_idx = score_series.index.searchsorted(cp, side="right") - 1
        if score_idx < 0: continue
        s = score_series.iloc[score_idx]
        if pd.isna(s): continue
        if s <= threshold: consec += 1
        else: consec = 0
        if consec >= confirm:
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                floating_price = float(closes_1h[cp_close_idx]); break

    if cap_hit is not None: return ("win", R_CAP)
    if sl_exit_idx is not None: return ("loss", -1.0)
    if floating_price is not None:
        R = (floating_price - entry)/risk if direction == "LONG" else (entry - floating_price)/risk
        return ("win" if R > 0 else "loss", R)
    # max hold
    return ("open", 0.0)


def main():
    print("etap_124: Floating TP vs Baseline RR=2.0 on V2 filters (BTC 6.3y)")
    print(f"Floating config: R_cap={R_CAP}, threshold={THRESHOLD}, confirm={CONFIRM}")
    print()
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    for nm in ["df_1d","df_1h","df_12h","df_2h","df_15m","df_20m"]:
        pass
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    print("[INFO] score series")
    score_long, score_short = build_score_series(df_1h)

    print("[INFO] collecting V2 setups")
    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    raw_setups = []
    for ob_list, df_l1 in [(wf_1d, df_1d), (wf_12h, df_12h)]:
        for ob_d in ob_list:
            touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
            if touch_t is None: continue
            if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)
            setup = react_v2_detailed(ob_d, touch_t, inval_t, df_15m, df_20m)
            if setup is None: continue
            # add ema_pro
            t = setup["signal_time"]
            idx = df_2h.index.searchsorted(t, side="right") - 1
            if idx >= 0 and not pd.isna(df_2h["ema200"].iloc[idx]):
                c = float(df_2h["close"].iloc[idx]); e = float(df_2h["ema200"].iloc[idx])
                setup["ema_pro"] = (c > e) if setup["direction"] == "LONG" else (c < e)
            else:
                setup["ema_pro"] = False
            raw_setups.append(setup)
    # Dedup
    seen = {}
    for s in raw_setups:
        k = (s["signal_time"], s["direction"], round(s["entry"], 2))
        if k not in seen: seen[k] = s
    setups = list(seen.values())
    print(f"  unique setups: {len(setups)}")

    # Filters
    def f_ema(t): return t["ema_pro"]
    def f_long(t): return t["direction"] == "LONG"
    def f_delay(t): return t["touch_delay_h"] < 60

    filter_configs = [
        ("F0: baseline (no filter)",       lambda t: True),
        ("F2: LONG only",                  f_long),
        ("F6: LONG + delay<60h",           lambda t: f_long(t) and f_delay(t)),
        ("F7: EMA + LONG + delay<60h",     lambda t: f_ema(t) and f_long(t) and f_delay(t)),
        ("F12: EMA pro OR LONG",           lambda t: f_ema(t) or f_long(t)),
    ]

    print()
    print(f"  {'Filter':<32} {'mode':<10} {'n':>4} {'WR':>5} {'PnL':>8} {'medR':>6} {'bad':>5}")
    print("  " + "-"*88)
    for f_label, f_fn in filter_configs:
        filtered = [s for s in setups if f_fn(s)]
        # baseline RR=2.0
        rows_b = []
        for s in filtered:
            outc, R, _ = simulate_baseline_rr(s, df_1m)
            if outc in ("win", "loss"):
                rows_b.append({"R": R, "year": s["signal_time"].year})
        # floating
        rows_f = []
        for s in filtered:
            outc, R = simulate_floating(s, df_1m, df_1h, score_long, score_short)
            if outc in ("win", "loss"):
                rows_f.append({"R": R, "year": s["signal_time"].year})

        for mode, rows in [("baseline", rows_b), ("floating", rows_f)]:
            n = len(rows)
            if n == 0:
                print(f"  {f_label:<32} {mode:<10} {0:>4d}  no data"); continue
            W = sum(1 for r in rows if r["R"] > 0)
            wr = W / n * 100
            pnl = sum(r["R"] for r in rows)
            Rs = sorted([r["R"] for r in rows])
            medR = Rs[n // 2]
            yr_map = defaultdict(float)
            for r in rows: yr_map[r["year"]] += r["R"]
            bad = sum(1 for v in yr_map.values() if v < 0)
            print(f"  {f_label:<32} {mode:<10} {n:>4d} {wr:>4.1f}% {pnl:>+7.1f}R "
                  f"{medR:>+5.2f} {bad}/{len(yr_map)}")

    print()
    print("Comparison: floating - baseline PnL delta")
    print("-" * 60)


if __name__ == "__main__":
    main()
