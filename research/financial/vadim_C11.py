"""Candidate C11 — run_3candles_sweep (continuation), Vadim pattern.

Pattern (smc-lib/patterns/run_3candles_sweep/definition.md), TFs {4h, 8h}:
  3 consecutive same-direction candles c1,c2,c3 where c2's wick sweeps c1's
  extreme and that wick dominates c2's body (>= 2.5x), all non-doji.

    SHORT (3 bear): c1.c<c1.o, c2.c<c2.o, c3.c<c3.o; c2.high>c1.high;
                    upper_wick = c2.high-max(c2.o,c2.c); body=|c2.o-c2.c|;
                    upper_wick >= 2.5*body.
    LONG  (3 bull): mirrored with c2.low<c1.low, lower_wick>=2.5*body.

Trade setup (continuation, after close of c3):
    SHORT: entry = max(c2.o,c2.c) + 0.3*upper_wick   (pull back into wick)
           sl    = c2.high
           tp    = c3.low
    LONG : entry = min(c2.o,c2.c) - 0.3*lower_wick
           sl    = c2.low
           tp    = c3.high
  Canonical RR ~ 1.4 (RR is fixed by tp/sl distances, not a free grid).

Causality / no-lookahead:
  - pattern confirms at close of c3 (= c3_time + TF). Limit-entry scanned on 1m
    strictly AFTER c3 close (arm = c3_time + 2*TF, since c3 opens at c3_time+TF
    and closes at c3_time+2*TF). Fill = first 1m bar where price touches entry.
  - SL/TP scanned on 1m from the FILL bar forward. tie on a bar -> loss.
  - drop signals not filled within MAX_HOLD or filled-but-open.
  - dedup by (confirm_time, direction, round(entry,6)).

NET cost (research/financial/cosim_net.py realistic limit-entry maker model):
    win  RT = 0.05%  (entry maker + TP maker)
    loss RT = 0.10%  (entry maker + SL taker+slip)
    risk_pct = |entry-sl|/entry*100;  cost_R = RT/(risk_pct/100)
    net_R = gross_R - cost_R.
  gross_R per trade: win -> +tp_dist/risk (the realized RR); loss -> -1.

NULL CONTROL: matched random-entry control. For each real signal we keep the
  same side and the same (entry,sl,tp) geometry but start the limit-fill scan at
  a RANDOM bar at a similar forward distance, drawn from the empirical fill-delay
  distribution. 2000 shuffles of the win/loss labels also reported. null_p =
  P(random net_ptt >= real net_ptt).

Run: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_C11.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = {"4h": 240, "8h": 480}
WICK_RATIO = 2.5
ENTRY_FRAC = 0.3
MAX_HOLD_MIN = 30 * 24 * 60   # 30 days
WIN_RT = 0.0005
LOSS_RT = 0.0010
N_SHUFFLE = 5000
RNG = np.random.default_rng(20260623)


def load_1m(sym: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = (df.index.tz_convert("UTC") if df.index.tz
                else df.index.tz_localize("UTC"))
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum",
    }).dropna(subset=["close"])


def detect_signals(df_tf: pd.DataFrame, tf_min: int):
    """Detect run_3candles_sweep on a TF; return list of signal dicts.

    confirm_time = c3_time (the open_time/index of c3 bar). c3 closes at
    c3_time + tf_min. We expose 'arm' = c3_time + 2*tf_min later for the fill
    scan, computed from the index timestamps so it is exact.
    """
    o = df_tf["open"].to_numpy()
    h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy()
    c = df_tf["close"].to_numpy()
    idx = df_tf.index
    n = len(c)
    out = []
    for i in range(2, n):
        i1, i2, i3 = i - 2, i - 1, i
        # all non-doji
        if c[i1] == o[i1] or c[i2] == o[i2] or c[i3] == o[i3]:
            continue
        bear = c[i1] < o[i1] and c[i2] < o[i2] and c[i3] < o[i3]
        bull = c[i1] > o[i1] and c[i2] > o[i2] and c[i3] > o[i3]
        if not (bear or bull):
            continue
        body2 = abs(o[i2] - c[i2])
        if body2 <= 0:
            continue
        if bear:
            # c2 wick sweeps c1 high; upper wick dominates
            if not (h[i2] > h[i1]):
                continue
            upper_wick = h[i2] - max(o[i2], c[i2])
            if upper_wick < WICK_RATIO * body2:
                continue
            entry = max(o[i2], c[i2]) + ENTRY_FRAC * upper_wick
            sl = h[i2]
            tp = l[i3]
            direction = "SHORT"
            # sanity: tp must be below entry, sl above entry
            if not (sl > entry > tp):
                continue
        else:
            if not (l[i2] < l[i1]):
                continue
            lower_wick = min(o[i2], c[i2]) - l[i2]
            if lower_wick < WICK_RATIO * body2:
                continue
            entry = min(o[i2], c[i2]) - ENTRY_FRAC * lower_wick
            sl = l[i2]
            tp = h[i3]
            direction = "LONG"
            if not (sl < entry < tp):
                continue
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        risk_pct = risk / entry * 100.0
        tp_dist = abs(tp - entry)
        out.append({
            "dir": direction,
            "entry": float(entry),
            "sl": float(sl),
            "tp": float(tp),
            "risk": float(risk),
            "risk_pct": float(risk_pct),
            "rr": float(tp_dist / risk),
            "confirm_time": idx[i3],           # c3 open_time
            "tf_min": tf_min,
        })
    return out


def find_fill(rec, lo1, hi1, idx1, n1):
    """Limit fill: first 1m bar at/after c3 close where price touches entry.

    arm = c3_time + 2*tf_min  (c3 closes at c3_time + tf_min for label=left,
    closed=left bars; the bar AFTER c3 opens at c3_time + 2*tf_min). We start the
    scan strictly after c3 close -> no entry/confirm-bar lookahead.
    """
    arm = rec["confirm_time"] + pd.Timedelta(minutes=2 * rec["tf_min"])
    sp = int(idx1.searchsorted(arm, side="left"))
    if sp >= n1:
        return -1, sp, sp
    end = min(sp + MAX_HOLD_MIN, n1)
    if rec["dir"] == "LONG":
        hit = np.where(lo1[sp:end] <= rec["entry"])[0]
    else:
        hit = np.where(hi1[sp:end] >= rec["entry"])[0]
    if hit.size == 0:
        return -1, sp, end
    return sp + int(hit[0]), sp, end


def resolve(rec, f, end, lo1, hi1):
    """From fill bar f forward, did TP or SL hit first? tie -> loss."""
    plo = lo1[f:end]
    phi = hi1[f:end]
    if rec["dir"] == "LONG":
        sl_m = plo <= rec["sl"]
        tp_m = phi >= rec["tp"]
    else:
        sl_m = phi >= rec["sl"]
        tp_m = plo <= rec["tp"]
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
    if sl_first == 10**9 and tp_first == 10**9:
        return "open"
    return "loss" if sl_first <= tp_first else "win"


def net_R(gross_r, risk_pct):
    rt = WIN_RT if gross_r > 0 else LOSS_RT
    cost = rt / (risk_pct / 100.0)
    return gross_r - cost


def main():
    all_trades = []          # closed trades, pooled
    per_asset = {a: [] for a in SYMBOLS}
    fill_delays = []         # bars from arm-sp to fill, for null distance model
    n_sig_total = 0
    n_nofill = 0
    n_open = 0

    for sym in SYMBOLS:
        print(f"loading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        lo1 = df_1m["low"].to_numpy()
        hi1 = df_1m["high"].to_numpy()
        idx1 = df_1m.index
        n1 = len(lo1)

        sigs = []
        for freq, tf_min in TFS.items():
            df_tf = resample(df_1m, freq)
            s = detect_signals(df_tf, tf_min)
            sigs.extend(s)
            print(f"  {sym} {freq}: {len(s)} raw signals", flush=True)

        # dedup by (confirm_time, direction, round(entry,6))
        seen = set()
        deduped = []
        for s in sorted(sigs, key=lambda r: (r["confirm_time"], r["dir"])):
            key = (s["confirm_time"].value, s["dir"], round(s["entry"], 6))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        n_sig_total += len(deduped)
        print(f"  {sym} deduped: {len(deduped)} signals", flush=True)

        for rec in deduped:
            f, sp, end = find_fill(rec, lo1, hi1, idx1, n1)
            if f < 0:
                n_nofill += 1
                continue
            outcome = resolve(rec, f, end, lo1, hi1)
            if outcome == "open":
                n_open += 1
                continue
            gross_r = rec["rr"] if outcome == "win" else -1.0
            nr = net_R(gross_r, rec["risk_pct"])
            fill_delays.append(f - sp)
            t = {
                "asset": sym, "dir": rec["dir"], "outcome": outcome,
                "gross_r": gross_r, "net_r": nr, "risk_pct": rec["risk_pct"],
                "rr": rec["rr"], "month": rec["confirm_time"].strftime("%Y-%m"),
                "f": f, "sp": sp, "end": end, "rec": rec,
                "confirm_time": rec["confirm_time"],
            }
            all_trades.append(t)
            per_asset[sym].append(t)

    n_closed = len(all_trades)
    if n_closed == 0:
        print(json.dumps({"ran_ok": True, "n_closed": 0,
                          "verdict": "no-signal"}))
        return {"ran_ok": True, "n_closed": 0}

    gross_arr = np.array([t["gross_r"] for t in all_trades])
    net_arr = np.array([t["net_r"] for t in all_trades])
    wins = sum(1 for t in all_trades if t["outcome"] == "win")
    wr = wins / n_closed * 100.0
    gross_ptt = float(gross_arr.mean())
    net_ptt = float(net_arr.mean())
    mean_rr = float(np.mean([t["rr"] for t in all_trades]))

    print("\n" + "=" * 78)
    print("C11 run_3candles_sweep — pooled BTC+ETH+SOL, 4h+8h")
    print("=" * 78)
    print(f"signals(deduped)={n_sig_total}  no_fill={n_nofill}  open={n_open}  "
          f"closed={n_closed}")
    print(f"WR={wr:.2f}%  gross_ptt={gross_ptt:+.4f}R  net_ptt={net_ptt:+.4f}R  "
          f"mean_RR={mean_rr:.2f}  median_risk%={np.median([t['risk_pct'] for t in all_trades]):.3f}")

    # per-asset net_ptt
    per_asset_net = []
    print("\nper-asset:")
    for a in SYMBOLS:
        ts = per_asset[a]
        if ts:
            npt = float(np.mean([t["net_r"] for t in ts]))
            wpa = sum(1 for t in ts if t["outcome"] == "win") / len(ts) * 100
        else:
            npt = 0.0
            wpa = 0.0
        per_asset_net.append({"asset": a, "net_ptt": round(npt, 4), "n": len(ts)})
        print(f"  {a}: n={len(ts)}  WR={wpa:.1f}%  net_ptt={npt:+.4f}R")

    # side distribution
    n_long = sum(1 for t in all_trades if t["dir"] == "LONG")
    print(f"\nside: LONG={n_long}  SHORT={n_closed - n_long}")

    # monthly mean net R (pooled)
    months = {}
    for t in all_trades:
        months.setdefault(t["month"], 0.0)
        months[t["month"]] += t["net_r"]
    monthly_vals = np.array(list(months.values()))
    monthly_mean_R = float(monthly_vals.mean()) if monthly_vals.size else 0.0
    print(f"\nmonthly net R: n_months={monthly_vals.size}  mean={monthly_mean_R:+.4f}  "
          f"pct_pos={100*(monthly_vals>0).mean():.0f}%  worst={monthly_vals.min():+.2f}")

    # ---- NULL CONTROL 1: matched random-entry (same geometry, random TIME) ----
    # For each real trade we keep its SIDE, risk% and RR magnitude, but place a
    # synthetic limit order at a RANDOM bar in the same asset's TF history. The
    # entry is set 1 ATR-ish step away from that bar's close in the limit
    # direction (entry = close*(1 -/+ risk_pct/100/0.3) so the 0.3-into-wick
    # offset is preserved); sl = entry +/- risk_dist; tp = entry +/- RR*risk_dist.
    # Then we do a REAL causal fill+resolve on 1m from that random bar forward.
    # This isolates whether the PATTERN's entry timing beats a random entry of
    # identical geometry. Many reps -> distribution of net_ptt.
    fill_delays = np.array(fill_delays) if fill_delays else np.array([0])
    NREP = 300
    rand_net = []
    # build quick lookup of asset 1m + a TF (4h) bar grid to draw random starts
    asset_arrays = {}
    for sym in SYMBOLS:
        df_1m = load_1m(sym)
        df_tf = resample(df_1m, "4h")
        asset_arrays[sym] = {
            "lo1": df_1m["low"].to_numpy(), "hi1": df_1m["high"].to_numpy(),
            "idx1": df_1m.index, "n1": len(df_1m),
            "tf_close": df_tf["close"].to_numpy(), "tf_idx": df_tf.index,
            "tf_n": len(df_tf),
        }
    # per-asset list of real trades (to draw matched random count per asset)
    real_by_asset = {a: [t for t in all_trades if t["asset"] == a]
                     for a in SYMBOLS}
    for _ in range(NREP):
        nets = []
        for sym in SYMBOLS:
            aa = asset_arrays[sym]
            for t in real_by_asset[sym]:
                rec = t["rec"]
                rp = rec["risk_pct"] / 100.0          # risk fraction
                rr = rec["rr"]
                side = rec["dir"]
                # random TF bar (leave room before the end for resolution)
                bi = int(RNG.integers(0, max(1, aa["tf_n"] - 1)))
                base = aa["tf_close"][bi]
                bar_open = aa["tf_idx"][bi]
                # entry placed pullback-style relative to base close
                if side == "LONG":
                    entry = base * (1.0 - rp)          # limit below
                    sl = entry * (1.0 - rp)            # risk_dist = entry*rp
                    tp = entry * (1.0 + rr * rp)
                else:
                    entry = base * (1.0 + rp)
                    sl = entry * (1.0 + rp)
                    tp = entry * (1.0 - rr * rp)
                # causal fill scan from bar AFTER this random TF bar
                arm = bar_open + pd.Timedelta(minutes=2 * 240)
                sp = int(aa["idx1"].searchsorted(arm, side="left"))
                if sp >= aa["n1"]:
                    continue
                end = min(sp + MAX_HOLD_MIN, aa["n1"])
                lo1, hi1 = aa["lo1"], aa["hi1"]
                if side == "LONG":
                    hit = np.where(lo1[sp:end] <= entry)[0]
                else:
                    hit = np.where(hi1[sp:end] >= entry)[0]
                if hit.size == 0:
                    continue                            # no fill -> drop (like real)
                f2 = sp + int(hit[0])
                rrec = {"dir": side, "sl": sl, "tp": tp}
                o2 = resolve(rrec, f2, end, lo1, hi1)
                if o2 == "open":
                    continue
                risk_pct2 = abs(entry - sl) / entry * 100.0
                gr = rr if o2 == "win" else -1.0
                nets.append(net_R(gr, risk_pct2))
        if nets:
            rand_net.append(np.mean(nets))
    rand_net = np.array(rand_net)
    null_p_rand = float((rand_net >= net_ptt).mean()) if rand_net.size else 1.0

    # ---- NULL CONTROL 2: label shuffle (permute win/loss outcomes) ----
    # Shuffle which trades are wins, keep the realized RR magnitudes & risk_pct
    # attached to each trade, recompute net_ptt. Tests whether the SELECTION of
    # which setups win carries info beyond the base win rate & RR distribution.
    rr_vals = np.array([t["rr"] for t in all_trades])
    rp_vals = np.array([t["risk_pct"] for t in all_trades])
    is_win = np.array([t["outcome"] == "win" for t in all_trades])
    shuf_net = np.empty(N_SHUFFLE)
    for k in range(N_SHUFFLE):
        perm = RNG.permutation(n_closed)
        w = is_win[perm]
        gr = np.where(w, rr_vals, -1.0)
        rt = np.where(gr > 0, WIN_RT, LOSS_RT)
        cost = rt / (rp_vals / 100.0)
        shuf_net[k] = (gr - cost).mean()
    null_p_shuf = float((shuf_net >= net_ptt).mean())

    # combined null_p = the more conservative (larger) of the two
    null_p = max(null_p_rand, null_p_shuf)
    print(f"\nNULL: random-entry p={null_p_rand:.3f} (mean rand net_ptt="
          f"{rand_net.mean():+.4f}, n_reps={rand_net.size})")
    print(f"      label-shuffle p={null_p_shuf:.3f} (mean shuf net_ptt="
          f"{shuf_net.mean():+.4f})")
    print(f"      null_p (conservative max) = {null_p:.3f}")

    # ---- verdict ----
    n_pos_assets = sum(1 for p in per_asset_net if p["net_ptt"] > 0)
    if net_ptt > 0 and null_p < 0.1 and n_pos_assets >= 2:
        verdict = "works"
    elif gross_ptt > 0 and net_ptt <= 0:
        verdict = "cost-killed"
    elif net_ptt > 0 and (null_p >= 0.1 or n_pos_assets < 2):
        verdict = "coin"
    else:
        verdict = "coin"
    print(f"\nVERDICT: {verdict}  (net_ptt>0={net_ptt>0}, null_p<0.1={null_p<0.1}, "
          f"cross-asset {n_pos_assets}/3)")

    result = {
        "cid": "C11", "name": "run-3-candles-sweep (continuation)",
        "ran_ok": True, "n_closed": n_closed,
        "gross_ptt": round(gross_ptt, 4), "net_ptt": round(net_ptt, 4),
        "wr": round(wr, 2),
        "per_asset_net_ptt": per_asset_net,
        "null_p": round(null_p, 4),
        "monthly_mean_R": round(monthly_mean_R, 4),
        "verdict": verdict,
        "mean_rr": round(mean_rr, 3),
        "n_long": n_long, "n_short": n_closed - n_long,
        "null_p_rand": round(null_p_rand, 4), "null_p_shuf": round(null_p_shuf, 4),
    }
    print("\n===JSON_BEGIN===")
    print(json.dumps(result))
    print("===JSON_END===")
    return result


if __name__ == "__main__":
    main()
