"""Confluence score из 12 факторов для i-RDRB+FVG mit setup'а.
Фильтр: score >= threshold (по умолчанию 6 = половина).

Факторы (для LONG; SHORT — зеркально):
  1. Daily low(D) ≈ zone_bottom (в пределах 0.3% от zone_width)
  2. 1d FVG того же направления overlap с zone
  3. Entry < Daily VWAP (discount)
  4. Liquidity grab под FL-1d (low(D) < последний FL-1d level до D)
  5. EMA-50(1d) близко к entry (±2% от entry)
  6. HA-1h GREEN (для LONG) на close FVG.c2
  7. ViC.D(D-1) в зоне интереса (Pine LTF=15m)
  8. EVoT 5-bar winner = BEAR (absorption для LONG)
  9. ASVK RSI ema_3 ≤ below_level (OS extreme на 1h)
 10. Hull-78 1d direct match (close > HMA для LONG)
 11. Money Hands ASVK A2 (bw2>SMA для LONG) на 6h
 12. OB-4h confluence (есть OB-4h pair того же направления в окне setup'а)

BTC + ETH 1h, 6 лет, RR=1.4.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb
from strategies.strategy_1_1_1 import detect_fvg, detect_ob_pair, zones_overlap
from research.asvk_trend_line.plot_asvk_trend_line import hma
from research.asvk_rsi.plot_asvk_rsi import adjusted_rsi, dynamic_levels
from research.money_hands.plot_money_hands import wavetrend_blueWaves, sma
from vic_levels import calculate_vic_d

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
]
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4
HMA_LEN = 78


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def heikin_close_open(df):
    n = len(df)
    ha_c = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha_o = np.zeros(n)
    ha_o[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
    cl_arr = ha_c.values
    for i in range(1, n):
        ha_o[i] = (ha_o[i-1] + cl_arr[i-1]) / 2
    return pd.Series(ha_o, index=df.index), ha_c


def scan_asset(asset, path):
    df_1m = load_1m(path)
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])
    df_4h = df_1m.resample("4h", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])
    df_6h = df_1m.resample("6h", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])
    df_1d = df_1m.resample("1D", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])

    # Pre-compute indicators
    hull_1d = hma(df_1d["close"], HMA_LEN).to_numpy()
    ema_50_1d = ema(df_1d["close"], 50).to_numpy()
    ha_o_1h, ha_c_1h = heikin_close_open(df_1h)
    rsi_ema3_1h = adjusted_rsi(df_1h["close"])
    rsi_above, rsi_below = dynamic_levels(rsi_ema3_1h)
    # Money Hands на 6h
    hlc3_6h = (df_6h["high"] + df_6h["low"] + df_6h["close"]) / 3
    _, bw2_6h, _ = wavetrend_blueWaves(hlc3_6h)
    bw2_sma_6h = sma(bw2_6h, 14)

    # Daily FL/FH fractals (pre-compute)
    h_1d = df_1d["high"].to_numpy(); l_1d = df_1d["low"].to_numpy()
    fl_levels = []  # (level, ready_idx)
    fh_levels = []
    for i in range(2, len(df_1d) - 2):
        if l_1d[i] < l_1d[i-2] and l_1d[i] < l_1d[i-1] and l_1d[i] < l_1d[i+1] and l_1d[i] < l_1d[i+2]:
            fl_levels.append((float(l_1d[i]), i + 2))  # ready_idx = pivot+2
        if h_1d[i] > h_1d[i-2] and h_1d[i] > h_1d[i-1] and h_1d[i] > h_1d[i+1] and h_1d[i] > h_1d[i+2]:
            fh_levels.append((float(h_1d[i]), i + 2))
    fl_arr = np.array([f[0] for f in fl_levels])
    fl_r = np.array([f[1] for f in fl_levels])
    fh_arr = np.array([f[0] for f in fh_levels])
    fh_r = np.array([f[1] for f in fh_levels])

    # Daily FVGs
    daily_fvgs = []  # (dir, bottom, top, c2_idx)
    for i in range(2, len(df_1d)):
        if df_1d.iloc[i-2]["high"] < df_1d.iloc[i]["low"]:
            daily_fvgs.append(("LONG", float(df_1d.iloc[i-2]["high"]),
                                 float(df_1d.iloc[i]["low"]), i))
        if df_1d.iloc[i-2]["low"] > df_1d.iloc[i]["high"]:
            daily_fvgs.append(("SHORT", float(df_1d.iloc[i]["high"]),
                                 float(df_1d.iloc[i-2]["low"]), i))

    # ViC.D cache
    days_idx = pd.date_range(start=df_1m.index.min().normalize(),
                             end=df_1m.index.max().normalize(), freq="D")
    vic_cache = {d: calculate_vic_d(df_1m, d, ltf_minutes=15) for d in days_idx}

    # Scan
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    opens_h = df_1h["open"].to_numpy()
    idx_1h = df_1h.index
    idx_4h = df_4h.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    op1 = df_1m["open"].to_numpy(); cl1 = df_1m["close"].to_numpy()
    vol1 = df_1m["volume"].to_numpy()
    idx1 = df_1m.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_1h, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_1h, k + 2)
        if fvg is None or fvg.direction != i_dir: continue
        if i_dir == "LONG":
            zone_b = float(min(lows[k - 2], lows[k - 1], lows[k], lows[k + 1]))
            zone_t = float(lows[k + 2])
        else:
            zone_t = float(max(highs[k - 2], highs[k - 1], highs[k], highs[k + 1]))
            zone_b = float(highs[k + 2])
        if zone_t <= zone_b: continue
        width = zone_t - zone_b
        if i_dir == "LONG":
            entry = zone_b + ENTRY_FRAC * width; sl = zone_b + SL_FRAC * width
            tp = entry + RR * (entry - sl)
        else:
            entry = zone_t - ENTRY_FRAC * width; sl = zone_t - SL_FRAC * width
            tp = entry - RR * (sl - entry)

        signal_time = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        day_d = signal_time.normalize()
        day_prev = day_d - pd.Timedelta(days=1)
        i_d = int(df_1d.index.searchsorted(day_d, side="right")) - 1
        if i_d < 50: continue  # need EMA-50

        # === Confluence factors ===
        f = {}
        # 1. Daily extreme ≈ zone границы
        if i_d >= 0:
            day_low = float(df_1d.iloc[i_d]["low"])
            day_high = float(df_1d.iloc[i_d]["high"])
            tol = 0.003 * width  # 0.3% width tolerance
            if i_dir == "LONG":
                f["1_daily_extreme"] = bool(abs(day_low - zone_b) < tol)
            else:
                f["1_daily_extreme"] = bool(abs(day_high - zone_t) < tol)

        # 2. 1d FVG overlap with zone (same direction)
        f["2_fvg_1d_overlap"] = False
        for dir_, b, t, c2_i in daily_fvgs:
            if c2_i > i_d: continue
            if dir_ == i_dir and zones_overlap(b, t, zone_b, zone_t):
                f["2_fvg_1d_overlap"] = True; break

        # 3. Entry < VWAP(D) (LONG) / > VWAP(D) (SHORT)
        day_seg = df_1m[(df_1m.index >= day_d) & (df_1m.index < signal_time)]
        if len(day_seg):
            typ = (day_seg["high"] + day_seg["low"] + day_seg["close"]) / 3
            vsum = (typ * day_seg["volume"]).sum()
            vol = day_seg["volume"].sum()
            vwap = float(vsum / vol) if vol > 0 else np.nan
        else:
            vwap = np.nan
        if not np.isnan(vwap):
            f["3_vwap"] = (entry < vwap) if i_dir == "LONG" else (entry > vwap)
        else:
            f["3_vwap"] = False

        # 4. Liquidity grab под FL-1d (last FL before D) / над FH-1d
        f["4_liq_grab"] = False
        if i_dir == "LONG" and fl_arr.size:
            mask = fl_r < i_d
            if mask.any():
                last_fl = fl_arr[mask][-1]
                f["4_liq_grab"] = day_low < last_fl
        elif i_dir == "SHORT" and fh_arr.size:
            mask = fh_r < i_d
            if mask.any():
                last_fh = fh_arr[mask][-1]
                f["4_liq_grab"] = day_high > last_fh

        # 5. EMA-50(1d) близко к entry (±2%)
        if i_d < len(ema_50_1d) and not np.isnan(ema_50_1d[i_d]):
            f["5_ema50_1d"] = abs(ema_50_1d[i_d] - entry) / entry < 0.02
        else:
            f["5_ema50_1d"] = False

        # 6. HA-1h GREEN/RED match (на close FVG.c2 = bar k+2)
        ha_o_v = ha_o_1h.iloc[k + 2]; ha_c_v = ha_c_1h.iloc[k + 2]
        if i_dir == "LONG":
            f["6_ha_1h"] = ha_c_v > ha_o_v
        else:
            f["6_ha_1h"] = ha_c_v < ha_o_v

        # 7. ViC.D(D-1) в зоне интереса
        vic_d_prev = vic_cache.get(day_prev)
        if vic_d_prev is not None:
            f["7_vic_d"] = zone_b < vic_d_prev < zone_t
        else:
            f["7_vic_d"] = False

        # 8. EVoT 5-bar BEAR winner для LONG / BULL для SHORT
        rng_start = idx_1h[k - 2]; rng_end = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        sp1 = int(idx1.searchsorted(rng_start, side="left"))
        ep1 = int(idx1.searchsorted(rng_end, side="left"))
        if ep1 > sp1:
            seg_o = op1[sp1:ep1]; seg_c = cl1[sp1:ep1]; seg_v = vol1[sp1:ep1]
            bm = seg_c > seg_o; rm = seg_c < seg_o
            mb = float(seg_v[bm].max()) if bm.any() else 0
            mr = float(seg_v[rm].max()) if rm.any() else 0
            if mb == 0 and mr == 0:
                f["8_evot"] = False
            else:
                winner = "BULL" if mb >= mr else "BEAR"
                if i_dir == "LONG":
                    f["8_evot"] = winner == "BEAR"
                else:
                    f["8_evot"] = winner == "BULL"
        else:
            f["8_evot"] = False

        # 9. ASVK RSI ema_3 ≤ below_level (LONG) / ≥ above_level (SHORT) на 1h
        ema3_v = rsi_ema3_1h.iloc[k + 2]
        rb = rsi_below.iloc[k + 2]; ra = rsi_above.iloc[k + 2]
        if pd.notna(ema3_v) and pd.notna(rb) and pd.notna(ra):
            if i_dir == "LONG":
                f["9_rsi_extreme"] = ema3_v <= rb
            else:
                f["9_rsi_extreme"] = ema3_v >= ra
        else:
            f["9_rsi_extreme"] = False

        # 10. Hull-78 1d direct
        if i_d < len(hull_1d) and not np.isnan(hull_1d[i_d]):
            c1d = float(df_1d.iloc[i_d]["close"])
            green = c1d > hull_1d[i_d]
            f["10_hull_1d"] = green if i_dir == "LONG" else (not green)
        else:
            f["10_hull_1d"] = False

        # 11. Money Hands A2 на 6h
        i_6 = int(df_6h.index.searchsorted(signal_time, side="right")) - 1
        if i_6 >= 14 and pd.notna(bw2_6h.iloc[i_6]) and pd.notna(bw2_sma_6h.iloc[i_6]):
            if i_dir == "LONG":
                f["11_mh_6h"] = bw2_6h.iloc[i_6] > bw2_sma_6h.iloc[i_6]
            else:
                f["11_mh_6h"] = bw2_6h.iloc[i_6] < bw2_sma_6h.iloc[i_6]
        else:
            f["11_mh_6h"] = False

        # 12. OB-4h confluence
        f["12_ob_4h"] = False
        sp4 = int(idx_4h.searchsorted(rng_start, side="left"))
        ep4 = int(idx_4h.searchsorted(rng_end + pd.Timedelta(hours=4), side="right"))
        for ci in range(max(sp4, 1), min(ep4, len(idx_4h))):
            ob = detect_ob_pair(df_4h, ci)
            if ob is not None and ob.direction == i_dir:
                f["12_ob_4h"] = True; break

        # Execution simulation
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            outcome = "no_mit"
        else:
            mit_idx = sp + int(mit_hits[0])
            post_lo = lo1[mit_idx:]; post_hi = hi1[mit_idx:]
            m = len(post_lo)
            if i_dir == "LONG":
                ei = np.where(post_lo <= entry)[0]; ti = np.where(post_hi >= tp)[0]
            else:
                ei = np.where(post_hi >= entry)[0]; ti = np.where(post_lo <= tp)[0]
            e_idx = int(ei[0]) if ei.size else m + 1
            tp_pre = int(ti[0]) if ti.size else m + 1
            if tp_pre < e_idx: outcome = "no_entry"
            elif e_idx >= m: outcome = "not_filled"
            else:
                p2l = post_lo[e_idx:]; p2h = post_hi[e_idx:]
                if i_dir == "LONG":
                    sm = p2l <= sl; tm = p2h >= tp
                else:
                    sm = p2h >= sl; tm = p2l <= tp
                sf = int(np.argmax(sm)) if sm.any() else -1
                tf = int(np.argmax(tm)) if tm.any() else -1
                if sf == -1 and tf == -1: outcome = "open"
                elif sf == -1: outcome = "win"
                elif tf == -1: outcome = "loss"
                else: outcome = "win" if tf < sf else "loss"

        row = {"dir": i_dir, "outcome": outcome, "score": sum(int(v) for v in f.values())}
        row.update(f)
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    parts = []
    for asset, path in ASSETS:
        print(f"scanning {asset}...", flush=True)
        df = scan_asset(asset, path)
        df["asset"] = asset
        parts.append(df)
    df_all = pd.concat(parts, ignore_index=True)

    closed = df_all[df_all["outcome"].isin(["win", "loss"])]
    w0 = int((closed["outcome"] == "win").sum()); l0 = len(closed) - w0
    base_wr = w0/len(closed)*100
    print(f"\nBaseline: n={len(closed)} W={w0} L={l0} WR={base_wr:.2f}% "
          f"ΣR={w0*RR-l0:+.2f} R/tr={(w0*RR-l0)/len(closed):+.3f}")

    print(f"\n=== Confluence score distribution ===")
    print(f"{'score':>5} {'n':>4} {'WR%':>6} {'ΣR':>+8} {'R/tr':>+7} {'Δprec':>+7}")
    for s in range(13):
        sub = closed[closed["score"] == s]
        w = int((sub["outcome"] == "win").sum()); l = len(sub) - w
        if not (w + l): continue
        wr = w/(w+l)*100
        r = w*RR - l
        d = wr - base_wr
        print(f"{s:>5} {w+l:>4} {wr:>6.2f} {r:>+8.2f} {r/(w+l):>+7.3f} {d:>+7.2f}")

    print(f"\n=== Cumulative score ≥ X ===")
    print(f"{'th':>3} {'n':>4} {'WR%':>6} {'ΣR':>+8} {'R/tr':>+7} {'Δprec':>+7}")
    for th in range(13):
        sub = closed[closed["score"] >= th]
        w = int((sub["outcome"] == "win").sum()); l = len(sub) - w
        if not (w + l): continue
        wr = w/(w+l)*100; r = w*RR - l
        d = wr - base_wr
        print(f"{th:>3} {w+l:>4} {wr:>6.2f} {r:>+8.2f} {r/(w+l):>+7.3f} {d:>+7.2f}")

    # WR по asset для score >= 6
    print(f"\n=== Threshold score≥6 per asset ===")
    for asset in ("BTCUSDT", "ETHUSDT"):
        sub = closed[(closed["asset"] == asset) & (closed["score"] >= 6)]
        w = int((sub["outcome"] == "win").sum()); l = len(sub) - w
        if not (w + l): continue
        wr = w/(w+l)*100; r = w*RR - l
        print(f"  {asset}: n={w+l} W={w} L={l} WR={wr:.2f}% ΣR={r:+.2f} R/tr={r/(w+l):+.3f}")

    # Per-factor stats (Δprec при наличии)
    print(f"\n=== Per-factor positive Δprec (factor=True vs False) ===")
    print(f"{'factor':>20} {'n_true':>7} {'WR_true':>8} {'n_false':>8} {'WR_false':>9} {'Δprec':>7}")
    for col in sorted([c for c in closed.columns if c[0:1].isdigit() or c.startswith(("1","2","3","4","5","6","7","8","9"))]):
        if col == "score": continue
        t = closed[closed[col] == True]; ff = closed[closed[col] == False]
        wt = int((t["outcome"] == "win").sum()); lt = len(t) - wt
        wf = int((ff["outcome"] == "win").sum()); lf = len(ff) - wf
        if not (wt + lt) or not (wf + lf): continue
        wrt = wt/(wt+lt)*100; wrf = wf/(wf+lf)*100
        d = wrt - wrf
        print(f"  {col:>20} {wt+lt:>7} {wrt:>7.2f}% {wf+lf:>8} {wrf:>8.2f}% {d:>+7.2f}")

    # Save
    out = ROOT / "signals" / "irdrb_confluence_score.csv"
    df_all.to_csv(out, index=False)
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
