"""Financial backtest — CANDIDATE C3: Mitigation-block flip (HTF). cid=C3.

Chain spec:
  OB on {4h,6h,12h} fully broken + Rule-1 (1 breakout bar + 3 confirming bars
  beyond the broken level) arms a Mitigation Block (detect_mitigation_block /
  scan_mitigation_blocks). Price then RETURNS to the former OB area, now role-FLIPPED:
    - Bearish MB (LONG OB broken DOWN)  -> former support becomes RESISTANCE -> SHORT setup
    - Bullish MB (SHORT OB broken UP)   -> former resistance becomes SUPPORT  -> LONG  setup

ENTRY: limit at 0.3 INTO mb.zone (from the side price approaches):
  - SHORT (bearish MB, price returns from below): entry = zone_lo + 0.30*(zone_hi-zone_lo)
  - LONG  (bullish MB, price returns from above): entry = zone_hi - 0.30*(zone_hi-zone_lo)
SL: beyond the FAR edge of mb.zone (invalidation = close back through broken_level):
  - SHORT: sl = zone_hi  (above resistance)
  - LONG : sl = zone_lo  (below support)
TP: RR = 2.0.  Reversal, two-sided.

Causality / NO lookahead (hard-won walls):
  - MB armed at post-bar index armed_at_idx (= confirm_idxs[-1]); its global HTF bar
    index = i_cur + 1 + armed_at_idx. The MB is only USABLE after that confirm bar CLOSES.
  - Entry is a LIMIT fill: scan 1m bars STRICTLY AFTER the arm bar closes for the first
    touch of the entry level (from confirm bar forward). The return must come from the
    correct side (we require price to first be outside the zone on the approach side,
    which is guaranteed: the breakout pushed price beyond broken_level / out of the zone).
  - SL/TP scanned on 1m from the FILL bar forward (never the entry/arm bar).
  - Dedup by (arm_time, direction, round(entry,6)).

NET costs (limit-entry maker model, research/financial/cosim_net.py, realistic 0.05/0.10):
  cost_R = RT(side)/(risk_pct/100), risk_pct = abs(entry-sl)/entry*100.
  net_R = gross_R - cost_R - funding(0.0001/8h * hold/8 / (risk_pct/100)).

NULL control: matched random-entry control — same count, same side distribution, random
  HTF bar at a similar forward distance, same entry/SL geometry derived from a random
  swing of comparable size; compute net_ptt over many draws; null_p = P(rand >= real).

Run: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_C3.py
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
SMC = ROOT / "smc-lib"
for p in (str(ROOT), str(SMC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob  # noqa: E402
from elements.mitigation_block.code import detect_mitigation_block  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
HTF_LIST = [("4h", 240), ("6h", 360), ("12h", 720)]
RR = 2.0
ENTRY_FRAC = 0.30
MAX_BARS_TO_BREAKOUT = 30
MAX_HOLD_MIN = 30 * 24 * 60          # 30 days to fill or to resolve
RETURN_WINDOW_BARS = 60              # HTF bars after arm within which the return-fill must occur
WIN_RT, LOSS_RT = 0.0005, 0.0010     # realistic limit-entry maker model
FUND_8H = 0.0001
RNG_SEED = 12345
N_NULL = 2000


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


def to_candles(df_tf: pd.DataFrame) -> list[Candle]:
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    t = df_tf.index.view("int64") // 10**6  # ms
    return [Candle(float(o[i]), float(h[i]), float(l[i]), float(c[i]), int(t[i]))
            for i in range(len(df_tf))]


def scan_mbs(candles: list[Candle], df_tf: pd.DataFrame, tf_min: int):
    """Yield armed Mitigation Blocks with a real arm timestamp (causal).

    For each (i-1, i) OB candidate, detect MB on post bars. armed_at_idx indexes
    post_bars = candles[i+1:], so the global HTF bar index of the arm bar is
    i + 1 + armed_at_idx. The arm bar's close time = arm bar open_time + tf_min.
    """
    out = []
    n = len(candles)
    times = df_tf.index  # tz-aware UTC, bar OPEN times
    for i in range(1, n - 4):
        ob = detect_ob(candles[i - 1], candles[i])
        if ob is None:
            continue
        post = candles[i + 1:]
        mb = detect_mitigation_block(ob, post, MAX_BARS_TO_BREAKOUT)
        if mb is None:
            continue
        arm_global = i + 1 + mb.armed_at_idx
        if arm_global >= n:
            continue
        # arm CONFIRMS when the arm bar CLOSES => usable from arm bar close onward
        arm_close_time = times[arm_global] + pd.Timedelta(minutes=tf_min)
        zlo, zhi = mb.zone
        if zhi <= zlo:
            continue
        if mb.direction == "bearish":   # resistance -> SHORT
            direction = "SHORT"
            entry = zlo + ENTRY_FRAC * (zhi - zlo)
            sl = zhi
        else:                            # bullish -> support -> LONG
            direction = "LONG"
            entry = zhi - ENTRY_FRAC * (zhi - zlo)
            sl = zlo
        risk = abs(entry - sl)
        if risk <= 0 or entry <= 0:
            continue
        out.append({
            "direction": direction,
            "entry": float(entry),
            "sl": float(sl),
            "risk": float(risk),
            "arm_global": arm_global,
            "arm_close_time": arm_close_time,
            "month": arm_close_time.strftime("%Y-%m"),
        })
    return out


def precompute_fills(recs, df_tf: pd.DataFrame, df_1m: pd.DataFrame, tf_min: int):
    """For each MB, find the LIMIT fill bar on 1m strictly after the arm bar closes,
    within RETURN_WINDOW_BARS HTF bars. Dedup by (arm_close_time, dir, round(entry,6))."""
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index
    n1 = len(lo1)
    out = []
    seen = set()
    for r in recs:
        key = (r["arm_close_time"].value, r["direction"], round(r["entry"], 6))
        if key in seen:
            continue
        seen.add(key)
        # fill scan begins strictly after the arm bar closes (no arm-bar lookahead)
        start_t = r["arm_close_time"]
        sp = int(idx1.searchsorted(start_t, side="left"))
        if sp >= n1:
            continue
        # return must come within RETURN_WINDOW_BARS HTF bars after arm
        ret_deadline = start_t + pd.Timedelta(minutes=tf_min * RETURN_WINDOW_BARS)
        fp_cap = int(idx1.searchsorted(ret_deadline, side="left"))
        fp_cap = min(fp_cap, n1)
        if fp_cap <= sp:
            continue
        if r["direction"] == "LONG":
            hit = np.where(lo1[sp:fp_cap] <= r["entry"])[0]
        else:
            hit = np.where(hi1[sp:fp_cap] >= r["entry"])[0]
        if hit.size == 0:
            continue  # never returned to entry within window -> no trade
        f = sp + int(hit[0])
        end = min(f + MAX_HOLD_MIN, n1)
        rec = dict(r)
        rec["f"] = f
        rec["end"] = end
        out.append(rec)
    return out, lo1, hi1


def sim_one(rec, lo1, hi1):
    """Return (outcome, gross_R, hold_hours). outcome in {'win','loss','open'}."""
    f = rec["f"]
    plo = lo1[f:rec["end"]]
    phi = hi1[f:rec["end"]]
    entry, sl, risk = rec["entry"], rec["sl"], rec["risk"]
    if rec["direction"] == "LONG":
        tp = entry + RR * risk
        sl_m = plo <= sl
        tp_m = phi >= tp
    else:
        tp = entry - RR * risk
        sl_m = phi >= sl
        tp_m = plo <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
    if sl_first == 10**9 and tp_first == 10**9:
        return "open", 0.0, 0.0
    # tie on a bar -> loss (conservative)
    if sl_first <= tp_first:
        return "loss", -1.0, (sl_first + 1) / 60.0
    return "win", RR, (tp_first + 1) / 60.0


def net_R(gross_r, risk_pct, hold_hours):
    rt = WIN_RT if gross_r > 0 else LOSS_RT
    cost = rt / (risk_pct / 100.0)
    hh = hold_hours if (np.isfinite(hold_hours) and hold_hours > 0) else 24.0
    fund = FUND_8H * (hh / 8.0) / (risk_pct / 100.0)
    return gross_r - cost - fund


def run_asset(sym: str):
    """Pool all 3 HTFs for one asset. Returns list of closed-trade dicts."""
    df_1m = load_1m(sym)
    trades = []
    for freq, tf_min in HTF_LIST:
        df_tf = resample(df_1m, freq)
        candles = to_candles(df_tf)
        recs = scan_mbs(candles, df_tf, tf_min)
        filled, lo1, hi1 = precompute_fills(recs, df_tf, df_1m, tf_min)
        for rec in filled:
            outcome, gross, hold = sim_one(rec, lo1, hi1)
            if outcome == "open":
                continue
            risk_pct = abs(rec["entry"] - rec["sl"]) / rec["entry"] * 100.0
            nr = net_R(gross, risk_pct, hold)
            trades.append({
                "asset": sym, "tf": freq, "direction": rec["direction"],
                "month": rec["month"], "gross_r": gross, "net_r": nr,
                "risk_pct": risk_pct, "win": 1 if gross > 0 else 0,
                "arm_close_time": rec["arm_close_time"], "f": rec["f"],
            })
        print(f"  {sym} {freq}: {len(recs)} MBs armed -> {len(filled)} filled "
              f"-> {sum(1 for t in trades if t['tf']==freq)} closed", flush=True)
    return trades


def null_control(all_trades, per_asset_1m, rng):
    """Matched random-entry control: same count, same side distribution, random HTF bar
    at a similar forward distance, entry/SL geometry from a random swing of comparable size.

    For each real trade we keep its direction and risk_pct (zone half-life is fixed by spec),
    but pick a RANDOM arm bar time on the same asset's 1m series and re-derive a random
    swing-based entry/SL with the SAME risk_pct, then simulate the identical RR=2.0 outcome.
    null_p = P(mean random net_ptt >= real net_ptt)."""
    real_net = np.mean([t["net_r"] for t in all_trades])
    # group by asset for sampling a random region
    by_asset = {}
    for t in all_trades:
        by_asset.setdefault(t["asset"], []).append(t)
    null_means = []
    for _ in range(N_NULL):
        nrs = []
        for sym, tr in by_asset.items():
            lo1, hi1, idx1, close1 = per_asset_1m[sym]
            n1 = len(lo1)
            for t in tr:
                # random start point with room for MAX_HOLD
                sp = int(rng.integers(0, max(1, n1 - MAX_HOLD_MIN - 1)))
                end = min(sp + MAX_HOLD_MIN, n1)
                px = float(close1[sp])
                risk = px * (t["risk_pct"] / 100.0)
                if risk <= 0:
                    continue
                if t["direction"] == "LONG":
                    entry, sl, tp = px, px - risk, px + RR * risk
                    sl_m = lo1[sp:end] <= sl
                    tp_m = hi1[sp:end] >= tp
                else:
                    entry, sl, tp = px, px + risk, px - RR * risk
                    sl_m = hi1[sp:end] >= sl
                    tp_m = lo1[sp:end] <= tp
                sf = int(np.argmax(sl_m)) if sl_m.any() else 10**9
                tf_ = int(np.argmax(tp_m)) if tp_m.any() else 10**9
                if sf == 10**9 and tf_ == 10**9:
                    continue
                if sf <= tf_:
                    g, hold = -1.0, (sf + 1) / 60.0
                else:
                    g, hold = RR, (tf_ + 1) / 60.0
                nrs.append(net_R(g, t["risk_pct"], hold))
        if nrs:
            null_means.append(np.mean(nrs))
    null_means = np.array(null_means, float)
    p = float((null_means >= real_net).mean()) if null_means.size else float("nan")
    return real_net, p, (float(null_means.mean()) if null_means.size else float("nan"))


def main():
    all_trades = []
    per_asset_1m = {}
    for sym in SYMBOLS:
        print(f"loading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        per_asset_1m[sym] = (df_1m["low"].to_numpy(), df_1m["high"].to_numpy(),
                             df_1m.index, df_1m["close"].to_numpy())
        all_trades += run_asset(sym)

    n_closed = len(all_trades)
    if n_closed == 0:
        print("\n[RESULT] NO closed trades — no-signal.")
        print("===JSON_BEGIN===")
        print(json.dumps({"ran_ok": True, "n_closed": 0, "verdict": "no-signal"}))
        print("===JSON_END===")
        return

    gross = np.array([t["gross_r"] for t in all_trades], float)
    net = np.array([t["net_r"] for t in all_trades], float)
    wins = sum(t["win"] for t in all_trades)
    wr = wins / n_closed * 100.0
    gross_ptt = float(gross.mean())
    net_ptt = float(net.mean())

    # per-asset net ptt
    per_asset = []
    for sym in SYMBOLS:
        ts = [t for t in all_trades if t["asset"] == sym]
        if ts:
            per_asset.append({"asset": sym,
                              "net_ptt": round(float(np.mean([t["net_r"] for t in ts])), 4),
                              "n": len(ts)})
        else:
            per_asset.append({"asset": sym, "net_ptt": 0.0, "n": 0})

    # per-tf breakdown (informational)
    per_tf = {}
    for freq, _ in HTF_LIST:
        ts = [t for t in all_trades if t["tf"] == freq]
        per_tf[freq] = (len(ts), round(float(np.mean([t["net_r"] for t in ts])), 4) if ts else 0.0)

    # monthly mean R (pooled net)
    month_R = {}
    for t in all_trades:
        month_R[t["month"]] = month_R.get(t["month"], 0.0) + t["net_r"]
    m_vals = np.array(list(month_R.values()), float)
    monthly_mean_R = float(m_vals.mean()) if m_vals.size else 0.0

    # null control
    rng = np.random.default_rng(RNG_SEED)
    real_net, null_p, null_mean = null_control(all_trades, per_asset_1m, rng)

    n_assets_pos = sum(1 for d in per_asset if d["net_ptt"] > 0 and d["n"] > 0)
    works = (net_ptt > 0) and (null_p < 0.1) and (n_assets_pos >= 2)
    if net_ptt > 0 and not works:
        verdict = "coin"
    elif net_ptt <= 0 and gross_ptt > 0:
        verdict = "cost-killed"
    elif net_ptt <= 0:
        verdict = "coin"
    else:
        verdict = "works"
    if works:
        verdict = "works"

    print("\n" + "=" * 90)
    print(f"C3 Mitigation-block flip (HTF {','.join(f for f,_ in HTF_LIST)}), RR={RR}, entry={ENTRY_FRAC} into zone")
    print("=" * 90)
    print(f"n_closed={n_closed}  WR={wr:.1f}%  gross_ptt={gross_ptt:+.4f}  net_ptt={net_ptt:+.4f}")
    print(f"monthly_mean_R(net,pooled)={monthly_mean_R:+.3f}  months={m_vals.size}")
    print("per-asset net_ptt: " + ", ".join(f"{d['asset']}={d['net_ptt']:+.4f}(n={d['n']})" for d in per_asset))
    print("per-tf  net_ptt: " + ", ".join(f"{k}={v[1]:+.4f}(n={v[0]})" for k, v in per_tf.items()))
    print(f"NULL: real_net={real_net:+.4f}  null_mean={null_mean:+.4f}  null_p={null_p:.4f}  (N={N_NULL})")
    print(f"cross-asset assets_net>0 = {n_assets_pos}/3")
    print(f"VERDICT: {verdict}")

    print("===JSON_BEGIN===")
    print(json.dumps({
        "ran_ok": True, "n_closed": n_closed, "gross_ptt": round(gross_ptt, 5),
        "net_ptt": round(net_ptt, 5), "wr": round(wr, 2),
        "per_asset_net_ptt": per_asset, "null_p": round(null_p, 5),
        "monthly_mean_R": round(monthly_mean_R, 4), "verdict": verdict,
        "per_tf": {k: list(v) for k, v in per_tf.items()},
        "n_assets_pos": n_assets_pos,
    }))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
