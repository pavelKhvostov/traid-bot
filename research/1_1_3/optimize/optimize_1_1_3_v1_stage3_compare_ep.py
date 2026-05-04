"""Stage 3 на 1.1.3 v1 ALL для двух entry_pct: 0.00 и 1.00.

Параметры:
  - fvg_variant = v1
  - ALL group, no_entry=on, untouched=on
  - entry в FVG:
      ep=0.00 → entry на fvg.bottom (LONG) / fvg.top (SHORT) — full retest
      ep=1.00 → entry на fvg.top (LONG) / fvg.bottom (SHORT) — first touch
  - SL внутри OB-htf, sl_pct = 0.60 (best Stage 2 для обоих ep)
  - RR ∈ [1.0, 6.0] step 0.1
      TP = entry ± RR × risk
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
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
EP_LIST = [0.00, 1.00]
SL_PCT = 0.60
RR_GRID = np.arange(1.0, 6.01, 0.1)


def precompute(sig, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 60 if sig["fvg_tf"] == "1h" else 120
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty: return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_no_entry(s, entry, sl, tp):
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
    if tp_pre_idx < entry_idx: return "no_entry"
    if entry_idx >= n: return "not_filled"
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


def stage3_grid(cache, ep_fixed):
    rows = []
    for rr_target in RR_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0
        for s in cache:
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ep_fixed * (s["fvg_t"] - s["fvg_b"])
                sl_lo = s["obh_b"]; sl_hi = s["obh_t"]
                sl = sl_lo + SL_PCT * (sl_hi - sl_lo)
                if sl >= entry: skipped += 1; continue
                risk = entry - sl
                tp = entry + rr_target * risk
            else:
                entry = s["fvg_t"] - ep_fixed * (s["fvg_t"] - s["fvg_b"])
                sl_hi = s["obh_t"]; sl_lo = s["obh_b"]
                sl = sl_hi - SL_PCT * (sl_hi - sl_lo)
                if sl <= entry: skipped += 1; continue
                risk = sl - entry
                tp = entry - rr_target * risk
            outcome = simulate_no_entry(s, entry, sl, tp)
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
            "ep": ep_fixed,
            "rr": round(rr_target, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
        })
    return pd.DataFrame(rows)


def main():
    print(f"[INFO] Stage 3 для 1.1.3 v1, ep in {EP_LIST}, sl_pct={SL_PCT}, RR [1..6] step 0.1")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    raw = detect_strategy_1_1_3_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h,
        fvg_variant="v1", verbose=False,
    )
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]
    print(f"  cache: {len(cache)}\n")

    grids = []
    for ep in EP_LIST:
        df = stage3_grid(cache, ep)
        grids.append(df)
        print("=" * 100)
        print(f"ep={ep:.2f}, sl_pct={SL_PCT}, vary RR")
        print("=" * 100)
        df_sorted = df.sort_values("pnl_r", ascending=False)
        print(df_sorted.drop(columns=["ep"]).head(15).to_string(index=False))
        best = df_sorted.iloc[0]
        print(f"\n  >>> Best RR={best['rr']}  WR={best['wr']}%  PnL={best['pnl_r']}R  "
              f"R/trade={best['r_per_trade']}")
        print()

    # Сравнительная таблица по ключевым RR
    key_rrs = [1.0, 1.5, 2.0, 2.2, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    print("=" * 100)
    print("Сравнительная таблица: PnL по ключевым RR")
    print("=" * 100)
    cmp_rows = []
    for rr in key_rrs:
        row = {"rr": rr}
        for i, ep in enumerate(EP_LIST):
            df = grids[i]
            sub = df[df["rr"] == rr]
            if len(sub) > 0:
                r = sub.iloc[0]
                row[f"ep={ep}_W"] = int(r["wins"])
                row[f"ep={ep}_L"] = int(r["losses"])
                row[f"ep={ep}_WR"] = r["wr"]
                row[f"ep={ep}_PnL"] = r["pnl_r"]
                row[f"ep={ep}_R/tr"] = r["r_per_trade"]
        cmp_rows.append(row)
    print(pd.DataFrame(cmp_rows).to_string(index=False))

    # Best per ep summary
    print()
    print("=" * 100)
    print("Best Stage 3 для каждого ep:")
    print("=" * 100)
    summary = []
    for df in grids:
        best = df.sort_values("pnl_r", ascending=False).iloc[0]
        summary.append({
            "ep": best["ep"], "best_rr": best["rr"],
            "wins": best["wins"], "losses": best["losses"], "no_entry": best["no_entry"],
            "closed": best["closed"], "wr": best["wr"],
            "pnl_r": best["pnl_r"], "r_per_trade": best["r_per_trade"],
        })
    print(pd.DataFrame(summary).to_string(index=False))

    out = Path("signals/optimize_1_1_3_v1_stage3_compare_ep.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(grids).to_csv(out, index=False)
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
