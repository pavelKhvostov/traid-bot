"""1.1.3 stage 3: RR sweep с/без BE-trailing.

Параметры (фикс из stage 1+2):
  entry = close(c2)                                          (ep = 1.0)
  sl_initial:
    LONG  = ob_htf.bottom + 0.5 * (ob_htf.top - ob_htf.bottom)
    SHORT = ob_htf.top    - 0.5 * (ob_htf.top - ob_htf.bottom)
  RR_target ∈ [1.0, 6.0] step 0.1
  TP = entry ± RR_target × risk_initial   (стандартный RR-based TP)

BE-trailing (новая логика):
  Когда цена достигает уровня +1R от entry (= entry ± risk_initial),
  SL переносится в безубыток (sl = entry).
  Если цена потом возвращается к entry → выход с 0R (BE-exit).

Каждая сделка симулируется ДВАЖДЫ: с BE и без — для прямого сравнения.

no_entry: tp_initial достигнут до entry → отмена (одинаково для обеих).

Outcomes:
  no_be:    win / loss / no_entry / not_filled / open
  with_be:  win / loss / be / no_entry / not_filled / open
            be = достигли +1R, потом цена вернулась в entry

Параметры:
  macro_mode = "extended"
  group: ALL и SWEPT отдельно (4 CSV)
  fvg_variant: v1, v2 отдельно

Выход:
  signals/stage3_1_1_3_rr_be_<variant>_<group>.csv
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

DAYS_BACK = 2310
SYMBOL = "BTCUSDT"
MACRO_MODE = "extended"
SL_PCT = 0.5
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
    start = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    # ограничение forward 30 днями — иначе OOM на 6.3y
    end = start + pd.Timedelta(days=30)
    forward = df_1m[(df_1m.index >= start) & (df_1m.index < end)]
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
    """Классика: SL/TP first-hit, no BE-trail."""
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


def simulate_with_be(s, entry, sl_initial, tp, be_trigger):
    """SL/TP/BE-trigger. При hit BE-trigger (= entry + 1R) → sl=entry.

    Tie-handling:
      - SL vs другие в одном баре: SL побеждает (pessimistic).
      - TP vs BE-trigger в одном баре: TP побеждает (optimistic; цена прошла оба уровня).
      - В фазе после BE: BE-exit vs TP в одном баре: BE-exit побеждает (pessimistic).
    """
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    direction = s["direction"]
    if direction == "LONG":
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
    if direction == "LONG":
        sl_mask = post_l <= sl_initial
        tp_mask = post_h >= tp
        be_mask = post_h >= be_trigger
    else:
        sl_mask = post_h >= sl_initial
        tp_mask = post_l <= tp
        be_mask = post_l <= be_trigger

    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    be_first = int(np.argmax(be_mask)) if be_mask.any() else -1

    BIG = n + 10
    sl_i = sl_first if sl_first != -1 else BIG
    tp_i = tp_first if tp_first != -1 else BIG
    be_i = be_first if be_first != -1 else BIG

    # SL pessimistic: при равенстве sl с другими -> loss.
    if sl_i <= tp_i and sl_i <= be_i:
        if sl_i == BIG: return "open"
        return "loss"
    # TP перед BE (или equal -> TP optimistic).
    if tp_i <= be_i:
        return "win"
    # BE первый: переключаем sl на entry.
    # Дальше после be_i ищем (entry vs tp).
    after_l = post_l[be_i:]
    after_h = post_h[be_i:]
    if direction == "LONG":
        be_exit_mask = after_l <= entry
        tp_after_mask = after_h >= tp
    else:
        be_exit_mask = after_h >= entry
        tp_after_mask = after_l <= tp
    be_exit_first = int(np.argmax(be_exit_mask)) if be_exit_mask.any() else -1
    tp_after_first = int(np.argmax(tp_after_mask)) if tp_after_mask.any() else -1
    if be_exit_first == -1 and tp_after_first == -1: return "open"
    if be_exit_first == -1: return "win"
    if tp_after_first == -1: return "be"
    # Tie pessimistic: BE-exit побеждает (sl_now=entry triggered ≤ tp).
    return "win" if tp_after_first < be_exit_first else "be"


def grid_for(cache):
    rows = []
    for rr_target in RR_GRID:
        # no_be counters
        w_nb = l_nb = ne_nb = nf_nb = op_nb = sk = 0
        # with_be counters
        w_wb = l_wb = be_wb = ne_wb = nf_wb = op_wb = 0
        for s in cache:
            ob_h = s["obh_t"] - s["obh_b"]
            if s["direction"] == "LONG":
                entry = s["close_c2"]
                sl = s["obh_b"] + SL_PCT * ob_h
                if sl >= entry: sk += 1; continue
                risk = entry - sl
                tp = entry + rr_target * risk
                be_trigger = entry + risk
            else:
                entry = s["close_c2"]
                sl = s["obh_t"] - SL_PCT * ob_h
                if sl <= entry: sk += 1; continue
                risk = sl - entry
                tp = entry - rr_target * risk
                be_trigger = entry - risk

            o_nb = simulate_no_be(s, entry, sl, tp)
            if   o_nb == "win":      w_nb += 1
            elif o_nb == "loss":     l_nb += 1
            elif o_nb == "no_entry": ne_nb += 1
            elif o_nb == "open":     op_nb += 1
            else:                    nf_nb += 1

            o_wb = simulate_with_be(s, entry, sl, tp, be_trigger)
            if   o_wb == "win":      w_wb += 1
            elif o_wb == "loss":     l_wb += 1
            elif o_wb == "be":       be_wb += 1
            elif o_wb == "no_entry": ne_wb += 1
            elif o_wb == "open":     op_wb += 1
            else:                    nf_wb += 1

        c_nb = w_nb + l_nb
        c_wb = w_wb + l_wb + be_wb
        pnl_nb = w_nb * rr_target - l_nb
        pnl_wb = w_wb * rr_target - l_wb       # be вклад в PnL = 0
        rows.append({
            "rr": float(rr_target),
            # no_be
            "w_nb": w_nb, "l_nb": l_nb, "ne_nb": ne_nb,
            "wr_nb": round(w_nb / c_nb * 100, 1) if c_nb else 0,
            "pnl_nb": round(pnl_nb, 2),
            "rtr_nb": round(pnl_nb / c_nb, 3) if c_nb else 0,
            # with_be
            "w_wb": w_wb, "l_wb": l_wb, "be_wb": be_wb, "ne_wb": ne_wb,
            "wr_wb": round(w_wb / (w_wb + l_wb) * 100, 1) if (w_wb + l_wb) else 0,
            "pnl_wb": round(pnl_wb, 2),
            "rtr_wb": round(pnl_wb / c_wb, 3) if c_wb else 0,
            "delta_pnl": round(pnl_wb - pnl_nb, 2),
            "skipped": sk,
        })
    return pd.DataFrame(rows)


def main():
    print(f"[INFO] 1.1.3 stage3 (RR sweep with/without BE-trail), macro_mode={MACRO_MODE}")
    print(f"  entry = close(c2), sl_pct = {SL_PCT}, RR in [1.0..6.0] step 0.1")
    print(f"  BE-trail: at +1R from entry, sl -> entry (BE)")
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
            out_csv = out_dir / f"stage3_1_1_3_rr_be_{variant}_{label}_6y.csv"
            df.to_csv(out_csv, index=False)
            print(f"  saved: {out_csv}")
            top_nb = df.sort_values("pnl_nb", ascending=False).head(8)
            top_wb = df.sort_values("pnl_wb", ascending=False).head(8)
            print(f"\n  TOP-8 by PnL_no_be ({variant}/{label}):")
            print(top_nb[["rr","w_nb","l_nb","ne_nb","wr_nb","pnl_nb","rtr_nb","pnl_wb","delta_pnl"]].to_string(index=False))
            print(f"\n  TOP-8 by PnL_with_be ({variant}/{label}):")
            print(top_wb[["rr","w_wb","l_wb","be_wb","ne_wb","wr_wb","pnl_wb","rtr_wb","pnl_nb","delta_pnl"]].to_string(index=False))
            best_nb = top_nb.iloc[0]
            best_wb = top_wb.iloc[0]
            print(f"  >>> BEST {variant}/{label} no_be: rr={best_nb['rr']:.1f} "
                  f"WR={best_nb['wr_nb']}% PnL={best_nb['pnl_nb']}R")
            print(f"  >>> BEST {variant}/{label} with_be: rr={best_wb['rr']:.1f} "
                  f"WR={best_wb['wr_wb']}% PnL={best_wb['pnl_wb']}R "
                  f"(no_be at same rr: {best_wb['pnl_nb']}R, delta={best_wb['delta_pnl']:+.2f})\n")
            summary_rows.append({
                "variant": variant, "group": label,
                "best_rr_nb": best_nb["rr"],
                "pnl_nb": best_nb["pnl_nb"],
                "best_rr_wb": best_wb["rr"],
                "pnl_wb": best_wb["pnl_wb"],
                "delta_at_best_wb": best_wb["delta_pnl"],
            })

    if summary_rows:
        print("=" * 100)
        print("BEST per (variant, group)")
        print("=" * 100)
        print(pd.DataFrame(summary_rows).to_string(index=False))


if __name__ == "__main__":
    main()
