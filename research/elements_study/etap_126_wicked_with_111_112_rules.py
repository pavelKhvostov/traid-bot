"""etap_126: Wicked+Fractal OB-D + точные правила 1.1.1 / 1.1.2.

Тестируем 4 варианта entry/SL/RR на одних setups (Wicked+Fractal OB-D + OB-htf
+ FVG-15m/20m inside, как V1 etap_121):

  A: 1.1.2 style — entry=0.70, sl=0.35 sym, RR=2.2, NO SWEPT
  B: 1.1.1 style — entry=0.80, sl=0.35 sym, RR=2.2, WITH SWEPT
  C: 1.1.1 hybrid — entry=0.80, sl=0.35 sym, RR=2.2, NO SWEPT
  D: B + F12 filter (EMA pro OR LONG)

Сравнение с V1 baseline (etap_121, entry=0.70 sl=0.35 RR=2.0): +24R / WR 37%.
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
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

_E121 = Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_spec = _ilu.spec_from_file_location("etap121_core", _E121)
_e121 = _ilu.module_from_spec(_spec); _sys.modules["etap121_core"] = _e121
_spec.loader.exec_module(_e121)
collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
find_first_touch_and_invalidation = _e121.find_first_touch_and_invalidation
any_edge_inside = _e121.any_edge_inside

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
MIN_SL_PCT = 1.0
MAX_HOLD_DAYS = 7


def check_swept(ob_htf_zone, prev_t, cur_t, df_htf):
    """SWEPT: min(prev.low, cur.low) < min(idx-1.low, idx-2.low) для LONG."""
    try:
        cur_idx = df_htf.index.get_loc(cur_t)
        prev_idx = df_htf.index.get_loc(prev_t)
    except (KeyError, TypeError):
        return False
    if prev_idx < 2: return False
    c1l = float(df_htf.iloc[prev_idx]["low"]); c2l = float(df_htf.iloc[cur_idx]["low"])
    c1h = float(df_htf.iloc[prev_idx]["high"]); c2h = float(df_htf.iloc[cur_idx]["high"])
    n1l = float(df_htf.iloc[prev_idx - 1]["low"]); n2l = float(df_htf.iloc[prev_idx - 2]["low"])
    n1h = float(df_htf.iloc[prev_idx - 1]["high"]); n2h = float(df_htf.iloc[prev_idx - 2]["high"])
    # direction inferred from zone — но мы не передаём direction, передаём LONG/SHORT через ob_htf_zone? Упростим:
    # Используем direction позже, тут пока вернём оба
    return min(c1l, c2l) < min(n1l, n2l), max(c1h, c2h) > max(n1h, n2h)


def detect_setups(ob_d_list, df_l1, df_1h, df_2h, df_15m, df_20m,
                    entry_pct, sl_pct, swept_required=False):
    """Wicked OB-D + OB-htf + FVG-15m/20m inside."""
    setups = []
    for ob_d in ob_d_list:
        touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
        if touch_t is None: continue
        if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)
        for df_htf, htf_h, htf_label in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
            df_w = df_htf[(df_htf.index >= touch_t) & (df_htf.index < inval_t)]
            if len(df_w) < 2: continue
            for i in range(1, len(df_w)):
                cand = detect_ob_pair(df_w, i)
                if cand is None or cand.direction != ob_d.direction: continue
                if not any_edge_inside(cand.bottom, cand.top, ob_d.bottom, ob_d.top): continue
                # SWEPT check (опционально)
                if swept_required:
                    sw_long, sw_short = check_swept(None, cand.prev_time, cand.cur_time, df_htf)
                    if cand.direction == "LONG" and not sw_long: continue
                    if cand.direction == "SHORT" and not sw_short: continue
                # find FVG-15m или FVG-20m
                for df_ltf, tf_min, tf_label in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
                    end_t = cand.cur_time + pd.Timedelta(minutes=htf_h * 60 - tf_min)
                    df_l = df_ltf[(df_ltf.index >= cand.prev_time) & (df_ltf.index <= end_t)]
                    for k in range(2, len(df_l)):
                        fvg = detect_fvg(df_l, k)
                        if fvg is None or fvg.direction != ob_d.direction: continue
                        if not any_edge_inside(fvg.bottom, fvg.top, cand.bottom, cand.top): continue
                        fb, ft = fvg.bottom, fvg.top
                        obb, obt = cand.bottom, cand.top
                        if ob_d.direction == "LONG":
                            entry = fb + entry_pct * (ft - fb)
                            sl = obb + sl_pct * (fb - obb)
                        else:
                            entry = ft - entry_pct * (ft - fb)
                            sl = obt - sl_pct * (obt - ft)
                        if MIN_SL_PCT > 0:
                            d = entry * MIN_SL_PCT / 100
                            if ob_d.direction == "LONG":
                                sl = min(sl, entry - d)
                            else:
                                sl = max(sl, entry + d)
                        if abs(entry - sl) <= 0: continue
                        if (ob_d.direction == "LONG" and sl >= entry) or (ob_d.direction == "SHORT" and sl <= entry):
                            continue
                        signal_time = fvg.c2_time + pd.Timedelta(minutes=tf_min)
                        setups.append({
                            "entry": entry, "sl": sl, "direction": ob_d.direction,
                            "signal_time": signal_time,
                            "ob_htf_tf": htf_label, "fvg_tf": tf_label,
                            "year": signal_time.year,
                        })
                        break
                    else:
                        continue
                    break
                break  # one reaction per htf TF
    return setups


def simulate(setup, df_1m, rr):
    direction = setup["direction"]; entry = setup["entry"]; sl = setup["sl"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0)
    tp = entry + rr*risk if direction == "LONG" else entry - rr*risk
    start = setup["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0)
    h = df_1m["high"].values[i0:i1]; l = df_1m["low"].values[i0:i1]
    if direction == "LONG":
        ent = np.where(l <= entry)[0]; tp_pre = np.where(h >= tp)[0]
    else:
        ent = np.where(h >= entry)[0]; tp_pre = np.where(l <= tp)[0]
    ent_i = int(ent[0]) if ent.size else len(h) + 1
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


def main():
    print("etap_126: Wicked+Fractal OB-D + 1.1.1/1.1.2 правила (BTC 6.3y)")
    print()
    df_1d = load_df(SYMBOL, "1d")
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
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = []
    for ob in wf_1d: all_ob_d.append((ob, df_1d))
    for ob in wf_12h: all_ob_d.append((ob, df_12h))

    variants = [
        ("A: 1.1.2 style (entry=0.70, RR=2.2, no SWEPT)", 0.70, 0.35, 2.2, False),
        ("B: 1.1.1 style (entry=0.80, RR=2.2, SWEPT)",    0.80, 0.35, 2.2, True),
        ("C: 1.1.1 hybrid (entry=0.80, RR=2.2, no SWEPT)", 0.80, 0.35, 2.2, False),
        # baseline V1 для сравнения
        ("V1 baseline (entry=0.70, RR=2.0, no SWEPT)",    0.70, 0.35, 2.0, False),
    ]

    print(f"  {'Variant':<55} {'sigs':>4} {'closed':>6} {'WR':>5} {'PnL':>8} {'bad':>5}")
    print("  " + "-"*100)
    all_setups = {}
    for v_label, e_pct, sl_pct, rr, swept in variants:
        setups = []
        for ob_d in [x[0] for x in all_ob_d]:
            df_l1 = next(d for o, d in all_ob_d if o is ob_d)
            sigs = detect_setups([ob_d], df_l1, df_1h, df_2h, df_15m, df_20m,
                                   entry_pct=e_pct, sl_pct=sl_pct, swept_required=swept)
            setups.extend(sigs)
        # dedup
        seen = {}
        for s in setups:
            k = (s["signal_time"], s["direction"], round(s["entry"], 2))
            if k not in seen: seen[k] = s
        unique = list(seen.values())
        # simulate
        trades = []
        for s in unique:
            outc, R = simulate(s, df_1m, rr)
            if outc in ("win", "loss"):
                trades.append({"R": R, "year": s["signal_time"].year, "s": s, "outc": outc})
        n = len(trades)
        if n == 0:
            print(f"  {v_label:<55} {len(unique):>4d} {0:>6d}  no data"); continue
        W = sum(1 for t in trades if t["R"] > 0)
        wr = W / n * 100
        pnl = sum(t["R"] for t in trades)
        yr_map = defaultdict(float)
        for t in trades: yr_map[t["year"]] += t["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        print(f"  {v_label:<55} {len(unique):>4d} {n:>6d} {wr:>4.1f}% {pnl:>+7.1f}R {bad}/{len(yr_map)}")
        all_setups[v_label] = (unique, trades)

    # F12 filter on best (likely B or C)
    print()
    print("=" * 90)
    print("Top variant + F12 filter (EMA-2h pro-trend OR LONG):")
    print("=" * 90)
    for v_label, (unique, trades) in all_setups.items():
        # ema_pro check
        ema_arr = df_2h["ema200"].to_numpy()
        close_2h = df_2h["close"].to_numpy()
        def ema_pro_f12(s):
            t = s["signal_time"]
            idx = df_2h.index.searchsorted(t, side="right") - 1
            if idx < 0 or pd.isna(ema_arr[idx]): ema = False
            else:
                ema = (close_2h[idx] > ema_arr[idx]) if s["direction"] == "LONG" else (close_2h[idx] < ema_arr[idx])
            return ema or s["direction"] == "LONG"
        filtered = [t for t in trades if ema_pro_f12(t["s"])]
        n = len(filtered)
        if n == 0: continue
        W = sum(1 for t in filtered if t["R"] > 0)
        wr = W / n * 100
        pnl = sum(t["R"] for t in filtered)
        yr_map = defaultdict(float)
        for t in filtered: yr_map[t["year"]] += t["R"]
        bad = sum(1 for v in yr_map.values() if v < 0)
        print(f"  {v_label[:60]:<60} +F12: n={n:>3d}  WR={wr:>4.1f}%  PnL={pnl:>+6.1f}R  bad={bad}/{len(yr_map)}")


if __name__ == "__main__":
    main()
