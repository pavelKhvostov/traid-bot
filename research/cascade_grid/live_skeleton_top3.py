"""Топ-3 новых грид-конфига через СТРОГИЙ live 1.1.x-скелет — честные объёмы.

Грид завышает счёт (PER_TOP_CAP=3 + свободный join). Здесь — настоящий канон:
collect_valid_macro_obs/fvgs (с инвалидацией close/wick + zone-inside-top),
find_signal_in_htf (fractal-инвалидация + entry FVG 15/20m), ~1 сигнал на (top,macro), dedup.

Параметры: top{OB,FVG} (FVG оборачивается в OBZone-duck), macro{OB,FVG}, htf{OB,RDRB}.

Конфиги:
  ref 1.1.1   : top=OB  macro=FVG htf=OB    (сверка с live)
  ref 1.1.2   : top=OB  macro=OB  htf=OB    (сверка с live)
  cand #1     : top=OB  macro=OB  htf=RDRB  (1.1.2 с RDRB на htf)
  cand #2     : top=FVG macro=OB  htf=OB    (FVG-якорь)
  cand #3     : top=FVG macro=FVG htf=RDRB  (чистый FVG + htf-RDRB)

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/cascade_grid/live_skeleton_top3.py
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
    OB_SL_DEPTH, OBZone, detect_ob_pair, detect_fvg,
    find_first_fvg_in_range, zones_overlap, collect_valid_macro_fvgs,
)
from strategies.strategy_1_1_2 import collect_valid_macro_obs  # noqa: E402
from strategies.strategy_rdrb import detect_rdrb  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RR_CURVE = [1.5, 2.0, 2.5]
MAX_HOLD_MIN = 30 * 24 * 60

CONFIGS = [
    ("ref-1.1.1",  "OB",  "FVG", "OB"),
    ("ref-1.1.2",  "OB",  "OB",  "OB"),
    ("cand1-htfRDRB",  "OB",  "OB",  "RDRB"),
    ("cand2-FVGtop",   "FVG", "OB",  "OB"),
    ("cand3-FVG+RDRB", "FVG", "FVG", "RDRB"),
]


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df_1m, freq):
    out = df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    out.index.name = "open_time"
    return out


def top_zones(df_top, kind):
    """top OB/FVG -> OBZone-duck (FVG: prev=c0, cur=c2)."""
    out = []
    if kind == "OB":
        for i in range(1, len(df_top)):
            z = detect_ob_pair(df_top, i)
            if z is not None:
                out.append(z)
    else:  # FVG
        for i in range(2, len(df_top)):
            z = detect_fvg(df_top, i)
            if z is not None:
                out.append(OBZone(z.direction, z.bottom, z.top, z.c0_time, z.c2_time))
    return out


def find_signal_in_htf_param(df_htf, df_15m, df_20m, ob_top, macro_zone,
                             search_start, htf_minutes, htf_label, htf_kind):
    """Канон strategy_1_1_1.find_signal_in_htf, но htf-детектор {OB,RDRB} параметризован."""
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 2:
        return None
    direction = ob_top.direction
    fvg_top, fvg_bottom = macro_zone.top, macro_zone.bottom
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
            if htf_kind == "OB":
                cand = detect_ob_pair(df_window, i)
                cprev, ccur = (df_window.index[i - 1], df_window.index[i]) if cand else (None, None)
            else:  # RDRB (нужно i>=2)
                cand = detect_rdrb(df_window, i, "V1") if i >= 2 else None
                cprev, ccur = (df_window.index[i - 2], df_window.index[i]) if cand else (None, None)
            if cand is None or cand.direction != direction:
                continue
            if not (zones_overlap(cand.bottom, cand.top, fvg_bottom, fvg_top)
                    and zones_overlap(cand.bottom, cand.top, ob_top.bottom, ob_top.top)):
                continue
            fvg_15m = find_first_fvg_in_range(
                df_15m, cprev, ccur + pd.Timedelta(minutes=htf_minutes - 15),
                direction, cand.bottom, cand.top)
            fvg_20m = find_first_fvg_in_range(
                df_20m, cprev, ccur + pd.Timedelta(minutes=htf_minutes - 20),
                direction, cand.bottom, cand.top)
            if fvg_15m is None and fvg_20m is None:
                continue
            if fvg_15m is None:
                fe, ftf = fvg_20m, 20
            elif fvg_20m is None:
                fe, ftf = fvg_15m, 15
            else:
                fe, ftf = ((fvg_15m, 15) if fvg_15m.c2_time <= fvg_20m.c2_time else (fvg_20m, 20))
            return {"fvg_entry": fe, "fvg_tf_min": ftf}
    return None


def scan_strict(tfs, top_kind, macro_kind, htf_kind):
    df_1d, df_12h, df_4h, df_6h = tfs["1d"], tfs["12h"], tfs["4h"], tfs["6h"]
    df_1h, df_2h, df_15m, df_20m = tfs["1h"], tfs["2h"], tfs["15m"], tfs["20m"]
    signals = []

    def collect_macro(df_macro, top, htf_hours, top_h):
        if macro_kind == "OB":
            return collect_valid_macro_obs(df_macro, top, htf_hours, top_h)
        return collect_valid_macro_fvgs(df_macro, top, htf_hours, top_h)

    def _scan_top(df_top, top_h, top_label):
        if df_top is None or df_top.empty:
            return
        for top in top_zones(df_top, top_kind):
            macro = ([(m, "4h") for m in collect_macro(df_4h, top, 4, top_h)]
                     + [(m, "6h") for m in collect_macro(df_6h, top, 6, top_h)])
            if not macro:
                continue
            search_start = top.cur_time + pd.Timedelta(hours=top_h)
            for mz, _mtf in macro:
                s1 = find_signal_in_htf_param(df_1h, df_15m, df_20m, top, mz,
                                              search_start, 60, "1h", htf_kind)
                s2 = find_signal_in_htf_param(df_2h, df_15m, df_20m, top, mz,
                                              search_start, 120, "2h", htf_kind)
                if s1 is None and s2 is None:
                    continue
                if s1 is None:
                    ch = s2
                elif s2 is None:
                    ch = s1
                else:
                    ch = s1 if s1["fvg_entry"].c2_time <= s2["fvg_entry"].c2_time else s2
                fe = ch["fvg_entry"]
                entry = (fe.bottom + fe.top) / 2.0
                depth = top.top - top.bottom
                sl = top.bottom + depth * OB_SL_DEPTH if top.direction == "LONG" else top.top - depth * OB_SL_DEPTH
                risk = abs(entry - sl)
                if risk <= 0 or (top.direction == "LONG" and sl >= entry) or \
                   (top.direction == "SHORT" and sl <= entry):
                    continue
                arm = fe.c2_time + pd.Timedelta(minutes=ch["fvg_tf_min"])
                signals.append((top.direction, float(entry), float(sl), float(risk), arm))

    _scan_top(df_1d, 24, "1d")
    _scan_top(df_12h, 12, "12h")
    seen, out = set(), []
    for s in sorted(signals, key=lambda x: x[4]):
        k = (s[4], s[0], round(s[1], 1))
        if k in seen:
            continue
        seen.add(k); out.append(s)
    return out


def simulate(signals, df_1m, rr):
    lo = df_1m["low"].to_numpy(); hi = df_1m["high"].to_numpy(); idx = df_1m.index
    ow = ol = nf = op = 0
    yr = defaultdict(lambda: [0, 0]); side = {"LONG": [0, 0], "SHORT": [0, 0]}
    for (d, entry, slv, risk, arm) in signals:
        sp = int(idx.searchsorted(arm, side="left"))
        if sp >= len(lo):
            continue
        end = min(sp + MAX_HOLD_MIN, len(lo))
        fh = np.where(lo[sp:end] <= entry)[0] if d == "LONG" else np.where(hi[sp:end] >= entry)[0]
        if not fh.size:
            nf += 1; continue
        f = sp + int(fh[0]); plo, phi = lo[f:end], hi[f:end]
        tp = entry + rr * risk if d == "LONG" else entry - rr * risk
        slm, tpm = (plo <= slv, phi >= tp) if d == "LONG" else (phi >= slv, plo <= tp)
        sf = int(np.argmax(slm)) if slm.any() else 10**9
        tf_ = int(np.argmax(tpm)) if tpm.any() else 10**9
        if sf == 10**9 and tf_ == 10**9:
            op += 1; continue
        win = tf_ < sf
        y = pd.Timestamp(arm).year
        if win:
            ow += 1
        else:
            ol += 1
        yr[y][0 if win else 1] += 1; side[d][0 if win else 1] += 1
    closed = ow + ol
    return {"n": len(signals), "closed": closed, "nf": nf, "open": op,
            "wr": ow / closed * 100 if closed else 0.0, "sumR": ow * rr - ol,
            "ptt": (ow * rr - ol) / closed if closed else 0.0,
            "L_R": side["LONG"][0] * rr - side["LONG"][1],
            "S_R": side["SHORT"][0] * rr - side["SHORT"][1],
            "year_R": {y: w * rr - l for y, (w, l) in yr.items()},
            "posyrs": sum(1 for (w, l) in yr.values() if w * rr - l > 0), "nyrs": len(yr)}


def main():
    PC = {}
    for sym in SYMBOLS:
        print(f"compose {sym}...", flush=True)
        d1 = load_1m(sym)
        PC[sym] = {"df_1m": d1, "tfs": {tl: rs(d1, fr) for tl, fr in
                   [("1d", "1d"), ("12h", "12h"), ("4h", "4h"), ("6h", "6h"),
                    ("1h", "1h"), ("2h", "2h"), ("15m", "15min"), ("20m", "20min")]}}

    print("\n" + "=" * 100)
    print("СТРОГИЙ live-скелет — честные объёмы (vs завышенный грид). RR=2.0 основной.")
    print("=" * 100)
    print(f"{'config':18} {'top/mac/htf':14} {'sym':>4} {'closed':>6} {'WR%':>6} "
          f"{'sumR':>7} {'ptt':>7} {'L_R':>6} {'S_R':>6} {'+yrs':>5}")
    for name, tk, mk, hk in CONFIGS:
        for sym in SYMBOLS:
            sigs = scan_strict(PC[sym]["tfs"], tk, mk, hk)
            m = simulate(sigs, PC[sym]["df_1m"], 2.0)
            print(f"{name:18} {tk+'/'+mk+'/'+hk:14} {sym[:3]:>4} {m['closed']:>6} "
                  f"{m['wr']:>6.1f} {m['sumR']:>+7.1f} {m['ptt']:>+7.3f} "
                  f"{m['L_R']:>+6.0f} {m['S_R']:>+6.0f} {m['posyrs']:>3}/{m['nyrs']}")
        print()

    # детальная год-разбивка для кандидатов @RR2.0
    print("=" * 100)
    print("ГОД-РАЗБИВКА кандидатов (RR=2.0)")
    print("=" * 100)
    for name, tk, mk, hk in CONFIGS[2:]:
        print(f"\n--- {name} ({tk}/{mk}/{hk}) ---")
        for sym in SYMBOLS:
            sigs = scan_strict(PC[sym]["tfs"], tk, mk, hk)
            m = simulate(sigs, PC[sym]["df_1m"], 2.0)
            yr = m["year_R"]
            line = " ".join(f"{y}:{yr.get(y, 0):+.0f}" for y in range(2020, 2027))
            print(f"  {sym:8} closed={m['closed']:4} sumR={m['sumR']:+.0f} ptt={m['ptt']:+.3f} | {line}")


if __name__ == "__main__":
    main()
