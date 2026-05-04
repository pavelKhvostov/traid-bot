"""1.1.3 с новой геометрией entry/SL:

  Stage 1: entry варьируется ТОЛЬКО в границах FVG-htf (fvg.bottom..fvg.top).
    LONG:  entry = fvg.bottom + ep × (fvg.top - fvg.bottom)
    SHORT: entry = fvg.top    - ep × (fvg.top - fvg.bottom)
    SL = ob_htf far edge (LONG: bottom, SHORT: top) — широкий, baseline.

  Stage 2: SL варьируется ТОЛЬКО в границах OB-htf (внутри его зоны).
    LONG:  SL = ob_htf.bottom + sp × (ob_htf.top    - ob_htf.bottom)
    SHORT: SL = ob_htf.top    - sp × (ob_htf.top    - ob_htf.bottom)
    sp=0  -> ob_htf far edge   (широкий)
    sp=1  -> ob_htf near edge  (тугой, прямо под FVG для LONG / над FVG для SHORT)
    entry = best Stage 1 для каждого варианта.
    TP = TP_const.

Прогон для FVG variants v1 и v2, группа ALL, no_entry=on, untouched=on.
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
ENTRY_GRID = np.arange(0.0, 1.01, 0.05)
SL_GRID = np.arange(0.0, 1.01, 0.05)


def precompute(sig, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 60 if sig["fvg_tf"] == "1h" else 120
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty: return None
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


def stage1_entry_in_fvg(cache):
    """Stage 1: entry варьируется в FVG, SL = ob_htf far edge."""
    rows = []
    for ep in ENTRY_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ep * (s["fvg_t"] - s["fvg_b"])
                sl = s["obh_b"]
            else:
                entry = s["fvg_t"] - ep * (s["fvg_t"] - s["fvg_b"])
                sl = s["obh_t"]
            tp = s["tp_const"]
            if s["direction"] == "LONG":
                if sl >= entry or tp <= entry: skipped += 1; continue
                risk = entry - sl
                rr = (tp - entry) / risk
            else:
                if sl <= entry or tp >= entry: skipped += 1; continue
                risk = sl - entry
                rr = (entry - tp) / risk
            outcome = simulate_no_entry(s, entry, sl, tp)
            if outcome == "win":
                wins += 1; pnl_r += rr; rr_sum += rr; n_with_rr += 1
            elif outcome == "loss":
                losses += 1; pnl_r -= 1.0; rr_sum += rr; n_with_rr += 1
            elif outcome == "no_entry": no_entry += 1
            elif outcome == "open": opens += 1
            else: nf += 1
        closed = wins + losses
        rows.append({
            "entry_pct": round(ep, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })
    return pd.DataFrame(rows)


def stage2_sl_in_obhtf(cache, ep_fixed):
    """Stage 2: SL варьируется внутри OB-htf, entry зафиксирован в FVG."""
    rows = []
    for sp in SL_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ep_fixed * (s["fvg_t"] - s["fvg_b"])
                sl_lo = s["obh_b"]; sl_hi = s["obh_t"]
                sl = sl_lo + sp * (sl_hi - sl_lo)
            else:
                entry = s["fvg_t"] - ep_fixed * (s["fvg_t"] - s["fvg_b"])
                sl_hi = s["obh_t"]; sl_lo = s["obh_b"]
                sl = sl_hi - sp * (sl_hi - sl_lo)
            tp = s["tp_const"]
            if s["direction"] == "LONG":
                if sl >= entry or tp <= entry: skipped += 1; continue
                risk = entry - sl
                rr = (tp - entry) / risk
            else:
                if sl <= entry or tp >= entry: skipped += 1; continue
                risk = sl - entry
                rr = (entry - tp) / risk
            outcome = simulate_no_entry(s, entry, sl, tp)
            if outcome == "win":
                wins += 1; pnl_r += rr; rr_sum += rr; n_with_rr += 1
            elif outcome == "loss":
                losses += 1; pnl_r -= 1.0; rr_sum += rr; n_with_rr += 1
            elif outcome == "no_entry": no_entry += 1
            elif outcome == "open": opens += 1
            else: nf += 1
        closed = wins + losses
        rows.append({
            "sl_pct": round(sp, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })
    return pd.DataFrame(rows)


def run_variant(variant: str, df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_1m):
    print()
    print("#" * 100)
    print(f"# FVG VARIANT: {variant}")
    print("#" * 100)
    raw = detect_strategy_1_1_3_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h,
        fvg_variant=variant, verbose=False,
    )
    print(f"  raw paths: {len(raw)}")

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]
    print(f"  ALL deduped: {len(deduped)}  cache: {len(cache)}")

    # Stage 1: entry в FVG
    df_s1 = stage1_entry_in_fvg(cache)
    df_s1_sorted = df_s1.sort_values("pnl_r", ascending=False)
    best_s1 = df_s1_sorted.iloc[0]
    print()
    print(f"--- Stage 1: entry в FVG, SL = ob_htf far edge ---")
    print(df_s1_sorted.head(10).to_string(index=False))
    print(f"\n  >>> Best ep = {best_s1['entry_pct']}  WR={best_s1['wr']}%  PnL={best_s1['pnl_r']}R  "
          f"R/trade={best_s1['r_per_trade']}  avg_RR={best_s1['avg_rr']}")

    ep_fixed = float(best_s1["entry_pct"])

    # Stage 2: SL в OB-htf
    df_s2 = stage2_sl_in_obhtf(cache, ep_fixed)
    df_s2_sorted = df_s2.sort_values("pnl_r", ascending=False)
    best_s2 = df_s2_sorted.iloc[0]
    print()
    print(f"--- Stage 2: ep={ep_fixed} (fixed), SL варьируется в OB-htf ---")
    print(df_s2_sorted.head(10).to_string(index=False))
    print(f"\n  >>> Best sl_pct = {best_s2['sl_pct']}  WR={best_s2['wr']}%  PnL={best_s2['pnl_r']}R  "
          f"R/trade={best_s2['r_per_trade']}  avg_RR={best_s2['avg_rr']}")
    baseline = df_s2[df_s2["sl_pct"] == 0.0].iloc[0]
    print(f"  Baseline (sl=0, ob_htf far edge) = Stage 1 best: WR={baseline['wr']}%  PnL={baseline['pnl_r']}R")

    return {"variant": variant, "n_cache": len(cache),
            "stage1": df_s1, "stage2": df_s2,
            "best_ep": best_s1["entry_pct"], "best_s1_pnl": best_s1["pnl_r"],
            "best_sl": best_s2["sl_pct"], "best_s2_pnl": best_s2["pnl_r"]}


def main() -> None:
    print(f"[INFO] 1.1.3 с новой геометрией: entry в FVG, SL в OB-htf. ALL only.")
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

    res_v1 = run_variant("v1", df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_1m)
    res_v2 = run_variant("v2", df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_1m)

    print()
    print("=" * 100)
    print("FINAL COMPARISON:")
    print("=" * 100)
    rows = [
        {"variant": "v1", "cache": res_v1["n_cache"],
         "best_ep": res_v1["best_ep"], "stage1_pnl": res_v1["best_s1_pnl"],
         "best_sl": res_v1["best_sl"], "stage2_pnl": res_v1["best_s2_pnl"]},
        {"variant": "v2", "cache": res_v2["n_cache"],
         "best_ep": res_v2["best_ep"], "stage1_pnl": res_v2["best_s1_pnl"],
         "best_sl": res_v2["best_sl"], "stage2_pnl": res_v2["best_s2_pnl"]},
    ]
    print(pd.DataFrame(rows).to_string(index=False))

    out = Path("signals/optimize_1_1_3_new_geometry.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([
        res_v1["stage1"].assign(variant="v1", stage="1"),
        res_v1["stage2"].assign(variant="v1", stage="2"),
        res_v2["stage1"].assign(variant="v2", stage="1"),
        res_v2["stage2"].assign(variant="v2", stage="2"),
    ]).to_csv(out, index=False)
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
