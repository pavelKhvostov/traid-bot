"""1.1.3 grid: entry_pct × sl_pct @ RR=1.8, SWEPT only, v1 + v2.

Сетка:
  entry_pct ∈ [0.00, 1.00] step 0.05  (доля по диапазону FVG-htf:
      0 = ближняя к OB граница, 1 = дальняя)
  sl_pct LONG ∈ [0.00, 0.40] step 0.05  (от ob.bottom вверх внутрь OB)
  sl_pct SHORT ∈ [0.00, 0.60] step 0.05 (от ob.top  вниз внутрь OB)
  RR target = 1.8 (фикс)
  no_entry = ON (TP до entry → отмена)
  macro_mode = "extended"
  group = SWEPT (фрактальный sweep на 2 соседях слева)

Формулы SL:
  LONG  : SL = ob_htf.bottom + sl_pct × ob_height
  SHORT : SL = ob_htf.top    - sl_pct × ob_height

Если sl_pct > 0.4 для LONG → skip (вне заданного диапазона LONG).
Если sl_pct > 0.6 для SHORT → skip (по сетке такого нет, но защитимся).

Если SL >= entry (LONG) или SL <= entry (SHORT) → skip (некорректный сетап).

Выход:
  signals/grid_1_1_3_entry_sl_rr180_swept_v1.csv
  signals/grid_1_1_3_entry_sl_rr180_swept_v2.csv
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
RR_TARGET = 1.8
MACRO_MODE = "extended"
EP_GRID = np.round(np.arange(0.00, 1.0001, 0.05), 2)
SL_GRID = np.round(np.arange(0.00, 0.6001, 0.05), 2)
SL_LONG_MAX = 0.40
SL_SHORT_MAX = 0.60


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
        "lows":  forward["low"].values.astype(np.float64),
    }


def simulate_no_entry(s, entry, sl, tp):
    """Векторно: TP до entry → no_entry; затем SL/TP first-hit."""
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


def grid_for_variant(cache):
    rows = []
    for ep in EP_GRID:
        for sl_p in SL_GRID:
            wins = losses = nf = no_entry = opens = skipped = 0
            for s in cache:
                fvg_w = s["fvg_t"] - s["fvg_b"]
                ob_h  = s["obh_t"] - s["obh_b"]
                direction = s["direction"]
                # entry внутри FVG: ep=0 → ближняя к OB граница, ep=1 → дальняя
                # LONG: FVG над OB, ближняя = fvg.bottom; дальняя = fvg.top
                # SHORT: FVG под OB, ближняя = fvg.top; дальняя = fvg.bottom
                if direction == "LONG":
                    if sl_p > SL_LONG_MAX:
                        skipped += 1; continue
                    entry = s["fvg_b"] + ep * fvg_w
                    sl    = s["obh_b"] + sl_p * ob_h
                    if sl >= entry: skipped += 1; continue
                    risk = entry - sl
                    tp = entry + RR_TARGET * risk
                else:
                    if sl_p > SL_SHORT_MAX:
                        skipped += 1; continue
                    entry = s["fvg_t"] - ep * fvg_w
                    sl    = s["obh_t"] - sl_p * ob_h
                    if sl <= entry: skipped += 1; continue
                    risk = sl - entry
                    tp = entry - RR_TARGET * risk
                outcome = simulate_no_entry(s, entry, sl, tp)
                if outcome == "win":
                    wins += 1
                elif outcome == "loss":
                    losses += 1
                elif outcome == "no_entry":
                    no_entry += 1
                elif outcome == "open":
                    opens += 1
                else:
                    nf += 1
            closed = wins + losses
            pnl_r = wins * RR_TARGET - losses * 1.0
            rows.append({
                "ep": float(ep),
                "sl_pct": float(sl_p),
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
    print(f"[INFO] 1.1.3 grid (entry x sl) @ RR={RR_TARGET}, SWEPT only, "
          f"macro_mode={MACRO_MODE}, ep step=0.05, sl step=0.05")
    print(f"  EP_GRID: {EP_GRID.tolist()}")
    print(f"  SL_GRID: {SL_GRID.tolist()}")

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
        print(f"\n[{variant}] detect...")
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
        # SWEPT only
        cache = []
        for d in deduped:
            if not d["swept"]: continue
            c = precompute(d["sig"], df_1m)
            if c is None: continue
            cache.append(c)
        print(f"  raw={len(raw)} deduped={len(deduped)} SWEPT cache={len(cache)}")
        if not cache:
            print(f"  [WARN] empty SWEPT cache — пропускаю {variant}")
            continue

        df = grid_for_variant(cache)
        out_csv = out_dir / f"grid_1_1_3_entry_sl_rr180_swept_{variant}.csv"
        df.to_csv(out_csv, index=False)
        print(f"  saved: {out_csv} ({len(df)} cells)")

        # Top-15 by PnL
        print(f"\n  TOP-15 cells by PnL (variant={variant}):")
        top = df.sort_values("pnl_r", ascending=False).head(15)
        print(top.to_string(index=False))
        best = top.iloc[0]
        print(f"\n  >>> BEST {variant}: ep={best['ep']:.2f}, sl_pct={best['sl_pct']:.2f}, "
              f"W={best['wins']} L={best['losses']} ne={best['no_entry']} "
              f"WR={best['wr']}% PnL={best['pnl_r']}R R/tr={best['r_per_trade']}")
        summary.append({
            "variant": variant, "best_ep": best["ep"], "best_sl": best["sl_pct"],
            "wins": best["wins"], "losses": best["losses"],
            "no_entry": best["no_entry"], "closed": best["closed"],
            "wr": best["wr"], "pnl_r": best["pnl_r"], "r_per_trade": best["r_per_trade"],
        })

    if summary:
        print("\n" + "=" * 80)
        print("BEST per variant")
        print("=" * 80)
        print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
