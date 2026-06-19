"""Fill delay vs WR на ВСЕХ 4036 ob_vc 2h."""
import pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HORIZON_MS = 7*24*3600*1000

rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
h_1m = np.array([r[2] for r in rows], dtype=np.float64)
l_1m = np.array([r[3] for r in rows], dtype=np.float64)


def tbm_with_delay(entry, sl, born, direction):
    if direction == "long":
        if entry <= sl: return None
        risk = entry - sl; TP = entry + risk
    else:
        if entry >= sl: return None
        risk = sl - entry; TP = entry - risk
    i_fill = int(np.searchsorted(ts_1m, born, side="left"))
    i_end = min(len(ts_1m)-1, int(np.searchsorted(ts_1m, born + HORIZON_MS)))
    if direction == "long":
        below = l_1m[i_fill:i_end+1] <= entry
    else:
        below = h_1m[i_fill:i_end+1] >= entry
    if not below.any(): return (0.0, None, "no_fill")
    fi = int(np.argmax(below)); fill_idx = i_fill + fi
    fill_ts = int(ts_1m[fill_idx])
    delay_min = (fill_ts - born) / 60000
    ph = h_1m[fill_idx:i_end+1]; pl = l_1m[fill_idx:i_end+1]
    if direction == "long":
        tp_hit = np.argmax(ph >= TP) if (ph >= TP).any() else -1
        sl_hit = np.argmax(pl <= sl) if (pl <= sl).any() else -1
    else:
        tp_hit = np.argmax(pl <= TP) if (pl <= TP).any() else -1
        sl_hit = np.argmax(ph >= sl) if (ph >= sl).any() else -1
    if tp_hit != -1 and (sl_hit == -1 or tp_hit <= sl_hit): return (1.0, delay_min, "tp_hit")
    if sl_hit != -1: return (-1.0, delay_min, "sl_hit")
    return (0.0, delay_min, "timeout")


src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = src[src.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()

# Get t_id from bulkowski
bulk = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet")
t_id_map = bulk[["born_ms","direction","t_id"]].drop_duplicates().set_index(["born_ms","direction"]).t_id.to_dict()

records = []
for (d, co), sub in g2h.groupby(["direction","ob_cur_open_ms"]):
    born = int(sub.iloc[0].born_ms); nc = len(sub)
    if d == "long":
        cf = sub.sort_values("fvg_zone_hi", ascending=False).iloc[0]
        fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
        dp = 0.8 if nc >= 2 else 0.2
        entry = fvg_hi - dp * (fvg_hi - fvg_lo); sl = float(cf.drop_lo)
    else:
        cf = sub.sort_values("fvg_zone_lo", ascending=True).iloc[0]
        fvg_hi = float(cf.fvg_zone_hi); fvg_lo = float(cf.fvg_zone_lo)
        dp = 0.8 if nc >= 2 else 0.2
        entry = fvg_lo + dp * (fvg_hi - fvg_lo); sl = float(cf.drop_hi)
    out = tbm_with_delay(entry, sl, born, d)
    if out is None: continue
    R, delay, reason = out
    t_id = t_id_map.get((born, d), "Unknown")
    records.append({
        "born_ms": born, "direction": d, "t_id": t_id,
        "R": R, "delay_min": delay, "reason": reason,
    })

rdf = pd.DataFrame(records)
print(f"Total trades processed: {len(rdf)}")
filled = rdf[rdf.delay_min.notna()].copy()
print(f"Filled: {len(filled)}  no_fill: {len(rdf) - len(filled)}")
print(f"\nDelay distribution (filled, minutes):")
print(filled.delay_min.describe(percentiles=[0.1,0.25,0.5,0.75,0.9]).to_string())

# Buckets
def b(h):
    if h <= 0.5: return "0_immediate (<30min)"
    if h <= 2: return "1_under_2h"
    if h <= 6: return "2_2_6h"
    if h <= 12: return "3_6_12h"
    if h <= 24: return "4_12_24h"
    if h <= 48: return "5_1_2d"
    return "6_over_2d"

filled["delay_h"] = filled.delay_min / 60
filled["bucket"] = filled.delay_h.apply(b)


def show_buckets(df, title, ref_wr):
    print(f"\n{'='*100}\n{title}  (baseline WR={ref_wr:.1f}%)\n{'='*100}")
    print(f"{'bucket':<25} {'N':>5} {'WR':>7} {'Wins':>5} {'Losses':>7} {'ΣR':>8} {'avg':>7}  {'lift':>6}")
    for b_, g in df.groupby("bucket"):
        w = (g.R==1).sum(); l = (g.R==-1).sum()
        wr = w/(w+l)*100 if (w+l) else 0
        lift = wr - ref_wr
        flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else ("❌" if lift <= -3 else ""))
        print(f"{b_:<25} {len(g):>5} {wr:>6.1f}% {w:>5} {l:>7} {g.R.sum():>+7.1f}R {g.R.mean():>+6.3f}  {lift:>+5.1f}pp {flag}")


# Baseline WR
all_w = (filled.R == 1).sum(); all_l = (filled.R == -1).sum()
all_wr = all_w / (all_w + all_l) * 100
print(f"\nALL 4036 baseline (filled only): N_filled={len(filled)}  W={all_w} L={all_l}  WR={all_wr:.1f}%  Σ={all_w-all_l:+}R")

show_buckets(filled, "ALL 4036 — by delay bucket", all_wr)

# Direction-wise
long_f = filled[filled.direction == "long"]
short_f = filled[filled.direction == "short"]
lw = (long_f.R==1).sum(); ll = (long_f.R==-1).sum()
sw = (short_f.R==1).sum(); sl_ = (short_f.R==-1).sum()
long_wr = lw/(lw+ll)*100; short_wr = sw/(sw+sl_)*100
print(f"\nLONG  baseline: N={len(long_f)}  WR={long_wr:.1f}%  Σ={lw-ll:+}R")
print(f"SHORT baseline: N={len(short_f)} WR={short_wr:.1f}%  Σ={sw-sl_:+}R")

show_buckets(long_f, "LONG 4036 — by delay bucket", long_wr)
show_buckets(short_f, "SHORT 4036 — by delay bucket", short_wr)

# Save
rdf.to_parquet(pathlib.Path(__file__).parent.parent / "data/fill_delay_4036.parquet")
print(f"\nSaved: data/fill_delay_4036.parquet")
