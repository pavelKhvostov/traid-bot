"""C4 sub-basket — кандидаты D7..D14.

Тест 8 новых независимых Dx сверх текущего D1..D6:

  D7  VOL_SPIKE     L0 / S50 + vol_z ≥ +2σ      / ANY
  D8  RETEST        L0 / S50 → close inside в N=3 баров (fire @ retest)
  D9  EDGE          L0 / shallow pen 5-25% + close outside  / WIDE
  D10 iFVG          FVG broken (close beyond), затем opposite-side touch
  D11 FRAC_CONF     L0 / S50 + Williams n=2 фрактал в окне 30 баров near level
  D12 HMA_CONF      L0 / S50 + sweep level near HMA-78 или HMA-200 (≤0.3% ATR)
  D13 CINS          L0 / S70 + close INSIDE zone (consumption) / WIDE
  D14 MARUBOZU      L0 / S50 + sweep-bar body/range ≥ 0.85 / ANY

Baseline: pred12h_baseline_v2.parquet (n=1356, conf=659, WR 48.60%).
Output: per-Dx stats + ranked CSV.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fvg.code import detect_fvg
from indicators.trend_line_asvk import hma

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASELINE = pathlib.Path.home() / "Desktop/pred12h_baseline_v2.parquet"
OUT = pathlib.Path.home() / "Desktop/c4_d7_d14_grid.csv"

MS_M = 60_000
TF12 = 12 * 60 * MS_M
TFD = 24 * 60 * MS_M
TF2D = 2 * TFD
TF3D = 3 * TFD
TFW = 7 * TFD
MON_ANCHOR = int(datetime(2017, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

# ─── Load 1m ──────────────────────────────────────────────────
print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS or t > END_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
print(f"  1m bars: {len(rows):,}")


def agg(d, tfms, anchor=0):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in d:
        b = ts - ((ts - anchor) % tfms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


bars12 = agg(rows, TF12); n12 = len(bars12)
t12 = np.array([b[0] for b in bars12], dtype=np.int64)
o12 = np.array([b[1] for b in bars12])
h12 = np.array([b[2] for b in bars12])
l12 = np.array([b[3] for b in bars12])
c12 = np.array([b[4] for b in bars12])
v12 = np.array([b[5] for b in bars12])
print(f"  12h bars: {n12:,}")

# ─── Per-bar derived series ───────────────────────────────────
body = np.abs(c12 - o12)
rng = h12 - l12
safe_rng = np.where(rng > 0, rng, 1.0)
body_pct = body / safe_rng

# ATR(14)
def atr_calc(highs, lows, closes, n=14):
    tr = np.zeros(len(highs))
    for i in range(1, len(highs)):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    out = np.zeros(len(highs))
    for i in range(n, len(highs)):
        out[i] = tr[i-n+1:i+1].mean()
    return out

atr12 = atr_calc(h12, l12, c12, 14)

# Volume z-score (rolling 50)
v_ser = pd.Series(v12)
v_mean = v_ser.rolling(50, min_periods=20).mean().bfill().values
v_std = v_ser.rolling(50, min_periods=20).std().bfill().values
v_z = (v12 - v_mean) / np.where(v_std > 0, v_std, 1.0)

# HMA-78 / HMA-200 on 12h closes
print("Computing HMA-78/200 on 12h closes...")
hma78_list = hma(c12.tolist(), 78)
hma200_list = hma(c12.tolist(), 200)
hma78 = np.array([x if x is not None else np.nan for x in hma78_list])
hma200 = np.array([x if x is not None else np.nan for x in hma200_list])

# Williams n=2 confirmation on every bar
fh_conf = np.zeros(n12, dtype=bool)
fl_conf = np.zeros(n12, dtype=bool)
fh_conf[:-2] = (h12[:-2] > h12[1:-1]) & (h12[:-2] > h12[2:])
fl_conf[:-2] = (l12[:-2] < l12[1:-1]) & (l12[:-2] < l12[2:])

# ─── FVG scan ─────────────────────────────────────────────────
bars_by_tf = {"12h": bars12, "D": agg(rows, TFD), "2D": agg(rows, TF2D),
              "3D": agg(rows, TF3D), "W": agg(rows, TFW, MON_ANCHOR)}
cans_by_tf = {tf: [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bb]
              for tf, bb in bars_by_tf.items()}
tfms_map = {"12h": TF12, "D": TFD, "2D": TF2D, "3D": TF3D, "W": TFW}

print("Scanning FVGs across TFs...")
all_fvg = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans) - 2):
        fv = detect_fvg(cans[i], cans[i+1], cans[i+2])
        if fv is None: continue
        all_fvg.append({
            "tf": tf, "direction": fv.direction,
            "zlo": fv.zone[0], "zhi": fv.zone[1],
            "c3_ms": cans[i+2].open_time,
            "ready_ms": cans[i+2].open_time + tfms,
        })
print(f"  Total FVGs: {len(all_fvg):,}")

# Per-FVG event timeline
print("Computing per-FVG event timelines...")
for z in all_fvg:
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    z["events"] = []
    z["broken_at"] = None  # first close THROUGH (for D10 iFVG)
    if sp >= n12: continue
    zlo, zhi = z["zlo"], z["zhi"]
    w = zhi - zlo
    if w <= 0: continue
    for k in range(sp, n12):
        if z["direction"] == "short":
            hh, cc = h12[k], c12[k]
            if hh < zlo: continue
            pen = min((hh - zlo) / w * 100, 999)
            ci = (cc >= zlo and cc <= zhi)
            co_far = (cc < zlo)
            co_thru = (cc > zhi)
        else:
            ll, cc = l12[k], c12[k]
            if ll > zhi: continue
            pen = min((zhi - ll) / w * 100, 999)
            ci = (cc >= zlo and cc <= zhi)
            co_far = (cc > zhi)
            co_thru = (cc < zlo)
        z["events"].append((k, pen, ci, co_far, co_thru))
        if z["broken_at"] is None and co_thru:
            z["broken_at"] = k

# ─── Filter helper ────────────────────────────────────────────
def filt_pass(z, k, ftype):
    if ftype == "ANY": return True
    age = (t12[k] - z["c3_ms"]) // TF12
    width = z["zhi"] - z["zlo"]
    atr = atr12[k] if atr12[k] > 0 else 1.0
    if ftype == "WIDE": return width / atr >= 0.7
    if ftype == "AGE50": return age >= 50
    return False

# ─── D-conditions ─────────────────────────────────────────────
def dx_d7_vol_spike():
    """L0 / S50 + vol_z[sweep_bar] ≥ +2 / ANY."""
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far, _ in z["events"]:
            if pen >= 50 and co_far and v_z[k] >= 2.0:
                fires.add((k, z["direction"]))
                break
    return fires

def dx_d8_retest(N=3):
    """L0 / S50 → close inside в окне +N баров. Fire @ retest bar."""
    fires = set()
    for z in all_fvg:
        sweep_k = None
        for k, pen, ci, co_far, _ in z["events"]:
            if sweep_k is None and pen >= 50 and co_far:
                sweep_k = k
                continue
            if sweep_k is not None and k <= sweep_k + N and ci:
                fires.add((k, z["direction"]))
                break
    return fires

def dx_d9_edge():
    """L0 / shallow pen [5..25%] + close OUTSIDE / WIDE."""
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far, _ in z["events"]:
            if 5 <= pen <= 25 and co_far and filt_pass(z, k, "WIDE"):
                fires.add((k, z["direction"]))
                break
    return fires

def dx_d10_ifvg():
    """FVG broken (close THROUGH), затем возврат к зоне с противоположной стороны.

    После broken_at: ждём следующего touch'а; fire @ этот touch.
    """
    fires = set()
    for z in all_fvg:
        br = z["broken_at"]
        if br is None: continue
        for k, pen, ci, co_far, _ in z["events"]:
            if k <= br: continue
            # Любой повторный touch после пробоя
            fires.add((k, z["direction"]))
            break
    return fires

def dx_d11_frac_conf(window=30, eps_atr=0.005):
    """L0 / S50 + Williams n=2 fractal в окне 30 баров на близком уровне."""
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far, _ in z["events"]:
            if not (pen >= 50 and co_far): continue
            atr = atr12[k] if atr12[k] > 0 else 1.0
            if z["direction"] == "short":
                ref = h12[k]
                lo = max(0, k - window)
                if np.any(fh_conf[lo:k] & (np.abs(h12[lo:k] - ref) < eps_atr * atr)):
                    fires.add((k, z["direction"]))
                    break
            else:
                ref = l12[k]
                lo = max(0, k - window)
                if np.any(fl_conf[lo:k] & (np.abs(l12[lo:k] - ref) < eps_atr * atr)):
                    fires.add((k, z["direction"]))
                    break
    return fires

def dx_d12_hma_conf(tol_atr=1.0):
    """L0 / S50 + sweep level в пределах 1.0×ATR от HMA-78/200."""
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far, _ in z["events"]:
            if not (pen >= 50 and co_far): continue
            if np.isnan(hma78[k]) and np.isnan(hma200[k]): continue
            atr = atr12[k] if atr12[k] > 0 else 1.0
            tol = tol_atr * atr
            level = h12[k] if z["direction"] == "short" else l12[k]
            near_78 = (not np.isnan(hma78[k])) and abs(hma78[k] - level) <= tol
            near_200 = (not np.isnan(hma200[k])) and abs(hma200[k] - level) <= tol
            if near_78 or near_200:
                fires.add((k, z["direction"]))
                break
    return fires

def dx_d13_cins():
    """L0 / pen ≥70% + close INSIDE / WIDE — consumption rejection."""
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far, _ in z["events"]:
            if pen >= 70 and ci and filt_pass(z, k, "WIDE"):
                fires.add((k, z["direction"]))
                break
    return fires

def dx_d14_rejection_bar(body_min=0.70):
    """L0 / S50 + **следующий бар** (k+1) — rejection candle body/rng ≥ 0.70
    в обратную сторону от sweep direction.

    (Marubozu-as-sweep-bar даёт 0: sweep требует wick ≥ 50%, что несовместимо
    с body ≥ 0.85. Поэтому проверяем «реакционный бар» — k+1.)
    """
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far, _ in z["events"]:
            if not (pen >= 50 and co_far): continue
            if k + 1 >= n12: continue
            kk = k + 1
            # rejection bar = strong body in opposite direction
            if body_pct[kk] < body_min: continue
            if z["direction"] == "short":  # FH pivot — нужен bearish bar k+1
                if c12[kk] < o12[kk]:
                    fires.add((k, z["direction"]))
                    break
            else:  # FL pivot — нужен bullish bar k+1
                if c12[kk] > o12[kk]:
                    fires.add((k, z["direction"]))
                    break
    return fires

# ─── Existing D1..D6 (for overlap analysis) ───────────────────
def evaluate_dx_classic(lifecycle, sweep_mode, filter_type):
    """Classic D1-D6 evaluator (subset of pred12h_c4_subbasket.py)."""
    fires = set()
    for z in all_fvg:
        # Lifecycle gate
        au = None
        if lifecycle == "L1":
            for k, pen, ci, _, _ in z["events"]:
                if pen >= 50: au = k + 1; break
        elif lifecycle == "L2":
            for k, pen, ci, _, _ in z["events"]:
                if pen >= 100: au = k + 1; break
        for k, pen, ci, co_far, _ in z["events"]:
            if au is not None and k >= au: break
            sweep_ok = False
            if sweep_mode == "S50": sweep_ok = pen >= 50 and co_far
            elif sweep_mode == "S70": sweep_ok = pen >= 70 and co_far
            elif sweep_mode == "S100": sweep_ok = pen >= 100 and co_far
            elif sweep_mode == "W50": sweep_ok = pen >= 50
            elif sweep_mode == "W100": sweep_ok = pen >= 100
            if not sweep_ok: continue
            if not filt_pass_classic(z, k, filter_type): continue
            fires.add((k, z["direction"]))
            break
    return fires

def filt_pass_classic(z, k, ftype):
    if ftype == "ANY": return True
    age = (t12[k] - z["c3_ms"]) // TF12
    width = z["zhi"] - z["zlo"]
    atr = atr12[k] if atr12[k] > 0 else 1.0
    is_htf = z["tf"] in ("D", "2D", "3D", "W")
    if ftype == "WIDE": return width / atr >= 0.7
    if ftype == "AGE50": return age >= 50
    if ftype == "AGE50_WIDE": return age >= 50 and width / atr >= 0.7
    if ftype == "HTF_WIDE": return is_htf and width / atr >= 0.7
    return False

D_classic = {
    "D1": ("L0", "S100", "WIDE"),
    "D2": ("L0", "S50",  "AGE50_WIDE"),
    "D3": ("L0", "S70",  "AGE50"),
    "D4": ("L0", "S50",  "HTF_WIDE"),
    "D5": ("L1", "W50",  "AGE50"),
    "D6": ("L2", "W100", "AGE50"),
}

# ─── Baseline match ───────────────────────────────────────────
print("Loading baseline...")
df_base = pd.read_parquet(BASELINE)
ts_to_idx = {int(t): k for k, t in enumerate(t12)}
pivot_map = {}
for _, p in df_base.iterrows():
    ts_ms = int(p["pivot_open_ts_ms"])
    if ts_ms not in ts_to_idx: continue
    k = ts_to_idx[ts_ms]
    pdir = p["direction"]
    expected_fvg_dir = "short" if pdir == "high" else "long"
    pivot_map[(k, expected_fvg_dir)] = (bool(p["confirmed"]), pdir, ts_ms)
print(f"  Baseline n={len(df_base)}, conf={df_base['confirmed'].sum()}, "
      f"WR={100*df_base['confirmed'].mean():.2f}%")


def stats(fires):
    matched = [pivot_map[(k, d)] for (k, d) in fires if (k, d) in pivot_map]
    n = len(matched)
    conf = sum(1 for c, _, _ in matched if c)
    wr = 100 * conf / n if n else 0.0
    return n, conf, wr, matched


# ─── Evaluate D7-D14 ──────────────────────────────────────────
print("\n" + "="*78)
print("D7-D14 Standalone Results")
print("="*78)

candidates = [
    ("D7",  "VOL_SPIKE",   "L0 / S50 + vol_z≥+2σ / ANY",       dx_d7_vol_spike),
    ("D8",  "RETEST",      "L0 / S50→inside (N=3) / ANY",      dx_d8_retest),
    ("D9",  "EDGE",        "L0 / pen 5-25% + close OUT / WIDE", dx_d9_edge),
    ("D10", "iFVG",        "broken→re-touch / ANY",             dx_d10_ifvg),
    ("D11", "FRAC_CONF",   "L0 / S50 + Williams n=2 ≤30b / ANY", dx_d11_frac_conf),
    ("D12", "HMA_CONF",    "L0 / S50 + ≤1.0×ATR от HMA-78/200", dx_d12_hma_conf),
    ("D13", "CINS",        "L0 / pen≥70% + close IN / WIDE",    dx_d13_cins),
    ("D14", "REJ_BAR",     "L0 / S50 + reject bar k+1 body≥0.70", dx_d14_rejection_bar),
]

print(f"  {'D':<4} {'name':<12} {'params':<38} {'n':>5} {'conf':>5} {'WR':>7} {'Δ_base':>7}")
print("  " + "-"*78)

dx_results = {}
for code, name, params, fn in candidates:
    fires = fn()
    n, conf, wr, matched = stats(fires)
    delta = wr - 48.60
    dx_results[code] = {"name": name, "params": params, "n": n, "conf": conf,
                        "wr": wr, "delta": delta, "fires": fires, "matched": matched}
    print(f"  {code:<4} {name:<12} {params:<38} {n:>5} {conf:>5} {wr:>6.2f}% {delta:>+6.2f}")

# ─── D1..D6 union (for unique-events analysis) ────────────────
print("\nComputing D1..D6 union for overlap...")
d16_union_fires = set()
d16_individual = {}
for code, (lc, sw, ft) in D_classic.items():
    f = evaluate_dx_classic(lc, sw, ft)
    d16_individual[code] = f
    d16_union_fires |= f

n_u, c_u, wr_u, _ = stats(d16_union_fires)
print(f"  D1..D6 union: n={n_u}, conf={c_u}, WR={wr_u:.2f}%")

# ─── Unique events: fires in Dx but NOT in D1..D6 ─────────────
print("\n" + "="*78)
print("D7-D14: Unique events (NOT in D1..D6) — pure incremental edge")
print("="*78)
print(f"  {'D':<4} {'n_uniq':>6} {'conf_uniq':>9} {'WR_uniq':>8} "
      f"{'n_all':>5} {'WR_all':>7} {'overlap%':>9}")
print("  " + "-"*78)

ranked = []
for code, _, _, fn in candidates:
    fires_full = dx_results[code]["fires"]
    fires_uniq = fires_full - d16_union_fires
    matched_uniq = [pivot_map[(k, d)] for (k, d) in fires_uniq if (k, d) in pivot_map]
    n_uq = len(matched_uniq)
    c_uq = sum(1 for c, _, _ in matched_uniq if c)
    wr_uq = 100 * c_uq / n_uq if n_uq else 0.0
    n_full = dx_results[code]["n"]
    wr_full = dx_results[code]["wr"]
    overlap = 100 * (1 - n_uq / n_full) if n_full else 0.0
    print(f"  {code:<4} {n_uq:>6} {c_uq:>9} {wr_uq:>7.2f}% "
          f"{n_full:>5} {wr_full:>6.2f}% {overlap:>8.1f}%")
    ranked.append({
        "Dx": code, "name": dx_results[code]["name"],
        "params": dx_results[code]["params"],
        "n_standalone": n_full, "WR_standalone": round(wr_full, 2),
        "delta_baseline": round(dx_results[code]["delta"], 2),
        "n_unique": n_uq, "conf_unique": c_uq,
        "WR_unique": round(wr_uq, 2),
        "overlap_pct": round(overlap, 1),
    })

# ─── Top by unique edge ───────────────────────────────────────
print("\n" + "="*78)
print("RANKED by unique edge:  WR_unique * sqrt(n_unique)   (impact score)")
print("="*78)
import math
ranked.sort(key=lambda r: r["WR_unique"] * math.sqrt(max(r["n_unique"], 1)), reverse=True)
print(f"  {'rank':<5} {'Dx':<4} {'n_uniq':>6} {'WR_uniq':>8} {'impact':>8} {'note':<30}")
for i, r in enumerate(ranked, 1):
    impact = r["WR_unique"] * math.sqrt(max(r["n_unique"], 1))
    print(f"  {i:<5} {r['Dx']:<4} {r['n_unique']:>6} {r['WR_unique']:>7.2f}% "
          f"{impact:>7.1f}  {r['name']}")

# ─── Save ─────────────────────────────────────────────────────
pd.DataFrame(ranked).to_csv(OUT, index=False)
print(f"\nSaved: {OUT}")
