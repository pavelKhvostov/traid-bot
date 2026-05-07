"""1.1.3 stage 2 (на базе stage 1 best): entry фикс на ep=1.0, TP const,
двигаем только SL внутри ob_htf.

Сетка по sl_pct внутри ob_htf-зоны:
  LONG  : sl = ob_htf.bottom + sl_pct * (ob_htf.top - ob_htf.bottom)
  SHORT : sl = ob_htf.top    - sl_pct * (ob_htf.top - ob_htf.bottom)

  sl_pct = 0 -> sl на дальней от рынка границе (= stage 1 base):
                LONG: sl = ob_htf.bottom; SHORT: sl = ob_htf.top
  sl_pct = 1 -> sl на ближней к рынку границе (узкий SL):
                LONG: sl = ob_htf.top;    SHORT: sl = ob_htf.bottom

Entry (фикс, ep=1.0):
  LONG  : entry = close(c2)
  SHORT : entry = close(c2)

TP (const, не меняется при движении SL):
  Расчёт из stage1 base: при entry=fvg.top/bottom, sl=ob_htf edge, RR=1.0
  LONG  : tp = 2*fvg.top    - ob_htf.bottom
  SHORT : tp = 2*fvg.bottom - ob_htf.top

Эффективный RR сделки растёт при увеличении sl_pct (узкий SL -> меньше риск,
тот же payoff в R от узкого риска), но WR падает (узкий SL легче пробить).

Skipped:
  - sl >= entry (LONG) / sl <= entry (SHORT)
  - tp <= entry (LONG) / tp >= entry (SHORT)

Параметры:
  macro_mode = "extended"
  group: ALL и SWEPT отдельно (4 CSV)
  fvg_variant: v1, v2 отдельно
  step = 0.05 -> 21 точка по sl_pct

Выход:
  signals/stage2_1_1_3_sl_const_tp_<variant>_<group>.csv
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
MACRO_MODE = "extended"
SL_GRID = np.round(np.arange(0.0, 1.0001, 0.05), 2)


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


def grid_for(cache):
    rows = []
    for sl_p in SL_GRID:
        wins = losses = nf = no_entry = opens = skipped = 0
        pnl_r = 0.0
        rr_sum = 0.0
        for s in cache:
            direction = s["direction"]
            close_c2 = s["close_c2"]
            obh_b = s["obh_b"]; obh_t = s["obh_t"]
            ob_h = obh_t - obh_b
            if direction == "LONG":
                base = s["fvg_t"]                          # fvg.top
                sl_for_tp = obh_b                          # дальняя от рынка
                entry = close_c2                           # ep=1.0
                sl = obh_b + sl_p * ob_h                   # двигаем sl вверх
                if sl >= entry: skipped += 1; continue
                tp = 2.0 * base - sl_for_tp                # const
                if tp <= entry: skipped += 1; continue
                risk = entry - sl
                rr_eff = (tp - entry) / risk
            else:
                base = s["fvg_b"]                          # fvg.bottom
                sl_for_tp = obh_t                          # дальняя от рынка
                entry = close_c2                           # ep=1.0
                sl = obh_t - sl_p * ob_h                   # двигаем sl вниз
                if sl <= entry: skipped += 1; continue
                tp = 2.0 * base - sl_for_tp                # const
                if tp >= entry: skipped += 1; continue
                risk = sl - entry
                rr_eff = (entry - tp) / risk
            outcome = simulate_no_entry(s, entry, sl, tp)
            if outcome == "win":
                wins += 1; pnl_r += rr_eff; rr_sum += rr_eff
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
            "sl_pct": float(sl_p),
            "wins": wins, "losses": losses,
            "no_entry": no_entry, "skipped": skipped,
            "opens": opens, "nf": nf,
            "closed": closed,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "r_per_trade": round(pnl_r / closed, 3) if closed else 0,
            "avg_rr_wins": round(rr_sum / wins, 3) if wins else 0,
        })
    return pd.DataFrame(rows)


def main():
    print(f"[INFO] 1.1.3 stage2 (sl-only, entry=close(c2), TP const), macro_mode={MACRO_MODE}")
    print(f"  SL_GRID step=0.05  ({len(SL_GRID)} points)")
    print(f"  sl_pct=0 -> sl на ob_htf edge (как stage1 base)")
    print(f"  sl_pct=1 -> sl на ближней к рынку границе ob_htf (узкий SL)")
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

    summary_rows = []
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
        print(f"  raw={len(raw)} deduped={len(deduped)} ALL={len(cache_all)} SWEPT={len(cache_swept)}")

        for label, cache in [("ALL", cache_all), ("SWEPT", cache_swept)]:
            if not cache:
                print(f"  [WARN] empty cache for {variant}/{label}")
                continue
            df = grid_for(cache)
            out_csv = out_dir / f"stage2_1_1_3_sl_const_tp_{variant}_{label}.csv"
            df.to_csv(out_csv, index=False)
            print(f"  saved: {out_csv}")
            top = df.sort_values("pnl_r", ascending=False).head(10)
            print(f"\n  TOP-10 by PnL ({variant}/{label}):")
            print(top.to_string(index=False))
            best = top.iloc[0]
            print(f"  >>> BEST {variant}/{label}: sl_pct={best['sl_pct']:.2f}  "
                  f"W={best['wins']} L={best['losses']} ne={best['no_entry']} "
                  f"sk={best['skipped']} WR={best['wr']}% PnL={best['pnl_r']}R "
                  f"R/tr={best['r_per_trade']} avgRR_w={best['avg_rr_wins']}\n")
            summary_rows.append({
                "variant": variant, "group": label,
                "best_sl_pct": best["sl_pct"],
                "wins": best["wins"], "losses": best["losses"],
                "no_entry": best["no_entry"], "skipped": best["skipped"],
                "closed": best["closed"], "wr": best["wr"],
                "pnl_r": best["pnl_r"], "r_per_trade": best["r_per_trade"],
                "avg_rr_wins": best["avg_rr_wins"],
            })

    if summary_rows:
        print("=" * 110)
        print("BEST per (variant, group)")
        print("=" * 110)
        print(pd.DataFrame(summary_rows).to_string(index=False))


if __name__ == "__main__":
    main()
