"""3-stage optimization для Strategy 1.1.2 (по аналогии с 1.1.1).

Stage 1: vary entry_pct (depth внутри FVG-htf), SL = ob_top edge, TP = TP_const, no_entry=on
Stage 2: entry = best Stage 1, vary sl_pct [ob_top edge -> fvg_htf edge], TP = TP_const
Stage 3: entry + SL фиксированы, vary RR [1.0..6.0] step 0.1

В 1.1.2 нет OB-htf, поэтому "wide SL" = ob_top edge (OB-1d/12h), а "tight SL"
= fvg_htf edge (граница 1h/2h FVG). SWEPT-фильтр не применяется (нет OB-htf пары).

TP_const = цена при default config (entry=mid FVG-htf, SL=ob_top edge, RR=1) —
сохраняется фиксированной во всех stages, чтобы Stage 1/2 двигали entry/SL
относительно той же цели.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_GRID = np.arange(0.0, 1.01, 0.05)
SL_GRID = np.arange(0.0, 1.01, 0.05)
RR_GRID = np.arange(1.0, 6.01, 0.1)


def precompute(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_htf_zone"]
    ob_b, ob_t = sig["ob_d_zone"]
    direction = sig["direction"]
    tf_minutes = 60 if sig["fvg_htf_tf"] == "1h" else 120
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    entry_mid = (fvg_b + fvg_t) / 2
    if direction == "LONG":
        risk_mid = entry_mid - ob_b
        tp_const = entry_mid + risk_mid
    else:
        risk_mid = ob_t - entry_mid
        tp_const = entry_mid - risk_mid
    return {
        "signal_time": sig["signal_time"],
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "ob_b": float(ob_b), "ob_t": float(ob_t),
        "tp_const": float(tp_const),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_no_entry(s: dict, entry: float, sl: float, tp: float) -> str:
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
    print(f"[INFO] Strategy 1.1.2 — 3-stage optimization, окно {DAYS_BACK}d")
    print()

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

    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, verbose=False,
    )
    print(f"  raw signals: {len(raw)}")

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    print(f"  deduped: {len(deduped)}")

    cache = [c for c in (precompute(s, df_1m) for s in deduped) if c is not None]
    print(f"  cache: {len(cache)}")
    out_dir = Path("signals"); out_dir.mkdir(parents=True, exist_ok=True)

    # ===================== STAGE 1 =====================
    print()
    print("=" * 100)
    print("Stage 1: vary entry_pct, SL=ob_top edge (sl_pct=0), TP=TP_const, no_entry=on")
    print("=" * 100)
    rows = []
    for ep in ENTRY_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            fw = s["fvg_t"] - s["fvg_b"]
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ep * fw
                sl = s["ob_b"]
            else:
                entry = s["fvg_t"] - ep * fw
                sl = s["ob_t"]
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
            outcome = simulate_no_entry(s, entry, sl, tp)
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
            "entry_pct": round(ep, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "nf": nf, "opens": opens, "skipped": skipped,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })
    df1 = pd.DataFrame(rows).sort_values("pnl_r", ascending=False)
    print(df1.to_string(index=False))
    best1 = df1.iloc[0]
    BEST_ENTRY = float(best1["entry_pct"])
    print(f"\n  >>> Stage 1 BEST entry_pct = {BEST_ENTRY}")
    print(f"      WR={best1['wr']}% PnL={best1['pnl_r']}R no_entry={best1['no_entry']} avg_RR={best1['avg_rr']}")
    df1.to_csv(out_dir / "optimize_1_1_2_stage1.csv", index=False)

    # ===================== STAGE 2 =====================
    print()
    print("=" * 100)
    print(f"Stage 2: entry_pct={BEST_ENTRY}, vary sl_pct [ob_top edge -> fvg_htf edge], TP=TP_const")
    print("=" * 100)
    rows = []
    for sp in SL_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            fw = s["fvg_t"] - s["fvg_b"]
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + BEST_ENTRY * fw
                sl_lo = s["ob_b"]; sl_hi = s["fvg_b"]
                sl = sl_lo + sp * (sl_hi - sl_lo)
            else:
                entry = s["fvg_t"] - BEST_ENTRY * fw
                sl_hi = s["ob_t"]; sl_lo = s["fvg_t"]
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
            outcome = simulate_no_entry(s, entry, sl, tp)
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
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })
    df2 = pd.DataFrame(rows).sort_values("pnl_r", ascending=False)
    print(df2.to_string(index=False))
    best2 = df2.iloc[0]
    BEST_SL = float(best2["sl_pct"])
    print(f"\n  >>> Stage 2 BEST sl_pct = {BEST_SL}")
    print(f"      WR={best2['wr']}% PnL={best2['pnl_r']}R no_entry={best2['no_entry']} avg_RR={best2['avg_rr']}")
    df2.to_csv(out_dir / "optimize_1_1_2_stage2.csv", index=False)

    # ===================== STAGE 3 =====================
    print()
    print("=" * 100)
    print(f"Stage 3: entry_pct={BEST_ENTRY}, sl_pct={BEST_SL}, vary RR [1.0..6.0] step 0.1")
    print("=" * 100)
    rows = []
    for rr_target in RR_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0
        for s in cache:
            fw = s["fvg_t"] - s["fvg_b"]
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + BEST_ENTRY * fw
                sl_lo = s["ob_b"]; sl_hi = s["fvg_b"]
                sl = sl_lo + BEST_SL * (sl_hi - sl_lo)
                if sl >= entry:
                    skipped += 1; continue
                risk = entry - sl
                tp = entry + rr_target * risk
            else:
                entry = s["fvg_t"] - BEST_ENTRY * fw
                sl_hi = s["ob_t"]; sl_lo = s["fvg_t"]
                sl = sl_hi - BEST_SL * (sl_hi - sl_lo)
                if sl <= entry:
                    skipped += 1; continue
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
            "rr": round(rr_target, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "nf": nf, "opens": opens, "skipped": skipped,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
        })
    df3 = pd.DataFrame(rows).sort_values("pnl_r", ascending=False)
    print(df3.to_string(index=False))
    best3 = df3.iloc[0]
    print(f"\n  >>> Stage 3 BEST RR = {best3['rr']}")
    print(f"      WR={best3['wr']}% PnL={best3['pnl_r']}R R/trade={best3['r_per_trade']}")
    df3.to_csv(out_dir / "optimize_1_1_2_stage3.csv", index=False)

    print()
    print("=" * 100)
    print("ИТОГ Strategy 1.1.2:")
    print(f"  entry_pct = {BEST_ENTRY}")
    print(f"  sl_pct    = {BEST_SL}")
    print(f"  RR        = {best3['rr']}")
    print(f"  → WR={best3['wr']}% PnL={best3['pnl_r']}R R/trade={best3['r_per_trade']}")


if __name__ == "__main__":
    main()
