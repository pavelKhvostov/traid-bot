"""CANDIDATE C4 — Sweep -> CHoCH -> OB entry (LTF reversal). Two-sided.

CHAIN (causal, no lookahead):
  1. HTF liquidity: confirmed Williams fractal on {4h, 6h} (N=2, confirms at center+2).
     SWEEP = a later HTF bar's wick takes the fractal level:
        swept FH (high above FH level) -> sell-side grab -> expect reversal DOWN -> SHORT setup.
        swept FL (low below FL level)  -> buy-side grab  -> expect reversal UP   -> LONG setup.
     The sweep is registered at the close of the HTF bar whose wick pierced the level
     (that bar is fully closed -> causal).
  2. LTF CHoCH: scan_market_structure on {1h, 2h} (LuxAlgo canon, close-cross of the
     opposite N2-fractal = reversal). After a swept-high we require the NEXT bearish CHoCH
     (os flips +1 -> -1); after a swept-low the NEXT bullish CHoCH. The CHoCH break bar must
     close AFTER the HTF sweep bar closes. The CHoCH is usable only at its break_idx (confirmed).
  3. First OB on 1h after the CHoCH break, located in the discount half (LONG) / premium half
     (SHORT) of the move. Move = from the swept fractal level to the CHoCH break-bar close.
        discount half = lower 50% of [lo_move, hi_move]; premium half = upper 50%.
     "first OB in that half" = first 2-candle OB (canon detect_ob) of the matching direction
     whose 0.5 (mid) price lies in the correct half, formed strictly after the CHoCH break bar.
  4. ENTRY: 0.5 (mid) of the OB-1h zone. LIMIT fill: from the OB-confirm bar forward, wait for
     price to TOUCH the mid on 1m.
     SL: beyond the swept fractal level (for SHORT: above swept FH by a small buffer = the HTF
     sweep bar's high; for LONG: below swept FL = the HTF sweep bar's low). SL is the protective
     invalidation -> "beyond the swept fractal".
     TP: next opposite fractal (next liquidity) on the OB TF (1h) that exists beyond entry in the
     trade direction; else RR=2.2.
  5. Manage SL/TP on 1m from the FILL bar forward (never the entry/confirm bar). Tie -> loss.

NET costs (limit-entry maker model, cosim_net.py realistic): win RT 0.05%, loss RT 0.10%.
  cost_R = RT / (risk_pct/100); risk_pct = abs(entry-sl)/entry*100. net_R = gross_R - cost_R.
Dedup by (confirm_time=OB-confirm bar, direction, round(entry,6)).
NULL control: random-entry matched control (same n, same side split, random fill bar at similar
  forward distance, same SL/TP geometry) x N_NULL; null_p = P(null mean net_ptt >= real net_ptt).

Run: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_C4.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.smc_adapter import Candle, detect_fractal, detect_ob  # noqa: E402

# CHoCH/BOS is a STANDALONE detector (not wired into the zone engine) — call it directly.
sys.path.insert(0, str(ROOT / "smc-lib"))
from elements.choch_bos.code import scan_market_structure  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
HTF_LIST = ["4h", "6h"]          # liquidity fractals
LTF_CHOCH = ["1h", "2h"]         # CHoCH timeframes
OB_TF = "1h"                     # OB entry TF
OB_TF_MIN = 60
FRACTAL_N = 2
CHOCH_LEN = 5
RR_FALLBACK = 2.2
RR_CAP = 5.0                     # cap liquidity-TP RR (project R-caps 3.5-4.5); above -> fallback 2.2
MIN_RISK_PCT = 0.05             # drop too-tight stops (matches cosim_net loader filter)
MAX_HOLD_MIN = 30 * 24 * 60      # 30 days
# sweep search window: an HTF fractal can be swept within this many HTF bars after it confirms
SWEEP_WINDOW_HTF = 60
# CHoCH must occur within this many LTF bars after the sweep bar closes
CHOCH_WINDOW_LTF = 120
# OB must form within this many OB-TF bars after the CHoCH break
OB_WINDOW = 60
WIN_RT = 0.0005
LOSS_RT = 0.0010
N_NULL = 1000
NULL_HOLD_MIN = 14 * 24 * 60  # cap forward scan in null draws (tractability); real uses MAX_HOLD
SEED = 12345
TF_MIN = {"1h": 60, "2h": 120, "4h": 240, "6h": 360}


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


def to_candles(df: pd.DataFrame) -> list[Candle]:
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); c = df["close"].to_numpy()
    t = (df.index.view("int64") // 1_000_000)  # ms
    return [Candle(float(o[i]), float(h[i]), float(l[i]), float(c[i]), int(t[i]))
            for i in range(len(df))]


# ---------------------------------------------------------------------------
# STEP 1: HTF swept fractals
# ---------------------------------------------------------------------------
def find_swept_fractals(df_htf: pd.DataFrame, htf_min: int):
    """Confirmed Williams fractals later swept by a wick.

    Returns list of dicts:
      {dir: 'SHORT'|'LONG', level, conf_time (fractal confirm), sweep_time (HTF bar close),
       sweep_high, sweep_low}
    SHORT setup = swept FH (high pierced above level).
    LONG  setup = swept FL (low pierced below level).
    """
    h = df_htf["high"].to_numpy()
    l = df_htf["low"].to_numpy()
    c = df_htf["close"].to_numpy()
    idx = df_htf.index
    n = len(df_htf)
    cands = to_candles(df_htf)
    out = []
    for center in range(FRACTAL_N, n - FRACTAL_N):
        window = cands[center - FRACTAL_N: center + FRACTAL_N + 1]
        fr = detect_fractal(window, n=FRACTAL_N)
        if fr is None:
            continue
        confirm_i = center + FRACTAL_N          # fractal usable only at center+N
        level = fr.level
        # search forward for the first bar whose wick takes the level
        end = min(confirm_i + 1 + SWEEP_WINDOW_HTF, n)
        if fr.direction == "high":
            # swept when a later bar's high pierces above the FH level
            for j in range(confirm_i + 1, end):
                if h[j] > level:
                    out.append({
                        "dir": "SHORT", "level": level,
                        "conf_time": idx[confirm_i],
                        "sweep_time": idx[j], "sweep_high": float(h[j]),
                        "sweep_low": float(l[j]),
                    })
                    break
        else:
            for j in range(confirm_i + 1, end):
                if l[j] < level:
                    out.append({
                        "dir": "LONG", "level": level,
                        "conf_time": idx[confirm_i],
                        "sweep_time": idx[j], "sweep_low": float(l[j]),
                        "sweep_high": float(h[j]),
                    })
                    break
    return out


# ---------------------------------------------------------------------------
# STEP 2: LTF CHoCH (reversal) after the sweep
# ---------------------------------------------------------------------------
def first_choch_after(df_ltf: pd.DataFrame, choch_events_idx, want_side: str,
                      after_ts, ltf_min: int):
    """First CHoCH of want_side ('bearish'|'bullish') whose break bar closes after `after_ts`.

    df_ltf indexed by open_time. The break bar at break_idx closes at open_time + ltf_min,
    which we treat as the confirm time (causal). Returns (break_time_close, choch_level) or None.
    Restricted to CHOCH_WINDOW_LTF bars after the sweep.
    """
    idx = df_ltf.index
    # earliest break bar must open at or after after_ts (so it closes strictly after sweep close)
    start_pos = int(idx.searchsorted(after_ts, side="left"))
    end_ts = None
    if start_pos < len(idx):
        end_pos = min(start_pos + CHOCH_WINDOW_LTF, len(idx) - 1)
        end_ts = idx[end_pos]
    for ev in choch_events_idx:
        if ev["type"] != "CHoCH" or ev["side"] != want_side:
            continue
        bt_open = ev["break_open_time"]
        if bt_open < after_ts:
            continue
        if end_ts is not None and bt_open > end_ts:
            break
        # break-bar CLOSE = open + ltf_min minutes; use that as confirm
        return ev["break_open_time"] + pd.Timedelta(minutes=ltf_min), ev["fractal_level"], ev["break_close"]
    return None


def precompute_choch(df_ltf: pd.DataFrame, ltf_min: int):
    """Run scan_market_structure once; return list with break open_time + close + level + side+type."""
    cands = to_candles(df_ltf)
    evs = scan_market_structure(cands, length=CHOCH_LEN)
    idx = df_ltf.index
    cl = df_ltf["close"].to_numpy()
    out = []
    for e in evs:
        out.append({
            "type": e.type, "side": e.side,
            "break_open_time": idx[e.break_idx],
            "break_close": float(cl[e.break_idx]),
            "fractal_level": float(e.fractal_level),
        })
    return out


# ---------------------------------------------------------------------------
# STEP 3: first OB-1h in the discount/premium half after the CHoCH
# ---------------------------------------------------------------------------
def first_ob_in_half(df_ob: pd.DataFrame, after_ts, trade_dir: str,
                     lo_move: float, hi_move: float):
    """First canon OB on OB-TF, matching direction, whose mid lies in the correct half,
    formed strictly after `after_ts`.

    trade_dir LONG  -> long OB whose mid in DISCOUNT half (lower 50% of [lo_move, hi_move]).
    trade_dir SHORT -> short OB whose mid in PREMIUM half (upper 50%).
    Returns (ob_confirm_time, zone_lo, zone_hi, mid) or None.
    ob_confirm_time = close time of `cur` bar of the OB (causal).
    """
    idx = df_ob.index
    start = int(idx.searchsorted(after_ts, side="left"))
    n = len(df_ob)
    if start < 1:
        start = 1
    end = min(start + OB_WINDOW, n)
    mid_move = (lo_move + hi_move) / 2.0
    o = df_ob["open"].to_numpy(); h = df_ob["high"].to_numpy()
    l = df_ob["low"].to_numpy(); c = df_ob["close"].to_numpy()
    want = "long" if trade_dir == "LONG" else "short"
    for i in range(max(start, 1), end):
        prev = Candle(float(o[i-1]), float(h[i-1]), float(l[i-1]), float(c[i-1]))
        cur = Candle(float(o[i]), float(h[i]), float(l[i]), float(c[i]))
        ob = detect_ob(prev, cur)
        if ob is None or ob.direction != want:
            continue
        zlo, zhi = ob.zone
        mid = (zlo + zhi) / 2.0
        if trade_dir == "LONG":
            in_half = mid <= mid_move      # discount = lower half
        else:
            in_half = mid >= mid_move      # premium = upper half
        if not in_half:
            continue
        # cur closes at idx[i] + OB_TF_MIN
        conf = idx[i] + pd.Timedelta(minutes=OB_TF_MIN)
        return conf, float(zlo), float(zhi), float(mid)
    return None


# ---------------------------------------------------------------------------
# STEP 3b/TP: next opposite fractal on the OB-TF beyond entry, else RR fallback
# ---------------------------------------------------------------------------
def next_opposite_fractal_tp(df_ob: pd.DataFrame, after_ts, trade_dir: str, entry: float):
    """Next confirmed opposite fractal (liquidity target) on the OB TF beyond `entry`
    in the trade direction, formed after `after_ts`. Returns level or None.

    LONG -> next FH (high fractal) above entry.  SHORT -> next FL below entry.
    Fractal confirms at center+N (causal); we require its confirm time > after_ts.
    """
    idx = df_ob.index
    start = int(idx.searchsorted(after_ts, side="left"))
    n = len(df_ob)
    cands = to_candles(df_ob)
    # iterate candidate centers; confirm at center+N
    for center in range(max(start, FRACTAL_N), n - FRACTAL_N):
        if idx[center + FRACTAL_N] <= after_ts:
            continue
        window = cands[center - FRACTAL_N: center + FRACTAL_N + 1]
        fr = detect_fractal(window, n=FRACTAL_N)
        if fr is None:
            continue
        if trade_dir == "LONG" and fr.direction == "high" and fr.level > entry:
            return float(fr.level)
        if trade_dir == "SHORT" and fr.direction == "low" and fr.level < entry:
            return float(fr.level)
    return None


# ---------------------------------------------------------------------------
# Build signals for one asset
# ---------------------------------------------------------------------------
def build_signals(sym: str, df_1m: pd.DataFrame):
    df_ob = resample(df_1m, OB_TF)
    # precompute CHoCH per LTF
    choch_pre = {}
    ltf_frames = {}
    for ltf in LTF_CHOCH:
        f = resample(df_1m, ltf)
        ltf_frames[ltf] = f
        choch_pre[ltf] = precompute_choch(f, TF_MIN[ltf])

    signals = []
    for htf in HTF_LIST:
        df_htf = resample(df_1m, htf)
        swept = find_swept_fractals(df_htf, TF_MIN[htf])
        for sw in swept:
            trade_dir = sw["dir"]
            want_side = "bearish" if trade_dir == "SHORT" else "bullish"
            sweep_close_ts = sw["sweep_time"] + pd.Timedelta(minutes=TF_MIN[htf])
            # try each LTF for the first matching CHoCH after the sweep closes
            best_choch = None
            for ltf in LTF_CHOCH:
                res = first_choch_after(ltf_frames[ltf], choch_pre[ltf],
                                        want_side, sweep_close_ts, TF_MIN[ltf])
                if res is None:
                    continue
                ch_time, ch_level, ch_close = res
                if best_choch is None or ch_time < best_choch[0]:
                    best_choch = (ch_time, ch_level, ch_close)
            if best_choch is None:
                continue
            ch_time, ch_level, ch_close = best_choch
            # move from swept fractal level to CHoCH break close
            lo_move = min(sw["level"], ch_close)
            hi_move = max(sw["level"], ch_close)
            ob = first_ob_in_half(df_ob, ch_time, trade_dir, lo_move, hi_move)
            if ob is None:
                continue
            ob_conf, zlo, zhi, mid = ob
            entry = mid
            # SL beyond swept fractal: SHORT -> above the swept HTF bar high; LONG -> below sweep low
            if trade_dir == "SHORT":
                sl = sw["sweep_high"]
                if sl <= entry:
                    continue
            else:
                sl = sw["sweep_low"]
                if sl >= entry:
                    continue
            risk = abs(entry - sl)
            if risk <= 0:
                continue
            # drop too-tight stops (cost_R explodes; matches cosim_net loader)
            risk_pct = risk / entry * 100.0
            if risk_pct < MIN_RISK_PCT:
                continue
            # TP: next opposite fractal on OB TF, else RR fallback. Cap RR (no 1000R targets).
            tp_liq = next_opposite_fractal_tp(df_ob, ob_conf, trade_dir, entry)
            fb = (entry + RR_FALLBACK * risk) if trade_dir == "LONG" else (entry - RR_FALLBACK * risk)
            if tp_liq is not None:
                rr_eff = abs(tp_liq - entry) / risk
                tp = tp_liq if (1.0 <= rr_eff <= RR_CAP) else fb
            else:
                tp = fb
            signals.append({
                "asset": sym, "dir": trade_dir, "entry": entry, "sl": sl, "tp": tp,
                "risk": risk, "confirm_time": ob_conf,
                "month": pd.Timestamp(ob_conf).strftime("%Y-%m"),
            })
    return signals, df_ob


# ---------------------------------------------------------------------------
# Fill + resolve on 1m
# ---------------------------------------------------------------------------
def resolve_trades(signals, df_1m):
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index; n1 = len(lo1)
    closed = []
    seen = set()
    for s in signals:
        key = (pd.Timestamp(s["confirm_time"]).value, s["dir"], round(s["entry"], 6))
        if key in seen:
            continue
        seen.add(key)
        # fill scan from confirm bar forward (OB cur already closed at confirm_time)
        sp = int(idx1.searchsorted(pd.Timestamp(s["confirm_time"]), side="left"))
        if sp >= n1:
            continue
        end = min(sp + MAX_HOLD_MIN, n1)
        if s["dir"] == "LONG":
            fhit = np.where(lo1[sp:end] <= s["entry"])[0]
        else:
            fhit = np.where(hi1[sp:end] >= s["entry"])[0]
        if fhit.size == 0:
            continue  # not filled
        f = sp + int(fhit[0])
        # resolve from FILL bar forward
        plo = lo1[f:end]; phi = hi1[f:end]
        if s["dir"] == "LONG":
            sl_m = plo <= s["sl"]; tp_m = phi >= s["tp"]
        else:
            sl_m = phi >= s["sl"]; tp_m = plo <= s["tp"]
        sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
        tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
        if sl_first == 10**9 and tp_first == 10**9:
            continue  # open / unresolved -> dropped
        win = tp_first < sl_first  # tie -> loss
        rr_real = abs(s["tp"] - s["entry"]) / s["risk"]
        gross_r = rr_real if win else -1.0
        risk_pct = abs(s["entry"] - s["sl"]) / s["entry"] * 100.0
        rt = WIN_RT if win else LOSS_RT
        cost_r = rt / (risk_pct / 100.0)
        net_r = gross_r - cost_r
        closed.append({
            "asset": s["asset"], "dir": s["dir"], "month": s["month"],
            "win": win, "gross_r": gross_r, "net_r": net_r,
            "risk_pct": risk_pct, "fill_idx": f, "rr": rr_real,
            "fwd_min": f - sp,
        })
    return closed, lo1, hi1, idx1


# ---------------------------------------------------------------------------
# NULL control: random entry, matched count + side split + forward distance
# ---------------------------------------------------------------------------
def null_control(closed, per_asset_1m, real_net_ptt):
    """For each real trade, draw a random fill bar at a similar forward distance and
    re-roll the SL/TP outcome with the SAME geometry (entry/sl/tp recomputed from a random
    anchor price). We instead use the simpler, robust label-shuffle-free approach:
    random entry bar -> random side -> simulate same RR & risk_pct distribution.

    Implementation: keep each trade's RR and risk_pct (geometry), but pick a RANDOM bar in
    that asset's 1m history as the 'entry', random direction matched to the global side split,
    place SL/TP at the trade's risk distance, and resolve forward. mean net_ptt over the set is
    one null draw. null_p = P(null mean >= real mean) over N_NULL draws.
    """
    rng = np.random.default_rng(SEED)
    n = len(closed)
    n_short = sum(1 for t in closed if t["dir"] == "SHORT")
    p_short = n_short / n if n else 0.5
    geom = np.array([(t["risk_pct"], t["rr"]) for t in closed], dtype=float)  # (n,2)
    risk_pct_arr = geom[:, 0]
    rr_arr = geom[:, 1]
    assets = list(per_asset_1m.keys())
    asset_arrays = {a: (per_asset_1m[a][0], per_asset_1m[a][1], per_asset_1m[a][2])
                    for a in assets}
    asset_n = {a: len(asset_arrays[a][2]) for a in assets}

    null_hold = min(MAX_HOLD_MIN, NULL_HOLD_MIN)  # cap forward scan for null tractability

    def resolve_one(a, bar, risk_pct, rr, is_short):
        lo1, hi1, close1 = asset_arrays[a]
        na = len(close1)
        entry = close1[bar]
        risk = entry * (risk_pct / 100.0)
        end = min(bar + null_hold, na)
        plo = lo1[bar:end]; phi = hi1[bar:end]
        if is_short:
            sl = entry + risk; tp = entry - rr * risk
            sl_m = phi >= sl; tp_m = plo <= tp
        else:
            sl = entry - risk; tp = entry + rr * risk
            sl_m = plo <= sl; tp_m = phi >= tp
        sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
        tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
        if sl_first == 10**9 and tp_first == 10**9:
            return None
        win = tp_first < sl_first
        gross = rr if win else -1.0
        cost = (WIN_RT if win else LOSS_RT) / (risk_pct / 100.0)
        return gross - cost

    null_means = np.empty(N_NULL)
    for d in range(N_NULL):
        a_choice = [assets[i] for i in rng.integers(len(assets), size=n)]
        bars = [int(rng.integers(0, asset_n[a] - 1)) for a in a_choice]
        shorts = rng.random(n) < p_short
        nets = []
        for k in range(n):
            r = resolve_one(a_choice[k], bars[k], risk_pct_arr[k], rr_arr[k], shorts[k])
            if r is not None:
                nets.append(r)
        null_means[d] = np.mean(nets) if nets else 0.0
    null_p = float(np.mean(null_means >= real_net_ptt))
    return null_p, float(null_means.mean()), float(null_means.std())


def main():
    all_closed = []
    per_asset_1m = {}
    for sym in SYMBOLS:
        print(f"loading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        signals, _ = build_signals(sym, df_1m)
        print(f"  {sym}: {len(signals)} raw signals", flush=True)
        closed, lo1, hi1, idx1 = resolve_trades(signals, df_1m)
        print(f"  {sym}: {len(closed)} closed trades", flush=True)
        per_asset_1m[sym] = (lo1, hi1, df_1m["close"].to_numpy())
        all_closed.extend(closed)

    n_closed = len(all_closed)
    if n_closed == 0:
        print("\n=== NO CLOSED TRADES ===")
        import json
        print("===JSON_BEGIN===")
        print(json.dumps({"n_closed": 0}))
        print("===JSON_END===")
        return

    gross_ptt = float(np.mean([t["gross_r"] for t in all_closed]))
    net_ptt = float(np.mean([t["net_r"] for t in all_closed]))
    wr = float(np.mean([1.0 if t["win"] else 0.0 for t in all_closed]) * 100)

    per_asset = []
    for a in SYMBOLS:
        sub = [t for t in all_closed if t["asset"] == a]
        per_asset.append({
            "asset": a,
            "net_ptt": round(float(np.mean([t["net_r"] for t in sub])), 4) if sub else 0.0,
            "n": len(sub),
        })

    # monthly mean net R (pooled): sum net_r per month, then mean across months
    month_R = {}
    for t in all_closed:
        month_R[t["month"]] = month_R.get(t["month"], 0.0) + t["net_r"]
    monthly_mean_R = float(np.mean(list(month_R.values()))) if month_R else 0.0

    print("\nrunning null control...", flush=True)
    null_p, null_mean, null_std = null_control(all_closed, per_asset_1m, net_ptt)

    n_pos_assets = sum(1 for p in per_asset if p["net_ptt"] > 0)
    works = (net_ptt > 0) and (null_p < 0.1) and (n_pos_assets >= 2)
    if works:
        verdict = "works"
    elif gross_ptt > 0 and net_ptt <= 0:
        verdict = "cost-killed"
    elif net_ptt > 0 and null_p >= 0.1:
        verdict = "coin"
    else:
        verdict = "coin"

    print("\n" + "=" * 90)
    print(f"C4 Sweep->CHoCH->OB  closed={n_closed}  WR={wr:.1f}%  "
          f"gross_ptt={gross_ptt:+.4f}  net_ptt={net_ptt:+.4f}")
    print(f"per_asset: " + "  ".join(f"{p['asset']}={p['net_ptt']:+.4f}(n={p['n']})"
                                     for p in per_asset))
    print(f"null: mean={null_mean:+.4f} std={null_std:.4f}  null_p={null_p:.4f}")
    print(f"monthly_mean_R(net)={monthly_mean_R:+.4f}  verdict={verdict}")
    print("=" * 90)

    import json
    print("===JSON_BEGIN===")
    print(json.dumps({
        "n_closed": n_closed, "gross_ptt": round(gross_ptt, 6),
        "net_ptt": round(net_ptt, 6), "wr": round(wr, 4),
        "per_asset": per_asset, "null_p": round(null_p, 6),
        "monthly_mean_R": round(monthly_mean_R, 6), "verdict": verdict,
        "n_pos_assets": n_pos_assets,
    }))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
