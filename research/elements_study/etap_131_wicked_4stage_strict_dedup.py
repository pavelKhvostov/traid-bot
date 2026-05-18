"""etap_131: etap_130 со строгим dedup -- один сетап на wicked OB-D.

etap_130 показал большие PnL (B2: +538R), но это multi-shot inflation:
324 base OB-D -> 3505 setups (x10). Per-trade R = +0.16R/trade (low).

Тут берём ТОЛЬКО первый успешный сетап для каждой wicked OB-D, аналогично
канону 1.1.1/1.1.4. Сравниваем с baseline V2+F12 (+42R / 138 / +0.30R/trade).
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
_E130 = _Path(__file__).parent / "etap_130_wicked_4stage_111_112.py"
_spec = _ilu.spec_from_file_location("etap121_core", _E121)
_e121 = _ilu.module_from_spec(_spec); _sys.modules["etap121_core"] = _e121
_spec.loader.exec_module(_e121)
_spec = _ilu.spec_from_file_location("etap130_core", _E130)
_e130 = _ilu.module_from_spec(_spec); _sys.modules["etap130_core"] = _e130
_spec.loader.exec_module(_e130)
collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
find_first_touch_and_invalidation = _e121.find_first_touch_and_invalidation
any_edge_inside = _e121.any_edge_inside
check_swept_dir = _e130.check_swept_dir
simulate = _e130.simulate

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
MIN_SL_PCT = 1.0


def first_setup_per_ob(ob_d, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                       macro_kind, swept_required, entry_pct, sl_pct):
    """Возвращает ТОЛЬКО первый найденный сетап для данной wicked OB-D."""
    touch_t, inval_t = find_first_touch_and_invalidation(ob_d, df_l1)
    if touch_t is None: return None
    if inval_t is None: inval_t = ob_d.cur_close + pd.Timedelta(days=21)

    for df_m, m_h, m_tf in [(df_4h, 4, "4h"), (df_6h, 6, "6h")]:
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
                            return {"entry": entry, "sl": sl, "direction": ob_d.direction,
                                    "signal_time": signal_time, "year": signal_time.year}
    return None


def summarize(label, setups, df_1m, df_2h, rr, apply_f12=False):
    if apply_f12:
        ema_arr = df_2h["ema200"].to_numpy(); close_2h = df_2h["close"].to_numpy()
        def f12_ok(s):
            t = s["signal_time"]; idx = df_2h.index.searchsorted(t, side="right") - 1
            if idx < 0 or pd.isna(ema_arr[idx]): ema = False
            else:
                ema = (close_2h[idx] > ema_arr[idx]) if s["direction"] == "LONG" else (close_2h[idx] < ema_arr[idx])
            return ema or s["direction"] == "LONG"
        setups = [s for s in setups if f12_ok(s)]
    trades = []
    for s in setups:
        outc, R = simulate(s, df_1m, rr)
        if outc in ("win", "loss"):
            trades.append({"R": R, "year": s["signal_time"].year})
    n = len(trades)
    if n == 0:
        print(f"  {label:<60} sigs={len(setups):>3d} closed=0   no data"); return
    W = sum(1 for t in trades if t["R"] > 0)
    wr = W / n * 100
    pnl = sum(t["R"] for t in trades)
    yr = defaultdict(float)
    for t in trades: yr[t["year"]] += t["R"]
    bad = sum(1 for v in yr.values() if v < 0)
    rpt = pnl / n
    print(f"  {label:<60} sigs={len(setups):>3d} closed={n:>3d} WR={wr:>4.1f}% PnL={pnl:>+6.1f}R bad={bad}/{len(yr)} R/tr={rpt:+.2f}")


def main():
    print("etap_131: Wicked OB-D + 4-stage cascade STRICT dedup (1 setup / ob_d)")
    print("Baseline V2+F12: +42R / 138 / WR 43.5% / +0.30R/trade")
    print()
    df_1d = load_df(SYMBOL, "1d"); df_1h = load_df(SYMBOL, "1h"); df_1m = load_df(SYMBOL, "1m")
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h"); df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m"); df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]
    print(f"  wicked+fractal OB: 1d={len(wf_1d)} 12h={len(wf_12h)} total={len(all_ob_d)}")
    print()

    variants = [
        ("A1: 1.1.1 cascade   (FVG macro + SWEPT, e=0.80 RR=2.0)", "FVG", True,  0.80, 0.35, 2.0),
        ("A2: 1.1.1 no-SWEPT  (FVG macro, e=0.80 RR=2.0)",          "FVG", False, 0.80, 0.35, 2.0),
        ("A3: 1.1.1 cascade   (FVG macro + SWEPT, e=0.80 RR=2.2)",  "FVG", True,  0.80, 0.35, 2.2),
        ("B1: 1.1.2 cascade   (OB macro,  e=0.70 RR=2.0)",          "OB",  False, 0.70, 0.35, 2.0),
        ("B2: 1.1.2 cascade   (OB macro,  e=0.70 RR=2.2)",          "OB",  False, 0.70, 0.35, 2.2),
    ]

    print("  STRICT (1 setup per ob_d):")
    print("  " + "-"*110)
    cache = {}
    for v_label, macro_kind, swept_req, e_pct, sl_pct, rr in variants:
        key = (macro_kind, swept_req, round(e_pct, 2), round(sl_pct, 2))
        if key not in cache:
            setups = []
            for ob, df_l1 in all_ob_d:
                s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                                       macro_kind=macro_kind, swept_required=swept_req,
                                       entry_pct=e_pct, sl_pct=sl_pct)
                if s is not None: setups.append(s)
            cache[key] = setups
        else:
            setups = cache[key]
        summarize(v_label, setups, df_1m, df_2h, rr, apply_f12=False)

    print()
    print("  + F12 (EMA pro OR LONG) overlay:")
    print("  " + "-"*110)
    for v_label, macro_kind, swept_req, e_pct, sl_pct, rr in variants:
        key = (macro_kind, swept_req, round(e_pct, 2), round(sl_pct, 2))
        setups = cache[key]
        summarize("F12: " + v_label, setups, df_1m, df_2h, rr, apply_f12=True)


if __name__ == "__main__":
    main()
