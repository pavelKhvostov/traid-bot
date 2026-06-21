"""Comprehensive winner profile for LONG 2h ob_vc since 2023-06-06.

For each WIN (R=+1) and LOSS (R=-1), compute:
  - Bar metrics: prev/cur body %, wick ratios, cur range %
  - Time: hour-of-day, day-of-week, session (Asia/EU/US)
  - Distance from ATR
  - n_FVG count
  - Parent HTF forming (p4, p6)
  - Bulkowski features (1d_engulf, 1d_db)
  - VWAP-3D crossings

Compare distributions winner vs loser, identify the strongest discriminators.
"""
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
HORIZON_MS = 14*24*3600*1000

rows = []
with CSV_1M.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if t < START_MS: continue
        rows.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
ts_1m = np.array([r[0] for r in rows], dtype=np.int64)
h_1m = np.array([r[2] for r in rows], dtype=np.float64)
l_1m = np.array([r[3] for r in rows], dtype=np.float64)
c_1m = np.array([r[4] for r in rows], dtype=np.float64)

rows_ohlc = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
cans_d = aggregate_all_tfs(rows_ohlc)
cans_2h = to_candles(cans_d["2h"])
cans_4h = to_candles(cans_d["4h"])
cans_1d = to_candles(cans_d["1d"])

bar2h_idx = {c.open_time: i for i, c in enumerate(cans_2h)}
bar4h_idx = {c.open_time: i for i, c in enumerate(cans_4h)}
bar1d_idx = {c.open_time: i for i, c in enumerate(cans_1d)}


def atr_14d_at(born_ms):
    """14-bar ATR on 1D at born_ms (using last 14 closed 1D bars)."""
    # Find 1d bar before born_ms
    arr_ts = np.array([c.open_time for c in cans_1d])
    idx = int(np.searchsorted(arr_ts, born_ms)) - 1
    if idx < 14: return None
    trs = []
    for k in range(idx-13, idx+1):
        if k == 0:
            tr = cans_1d[k].high - cans_1d[k].low
        else:
            p_close = cans_1d[k-1].close
            tr = max(cans_1d[k].high - cans_1d[k].low,
                     abs(cans_1d[k].high - p_close),
                     abs(cans_1d[k].low - p_close))
        trs.append(tr)
    return float(np.mean(trs))


# Pre-existing data
PD = pathlib.Path(__file__).parent.parent / "data"
parent = pd.read_parquet(PD / "forming_parent_long.parquet")
bulk = pd.read_parquet(PD / "bulkowski_features.parquet")
bulk_long = bulk[bulk.direction == "long"][["born_ms","t_id","1d_engulf","1d_db","1d_hammer","1d_busted",
                                             "4h_engulf","4h_db","B1_aligned"]].copy()
merge_keys = ["born_ms"]
df_merge = parent.merge(bulk_long, on="born_ms", how="left")
df_merge["B1_aligned"] = df_merge.B1_aligned.fillna(False).astype(bool)
for c in ["1d_engulf","1d_db","1d_hammer","1d_busted","4h_engulf","4h_db"]:
    df_merge[c] = df_merge[c].fillna(False).astype(bool)

# Subset 2023+
sub = df_merge[df_merge.born_ms >= CUT].copy()

# Compute bar-level features per setup
records = []
for _, r in sub.iterrows():
    co = int(r.ob_cur_open_ms)
    born = int(r.born_ms)
    idx2h = bar2h_idx.get(co)
    if idx2h is None or idx2h < 1: continue
    prev2 = cans_2h[idx2h-1]; cur2 = cans_2h[idx2h]
    prev_body = (prev2.close - prev2.open) / prev2.open
    cur_body = (cur2.close - cur2.open) / cur2.open
    prev_lower_wick = (min(prev2.open, prev2.close) - prev2.low) / prev2.open
    cur_lower_wick = (min(cur2.open, cur2.close) - cur2.low) / cur2.open
    prev_upper_wick = (prev2.high - max(prev2.open, prev2.close)) / prev2.open
    cur_upper_wick = (cur2.high - max(cur2.open, cur2.close)) / cur2.open
    cur_range_pct = (cur2.high - cur2.low) / cur2.open
    prev_range_pct = (prev2.high - prev2.low) / prev2.open

    # Time
    dt = datetime.fromtimestamp(born/1000, tz=timezone.utc)
    hour = dt.hour
    dow = dt.weekday()
    # Session by UTC hour: Asia 0-7, EU 7-14, US 14-22, off-hours
    if 0 <= hour < 7: session = "Asia"
    elif 7 <= hour < 14: session = "EU"
    elif 14 <= hour < 22: session = "US"
    else: session = "Off"

    # ATR-based metrics
    atr = atr_14d_at(born)
    cur_to_atr = cur_range_pct * cur2.open / atr if atr else None
    drop_lo = min(prev2.low, cur2.low)
    wick_depth_atr = (cur2.close - drop_lo) / atr if atr else None  # bounce % of ATR

    # Recovery: how much did cur recover from wick? (drop_lo to cur.close)
    recovery_pct = (cur2.close - drop_lo) / drop_lo
    # Engulfing strength: cur close > prev high?
    full_engulf = cur2.close > prev2.high

    records.append({
        "born_ms": born,
        "R": r.R, "touched": r.touched,
        "p4": r.p4_form, "p6": r.p6_form,
        "B1": r.B1_aligned, "engulf_1d": r["1d_engulf"], "db_1d": r["1d_db"],
        "t_id": r.t_id,
        "prev_body_pct": prev_body*100, "cur_body_pct": cur_body*100,
        "prev_lower_wick_pct": prev_lower_wick*100,
        "cur_lower_wick_pct": cur_lower_wick*100,
        "prev_upper_wick_pct": prev_upper_wick*100,
        "cur_upper_wick_pct": cur_upper_wick*100,
        "cur_range_pct": cur_range_pct*100,
        "prev_range_pct": prev_range_pct*100,
        "hour": hour, "dow": dow, "session": session,
        "atr_d": atr, "cur_range_atr": cur_to_atr,
        "wick_depth_atr": wick_depth_atr, "recovery_pct": recovery_pct*100,
        "full_engulf": full_engulf,
    })

rdf = pd.DataFrame(records)
print(f"Records: {len(rdf)}  W={int((rdf.R==1).sum())}  L={int((rdf.R==-1).sum())}  Timeout={int(((rdf.touched) & (rdf.R==0)).sum())}")

# Filter to W/L only
dec = rdf[rdf.R != 0].copy()
w = dec[dec.R == 1]; l = dec[dec.R == -1]
print(f"\nDecisive: W={len(w)} L={len(l)}  baseline WR={len(w)/(len(w)+len(l))*100:.1f}%")


# Profile comparison
def profile(numeric_cols, binary_cols):
    print(f"\n{'='*100}")
    print(f"NUMERIC FEATURES — mean ± std for W vs L (smaller p-distance = stronger discriminator)")
    print(f"{'='*100}")
    print(f"{'feature':<25} {'W_mean':>8} {'W_med':>8} {'L_mean':>8} {'L_med':>8} {'diff_mean':>9}")
    for c in numeric_cols:
        wv = w[c].dropna(); lv = l[c].dropna()
        if len(wv) < 5 or len(lv) < 5: continue
        wm, wmd = wv.mean(), wv.median()
        lm, lmd = lv.mean(), lv.median()
        print(f"  {c:<25} {wm:>+8.2f} {wmd:>+8.2f} {lm:>+8.2f} {lmd:>+8.2f} {wm-lm:>+8.2f}")

    print(f"\n{'='*100}")
    print(f"BINARY FEATURES — % of W vs % of L (bigger diff = stronger)")
    print(f"{'='*100}")
    print(f"{'feature':<25} {'%_W':>7} {'%_L':>7} {'diff_pp':>8}")
    for c in binary_cols:
        if c not in w.columns: continue
        pw = w[c].mean()*100; pl = l[c].mean()*100
        print(f"  {c:<25} {pw:>6.1f}% {pl:>6.1f}% {pw-pl:>+7.1f}pp")


profile(
    ["prev_body_pct","cur_body_pct","prev_lower_wick_pct","cur_lower_wick_pct",
     "prev_upper_wick_pct","cur_upper_wick_pct","cur_range_pct","prev_range_pct",
     "cur_range_atr","wick_depth_atr","recovery_pct","atr_d","hour","dow"],
    ["p4","p6","B1","engulf_1d","db_1d","full_engulf"]
)

# Type distribution
print(f"\n{'='*100}")
print(f"TYPE DISTRIBUTION (W vs L)")
print(f"{'='*100}")
print(f"{'t_id':<8} {'W':>5} {'L':>5} {'WR':>6}")
for t, g in dec.groupby("t_id"):
    nw = (g.R==1).sum(); nl = (g.R==-1).sum()
    wr = nw/(nw+nl)*100 if (nw+nl) else 0
    print(f"  {t:<8} {nw:>5} {nl:>5} {wr:>5.1f}%")

# Session breakdown
print(f"\n{'='*100}")
print(f"SESSION BREAKDOWN")
print(f"{'='*100}")
for s, g in dec.groupby("session"):
    nw = (g.R==1).sum(); nl = (g.R==-1).sum()
    wr = nw/(nw+nl)*100 if (nw+nl) else 0
    print(f"  {s:<8} N={len(g):>4}  W={nw:>4} L={nl:>4} WR={wr:>5.1f}%")

# Hour-of-day
print(f"\nHour-of-day (UTC) — only show buckets with N≥30")
for h in range(24):
    g = dec[dec.hour == h]
    if len(g) < 30: continue
    nw = (g.R==1).sum(); nl = (g.R==-1).sum()
    wr = nw/(nw+nl)*100 if (nw+nl) else 0
    print(f"  UTC {h:>2}:00  N={len(g):>4} WR={wr:>5.1f}%")
