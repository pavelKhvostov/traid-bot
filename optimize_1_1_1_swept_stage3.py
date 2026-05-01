"""Stage 3 на SWEPT: фиксируем entry=0.80 и sl_pct=0.40, варьируем RR (TP).

Параметры:
  - entry = entry_pct=0.80 (best из Stage 1 с no_entry)
  - SL: sl_pct=0.40 в пределах [ob_htf edge -> fvg entry edge]
      LONG:  SL = ob_htf.bottom + 0.40 × (fvg.bottom - ob_htf.bottom)
      SHORT: SL = ob_htf.top    - 0.40 × (ob_htf.top    - fvg.top)
  - RR ∈ [1.0, 6.0] step 0.1
      TP_LONG  = entry + rr × (entry - SL)
      TP_SHORT = entry - rr × (SL - entry)
  - Включён no_entry (TP до entry -> отмена)
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_PCT = 0.80   # best Stage 1 (с no_entry)
SL_PCT = 0.40      # из Stage 2 (по запросу пользователя)
RR_GRID = np.arange(1.0, 6.01, 0.1)


def check_swept_for_path(sig: dict, df_1h: pd.DataFrame, df_2h: pd.DataFrame) -> bool | None:
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2:
        return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[prev_idx]["low"]); c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx - 1]["low"]); n2l = float(df_top.iloc[prev_idx - 2]["low"])
    n1h = float(df_top.iloc[prev_idx - 1]["high"]); n2h = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_with_no_entry(s: dict, entry: float, sl: float, tp: float) -> str:
    """С no_entry: если TP достигнут до entry — отмена."""
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if s["direction"] == "LONG":
        entry_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
    else:
        entry_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]
    entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
    tp_pre_idx = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    if tp_pre_idx < entry_idx:
        return "no_entry"
    if entry_idx >= n:
        return "not_filled"
    post_l = lows[entry_idx:]; post_h = highs[entry_idx:]
    if s["direction"] == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def main() -> None:
    print(f"[INFO] Stage 3 SWEPT: entry={ENTRY_PCT}, sl_pct={SL_PCT}, RR varies [1.0..6.0] step 0.1, no_entry=on")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]

    raw = detect_strategy_1_1_1_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept_for_path(s, df_1h, df_2h)
        if sw is None:
            continue
        groups[key].append({"sig": s, "swept": sw})
    swept_reps = [next(p["sig"] for p in paths if p["swept"])
                  for key, paths in groups.items() if any(p["swept"] for p in paths)]
    cache = [c for c in (precompute_signal(s, df_1m) for s in swept_reps) if c is not None]
    print(f"  SWEPT cache: {len(cache)}")

    print()
    print("=" * 100)
    print(f"Stage 3: entry_pct={ENTRY_PCT}, sl_pct={SL_PCT}, RR varies [1.0..6.0] step 0.1")
    print("=" * 100)
    rows = []
    for rr_target in RR_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0
        for s in cache:
            fw = s["fvg_t"] - s["fvg_b"]
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ENTRY_PCT * fw
                sl_lo = s["obh_b"]
                sl_hi = s["fvg_b"]
                sl = sl_lo + SL_PCT * (sl_hi - sl_lo)
                if sl >= entry:
                    skipped += 1; continue
                risk = entry - sl
                tp = entry + rr_target * risk
            else:
                entry = s["fvg_t"] - ENTRY_PCT * fw
                sl_hi = s["obh_t"]
                sl_lo = s["fvg_t"]
                sl = sl_hi - SL_PCT * (sl_hi - sl_lo)
                if sl <= entry:
                    skipped += 1; continue
                risk = sl - entry
                tp = entry - rr_target * risk
            outcome = simulate_with_no_entry(s, entry, sl, tp)
            if outcome == "win":
                wins += 1; pnl_r += rr_target
            elif outcome == "loss":
                losses += 1; pnl_r -= 1.0
            elif outcome == "no_entry":
                no_entry += 1
            elif outcome == "open":
                opens += 1
            else:
                nf += 1
        closed = wins + losses
        rows.append({
            "rr": round(rr_target, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "nf": nf, "opens": opens, "skipped": skipped,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
        })
    df = pd.DataFrame(rows).sort_values("pnl_r", ascending=False)
    print(df.to_string(index=False))

    best = df.iloc[0]
    print()
    print(f"  >>> Best RR = {best['rr']}")
    print(f"      wins={best['wins']} losses={best['losses']} no_entry={best['no_entry']} "
          f"WR={best['wr']}% PnL={best['pnl_r']}R R/trade={best['r_per_trade']}")

    out = Path("signals/optimize_1_1_1_swept_stage3.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nGrid saved: {out}")


if __name__ == "__main__":
    main()
