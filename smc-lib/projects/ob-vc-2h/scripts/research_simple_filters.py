"""Тест простых фильтров A1-A7 на 20 positive типах.

A1 HTF cascade clash
A2 Dead-on-arrival (pierced ≤ 1×HTF)
A3 Asia session (UTC 00-06)
A4 FVG pre-mitigated до born
A5 HMA-78 distance large (>2×ATR)
A6 Zone width too wide (R% > 1.5%)
A7 Cur body too small (<0.5%)

Для каждого фильтра: WR/Σ R до и после, # dropped trades.
"""
import sys, pathlib, time
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import load_1m, aggregate_all_tfs, to_candles

t0 = time.time()
df = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = df[df.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction", "ob_cur_open_ms"])["ltf"].transform(
    lambda x: "15m" in set(x))
mask = ((g2h.has_15m & (g2h.ltf == "15m")) | (~g2h.has_15m & (g2h.ltf == "20m")))
g2h = g2h[mask].copy()

cans = to_candles(aggregate_all_tfs(load_1m())["2h"])
bar_idx = {c.open_time: i for i, c in enumerate(cans)}

# Load HTF candles for cascade check
rows = load_1m()
bars_all = aggregate_all_tfs(rows)
cans_12h = to_candles(bars_all["12h"])
cans_6h = to_candles(bars_all["6h"])
cans_4h = to_candles(bars_all["4h"])
cans_1d = to_candles(bars_all["1d"])

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
    R = abs(entry - sl)
    TP1 = entry + R if direction == "long" else entry - R
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
    """Get last closed HTF bar before ts_ms."""
    for i in range(len(htf_cans)-1, -1, -1):
        if htf_cans[i].open_time < ts_ms:
            return htf_cans[i]
    return None


# Process all setups
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
        if dd == d and nc == n_class and sw == swept:
            fi = i; break
    if fi is None: continue

    if extreme == "prev":
        r = wick_ratio(d, prev, cur)
        suffix = "a" if r >= 2.0 else "b"
        t_id = ORIG_PREV[fi] + suffix
    else:
        t_id = ORIG_CUR[fi]
    if t_id in NEGATIVE: continue   # drop list

    chosen = sub.iloc[0]
    born = int(chosen.born_ms)

    # OLD rule entry/SL
    if d == "long":
        chosen_fvg = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = chosen_fvg.fvg_zone_hi - deep * (chosen_fvg.fvg_zone_hi - chosen_fvg.fvg_zone_lo)
        sl = chosen_fvg.drop_lo
    else:
        chosen_fvg = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        deep = 0.8 if n_comp >= 2 else 0.2
        entry = chosen_fvg.fvg_zone_lo + deep * (chosen_fvg.fvg_zone_hi - chosen_fvg.fvg_zone_lo)
        sl = chosen_fvg.drop_hi
    R = abs(entry - sl)
    R_pct = R / entry * 100

    out = tbm(entry, sl, d, born)
    if out is None: continue
    rv = None
    if out.get("touched", False):
        rv = 1 if out["outcome"] == "win" else (-1 if out["outcome"] == "loss" else 0)

    # Features for filters
    # A1: HTF cascade
    bar_12h = get_htf_bar_at(cans_12h, born)
    bar_6h  = get_htf_bar_at(cans_6h, born)
    bar_4h  = get_htf_bar_at(cans_4h, born)
    cascade_against = False
    if bar_12h and bar_6h and bar_4h:
        bs = [(b.close - b.open) / b.open for b in (bar_12h, bar_6h, bar_4h)]
        if d == "long":
            cascade_against = all(b < -0.003 for b in bs)   # all 3 BEAR ≥0.3%
        else:
            cascade_against = all(b > 0.003 for b in bs)

    # A2: dead-on-arrival (pierced ≤ 2h after born)
    invalid_ms = int(chosen.valid_until_ms)
    dead = (invalid_ms - born) < 2*3600*1000

    # A3: Asia session (born in 00-06 UTC)
    born_dt = datetime.fromtimestamp(born/1000, timezone.utc)
    asia = (born_dt.hour < 6)

    # A4: FVG pre-mitigated (before born, 1m price touched zone_lo/hi)
    # Check if 1m low (LONG) reached fvg_zone_lo (= zone bottom) before born
    if d == "long":
        zone_target = chosen_fvg.fvg_zone_lo
        i_start = int(np.searchsorted(ts_1m, chosen_fvg.fvg_c3_close_ms))
        i_end_pre = int(np.searchsorted(ts_1m, born))
        if i_end_pre > i_start:
            pre_mitig = (l_1m[i_start:i_end_pre] <= zone_target).any()
        else:
            pre_mitig = False
    else:
        zone_target = chosen_fvg.fvg_zone_hi
        i_start = int(np.searchsorted(ts_1m, chosen_fvg.fvg_c3_close_ms))
        i_end_pre = int(np.searchsorted(ts_1m, born))
        if i_end_pre > i_start:
            pre_mitig = (h_1m[i_start:i_end_pre] >= zone_target).any()
        else:
            pre_mitig = False

    # A6: zone width too wide
    too_wide = R_pct > 1.5

    # A7: cur body small
    cur_body_pct = abs(cur.close - cur.open) / cur.open * 100
    small_body = cur_body_pct < 0.5

    records.append({
        "t_id": t_id, "direction": d,
        "touched": out.get("touched", False), "R": rv,
        "R_pct": R_pct,
        "cascade_against": cascade_against,
        "dead_on_arrival": dead,
        "asia": asia,
        "pre_mitigated": pre_mitig,
        "wide_zone": too_wide,
        "small_body": small_body,
    })

rdf = pd.DataFrame(records)
print(f"Processed (20 positive types): {len(rdf):,}\n")

# Baseline
base_w = (rdf.R == 1).sum(); base_l = (rdf.R == -1).sum()
base_nt = rdf.touched.sum()
base_wr = base_w/base_nt*100 if base_nt else 0
print(f"Baseline: N={len(rdf):,}  touch={base_nt:,}  WR={base_wr:.1f}%  Σ={base_w-base_l:+}R")

# Test each filter
filters = [
    ("A1 HTF cascade clash", "cascade_against"),
    ("A2 Dead-on-arrival",   "dead_on_arrival"),
    ("A3 Asia session",      "asia"),
    ("A4 Pre-mitigated FVG", "pre_mitigated"),
    ("A6 Wide zone R%>1.5",  "wide_zone"),
    ("A7 Small cur body",    "small_body"),
]
print(f"\n{'Filter':<26} {'Drop':>6} {'kept':>6} {'WR_drop':>9} {'WR_kept':>9} {'ΣR_drop':>9} {'ΣR_kept':>9} {'Δ Σ':>6}")
print("-"*90)
for name, col in filters:
    dropped = rdf[rdf[col]]
    kept = rdf[~rdf[col]]
    nd = len(dropped); nk = len(kept)
    dw = (dropped.R == 1).sum(); dl = (dropped.R == -1).sum()
    kw = (kept.R == 1).sum(); kl = (kept.R == -1).sum()
    dnt = dropped.touched.sum(); knt = kept.touched.sum()
    wr_d = dw/dnt*100 if dnt else 0
    wr_k = kw/knt*100 if knt else 0
    sig_d = dw - dl; sig_k = kw - kl
    delta = sig_k - (base_w - base_l)
    print(f"{name:<26} {nd:>6} {nk:>6} {wr_d:>8.1f}% {wr_k:>8.1f}% {sig_d:>+8}R {sig_k:>+8}R {delta:>+5}R")

# Combined filter test: all A1+A2+A3+A4+A6+A7
print(f"\n{'='*90}")
print(f"COMBINED: drop if ANY of A1, A2, A3, A4, A6, A7 is true")
print(f"{'='*90}")
combined_drop = (rdf.cascade_against | rdf.dead_on_arrival | rdf.asia |
                 rdf.pre_mitigated | rdf.wide_zone | rdf.small_body)
kept_all = rdf[~combined_drop]
nt = kept_all.touched.sum()
w = (kept_all.R == 1).sum(); l = (kept_all.R == -1).sum()
wr = w/nt*100 if nt else 0
print(f"After ALL filters:  N={len(kept_all):,}  touch={nt:,}  WR={wr:.1f}%  Σ={w-l:+}R  ({len(rdf)-len(kept_all)} dropped)")

# By type
print(f"\nPer-type Σ R after ALL filters:")
for t in sorted(rdf.t_id.unique()):
    g = kept_all[kept_all.t_id == t]
    if len(g) == 0:
        print(f"  {t:<6} drop all"); continue
    nt = g.touched.sum(); w = (g.R == 1).sum(); l = (g.R == -1).sum()
    wr = w/nt*100 if nt else 0
    print(f"  {t:<6}  N={len(g):>4}  WR={wr:>5.1f}%  Σ={w-l:>+4}R")

print(f"\nElapsed: {time.time()-t0:.1f}s")
