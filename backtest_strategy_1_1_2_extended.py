"""Бэктест Strategy 1.1.2 с extended_macro_search=True.

Сравнение baseline (старая логика macro) и extended (включает macro,
формирующиеся ПОСЛЕ закрытия cur top-OB).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
SL_TOLERANCE = 0.005


def to_utc3(ts) -> str:
    if ts is None or ts == "":
        return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def simulate_outcome(sig, df_1m, rr_ratio):
    direction = sig["direction"]
    entry = sig["entry"]
    sl = sig["sl"]
    risk = sig["risk"]
    signal_time = sig["signal_time"]
    if direction == "LONG":
        tp = entry + risk * rr_ratio
    else:
        tp = entry - risk * rr_ratio
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = signal_time + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]
    activation_time = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= entry: activation_time = ts; break
        else:
            if h >= entry: activation_time = ts; break
    base = {
        "signal_time": signal_time,
        "top_tf": sig.get("top_tf", "1d"),
        "ob_d_time": to_utc3(sig["ob_d_cur_time"]),
        "ob_macro_time": to_utc3(sig["ob_macro_cur_time"]),
        "ob_macro_tf": sig["ob_macro_tf"],
        "ob_htf_time": to_utc3(sig["ob_htf_cur_time"]),
        "ob_htf_tf": sig["ob_htf_tf"],
        "fvg_time": to_utc3(sig["fvg_c2_time"]),
        "fvg_tf": sig["fvg_tf"],
        "direction": direction, "entry": entry, "sl": sl, "tp": tp,
        "risk_pct": round(risk / entry * 100, 4),
        "fvg_top": sig["fvg_zone"][1], "fvg_bottom": sig["fvg_zone"][0],
    }
    if activation_time is None:
        return {**base, "outcome": "not_filled", "activation_time": ""}
    sim = df_1m[df_1m.index >= activation_time]
    outcome = "open"
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= sl: outcome = "loss"; break
            if h >= tp: outcome = "win"; break
        else:
            if h >= sl: outcome = "loss"; break
            if l <= tp: outcome = "win"; break
    return {**base, "outcome": outcome, "activation_time": to_utc3(activation_time)}


def dedupe(rows):
    primary = {}
    for r in rows:
        k = (r["signal_time"], r["direction"], round(float(r["entry"]), 8))
        primary.setdefault(k, []).append(r)
    out = []
    for k, group in primary.items():
        sorted_group = sorted(group, key=lambda r: float(r["sl"]))
        entry = float(k[2])
        cur_bucket = []
        cur_first_sl = None
        cur_outcome = None
        for r in sorted_group:
            sl = float(r["sl"])
            outc = r["outcome"]
            if cur_first_sl is None:
                cur_bucket = [r]; cur_first_sl = sl; cur_outcome = outc
                continue
            if abs(sl - cur_first_sl) / entry < SL_TOLERANCE and outc == cur_outcome:
                cur_bucket.append(r)
            else:
                out.append(cur_bucket[0])
                cur_bucket = [r]; cur_first_sl = sl; cur_outcome = outc
        if cur_bucket:
            out.append(cur_bucket[0])
    return out


def run_variant(name: str, extended: bool, dfs: dict) -> dict:
    print()
    print("=" * 90)
    print(f"VARIANT: {name}  (extended_macro_search={extended})")
    print("=" * 90)
    raw = detect_strategy_1_1_2_signals(
        dfs["1d_f"], dfs["12h_f"], dfs["4h"], dfs["6h"],
        dfs["1h"], dfs["2h"], dfs["15m"], dfs["20m"],
        extended_macro_search=extended, verbose=True,
    )
    print(f"  raw signals: {len(raw)}")

    results = {}
    for rr in [1.0, 2.2]:
        rows = [simulate_outcome(s, dfs["1m"], rr) for s in raw]
        deduped = dedupe(rows)
        df = pd.DataFrame(deduped)
        closed = df[df["outcome"].isin(["win", "loss"])]
        W = int((closed["outcome"] == "win").sum())
        L = int((closed["outcome"] == "loss").sum())
        nf = (df["outcome"] == "not_filled").sum()
        op = (df["outcome"] == "open").sum()
        wr = W / (W + L) * 100 if (W + L) else 0
        pnl = W * rr - L
        print(f"\n  RR={rr}: total={len(df)} closed={W+L} W={W} L={L} not_filled={nf} open={op}")
        print(f"           WR={wr:.1f}% PnL={pnl:+.1f}R R/trade={pnl / (W+L):.3f}" if (W+L) else "")
        if not closed.empty:
            cy = closed.copy()
            cy["t"] = pd.to_datetime(cy["fvg_time"])
            cy["year"] = cy["t"].dt.year
            for y in sorted(cy["year"].unique()):
                sub = cy[cy["year"] == y]
                Wy = int((sub["outcome"] == "win").sum())
                Ly = int((sub["outcome"] == "loss").sum())
                wry = Wy / (Wy + Ly) * 100 if (Wy + Ly) else 0
                pnly = Wy * rr - Ly
                print(f"    {y}: n={Wy+Ly} WR={wry:.1f}% PnL={pnly:+.1f}R")
        results[rr] = {"raw": len(raw), "deduped": len(deduped), "closed": W+L,
                       "wins": W, "losses": L, "wr": round(wr, 1),
                       "pnl_r": round(pnl, 2)}
    return results


def main():
    print(f"[INFO] Strategy 1.1.2 baseline vs extended, окно {DAYS_BACK}d")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    dfs = {
        "1d_f": df_1d[df_1d.index >= cutoff],
        "12h_f": df_12h[df_12h.index >= cutoff],
        "4h": df_4h, "6h": df_6h, "1h": df_1h, "2h": df_2h,
        "15m": df_15m, "20m": df_20m, "1m": df_1m,
    }

    res_base = run_variant("BASELINE", extended=False, dfs=dfs)
    res_ext = run_variant("EXTENDED", extended=True, dfs=dfs)

    print()
    print("=" * 90)
    print("СРАВНЕНИЕ BASELINE vs EXTENDED:")
    print("=" * 90)
    rows = []
    for rr in [1.0, 2.2]:
        rows.append({
            "RR": rr,
            "B_raw": res_base[rr]["raw"], "B_dedup": res_base[rr]["deduped"],
            "B_closed": res_base[rr]["closed"], "B_WR": res_base[rr]["wr"],
            "B_PnL": res_base[rr]["pnl_r"],
            "E_raw": res_ext[rr]["raw"], "E_dedup": res_ext[rr]["deduped"],
            "E_closed": res_ext[rr]["closed"], "E_WR": res_ext[rr]["wr"],
            "E_PnL": res_ext[rr]["pnl_r"],
            "Δ_PnL": round(res_ext[rr]["pnl_r"] - res_base[rr]["pnl_r"], 2),
        })
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
