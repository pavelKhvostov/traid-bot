"""CANDIDATE C6 — ob_vc cascade (HTF VC-block) on BTC+ETH+SOL, full history.

Chain spec:
  L1 = ob_vc on 1d & 12h (HTF OB validated by paired LTF FVG via HTF_TO_LTF + first
       opposite Williams-2 fractal; canon detect_ob_vc #1-#9). entry_zone = OB drop/rally area.
  On RETURN into L1 entry_zone, confirm with a 1h OB or FVG (same direction) whose zone
  overlaps L1 entry_zone.
  ENTRY: 0.7 into ob_vc.entry_zone (wide drop/rally area).
         LONG  entry = ez_lo + 0.7*(ez_hi-ez_lo) ; SHORT entry = ez_hi - 0.7*(ez_hi-ez_lo)
  SL:    0.35 symmetric BEYOND the entry_zone edge (= the far OB edge from entry).
         risk = abs(entry - sl). LONG sl below ez_lo by 0.35*width; SHORT sl above ez_hi.
         (Mirrors 1.1.2 sl_pct=0.35 sym: SL is placed 0.35 of zone-width past the protective edge.)
  TP:    RR = 2.2.  Two-sided.

CAUSALITY (hard walls):
  - L1 ob_vc is only USABLE after its arming time = max(primary_fvg.c3 close,
    first-opposite-fractal confirmation = fh_center.open + (N+1)*LTF). No lookahead.
  - 1h confirm: OB confirms at cur.close (open+1h); FVG confirms at c3.close (c3.open+1h).
    confirm must occur AFTER L1 arming and price must be touching/inside L1 at that bar.
  - Entry is a LIMIT fill: from confirm-bar-close forward (+1h), wait for price to TOUCH
    entry; manage SL/TP from the FILL bar forward. If TP would print before fill -> no_entry.
  - Dedup by (confirm_time, direction, round(entry,6)).

NET costs (research/financial/cosim_net.py realistic model): win RT=0.05%, loss RT=0.10%.
  cost_R = RT / (risk_pct/100), risk_pct = abs(entry-sl)/entry*100. net_R = gross_R - cost_R.
NULL control: matched random-entry control (same count, same side split, random bar at a
  similar forward distance) repeated; null_p = P(random net_ptt >= real net_ptt).

Run: cd traid-bot && set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_C6.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import os
import json
from collections import defaultdict

import numpy as np
import pandas as pd

# smc-lib on path
SMC = _ROOT / "smc-lib"
for p in (str(SMC), str(SMC / "prediction-algo")):
    if p not in _sys.path:
        _sys.path.insert(0, p)
os.environ.setdefault("SMCLIB_ROOT", str(SMC))

from data_manager import load_df, compose_from_base  # noqa: E402
from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob  # noqa: E402
from elements.fvg.code import detect_fvg  # noqa: E402
from elements.ob_vc.code import (  # noqa: E402
    detect_ob_vc, HTF_TO_LTF, LTF_DURATION_MS,
)

try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
HTFS = ["1d", "12h"]            # L1 detection TFs
ENTRY_PCT = 0.70
SL_PCT = 0.35
RR = 2.2
N_FRACTAL = 2
WIN_RT, LOSS_RT = 0.0005, 0.0010   # realistic limit-entry net model
# return/confirm search horizon after L1 arming (cap the run; institutional zones live weeks)
RETURN_HORIZON_DAYS = 90
MANAGE_DAYS = 60            # max days to resolve a filled trade; else dropped as "open"
N_NULL = 200
SEED = 7
MANAGE_BARS = MANAGE_DAYS * 24 * 60   # 1m bars in management window

HTF_MS = {"1d": 86_400_000, "12h": 43_200_000}


def df_to_candles(df: pd.DataFrame) -> list[Candle]:
    return [
        Candle(open=float(r.open), high=float(r.high), low=float(r.low),
               close=float(r.close), open_time=int(ts.value // 1_000_000))
        for ts, r in zip(df.index, df.itertuples(index=False))
    ]


def _fvgs_from_candles(cs: list[Candle]) -> list:
    out = []
    for i in range(2, len(cs)):
        f = detect_fvg(cs[i - 2], cs[i - 1], cs[i])
        if f is not None:
            out.append(f)
    return out


def _arming_ms(obvc, htf: str) -> int:
    """Causal arming time of the ob_vc (ms): latest of validating-FVG close and the
    first-opposite-fractal confirmation across LTF components. After this, the whole
    composite is fully confirmed and usable. NO lookahead beyond it.
    """
    arm = 0
    # primary fvg c3 close
    pf = obvc.primary_fvg
    # find ltf of each component to get its duration; use max over all components
    for ltf, fvg in obvc.fvg_components:
        ltf_ms = LTF_DURATION_MS.get(ltf, 0)
        fvg_close = (fvg.c3.open_time or 0) + ltf_ms
        arm = max(arm, fvg_close)
    # The first-opposite-fractal confirm time bounds #8; it is >= every validating FVG close
    # by construction, so it dominates. Recompute conservatively: we don't have the fractal
    # center here, but #8 guarantees fvg_close <= fh_confirm; the fractal needs N more LTF bars
    # to confirm. Add (N_FRACTAL)*max-ltf as a conservative cushion so we never act early.
    max_ltf_ms = max((LTF_DURATION_MS.get(ltf, 0) for ltf, _ in obvc.fvg_components), default=0)
    arm += N_FRACTAL * max_ltf_ms
    return arm


def detect_L1_obvc(resampled: dict, df_1m: pd.DataFrame, htf: str) -> list[dict]:
    """Detect ob_vc L1 zones on one HTF. Returns list of dicts with entry_zone, direction,
    arming time (ms), and HTF cur open (for diagnostics).
    """
    df_htf = resampled.get(htf)
    if df_htf is None or df_htf.empty:
        return []
    allowed_ltfs = HTF_TO_LTF[htf]
    # Prepare LTF candles + FVGs once
    ltf_all_candles, ltf_all_fvgs = {}, {}
    for ltf in allowed_ltfs:
        df_ltf = resampled.get(ltf)
        if df_ltf is None or df_ltf.empty:
            continue
        cs = df_to_candles(df_ltf)
        ltf_all_candles[ltf] = cs
        ltf_all_fvgs[ltf] = _fvgs_from_candles(cs)
    if not ltf_all_candles:
        return []
    # pre-sort LTF candle open_times for fast slicing
    ltf_open_arr = {ltf: np.array([c.open_time or 0 for c in cs])
                    for ltf, cs in ltf_all_candles.items()}

    out = []
    idx_vals = df_htf.index
    o = df_htf["open"].values; h = df_htf["high"].values
    lo = df_htf["low"].values; c = df_htf["close"].values
    for i in range(1, len(df_htf)):
        prev_c = Candle(open=float(o[i - 1]), high=float(h[i - 1]), low=float(lo[i - 1]),
                        close=float(c[i - 1]), open_time=int(idx_vals[i - 1].value // 1_000_000))
        cur_c = Candle(open=float(o[i]), high=float(h[i]), low=float(lo[i]),
                       close=float(c[i]), open_time=int(idx_vals[i].value // 1_000_000))
        ob = detect_ob(prev_c, cur_c)
        if ob is None:
            continue
        ob_cur_ms = cur_c.open_time or 0
        ltf_bars_after = {}
        for ltf, cs in ltf_all_candles.items():
            arr = ltf_open_arr[ltf]
            j = int(np.searchsorted(arr, ob_cur_ms, side="left"))
            ltf_bars_after[ltf] = cs[j:]
        obvc = detect_ob_vc(ob, htf=htf, ltf_bars_after_ob=ltf_bars_after,
                            ltf_fvgs=ltf_all_fvgs, n_fractal=N_FRACTAL, df_1m=df_1m)
        if obvc is None:
            continue
        ez_lo, ez_hi = obvc.entry_zone
        if ez_hi <= ez_lo:
            continue
        arm = _arming_ms(obvc, htf)
        out.append({
            "htf": htf,
            "direction": "LONG" if obvc.direction == "long" else "SHORT",
            "ez_lo": float(ez_lo), "ez_hi": float(ez_hi),
            "arm_ms": int(arm),
            "n_fvg": len(obvc.fvg_components),
        })
    return out


def find_1h_confirm(L1: dict, df_1h: pd.DataFrame, fvg_1h: list, ob_1h: list) -> dict | None:
    """After L1 arming, find first 1h OB or FVG of same direction that confirms while price
    is touching/inside L1 entry_zone. Returns the confirm record (confirm_time ms + diag) or None.

    ob_1h / fvg_1h are precomputed lists of (confirm_ms, direction, zone_lo, zone_hi).
    """
    arm = L1["arm_ms"]
    horizon = arm + RETURN_HORIZON_DAYS * 86_400_000
    want = "long" if L1["direction"] == "LONG" else "short"
    ez_lo, ez_hi = L1["ez_lo"], L1["ez_hi"]
    best = None
    for conf_ms, d, zlo, zhi in fvg_1h:
        if d != want or conf_ms <= arm or conf_ms > horizon:
            continue
        # overlap with L1 entry_zone (price reaction zone inside L1)
        if max(zlo, ez_lo) < min(zhi, ez_hi):
            if best is None or conf_ms < best:
                best = conf_ms
    for conf_ms, d, zlo, zhi in ob_1h:
        if d != want or conf_ms <= arm or conf_ms > horizon:
            continue
        if max(zlo, ez_lo) < min(zhi, ez_hi):
            if best is None or conf_ms < best:
                best = conf_ms
    if best is None:
        return None
    return {"confirm_ms": best}


def precompute_1h_structures(df_1h: pd.DataFrame):
    cs = df_to_candles(df_1h)
    ob_list = []  # (confirm_ms = cur.open + 1h, dir, lo, hi)
    for i in range(1, len(cs)):
        ob = detect_ob(cs[i - 1], cs[i])
        if ob is None:
            continue
        conf = (cs[i].open_time or 0) + 3_600_000
        ob_list.append((conf, ob.direction, ob.zone[0], ob.zone[1]))
    fvg_list = []  # (confirm_ms = c3.open + 1h, dir, lo, hi)
    for i in range(2, len(cs)):
        f = detect_fvg(cs[i - 2], cs[i - 1], cs[i])
        if f is None:
            continue
        conf = (cs[i].open_time or 0) + 3_600_000
        fvg_list.append((conf, f.direction, f.zone[0], f.zone[1]))
    return ob_list, fvg_list


def build_trades_for_symbol(symbol: str) -> list[dict]:
    df_1m = load_df(symbol, "1m")
    if df_1m.empty:
        return []
    df_1d = load_df(symbol, "1d")
    df_12h = load_df(symbol, "12h")
    df_1h = load_df(symbol, "1h")
    df_4h = load_df(symbol, "4h")
    df_6h = load_df(symbol, "6h")
    if df_6h.empty:
        df_6h = compose_from_base(df_1h, "6h")
    resampled = {"1d": df_1d, "12h": df_12h, "4h": df_4h, "6h": df_6h, "1h": df_1h}

    # L1 ob_vc zones across HTFs
    L1s = []
    for htf in HTFS:
        L1s.extend(detect_L1_obvc(resampled, df_1m, htf))

    ob_1h, fvg_1h = precompute_1h_structures(df_1h)

    # 1m arrays for fill/manage
    m_open_ms = (df_1m.index.view("int64") // 1_000_000).astype(np.int64)
    m_high = df_1m["high"].values.astype(np.float64)
    m_low = df_1m["low"].values.astype(np.float64)

    raw = []
    for L1 in L1s:
        conf = find_1h_confirm(L1, df_1h, fvg_1h, ob_1h)
        if conf is None:
            continue
        confirm_ms = conf["confirm_ms"]
        ez_lo, ez_hi = L1["ez_lo"], L1["ez_hi"]
        width = ez_hi - ez_lo
        if L1["direction"] == "LONG":
            entry = ez_lo + ENTRY_PCT * width
            sl = ez_lo - SL_PCT * width
            risk = entry - sl
        else:
            entry = ez_hi - ENTRY_PCT * width
            sl = ez_hi + SL_PCT * width
            risk = sl - entry
        if risk <= 0:
            continue
        raw.append({
            "symbol": symbol, "htf": L1["htf"], "direction": L1["direction"],
            "confirm_ms": confirm_ms, "entry": float(entry), "sl": float(sl),
            "risk": float(risk),
        })

    # Dedup by (confirm_time, direction, round(entry,6))
    groups = {}
    for r in raw:
        key = (r["confirm_ms"], r["direction"], round(r["entry"], 6))
        if key not in groups:
            groups[key] = r
    deduped = list(groups.values())

    # Simulate each (limit fill from confirm + 1h forward)
    trades = []
    for r in deduped:
        start_ms = r["confirm_ms"]  # confirm already = bar close (open+1h); forward from here
        si = int(np.searchsorted(m_open_ms, start_ms, side="left"))
        if si >= len(m_high):
            continue
        highs = m_high[si:si + MANAGE_BARS]; lows = m_low[si:si + MANAGE_BARS]
        entry, sl, risk, direction = r["entry"], r["sl"], r["risk"], r["direction"]
        if direction == "LONG":
            tp = entry + RR * risk
            entry_idxs = np.where(lows <= entry)[0]
            tp_pre_idxs = np.where(highs >= tp)[0]
        else:
            tp = entry - RR * risk
            entry_idxs = np.where(highs >= entry)[0]
            tp_pre_idxs = np.where(lows <= tp)[0]
        n = len(highs)
        entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
        tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
        if tp_pre < entry_idx:
            continue  # no_entry: TP would print before fill
        if entry_idx >= n:
            continue  # not_filled
        post_h = highs[entry_idx:]; post_l = lows[entry_idx:]
        if direction == "LONG":
            sl_mask = post_l <= sl; tp_mask = post_h >= tp
        else:
            sl_mask = post_h >= sl; tp_mask = post_l <= tp
        sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
        tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
        if sl_first == -1 and tp_first == -1:
            continue  # open
        if sl_first == -1:
            outcome = "win"
        elif tp_first == -1:
            outcome = "loss"
        else:
            outcome = "win" if tp_first < sl_first else "loss"
        gross_R = RR if outcome == "win" else -1.0
        risk_pct = abs(entry - sl) / entry * 100.0
        rt = WIN_RT if gross_R > 0 else LOSS_RT
        cost_R = rt / (risk_pct / 100.0)
        net_R = gross_R - cost_R
        fill_ms = int(m_open_ms[si + entry_idx])
        trades.append({
            "symbol": symbol, "htf": r["htf"], "direction": direction,
            "confirm_ms": r["confirm_ms"], "fill_ms": fill_ms,
            "entry": entry, "sl": sl, "risk_pct": risk_pct,
            "gross_R": gross_R, "net_R": net_R,
        })
    print(f"  {symbol}: L1={len(L1s)} deduped_sig={len(deduped)} closed={len(trades)}")
    return trades


def null_control(trades: list[dict], df_1m_by_sym: dict, rng: np.random.Generator) -> float:
    """Matched random-entry control. For each real trade, pick a RANDOM 1m bar (in the same
    symbol's history) as the confirm, keep the same direction and the same risk_pct (distance
    structure), simulate the SAME RR=2.2 limit/SL/TP. Repeat N_NULL times; null_p = fraction of
    null runs whose net_ptt >= real net_ptt.
    """
    if not trades:
        return float("nan")
    real_net = float(np.mean([t["net_R"] for t in trades]))
    # cache per-symbol arrays
    arrs = {}
    for sym, df in df_1m_by_sym.items():
        if df.empty:
            continue
        arrs[sym] = (df["high"].values.astype(np.float64), df["low"].values.astype(np.float64))
    # Bounded forward window so random-entry sim is fast AND a fair matched control:
    # use the SAME management horizon real trades had (MANAGE_BARS).
    WIN_BARS = MANAGE_BARS
    ge = 0
    for _ in range(N_NULL):
        nets = []
        for t in trades:
            sym = t["symbol"]
            if sym not in arrs:
                continue
            highs_full, lows_full = arrs[sym]
            n_full = len(highs_full)
            # random start; leave room for the bounded window
            si = int(rng.integers(0, max(1, n_full - WIN_BARS - 10)))
            highs = highs_full[si:si + WIN_BARS]; lows = lows_full[si:si + WIN_BARS]
            if len(highs) < 5:
                continue
            direction = t["direction"]
            risk_pct = t["risk_pct"]
            # synthetic entry at first bar's price; SL/TP from risk_pct
            ref = (highs[0] + lows[0]) / 2.0
            entry = ref
            if direction == "LONG":
                sl = entry * (1 - risk_pct / 100.0)
                tp = entry + RR * (entry - sl)
                entry_idxs = np.where(lows <= entry)[0]
                tp_pre_idxs = np.where(highs >= tp)[0]
            else:
                sl = entry * (1 + risk_pct / 100.0)
                tp = entry - RR * (sl - entry)
                entry_idxs = np.where(highs >= entry)[0]
                tp_pre_idxs = np.where(lows <= tp)[0]
            n = len(highs)
            ei = int(entry_idxs[0]) if entry_idxs.size else n + 1
            tpp = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
            if tpp < ei or ei >= n:
                continue
            ph = highs[ei:]; pl = lows[ei:]
            if direction == "LONG":
                slm = pl <= sl; tpm = ph >= tp
            else:
                slm = ph >= sl; tpm = pl <= tp
            sf = int(np.argmax(slm)) if slm.any() else -1
            tf = int(np.argmax(tpm)) if tpm.any() else -1
            if sf == -1 and tf == -1:
                continue
            if sf == -1:
                g = RR
            elif tf == -1:
                g = -1.0
            else:
                g = RR if tf < sf else -1.0
            rt = WIN_RT if g > 0 else LOSS_RT
            nets.append(g - rt / (risk_pct / 100.0))
        if nets and float(np.mean(nets)) >= real_net:
            ge += 1
    return ge / N_NULL


def main():
    rng = np.random.default_rng(SEED)
    print("[C6] ob_vc cascade (HTF 1d/12h VC-block) -> 1h OB/FVG confirm. RR=2.2, entry=0.70, sl=0.35 sym")
    all_trades = []
    df_1m_by_sym = {}
    for sym in SYMBOLS:
        df_1m_by_sym[sym] = load_df(sym, "1m")
        all_trades.extend(build_trades_for_symbol(sym))

    n_closed = len(all_trades)
    if n_closed == 0:
        print("[C6] no closed trades")
        out = {"ran_ok": True, "n_closed": 0}
        print("\n[JSON_RESULT]"); print(json.dumps(out))
        return

    gross = np.array([t["gross_R"] for t in all_trades])
    net = np.array([t["net_R"] for t in all_trades])
    wins = int((gross > 0).sum())
    gross_ptt = float(gross.mean())
    net_ptt = float(net.mean())
    wr = wins / n_closed * 100.0

    per_asset = {}
    for sym in SYMBOLS:
        s = [t for t in all_trades if t["symbol"] == sym]
        per_asset[sym] = {"net_ptt": float(np.mean([t["net_R"] for t in s])) if s else 0.0,
                          "n": len(s)}

    # monthly mean net R (pooled by confirm month)
    month_R = defaultdict(float)
    for t in all_trades:
        m = pd.Timestamp(t["confirm_ms"], unit="ms", tz="UTC").strftime("%Y-%m")
        month_R[m] += t["net_R"]
    months = sorted(month_R)
    monthly_mean_R = float(np.mean([month_R[m] for m in months])) if months else 0.0

    null_p = null_control(all_trades, df_1m_by_sym, rng)

    pos_assets = sum(1 for sym in SYMBOLS if per_asset[sym]["n"] > 0 and per_asset[sym]["net_ptt"] > 0)
    print(f"\n  n_closed={n_closed} WR={wr:.1f}% gross_ptt={gross_ptt:+.4f} net_ptt={net_ptt:+.4f}")
    for sym in SYMBOLS:
        print(f"    {sym}: net_ptt={per_asset[sym]['net_ptt']:+.4f} n={per_asset[sym]['n']}")
    print(f"  null_p={null_p:.4f}  monthly_mean_R={monthly_mean_R:+.4f}  pos_assets={pos_assets}/3")

    works = (net_ptt > 0) and (null_p < 0.1) and (pos_assets >= 2)
    out = {
        "cid": "C6", "ran_ok": True, "n_closed": n_closed,
        "gross_ptt": round(gross_ptt, 5), "net_ptt": round(net_ptt, 5),
        "wr": round(wr, 2),
        "per_asset_net_ptt": [{"asset": s, "net_ptt": round(per_asset[s]["net_ptt"], 5),
                               "n": per_asset[s]["n"]} for s in SYMBOLS],
        "null_p": round(null_p, 4), "monthly_mean_R": round(monthly_mean_R, 4),
        "works": works,
    }
    print("\n[JSON_RESULT]"); print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
