"""Stage 2 на 1.1.2 ALL: entry=0.70, vary sl_pct [ob_htf edge -> fvg edge], TP=TP_const, no_entry=on.

Параметры:
  - entry_pct = 0.70 (best Stage 1 на ALL)
  - SL варьируется:
      LONG:  SL = ob_htf.bottom + sl_pct × (fvg.bottom - ob_htf.bottom)
      SHORT: SL = ob_htf.top    - sl_pct × (ob_htf.top    - fvg.top)
  - sl_pct ∈ [0, 1] step 0.05
      0 = ob_htf edge (широкий SL, baseline Stage 1)
      1 = fvg entry edge (тугой SL, ближе к entry)
  - TP = TP_const (price при default entry=mid FVG, SL=ob_htf edge, RR=1)
  - no_entry: ON
  - ВСЕ сетапы 1.1.2 (без SWEPT-фильтра)
"""
from __future__ import annotations


# --- repo-root injection (Phase 3 refactor) ---
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
# --- end repo-root injection ---

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_PCT = 0.70   # best Stage 1 на ALL
SL_GRID = np.arange(0.0, 1.01, 0.05)


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    entry_mid = (fvg_b + fvg_t) / 2
    if direction == "LONG":
        risk_mid = entry_mid - obh_b
        tp_const = entry_mid + risk_mid
    else:
        risk_mid = obh_t - entry_mid
        tp_const = entry_mid - risk_mid
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "tp_const": float(tp_const),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_with_no_entry(s: dict, entry: float, sl: float, tp: float) -> str:
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
    print(f"[INFO] Stage 2 на 1.1.2 ALL: entry={ENTRY_PCT}, vary sl_pct [ob_htf edge -> fvg edge]")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )
    print(f"  raw paths: {len(raw)}")

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    cache = [c for c in (precompute_signal(s, df_1m) for s in deduped) if c is not None]
    print(f"  ALL deduped: {len(deduped)}  cache: {len(cache)}")

    print()
    print("=" * 100)
    print(f"Stage 2: entry_pct={ENTRY_PCT}, TP=TP_const, sl_pct in [0..1] step 0.05")
    print("  sl_pct=0  -> SL = ob_htf edge (широкий)")
    print("  sl_pct=1  -> SL = fvg entry edge (тугой)")
    print("=" * 100)
    rows = []
    for sp in SL_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            fw = s["fvg_t"] - s["fvg_b"]
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ENTRY_PCT * fw
                sl_lo = s["obh_b"]
                sl_hi = s["fvg_b"]
                sl = sl_lo + sp * (sl_hi - sl_lo)
            else:
                entry = s["fvg_t"] - ENTRY_PCT * fw
                sl_hi = s["obh_t"]
                sl_lo = s["fvg_t"]
                sl = sl_hi - sp * (sl_hi - sl_lo)
            tp = s["tp_const"]
            if s["direction"] == "LONG":
                if sl >= entry or tp <= entry:
                    skipped += 1; continue
                risk = entry - sl
                rr = (tp - entry) / risk
            else:
                if sl <= entry or tp >= entry:
                    skipped += 1; continue
                risk = sl - entry
                rr = (entry - tp) / risk
            outcome = simulate_with_no_entry(s, entry, sl, tp)
            if outcome == "win":
                wins += 1; pnl_r += rr; rr_sum += rr; n_with_rr += 1
            elif outcome == "loss":
                losses += 1; pnl_r -= 1.0; rr_sum += rr; n_with_rr += 1
            elif outcome == "no_entry":
                no_entry += 1
            elif outcome == "open":
                opens += 1
            else:
                nf += 1
        closed = wins + losses
        rows.append({
            "sl_pct": round(sp, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "nf": nf, "opens": opens, "skipped": skipped,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })
    df = pd.DataFrame(rows).sort_values("pnl_r", ascending=False)
    print(df.to_string(index=False))

    best = df.iloc[0]
    print()
    print(f"  >>> Best sl_pct = {best['sl_pct']}")
    print(f"      W={best['wins']} L={best['losses']} no_entry={best['no_entry']} "
          f"WR={best['wr']}% PnL={best['pnl_r']}R R/trade={best['r_per_trade']} avg_RR={best['avg_rr']}")

    baseline = df[df["sl_pct"] == 0.0].iloc[0]
    print(f"  Baseline (sl_pct=0, ob_htf edge): W={baseline['wins']} L={baseline['losses']} "
          f"WR={baseline['wr']}% PnL={baseline['pnl_r']}R R/trade={baseline['r_per_trade']} avg_RR={baseline['avg_rr']}")

    out = Path("signals/optimize_1_1_2_stage2.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nGrid saved: {out}")


if __name__ == "__main__":
    main()
