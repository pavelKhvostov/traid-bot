"""Phase 1 — detect ob_vc across all 8 HTFs on 6y BTC.

Canon: ~/smc-lib/elements/ob_vc/definition.md (#1-#8; #9 deferred to phase1_with_cond9).

Output: data/ob_vc_phase1.parquet with columns:
  htf, ltf, direction, ob_cur_open_ms, ob_cur_close_ms, born_ms,
  ob_zone_lo, ob_zone_hi, drop_lo, drop_hi, fract_level, fract_center_ms,
  fract_confirm_ms, valid_until_ms, n_components,
  fvg_c1_open_ms, fvg_c3_close_ms, fvg_zone_lo, fvg_zone_hi
(каждая строка = одна FVG-component; OB может появиться несколько раз)
"""
from __future__ import annotations
import sys, time, pathlib
from bisect import bisect_left
from collections import defaultdict

import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from _lib import (
    DATA_DIR, START_MS, HTF_TO_LTF, ALL_HTFS, ALL_LTFS, TFS_MS, N_FRACTAL,
    load_1m, aggregate_all_tfs, to_candles, detect_williams_n2,
)
from elements.ob.code import detect_ob
from elements.fvg.code import detect_fvg


t0 = time.time()
print("=" * 78)
print("Phase 1 — ob_vc detection across all 8 HTFs (canon #1-#8)")
print("=" * 78)

rows = load_1m()
print(f"\n1m bars: {len(rows):,}")

print("\nAggregating to all TFs...")
bars_raw = aggregate_all_tfs(rows)
candles = {tf: to_candles(b) for tf, b in bars_raw.items()}
for tf, b in bars_raw.items():
    print(f"  {tf:4}: {len(b):>7,} bars")


# ─── 1. Williams N=2 fractals on every LTF ──────────────────
print("\nDetecting Williams N=2 on all LTFs...")
fractals = {}  # tf -> {"FH": [...], "FL": [...]}
for ltf in ALL_LTFS:
    fhs, fls = detect_williams_n2(candles[ltf], n=N_FRACTAL)
    fractals[ltf] = {"FH": fhs, "FL": fls}
    print(f"  {ltf:4}: FH={len(fhs):>6,}  FL={len(fls):>6,}")

# Pre-extract arrays for fast bisect
fract_arrs = {}
for ltf in ALL_LTFS:
    for kind in ("FH", "FL"):
        arr = fractals[ltf][kind]
        fract_arrs[(ltf, kind)] = {
            "ts": [x[2] for x in arr],
            "level": [x[1] for x in arr],
        }


# ─── 2. FVGs on every LTF, split by direction ───────────────
print("\nDetecting FVGs on all LTFs...")
fvgs_by_ltf_dir = {(ltf, d): [] for ltf in ALL_LTFS for d in ("long", "short")}
for ltf in ALL_LTFS:
    cans = candles[ltf]
    ltf_ms = TFS_MS[ltf]
    for i in range(len(cans) - 2):
        fv = detect_fvg(cans[i], cans[i+1], cans[i+2])
        if fv is None: continue
        fvgs_by_ltf_dir[(ltf, fv.direction)].append({
            "c1_open_ms": cans[i].open_time,
            "c3_open_ms": cans[i+2].open_time,
            "c3_close_ms": cans[i+2].open_time + ltf_ms,
            "zone": fv.zone,
        })
for ltf in ALL_LTFS:
    nL = len(fvgs_by_ltf_dir[(ltf, "long")])
    nS = len(fvgs_by_ltf_dir[(ltf, "short")])
    print(f"  {ltf:4}: long={nL:>6,}  short={nS:>6,}")
for k, v in fvgs_by_ltf_dir.items():
    v.sort(key=lambda x: x["c1_open_ms"])
fvg_c1_arr = {k: [x["c1_open_ms"] for x in v] for k, v in fvgs_by_ltf_dir.items()}


# ─── 3. OBs on every HTF + actionable lifetime ──────────────
print("\nDetecting OBs on all HTFs with actionable lifetime...")
obs_by_htf = {htf: [] for htf in ALL_HTFS}
for htf in ALL_HTFS:
    cans = candles[htf]
    bars_arr = bars_raw[htf]
    htf_ms = TFS_MS.get(htf) or (2 if htf == "2d" else 3) * 1440 * 60_000
    for i in range(1, len(cans)):
        ob = detect_ob(cans[i-1], cans[i])
        if ob is None: continue
        zlo, zhi = ob.zone
        valid_until_ms = None
        for j in range(i+1, len(bars_arr)):
            close = bars_arr[j][4]
            if ob.direction == "long" and close < zlo:
                valid_until_ms = bars_arr[j][0]; break
            if ob.direction == "short" and close > zhi:
                valid_until_ms = bars_arr[j][0]; break
        if valid_until_ms is None:
            valid_until_ms = bars_arr[-1][0] + htf_ms * 2
        obs_by_htf[htf].append({
            "ob": ob,
            "cur_open_ms": cans[i].open_time,
            "cur_close_ms": cans[i].open_time + htf_ms,
            "valid_until_ms": valid_until_ms,
        })
total_obs = sum(len(v) for v in obs_by_htf.values())
print(f"  Total OBs: {total_obs:,}")
for htf in ALL_HTFS:
    nL = sum(1 for o in obs_by_htf[htf] if o["ob"].direction == "long")
    nS = sum(1 for o in obs_by_htf[htf] if o["ob"].direction == "short")
    print(f"  {htf:4}: long={nL:>5,}  short={nS:>5,}  total={len(obs_by_htf[htf]):>5,}")


# ─── 4. Match ob_vc per canon #1-#8 ─────────────────────────
print("\nMatching ob_vc (canon #1-#8)...")

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

def overlap(a, b): return max(a[0], b[0]) <= min(a[1], b[1])
def contained(inner, outer): return inner[0] >= outer[0] and inner[1] <= outer[1]


records = []
combo_counts = defaultdict(int)
unique_ob_vc_per_htf = defaultdict(set)

for htf in ALL_HTFS:
    for o_dict in obs_by_htf[htf]:
        ob = o_dict["ob"]
        cur_open_ms = o_dict["cur_open_ms"]
        cur_close_ms = o_dict["cur_close_ms"]
        valid_until_ms = o_dict["valid_until_ms"]
        prev, cur = ob.prev, ob.cur

        if ob.direction == "long":
            drop_area = (min(prev.low, cur.low), prev.open)
            drop_hi = prev.open
            low_ob_vc = drop_area[0]
            kind = "FH"
        else:
            drop_area = (prev.open, max(prev.high, cur.high))
            drop_hi = prev.open
            high_ob_vc = drop_area[1]
            kind = "FL"

        ob_qualifies = False
        for ltf in HTF_TO_LTF[htf]:
            ltf_ms = TFS_MS[ltf]
            first = find_first_fractal_past(ltf, kind, cur_open_ms, drop_hi, ob.direction)
            if first is None:
                continue
            fract_level, fract_center_ms = first
            fract_confirm_ms = fract_center_ms + (N_FRACTAL + 1) * ltf_ms

            if ob.direction == "long":
                allowed_range = (low_ob_vc, fract_level)
            else:
                allowed_range = (fract_level, high_ob_vc)

            # Relaxed #7 (2026-06-07): replace temporal с spatial: fvg.zone ⊆ drop_area.
            # Allow FVGs c1.open ≥ prev.open_time (i.e. within OB pair window = 2×HTF).
            fvg_list = fvgs_by_ltf_dir[(ltf, ob.direction)]
            c1_arr = fvg_c1_arr[(ltf, ob.direction)]
            _MIN_MS = 60_000
            htf_period_ms = TFS_MS.get(htf) or (2 * 1440 * _MIN_MS if htf == "2d"
                                                else 3 * 1440 * _MIN_MS)
            prev_open_ms = cur_open_ms - htf_period_ms
            i_lo = bisect_left(c1_arr, prev_open_ms)
            for k in range(i_lo, len(fvg_list)):
                fd = fvg_list[k]
                if fd["c1_open_ms"] > fract_confirm_ms: break
                if fd["c3_close_ms"] > fract_confirm_ms: continue
                if valid_until_ms <= fd["c3_close_ms"]: continue
                if not overlap(fd["zone"], drop_area): continue
                if not contained(fd["zone"], allowed_range): continue

                ob_qualifies = True
                combo_counts[(htf, ltf)] += 1
                born_ms = max(cur_close_ms, fd["c3_close_ms"])
                records.append({
                    "htf": htf, "ltf": ltf,
                    "direction": ob.direction,
                    "ob_cur_open_ms": cur_open_ms,
                    "ob_cur_close_ms": cur_close_ms,
                    "born_ms": born_ms,
                    "ob_zone_lo": ob.zone[0], "ob_zone_hi": ob.zone[1],
                    "drop_lo": drop_area[0], "drop_hi": drop_area[1],
                    "fract_level": fract_level,
                    "fract_center_ms": fract_center_ms,
                    "fract_confirm_ms": fract_confirm_ms,
                    "valid_until_ms": valid_until_ms,
                    "fvg_c1_open_ms": fd["c1_open_ms"],
                    "fvg_c3_close_ms": fd["c3_close_ms"],
                    "fvg_zone_lo": fd["zone"][0],
                    "fvg_zone_hi": fd["zone"][1],
                })

        if ob_qualifies:
            unique_ob_vc_per_htf[htf].add((ob.direction, cur_open_ms))


# ─── 5. Save & report ────────────────────────────────────────
df = pd.DataFrame(records)
out = DATA_DIR / "ob_vc_phase1.parquet"
df.to_parquet(out, index=False)

print(f"\n{'='*78}")
print(f"RESULTS  (saved → {out.relative_to(pathlib.Path.home())})")
print(f"{'='*78}")
print(f"\nTotal FVG-components:  {len(df):,}")
print(f"Total unique ob_vc instances:  {sum(len(s) for s in unique_ob_vc_per_htf.values()):,}\n")

print(f"{'HTF':<5} {'OBs':>7} {'ob_vc':>7} {'rate':>6}   {'LTFs':<14} {'components per LTF'}")
print("-" * 90)
for htf in ALL_HTFS:
    n_obs = len(obs_by_htf[htf])
    n_ob_vc = len(unique_ob_vc_per_htf[htf])
    rate = n_ob_vc / n_obs * 100 if n_obs else 0
    ltf_parts = []
    for ltf in HTF_TO_LTF[htf]:
        c = combo_counts[(htf, ltf)]
        ltf_parts.append(f"{ltf}={c}")
    print(f"{htf:<5} {n_obs:>7,} {n_ob_vc:>7,} {rate:>5.1f}%   {'/'.join(HTF_TO_LTF[htf]):<14} {'  '.join(ltf_parts)}")

print(f"\nElapsed: {time.time() - t0:.1f}s")
