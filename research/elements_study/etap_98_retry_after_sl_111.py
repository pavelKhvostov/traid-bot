"""etap_98: Strategy 1.1.1 retry-after-SL — улучшает ли статистику повторный
вход в зоне FVG-macro если первый стопнут.

Гипотеза пользователя: сейчас в зоне FVG-macro (4h/6h) ищется ОДНА реакция
(один OB-htf + entry FVG). Если зона остаётся валидна (фрактал-инвалидатор
ещё не сформировался), но первый вход был выбит SL — взять следующий OB-htf
с entry FVG.

Сравнение:
  baseline = текущий one-shot (первый OB-htf в зоне, остальные игнорятся)
  retry    = chain. После loss берём следующий OB-htf, чей entry FVG c2_close
             > времени SL предыдущего. Останавливаемся на win/open/nf/no_entry.

Параметры live-approved 1.1.1: entry=0.80, sl=0.35 sym, RR=2.2, SWEPT ON.
SL формула: SL = obh_b + 0.35 × (fvg_b - obh_b)  (LONG), зеркально SHORT.
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
    OBZone,
    FVGZone,
    collect_valid_macro_fvgs,
    detect_fvg,
    detect_ob_pair,
    find_first_fvg_in_range,
    zones_overlap,
)

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_PCT = 0.80
SL_PCT = 0.35
RR = 2.2


# -------------------------------------------------------------------
# Modified detector: возвращает ВСЕ valid (OB-htf, entry-FVG) в окне
# FVG-macro зоны, до момента fractal-инвалидации (как в оригинале).
# -------------------------------------------------------------------
def find_all_signals_in_htf(
    df_htf: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    ob_d: OBZone,
    fvg_macro: FVGZone,
    search_start: pd.Timestamp,
    htf_minutes: int,
    htf_label: str,
) -> list[dict]:
    """То же что find_signal_in_htf, но не return на первом совпадении —
    собирает ВСЕ валидные пары (OB-htf, entry-FVG) до фрактал-инвалидации."""
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 2:
        return []

    direction = ob_d.direction
    fvg_top = fvg_macro.top
    fvg_bottom = fvg_macro.bottom
    highs = df_window["high"].values
    lows = df_window["low"].values

    out: list[dict] = []
    fractal_confirm_idx: int | None = None

    for i in range(n):
        if i >= 4 and fractal_confirm_idx is None:
            j = i - 2
            f_low = float(lows[j])
            f_high = float(highs[j])
            is_ll = (
                f_low < float(lows[j - 2]) and f_low < float(lows[j - 1])
                and f_low < float(lows[j + 1]) and f_low < float(lows[j + 2])
            )
            is_hh = (
                f_high > float(highs[j - 2]) and f_high > float(highs[j - 1])
                and f_high > float(highs[j + 1]) and f_high > float(highs[j + 2])
            )
            if direction == "LONG" and is_ll and f_low < fvg_bottom:
                fractal_confirm_idx = i
            elif direction == "SHORT" and is_hh and f_high > fvg_top:
                fractal_confirm_idx = i

        if fractal_confirm_idx is not None and i > fractal_confirm_idx:
            break

        if i >= 1:
            cand = detect_ob_pair(df_window, i)
            if cand is not None and cand.direction == direction \
               and zones_overlap(cand.bottom, cand.top, fvg_bottom, fvg_top) \
               and zones_overlap(cand.bottom, cand.top, ob_d.bottom, ob_d.top):
                fvg_15m = find_first_fvg_in_range(
                    df_15m,
                    cand.prev_time,
                    cand.cur_time + pd.Timedelta(minutes=htf_minutes - 15),
                    direction, cand.bottom, cand.top,
                )
                fvg_20m = find_first_fvg_in_range(
                    df_20m,
                    cand.prev_time,
                    cand.cur_time + pd.Timedelta(minutes=htf_minutes - 20),
                    direction, cand.bottom, cand.top,
                )
                if fvg_15m is not None or fvg_20m is not None:
                    if fvg_15m is None:
                        fvg_entry, fvg_tf = fvg_20m, "20m"
                    elif fvg_20m is None:
                        fvg_entry, fvg_tf = fvg_15m, "15m"
                    else:
                        if fvg_15m.c2_time <= fvg_20m.c2_time:
                            fvg_entry, fvg_tf = fvg_15m, "15m"
                        else:
                            fvg_entry, fvg_tf = fvg_20m, "20m"
                    out.append({
                        "ob_htf": cand,
                        "htf_label": htf_label,
                        "fvg_entry": fvg_entry,
                        "fvg_tf": fvg_tf,
                    })
    return out


def detect_multi_signals(
    df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m
) -> dict[tuple, list[dict]]:
    """Возвращает словарь macro_group_id -> список сигналов внутри неё."""
    groups: dict[tuple, list[dict]] = {}

    def _scan(df_top, top_tf_hours, top_label):
        if df_top is None or df_top.empty:
            return
        for idx in range(1, len(df_top)):
            ob_top = detect_ob_pair(df_top, idx)
            if ob_top is None:
                continue
            valid_4h = collect_valid_macro_fvgs(df_4h, ob_top, htf_hours=4, top_tf_hours=top_tf_hours)
            valid_6h = collect_valid_macro_fvgs(df_6h, ob_top, htf_hours=6, top_tf_hours=top_tf_hours)
            for fvg_macro, macro_tf in [(f, "4h") for f in valid_4h] + [(f, "6h") for f in valid_6h]:
                search_start = ob_top.cur_time + pd.Timedelta(hours=top_tf_hours)
                pairs_1h = find_all_signals_in_htf(df_1h, df_15m, df_20m, ob_top, fvg_macro, search_start, 60, "1h")
                pairs_2h = find_all_signals_in_htf(df_2h, df_15m, df_20m, ob_top, fvg_macro, search_start, 120, "2h")
                all_pairs = pairs_1h + pairs_2h
                if not all_pairs:
                    continue
                all_pairs.sort(key=lambda p: p["fvg_entry"].c2_time)

                gid = (top_label, ob_top.cur_time, macro_tf, fvg_macro.c2_time, ob_top.direction)
                records = []
                for p in all_pairs:
                    ob_htf = p["ob_htf"]
                    fvg_entry = p["fvg_entry"]
                    records.append({
                        "group_id": gid,
                        "direction": ob_top.direction,
                        "signal_time": fvg_entry.c2_time,
                        "top_tf": top_label,
                        "ob_d_cur_time": ob_top.cur_time,
                        "ob_d_prev_time": ob_top.prev_time,
                        "ob_d_zone": (ob_top.bottom, ob_top.top),
                        "fvg_macro_tf": macro_tf,
                        "fvg_macro_c2_time": fvg_macro.c2_time,
                        "fvg_macro_zone": (fvg_macro.bottom, fvg_macro.top),
                        "ob_htf_tf": p["htf_label"],
                        "ob_htf_prev_time": ob_htf.prev_time,
                        "ob_htf_cur_time": ob_htf.cur_time,
                        "ob_htf_zone": (ob_htf.bottom, ob_htf.top),
                        "fvg_tf": p["fvg_tf"],
                        "fvg_c0_time": fvg_entry.c0_time,
                        "fvg_c2_time": fvg_entry.c2_time,
                        "fvg_zone": (fvg_entry.bottom, fvg_entry.top),
                    })
                groups.setdefault(gid, []).extend(records)

    _scan(df_1d, 24, "1d")
    _scan(df_12h, 12, "12h")
    return groups


# -------------------------------------------------------------------
# SWEPT filter (same as stage3)
# -------------------------------------------------------------------
def check_swept(sig: dict, df_1h: pd.DataFrame, df_2h: pd.DataFrame) -> bool | None:
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


# -------------------------------------------------------------------
# Simulation (one trade) — return (outcome, exit_time, entry, sl, tp).
# Применяется approved формула sym SL: sl = obh_b + sl_pct*(fb - obh_b).
# -------------------------------------------------------------------
def simulate_one(sig: dict, df_1m: pd.DataFrame, entry_pct: float, sl_pct: float, rr: float):
    fb, ft = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + entry_pct * fw
        sl = obh_b + sl_pct * (fb - obh_b)
        if sl >= entry:
            return "skipped", None, entry, sl, None
        risk = entry - sl
        tp = entry + rr * risk
    else:
        entry = ft - entry_pct * fw
        sl = obh_t - sl_pct * (obh_t - ft)
        if sl <= entry:
            return "skipped", None, entry, sl, None
        risk = sl - entry
        tp = entry - rr * risk

    tf_min = 15 if sig["fvg_tf"] == "15m" else 20
    fill_start = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    forward = df_1m[df_1m.index >= fill_start]
    if forward.empty:
        return "nf", None, entry, sl, tp

    highs = forward["high"].values.astype(np.float64)
    lows = forward["low"].values.astype(np.float64)
    idx_ts = forward.index
    n = len(highs)
    if direction == "LONG":
        ent_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
    else:
        ent_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    if tp_pre_i < ent_i:
        return "no_entry", (idx_ts[tp_pre_i] if tp_pre_i < n else None), entry, sl, tp
    if ent_i >= n:
        return "nf", None, entry, sl, tp
    post_l = lows[ent_i:]; post_h = highs[ent_i:]
    post_ts = idx_ts[ent_i:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_f = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_f = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_f == -1 and tp_f == -1:
        return "open", None, entry, sl, tp
    if sl_f == -1:
        return "win", post_ts[tp_f], entry, sl, tp
    if tp_f == -1:
        return "loss", post_ts[sl_f], entry, sl, tp
    if tp_f < sl_f:
        return "win", post_ts[tp_f], entry, sl, tp
    return "loss", post_ts[sl_f], entry, sl, tp


# -------------------------------------------------------------------
# Run experiment: baseline (one-shot) vs retry (chain after SL)
# -------------------------------------------------------------------
def run_experiment(groups, df_1m, df_1h, df_2h, mode: str) -> list[dict]:
    """mode: 'baseline' or 'retry'."""
    trades = []
    for gid, gsigs in groups.items():
        # SWEPT filter — оставляем только сигналы, чей OB-htf прошёл SWEPT
        swept = []
        for s in gsigs:
            sw = check_swept(s, df_1h, df_2h)
            if sw is True:
                swept.append(s)
        if not swept:
            continue
        # gsigs пришли отсортированы по fvg_c2_time (см. detect_multi_signals)
        swept.sort(key=lambda x: x["fvg_c2_time"])

        if mode == "baseline":
            s = swept[0]
            outcome, exit_t, ent, sl, tp = simulate_one(s, df_1m, ENTRY_PCT, SL_PCT, RR)
            trades.append({**s, "outcome": outcome, "trade_idx_in_zone": 0,
                            "entry_v": ent, "sl_v": sl, "tp_v": tp,
                            "exit_time": exit_t, "n_in_zone_total": len(swept)})
            continue

        # retry mode
        prev_sl_time = None
        for idx, s in enumerate(swept):
            tf_min = 15 if s["fvg_tf"] == "15m" else 20
            sig_close = s["signal_time"] + pd.Timedelta(minutes=tf_min)
            if prev_sl_time is not None and sig_close <= prev_sl_time:
                # сигнал был уже "в полёте" когда предыдущий стопнул —
                # пропускаем (он не может считаться "повторным входом после
                # того как первый стопнули")
                continue
            outcome, exit_t, ent, sl, tp = simulate_one(s, df_1m, ENTRY_PCT, SL_PCT, RR)
            trades.append({**s, "outcome": outcome, "trade_idx_in_zone": idx,
                            "entry_v": ent, "sl_v": sl, "tp_v": tp,
                            "exit_time": exit_t, "n_in_zone_total": len(swept)})
            if outcome == "loss":
                prev_sl_time = exit_t
                continue
            else:
                break
    return trades


def summarize(trades, label, rr=RR):
    closed = [t for t in trades if t["outcome"] in ("win", "loss")]
    W = sum(1 for t in closed if t["outcome"] == "win")
    L = sum(1 for t in closed if t["outcome"] == "loss")
    n = W + L
    wr = (W / n * 100) if n else 0.0
    pnl = W * rr - L * 1.0
    r_per = pnl / n if n else 0.0
    nf = sum(1 for t in trades if t["outcome"] == "nf")
    ne = sum(1 for t in trades if t["outcome"] == "no_entry")
    op = sum(1 for t in trades if t["outcome"] == "open")
    sk = sum(1 for t in trades if t["outcome"] == "skipped")

    # Yearly breakdown
    yearly = defaultdict(lambda: [0, 0, 0.0])  # W, L, PnL
    for t in closed:
        y = pd.Timestamp(t["signal_time"]).year
        if t["outcome"] == "win":
            yearly[y][0] += 1; yearly[y][2] += rr
        else:
            yearly[y][1] += 1; yearly[y][2] -= 1.0

    print()
    print("=" * 70)
    print(f"  {label}")
    print("=" * 70)
    print(f"  total={len(trades)}  closed={n}  not_filled={nf}  open={op}  no_entry={ne}  skipped={sk}")
    print(f"  W={W}  L={L}  WR={wr:.1f}%  PnL={pnl:+.1f}R  R/trade={r_per:+.3f}")
    print("  По годам:")
    bad_years = 0
    for y in sorted(yearly):
        Wy, Ly, pnly = yearly[y]
        wry = Wy / (Wy + Ly) * 100 if (Wy + Ly) else 0
        marker = " (bad)" if pnly < 0 else ""
        if pnly < 0:
            bad_years += 1
        print(f"    {y}: n={Wy+Ly:3d}  WR={wry:5.1f}%  PnL={pnly:+6.1f}R{marker}")
    print(f"  bad years: {bad_years}/{len(yearly)}")
    return {"n": n, "W": W, "L": L, "wr": wr, "pnl": pnl, "r_per": r_per, "bad": bad_years}


def summarize_retry_breakdown(trades, rr=RR):
    """Анализ retry-only: сколько retry-сделок (idx>0), какой их WR/PnL."""
    first_only = [t for t in trades if t["trade_idx_in_zone"] == 0 and t["outcome"] in ("win", "loss")]
    retries = [t for t in trades if t["trade_idx_in_zone"] > 0 and t["outcome"] in ("win", "loss")]

    print()
    print("=" * 70)
    print("  RETRY breakdown (только в retry-режиме)")
    print("=" * 70)
    for label, group in [("first (idx=0)", first_only), ("retry (idx>0)", retries)]:
        if not group:
            print(f"  {label}: пусто")
            continue
        W = sum(1 for t in group if t["outcome"] == "win")
        L = sum(1 for t in group if t["outcome"] == "loss")
        n = W + L
        wr = (W / n * 100) if n else 0.0
        pnl = W * rr - L * 1.0
        print(f"  {label}: n={n}  W={W} L={L}  WR={wr:.1f}%  PnL={pnl:+.1f}R")

    # Сколько зон выдали retry?
    retry_zones = {t["group_id"] for t in trades if t["trade_idx_in_zone"] > 0}
    print(f"  Уникальных зон с retry: {len(retry_zones)}")
    # Распределение глубины (по индексам)
    max_idx = max((t["trade_idx_in_zone"] for t in trades), default=0)
    print(f"  Max chain length: {max_idx + 1}  trades")
    by_idx = defaultdict(int)
    for t in trades:
        if t["outcome"] in ("win", "loss"):
            by_idx[t["trade_idx_in_zone"]] += 1
    for i in sorted(by_idx):
        print(f"    idx={i}: {by_idx[i]} trades")


def main():
    print(f"[INFO] etap_98: 1.1.1 retry-after-SL test, {SYMBOL}, {DAYS_BACK}d, "
          f"entry={ENTRY_PCT} sl={SL_PCT} sym RR={RR}, SWEPT ON")
    print()
    print("[INFO] loading data")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]
    print(f"  1d={len(df_1d_f)} 12h={len(df_12h_f)} 4h={len(df_4h)} 6h={len(df_6h)} "
          f"1h={len(df_1h)} 2h={len(df_2h)} 15m={len(df_15m)} 20m={len(df_20m)} 1m={len(df_1m)}")

    print()
    print("[INFO] detect multi-shot signals (all OB-htf+entry pairs per macro zone)")
    groups = detect_multi_signals(df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    total_pairs = sum(len(g) for g in groups.values())
    multi_zones = sum(1 for g in groups.values() if len(g) > 1)
    print(f"  macro zones with >=1 signal: {len(groups)}")
    print(f"  total (OB-htf, entry) pairs: {total_pairs}")
    print(f"  zones with multi-shot (>1 pair): {multi_zones}")
    dist = defaultdict(int)
    for g in groups.values():
        dist[len(g)] += 1
    print("  distribution by pair count per zone:")
    for k in sorted(dist):
        print(f"    {k} pair(s): {dist[k]} zones")

    print()
    print("[INFO] applying SWEPT filter")
    # Quick stat: how many pairs pass SWEPT?
    swept_pass = 0
    for g in groups.values():
        for s in g:
            if check_swept(s, df_1h, df_2h) is True:
                swept_pass += 1
    print(f"  pairs passing SWEPT: {swept_pass} / {total_pairs}")

    print()
    print("[INFO] running baseline (one-shot, first signal per zone)")
    baseline_trades = run_experiment(groups, df_1m, df_1h, df_2h, mode="baseline")
    baseline_summary = summarize(baseline_trades, "BASELINE: 1.1.1 one-shot (current live)")

    print()
    print("[INFO] running retry (chain after SL, same zone)")
    retry_trades = run_experiment(groups, df_1m, df_1h, df_2h, mode="retry")
    retry_summary = summarize(retry_trades, "RETRY: 1.1.1 chain after SL")
    summarize_retry_breakdown(retry_trades)

    # Delta
    print()
    print("=" * 70)
    print("  DELTA  (retry - baseline)")
    print("=" * 70)
    print(f"  trades closed: {retry_summary['n'] - baseline_summary['n']:+d}  "
          f"(baseline {baseline_summary['n']} -> retry {retry_summary['n']})")
    print(f"  W: {retry_summary['W'] - baseline_summary['W']:+d}  "
          f"L: {retry_summary['L'] - baseline_summary['L']:+d}")
    print(f"  WR: {retry_summary['wr'] - baseline_summary['wr']:+.1f}pp")
    print(f"  PnL: {retry_summary['pnl'] - baseline_summary['pnl']:+.1f}R  "
          f"({baseline_summary['pnl']:+.1f} -> {retry_summary['pnl']:+.1f})")
    print(f"  R/trade: {retry_summary['r_per'] - baseline_summary['r_per']:+.3f}  "
          f"({baseline_summary['r_per']:+.3f} -> {retry_summary['r_per']:+.3f})")
    print(f"  bad years: {retry_summary['bad'] - baseline_summary['bad']:+d}")

    out_dir = Path("research/elements_study/output")
    out_dir.mkdir(parents=True, exist_ok=True)
    for label, trades in [("baseline", baseline_trades), ("retry", retry_trades)]:
        flat = []
        for t in trades:
            flat.append({
                "group_id": str(t["group_id"]),
                "trade_idx_in_zone": t["trade_idx_in_zone"],
                "n_in_zone_total": t["n_in_zone_total"],
                "direction": t["direction"],
                "top_tf": t["top_tf"],
                "macro_tf": t["fvg_macro_tf"],
                "macro_c2": str(t["fvg_macro_c2_time"]),
                "ob_htf_tf": t["ob_htf_tf"],
                "ob_htf_cur": str(t["ob_htf_cur_time"]),
                "fvg_tf": t["fvg_tf"],
                "signal_time": str(t["signal_time"]),
                "entry": t["entry_v"],
                "sl": t["sl_v"],
                "tp": t["tp_v"],
                "outcome": t["outcome"],
                "exit_time": str(t["exit_time"]) if t.get("exit_time") else "",
            })
        df_out = pd.DataFrame(flat)
        path = out_dir / f"etap_98_{label}.csv"
        df_out.to_csv(path, index=False)
        print(f"  written {path} ({len(df_out)} rows)")


if __name__ == "__main__":
    main()
