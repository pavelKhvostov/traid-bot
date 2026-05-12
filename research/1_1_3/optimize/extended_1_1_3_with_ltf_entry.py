"""1.1.3 extended: после первичного 1.1.3 fvg-сигнала ищем вторичный OB-1h/2h
+ FVG-15m/20m (как в 1.1.1) и торгуем по нему.

Pipeline:
  1. Берём 1.1.3 сигнал (top-OB → macro-OB → primary OB-htf + immediate FVG того же ТФ).
  2. SWEPT-фильтр на первичном ob_htf.
  3. После close(primary.fvg.c2) ищем в диапазоне:
       LONG : [close_c2 ... primary_ob_htf.bottom]
       SHORT: [primary_ob_htf.top ... close_c2]
     вторичный OB-1h ИЛИ OB-2h (earliest cur_time wins). Зона вторичного OB
     должна overlap с этим диапазоном.
  4. В вторичном OB ищем FVG-15m или FVG-20m в окне [ob.prev_time, ob.cur_time +
     (htf_min - 15/20)min] И overlap с OB.
  5. Финальный сигнал: entry/sl/tp по FVG-15m/20m + вторичный OB.

Invalidation вторичного поиска:
  при close на ТФ вторичного OB ниже primary_ob.bottom (LONG) / выше top (SHORT) —
  поиск прекращается.

Параметры (фикс):
  entry_pct = 0.8 в FVG-15m/20m
  sl_pct    = 0.35 в вторичном OB-1h/2h
  RR        = 2.2
  no_entry  = on
  без BE-trail
  macro_mode = extended
  group     = SWEPT (фильтр на первичном ob_htf)
  variant   = v1, v2 отдельно

Выход:
  signals/extended_1_1_3_ltf_v1_SWEPT.csv  (per-trade)
  signals/extended_1_1_3_ltf_v2_SWEPT.csv
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
from strategies.strategy_1_1_1 import (
    detect_ob_pair,
    detect_fvg,
    find_first_fvg_in_range,
    zones_overlap,
)
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
MACRO_MODE = "extended"
EP_PCT = 0.8
SL_PCT = 0.35
RR_TARGET = 2.2


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


def find_secondary_in_tf(
    df_htf: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    search_start: pd.Timestamp,
    range_bot: float,
    range_top: float,
    direction: str,
    htf_label: str,
):
    """Найти первый OB-htf overlap с диапазоном + FVG-15m/20m в нём.

    Invalidation: первая свеча, закрывшаяся за пределы диапазона
    [range_bot, range_top] (любая сторона) — поиск прекращается.
    """
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 2:
        return None
    htf_minutes = 60 if htf_label == "1h" else 120

    for i in range(1, n):
        # Invalidation: close за пределами диапазона (обе стороны).
        cur_close = float(df_window.iloc[i]["close"])
        if cur_close < range_bot or cur_close > range_top:
            return None
        # Detect OB-pair (i-1, i).
        cand = detect_ob_pair(df_window, i)
        if cand is None or cand.direction != direction:
            continue
        # OB overlap с диапазоном [range_bot, range_top].
        if not zones_overlap(cand.bottom, cand.top, range_bot, range_top):
            continue
        # FVG-15m в окне OB.
        fvg_15m = find_first_fvg_in_range(
            df_15m, cand.prev_time,
            cand.cur_time + pd.Timedelta(minutes=htf_minutes - 15),
            direction, cand.bottom, cand.top,
        )
        fvg_20m = find_first_fvg_in_range(
            df_20m, cand.prev_time,
            cand.cur_time + pd.Timedelta(minutes=htf_minutes - 20),
            direction, cand.bottom, cand.top,
        )
        if fvg_15m is None and fvg_20m is None:
            continue
        if fvg_15m is None:
            fvg_chosen, fvg_tf = fvg_20m, "20m"
        elif fvg_20m is None:
            fvg_chosen, fvg_tf = fvg_15m, "15m"
        else:
            if fvg_15m.c2_time <= fvg_20m.c2_time:
                fvg_chosen, fvg_tf = fvg_15m, "15m"
            else:
                fvg_chosen, fvg_tf = fvg_20m, "20m"
        return {
            "ob": cand, "ob_tf": htf_label,
            "fvg": fvg_chosen, "fvg_tf": fvg_tf,
        }
    return None


def find_secondary(primary_sig, df_1h, df_2h, df_15m, df_20m):
    """Earliest-wins на 1h vs 2h."""
    fvg_c2 = pd.Timestamp(primary_sig["fvg_c2_time"])
    if fvg_c2.tz is None: fvg_c2 = fvg_c2.tz_localize("UTC")
    primary_fvg_tf = primary_sig["fvg_tf"]
    primary_tf_min = 60 if primary_fvg_tf == "1h" else 120
    df_for_close = df_1h if primary_fvg_tf == "1h" else df_2h
    if fvg_c2 not in df_for_close.index:
        return None
    close_c2 = float(df_for_close.loc[fvg_c2, "close"])
    search_start = fvg_c2 + pd.Timedelta(minutes=primary_tf_min)

    primary_ob_bot, primary_ob_top = primary_sig["ob_htf_zone"]
    direction = primary_sig["direction"]
    if direction == "LONG":
        range_bot, range_top = primary_ob_bot, close_c2
    else:
        range_bot, range_top = close_c2, primary_ob_top
    if range_top <= range_bot:
        return None  # вырожденный диапазон

    sig_1h = find_secondary_in_tf(
        df_1h, df_15m, df_20m, search_start,
        range_bot, range_top, direction, "1h",
    )
    sig_2h = find_secondary_in_tf(
        df_2h, df_15m, df_20m, search_start,
        range_bot, range_top, direction, "2h",
    )
    if sig_1h is None and sig_2h is None:
        return None
    if sig_1h is None: return {**sig_2h, "close_c2": close_c2}
    if sig_2h is None: return {**sig_1h, "close_c2": close_c2}
    if sig_1h["ob"].cur_time <= sig_2h["ob"].cur_time:
        return {**sig_1h, "close_c2": close_c2}
    return {**sig_2h, "close_c2": close_c2}


def simulate_no_be(highs, lows, entry, sl, tp, direction):
    n = len(highs)
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
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def to_utc3(ts):
    if ts is None or ts == "": return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def run_variant(variant, dfs, out_dir):
    df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m = dfs
    print(f"\n[{variant}] detect 1.1.3 primary signals...")
    raw = detect_strategy_1_1_3_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h,
        fvg_variant=variant, macro_mode=MACRO_MODE, verbose=False,
    )
    # Dedup и SWEPT-фильтр
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept(s, df_1h, df_2h)
        if sw is None: continue
        groups[key].append({"sig": s, "swept": sw})
    primary_swept = []
    for k, paths in groups.items():
        any_swept = any(p["swept"] for p in paths)
        if not any_swept: continue
        primary_swept.append(paths[0]["sig"])
    print(f"  raw={len(raw)} primary_swept={len(primary_swept)}")

    # Поиск вторичных
    secondary_signals = []
    no_secondary = 0
    for primary in primary_swept:
        sec = find_secondary(primary, df_1h, df_2h, df_15m, df_20m)
        if sec is None:
            no_secondary += 1
            continue
        secondary_signals.append({"primary": primary, "secondary": sec})
    print(f"  secondary found: {len(secondary_signals)}  no_secondary: {no_secondary}")

    # Симуляция
    rows = []
    wins = losses = ne = nf = open_ct = skipped = 0
    for ss in secondary_signals:
        primary = ss["primary"]
        sec = ss["secondary"]
        fvg = sec["fvg"]
        ob = sec["ob"]
        direction = primary["direction"]
        fvg_w = fvg.top - fvg.bottom
        ob_h = ob.top - ob.bottom
        if direction == "LONG":
            entry = fvg.bottom + EP_PCT * fvg_w
            sl = ob.bottom + SL_PCT * ob_h
            if sl >= entry: skipped += 1; continue
            risk = entry - sl
            tp = entry + RR_TARGET * risk
        else:
            entry = fvg.top - EP_PCT * fvg_w
            sl = ob.top - SL_PCT * ob_h
            if sl <= entry: skipped += 1; continue
            risk = sl - entry
            tp = entry - RR_TARGET * risk
        tf_15_min = 15 if sec["fvg_tf"] == "15m" else 20
        fill_scan_start = fvg.c2_time + pd.Timedelta(minutes=tf_15_min)
        forward = df_1m[df_1m.index >= fill_scan_start]
        if forward.empty:
            nf += 1; continue
        highs = forward["high"].values.astype(np.float64)
        lows = forward["low"].values.astype(np.float64)
        outcome = simulate_no_be(highs, lows, entry, sl, tp, direction)
        if outcome == "win":     wins += 1
        elif outcome == "loss":  losses += 1
        elif outcome == "no_entry": ne += 1
        elif outcome == "open":  open_ct += 1
        else: nf += 1
        rows.append({
            "signal_time": to_utc3(fvg.c2_time),
            "direction": direction,
            "primary_top_tf": primary["top_tf"],
            "primary_macro_tf": primary["ob_macro_tf"],
            "primary_htf_tf": primary["ob_htf_tf"],
            "primary_fvg_tf": primary["fvg_tf"],
            "primary_close_c2": round(sec["close_c2"], 4),
            "primary_ob_htf_top": round(primary["ob_htf_zone"][1], 4),
            "primary_ob_htf_bottom": round(primary["ob_htf_zone"][0], 4),
            "sec_ob_tf": sec["ob_tf"],
            "sec_ob_top": round(ob.top, 4),
            "sec_ob_bottom": round(ob.bottom, 4),
            "sec_fvg_tf": sec["fvg_tf"],
            "sec_fvg_top": round(fvg.top, 4),
            "sec_fvg_bottom": round(fvg.bottom, 4),
            "entry": round(entry, 4),
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "risk_pct": round(risk / entry * 100, 4),
            "outcome": outcome,
        })

    closed = wins + losses
    pnl_r = wins * RR_TARGET - losses * 1.0
    print(f"  total={len(secondary_signals)} W={wins} L={losses} ne={ne} sk={skipped} nf={nf} open={open_ct}")
    if closed:
        print(f"  WR={wins/closed*100:.1f}%  PnL={pnl_r:+.2f}R  R/tr={pnl_r/closed:.3f}")
    long_w = sum(1 for r in rows if r["direction"]=="LONG" and r["outcome"]=="win")
    long_l = sum(1 for r in rows if r["direction"]=="LONG" and r["outcome"]=="loss")
    short_w = sum(1 for r in rows if r["direction"]=="SHORT" and r["outcome"]=="win")
    short_l = sum(1 for r in rows if r["direction"]=="SHORT" and r["outcome"]=="loss")
    long_pnl = long_w * RR_TARGET - long_l
    short_pnl = short_w * RR_TARGET - short_l
    if (long_w+long_l):
        print(f"  LONG: {long_w}W/{long_l}L WR={long_w/(long_w+long_l)*100:.1f}% PnL={long_pnl:+.1f}R")
    if (short_w+short_l):
        print(f"  SHORT: {short_w}W/{short_l}L WR={short_w/(short_w+short_l)*100:.1f}% PnL={short_pnl:+.1f}R")

    # By year
    if rows:
        df = pd.DataFrame(rows)
        df["t"] = pd.to_datetime(df["signal_time"])
        df["year"] = df["t"].dt.year
        closed_df = df[df["outcome"].isin(["win","loss"])]
        for y in sorted(closed_df["year"].unique()):
            sub = closed_df[closed_df["year"]==y]
            Wy = (sub["outcome"]=="win").sum()
            Ly = (sub["outcome"]=="loss").sum()
            wry = Wy/(Wy+Ly)*100 if (Wy+Ly) else 0
            pnly = Wy*RR_TARGET - Ly
            print(f"  {y}: n={Wy+Ly} WR={wry:.1f}% PnL={pnly:+.1f}R")

    out_csv = out_dir / f"extended_1_1_3_ltf_{variant}_SWEPT.csv"
    if rows:
        pd.DataFrame(rows).drop(columns=[]).to_csv(out_csv, index=False)
        print(f"  saved: {out_csv}")
    return {
        "variant": variant,
        "primary_swept": len(primary_swept),
        "secondary_found": len(secondary_signals),
        "no_secondary": no_secondary,
        "total": len(secondary_signals), "W": wins, "L": losses,
        "ne": ne, "sk": skipped, "nf": nf, "open": open_ct,
        "closed": closed,
        "wr": round(wins/closed*100, 1) if closed else 0,
        "pnl_r": round(pnl_r, 2),
        "r_per_trade": round(pnl_r/closed, 3) if closed else 0,
    }


def main():
    print(f"[INFO] 1.1.3 extended (LTF entry): primary 1.1.3 SWEPT -> secondary OB+FVG-15m/20m")
    print(f"  EP={EP_PCT} (in FVG-15m/20m), SL={SL_PCT} (in secondary OB), RR={RR_TARGET}")
    print(f"  macro_mode={MACRO_MODE}, group=SWEPT")

    df_1d  = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h  = load_df(SYMBOL, "4h")
    df_1h  = load_df(SYMBOL, "1h")
    df_6h  = compose_from_base(df_1h, "6h")
    df_2h  = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m  = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f  = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    out_dir = Path("signals")
    out_dir.mkdir(parents=True, exist_ok=True)

    dfs = (df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m)
    summary = []
    for variant in ["v1", "v2"]:
        s = run_variant(variant, dfs, out_dir)
        summary.append(s)

    print("\n" + "=" * 90)
    print("SUMMARY (SWEPT)")
    print("=" * 90)
    print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
