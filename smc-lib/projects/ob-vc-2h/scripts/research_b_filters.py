"""Test B-фильтров (positive predictors) на 20 positive типах ПОСЛЕ A1+A2.

B1: HTF cascade ALIGNED (3 HTF same direction as trade)
B2: n_FVG ≥ 3
B3: Cur volume spike (cur vol > Q75 of last 20 bars)
B4: EU/US session born (UTC 08-22)
B5: Deep sweep (prev wick > 1% of price)
B6: Strong engulf (cur.close beyond prev.high/low)
B7: Quick FVG mitigation (FVG touched within 30min of born)
"""
import sys, pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles

t0 = time.time()
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction", "ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf == "15m")) | (~g2h.has_15m & (g2h.ltf == "20m")))
g2h = g2h[mask].copy()

# Load with volumes (2h)
rows = load_1m()
def agg_with_vol(rs, tf_ms):
    out = []; cb=None; o=h=l=c=v=0.0
    for t,oo,hh,ll,cc in rs:
        # 1m rows don't have volume — we'll skip volume for now
        b = t - (t % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v=oo,hh,ll,cc,1
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v+=1   # use bar count as proxy
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

# Use existing aggregation; for volume use cur body size as proxy (cleaner)
cans_dict = aggregate_all_tfs(rows)
cans = to_candles(cans_dict["2h"])
cans_12h = to_candles(cans_dict["12h"])
cans_6h = to_candles(cans_dict["6h"])
cans_4h = to_candles(cans_dict["4h"])
bar_idx = {c.open_time: i for i, c in enumerate(cans)}

_rows = load_1m()
ts_1m = np.array([r[0] for r in _rows], dtype=np.int64)
h_1m = np.array([r[2] for r in _rows], dtype=np.float64)
l_1m = np.array([r[3] for r in _rows], dtype=np.float64)
HORIZON_MS = 14*24*3600*1000

NEGATIVE = {"T3b","T6","T13a","T13b","T16"}
ORIG_PREV = {0:"T1",1:"T3",2:"T5",3:"T7",4:"T9",5:"T11",6:"T13",7:"T15"}
ORIG_CUR  = {0:"T2",1:"T4",2:"T6",3:"T8",4:"T10",5:"T12",6:"T14",7:"T16"}
prev_types_idx = [
    ("long",True,"≥2"),("long",True,"1"),("long",False,"≥2"),("long",False,"1"),
    ("short",True,"≥2"),("short",True,"1"),("short",False,"≥2"),("short",False,"1"),
]


def wick_ratio(direction, prev, cur, EPS=0.01):
    if direction == "long":
        pw = min(prev.open, prev.close) - prev.low
        cw = min(cur.open, cur.close) - cur.low
    else:
        pw = prev.high - max(prev.open, prev.close)
        cw = cur.high - max(cur.open, cur.close)
    return float("inf") if cw < EPS else pw / cw


def tbm(entry, sl, direction, born_ms):
    if direction == "long" and entry <= sl: return None
    if direction == "short" and entry >= sl: return None
    R = abs(entry - sl); TP1 = entry + R if direction=="long" else entry - R
    i_start = int(np.searchsorted(ts_1m, born_ms))
    if i_start >= len(ts_1m): return None
    i_end = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born_ms + HORIZON_MS)))
    if direction == "long":
        sl_arr = l_1m[i_start:i_end+1]
        tr = int(np.argmax(sl_arr <= entry)) if (sl_arr <= entry).any() else -1
    else:
        sh_arr = h_1m[i_start:i_end+1]
        tr = int(np.argmax(sh_arr >= entry)) if (sh_arr >= entry).any() else -1
    if tr == -1: return {"touched": False}
    ti = i_start + tr
    ph = h_1m[ti:i_end+1]; pl = l_1m[ti:i_end+1]
    if direction == "long":
        tp1r = int(np.argmax(ph >= TP1)) if (ph >= TP1).any() else -1
        slr = int(np.argmax(pl <= sl)) if (pl <= sl).any() else -1
    else:
        tp1r = int(np.argmax(pl <= TP1)) if (pl <= TP1).any() else -1
        slr = int(np.argmax(ph >= sl)) if (ph >= sl).any() else -1
    if tp1r != -1 and (slr == -1 or tp1r <= slr): return {"touched": True, "outcome": "win"}
    elif slr != -1: return {"touched": True, "outcome": "loss"}
    return {"touched": True, "outcome": "timeout"}


def get_htf_bar_at(htf_cans, ts_ms):
    for i in range(len(htf_cans)-1, -1, -1):
        if htf_cans[i].open_time < ts_ms:
            return htf_cans[i]
    return None


records = []
for k, ((d, co), sub) in enumerate(g2h.groupby(["direction","ob_cur_open_ms"])):
    co = int(co); idx = bar_idx.get(co)
    if idx is None or idx < 3: continue
    n2c=cans[idx-3]; n1c=cans[idx-2]; prev=cans[idx-1]; cur=cans[idx]

    if d == "long":
        swept = min(prev.low,cur.low) < min(n1c.low,n2c.low)
        extreme = "prev" if prev.low < cur.low else "cur"
    else:
        swept = max(prev.high,cur.high) > max(n1c.high,n2c.high)
        extreme = "prev" if prev.high > cur.high else "cur"
    n_comp = len(sub); n_class = "≥2" if n_comp >= 2 else "1"
    fi = None
    for i,(dd,sw,nc) in enumerate(prev_types_idx):
        if dd == d and nc == n_class and sw == swept: fi = i; break
    if fi is None: continue
    if extreme == "prev":
        r = wick_ratio(d, prev, cur)
        suffix = "a" if r >= 2.0 else "b"
        t_id = ORIG_PREV[fi] + suffix
    else:
        t_id = ORIG_CUR[fi]
    if t_id in NEGATIVE: continue

    chosen = sub.iloc[0]; born = int(chosen.born_ms)
    invalid_ms = int(chosen.valid_until_ms)

    if d == "long":
        chosen_fvg = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = chosen_fvg.fvg_zone_hi - deep*(chosen_fvg.fvg_zone_hi - chosen_fvg.fvg_zone_lo)
        sl = chosen_fvg.drop_lo
    else:
        chosen_fvg = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = chosen_fvg.fvg_zone_lo + deep*(chosen_fvg.fvg_zone_hi - chosen_fvg.fvg_zone_lo)
        sl = chosen_fvg.drop_hi

    # APPLY A1+A2 (skip if either fires)
    bar_12h = get_htf_bar_at(cans_12h, born)
    bar_6h  = get_htf_bar_at(cans_6h, born)
    bar_4h  = get_htf_bar_at(cans_4h, born)
    cascade_against = False
    cascade_aligned = False
    if bar_12h and bar_6h and bar_4h:
        bs = [(b.close - b.open) / b.open for b in (bar_12h, bar_6h, bar_4h)]
        if d == "long":
            cascade_against = all(b < -0.003 for b in bs)
            cascade_aligned = all(b > 0.003 for b in bs)
        else:
            cascade_against = all(b > 0.003 for b in bs)
            cascade_aligned = all(b < -0.003 for b in bs)
    if cascade_against: continue  # A1
    if (invalid_ms - born) < 2*3600*1000: continue  # A2

    out = tbm(entry, sl, d, born)
    if out is None: continue
    rv = None
    if out.get("touched", False):
        rv = 1 if out["outcome"] == "win" else (-1 if out["outcome"] == "loss" else 0)

    # B-features
    # B2: n_FVG ≥ 3
    n_fvg_high = n_comp >= 3
    # B4: EU/US session born (UTC 08-22)
    bdt = datetime.fromtimestamp(born/1000, timezone.utc)
    eu_us = 8 <= bdt.hour < 22
    # B5: deep sweep (prev wick > 1% of price)
    if d == "long":
        pw_abs = min(prev.open,prev.close) - prev.low
        deep_sweep = (pw_abs / cur.low) > 0.01
    else:
        pw_abs = prev.high - max(prev.open,prev.close)
        deep_sweep = (pw_abs / cur.high) > 0.01
    # B6: strong engulf
    if d == "long":
        strong_engulf = cur.close > prev.high
    else:
        strong_engulf = cur.close < prev.low
    # B7: quick FVG mitigation (cur close > FVG top within cur bar already - already implied)
    # Re-define: FVG touched within 30 min after born
    i_start = int(np.searchsorted(ts_1m, born))
    i_end_30 = int(np.searchsorted(ts_1m, born + 30*60*1000))
    if d == "long":
        quick_mit = (l_1m[i_start:i_end_30] <= chosen_fvg.fvg_zone_hi).any() if i_end_30 > i_start else False
    else:
        quick_mit = (h_1m[i_start:i_end_30] >= chosen_fvg.fvg_zone_lo).any() if i_end_30 > i_start else False
    # B3: cur volume spike — use cur body size > prev 20 median × 1.5 (proxy)
    bodies = [abs(cans[i].close - cans[i].open) for i in range(max(0,idx-20), idx)]
    if bodies:
        med = np.median(bodies)
        cur_body = abs(cur.close - cur.open)
        body_spike = cur_body > med * 1.5
    else:
        body_spike = False

    records.append({
        "t_id": t_id, "direction": d,
        "touched": out.get("touched", False), "R": rv,
        "B1_aligned": cascade_aligned,
        "B2_nfvg_high": n_fvg_high,
        "B3_body_spike": body_spike,
        "B4_eu_us": eu_us,
        "B5_deep_sweep": deep_sweep,
        "B6_strong_engulf": strong_engulf,
        "B7_quick_mit": quick_mit,
    })

rdf = pd.DataFrame(records)
print(f"After A1+A2 baseline: {len(rdf):,}")
base_w = (rdf.R == 1).sum(); base_l = (rdf.R == -1).sum()
base_nt = rdf.touched.sum()
print(f"Baseline (post A1+A2): N={len(rdf):,}  touch={base_nt:,}  WR={base_w/base_nt*100:.1f}%  Σ={base_w-base_l:+}R\n")

filters = [
    ("B1 HTF cascade aligned", "B1_aligned"),
    ("B2 n_FVG ≥ 3",            "B2_nfvg_high"),
    ("B3 Body spike >1.5×med",  "B3_body_spike"),
    ("B4 EU/US session born",   "B4_eu_us"),
    ("B5 Deep sweep >1% price", "B5_deep_sweep"),
    ("B6 Strong engulf",        "B6_strong_engulf"),
    ("B7 Quick mitigation 30m", "B7_quick_mit"),
]
print(f"\n{'Filter':<28} {'In':>5} {'Out':>5} {'WR_in':>7} {'WR_out':>8} {'ΣR_in':>7} {'ΣR_out':>8} {'EV in/trade':>11}")
print("-"*90)
for name, col in filters:
    inn = rdf[rdf[col]]
    out = rdf[~rdf[col]]
    nin = len(inn); nout = len(out)
    wi = (inn.R == 1).sum(); li = (inn.R == -1).sum()
    wo = (out.R == 1).sum(); lo = (out.R == -1).sum()
    nti = inn.touched.sum(); nto = out.touched.sum()
    wr_i = wi/nti*100 if nti else 0
    wr_o = wo/nto*100 if nto else 0
    ev_i = (2*wr_i/100) - 1
    print(f"{name:<28} {nin:>5} {nout:>5} {wr_i:>6.1f}% {wr_o:>7.1f}% {wi-li:>+6}R {wo-lo:>+7}R {ev_i:>+10.3f}R")

print(f"\nElapsed: {time.time()-t0:.1f}s")
