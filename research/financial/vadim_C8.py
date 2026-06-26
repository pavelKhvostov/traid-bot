"""C8 — Fractal-sweep -> i-FVG reclaim. key=C8.

Chain (causal, no lookahead):
  1. HTF fractal on {12h,1d} (Williams N=2). Confirmed only at center+N bars
     (we use the fractal's CONFIRM bar = center index + N, i.e. the bar that
     closes the 2N+1 window). Level is known only from confirm onward.
  2. Fractal SWEPT: a later HTF bar wicks past the level (FH: high>level;
     FL: low<level). Sweep = liquidity grab -> expect reversal.
       FH swept (liquidity above)  -> reversal SHORT.
       FL swept (liquidity below)  -> reversal LONG.
  3. An i-FVG (detect_i_fvg, canon v2) forms on {4h,6h} at/near the sweep,
     with i-FVG.direction matching the reversal direction (SHORT after FH,
     LONG after FL). "At/near": the i-FVG arm bar (B.c3 close) is within a
     window after the sweep bar AND the overlap ZoI is within NEAR_PCT of the
     swept fractal level.
  4. ENTRY: 0.5 into ifvg.overlap (mid of ZoI). LIMIT fill: wait for price to
     TOUCH that level from the i-FVG ARM bar forward (strictly after arm),
     scanned on 1m.
  5. SL: beyond the swept fractal level (plus a small buffer in risk units of
     the zone): LONG sl = fractal_level - buf ; SHORT sl = fractal_level + buf.
     buf = ZoI half-width (so SL sits clearly beyond the swept low/high).
  6. TP: next liquidity = the nearest OPPOSITE-direction HTF fractal level
     beyond entry in the trade direction, known causally (confirmed before the
     i-FVG arm). If none -> RR=2.0.

Costs: limit-entry maker model (research/financial/cosim_net.py):
  win RT=0.05%, loss RT=0.10%; cost_R = RT/(risk_pct/100),
  risk_pct = abs(entry-sl)/entry*100. net_R = gross_R - cost_R.

Null control: matched random-entry control. For each real trade we keep its
direction, entry-distance-from-arm-price, risk and RR, but pick a RANDOM arm
bar in the asset's history and re-derive entry/sl at the same relative geometry,
then simulate. Repeat N_NULL times; null_p = P(random_mean_netR >= real_netR).

Run: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_C8.py
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
from elements.i_fvg.code import detect_i_fvg  # noqa: E402
from elements.fractal.code import detect_fractal  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
HTF_TFS = [("12h", 720), ("1d", 1440)]      # fractal TFs
LTF_TFS = [("4h", 240), ("6h", 360)]        # i-FVG TFs
FRACTAL_N = 2
RR_DEFAULT = 2.0
MAX_HOLD_MIN = 30 * 24 * 60                  # 30 days
SWEEP_WINDOW_MIN = 14 * 24 * 60              # i-FVG must arm within 14d of sweep
SWEEP_LOOKAHEAD_HTF_BARS = 60               # how far ahead (in HTF bars) to look for a sweep of a fractal
NEAR_PCT = 3.0                              # i-FVG ZoI within 3% of swept fractal level
IFVG_MAX_BETWEEN = 80                       # cap candles between A.c3 and B.c1 (perf + canon-sane)
WIN_RT = 0.0005
LOSS_RT = 0.0010
N_NULL = 400
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


def df_to_candles(df: pd.DataFrame) -> list[Candle]:
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    lo = df["low"].to_numpy(); c = df["close"].to_numpy()
    ts = (df.index.view("int64") // 1_000_000)  # ms
    return [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(ts[i]))
            for i in range(len(df))]


# ---------------------------------------------------------------------------
# Step 1+2: HTF fractals + their sweeps (causal)
# ---------------------------------------------------------------------------
def htf_fractals_with_sweeps(df_htf: pd.DataFrame):
    """Return list of dicts for each fractal that gets swept.

    Each: {dir_swept('SHORT'|'LONG'), level, confirm_time, sweep_time,
           opp_levels_known: list[(time,level)] of opposite fractals confirmed
           before sweep -> for TP 'next liquidity'}.
    confirm_time = open_time of the bar at center+N (window-closing bar).
    sweep_time   = open_time of the HTF bar that swept the level.
    """
    candles = df_to_candles(df_htf)
    times = df_htf.index
    n = len(candles)
    N = FRACTAL_N
    # detect all confirmed fractals: center i in [N, n-N-1], confirm bar = i+N
    fr = []  # (confirm_idx, center_idx, direction('high'|'low'), level)
    for ci in range(N, n - N):
        f = detect_fractal(candles[ci - N: ci + N + 1], n=N)
        if f is None:
            continue
        fr.append((ci + N, ci, f.direction, f.level))
    fr.sort(key=lambda x: x[0])

    hi = df_htf["high"].to_numpy()
    lo = df_htf["low"].to_numpy()

    out = []
    for confirm_idx, center_idx, direction, level in fr:
        # sweep search starts strictly AFTER confirm bar
        start = confirm_idx + 1
        end = min(start + SWEEP_LOOKAHEAD_HTF_BARS, n)
        sweep_idx = None
        for j in range(start, end):
            if direction == "high" and hi[j] > level:
                sweep_idx = j
                break
            if direction == "low" and lo[j] < level:
                sweep_idx = j
                break
        if sweep_idx is None:
            continue
        dir_swept = "SHORT" if direction == "high" else "LONG"
        # opposite fractals confirmed strictly before the sweep bar -> TP liquidity
        opp_dir = "low" if direction == "high" else "high"
        opp = [(times[c_idx_], lev) for (cf, c_idx_, d, lev) in fr
               if d == opp_dir and cf < sweep_idx]
        out.append({
            "dir": dir_swept,
            "level": float(level),
            "confirm_time": times[confirm_idx],
            "sweep_time": times[sweep_idx],
            "opp_levels": opp,
        })
    return out


# ---------------------------------------------------------------------------
# Step 3: i-FVG on LTF (causal scan)
# ---------------------------------------------------------------------------
def ltf_ifvgs(df_ltf: pd.DataFrame):
    """All i-FVGs on this LTF. arm_time = B.c3 open_time (armed at its close).

    Returns list of dicts: {dir('LONG'|'SHORT'), overlap(lo,hi), arm_time,
                            arm_idx}. arm_idx = index of B.c3 in df_ltf.
    """
    candles = df_to_candles(df_ltf)
    times = df_ltf.index
    n = len(candles)
    out = []
    # FVG-A at (i, i+1, i+2); FVG-B at (j, j+1, j+2) with j > i+2 (B.c1 after A.c3)
    # between = candles[i+3 .. j-1]. Cap |between| for perf.
    # Detect all simple FVGs first as candidates.
    fvg_idx = []  # i where (i,i+1,i+2) is an FVG, with direction
    hi = df_ltf["high"].to_numpy(); lo = df_ltf["low"].to_numpy()
    for i in range(n - 2):
        c1h, c3l = hi[i], lo[i + 2]
        c1l, c3h = lo[i], hi[i + 2]
        if c1h < c3l:
            fvg_idx.append((i, "long"))
        elif c1l > c3h:
            fvg_idx.append((i, "short"))
    # for each A, pair with later B of opposite direction within between cap
    for ai, (i, a_dir) in enumerate(fvg_idx):
        a_c3 = i + 2
        for (j, b_dir) in fvg_idx[ai + 1:]:
            if b_dir == a_dir:
                continue
            if j <= a_c3:           # B.c1 must be after A.c3
                continue
            between_n = j - (a_c3 + 1)
            if between_n < 0:
                continue
            if between_n > IFVG_MAX_BETWEEN:
                break               # fvg_idx sorted by i -> further j only larger
            between = tuple(candles[a_c3 + 1: j])
            ifvg = detect_i_fvg(
                candles[i], candles[i + 1], candles[i + 2],
                between,
                candles[j], candles[j + 1], candles[j + 2],
            )
            if ifvg is None:
                continue
            arm_idx = j + 2  # B.c3
            out.append({
                "dir": "LONG" if ifvg.direction == "long" else "SHORT",
                "overlap": (float(ifvg.overlap[0]), float(ifvg.overlap[1])),
                "arm_time": times[arm_idx],
                "arm_idx": arm_idx,
            })
    return out


# ---------------------------------------------------------------------------
# Build C8 signals (combine sweep + i-FVG)
# ---------------------------------------------------------------------------
def build_signals(df_1m, htf_resampled, ltf_resampled):
    """Combine HTF fractal sweeps with LTF i-FVGs into C8 signals."""
    sweeps = []
    for tf, _m in HTF_TFS:
        sweeps += htf_fractals_with_sweeps(htf_resampled[tf])
    ifvgs = []
    for tf, m in LTF_TFS:
        for z in ltf_ifvgs(ltf_resampled[tf]):
            z["tf"] = tf; z["tf_min"] = m
            ifvgs.append(z)

    sigs = []
    seen = set()
    for z in ifvgs:
        zlo, zhi = z["overlap"]
        zmid = 0.5 * (zlo + zhi)
        # find a matching sweep: same direction, sweep_time <= arm_time,
        # arm within SWEEP_WINDOW, ZoI near the swept fractal level.
        best = None
        for s in sweeps:
            if s["dir"] != z["dir"]:
                continue
            if s["sweep_time"] > z["arm_time"]:
                continue
            dt_min = (z["arm_time"] - s["sweep_time"]).total_seconds() / 60.0
            if dt_min > SWEEP_WINDOW_MIN:
                continue
            near = abs(zmid - s["level"]) / s["level"] * 100.0
            if near > NEAR_PCT:
                continue
            # most recent sweep before arm wins (smallest dt)
            if best is None or dt_min < best[0]:
                best = (dt_min, s, near)
        if best is None:
            continue
        _dt, s, near = best
        flevel = s["level"]
        zhw = 0.5 * (zhi - zlo)             # ZoI half-width = SL buffer beyond fractal
        entry = zmid
        if z["dir"] == "LONG":
            sl = flevel - zhw
            if sl >= entry:                 # malformed geometry
                continue
        else:
            sl = flevel + zhw
            if sl <= entry:
                continue
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        # TP: next liquidity = nearest opposite fractal level beyond entry in trade dir
        tp = None
        if z["dir"] == "LONG":
            cands = [lev for (_t, lev) in s["opp_levels"] if lev > entry + 0.1 * risk]
            if cands:
                tp = min(cands)             # nearest above
        else:
            cands = [lev for (_t, lev) in s["opp_levels"] if lev < entry - 0.1 * risk]
            if cands:
                tp = max(cands)             # nearest below
        rr_used = None
        if tp is not None:
            rr_used = abs(tp - entry) / risk
            if rr_used < 0.3:               # too close -> fall back to RR_DEFAULT
                tp = None
        if tp is None:
            if z["dir"] == "LONG":
                tp = entry + RR_DEFAULT * risk
            else:
                tp = entry - RR_DEFAULT * risk
            rr_used = RR_DEFAULT

        key = (z["arm_time"].value, z["dir"], round(entry, 6))
        if key in seen:
            continue
        seen.add(key)
        sigs.append({
            "dir": z["dir"], "entry": entry, "sl": sl, "tp": tp, "risk": risk,
            "rr_used": rr_used, "arm_time": z["arm_time"], "arm_idx_tf": z["arm_idx"],
            "tf": z["tf"], "tf_min": z["tf_min"],
            "month": z["arm_time"].strftime("%Y-%m"),
            "flevel": flevel, "near": near,
        })
    return sigs


# ---------------------------------------------------------------------------
# Simulate one trade on 1m (limit fill from arm forward, SL/TP from fill forward)
# ---------------------------------------------------------------------------
def simulate(sig, lo1, hi1, idx1):
    n1 = len(lo1)
    # fill scan starts strictly AFTER the arm bar close.
    arm = sig["arm_time"] + pd.Timedelta(minutes=sig["tf_min"])
    sp = int(idx1.searchsorted(arm, side="left"))
    if sp >= n1:
        return None
    end = min(sp + MAX_HOLD_MIN, n1)
    if sig["dir"] == "LONG":
        hit = np.where(lo1[sp:end] <= sig["entry"])[0]
    else:
        hit = np.where(hi1[sp:end] >= sig["entry"])[0]
    if hit.size == 0:
        return None  # not filled
    f = sp + int(hit[0])
    plo = lo1[f:end]; phi = hi1[f:end]
    if sig["dir"] == "LONG":
        sl_m = plo <= sig["sl"]; tp_m = phi >= sig["tp"]
    else:
        sl_m = phi >= sig["sl"]; tp_m = plo <= sig["tp"]
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
    if sl_first == 10**9 and tp_first == 10**9:
        return None  # open at horizon -> drop
    win = tp_first < sl_first  # tie -> loss (sl_first <= tp_first => loss)
    gross_r = sig["rr_used"] if win else -1.0
    risk_pct = abs(sig["entry"] - sig["sl"]) / sig["entry"] * 100.0
    rt = WIN_RT if win else LOSS_RT
    cost_r = rt / (risk_pct / 100.0)
    net_r = gross_r - cost_r
    return {"win": win, "gross_r": gross_r, "net_r": net_r,
            "risk_pct": risk_pct, "month": sig["month"], "dir": sig["dir"],
            "rr_used": sig["rr_used"]}


# ---------------------------------------------------------------------------
# Null control: matched random-entry. Same dir, same RR, same risk_pct, random arm bar.
# ---------------------------------------------------------------------------
def null_trade(real, lo1, hi1, idx1, close1, n1):
    """Pick a random 1m bar; build a trade with same dir/rr_used/risk_pct."""
    # random arm bar with room for MAX_HOLD
    sp = int(RNG.integers(0, max(1, n1 - 1)))
    end = min(sp + MAX_HOLD_MIN, n1)
    if end - sp < 100:
        return None
    px = close1[sp]
    risk = px * (real["risk_pct"] / 100.0)
    if real["dir"] == "LONG":
        entry = px; sl = entry - risk; tp = entry + real["rr_used"] * risk
        plo = lo1[sp:end]; phi = hi1[sp:end]
        sl_m = plo <= sl; tp_m = phi >= tp
    else:
        entry = px; sl = entry + risk; tp = entry - real["rr_used"] * risk
        plo = lo1[sp:end]; phi = hi1[sp:end]
        sl_m = phi >= sl; tp_m = plo <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
    if sl_first == 10**9 and tp_first == 10**9:
        return None
    win = tp_first < sl_first
    gross_r = real["rr_used"] if win else -1.0
    rt = WIN_RT if win else LOSS_RT
    cost_r = rt / (real["risk_pct"] / 100.0)
    return gross_r - cost_r


def main():
    pooled_results = []          # closed real trades (dicts)
    per_asset = {a: [] for a in SYMBOLS}
    asset_1m = {}                # asset -> (lo,hi,idx,close,n)

    for sym in SYMBOLS:
        print(f"loading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        htf_r = {tf: resample(df_1m, tf) for tf, _ in HTF_TFS}
        ltf_r = {tf: resample(df_1m, tf) for tf, _ in LTF_TFS}
        sigs = build_signals(df_1m, htf_r, ltf_r)
        print(f"  {sym}: {len(sigs)} C8 signals (deduped)", flush=True)

        lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
        close1 = df_1m["close"].to_numpy(); idx1 = df_1m.index; n1 = len(lo1)
        asset_1m[sym] = (lo1, hi1, idx1, close1, n1)

        for sig in sigs:
            r = simulate(sig, lo1, hi1, idx1)
            if r is None:
                continue
            r["asset"] = sym
            pooled_results.append(r)
            per_asset[sym].append(r)

    n_closed = len(pooled_results)
    if n_closed == 0:
        print(json.dumps({"ran_ok": True, "n_closed": 0, "verdict": "no-signal"}))
        return None

    gross = np.array([r["gross_r"] for r in pooled_results])
    net = np.array([r["net_r"] for r in pooled_results])
    wins = sum(r["win"] for r in pooled_results)
    gross_ptt = float(gross.mean())
    net_ptt = float(net.mean())
    wr = wins / n_closed * 100.0

    # per-asset net ptt
    per_asset_net = []
    for a in SYMBOLS:
        rs = per_asset[a]
        if rs:
            per_asset_net.append({"asset": a,
                                  "net_ptt": round(float(np.mean([r["net_r"] for r in rs])), 4),
                                  "n": len(rs)})
        else:
            per_asset_net.append({"asset": a, "net_ptt": 0.0, "n": 0})

    # monthly mean R (net, pooled)
    month_R = {}
    for r in pooled_results:
        month_R[r["month"]] = month_R.get(r["month"], 0.0) + r["net_r"]
    monthly_mean_R = float(np.mean(list(month_R.values()))) if month_R else 0.0

    # ---- NULL control ----
    null_means = []
    for _k in range(N_NULL):
        vals = []
        for r in pooled_results:
            lo1, hi1, idx1, close1, n1 = asset_1m[r["asset"]]
            nv = null_trade(r, lo1, hi1, idx1, close1, n1)
            if nv is not None:
                vals.append(nv)
        if vals:
            null_means.append(float(np.mean(vals)))
    null_means = np.array(null_means)
    null_p = float((null_means >= net_ptt).mean()) if null_means.size else 1.0

    n_assets_pos = sum(1 for d in per_asset_net if d["net_ptt"] > 0 and d["n"] > 0)
    works = (net_ptt > 0) and (null_p < 0.1) and (n_assets_pos >= 2)
    if n_closed < 15:
        verdict = "no-signal"
    elif works:
        verdict = "works"
    elif net_ptt <= 0 and gross_ptt > 0:
        verdict = "cost-killed"
    else:
        verdict = "coin"

    out = {
        "cid": "C8",
        "name": "Fractal-sweep -> i-FVG reclaim",
        "ran_ok": True,
        "n_closed": n_closed,
        "gross_ptt": round(gross_ptt, 4),
        "net_ptt": round(net_ptt, 4),
        "wr": round(wr, 2),
        "per_asset_net_ptt": per_asset_net,
        "null_p": round(null_p, 4),
        "monthly_mean_R": round(monthly_mean_R, 4),
        "null_mean": round(float(null_means.mean()), 4) if null_means.size else None,
        "verdict": verdict,
        "n_months": len(month_R),
    }
    print("\n===JSON_BEGIN===")
    print(json.dumps(out))
    print("===JSON_END===")
    return out


if __name__ == "__main__":
    main()
