"""Compute 24-type ob_vc 2h classification + TBM for any SYMBOL (e.g. ETHUSDT).

Reuses BTC canon (#1-#8 with relaxed #7; LTF FVG component validated against
drop_area + allowed_range; LTF priority 15m → 20m fallback).
Per ob_vc: pick chosen FVG (top for long, bottom for short), TBM with
deep=0.8 if n_FVG ≥ 2 else 0.2, SL=low/high_ob_vc, fixed TP1R, horizon 14d on 1m.
Outputs counts + WR/EV/ΣR/avg R% per T1a..T16.
"""
from __future__ import annotations
import csv, sys, time, pathlib
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from _lib import TFS_MS, N_FRACTAL, agg, to_candles, detect_williams_n2
from elements.ob.code import detect_ob
from elements.fvg.code import detect_fvg


SYMBOL = (sys.argv[1] if len(sys.argv) > 1 else "ETHUSDT").upper()
CSV_PATH = pathlib.Path.home() / f"traid-bot/data/{SYMBOL}_1m_vic_vadim.csv"
HTF = "2h"
LTFS = ("15m", "20m")

START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def load_1m_symbol() -> list[tuple]:
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
            if t < START_MS: continue
            rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return rows


def overlap(a, b): return max(a[0], b[0]) <= min(a[1], b[1])
def contained(inner, outer): return inner[0] >= outer[0] and inner[1] <= outer[1]


HORIZON_MS = 14 * 24 * 3600 * 1000


def tbm_one(direction, fvg_lo, fvg_hi, drop_lo, drop_hi, n_comp,
            born_ms, ts_1m, h_1m, l_1m):
    """Fixed TP1R on 1m, horizon 14d. Returns dict with touched/outcome/R/entry."""
    if direction == "long":
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = fvg_hi - deep * (fvg_hi - fvg_lo)
        sl = drop_lo
        if entry <= sl:
            return {"touched": False, "entry": entry, "R": None}
        R = entry - sl
        i_start = int(np.searchsorted(ts_1m, born_ms))
        if i_start >= len(ts_1m):
            return {"touched": False, "entry": entry, "R": R}
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        slice_l = l_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(slice_l <= entry)) if (slice_l <= entry).any() else -1
        if touch_rel == -1:
            return {"touched": False, "entry": entry, "R": R}
        touch_idx = i_start + touch_rel
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]
        TP1 = entry + R
        tp1_rel = int(np.argmax(post_h >= TP1)) if (post_h >= TP1).any() else -1
        sl_rel  = int(np.argmax(post_l <= sl))  if (post_l <= sl).any()  else -1
        if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
            return {"touched": True, "outcome": "win",  "entry": entry, "R": R}
        if sl_rel != -1:
            return {"touched": True, "outcome": "loss", "entry": entry, "R": R}
        return {"touched": True, "outcome": "timeout",  "entry": entry, "R": R}
    else:
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = fvg_lo + deep * (fvg_hi - fvg_lo)
        sl = drop_hi
        if entry >= sl:
            return {"touched": False, "entry": entry, "R": None}
        R = sl - entry
        i_start = int(np.searchsorted(ts_1m, born_ms))
        if i_start >= len(ts_1m):
            return {"touched": False, "entry": entry, "R": R}
        i_end = min(len(ts_1m) - 1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
        slice_h = h_1m[i_start:i_end+1]
        touch_rel = int(np.argmax(slice_h >= entry)) if (slice_h >= entry).any() else -1
        if touch_rel == -1:
            return {"touched": False, "entry": entry, "R": R}
        touch_idx = i_start + touch_rel
        post_h = h_1m[touch_idx:i_end+1]
        post_l = l_1m[touch_idx:i_end+1]
        TP1 = entry - R
        tp1_rel = int(np.argmax(post_l <= TP1)) if (post_l <= TP1).any() else -1
        sl_rel  = int(np.argmax(post_h >= sl))  if (post_h >= sl).any()  else -1
        if tp1_rel != -1 and (sl_rel == -1 or tp1_rel <= sl_rel):
            return {"touched": True, "outcome": "win",  "entry": entry, "R": R}
        if sl_rel != -1:
            return {"touched": True, "outcome": "loss", "entry": entry, "R": R}
        return {"touched": True, "outcome": "timeout",  "entry": entry, "R": R}


def main():
    t0 = time.time()
    print(f"[{SYMBOL}] Loading 1m...")
    rows = load_1m_symbol()
    print(f"[{SYMBOL}] 1m bars: {len(rows):,} "
          f"({datetime.fromtimestamp(rows[0][0]/1000, tz=timezone.utc):%Y-%m-%d} → "
          f"{datetime.fromtimestamp(rows[-1][0]/1000, tz=timezone.utc):%Y-%m-%d})")

    ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
    h_1m  = np.array([r[2] for r in rows], dtype=np.float64)
    l_1m  = np.array([r[3] for r in rows], dtype=np.float64)

    # ─── Aggregate ─────────────────────────────────────────
    bars_htf = agg(rows, TFS_MS[HTF], anchor=0)
    bars_ltf = {ltf: agg(rows, TFS_MS[ltf], anchor=0) for ltf in LTFS}
    cans_htf = to_candles(bars_htf)
    cans_ltf = {ltf: to_candles(bars_ltf[ltf]) for ltf in LTFS}
    print(f"  {HTF}: {len(cans_htf):,} bars; " +
          "; ".join(f"{ltf}: {len(cans_ltf[ltf]):,}" for ltf in LTFS))

    # ─── Williams fractals on LTFs ─────────────────────────
    fract_arrs = {}
    for ltf in LTFS:
        fhs, fls = detect_williams_n2(cans_ltf[ltf], n=N_FRACTAL)
        for kind, arr in (("FH", fhs), ("FL", fls)):
            fract_arrs[(ltf, kind)] = {
                "ts": [x[2] for x in arr],
                "level": [x[1] for x in arr],
            }

    # ─── FVGs on LTFs, split by dir ────────────────────────
    fvgs = {(ltf, d): [] for ltf in LTFS for d in ("long", "short")}
    for ltf in LTFS:
        cans = cans_ltf[ltf]
        ltf_ms = TFS_MS[ltf]
        for i in range(len(cans) - 2):
            fv = detect_fvg(cans[i], cans[i+1], cans[i+2])
            if fv is None: continue
            fvgs[(ltf, fv.direction)].append({
                "c1_open_ms": cans[i].open_time,
                "c3_close_ms": cans[i+2].open_time + ltf_ms,
                "zone": fv.zone,
            })
    for v in fvgs.values():
        v.sort(key=lambda x: x["c1_open_ms"])
    fvg_c1 = {k: [x["c1_open_ms"] for x in v] for k, v in fvgs.items()}

    # ─── OBs on 2h + actionable lifetime ───────────────────
    obs = []
    htf_ms = TFS_MS[HTF]
    for i in range(1, len(cans_htf)):
        ob = detect_ob(cans_htf[i-1], cans_htf[i])
        if ob is None: continue
        zlo, zhi = ob.zone
        valid_until = None
        for j in range(i+1, len(bars_htf)):
            close = bars_htf[j][4]
            if ob.direction == "long" and close < zlo:
                valid_until = bars_htf[j][0]; break
            if ob.direction == "short" and close > zhi:
                valid_until = bars_htf[j][0]; break
        if valid_until is None:
            valid_until = bars_htf[-1][0] + 2 * htf_ms
        obs.append({
            "ob": ob,
            "cur_open_ms": cans_htf[i].open_time,
            "cur_close_ms": cans_htf[i].open_time + htf_ms,
            "valid_until_ms": valid_until,
            "idx": i,
        })
    print(f"  OBs on {HTF}: {len(obs):,}")

    # ─── Match ob_vc per canon ─────────────────────────────
    def find_first_fractal_past(ltf, kind, after_ms, threshold, direction):
        arr = fract_arrs[(ltf, kind)]
        ts = arr["ts"]; lv = arr["level"]
        idx = bisect_left(ts, after_ms)
        for j in range(idx, len(ts)):
            if direction == "long" and lv[j] > threshold:
                return (lv[j], ts[j])
            if direction == "short" and lv[j] < threshold:
                return (lv[j], ts[j])
        return None

    records = []
    unique_ob_vc = set()
    for o in obs:
        ob = o["ob"]
        cur_open_ms = o["cur_open_ms"]; cur_close_ms = o["cur_close_ms"]
        valid_until_ms = o["valid_until_ms"]
        prev, cur = ob.prev, ob.cur
        if ob.direction == "long":
            drop_area = (min(prev.low, cur.low), prev.open)
            kind = "FH"
        else:
            drop_area = (prev.open, max(prev.high, cur.high))
            kind = "FL"
        drop_hi = prev.open

        ob_qualifies = False
        # priority 15m → 20m
        chosen_ltf = None
        for ltf in LTFS:
            ltf_ms = TFS_MS[ltf]
            first = find_first_fractal_past(ltf, kind, cur_open_ms, drop_hi, ob.direction)
            if first is None: continue
            fract_level, fract_center_ms = first
            fract_confirm_ms = fract_center_ms + (N_FRACTAL + 1) * ltf_ms
            if ob.direction == "long":
                allowed_range = (drop_area[0], fract_level)
            else:
                allowed_range = (fract_level, drop_area[1])

            prev_open_ms = cur_open_ms - htf_ms
            fvg_list = fvgs[(ltf, ob.direction)]
            c1_arr = fvg_c1[(ltf, ob.direction)]
            i_lo = bisect_left(c1_arr, prev_open_ms)
            comps = []
            for k in range(i_lo, len(fvg_list)):
                fd = fvg_list[k]
                if fd["c1_open_ms"] > fract_confirm_ms: break
                if fd["c3_close_ms"] > fract_confirm_ms: continue
                if valid_until_ms <= fd["c3_close_ms"]: continue
                if not overlap(fd["zone"], drop_area): continue
                if not contained(fd["zone"], allowed_range): continue
                comps.append(fd)
            if comps:
                ob_qualifies = True
                chosen_ltf = ltf
                n_comp = len(comps)
                chosen_comps = comps
                break  # 15m priority — drop 20m if 15m found
        if not ob_qualifies: continue
        unique_ob_vc.add((ob.direction, cur_open_ms))

        # Pick chosen FVG: top for long (max hi), bottom for short (min lo)
        if ob.direction == "long":
            chosen_fvg = max(chosen_comps, key=lambda x: x["zone"][1])
        else:
            chosen_fvg = min(chosen_comps, key=lambda x: x["zone"][0])
        fvg_lo, fvg_hi = chosen_fvg["zone"]
        born_ms = max(cur_close_ms, chosen_fvg["c3_close_ms"])
        tbm = tbm_one(ob.direction, fvg_lo, fvg_hi,
                      drop_area[0], drop_area[1], n_comp,
                      born_ms, ts_1m, h_1m, l_1m)

        # ─── Classify 24 types ────────────────────────────
        idx = o["idx"]
        if idx < 3: continue
        n2 = cans_htf[idx-3]; n1 = cans_htf[idx-2]
        prev_c = cans_htf[idx-1]; cur_c = cans_htf[idx]
        if ob.direction == "long":
            swept = min(prev_c.low, cur_c.low) < min(n1.low, n2.low)
            extreme = "prev" if prev_c.low < cur_c.low else "cur"
        else:
            swept = max(prev_c.high, cur_c.high) > max(n1.high, n2.high)
            extreme = "prev" if prev_c.high > cur_c.high else "cur"
        n_class = "≥2" if n_comp >= 2 else "1"

        if extreme == "prev":
            if ob.direction == "long":
                pw = min(prev_c.open, prev_c.close) - prev_c.low
                cw = min(cur_c.open,  cur_c.close)  - cur_c.low
            else:
                pw = prev_c.high - max(prev_c.open, prev_c.close)
                cw = cur_c.high  - max(cur_c.open,  cur_c.close)
            r = float("inf") if cw < 0.01 else pw / cw
            strong = (r >= 2.0)
        else:
            strong = None

        # T-ID mapping (same as reclassify_24_types.py)
        ORIG_PREV = {("long",True,"≥2"):"T1", ("long",True,"1"):"T3",
                     ("long",False,"≥2"):"T5", ("long",False,"1"):"T7",
                     ("short",True,"≥2"):"T9", ("short",True,"1"):"T11",
                     ("short",False,"≥2"):"T13", ("short",False,"1"):"T15"}
        ORIG_CUR  = {("long",True,"≥2"):"T2", ("long",True,"1"):"T4",
                     ("long",False,"≥2"):"T6", ("long",False,"1"):"T8",
                     ("short",True,"≥2"):"T10",("short",True,"1"):"T12",
                     ("short",False,"≥2"):"T14",("short",False,"1"):"T16"}
        key = (ob.direction, bool(swept), n_class)
        if extreme == "prev":
            base = ORIG_PREV.get(key);
            if base is None: continue
            t_id = base + ("a" if strong else "b")
        else:
            t_id = ORIG_CUR.get(key)
            if t_id is None: continue
        rec = {"t_id": t_id, "direction": ob.direction,
               "extreme": extreme, "ltf": chosen_ltf,
               "n_comp": n_comp,
               "born_ms": int(born_ms),
               "cur_open_ms": int(cur_open_ms),
               "cur_close_ms": int(cur_close_ms),
               "fvg_zone_lo": float(fvg_lo), "fvg_zone_hi": float(fvg_hi),
               "drop_lo": float(drop_area[0]), "drop_hi": float(drop_area[1]),
               "entry": tbm.get("entry"), "R": tbm.get("R"),
               "touched": bool(tbm.get("touched", False)),
               "outcome": tbm.get("outcome")}
        records.append(rec)

    rdf = pd.DataFrame(records)
    out_dir = pathlib.Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{SYMBOL}_2h_24types.parquet"
    rdf.to_parquet(out, index=False)

    T_ORDER = ["T1a","T1b","T2","T3a","T3b","T4","T5a","T5b","T6","T7a","T7b","T8",
               "T9a","T9b","T10","T11a","T11b","T12","T13a","T13b","T14","T15a","T15b","T16"]
    long_n = (rdf.direction == "long").sum()
    short_n = (rdf.direction == "short").sum()
    print(f"\n[{SYMBOL}] 2h ob_vc total: {len(unique_ob_vc):,} unique "
          f"({long_n:,} long / {short_n:,} short)")
    print(f"Saved → {out}")
    print(f"\n{'T':<6} {'N':>5} {'tch':>5} {'WR%':>6} {'EV':>9} {'ΣR':>6} {'R%':>6}")
    print("─" * 50)

    counts = {}
    tbm_full = {}
    rpct = {}
    total_sigR = 0
    for t in T_ORDER:
        g = rdf[rdf.t_id == t]
        n = len(g)
        n_t = int(g.touched.sum())
        tg = g[g.touched]
        wins = int((tg.outcome == "win").sum())
        losses = int((tg.outcome == "loss").sum())
        wr = wins / n_t * 100 if n_t else 0.0
        ev = (2 * wr / 100) - 1 if n_t else 0.0
        sigR = wins - losses
        total_sigR += sigR
        # R% — average over touched trades (entry/R defined)
        gtouch = g[g.touched & g.entry.notna() & g.R.notna()]
        if len(gtouch):
            rpct_vals = (gtouch.R / gtouch.entry) * 100
            avg_rpct = float(rpct_vals.mean())
        else:
            avg_rpct = 0.0
        counts[t] = n
        tbm_full[t] = (wr, ev, sigR)
        rpct[t] = avg_rpct
        print(f"{t:<6} {n:>5} {n_t:>5} {wr:>5.1f}% {ev:>+7.3f}R {sigR:>+5}R {avg_rpct:>5.2f}%")

    print(f"\n  Σ {SYMBOL} 24 types: {total_sigR:+}R за {len(rdf):,} ob_vc")

    # Emit dict literals for PNG script
    print("\n# Dicts for plot script:")
    print(f'DATA_{SYMBOL[:3]} = {{')
    for t in T_ORDER:
        print(f'    "{t}": {counts[t]},')
    print("}")
    print(f'TBM_{SYMBOL[:3]} = {{')
    for t in T_ORDER:
        wr, ev, sigR = tbm_full[t]
        print(f'    "{t}": ({wr:.1f}, {ev:+.3f}, {sigR:+}),')
    print("}")
    print(f'RPCT_{SYMBOL[:3]} = {{')
    for t in T_ORDER:
        print(f'    "{t}": {rpct[t]:.2f},')
    print("}")
    print(f"\nElapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
