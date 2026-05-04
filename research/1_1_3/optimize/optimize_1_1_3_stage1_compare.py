"""Stage 1 на 1.1.3: vary entry_pct отдельно для SWEPT / NOT-SWEPT / ALL.

Геометрия 1.1.3:
  LONG:  FVG лежит ВЫШЕ OB-htf.top. Entry-диапазон = [OB-htf.top, FVG.top].
  SHORT: FVG лежит НИЖЕ OB-htf.bottom. Entry-диапазон = [FVG.bottom, OB-htf.bottom].

Параметры:
  - entry_pct ∈ [0..1] step 0.05
      ep=0 → entry на дальнем краю OB-htf (deep, между OB и FVG)
      ep=1 → entry на дальнем краю FVG (shallow)
  - SL = OB-htf far edge (LONG: bottom, SHORT: top)
  - TP = TP_const (price при default config: entry=mid FVG, SL=ob_htf far edge, RR=1)
  - no_entry: ON
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


def precompute(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 60 if sig["fvg_tf"] == "1h" else 120
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    # TP_const: цена при default config (entry=mid FVG, SL=ob_htf far edge, RR=1)
    entry_mid = (fvg_b + fvg_t) / 2
    if direction == "LONG":
        risk_mid = entry_mid - obh_b   # SL = ob_htf.bottom
        tp_const = entry_mid + risk_mid
    else:
        risk_mid = obh_t - entry_mid   # SL = ob_htf.top
        tp_const = entry_mid - risk_mid
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
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


def stage1_grid(cache: list[dict], group_name: str) -> pd.DataFrame:
    rows = []
    for ep in ENTRY_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            # Entry-диапазон: [ob_htf far edge ... fvg far edge]
            if s["direction"] == "LONG":
                # deep = ob_htf.top, shallow = fvg.top
                entry = s["obh_t"] + ep * (s["fvg_t"] - s["obh_t"])
                sl = s["obh_b"]
            else:
                # deep = ob_htf.bottom, shallow = fvg.bottom
                entry = s["obh_b"] - ep * (s["obh_b"] - s["fvg_b"])
                sl = s["obh_t"]
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
            "group": group_name,
            "entry_pct": round(ep, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })
    return pd.DataFrame(rows)


def main() -> None:
    print(f"[INFO] Stage 1 на 1.1.3: SWEPT/NOT-SWEPT/ALL, entry_pct over [ob_htf far edge..fvg far edge]")
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

    raw = detect_strategy_1_1_3_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, verbose=False,
    )
    print(f"  raw paths: {len(raw)}")

    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept_for_path(s, df_1h, df_2h)
        if sw is None:
            continue
        groups[key].append({"sig": s, "swept": sw})

    swept_reps = [next(p["sig"] for p in paths if p["swept"])
                  for key, paths in groups.items() if any(p["swept"] for p in paths)]
    not_swept_reps = [paths[0]["sig"]
                      for key, paths in groups.items() if not any(p["swept"] for p in paths)]
    all_reps = [paths[0]["sig"] for key, paths in groups.items()]

    cache_swept = [c for c in (precompute(s, df_1m) for s in swept_reps) if c is not None]
    cache_not_swept = [c for c in (precompute(s, df_1m) for s in not_swept_reps) if c is not None]
    cache_all = [c for c in (precompute(s, df_1m) for s in all_reps) if c is not None]

    print(f"  SWEPT cache: {len(cache_swept)}")
    print(f"  NOT-SWEPT cache: {len(cache_not_swept)}")
    print(f"  ALL cache: {len(cache_all)}")

    df_swept = stage1_grid(cache_swept, "SWEPT")
    df_not_swept = stage1_grid(cache_not_swept, "NOT-SWEPT")
    df_all = stage1_grid(cache_all, "ALL")

    for label, df, cache_size in [
        ("SWEPT", df_swept, len(cache_swept)),
        ("NOT-SWEPT", df_not_swept, len(cache_not_swept)),
        ("ALL", df_all, len(cache_all)),
    ]:
        print()
        print("=" * 100)
        print(f"Stage 1 -- {label} (cache={cache_size})")
        print("=" * 100)
        df_sorted = df.sort_values("pnl_r", ascending=False)
        print(df_sorted.drop(columns=["group"]).to_string(index=False))
        best = df_sorted.iloc[0]
        print(f"\n  >>> Best entry_pct = {best['entry_pct']}")
        print(f"      W={best['wins']} L={best['losses']} no_entry={best['no_entry']} "
              f"WR={best['wr']}% PnL={best['pnl_r']}R R/trade={best['r_per_trade']} avg_RR={best['avg_rr']}")

    print()
    print("=" * 100)
    print("СВОДКА -- best entry_pct в каждой группе:")
    print("=" * 100)
    summary = []
    for label, df in [("SWEPT", df_swept), ("NOT-SWEPT", df_not_swept), ("ALL", df_all)]:
        best = df.sort_values("pnl_r", ascending=False).iloc[0]
        summary.append({
            "group": label,
            "best_entry_pct": best["entry_pct"],
            "wins": best["wins"], "losses": best["losses"], "no_entry": best["no_entry"],
            "closed": best["closed"], "wr": best["wr"], "pnl_r": best["pnl_r"],
            "r_per_trade": best["r_per_trade"], "avg_rr": best["avg_rr"],
        })
    print(pd.DataFrame(summary).to_string(index=False))

    out = Path("signals/optimize_1_1_3_stage1_compare.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([df_swept, df_not_swept, df_all]).to_csv(out, index=False)
    print(f"\n  saved: {out}")


if __name__ == "__main__":
    main()
