"""CANDIDATE C7 — ob_liq sweep -> reaction.

Chain spec:
  ob_liq on {4h,12h} (detect_ob_liq; canon OB-pair with explicit LIQ marker:
  prev lower/upper wick > 3x cur wick AND > prev body) ->
  a LATER wick SWEEPS the liq_marker (first-touch from the cur/confirm bar
  forward) -> reaction.
  ENTRY: limit at 0.5 into entry_zone (the wide canon-OB drop/rally area)
         placed AFTER the marker is tapped.
  SL:    beyond prev.low/high (the liq extreme).
  TP:    RR=2.0.  (Two-sided.)

Causality / no-lookahead (hard-won walls):
  - ob_liq pattern confirms at the close of `cur` (the 2nd bar). It is usable
    only from cur's close-time forward.
  - SWEEP detection: scan bars strictly AFTER cur (on the SAME TF) for the
    first bar whose wick enters the liq_marker. That sweep bar's CLOSE time is
    the confirm/arm time of the trade. The sweep itself is detected from the
    sweep bar's extreme (a wick), but we do NOT act inside the sweep bar — the
    entry limit fill is searched on 1m starting strictly AFTER the sweep bar's
    close.
  - Entry is a LIMIT at 0.5 into entry_zone. We wait for 1m price to TOUCH that
    level from (sweep_close + tf) forward.
  - SL/TP scanned on 1m from the FILL bar forward (never the entry/sweep bar).

NET costs (limit-entry maker model, research/financial/cosim_net.py):
  win  RT = 0.05% ;  loss RT = 0.10% ;  cost_R = RT / (risk_pct/100),
  risk_pct = abs(entry-sl)/entry*100 ;  net_R = gross_R - cost_R.

Dedup near-duplicate signals by (sweep_confirm_time, direction, round(entry,6)).

NULL CONTROL: matched random-entry control — same count, same side
distribution, random arm bars on the same TF at a similar bar-distance, same
RR=2.0, same NET cost model. null_p = P(random net_ptt >= real net_ptt) over
N_NULL resamples.

Run: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_C7.py
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "smc-lib"))

from candle import Candle  # noqa: E402
from elements.ob_liq.code import detect_ob_liq  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = {"4h": 240, "12h": 720}
RR = 2.0
MAX_SWEEP_BARS = 60          # how many TF bars forward to look for the sweep
MAX_HOLD_MIN = 30 * 24 * 60  # 30 days to fill + resolve (same as other engines)
WIN_RT = 0.0005              # 0.05% round-turn maker (limit win)
LOSS_RT = 0.0010             # 0.10% round-turn (limit entry + market/slip SL)
N_NULL = 2000
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


def df_to_candles(df_tf: pd.DataFrame) -> list[Candle]:
    o = df_tf["open"].to_numpy()
    h = df_tf["high"].to_numpy()
    lo = df_tf["low"].to_numpy()
    c = df_tf["close"].to_numpy()
    t = df_tf.index
    return [Candle(o[i], h[i], lo[i], c[i], int(t[i].value // 1_000_000))
            for i in range(len(df_tf))]


def find_signals(df_tf: pd.DataFrame, tf_min: int):
    """Return list of raw C7 signals (sweep confirmed) for one TF.

    Each signal:
      dir, entry, sl, risk, sweep_time (confirm/arm time = sweep bar close).
    """
    candles = df_to_candles(df_tf)
    n = len(candles)
    hi = df_tf["high"].to_numpy()
    lo = df_tf["low"].to_numpy()
    times = df_tf.index
    out = []
    for i in range(n - 1):
        prev, cur = candles[i], candles[i + 1]
        ob = detect_ob_liq(prev, cur)
        if ob is None:
            continue
        # liq_marker (narrow ZoI) = ob.zone ; entry_zone (wide) = ob.entry_zone
        lz_lo, lz_hi = min(ob.zone), max(ob.zone)
        ez_lo, ez_hi = min(ob.entry_zone), max(ob.entry_zone)
        # entry = 0.5 into the wide entry_zone (mid of drop/rally area)
        entry = 0.5 * (ez_lo + ez_hi)
        # search forward (bars strictly after cur = index i+2 ..) for the first
        # bar whose wick enters the liq_marker (the sweep / first-touch).
        # cur is at index i+1; scan from i+2.
        start = i + 2
        end = min(start + MAX_SWEEP_BARS, n)
        sweep_idx = -1
        for j in range(start, end):
            if ob.direction == "long":
                # LONG: a later wick sweeps DOWN into [prev.low, cur.low]
                if lo[j] <= lz_hi:   # entered the marker from above (low dips in)
                    sweep_idx = j
                    break
            else:
                # SHORT: a later wick sweeps UP into [cur.high, prev.high]
                if hi[j] >= lz_lo:   # entered the marker from below (high pokes in)
                    sweep_idx = j
                    break
        if sweep_idx < 0:
            continue
        # SL beyond the liq extreme (prev.low for long / prev.high for short)
        if ob.direction == "long":
            direction = "LONG"
            sl = prev.low
            if not (sl < entry):     # sanity: SL must be below entry for long
                continue
        else:
            direction = "SHORT"
            sl = prev.high
            if not (sl > entry):
                continue
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        sweep_time = times[sweep_idx]
        out.append({
            "dir": direction,
            "entry": float(entry),
            "sl": float(sl),
            "risk": float(risk),
            "sweep_time": sweep_time,
            "month": sweep_time.strftime("%Y-%m"),
            "tf_min": tf_min,
        })
    return out


def precompute_fill(recs, df_1m: pd.DataFrame):
    """Attach 1m fill index + end index to each rec (RR-independent).

    Fill scan starts at sweep_time + tf_min (strictly after the sweep bar's
    close) so we never peek inside the sweep bar.
    """
    lo1 = df_1m["low"].to_numpy()
    hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index
    n1 = len(lo1)
    out = []
    seen = set()
    for r in recs:
        key = (r["sweep_time"].value, r["dir"], round(r["entry"], 6))
        if key in seen:
            continue
        seen.add(key)
        arm = r["sweep_time"] + pd.Timedelta(minutes=r["tf_min"])
        sp = int(idx1.searchsorted(arm, side="left"))
        if sp >= n1:
            continue
        end = min(sp + MAX_HOLD_MIN, n1)
        if r["dir"] == "LONG":
            hit = np.where(lo1[sp:end] <= r["entry"])[0]
        else:
            hit = np.where(hi1[sp:end] >= r["entry"])[0]
        f = sp + int(hit[0]) if hit.size else -1
        r2 = dict(r)
        r2["f"] = f
        r2["end"] = end
        out.append(r2)
    return out, lo1, hi1


def sim(rec, rr, lo1, hi1):
    """Return ('win'|'loss'|'no_fill'|'open', gross_R)."""
    f = rec["f"]
    if f < 0:
        return "no_fill", 0.0
    plo = lo1[f:rec["end"]]
    phi = hi1[f:rec["end"]]
    if rec["dir"] == "LONG":
        tp = rec["entry"] + rr * rec["risk"]
        sl_m = plo <= rec["sl"]
        tp_m = phi >= tp
    else:
        tp = rec["entry"] - rr * rec["risk"]
        sl_m = phi >= rec["sl"]
        tp_m = plo <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
    if sl_first == 10**9 and tp_first == 10**9:
        return "open", 0.0
    if sl_first <= tp_first:    # tie -> loss (conservative)
        return "loss", -1.0
    return "win", float(rr)


def net_of(gross_r: float, risk_pct: float) -> float:
    rt = WIN_RT if gross_r > 0 else LOSS_RT
    cost_R = rt / (risk_pct / 100.0)
    return gross_r - cost_R


def build_null_control(closed_recs, per_asset_1m):
    """Matched random-entry control: same count, same side distribution, random
    arm-bars on the same asset+TF at a similar forward distance, same RR/cost.

    For each real closed trade we draw a random arm time (a random 1m bar in the
    asset's history with room to play out), use a random side from the real side
    pool, and a random SL distance drawn from the real risk_pct distribution
    (so risk_pct ~ matched). Returns array of N_NULL mean-net-R draws.
    """
    # Pool real side & risk_pct for matched sampling
    sides = np.array([1 if r["dir"] == "LONG" else -1 for r in closed_recs])
    risk_pcts = np.array([r["risk_pct"] for r in closed_recs])
    n_real = len(closed_recs)
    # group real recs by asset to reuse that asset's 1m arrays
    assets = list({r["asset"] for r in closed_recs})
    means = np.empty(N_NULL)
    # Precompute per-asset usable bar range
    asset_arrays = {}
    for a in assets:
        lo1, hi1, op1 = per_asset_1m[a]
        asset_arrays[a] = (lo1, hi1, op1, len(lo1))
    for k in range(N_NULL):
        nets = np.empty(n_real)
        for t in range(n_real):
            a = closed_recs[t]["asset"]
            lo1, hi1, op1, n1 = asset_arrays[a]
            # random arm bar with at least some room; use up to MAX_HOLD window
            sp = int(RNG.integers(0, n1 - 1))
            end = min(sp + MAX_HOLD_MIN, n1)
            # random matched side & risk
            side = int(sides[RNG.integers(0, n_real)])
            rp = float(risk_pcts[RNG.integers(0, n_real)])
            entry = float(op1[sp])   # enter at the open of the random bar
            risk = entry * rp / 100.0
            plo = lo1[sp:end]
            phi = hi1[sp:end]
            if side == 1:
                tp = entry + RR * risk
                sl = entry - risk
                sl_m = plo <= sl
                tp_m = phi >= tp
            else:
                tp = entry - RR * risk
                sl = entry + risk
                sl_m = phi >= sl
                tp_m = plo <= tp
            sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
            tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
            if sl_first == 10**9 and tp_first == 10**9:
                nets[t] = 0.0   # unresolved -> 0 (rare with 30d window)
                continue
            gross = -1.0 if sl_first <= tp_first else float(RR)
            nets[t] = net_of(gross, rp)
        means[k] = nets.mean()
    return means


def main():
    pooled = []           # closed trades (with net) across assets+TFs
    per_asset_1m = {}      # asset -> (lo1, hi1, open1)
    raw_counts = {}

    for sym in SYMBOLS:
        print(f"loading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        lo1 = df_1m["low"].to_numpy()
        hi1 = df_1m["high"].to_numpy()
        op1 = df_1m["open"].to_numpy()
        per_asset_1m[sym] = (lo1, hi1, op1)
        for tf, tf_min in TFS.items():
            df_tf = resample(df_1m, tf)
            sigs = find_signals(df_tf, tf_min)
            recs, _, _ = precompute_fill(sigs, df_1m)
            raw_counts[(sym, tf)] = (len(sigs), len(recs))
            print(f"  {sym} {tf}: {len(sigs)} raw sweep-signals, "
                  f"{len(recs)} after dedup", flush=True)
            for r in recs:
                o, gross = sim(r, RR, lo1, hi1)
                if o not in ("win", "loss"):
                    continue
                entry, sl = r["entry"], r["sl"]
                risk_pct = abs(entry - sl) / entry * 100.0
                if risk_pct <= 0.05:    # match cosim filter (avoid div blowup)
                    continue
                net = net_of(gross, risk_pct)
                pooled.append({
                    "asset": sym, "tf": tf, "dir": r["dir"],
                    "gross_r": gross, "net_r": net, "risk_pct": risk_pct,
                    "month": r["month"], "outcome": o,
                })

    n_closed = len(pooled)
    print(f"\n=== POOLED CLOSED: {n_closed} ===")
    if n_closed == 0:
        result = {
            "ran_ok": True, "n_closed": 0, "gross_ptt": 0.0, "net_ptt": 0.0,
            "wr": 0.0, "per_asset_net_ptt": [], "null_p": 1.0,
            "monthly_mean_R": 0.0, "verdict": "no-signal",
        }
        print("\n===JSON_BEGIN===")
        print(json.dumps(result))
        print("===JSON_END===")
        return

    gross_arr = np.array([p["gross_r"] for p in pooled])
    net_arr = np.array([p["net_r"] for p in pooled])
    wins = sum(1 for p in pooled if p["outcome"] == "win")
    gross_ptt = float(gross_arr.mean())
    net_ptt = float(net_arr.mean())
    wr = wins / n_closed * 100.0

    # per-asset net ptt
    per_asset = []
    for a in SYMBOLS:
        sub = [p for p in pooled if p["asset"] == a]
        if sub:
            per_asset.append({
                "asset": a,
                "net_ptt": round(float(np.mean([p["net_r"] for p in sub])), 4),
                "n": len(sub),
            })
        else:
            per_asset.append({"asset": a, "net_ptt": 0.0, "n": 0})

    # side distribution
    n_long = sum(1 for p in pooled if p["dir"] == "LONG")
    n_short = n_closed - n_long

    # monthly net R pooled (sum of net per calendar month, then mean)
    month_R = {}
    for p in pooled:
        month_R[p["month"]] = month_R.get(p["month"], 0.0) + p["net_r"]
    m_vals = np.array(list(month_R.values()))
    monthly_mean_R = float(m_vals.mean()) if m_vals.size else 0.0

    # NULL control
    print("running null control...", flush=True)
    null_means = build_null_control(pooled, per_asset_1m)
    null_p = float((null_means >= net_ptt).mean())

    n_assets_pos = sum(1 for pa in per_asset if pa["n"] > 0 and pa["net_ptt"] > 0)

    # verdict
    if net_ptt <= 0 and gross_ptt > 0:
        verdict = "cost-killed"
    elif net_ptt <= 0:
        verdict = "coin"
    elif null_p >= 0.1:
        verdict = "coin"
    elif n_assets_pos < 2:
        verdict = "coin"
    else:
        verdict = "works"

    print(f"gross_ptt={gross_ptt:+.4f}  net_ptt={net_ptt:+.4f}  wr={wr:.1f}%")
    print(f"sides: LONG={n_long} SHORT={n_short}")
    print(f"per_asset: " + ", ".join(
        f"{pa['asset']}={pa['net_ptt']:+.4f}(n={pa['n']})" for pa in per_asset))
    print(f"null_p={null_p:.4f}  (null mean={null_means.mean():+.4f}, "
          f"95p={np.percentile(null_means,95):+.4f})")
    print(f"monthly_mean_R={monthly_mean_R:+.3f}  n_months={m_vals.size}")
    print(f"n_assets_pos={n_assets_pos}  verdict={verdict}")

    result = {
        "ran_ok": True,
        "n_closed": n_closed,
        "gross_ptt": round(gross_ptt, 4),
        "net_ptt": round(net_ptt, 4),
        "wr": round(wr, 2),
        "per_asset_net_ptt": per_asset,
        "null_p": round(null_p, 4),
        "monthly_mean_R": round(monthly_mean_R, 4),
        "verdict": verdict,
        "n_long": n_long, "n_short": n_short,
    }
    print("\n===JSON_BEGIN===")
    print(json.dumps(result))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
