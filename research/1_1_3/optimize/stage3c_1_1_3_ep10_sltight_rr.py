"""1.1.3: entry=close(c2), sl на ближней к рынку границе ob_htf, RR sweep, без BE.

Параметры:
  entry:
    LONG  : close(c2)
    SHORT : close(c2)
  sl (узкий, на ближней к рынку границе ob_htf):
    LONG  : sl = ob_htf.top
    SHORT : sl = ob_htf.bottom
  RR_target ∈ [1.0, 6.0] step 0.1
  TP = entry ± RR_target × risk
  no_entry: tp до entry -> отмена
  без BE-trail (классика)

Group: ALL и SWEPT отдельно.
Variant: v1, v2 отдельно (4 CSV).

Выход:
  signals/stage3c_1_1_3_ep10_sltight_<variant>_<group>.csv
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

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
MACRO_MODE = "extended"
RR_GRID = np.round(np.arange(1.0, 6.0001, 0.1), 2)


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
    c1l = float(df_top.iloc[prev_idx]["low"]);  c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx - 1]["low"]);  n2l = float(df_top.iloc[prev_idx - 2]["low"])
    n1h = float(df_top.iloc[prev_idx - 1]["high"]); n2h = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def precompute(sig, df_1h, df_2h, df_1m):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    fvg_tf = sig["fvg_tf"]
    tf_minutes = 60 if fvg_tf == "1h" else 120
    df_htf_for_close = df_1h if fvg_tf == "1h" else df_2h
    c2_time = pd.Timestamp(sig["fvg_c2_time"])
    if c2_time.tz is None:
        c2_time = c2_time.tz_localize("UTC")
    if c2_time not in df_htf_for_close.index:
        return None
    close_c2 = float(df_htf_for_close.loc[c2_time, "close"])
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "close_c2": close_c2,
        "highs": forward["high"].values.astype(np.float64),
        "lows":  forward["low"].values.astype(np.float64),
    }


def simulate_no_be(s, entry, sl, tp):
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


def grid_for(cache):
    rows = []
    for rr_target in RR_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        for s in cache:
            if s["direction"] == "LONG":
                entry = s["close_c2"]
                sl = s["obh_t"]                   # ближняя к рынку граница (узкий SL)
                if sl >= entry: skipped += 1; continue
                risk = entry - sl
                tp = entry + rr_target * risk
            else:
                entry = s["close_c2"]
                sl = s["obh_b"]                   # ближняя к рынку граница (узкий SL)
                if sl <= entry: skipped += 1; continue
                risk = sl - entry
                tp = entry - rr_target * risk
            outcome = simulate_no_be(s, entry, sl, tp)
            if outcome == "win": wins += 1
            elif outcome == "loss": losses += 1
            elif outcome == "no_entry": no_entry += 1
            elif outcome == "open": opens += 1
            else: nf += 1
        closed = wins + losses
        pnl_r = wins * rr_target - losses * 1.0
        rows.append({
            "rr": float(rr_target),
            "wins": wins, "losses": losses,
            "no_entry": no_entry, "skipped": skipped,
            "opens": opens, "nf": nf,
            "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
        })
    return pd.DataFrame(rows)


def main():
    print(f"[INFO] 1.1.3 stage3c: entry=close(c2), sl=ob_htf tight edge, "
          f"RR sweep [1.0..6.0], no BE, macro_mode={MACRO_MODE}")
    print()

    df_1d  = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h  = load_df(SYMBOL, "4h")
    df_1h  = load_df(SYMBOL, "1h")
    df_6h  = compose_from_base(df_1h, "6h")
    df_2h  = compose_from_base(df_1h, "2h")
    df_1m  = load_df(SYMBOL, "1m")

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f  = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    out_dir = Path("signals")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for variant in ["v1", "v2"]:
        print(f"[{variant}] detect...")
        raw = detect_strategy_1_1_3_signals(
            df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h,
            fvg_variant=variant, macro_mode=MACRO_MODE, verbose=False,
        )
        groups = defaultdict(list)
        for s in raw:
            key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
            sw = check_swept(s, df_1h, df_2h)
            if sw is None: continue
            groups[key].append({"sig": s, "swept": sw})
        deduped = []
        for k, paths in groups.items():
            rep = paths[0]["sig"]
            any_swept = any(p["swept"] for p in paths)
            deduped.append({"sig": rep, "swept": any_swept})
        cache_all = []
        for d in deduped:
            c = precompute(d["sig"], df_1h, df_2h, df_1m)
            if c is None: continue
            c["_swept"] = d["swept"]
            cache_all.append(c)
        cache_swept = [c for c in cache_all if c["_swept"]]
        print(f"  raw={len(raw)} ALL={len(cache_all)} SWEPT={len(cache_swept)}")
        for label, cache in [("ALL", cache_all), ("SWEPT", cache_swept)]:
            if not cache: continue
            df = grid_for(cache)
            out_csv = out_dir / f"stage3c_1_1_3_ep10_sltight_{variant}_{label}.csv"
            df.to_csv(out_csv, index=False)
            print(f"  saved: {out_csv}")
            top = df.sort_values("pnl_r", ascending=False).head(10)
            print(f"\n  TOP-10 by PnL ({variant}/{label}):")
            print(top.to_string(index=False))
            best = top.iloc[0]
            print(f"  >>> BEST {variant}/{label}: rr={best['rr']:.1f}  "
                  f"W={best['wins']} L={best['losses']} ne={best['no_entry']} "
                  f"sk={best['skipped']} WR={best['wr']}% PnL={best['pnl_r']}R "
                  f"R/tr={best['r_per_trade']}\n")
            summary.append({
                "variant": variant, "group": label,
                "best_rr": best["rr"],
                "wins": best["wins"], "losses": best["losses"],
                "no_entry": best["no_entry"], "skipped": best["skipped"],
                "closed": best["closed"], "wr": best["wr"],
                "pnl_r": best["pnl_r"], "r_per_trade": best["r_per_trade"],
            })

    if summary:
        print("=" * 100)
        print("BEST per (variant, group)")
        print("=" * 100)
        print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
