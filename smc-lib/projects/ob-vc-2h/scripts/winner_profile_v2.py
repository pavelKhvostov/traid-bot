"""Deeper winner profile: add volume, momentum, HMA, HTF context features."""
import sys, pathlib, csv
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import aggregate_all_tfs, to_candles

CSV_1M = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
TF_2H = 2 * 3600 * 1000

rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
v_1m = np.array([r[5] for r in rows], dtype=np.float64)

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
cans_4h = to_candles(cans_d["4h"])
cans_12h = to_candles(cans_d["12h"])
cans_1d = to_candles(cans_d["1d"])
bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}


# 2h volume per bar
def vol_2h(open_time_ms):
    i_lo = int(np.searchsorted(ts_1m, open_time_ms, side="left"))
    i_hi = int(np.searchsorted(ts_1m, open_time_ms + TF_2H, side="left"))
    return float(v_1m[i_lo:i_hi].sum())


# Pre-compute 2h volumes
ts_2h_arr = np.array([c.open_time for c in cans_2h])
vol_2h_arr = np.array([vol_2h(c.open_time) for c in cans_2h])

# 1D HMA-78 — simple proxy: WMA-78 / HMA approximation, use SMA-78 as proxy
c_1d = np.array([c.close for c in cans_1d])
ts_1d_arr = np.array([c.open_time for c in cans_1d])


def hma_proxy(idx, period=78):
    if idx < period: return None
    # Hull MA proxy: WMA(2*WMA(close, period/2) - WMA(close, period), sqrt(period))
    # Simplified to WMA-period for speed
    weights = np.arange(1, period + 1)
    vals = c_1d[idx-period+1:idx+1]
    return float(np.average(vals, weights=weights))


# Pre-existing data
PD = pathlib.Path(__file__).parent.parent / "data"
parent = pd.read_parquet(PD / "forming_parent_long.parquet")
bulk = pd.read_parquet(PD / "bulkowski_features.parquet")
bulk_long = bulk[bulk.direction == "long"][["born_ms","t_id","1d_engulf","1d_db","B1_aligned"]].copy()
df_merge = parent.merge(bulk_long, on="born_ms", how="left")
df_merge["B1_aligned"] = df_merge.B1_aligned.fillna(False).astype(bool)
for c in ["1d_engulf","1d_db"]:
    df_merge[c] = df_merge[c].fillna(False).astype(bool)

sub = df_merge[df_merge.born_ms >= CUT].copy()


def daily_idx_at(born):
    return int(np.searchsorted(ts_1d_arr, born, side="right")) - 1


def last_n_2h_return(idx2h, n=10):
    if idx2h < n: return None
    p0 = cans_2h[idx2h - n].close
    p1 = cans_2h[idx2h - 1].close
    return (p1 - p0) / p0 * 100


records = []
for _, r in sub.iterrows():
    co = int(r.ob_cur_open_ms); born = int(r.born_ms)
    idx2h = bar2h_idx.get(co)
    if idx2h is None or idx2h < 50: continue
    prev2 = cans_2h[idx2h-1]; cur2 = cans_2h[idx2h]

    # Volume cur 2h
    vol_cur = vol_2h_arr[idx2h]
    vol_prev = vol_2h_arr[idx2h-1]
    vol_avg20 = vol_2h_arr[max(0, idx2h-20):idx2h].mean()
    vol_spike = vol_cur / vol_avg20 if vol_avg20 > 0 else None
    vol_ratio_cur_prev = vol_cur / vol_prev if vol_prev > 0 else None

    # 5-bar momentum (cumulative return last 5 2h closed bars)
    mom_5 = last_n_2h_return(idx2h, n=5)
    mom_10 = last_n_2h_return(idx2h, n=10)
    mom_20 = last_n_2h_return(idx2h, n=20)

    # HMA-78 distance on 1D
    di = daily_idx_at(born)
    hma = hma_proxy(di, 78) if di and di >= 78 else None
    hma_dist_pct = ((cur2.close - hma) / hma * 100) if hma else None

    # 1D current bullish? (last fully-closed 1D)
    if di and di >= 1:
        d1_bar = cans_1d[di]
        d1_bull = d1_bar.close > d1_bar.open
        d1_body_pct = (d1_bar.close - d1_bar.open) / d1_bar.open * 100
        # Previous 1D
        d1_prev_bull = cans_1d[di-1].close > cans_1d[di-1].open
    else:
        d1_bull = None; d1_body_pct = None; d1_prev_bull = None

    # 12h current bullish
    ts_12h_arr = np.array([c.open_time for c in cans_12h])
    i12 = int(np.searchsorted(ts_12h_arr, born, side="right")) - 1
    d12_bull = (cans_12h[i12].close > cans_12h[i12].open) if i12 >= 0 else None

    # Distance from 14d high/low (per 1D)
    if di and di >= 14:
        h14 = max(c.high for c in cans_1d[di-13:di+1])
        l14 = min(c.low for c in cans_1d[di-13:di+1])
        rng14 = h14 - l14
        pos_in_range = (cur2.close - l14) / rng14 * 100 if rng14 > 0 else 50
    else:
        pos_in_range = None

    # cur body / cur range ratio (displacement quality)
    cur_body = abs(cur2.close - cur2.open)
    cur_range = cur2.high - cur2.low
    disp_quality = cur_body / cur_range if cur_range > 0 else None

    # Was prev bar a "trap" (engulfed by cur)?
    prev_engulfed = (cur2.close > prev2.open) and (cur2.open < prev2.close)

    # Drop_lo break of N-bar low: how many of last N 2h bars had low < our drop_lo?
    drop_lo = min(prev2.low, cur2.low)
    lows_20 = np.array([c.low for c in cans_2h[max(0, idx2h-20):idx2h-1]])
    n_below = int((lows_20 < drop_lo).sum())  # 0 = drop_lo broke 20-bar low

    # Days since last D-FL
    fl_ts_below = [c.open_time for c in cans_1d[:di+1] if di and c.low < drop_lo]
    days_since_below = (born - fl_ts_below[-1]) / (24*3600*1000) if fl_ts_below else None

    records.append({
        "born_ms": born, "R": r.R, "touched": r.touched,
        "p4": r.p4_form, "p6": r.p6_form, "B1": r.B1_aligned,
        "engulf_1d": r["1d_engulf"], "db_1d": r["1d_db"], "t_id": r.t_id,
        "vol_cur": vol_cur, "vol_spike_20": vol_spike,
        "vol_ratio_cur_prev": vol_ratio_cur_prev,
        "mom_5": mom_5, "mom_10": mom_10, "mom_20": mom_20,
        "hma_dist_pct": hma_dist_pct,
        "d1_bull": d1_bull, "d1_body_pct": d1_body_pct, "d1_prev_bull": d1_prev_bull,
        "d12_bull": d12_bull,
        "pos_in_range_14d": pos_in_range,
        "disp_quality": disp_quality,
        "prev_engulfed": prev_engulfed,
        "n_below_drop_in_20": n_below,
        "days_since_below_drop": days_since_below,
    })

rdf = pd.DataFrame(records)
dec = rdf[rdf.R != 0].copy()
w = dec[dec.R == 1]; l = dec[dec.R == -1]
print(f"Decisive: W={len(w)} L={len(l)}  WR baseline={len(w)/(len(w)+len(l))*100:.1f}%")


# Numeric comparison
print(f"\n{'='*110}")
print(f"NEW NUMERIC FEATURES — mean W vs mean L (diff > 0 = winner-leaning)")
print(f"{'='*110}")
print(f"{'feature':<28} {'W_mean':>10} {'W_med':>10} {'L_mean':>10} {'L_med':>10} {'diff':>9}")
nfeat = ["vol_spike_20","vol_ratio_cur_prev","mom_5","mom_10","mom_20",
         "hma_dist_pct","d1_body_pct","pos_in_range_14d","disp_quality",
         "n_below_drop_in_20","days_since_below_drop"]
for c in nfeat:
    wv = w[c].dropna(); lv = l[c].dropna()
    if len(wv) < 10 or len(lv) < 10: continue
    wm, wmd = wv.mean(), wv.median()
    lm, lmd = lv.mean(), lv.median()
    print(f"  {c:<28} {wm:>+10.3f} {wmd:>+10.3f} {lm:>+10.3f} {lmd:>+10.3f} {wm-lm:>+9.3f}")

print(f"\n{'='*110}")
print(f"BINARY — %W vs %L (diff_pp)")
print(f"{'='*110}")
bf = ["d1_bull","d1_prev_bull","d12_bull","prev_engulfed"]
for c in bf:
    wv = w[c].dropna(); lv = l[c].dropna()
    if len(wv) < 5 or len(lv) < 5: continue
    pw = wv.mean()*100; pl = lv.mean()*100
    print(f"  {c:<28} W={pw:>5.1f}% L={pl:>5.1f}%  diff={pw-pl:>+5.1f}pp")


# Find sharp boundaries — quantile analysis
print(f"\n{'='*110}")
print(f"QUANTILE-BASED WR — split each numeric feature into 5 buckets, see WR per bucket")
print(f"{'='*110}")
for c in nfeat:
    sub_v = dec[dec[c].notna()].copy()
    if len(sub_v) < 100: continue
    try:
        sub_v["bucket"] = pd.qcut(sub_v[c], q=5, labels=["Q1_low","Q2","Q3","Q4","Q5_high"], duplicates='drop')
    except Exception:
        continue
    print(f"\n  {c}:")
    for b, g in sub_v.groupby("bucket"):
        nw = (g.R==1).sum(); nl = (g.R==-1).sum()
        if (nw+nl) < 10: continue
        wr = nw/(nw+nl)*100
        rng = f"{g[c].min():.2f}..{g[c].max():.2f}"
        print(f"    {str(b):<10} N={nw+nl:>4} WR={wr:>5.1f}%  range=[{rng}]")
