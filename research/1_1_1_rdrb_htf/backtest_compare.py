"""Вариант C: 1.1.1 с htf-этажом RDRB вместо OB — head-to-head сравнение.

Скелет 1.1.1: OB-{1d,12h} + FVG-{4h,6h} → [HTF] {1h,2h} + FVG-{15m,20m}.
Меняется ТОЛЬКО детектор htf-этажа:
  kind="OB"   — baseline 1.1.1 (detect_ob_pair) — должен ~воспроизвести raw 1.1.1
  kind="RDRB" — вариант C (detect_rdrb, 3-свечной reversal-block, туже зона → туже SL?)
Всё остальное (top-OB, macro-FVG collection, fractal-инвалидация, entry-FVG, SL внутри
top-OB, entry=mid entry-FVG) идентично → честное сравнение «помогает ли RDRB на htf».

Исполнение: arm с close(entry-FVG.c2); limit-fill на 1m; SL/TP intrabar; MAX_HOLD; RR-сетка.
БЕЗ confluence/SWEPT/floating-TP (чистый каркас, чтобы изолировать эффект htf-детектора).

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/1_1_1_rdrb_htf/backtest_compare.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.strategy_1_1_1 import (  # noqa: E402
    OB_SL_DEPTH, collect_valid_macro_fvgs, detect_ob_pair,
    find_first_fvg_in_range, zones_overlap,
)
from strategies.strategy_rdrb import detect_rdrb  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
RR_GRID = [1.5, 2.0, 2.2, 2.5]
MAX_HOLD_MIN = 30 * 24 * 60


def load_1m(sym: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    df.index.name = "open_time"
    return df.sort_index()


def rs(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    out = df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    out.index.name = "open_time"
    return out


def htf_zone(df_window: pd.DataFrame, i: int, kind: str):
    """Вернуть (direction, bottom, top, prev_time, cur_time) htf-зоны или None."""
    if kind == "OB":
        ob = detect_ob_pair(df_window, i)
        if ob is None:
            return None
        return ob.direction, ob.bottom, ob.top, ob.prev_time, ob.cur_time
    rd = detect_rdrb(df_window, i, "V1")
    if rd is None:
        return None
    prev_time = df_window.index[i - 2] if i >= 2 else df_window.index[i - 1]
    return rd.direction, rd.bottom, rd.top, prev_time, df_window.index[i]


def find_signal_htf(df_htf, df_15m, df_20m, ob_top, fvg_macro,
                    search_start, htf_minutes, htf_label, kind):
    """Аналог strategy_1_1_1.find_signal_in_htf, но htf-детектор параметризован (OB|RDRB)."""
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 2:
        return None
    direction = ob_top.direction
    fvg_top, fvg_bottom = fvg_macro.top, fvg_macro.bottom
    highs = df_window["high"].values
    lows = df_window["low"].values
    fractal_confirm_idx = None

    for i in range(n):
        if i >= 4 and fractal_confirm_idx is None:
            j = i - 2
            f_low, f_high = float(lows[j]), float(highs[j])
            is_ll = (f_low < lows[j - 2] and f_low < lows[j - 1]
                     and f_low < lows[j + 1] and f_low < lows[j + 2])
            is_hh = (f_high > highs[j - 2] and f_high > highs[j - 1]
                     and f_high > highs[j + 1] and f_high > highs[j + 2])
            if direction == "LONG" and is_ll and f_low < fvg_bottom:
                fractal_confirm_idx = i
            elif direction == "SHORT" and is_hh and f_high > fvg_top:
                fractal_confirm_idx = i
        if fractal_confirm_idx is not None and i > fractal_confirm_idx:
            return None

        if i >= 1:
            z = htf_zone(df_window, i, kind)
            if z is None:
                continue
            zdir, zb, zt, zprev, zcur = z
            if zdir != direction:
                continue
            if not (zones_overlap(zb, zt, fvg_bottom, fvg_top)
                    and zones_overlap(zb, zt, ob_top.bottom, ob_top.top)):
                continue
            fvg_15m = find_first_fvg_in_range(
                df_15m, zprev, zcur + pd.Timedelta(minutes=htf_minutes - 15),
                direction, zb, zt)
            fvg_20m = find_first_fvg_in_range(
                df_20m, zprev, zcur + pd.Timedelta(minutes=htf_minutes - 20),
                direction, zb, zt)
            if fvg_15m is None and fvg_20m is None:
                continue
            if fvg_15m is None:
                fvg_entry, fvg_tf = fvg_20m, "20m"
            elif fvg_20m is None:
                fvg_entry, fvg_tf = fvg_15m, "15m"
            else:
                fvg_entry, fvg_tf = ((fvg_15m, "15m") if fvg_15m.c2_time <= fvg_20m.c2_time
                                     else (fvg_20m, "20m"))
            return {"htf_label": htf_label, "fvg_entry": fvg_entry, "fvg_tf": fvg_tf}
    return None


def scan(tfs: dict, kind: str) -> list[dict]:
    df_1d, df_12h, df_4h, df_6h = tfs["1d"], tfs["12h"], tfs["4h"], tfs["6h"]
    df_1h, df_2h, df_15m, df_20m = tfs["1h"], tfs["2h"], tfs["15m"], tfs["20m"]
    signals = []

    def _scan_top(df_top, top_tf_hours):
        if df_top is None or df_top.empty:
            return
        for idx in range(1, len(df_top)):
            ob_top = detect_ob_pair(df_top, idx)
            if ob_top is None:
                continue
            macro = ([(f, "4h") for f in collect_valid_macro_fvgs(
                          df_4h, ob_top, 4, top_tf_hours)]
                     + [(f, "6h") for f in collect_valid_macro_fvgs(
                          df_6h, ob_top, 6, top_tf_hours)])
            if not macro:
                continue
            search_start = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)
            for fvg_macro, _mtf in macro:
                s1 = find_signal_htf(df_1h, df_15m, df_20m, ob_top, fvg_macro,
                                     search_start, 60, "1h", kind)
                s2 = find_signal_htf(df_2h, df_15m, df_20m, ob_top, fvg_macro,
                                     search_start, 120, "2h", kind)
                if s1 is None and s2 is None:
                    continue
                if s1 is None:
                    chosen = s2
                elif s2 is None:
                    chosen = s1
                else:
                    chosen = (s1 if s1["fvg_entry"].c2_time <= s2["fvg_entry"].c2_time else s2)
                fe = chosen["fvg_entry"]
                entry = (fe.bottom + fe.top) / 2
                depth = ob_top.top - ob_top.bottom
                if ob_top.direction == "LONG":
                    sl = ob_top.bottom + depth * OB_SL_DEPTH
                else:
                    sl = ob_top.top - depth * OB_SL_DEPTH
                risk = abs(entry - sl)
                if risk <= 0:
                    continue
                if (ob_top.direction == "LONG" and sl >= entry) or \
                   (ob_top.direction == "SHORT" and sl <= entry):
                    continue
                signals.append({
                    "direction": ob_top.direction, "entry": float(entry),
                    "sl": float(sl), "risk": float(risk),
                    "arm_time": fe.c2_time, "htf_tf": chosen["htf_label"],
                    "year": fe.c2_time.year,
                })

    _scan_top(df_1d, 24)
    _scan_top(df_12h, 12)
    # dedup по (arm_time, direction, entry)
    seen, out = set(), []
    for s in sorted(signals, key=lambda x: x["arm_time"]):
        k = (s["arm_time"], s["direction"], round(s["entry"], 2))
        if k in seen:
            continue
        seen.add(k); out.append(s)
    return out


def simulate(sigs, df_1m, rr):
    lo = df_1m["low"].to_numpy(); hi = df_1m["high"].to_numpy()
    idx = df_1m.index
    ow = ol = nf = op = 0
    yearly = defaultdict(lambda: [0, 0, 0.0])
    side = {"LONG": [0, 0, 0.0], "SHORT": [0, 0, 0.0]}
    for s in sigs:
        arm = s["arm_time"] + pd.Timedelta(minutes=15)
        sp = int(idx.searchsorted(arm, side="left"))
        if sp >= len(lo):
            continue
        end = min(sp + MAX_HOLD_MIN, len(lo))
        d, entry, sl, risk = s["direction"], s["entry"], s["sl"], s["risk"]
        tp = entry + rr * risk if d == "LONG" else entry - rr * risk
        if d == "LONG":
            fh = np.where(lo[sp:end] <= entry)[0]
        else:
            fh = np.where(hi[sp:end] >= entry)[0]
        if not fh.size:
            nf += 1; continue
        f = sp + int(fh[0])
        plo, phi = lo[f:end], hi[f:end]
        if d == "LONG":
            sl_m, tp_m = plo <= sl, phi >= tp
        else:
            sl_m, tp_m = phi >= sl, plo <= tp
        slf = int(np.argmax(sl_m)) if sl_m.any() else 10**9
        tpf = int(np.argmax(tp_m)) if tp_m.any() else 10**9
        if slf == 10**9 and tpf == 10**9:
            op += 1; continue
        win = tpf < slf
        R = rr if win else -1.0
        yr = s["year"]
        if win:
            ow += 1; yearly[yr][0] += 1; side[d][0] += 1
        else:
            ol += 1; yearly[yr][1] += 1; side[d][1] += 1
        yearly[yr][2] += R; side[d][2] += R
    closed = ow + ol
    return {"n": len(sigs), "closed": closed, "w": ow, "l": ol, "nf": nf, "open": op,
            "wr": ow / closed * 100 if closed else 0.0, "total": ow * rr - ol,
            "yearly": dict(yearly), "side": side}


def main():
    for sym in SYMBOLS:
        print(f"\nloading + composing {sym}...", flush=True)
        df_1m = load_1m(sym)
        tfs = {"1d": rs(df_1m, "1d"), "12h": rs(df_1m, "12h"), "4h": rs(df_1m, "4h"),
               "6h": rs(df_1m, "6h"), "2h": rs(df_1m, "2h"), "1h": rs(df_1m, "1h"),
               "15m": rs(df_1m, "15min"), "20m": rs(df_1m, "20min")}
        sig_ob = scan(tfs, "OB")
        sig_rd = scan(tfs, "RDRB")
        print(f"  {sym}: OB-htf {len(sig_ob)} setups | RDRB-htf {len(sig_rd)} setups")

        print("=" * 78)
        print(f"{sym}  —  OB-htf (baseline 1.1.1)  vs  RDRB-htf (вариант C)")
        print("=" * 78)
        print(f"{'kind':>6} {'RR':>4} {'closed':>6} {'WR%':>6} {'totalR':>8} {'avgR':>7}  "
              f"{'L_R':>7} {'S_R':>7}")
        for kind, sigs in (("OB", sig_ob), ("RDRB", sig_rd)):
            for rr in RR_GRID:
                m = simulate(sigs, df_1m, rr)
                avg = m["total"] / m["closed"] if m["closed"] else 0
                print(f"{kind:>6} {rr:>4.1f} {m['closed']:>6} {m['wr']:>6.1f} "
                      f"{m['total']:>+8.1f} {avg:>+7.3f}  "
                      f"{m['side']['LONG'][2]:>+7.1f} {m['side']['SHORT'][2]:>+7.1f}")
            print()

        # год-разбивка при RR=2.2 (live-RR 1.1.x)
        print(f"ГОД-РАЗБИВКА {sym} RR=2.2")
        years = list(range(2020, 2027))
        print(f"{'kind':>6}  " + "  ".join(f"{y:>7}" for y in years) + f"  {'+yrs':>6}")
        for kind, sigs in (("OB", sig_ob), ("RDRB", sig_rd)):
            m = simulate(sigs, df_1m, 2.2)
            y = m["yearly"]; cells, pos, tot = [], 0, 0
            for yr in years:
                if yr in y and (y[yr][0] + y[yr][1]) > 0:
                    r = y[yr][2]; cells.append(f"{r:>+7.1f}"); tot += 1
                    if r > 0:
                        pos += 1
                else:
                    cells.append(f"{'-':>7}")
            print(f"{kind:>6}  " + "  ".join(cells) + f"  {pos:>3}/{tot}")


if __name__ == "__main__":
    main()
