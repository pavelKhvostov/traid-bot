"""Diagnostic preview: WR/PnL по 6 live-конфигам + последние 3 сигнала по месяцам.

Прогоняет на 3y BTCUSDT, default config (entry=mid FVG, SL=15% inside top-OB,
no_entry=on, RR ∈ {1.0, 2.2}). Конфиги те, которые пойдут в live:
  1.1.1 SWEPT — с SWEPT-фильтром
  1.1.2       — без SWEPT
  1.1.3 v1    — без SWEPT (default: macro_mode=untouched)
  1.1.3 v2    — без SWEPT
  1.1.4 v1    — без SWEPT
  1.1.4 v2    — без SWEPT
Observability — наблюдаем все версии в живом потоке.

Outputs:
  Таблица 1: WR / PnL / R/trade × 5 конфигов × 2 RR
  Таблица 2: для каждого конфига — 3 последних календарных месяца,
             в каждом самый свежий сигнал в формате live-бота + outcome
             (WIN / LOSS / NO_ENTRY).

Скрипт diagnostic-only: ничего не пишет в live, не отправляет в Telegram.
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
from typing import Callable

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals
from strategies.strategy_1_1_4 import detect_strategy_1_1_4_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR_LIST = [1.0, 2.2]


# ======================================================================
# SWEPT-чек (идентичен analyze_1_1_1_ob_swept.py)
# ======================================================================

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


# ======================================================================
# Дедуп по (signal_time, direction, round(entry, 2)) — упрощённый
# ======================================================================

def dedupe_by_key(raw: list[dict]) -> list[dict]:
    seen = {}
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        if key not in seen:
            seen[key] = s
    return list(seen.values())


def split_by_swept(raw: list[dict], df_1h: pd.DataFrame, df_2h: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Группируем raw по dedup-ключу, swept=True если ХОТЯ БЫ один путь swept."""
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept(s, df_1h, df_2h)
        if sw is None:
            continue
        groups[key].append({"sig": s, "swept": sw})
    swept_reps = [next(p["sig"] for p in paths if p["swept"])
                  for key, paths in groups.items() if any(p["swept"] for p in paths)]
    all_reps = [paths[0]["sig"] for key, paths in groups.items()]
    return all_reps, swept_reps


# ======================================================================
# Симуляция outcome на 1m с no_entry-логикой
# ======================================================================

def simulate_outcome(sig: dict, df_1m: pd.DataFrame, rr: float, htf_used_for_tf_minutes: bool) -> str:
    """outcome ∈ {win, loss, no_entry, not_filled, open}.

    htf_used_for_tf_minutes:
      True (для 1.1.3, 1.1.4) — tf_minutes = 60/120 от ob_htf_tf
      False (для 1.1.1, 1.1.2) — tf_minutes = 15/20 от fvg_tf
    """
    direction = sig["direction"]
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    risk = float(sig["risk"])
    signal_time = sig["signal_time"]

    if htf_used_for_tf_minutes:
        tf_minutes = 60 if sig["ob_htf_tf"] == "1h" else 120
    else:
        tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20

    if direction == "LONG":
        tp = entry + rr * risk
    else:
        tp = entry - rr * risk

    fill_scan_start = signal_time + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]
    if forward.empty:
        return "not_filled"

    highs = forward["high"].values.astype(np.float64)
    lows = forward["low"].values.astype(np.float64)
    n = len(highs)

    if direction == "LONG":
        entry_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
        sl_pre_idxs = np.where(lows <= sl)[0]
    else:
        entry_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]
        sl_pre_idxs = np.where(highs >= sl)[0]

    entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
    tp_pre_idx = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1
    sl_pre_idx = int(sl_pre_idxs[0]) if sl_pre_idxs.size else n + 1

    # NO_ENTRY: если TP или SL хитнулись СТРОГО раньше entry
    pre_entry_min = min(tp_pre_idx, sl_pre_idx)
    if pre_entry_min < entry_idx:
        return "no_entry"
    if entry_idx >= n:
        return "not_filled"

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


# ======================================================================
# Format в стиле live-бота (без кружков)
# ======================================================================

def format_top_label(top_tf: str) -> str:
    return "Daily" if top_tf == "1d" else top_tf


def format_signal_preview(sig: dict, version: str, outcome: str, rr: float) -> str:
    """Превью сигнала как его отправил бы бот, + outcome для контекста.

    Зависит от структуры сигнала версии:
      1.1.1: macro=FVG, entry=15m/20m FVG младшего ТФ
        → "Daily OB + 4h FVG / 1h OB + 15m FVG"
      1.1.2: macro=OB, entry=15m/20m FVG
        → "Daily OB + 4h OB / 1h OB + 15m FVG"
      1.1.3: macro=OB, entry=FVG того же ТФ что OB-htf
        → "Daily OB + 4h OB / 1h OB + 1h FVG"
      1.1.4: macro=FVG, entry=FVG того же ТФ что OB-htf
        → "Daily OB + 4h FVG / 1h OB + 1h FVG"
    """
    sym_short = SYMBOL.replace("USDT", "")
    direction = sig["direction"]
    top_label = format_top_label(sig["top_tf"])

    # Macro: 1.1.1 и 1.1.4 имеют macro=FVG; 1.1.2 и 1.1.3 имеют macro=OB.
    # version приходит как "1.1.1 SWEPT", "1.1.4 v1" и т.д. — сравниваем по prefix.
    if version.startswith("1.1.1") or version.startswith("1.1.4"):
        macro_pat = "FVG"
        macro_tf = sig.get("fvg_macro_tf") or sig.get("macro_tf")
    else:  # 1.1.2, 1.1.3
        macro_pat = "OB"
        macro_tf = sig.get("ob_macro_tf") or sig.get("macro_tf")

    # Entry
    htf_tf = sig["ob_htf_tf"]
    fvg_tf = sig.get("fvg_tf")
    # Для 1.1.3/1.1.4 fvg_tf == htf_tf (тот же ТФ)

    confirm_time = pd.Timestamp(sig["signal_time"])
    if confirm_time.tz is None:
        confirm_time = confirm_time.tz_localize("UTC")
    ts_str = confirm_time.strftime("%Y-%m-%d %H:%M UTC")

    rr_str = f"{rr:.1f}".rstrip("0").rstrip(".")
    return (
        f"[{ts_str}]  outcome={outcome.upper()} (RR={rr_str})\n"
        f"{sym_short} - {direction}\n"
        f"POI: {top_label} OB + {macro_tf} {macro_pat}\n"
        f"Volume confirmation: {htf_tf} OB + {fvg_tf} FVG"
    )


# ======================================================================
# Фильтрация: 3 последних месяца, по 1 сигналу в каждом
# ======================================================================

def pick_monthly_samples(sigs: list[dict], n_months: int = 3) -> list[dict]:
    """Берём 3 последних календарных месяца по signal_time, в каждом —
    самый свежий сигнал. Если в месяце нет сигналов — пропускаем.

    Возвращает list[dict] длины 0..n_months, отсортированный по убыванию даты.
    """
    if not sigs:
        return []
    by_month: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for s in sigs:
        ts = pd.Timestamp(s["signal_time"])
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        by_month[(ts.year, ts.month)].append(s)

    sorted_months = sorted(by_month.keys(), reverse=True)
    picked = []
    for ym in sorted_months[:n_months]:
        # Самый свежий сигнал в этом месяце
        month_sigs = sorted(by_month[ym], key=lambda s: pd.Timestamp(s["signal_time"]), reverse=True)
        picked.append(month_sigs[0])
    return picked


# ======================================================================
# Main
# ======================================================================

def main() -> None:
    print(f"[INFO] Preview: 5 strategies × 2 RR на {SYMBOL}, окно {DAYS_BACK}d")
    print()

    print("[INFO] загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    # ---------- detect все ----------
    print("[INFO] detect 1.1.1...")
    raw_111 = detect_strategy_1_1_1_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                             df_1h, df_2h, df_15m, df_20m, verbose=False)
    print(f"  raw: {len(raw_111)}")

    print("[INFO] detect 1.1.2...")
    raw_112 = detect_strategy_1_1_2_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                             df_1h, df_2h, df_15m, df_20m, verbose=False)
    print(f"  raw: {len(raw_112)}")

    print("[INFO] detect 1.1.3 v1...")
    raw_113_v1 = detect_strategy_1_1_3_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                                df_1h, df_2h,
                                                fvg_variant="v1", macro_mode="untouched",
                                                verbose=False)
    print(f"  raw: {len(raw_113_v1)}")

    print("[INFO] detect 1.1.3 v2...")
    raw_113_v2 = detect_strategy_1_1_3_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                                df_1h, df_2h,
                                                fvg_variant="v2", macro_mode="untouched",
                                                verbose=False)
    print(f"  raw: {len(raw_113_v2)}")

    print("[INFO] detect 1.1.4 v1...")
    raw_114_v1 = detect_strategy_1_1_4_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                                df_1h, df_2h, fvg_variant="v1", verbose=False)
    print(f"  raw: {len(raw_114_v1)}")

    print("[INFO] detect 1.1.4 v2...")
    raw_114_v2 = detect_strategy_1_1_4_signals(df_1d_f, df_12h_f, df_4h, df_6h,
                                                df_1h, df_2h, fvg_variant="v2", verbose=False)
    print(f"  raw: {len(raw_114_v2)}")

    # ---------- dedup + SWEPT-split для 1.1.1 ----------
    # _all не используется (в live идёт только SWEPT для 1.1.1).
    _, deduped_111_swept = split_by_swept(raw_111, df_1h, df_2h)
    deduped_112 = dedupe_by_key(raw_112)
    deduped_113_v1 = dedupe_by_key(raw_113_v1)
    deduped_113_v2 = dedupe_by_key(raw_113_v2)
    deduped_114_v1 = dedupe_by_key(raw_114_v1)
    deduped_114_v2 = dedupe_by_key(raw_114_v2)

    # Конфигурации для прогона — те, что пойдут в live (observability).
    # Без 1.1.1 ALL: в live идёт только SWEPT-вариант.
    configs = [
        ("1.1.1 SWEPT", deduped_111_swept, False),  # tf_minutes из fvg_tf
        ("1.1.2",       deduped_112,       False),
        ("1.1.3 v1",    deduped_113_v1,    True),   # tf_minutes из ob_htf_tf
        ("1.1.3 v2",    deduped_113_v2,    True),
        ("1.1.4 v1",    deduped_114_v1,    True),
        ("1.1.4 v2",    deduped_114_v2,    True),
    ]

    # ---------- Симуляция outcomes для каждого конфига и каждого RR ----------
    # Кэш по конфигу и RR
    print("\n[INFO] симуляция outcomes (это займёт несколько минут)...")
    outcomes_cache: dict[tuple[str, float], list[str]] = {}
    for label, sigs, htf_minutes in configs:
        for rr in RR_LIST:
            print(f"  {label} RR={rr}...", end="", flush=True)
            outs = [simulate_outcome(s, df_1m, rr, htf_minutes) for s in sigs]
            outcomes_cache[(label, rr)] = outs
            print(f" done ({len(outs)})")

    # ---------- ТАБЛИЦА 1: WR / PnL / R/trade ----------
    print()
    print("=" * 100)
    print("ТАБЛИЦА 1: WR / PnL / R-per-trade × конфиг × RR (default config, no_entry=on)")
    print("=" * 100)
    print(f"{'Конфиг':<14} {'RR':>5} {'total':>6} {'no_entry':>9} {'closed':>7} "
          f"{'W':>5} {'L':>5} {'WR':>7} {'PnL':>9} {'R/tr':>8}")
    print("-" * 100)
    for label, sigs, _ in configs:
        for rr in RR_LIST:
            outs = outcomes_cache[(label, rr)]
            n = len(outs)
            ne = sum(1 for o in outs if o == "no_entry")
            wins = sum(1 for o in outs if o == "win")
            losses = sum(1 for o in outs if o == "loss")
            closed = wins + losses
            wr = wins / closed * 100 if closed else 0
            pnl = wins * rr - losses
            r_per = pnl / closed if closed else 0
            print(f"{label:<14} {rr:>5.1f} {n:>6d} {ne:>9d} {closed:>7d} "
                  f"{wins:>5d} {losses:>5d} {wr:>6.1f}% {pnl:>+8.1f}R {r_per:>+7.3f}")

    # ---------- ТАБЛИЦА 2: 3 последних месяца, по 1 сигналу ----------
    print()
    print("=" * 100)
    print("ТАБЛИЦА 2: последние 3 календарных месяца, самый свежий сигнал каждого")
    print("Формат — как бы бот отправил, + outcome для контекста (на RR=1.0)")
    print("=" * 100)

    for label, sigs, htf_minutes in configs:
        print()
        print(f"### {label}")
        print(f"всего deduped: {len(sigs)}")
        picks = pick_monthly_samples(sigs, n_months=3)
        if not picks:
            print("  нет сигналов")
            continue
        # Используем outcome на RR=1.0 (соответствует ему по индексу в deduped списке)
        outs_rr1 = outcomes_cache[(label, 1.0)]
        # Найдём индекс каждого pick в исходном списке sigs (через signal_time)
        for p in picks:
            try:
                idx = sigs.index(p)
                outcome = outs_rr1[idx]
            except (ValueError, IndexError):
                outcome = "?"
            # Передаём label как version — format_signal_preview разбирает по prefix.
            preview = format_signal_preview(p, label, outcome, 1.0)
            print()
            print(preview)
        print()


if __name__ == "__main__":
    main()
