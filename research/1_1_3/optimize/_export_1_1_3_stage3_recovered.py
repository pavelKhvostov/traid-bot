"""1.1.3 Stage 3: ep=0.80, sl_pct=0.30 (= 18% inside OB-htf), vary RR.

Параметры:
  - entry_pct = 0.80 (в FVG)
  - sl_pct = 0.30 (в 60%-grid: SL = ob_htf.bottom + 0.18 × ob_height для LONG)
  - RR ∈ [1.0, 6.0] step 0.1
  - TP = entry ± RR × risk (честный, не TP_const)
  - no_entry = ON, macro_mode = "extended"

Сохраняет:
  signals/stage3_1_1_3_grid.csv         — full grid (RR sweep × variant × group)
  signals/stage3_1_1_3_positions_<best>.csv — per-trade для best
"""
from __future__ import annotations

# --- repo-root injection ---
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
ENTRY_PCT = 0.80
SL_PCT = 0.30
SL_DEPTH_RATIO = 0.6
RR_GRID = np.arange(1.0, 6.01, 0.1)


def to_utc3(ts):
    if ts is None or ts == "": return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def check_swept(sig, df_1h, df_2h):
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2: return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[prev_idx]["low"]); c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx - 1]["low"]); n2l = float(df_top.iloc[prev_idx - 2]["low"])
    n1h = float(df_top.iloc[prev_idx - 1]["high"]); n2h = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def precompute(sig, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 60 if sig["fvg_tf"] == "1h" else 120
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty: return None
    return {
        "sig": sig,
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_full(s, entry, sl, tp, df_1m):
    sig = s["sig"]
    signal_time = sig["signal_time"]
    tf_minutes = 60 if sig["fvg_tf"] == "1h" else 120
    fill_scan_start = signal_time + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]
    activation_time = None; no_entry = False
    direction = s["direction"]
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if h >= tp and activation_time is None:
                no_entry = True; break
            if l <= entry: activation_time = ts; break
        else:
            if l <= tp and activation_time is None:
                no_entry = True; break
            if h >= entry: activation_time = ts; break
    if no_entry: return ("no_entry", None, None, None, "no_entry", 0, 0)
    if activation_time is None: return ("not_filled", None, None, None, "not_filled", 0, 0)
    sim = df_1m[df_1m.index >= activation_time]
    outcome = "open"; exit_time = None; exit_price = None; hit_type = None
    mfe = 0.0; mae = 0.0
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            mfe = max(mfe, h - entry); mae = max(mae, entry - l)
            if l <= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"; break
            if h >= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"; break
        else:
            mfe = max(mfe, entry - l); mae = max(mae, h - entry)
            if h >= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"; break
            if l <= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"; break
    return (outcome, activation_time, exit_time, exit_price, hit_type or "open", mfe, mae)


def stage3_grid(cache, swept_filter, dfs):
    rows = []
    for rr_target in RR_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0
        for s in cache:
            if swept_filter is True and not s.get("_swept"): continue
            if swept_filter is False and s.get("_swept"): continue
            ob_height = s["obh_t"] - s["obh_b"]
            fvg_width = s["fvg_t"] - s["fvg_b"]
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ENTRY_PCT * fvg_width
                sl = s["obh_b"] + SL_PCT * SL_DEPTH_RATIO * ob_height
                if sl >= entry: skipped += 1; continue
                risk = entry - sl
                tp = entry + rr_target * risk
            else:
                entry = s["fvg_t"] - ENTRY_PCT * fvg_width
                sl = s["obh_t"] - SL_PCT * SL_DEPTH_RATIO * ob_height
                if sl <= entry: skipped += 1; continue
                risk = sl - entry
                tp = entry - rr_target * risk
            outcome, *_ = simulate_full(s, entry, sl, tp, dfs["1m"])
            if outcome == "win":
                wins += 1; pnl_r += rr_target
            elif outcome == "loss":
                losses += 1; pnl_r -= 1.0
            elif outcome == "no_entry": no_entry += 1
            elif outcome == "open": opens += 1
            else: nf += 1
        closed = wins + losses
        rows.append({
            "rr": round(rr_target, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "skipped": skipped, "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
        })
    return pd.DataFrame(rows)


def export_positions(cache, rr_target, dfs):
    rows = []
    for s in cache:
        sig = s["sig"]
        ob_height = s["obh_t"] - s["obh_b"]
        fvg_width = s["fvg_t"] - s["fvg_b"]
        if s["direction"] == "LONG":
            entry = s["fvg_b"] + ENTRY_PCT * fvg_width
            sl = s["obh_b"] + SL_PCT * SL_DEPTH_RATIO * ob_height
            if sl >= entry: continue
            risk = entry - sl
            tp = entry + rr_target * risk
        else:
            entry = s["fvg_t"] - ENTRY_PCT * fvg_width
            sl = s["obh_t"] - SL_PCT * SL_DEPTH_RATIO * ob_height
            if sl <= entry: continue
            risk = sl - entry
            tp = entry - rr_target * risk
        outcome, act_t, exit_t, exit_p, hit, mfe, mae = simulate_full(s, entry, sl, tp, dfs["1m"])
        rows.append({
            "signal_time": to_utc3(sig["signal_time"]),
            "direction": sig["direction"],
            "swept": "Y" if s.get("_swept") else "N",
            "macro_age": "OLD" if pd.Timestamp(sig["ob_macro_cur_time"]) < pd.Timestamp(sig["ob_d_cur_time"]) else "NEW",
            "top_tf": sig["top_tf"],
            "ob_d_time": to_utc3(sig["ob_d_cur_time"]),
            "ob_d_top": round(sig["ob_d_zone"][1], 2),
            "ob_d_bottom": round(sig["ob_d_zone"][0], 2),
            "ob_macro_tf": sig["ob_macro_tf"],
            "ob_macro_time": to_utc3(sig["ob_macro_cur_time"]),
            "ob_macro_top": round(sig["ob_macro_zone"][1], 2),
            "ob_macro_bottom": round(sig["ob_macro_zone"][0], 2),
            "ob_htf_tf": sig["ob_htf_tf"],
            "ob_htf_time": to_utc3(sig["ob_htf_cur_time"]),
            "ob_htf_top": round(sig["ob_htf_zone"][1], 2),
            "ob_htf_bottom": round(sig["ob_htf_zone"][0], 2),
            "fvg_tf": sig["fvg_tf"],
            "fvg_c2_time": to_utc3(sig["fvg_c2_time"]),
            "fvg_top": round(sig["fvg_zone"][1], 2),
            "fvg_bottom": round(sig["fvg_zone"][0], 2),
            "entry_pct": ENTRY_PCT, "sl_pct": SL_PCT, "rr_target": rr_target,
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "risk_abs": round(risk, 2),
            "risk_pct": round(risk / entry * 100, 4),
            "outcome": outcome,
            "activation_time": to_utc3(act_t) if act_t else "",
            "exit_time": to_utc3(exit_t) if exit_t else "",
            "exit_price": round(exit_p, 2) if exit_p else "",
            "hit_type": hit,
            "mfe_pct": round(mfe / entry * 100, 4) if entry else 0,
            "mae_pct": round(mae / entry * 100, 4) if entry else 0,
        })
    return rows


def main():
    print(f"[INFO] 1.1.3 Stage 3: ep={ENTRY_PCT}, sl_pct={SL_PCT} (= 18% inside OB-htf), vary RR [1..6]")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    dfs = {
        "1d_f": df_1d[df_1d.index >= cutoff],
        "12h_f": df_12h[df_12h.index >= cutoff],
        "4h": df_4h, "6h": df_6h, "1h": df_1h, "2h": df_2h, "1m": df_1m,
    }

    all_grids = []
    cache_by_variant = {}
    for variant in ["v1", "v2"]:
        print(f"\n[{variant}] detect...")
        raw = detect_strategy_1_1_3_signals(
            dfs["1d_f"], dfs["12h_f"], dfs["4h"], dfs["6h"], dfs["1h"], dfs["2h"],
            fvg_variant=variant, macro_mode="extended", verbose=False,
        )
        groups = defaultdict(list)
        for s in raw:
            key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
            sw = check_swept(s, dfs["1h"], dfs["2h"])
            if sw is None: continue
            groups[key].append({"sig": s, "swept": sw})
        deduped = []
        for k, paths in groups.items():
            rep = paths[0]["sig"]
            any_swept = any(p["swept"] for p in paths)
            deduped.append({"sig": rep, "swept": any_swept})
        cache = []
        for d in deduped:
            c = precompute(d["sig"], dfs["1m"])
            if c is None: continue
            c["_swept"] = d["swept"]
            cache.append(c)
        cache_by_variant[variant] = cache
        print(f"  raw={len(raw)} deduped={len(deduped)} cache={len(cache)}")

        for label, sw_filter in [("ALL", None), ("SWEPT", True), ("NOT-SWEPT", False)]:
            df = stage3_grid(cache, sw_filter, dfs)
            df["variant"] = variant
            df["group"] = label
            all_grids.append(df)

    grid_df = pd.concat(all_grids)[["variant", "group", "rr", "wins", "losses",
                                     "no_entry", "skipped", "closed", "wr", "pnl_r",
                                     "r_per_trade"]]
    out_grid = Path("signals/stage3_1_1_3_grid.csv")
    out_grid.parent.mkdir(parents=True, exist_ok=True)
    grid_df.to_csv(out_grid, index=False)
    print(f"\n  Grid saved: {out_grid} ({len(grid_df)} rows)")

    # Top by PnL per variant/group
    print()
    print("Top by PnL (each variant/group):")
    best_per_group = []
    for (v, g), sub in grid_df.groupby(["variant", "group"]):
        b = sub.sort_values("pnl_r", ascending=False).iloc[0]
        best_per_group.append((v, g, b))
        print(f"  {v}/{g}: best RR={b['rr']} W={b['wins']} L={b['losses']} "
              f"closed={b['closed']} WR={b['wr']}% PnL={b['pnl_r']}R R/tr={b['r_per_trade']}")

    # Best overall
    best = max(best_per_group, key=lambda x: x[2]["pnl_r"])
    BEST_VAR, BEST_GROUP, BEST_ROW = best
    BEST_RR = float(BEST_ROW["rr"])
    print(f"\n  >>> Overall best: {BEST_VAR}/{BEST_GROUP} RR={BEST_RR}")

    # Per-trade positions for best
    print(f"\n[positions] export {BEST_VAR}/{BEST_GROUP} RR={BEST_RR}...")
    cache = cache_by_variant[BEST_VAR]
    if BEST_GROUP == "SWEPT":
        cache = [c for c in cache if c.get("_swept")]
    elif BEST_GROUP == "NOT-SWEPT":
        cache = [c for c in cache if not c.get("_swept")]
    positions = export_positions(cache, BEST_RR, dfs)
    pos_df = pd.DataFrame(positions)
    pos_df.insert(0, "n", range(1, len(pos_df) + 1))
    out_pos = Path(f"signals/stage3_1_1_3_positions_{BEST_VAR}_{BEST_GROUP}_rr{int(BEST_RR*10):03d}.csv")
    pos_df.to_csv(out_pos, index=False)
    print(f"  Positions saved: {out_pos} ({len(pos_df)} rows)")
    outcomes = pos_df["outcome"].value_counts().to_dict()
    print(f"  Outcomes: {outcomes}")
    closed = pos_df[pos_df["outcome"].isin(["win","loss"])]
    if len(closed):
        w = (closed["outcome"]=="win").sum()
        l = (closed["outcome"]=="loss").sum()
        print(f"  closed={w+l} W={w} L={l} WR={w/(w+l)*100:.1f}% PnL={w*BEST_RR-l:+.2f}R")


if __name__ == "__main__":
    main()
