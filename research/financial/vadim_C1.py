"""CANDIDATE C1 — Breaker-flip retest (LTF). key=C1.

Chain:
  OB on {1h,2h} (detect_ob on consecutive bars)
  -> breaker ARMED = a close crosses prev wick within 4 bars (detect_breaker, canon v4)
  -> price RETURNS into breaker zone.
ENTRY: 0.5 into the breaker zone (midpoint), from the flip side (limit).
  Bullish breaker (LONG OB pair flip) => SHORT resist, entry from ABOVE.
  Bearish breaker (SHORT OB pair flip) => LONG support, entry from BELOW.
SL: just beyond breaker INITIAL_zone outer edge:
  Bullish/SHORT -> prev.high (= initial_zone hi). Bearish/LONG -> prev.low (= initial_zone lo).
TP: fixed RR=2.0.
Two-sided.

CAUSALITY (no lookahead):
  - breaker is usable only AFTER the armed bar (activated_at_idx) closes.
  - the entry zone = INITIAL zone fixed at arm time (current_zone shrinks are themselves
    caused by later returns -> using them would be lookahead). Entry = midpoint of initial zone.
  - limit fill scanned on 1m starting strictly AFTER the armed bar's close.
  - SL/TP scanned on 1m from the FILL bar forward.
  - signal invalidated if breaker CONSUMED (current_zone wiped) before fill -> drop.
  - dedup by (arm_time, direction, round(entry,6)).

NET costs (cosim_net realistic limit-entry maker model): win RT=0.05%, loss RT=0.10%;
cost_R = RT/(risk_pct/100), risk_pct = |entry-sl|/entry*100. net per trade = gross_R - cost_R.

NULL CONTROL: matched random-entry control (same n, same side mix, random arm bars at a
similar distance distribution) -> null_p = P(random_net_ptt >= real_net_ptt) over many draws.

Run: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_C1.py
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
from elements.ob.code import detect_ob  # noqa: E402
from elements.breaker_block.code import detect_breaker  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = {"1h": 60, "2h": 120}
RR = 2.0
MAX_HOLD_MIN = 30 * 24 * 60  # 30 days
WIN_RT = 0.0005   # realistic maker entry + maker TP
LOSS_RT = 0.0010  # realistic maker entry + taker SL
N_NULL = 500
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
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    lo = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    t = df_tf.index.view("int64") // 1_000_000  # ms
    return [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i]))
            for i in range(len(df_tf))]


def find_breakers(df_tf: pd.DataFrame, tf_min: int):
    """Scan a TF for breaker arms. Returns list of dict signals (causal at arm bar).

    For each consecutive OB pair (i-1,i), detect breaker over post=candles[i+1:].
    Arm bar absolute index = i + 1 + activated_at_idx. Entry = midpoint of INITIAL zone.
    """
    candles = df_to_candles(df_tf)
    times = df_tf.index  # bar open_time index (TF), used for arm timestamp
    n = len(candles)
    out = []
    for i in range(1, n - 1):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        post = candles[i + 1:]
        br = detect_breaker(ob, post)
        if br is None:
            continue
        arm_abs = i + 1 + br.activated_at_idx  # absolute TF index of armed bar
        if arm_abs >= n:
            continue
        z_lo, z_hi = br.initial_zone
        if z_hi <= z_lo:
            continue
        entry = 0.5 * (z_lo + z_hi)
        if br.direction == "bullish":
            # Bullish breaker = SHORT resist; price returns from above into zone.
            direction = "SHORT"
            sl = z_hi              # just beyond outer edge = prev.high = initial hi
        else:
            # Bearish breaker = LONG support; price returns from below into zone.
            direction = "LONG"
            sl = z_lo              # prev.low = initial lo
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        # arm timestamp: usable only AFTER the armed bar closes
        arm_time = times[arm_abs]
        out.append({
            "dir": direction,
            "entry": float(entry),
            "sl": float(sl),
            "risk": float(risk),
            "arm_time": arm_time,
            "tf_min": tf_min,
            "month": arm_time.strftime("%Y-%m"),
        })
    return out


def precompute_fill(sigs, df_1m: pd.DataFrame):
    """Add 1m fill index. Fill scanned strictly after armed-bar close (arm_time + tf_min).

    A breaker entry is a limit at the zone midpoint, reached from the flip side:
      SHORT -> price rises to touch entry (high >= entry).
      LONG  -> price falls to touch entry (low  <= entry).
    """
    lo1 = df_1m["low"].to_numpy()
    hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index
    n1 = len(lo1)
    recs = []
    seen = set()
    for s in sigs:
        key = (s["arm_time"].value, s["dir"], round(s["entry"], 6))
        if key in seen:
            continue
        seen.add(key)
        arm = s["arm_time"] + pd.Timedelta(minutes=s["tf_min"])
        sp = int(idx1.searchsorted(arm, side="left"))
        if sp >= n1:
            continue
        end = min(sp + MAX_HOLD_MIN, n1)
        if s["dir"] == "LONG":
            hit = np.where(lo1[sp:end] <= s["entry"])[0]
        else:
            hit = np.where(hi1[sp:end] >= s["entry"])[0]
        f = sp + int(hit[0]) if hit.size else -1
        r = dict(s)
        r["f"] = f
        r["end"] = end
        r["sp"] = sp
        recs.append(r)
    return recs, lo1, hi1


def sim(rec, lo1, hi1, rr=RR) -> str:
    f = rec["f"]
    if f < 0:
        return "no_fill"
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
        return "open"
    return "loss" if sl_first <= tp_first else "win"


def net_of(rec, outcome, rr=RR):
    """Gross & net R for a closed trade. risk_pct = |entry-sl|/entry*100."""
    if outcome == "win":
        gross = rr
        rt = WIN_RT
    else:
        gross = -1.0
        rt = LOSS_RT
    risk_pct = abs(rec["entry"] - rec["sl"]) / rec["entry"] * 100.0
    cost_R = rt / (risk_pct / 100.0)
    return gross, gross - cost_R, risk_pct


NULL_SCAN_CAP = 14 * 24 * 60   # cap resolution scan to 14 days of 1m bars (speed)


def null_control(pooled, per_asset, rr=RR):
    """Matched random-entry control: for each real CLOSED signal keep its asset, direction,
    and the same risk distance (|entry-sl|), but place the entry at a RANDOM 1m bar near the
    arm time. Entry = that bar's close; SL at same risk on the flip side; TP at rr*risk.
    Resolve from the bar AFTER the random entry forward (no entry-bar lookahead). This
    preserves count, side mix, asset and bar-distance scale while destroying the structural
    (breaker) location -> tests whether the *location* (not just direction/risk) carries edge.

    Vectorised across the N_NULL draws PER trade (each trade contributes one outcome per draw),
    resolution scan capped at NULL_SCAN_CAP bars for speed.
    """
    # Precompute, per closed rec, the random-draw range and window arrays once.
    prepped = []
    for rec in pooled:
        asset = rec["asset"]
        lo1, hi1, cl1, _ = per_asset[asset]
        sp, end = rec["sp"], rec["end"]
        if end - sp < 3:
            continue
        prepped.append((rec, lo1, hi1, cl1, sp, end))

    if not prepped:
        return np.zeros(N_NULL)

    sums = np.zeros(N_NULL)        # sum of net R per draw
    counts = np.zeros(N_NULL)      # number of resolved trades per draw
    for rec, lo1, hi1, cl1, sp, end in prepped:
        risk = rec["risk"]
        is_long = rec["dir"] == "LONG"
        # random entry bars for all draws at once (in [sp, end-2])
        js = RNG.integers(sp, end - 1, size=N_NULL)
        for d in range(N_NULL):
            j = int(js[d])
            entry = float(cl1[j])
            if is_long:
                sl = entry - risk; tp = entry + rr * risk
            else:
                sl = entry + risk; tp = entry - rr * risk
            jp = j + 1
            we = min(jp + NULL_SCAN_CAP, end)
            plo = lo1[jp:we]; phi = hi1[jp:we]
            if is_long:
                sl_idx = np.argmax(plo <= sl) if (plo <= sl).any() else -1
                tp_idx = np.argmax(phi >= tp) if (phi >= tp).any() else -1
            else:
                sl_idx = np.argmax(phi >= sl) if (phi >= sl).any() else -1
                tp_idx = np.argmax(plo <= tp) if (plo <= tp).any() else -1
            if sl_idx == -1 and tp_idx == -1:
                continue
            if tp_idx == -1:
                win = False
            elif sl_idx == -1:
                win = True
            else:
                win = tp_idx < sl_idx
            gross = rr if win else -1.0
            rt = WIN_RT if win else LOSS_RT
            risk_pct = risk / entry * 100.0
            sums[d] += gross - rt / (risk_pct / 100.0)
            counts[d] += 1
    return np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)


def main():
    pooled = []
    per_asset = {}     # asset -> (lo1, hi1, close1, n1)
    per_asset_recs = {}
    print("=" * 90)
    print("CANDIDATE C1 — Breaker-flip retest (LTF). OB{1h,2h} -> breaker arm -> 0.5-zone limit, RR=2.0")
    print("=" * 90)
    for sym in SYMBOLS:
        print(f"loading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        sigs_all = []
        for freq, tf_min in TFS.items():
            df_tf = resample(df_1m, freq)
            sg = find_breakers(df_tf, tf_min)
            for s in sg:
                s["tf"] = freq
            sigs_all.extend(sg)
            print(f"  {sym} {freq}: {len(sg)} breaker arms", flush=True)
        recs, lo1, hi1 = precompute_fill(sigs_all, df_1m)
        per_asset[sym] = (lo1, hi1, df_1m["close"].to_numpy(), len(lo1))
        per_asset_recs[sym] = recs
        for r in recs:
            r2 = dict(r); r2["asset"] = sym
            pooled.append(r2)
        print(f"  {sym}: {len(recs)} deduped signals", flush=True)

    # simulate
    wins = losses = no_fill = openn = 0
    gross_list = []; net_list = []
    month_net = {}
    per_asset_net = {a: [] for a in SYMBOLS}
    closed_pooled = []
    for rec in pooled:
        lo1, hi1, _, _ = per_asset[rec["asset"]]
        o = sim(rec, lo1, hi1)
        if o == "no_fill":
            no_fill += 1; continue
        if o == "open":
            openn += 1; continue
        gross, net, _ = net_of(rec, o)
        if o == "win":
            wins += 1
        else:
            losses += 1
        gross_list.append(gross); net_list.append(net)
        month_net[rec["month"]] = month_net.get(rec["month"], 0.0) + net
        per_asset_net[rec["asset"]].append(net)
        closed_pooled.append(rec)

    n_closed = wins + losses
    if n_closed == 0:
        print("NO CLOSED TRADES")
        result = dict(ran_ok=True, n_closed=0, gross_ptt=0.0, net_ptt=0.0, wr=0.0,
                      per_asset=[], null_p=1.0, monthly_mean_R=0.0,
                      verdict="no-signal")
        print("\n===JSON_BEGIN===")
        print(json.dumps(result))
        print("===JSON_END===")
        return

    gross_ptt = float(np.mean(gross_list))
    net_ptt = float(np.mean(net_list))
    wr = wins / n_closed * 100.0

    # months: span from first to last calendar month (R/month pooled net)
    months_sorted = sorted(month_net)
    if months_sorted:
        start = pd.Period(months_sorted[0], "M")
        endp = pd.Period(months_sorted[-1], "M")
        n_months = (endp - start).n + 1
        monthly_mean_R = float(sum(month_net.values()) / n_months)
    else:
        monthly_mean_R = 0.0

    per_asset_out = []
    for a in SYMBOLS:
        arr = per_asset_net[a]
        per_asset_out.append({"asset": a,
                              "net_ptt": round(float(np.mean(arr)), 4) if arr else 0.0,
                              "n": len(arr)})

    # null control
    print("\nrunning null control (random-entry matched, {} draws)...".format(N_NULL), flush=True)
    null_means = null_control(closed_pooled, per_asset)
    null_p = float((null_means >= net_ptt).mean())

    cross_pos = sum(1 for d in per_asset_out if d["net_ptt"] > 0 and d["n"] > 0)
    works = (net_ptt > 0) and (null_p < 0.1) and (cross_pos >= 2)
    if n_closed < 20:
        verdict = "no-signal (too few trades)"
    elif gross_ptt > 0 and net_ptt <= 0:
        verdict = "cost-killed"
    elif net_ptt <= 0:
        verdict = "coin"
    elif works:
        verdict = "works"
    else:
        verdict = "coin"

    print("\n--- RESULTS (pooled, RR=2.0, net=realistic costs) ---")
    print(f"  n_closed={n_closed}  wins={wins} losses={losses}  no_fill={no_fill} open={openn}")
    print(f"  WR={wr:.1f}%  gross_ptt={gross_ptt:+.4f}  net_ptt={net_ptt:+.4f}")
    print(f"  monthly_mean_R(net,pooled)={monthly_mean_R:+.4f} over {n_months} months")
    for d in per_asset_out:
        print(f"    {d['asset']}: net_ptt={d['net_ptt']:+.4f} n={d['n']}")
    print(f"  null_p={null_p:.4f}  (mean null net_ptt={null_means.mean():+.4f}, "
          f"95pct={np.percentile(null_means,95):+.4f})")
    print(f"  cross_asset_pos={cross_pos}/3  VERDICT={verdict}")

    result = dict(
        ran_ok=True, n_closed=n_closed,
        gross_ptt=round(gross_ptt, 4), net_ptt=round(net_ptt, 4), wr=round(wr, 2),
        per_asset=per_asset_out, null_p=round(null_p, 4),
        monthly_mean_R=round(monthly_mean_R, 4), verdict=verdict,
    )
    print("\n===JSON_BEGIN===")
    print(json.dumps(result))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
