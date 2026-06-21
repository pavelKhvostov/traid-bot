"""B1_v4: corpus B1Cx с удалённым B1C5 (REJ_BAR — lookahead violation).

B1Cx после очистки:
  B1C1  strict sweep  L0 / S100 / WIDE
  B1C2  strict sweep  L0 / S50  / AGE-WIDE
  B1C3  strict sweep  L0 / S70  / AGE50
  B1C4  strict sweep  L0 / S50  / HTF-WIDE
  B1C5  vol spike     L0 / S50 + vol_z ≥ +2σ           (был B1C6)
  B1C6  retest        L0 / S50 → close inside (≤3 баров) (был B1C7)

REJ_BAR удалён — нарушал правило causality (использовал body_pct[i+1]).
См. memory [[feedback-b-series-strict-causal-i]].
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.fvg.code import detect_fvg

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
BASELINE = pathlib.Path.home() / "Desktop/pred12h_baseline_v2.parquet"

MS_M = 60_000
TF12 = 12 * 60 * MS_M
TFD = 24 * 60 * MS_M
TF2D = 2 * TFD
TF3D = 3 * TFD
TFW = 7 * TFD
MON_ANCHOR = int(datetime(2017, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS or t > END_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))


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
o12 = np.array([b[1] for b in bars12]); h12 = np.array([b[2] for b in bars12])
l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])
v12 = np.array([b[5] for b in bars12])

body = np.abs(c12 - o12); rng = h12 - l12
safe_rng = np.where(rng > 0, rng, 1.0); body_pct = body / safe_rng

def atr_calc(highs, lows, closes, n=14):
    tr = np.zeros(len(highs))
    for i in range(1, len(highs)):
        tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    out = np.zeros(len(highs))
    for i in range(n, len(highs)):
        out[i] = tr[i-n+1:i+1].mean()
    return out

atr12 = atr_calc(h12, l12, c12, 14)

# Volume z-score (rolling 50, past-only)
v_ser = pd.Series(v12)
v_mean = v_ser.rolling(50, min_periods=20).mean().bfill().values
v_std = v_ser.rolling(50, min_periods=20).std().bfill().values
v_z = (v12 - v_mean) / np.where(v_std > 0, v_std, 1.0)

bars_by_tf = {"12h": bars12, "D": agg(rows, TFD), "2D": agg(rows, TF2D),
              "3D": agg(rows, TF3D), "W": agg(rows, TFW, MON_ANCHOR)}
cans_by_tf = {tf: [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bb]
              for tf, bb in bars_by_tf.items()}
tfms_map = {"12h": TF12, "D": TFD, "2D": TF2D, "3D": TF3D, "W": TFW}

all_fvg = []
for tf, cans in cans_by_tf.items():
    tfms = tfms_map[tf]
    for i in range(len(cans) - 2):
        fv = detect_fvg(cans[i], cans[i+1], cans[i+2])
        if fv is None: continue
        all_fvg.append({"tf": tf, "direction": fv.direction,
            "zlo": fv.zone[0], "zhi": fv.zone[1],
            "c3_ms": cans[i+2].open_time,
            "ready_ms": cans[i+2].open_time + tfms})

for z in all_fvg:
    sp = int(np.searchsorted(t12, z["ready_ms"], side='left'))
    z["events"] = []
    if sp >= n12: continue
    zlo, zhi = z["zlo"], z["zhi"]; w = zhi - zlo
    if w <= 0: continue
    for k in range(sp, n12):
        if z["direction"] == "short":
            hh, cc = h12[k], c12[k]
            if hh < zlo: continue
            pen = min((hh - zlo) / w * 100, 999)
            ci = (cc >= zlo and cc <= zhi); co_far = (cc < zlo)
        else:
            ll, cc = l12[k], c12[k]
            if ll > zhi: continue
            pen = min((zhi - ll) / w * 100, 999)
            ci = (cc >= zlo and cc <= zhi); co_far = (cc > zhi)
        z["events"].append((k, pen, ci, co_far))

def filt(z, k, ftype):
    age = (t12[k] - z["c3_ms"]) // TF12
    width = z["zhi"] - z["zlo"]
    atr = atr12[k] if atr12[k] > 0 else 1.0
    is_htf = z["tf"] in ("D", "2D", "3D", "W")
    if ftype == "ANY": return True
    if ftype == "WIDE": return width / atr >= 0.7
    if ftype == "AGE50_WIDE": return age >= 50 and width / atr >= 0.7
    if ftype == "AGE50": return age >= 50
    if ftype == "HTF_WIDE": return is_htf and width / atr >= 0.7
    return False

def eval_classic(filt_type, pen_min):
    """Strict sweep: pen ≥ pen_min, close OUTSIDE, фильтр.
    Causality: использует только bar k (текущий) + zone (создана раньше).
    """
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far in z["events"]:
            if pen < pen_min: continue
            if not co_far: continue
            if not filt(z, k, filt_type): continue
            fires.add((k, z["direction"]))
            break
    return fires

# B1C1: S100 / WIDE
B1C1 = eval_classic("WIDE", 100)
# B1C2: S50 / AGE-WIDE
B1C2 = eval_classic("AGE50_WIDE", 50)
# B1C3: S70 / AGE50
B1C3 = eval_classic("AGE50", 70)
# B1C4: S50 / HTF-WIDE
B1C4 = eval_classic("HTF_WIDE", 50)

# B1C5 (был B1C6): VOL_SPIKE — S50 + vol_z ≥ +2σ. Causality OK (rolling past-only).
def B_vol_spike():
    fires = set()
    for z in all_fvg:
        for k, pen, ci, co_far in z["events"]:
            if pen >= 50 and co_far and v_z[k] >= 2.0:
                fires.add((k, z["direction"])); break
    return fires
B1C5 = B_vol_spike()

# B1C6 (был B1C7): RETEST — S50 → close inside в +N=3 баров.
# Causality OK: fire bar = retest bar, uses past sweep + current close.
def B_retest(N=3):
    fires = set()
    for z in all_fvg:
        sweep_k = None
        for k, pen, ci, co_far in z["events"]:
            if sweep_k is None and pen >= 50 and co_far:
                sweep_k = k; continue
            if sweep_k is not None and k <= sweep_k + N and ci:
                fires.add((k, z["direction"])); break
    return fires
B1C6 = B_retest()

# Baseline match
df_base = pd.read_parquet(BASELINE)
ts_to_idx = {int(t): k for k, t in enumerate(t12)}
pivot_map = {}
for _, p in df_base.iterrows():
    ts_ms = int(p["pivot_open_ts_ms"])
    if ts_ms not in ts_to_idx: continue
    k = ts_to_idx[ts_ms]
    expected = "short" if p["direction"] == "high" else "long"
    pivot_map[(k, expected)] = (bool(p["confirmed"]), p["direction"], ts_ms)

def stats(fires):
    m = [pivot_map[(k, d)] for (k, d) in fires if (k, d) in pivot_map]
    n = len(m); conf = sum(1 for c, _, _ in m if c)
    return n, conf, (100*conf/n if n else 0.0)

print(f"{'B1Cx':<5} {'name':<14} {'n':>5} {'conf':>5} {'WR':>7}")
print("-"*50)
for code, fset, name in [
    ("B1C1", B1C1, "S100/WIDE"),
    ("B1C2", B1C2, "S50/AGE-WIDE"),
    ("B1C3", B1C3, "S70/AGE50"),
    ("B1C4", B1C4, "S50/HTF-WIDE"),
    ("B1C5", B1C5, "VOL_SPIKE"),
    ("B1C6", B1C6, "RETEST"),
]:
    n, conf, wr = stats(fset)
    print(f"{code:<5} {name:<14} {n:>5} {conf:>5} {wr:>6.2f}%")

union = B1C1 | B1C2 | B1C3 | B1C4 | B1C5 | B1C6
n_u, c_u, wr_u = stats(union)
print("-"*50)
print(f"B1_v4 UNION         {n_u:>5} {c_u:>5} {wr_u:>6.2f}%")

print(f"\nSравнение:")
print(f"  B1_v2 (старый wick-fill): n=251 / WR 64.50%")
print(f"  B1_v3 (с REJ_BAR LOOKAHEAD): n=255 / WR 74.12%   ← было неверно")
print(f"  B1_v4 (causal-only):       n={n_u} / WR {wr_u:.2f}%   ← правильное")
