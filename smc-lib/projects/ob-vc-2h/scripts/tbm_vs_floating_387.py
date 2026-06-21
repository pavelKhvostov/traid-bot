"""TBM (fixed TP1R) on same 387 basket for comparison with Floating TP."""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HORIZON_MS = 7*24*3600*1000  # MATCH Floating 7d horizon

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


def tbm(entry, sl, born, direction):
    """Fixed TP1R + SL with 7d horizon. Returns (R, reason)."""
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
    if not below.any(): return (0.0, "no_fill")
    fi = int(np.argmax(below)); fill_idx = i_fill + fi
    ph = h_1m[fill_idx:i_end+1]; pl = l_1m[fill_idx:i_end+1]
    if direction == "long":
        tp_hit = np.argmax(ph >= TP) if (ph >= TP).any() else -1
        sl_hit = np.argmax(pl <= sl) if (pl <= sl).any() else -1
    else:
        tp_hit = np.argmax(pl <= TP) if (pl <= TP).any() else -1
        sl_hit = np.argmax(ph >= sl) if (ph >= sl).any() else -1
    if tp_hit != -1 and (sl_hit == -1 or tp_hit <= sl_hit): return (1.0, "tp_hit")
    if sl_hit != -1: return (-1.0, "sl_hit")
    # Timeout — mark to market
    if direction == "long":
        m2m = (h_1m[i_end] - entry) / risk  # use close approx (last bar high)
    else:
        m2m = (entry - l_1m[i_end]) / risk
    return (0.0, "timeout")


# Load basket data (387)
floating_res = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/floating_tp_387.parquet")
print(f"Floating results: {len(floating_res)}")

# Get entry/sl per setup
src = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/ob_vc_phase1_5.parquet")
g2h = src[src.htf == "2h"].copy()
g2h["has_15m"] = g2h.groupby(["direction","ob_cur_open_ms"])["ltf"].transform(lambda x: "15m" in set(x))
mask_lt = ((g2h.has_15m & (g2h.ltf=="15m")) | (~g2h.has_15m & (g2h.ltf=="20m")))
g2h = g2h[mask_lt].copy()
setups = {}
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
    setups[(d, born)] = (entry, sl)

# Apply TBM
results = []
for _, r in floating_res.iterrows():
    born = int(r.born_ms); d = r.direction
    e, sl = setups[(d, born)]
    out = tbm(e, sl, born, d)
    if out is None: continue
    R, reason = out
    results.append({
        "born_ms": born, "direction": d, "t_id": r.t_id,
        "R_tbm": R, "reason_tbm": reason,
        "R_float": r.R, "reason_float": r.exit_reason,
    })

res = pd.DataFrame(results)
print(f"TBM trades: {len(res)}")

# Stats
tbm_sumR = res.R_tbm.sum()
float_sumR = res.R_float.sum()
print(f"\n{'='*100}")
print(f"COMPARISON: TBM (fixed TP1R, 7d horizon) vs FLOATING TP")
print(f"{'='*100}")
print(f"{'metric':<30} {'TBM':>12} {'Floating':>12}")
print(f"{'Total R':<30} {tbm_sumR:>+11.1f}R {float_sumR:>+11.1f}R")
print(f"{'Σ R / year':<30} {tbm_sumR/6.5:>+11.1f}R {float_sumR/6.5:>+11.1f}R")
print(f"{'Avg R/trade':<30} {res.R_tbm.mean():>+11.3f}R {res.R_float.mean():>+11.3f}R")
print(f"{'Median R':<30} {res.R_tbm.median():>+11.3f}R {res.R_float.median():>+11.3f}R")
print(f"{'WR (R>0)':<30} {(res.R_tbm>0).mean()*100:>10.1f}% {(res.R_float>0).mean()*100:>10.1f}%")
print(f"{'wins':<30} {(res.R_tbm>0).sum():>11} {(res.R_float>0).sum():>11}")
print(f"{'losses':<30} {(res.R_tbm<0).sum():>11} {(res.R_float<0).sum():>11}")
print(f"{'no_fill / timeouts':<30} {(res.R_tbm==0).sum():>11} {(res.R_float==0).sum():>11}")

# TBM exit breakdown
print(f"\nTBM exit reasons:")
for r, c in res.reason_tbm.value_counts().items():
    sub_r = res[res.reason_tbm == r]
    print(f"  {r:<14} N={c:>4}  avg R={sub_r.R_tbm.mean():+.3f}  ΣR={sub_r.R_tbm.sum():+.1f}")

# Per year
res["year"] = pd.to_datetime(res.born_ms, unit="ms", utc=True).dt.year
print(f"\n{'='*100}\nBY YEAR (TBM vs Floating)\n{'='*100}")
print(f"{'Year':<6} {'N':>4}  {'TBM_R':>9} {'TBM_WR':>8}  {'Float_R':>9} {'Flt_WR':>7}  diff")
for y, g in res.groupby("year"):
    tbm_r = g.R_tbm.sum(); tbm_w = (g.R_tbm > 0).mean()*100
    flt_r = g.R_float.sum(); flt_w = (g.R_float > 0).mean()*100
    print(f"{y:<6} {len(g):>4}  {tbm_r:>+8.1f}R {tbm_w:>7.1f}%  {flt_r:>+8.1f}R {flt_w:>6.1f}%  {tbm_r-flt_r:>+5.1f}R")

# Per direction × year
print(f"\n{'='*100}\nLONG by year\n{'='*100}")
long_res = res[res.direction == "long"]
print(f"{'Year':<6} {'N':>4}  {'TBM_R':>9} {'TBM_WR':>8}  {'Float_R':>9}")
for y, g in long_res.groupby("year"):
    tbm_r = g.R_tbm.sum(); tbm_w = (g.R_tbm > 0).mean()*100
    flt_r = g.R_float.sum()
    print(f"{y:<6} {len(g):>4}  {tbm_r:>+8.1f}R {tbm_w:>7.1f}%  {flt_r:>+8.1f}R")

print(f"\nSHORT by year")
short_res = res[res.direction == "short"]
print(f"{'Year':<6} {'N':>4}  {'TBM_R':>9} {'TBM_WR':>8}  {'Float_R':>9}")
for y, g in short_res.groupby("year"):
    tbm_r = g.R_tbm.sum(); tbm_w = (g.R_tbm > 0).mean()*100
    flt_r = g.R_float.sum()
    print(f"{y:<6} {len(g):>4}  {tbm_r:>+8.1f}R {tbm_w:>7.1f}%  {flt_r:>+8.1f}R")

# Per type
print(f"\n{'='*100}\nBY TYPE (TBM vs Floating)\n{'='*100}")
print(f"{'Type':<5} {'dir':<6} {'N':>4}  {'TBM_R':>9} {'TBM_WR':>8}  {'Float_R':>9} {'Flt_WR':>7}")
for (t, d), g in res.groupby(["t_id","direction"]):
    tbm_r = g.R_tbm.sum(); tbm_w = (g.R_tbm > 0).mean()*100
    flt_r = g.R_float.sum(); flt_w = (g.R_float > 0).mean()*100
    print(f"{t:<5} {d:<6} {len(g):>4}  {tbm_r:>+8.1f}R {tbm_w:>7.1f}%  {flt_r:>+8.1f}R {flt_w:>6.1f}%")

# When TBM > Floating (trades where fixed TP1R hit but Floating exited differently)
print(f"\n{'='*100}\nWHERE THEY DIFFER\n{'='*100}")
tbm_win_float_loss = res[(res.R_tbm == 1.0) & (res.R_float < 0)]
print(f"TBM_win but Floating_loss: {len(tbm_win_float_loss)}  ΣR_tbm={tbm_win_float_loss.R_tbm.sum():+}R ΣR_flt={tbm_win_float_loss.R_float.sum():+.1f}R")
tbm_loss_float_win = res[(res.R_tbm == -1.0) & (res.R_float > 1.0)]
print(f"TBM_loss but Floating big_win: {len(tbm_loss_float_win)}  ΣR_tbm={tbm_loss_float_win.R_tbm.sum():+}R ΣR_flt={tbm_loss_float_win.R_float.sum():+.1f}R")
tbm_win_float_big = res[(res.R_tbm == 1.0) & (res.R_float > 1.5)]
print(f"TBM_win AND Floating big_win (>1.5R): {len(tbm_win_float_big)}  ΣR_flt={tbm_win_float_big.R_float.sum():+.1f}R")
