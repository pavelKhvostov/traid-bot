"""etap_130: Wicked+Fractal OB-D + full 4-stage cascade (1.1.1 macro-FVG / 1.1.2 macro-OB).

etap_126 testовал 3-stage: wicked OB-D -> OB-htf-1h/2h -> FVG-15m/20m.
Тут добавляем средний уровень (L2: macro 4h/6h) как в канонe 1.1.1/1.1.2.

Варианты:
  A1: 1.1.1 cascade  -- L1 wicked OB-D / L2 FVG-{4h,6h} / L3 OB-{1h,2h} SWEPT / L4 FVG-{15m,20m}
  A2: 1.1.1 no-SWEPT -- same as A1, но без SWEPT
  B1: 1.1.2 cascade  -- L1 wicked OB-D / L2 OB-{4h,6h} / L3 OB-{1h,2h} / L4 FVG-{15m,20m}

Для каждого варианта прогон RR=2.0 и RR=2.2, плюс F12 (EMA pro OR LONG) overlay.

Baseline V2+F12 (etap_123): +42R / WR 43.5% / 138 closed / 2 bad / 6.3y.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

_E121 = _Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
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


def collect_obs(df, direction_only=None):
    out = []
    for idx in range(1, len(df)):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        if direction_only and ob.direction != direction_only: continue
        out.append(ob)
    return out


def check_swept_dir(prev_t, cur_t, df_htf, direction):
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
    if direction == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def detect_4stage(ob_d, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                  macro_kind, swept_required, entry_pct, sl_pct):
    """macro_kind in ('FVG','OB'). One setup per (L2 TF, L3 TF, L4 TF)."""
    setups = []
    touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
    if touch_t is None: return setups
    if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)

    for df_m, m_h, m_tf in [(df_4h, 4, "4h"), (df_6h, 6, "6h")]:
        # L2 macro inside ob_d, между touch и inval
        dfw_m = df_m[(df_m.index >= touch_t) & (df_m.index < inval_t)]
        if len(dfw_m) < 3: continue
        for j in range(2, len(dfw_m)):
            if macro_kind == "FVG":
                macro = detect_fvg(dfw_m, j)
            else:
                macro = detect_ob_pair(dfw_m, j)
            if macro is None or macro.direction != ob_d.direction: continue
            if not any_edge_inside(macro.bottom, macro.top, ob_d.bottom, ob_d.top): continue
            mb, mt = macro.bottom, macro.top
            # L3: OB-1h/2h внутри L2
            macro_time = macro.c2_time if macro_kind == "FVG" else macro.cur_time
            for df_h, h_h, h_tf in [(df_1h, 1, "1h"), (df_2h, 2, "2h")]:
                dfw_h = df_h[(df_h.index >= macro_time) & (df_h.index < inval_t)]
                if len(dfw_h) < 2: continue
                for i in range(1, len(dfw_h)):
                    cand = detect_ob_pair(dfw_h, i)
                    if cand is None or cand.direction != ob_d.direction: continue
                    if not any_edge_inside(cand.bottom, cand.top, mb, mt): continue
                    if swept_required:
                        if not check_swept_dir(cand.prev_time, cand.cur_time, df_h, ob_d.direction):
                            continue
                    # L4: FVG-15m/20m внутри cand
                    for df_l, tf_min, tf_lbl in [(df_15m, 15, "15m"), (df_20m, 20, "20m")]:
                        end_t = cand.cur_time + pd.Timedelta(minutes=h_h * 60 - tf_min)
                        dfw_l = df_l[(df_l.index >= cand.prev_time) & (df_l.index <= end_t)]
                        for k in range(2, len(dfw_l)):
                            fvg = detect_fvg(dfw_l, k)
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
                                "L2_tf": m_tf, "L3_tf": h_tf, "L4_tf": tf_lbl,
                                "year": signal_time.year,
                            })
                            break
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


def summarize(label, setups, df_1m, df_2h, rr, apply_f12=False):
    # dedup
    seen = {}
    for s in setups:
        k = (s["signal_time"], s["direction"], round(s["entry"], 2))
        if k not in seen: seen[k] = s
    unique = list(seen.values())
    if apply_f12:
        ema_arr = df_2h["ema200"].to_numpy(); close_2h = df_2h["close"].to_numpy()
        def ema_pro_or_long(s):
            t = s["signal_time"]; idx = df_2h.index.searchsorted(t, side="right") - 1
            if idx < 0 or pd.isna(ema_arr[idx]): ema = False
            else:
                ema = (close_2h[idx] > ema_arr[idx]) if s["direction"] == "LONG" else (close_2h[idx] < ema_arr[idx])
            return ema or s["direction"] == "LONG"
        unique = [s for s in unique if ema_pro_or_long(s)]
    closed_trades = []
    for s in unique:
        outc, R = simulate(s, df_1m, rr)
        if outc in ("win", "loss"):
            closed_trades.append({"R": R, "year": s["signal_time"].year})
    n = len(closed_trades)
    if n == 0:
        print(f"  {label:<60} sigs={len(unique):>3d} closed=0   no data")
        return
    W = sum(1 for t in closed_trades if t["R"] > 0)
    wr = W / n * 100
    pnl = sum(t["R"] for t in closed_trades)
    yr = defaultdict(float)
    for t in closed_trades: yr[t["year"]] += t["R"]
    bad = sum(1 for v in yr.values() if v < 0)
    print(f"  {label:<60} sigs={len(unique):>3d} closed={n:>3d} WR={wr:>4.1f}% PnL={pnl:>+6.1f}R bad={bad}/{len(yr)}")


def main():
    print("etap_130: Wicked+Fractal OB-D + full 4-stage cascade (1.1.1 / 1.1.2)")
    print("Baseline V2+F12: +42R / WR 43.5% / 138 closed / 2 bad")
    print()
    df_1d = load_df(SYMBOL, "1d"); df_1h = load_df(SYMBOL, "1h"); df_1m = load_df(SYMBOL, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h"); df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m"); df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    for d in (df_1d, df_1h, df_12h, df_4h, df_6h, df_2h, df_15m, df_20m):
        d.drop(d[d.index < cutoff].index, inplace=True)
    df_1m = df_1m[df_1m.index >= cutoff]
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]
    print(f"  wicked+fractal OB: 1d={len(wf_1d)} 12h={len(wf_12h)} total={len(all_ob_d)}")
    print()

    # Variants
    print("  4-stage cascades:")
    print("  " + "-"*90)
    variants = [
        ("A1: 1.1.1 cascade   (FVG macro + SWEPT, e=0.80 RR=2.0)", "FVG", True,  0.80, 0.35, 2.0),
        ("A2: 1.1.1 no-SWEPT  (FVG macro, e=0.80 RR=2.0)",          "FVG", False, 0.80, 0.35, 2.0),
        ("A3: 1.1.1 cascade   (FVG macro + SWEPT, e=0.80 RR=2.2)",  "FVG", True,  0.80, 0.35, 2.2),
        ("B1: 1.1.2 cascade   (OB macro,  e=0.70 RR=2.0)",          "OB",  False, 0.70, 0.35, 2.0),
        ("B2: 1.1.2 cascade   (OB macro,  e=0.70 RR=2.2)",          "OB",  False, 0.70, 0.35, 2.2),
    ]
    results = {}
    for v_label, macro_kind, swept_req, e_pct, sl_pct, rr in variants:
        setups = []
        for ob, df_l1 in all_ob_d:
            sigs = detect_4stage(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                                 macro_kind=macro_kind, swept_required=swept_req,
                                 entry_pct=e_pct, sl_pct=sl_pct)
            setups.extend(sigs)
        results[v_label] = (setups, rr)
        summarize(v_label, setups, df_1m, df_2h, rr, apply_f12=False)

    print()
    print("  + F12 (EMA pro OR LONG) overlay:")
    print("  " + "-"*90)
    for v_label, (setups, rr) in results.items():
        summarize("F12: " + v_label, setups, df_1m, df_2h, rr, apply_f12=True)


if __name__ == "__main__":
    main()
