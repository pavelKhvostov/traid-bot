"""Phase A — Master dataset for maxV expert research.

Period: last 6 months BTC (2025-12-04 .. 2026-06-04)
TFs: 4h, 6h, 12h, D, 2D, 3D (mlt=45 LTF per CEIL rule)
Output:
  ~/Desktop/maxv_master_6m.parquet — per maxV event (one row per maxV formation)
  ~/Desktop/maxv_touches_6m.parquet — per touch event (one row per maxV touch)
"""
from __future__ import annotations
import math, sys, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.home() / "smc-lib"))
from indicators.vic_asvk import auto_ltf_minutes
from elements.fvg.code import detect_fvg
from candle import Candle

MS_M = 60_000
MSK = timezone(timedelta(hours=3))
CSV = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

TF_MIN = {"4h": 240, "6h": 360, "12h": 720, "D": 1440, "2D": 2880, "3D": 4320}
FVG_TFS = ["15m", "20m", "1h", "2h"]
FVG_TF_MIN = {"15m": 15, "20m": 20, "1h": 60, "2h": 120}
MLT = 45

# Phase A scope
DATE_FROM = "2025-12-04"
DATE_TO = "2026-06-04"

# Reaction params (Triple-Barrier)
PT = 1.5  # profit barrier (in ATR)
SL = 1.0  # stop barrier
T1_BARS = 12  # max bars (in HTF's own TF)


def load_1m():
    start_ms = int(datetime.fromisoformat(DATE_FROM).replace(tzinfo=timezone.utc).timestamp()*1000)
    end_ms = int(datetime.fromisoformat(DATE_TO).replace(tzinfo=timezone.utc).timestamp()*1000) + 24*3600*1000
    rows = []
    with CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            ts = int(t.timestamp() * 1000)
            if ts < start_ms - 30*24*3600*1000: continue  # +30d lookback for LTF anchor
            if ts >= end_ms: break
            rows.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return rows, start_ms, end_ms


def agg(rs, tf_ms, anchor=0):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in rs:
        b = ts - ((ts - anchor) % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


def compute_maxv_events(rows_1m, tf_name, tf_min, anchor_ms=0):
    """For each HTF candle of given TF, compute maxV event."""
    tf_ms = tf_min * MS_M
    ltf_min = auto_ltf_minutes(tf_min, MLT)
    print(f"  {tf_name} (LTF={ltf_min}m, anchor={anchor_ms})", end=" ")
    htf_bars = agg(rows_1m, tf_ms, anchor_ms)
    events = []
    for hb_ts, hb_o, hb_h, hb_l, hb_c, hb_v in htf_bars:
        hb_end = hb_ts + tf_ms
        # LTF bars within this HTF, anchored to HTF start
        ltf_ms = ltf_min * MS_M
        ltf_bars = []
        cb = None; o = h = l = c = 0.0; v = 0.0
        for ts, oo, hh, ll, cc, vv in rows_1m:
            if ts < hb_ts: continue
            if ts >= hb_end: break
            b = ts - ((ts - hb_ts) % ltf_ms)
            if b != cb:
                if cb is not None: ltf_bars.append((cb, o, h, l, c, v))
                cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
            else:
                h = max(h, hh); l = min(l, ll); c = cc; v += vv
        if cb is not None: ltf_bars.append((cb, o, h, l, c, v))
        if not ltf_bars: continue
        # Max-vol bar (absolute, any direction)
        mb = max(ltf_bars, key=lambda b: b[5])
        mb_ts, mb_o, mb_h, mb_l, mb_c, mb_v = mb
        # Position in parent candle
        rng = hb_h - hb_l
        if rng <= 0: continue
        pos_in_range = (mb_c - hb_l) / rng  # 0..1
        body_lo, body_hi = min(hb_o, hb_c), max(hb_o, hb_c)
        if mb_c < body_lo:
            position = "lower_wick"
        elif mb_c > body_hi:
            position = "upper_wick"
        elif mb_c < (body_lo + body_hi) / 2:
            position = "body_bottom"
        else:
            position = "body_top"
        # Time-of-day of max-vol LTF bar
        mb_dt = datetime.fromtimestamp(mb_ts/1000, tz=timezone.utc)
        utc_hour = mb_dt.hour
        if utc_hour < 8: session = "asia"
        elif utc_hour < 13: session = "london"
        elif utc_hour < 21: session = "ny"
        else: session = "off"
        candle_color = "bull" if hb_c > hb_o else ("bear" if hb_c < hb_o else "doji")
        events.append({
            "tf": tf_name,
            "formed_ts": hb_ts,
            "level": float(mb_c),
            "zone_lo": float(mb_l),
            "zone_hi": float(mb_h),
            "maxV_vol": float(mb_v),
            "parent_O": hb_o, "parent_H": hb_h, "parent_L": hb_l, "parent_C": hb_c,
            "parent_color": candle_color,
            "position": position,
            "pos_in_range": pos_in_range,
            "session": session,
            "max_vol_ltf_ts": mb_ts,
        })
    print(f"{len(events)} events")
    return events


def scan_fvgs(rows_1m, ltf_min):
    tf_ms = ltf_min * MS_M
    bars = agg(rows_1m, tf_ms)
    cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
    out = []
    for i in range(2, len(cans)):
        f = detect_fvg(cans[i-2], cans[i-1], cans[i])
        if f is not None:
            out.append({"ready_ts": cans[i].open_time + tf_ms, "lo": f.zone[0], "hi": f.zone[1], "dir": f.direction})
    return out


def compute_atr(rows_1m, tf_ms, period=14, anchor=0):
    bars = agg(rows_1m, tf_ms, anchor)
    n = len(bars)
    tr = np.zeros(n); atr = np.zeros(n)
    for i in range(1, n):
        h, l = bars[i][2], bars[i][3]; cp = bars[i-1][4]
        tr[i] = max(h-l, abs(h-cp), abs(l-cp))
    for i in range(period, n):
        atr[i] = tr[i-period+1:i+1].mean()
    return [(bars[i][0], atr[i]) for i in range(n)]


def main():
    print("[1/4] Loading 1m BTC...")
    rows_1m, start_ms, end_ms = load_1m()
    print(f"  {len(rows_1m):,} bars, range {DATE_FROM} .. {DATE_TO}")

    # Compute maxV events per TF
    print("\n[2/4] Compute maxV events per TF (only events formed within scope window)...")
    all_events = []
    for tf_name, tf_min in TF_MIN.items():
        anchor = 0  # epoch — for D ok, for 3D also OK
        evs = compute_maxv_events(rows_1m, tf_name, tf_min, anchor)
        # Filter to events formed >= scope start
        evs = [e for e in evs if e["formed_ts"] >= start_ms]
        all_events.extend(evs)
    print(f"  Total maxV events: {len(all_events)}")

    df_events = pd.DataFrame(all_events)
    out1 = Path.home() / "Desktop" / "maxv_master_6m.parquet"
    df_events.to_parquet(out1, index=False)
    print(f"  → {out1}")

    # Scan FVGs on 15m/20m/1h/2h
    print("\n[3/4] Scan FVGs on LTFs (15m/20m/1h/2h)...")
    fvgs_by_tf = {}
    for tf, m in FVG_TF_MIN.items():
        fvgs_by_tf[tf] = scan_fvgs(rows_1m, m)
        print(f"  {tf}: {len(fvgs_by_tf[tf])} FVGs")

    # Precompute 12h bars for touch tracking + ATR
    print("\n[4/4] Compute touches + reactions...")
    bars_12h = agg(rows_1m, 720 * MS_M)
    atr_12h = compute_atr(rows_1m, 720*MS_M)
    atr_map = {ts: atr for ts, atr in atr_12h}

    ts12 = np.array([b[0] for b in bars_12h], dtype=np.int64)
    h12 = np.array([b[2] for b in bars_12h])
    l12 = np.array([b[3] for b in bars_12h])
    c12 = np.array([b[4] for b in bars_12h])

    # For each maxV: iterate forward 12h bars, detect touches (zone entry)
    touches = []
    n_events = len(all_events)
    for k, ev in enumerate(all_events):
        if k % 200 == 0: print(f"  {k}/{n_events}...")
        # Start: 1 12h bar after formation
        start_idx = int(np.searchsorted(ts12, ev["formed_ts"], side='right'))
        # Find first touch (zone entry by 12h bar)
        # Force zone: [zone_lo, zone_hi]
        zl, zh = ev["zone_lo"], ev["zone_hi"]
        lvl = ev["level"]
        zone_half_lo = lvl - zl  # symmetric or asymm
        zone_half_hi = zh - lvl
        for j in range(start_idx, len(bars_12h)):
            bar_h, bar_l = h12[j], l12[j]
            # Did bar enter zone?
            entered = bar_l <= zh and bar_h >= zl
            if not entered: continue
            # Deepest penetration price (closest to LEVEL)
            if bar_l > lvl: touch_price = bar_l
            elif bar_h < lvl: touch_price = bar_h
            else: touch_price = lvl  # bar straddles level
            # Force at deepest penetration (symmetric linear)
            if touch_price <= lvl:
                force = (touch_price - zl) / max(lvl - zl, 1e-9)
            else:
                force = (zh - touch_price) / max(zh - lvl, 1e-9)
            force = max(0.0, min(1.0, force))
            # Reaction (Triple-Barrier from this 12h bar entry)
            touch_ts = ts12[j]
            atr_val = atr_map.get(int(touch_ts), 0)
            if atr_val <= 0: break
            side = "support" if c12[max(0,j-1)] > lvl else "resistance"
            if side == "resistance":
                pt_lvl = lvl - PT * atr_val
                sl_lvl = lvl + SL * atr_val
            else:
                pt_lvl = lvl + PT * atr_val
                sl_lvl = lvl - SL * atr_val
            label = 0; end_j = min(j + T1_BARS, len(bars_12h) - 1)
            for jj in range(j + 1, end_j + 1):
                bh, bl = h12[jj], l12[jj]
                if side == "resistance":
                    if bl <= pt_lvl: label = +1; break
                    if bh >= sl_lvl: label = -1; break
                else:
                    if bh >= pt_lvl: label = +1; break
                    if bl <= sl_lvl: label = -1; break
            # FVG presence in zone at touch time
            fvg_counts = {}
            for tf in FVG_TFS:
                fvg_counts[f"fvg_{tf}"] = sum(
                    1 for f in fvgs_by_tf[tf]
                    if f["ready_ts"] <= touch_ts and (f["lo"] <= zh and f["hi"] >= zl)
                )
            # Age in TF bars between formation and touch
            tf_ms = TF_MIN[ev["tf"]] * MS_M
            age_bars = int((touch_ts - ev["formed_ts"]) / tf_ms)
            touch_row = {
                "tf": ev["tf"],
                "formed_ts": ev["formed_ts"],
                "level": lvl,
                "touch_ts": int(touch_ts),
                "touch_price": float(touch_price),
                "force": force,
                "side": side,
                "label": label,
                "age_bars": age_bars,
                "position": ev["position"],
                "parent_color": ev["parent_color"],
                "session": ev["session"],
                **fvg_counts,
            }
            touches.append(touch_row)
            # only first touch per maxV — break
            break

    df_touch = pd.DataFrame(touches)
    out2 = Path.home() / "Desktop" / "maxv_touches_6m.parquet"
    df_touch.to_parquet(out2, index=False)
    print(f"  Touches: {len(df_touch)}  → {out2}")

    if len(df_touch) > 0:
        print(f"\n=== Sanity stats ===")
        print(f"  Label distribution: {df_touch['label'].value_counts().to_dict()}")
        print(f"  P(reaction = +1): {(df_touch['label']==1).mean()*100:.1f}%")
        print(f"  P(stop = -1): {(df_touch['label']==-1).mean()*100:.1f}%")
        print(f"  P(timeout = 0): {(df_touch['label']==0).mean()*100:.1f}%")
        print(f"\n  By TF (P(reaction)):")
        for tf in TF_MIN:
            sub = df_touch[df_touch["tf"] == tf]
            if not sub.empty:
                print(f"    {tf}: n={len(sub)} P+1={(sub['label']==1).mean()*100:.1f}%")


if __name__ == "__main__":
    main()
