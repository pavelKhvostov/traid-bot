"""Strategy 1.1.1 + Floating TP — полная имплементация версии из PDF etap108.

Описывает то что показано в `research/elements_study/output/etap108_floating_tp_human_guide.pdf`:
финальная версия 1.1.1 с автоследованием через 4-indicator momentum score.

Этот файл — self-contained reference implementation, объединяющая:
  - Cascade detector 1.1.1 SWEPT (OB-{1d,12h} + FVG-{4h,6h} → OB-{1h,2h} + FVG-{15m,20m})
  - Entry / SL по approved формуле (entry=0.80, sl=0.35 symmetric)
  - Floating TP simulator с 4 способами выхода
  - 4-indicator composite score (Hull / Money Hands / RSI / ASVK)
  - Per-symbol configs (BTC / ETH / SOL)

Используется как backtest detector + simulator. Для live-интеграции нужен
Position manager (на каждом 1h close вызывать `should_exit_floating()`).
См. [[strategy-1-1-1-floating-tp-final]] и TBD live integration.

Источники (с этого файла можно делать диффы при обновлениях):
  - Cascade: research/elements_study/etap_98_retry_after_sl_111.py
  - Indicators + simulator: research/elements_study/etap_103_floating_tp.py
  - Tuning: etap_104..107
  - PDF generator: research/elements_study/etap_108_floating_tp_pdf.py
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from strategies.strategy_1_1_1 import (
    OBZone,
    FVGZone,
    collect_valid_macro_fvgs,
    detect_fvg,
    detect_ob_pair,
    find_first_fvg_in_range,
    zones_overlap,
)


# ============================================================
# Approved live parameters (PDF etap108 + memory project_111_approved)
# ============================================================

ENTRY_PCT = 0.80          # глубина в FVG-entry (0=ближняя, 1=дальняя граница)
SL_PCT = 0.35             # symmetric: между OB-htf edge и FVG-entry edge
RR_BASELINE = 2.2         # fixed RR — используется ТОЛЬКО для no_entry-проверки
MAX_HOLD_DAYS = 7         # таймаут "Способ #4" (max-hold mark-to-market)

# Per-symbol floating-TP конфиги (winners из etap_105/106/107):
#   R_cap     — потолок прибыли (Способ #2 — Hard cap hit)
#   threshold — exit когда score(t) <= threshold (Способ #3)
#   confirm   — сколько consecutive 1h-баров должны быть ниже threshold
FLOATING_TP_CONFIG: dict[str, dict] = {
    "BTCUSDT": {"R_cap": 4.5, "threshold": -0.25, "confirm": 2},
    "ETHUSDT": {"R_cap": 4.5, "threshold": -0.25, "confirm": 2},
    "SOLUSDT": {"R_cap": 3.5, "threshold":  0.00, "confirm": 1},
}


# ============================================================
# CASCADE — Strategy 1.1.1 SWEPT detector
# ============================================================

def find_all_signals_in_macro(
    df_htf: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_20m: pd.DataFrame,
    ob_top: OBZone,
    fvg_macro: FVGZone,
    search_start: pd.Timestamp,
    htf_minutes: int,
    htf_label: str,
) -> list[dict]:
    """Найти все валидные пары (OB-htf, entry-FVG) внутри FVG-macro,
    до фрактал-инвалидации макрозоны."""
    df_window = df_htf[df_htf.index >= search_start]
    n = len(df_window)
    if n < 2:
        return []
    direction = ob_top.direction
    fvg_top = fvg_macro.top
    fvg_bottom = fvg_macro.bottom
    highs = df_window["high"].values
    lows = df_window["low"].values
    out: list[dict] = []
    fractal_confirm_idx: int | None = None
    for i in range(n):
        if i >= 4 and fractal_confirm_idx is None:
            j = i - 2
            f_low = float(lows[j]); f_high = float(highs[j])
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
               and zones_overlap(cand.bottom, cand.top, ob_top.bottom, ob_top.top):
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
                    fvg_entry, fvg_tf = fvg_20m, "20m"
                elif fvg_20m is None:
                    fvg_entry, fvg_tf = fvg_15m, "15m"
                elif fvg_15m.c2_time <= fvg_20m.c2_time:
                    fvg_entry, fvg_tf = fvg_15m, "15m"
                else:
                    fvg_entry, fvg_tf = fvg_20m, "20m"
                out.append({
                    "ob_htf": cand, "htf_label": htf_label,
                    "fvg_entry": fvg_entry, "fvg_tf": fvg_tf,
                })
    return out


def detect_signals_111(
    df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
) -> list[dict]:
    """Strategy 1.1.1 cascade. Возвращает список сигналов с полными meta.

    Cascade:
      L1: OB-{1d, 12h}           — top-OB обе TF параллельно
      L2: FVG-{4h, 6h}           — macro-FVG нужного направления внутри top-OB
      L3: OB-{1h, 2h} (SWEPT)    — htf-OB внутри FVG-macro + ob_top
      L4: FVG-{15m, 20m}         — entry-FVG внутри OB-htf по времени
    """
    signals: list[dict] = []

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
                pairs_1h = find_all_signals_in_macro(df_1h, df_15m, df_20m, ob_top, fvg_macro, search_start, 60, "1h")
                pairs_2h = find_all_signals_in_macro(df_2h, df_15m, df_20m, ob_top, fvg_macro, search_start, 120, "2h")
                all_pairs = pairs_1h + pairs_2h
                if not all_pairs:
                    continue
                all_pairs.sort(key=lambda p: p["fvg_entry"].c2_time)
                for p in all_pairs:
                    ob_htf = p["ob_htf"]
                    fvg_entry = p["fvg_entry"]
                    signals.append({
                        "direction": ob_top.direction,
                        "signal_time": fvg_entry.c2_time,
                        "top_tf": top_label,
                        "ob_d_cur_time": ob_top.cur_time,
                        "ob_d_zone": (ob_top.bottom, ob_top.top),
                        "fvg_macro_tf": macro_tf,
                        "fvg_macro_zone": (fvg_macro.bottom, fvg_macro.top),
                        "ob_htf_tf": p["htf_label"],
                        "ob_htf_prev_time": ob_htf.prev_time,
                        "ob_htf_cur_time": ob_htf.cur_time,
                        "ob_htf_zone": (ob_htf.bottom, ob_htf.top),
                        "fvg_tf": p["fvg_tf"],
                        "fvg_c2_time": fvg_entry.c2_time,
                        "fvg_zone": (fvg_entry.bottom, fvg_entry.top),
                    })

    _scan(df_1d, 24, "1d")
    _scan(df_12h, 12, "12h")
    return signals


def check_swept(sig: dict, df_1h: pd.DataFrame, df_2h: pd.DataFrame) -> bool | None:
    """SWEPT-фильтр на OB-htf: cur+prev лоу/хай должны "снимать" 2-х барный
    локальный экстремум. Без этого фильтра 1.1.1 не утверждена."""
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
    c1l = float(df_top.iloc[prev_idx]["low"]);  c2l = float(df_top.iloc[cur_idx]["low"])
    c1h = float(df_top.iloc[prev_idx]["high"]); c2h = float(df_top.iloc[cur_idx]["high"])
    n1l = float(df_top.iloc[prev_idx - 1]["low"]);  n2l = float(df_top.iloc[prev_idx - 2]["low"])
    n1h = float(df_top.iloc[prev_idx - 1]["high"]); n2h = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


# ============================================================
# ENTRY / SL builder (approved symmetric formula)
# ============================================================

def build_entry_sl(sig: dict) -> tuple[float, float] | None:
    """Approved live formula:
        entry = fvg_bottom + 0.80 × (fvg_top - fvg_bottom)        [LONG]
        sl    = ob_htf_bottom + 0.35 × (fvg_bottom - ob_htf_bottom) [LONG]
        зеркально SHORT.
    Возвращает (entry, sl) или None если геометрия невалидна."""
    direction = sig["direction"]
    fb, ft = sig["fvg_zone"]
    obb, obt = sig["ob_htf_zone"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl = obb + SL_PCT * (fb - obb)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl = obt - SL_PCT * (obt - ft)
        if sl <= entry: return None
    return float(entry), float(sl)


# ============================================================
# 4-INDICATOR MOMENTUM SCORE (composite)
# ============================================================
# Lookahead-safe — все индикаторы на closed 1h-бары до момента checkpoint.

def _wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def _hull_ma(close: pd.Series, length: int = 78) -> pd.Series:
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * _wma_fast(arr, half) - _wma_fast(arr, length)
    hull = _wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def hull_signal(close: pd.Series, length: int = 78) -> pd.Series:
    """+1 если close[i] > hull[i-2], -1 если ниже, 0 если nan.
    Hull от 2 бар назад — lookahead-safe."""
    hull = _hull_ma(close, length)
    out = np.zeros(len(close), dtype=float)
    arr_c = close.values; arr_h = hull.values
    for i in range(len(close)):
        if i < 2 or pd.isna(arr_h[i - 2]):
            out[i] = 0
        else:
            out[i] = 1.0 if arr_c[i] > arr_h[i - 2] else -1.0
    return pd.Series(out, index=close.index)


def _mh_bw2(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Money Hands bw2 (WaveTrend LazyBear) + SMA(14)."""
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    esa = hlc3.ewm(span=9, adjust=False).mean()
    d = (hlc3 - esa).abs().ewm(span=9, adjust=False).mean()
    ci = (hlc3 - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=12, adjust=False).mean()
    wt2 = wt1.rolling(4, min_periods=4).mean()
    sma14 = wt2.rolling(14, min_periods=14).mean()
    return wt2, sma14


def mh_signal(df: pd.DataFrame) -> pd.Series:
    """Money Hands цвет → score:
        зеленый  (bw2 > 0, bw2 >= SMA14)  → +1
        серый  ← зеленого (bw2 > 0, bw2 < SMA14)  → +0.5
        nan / 0                                    →  0
        серый  ← красного (bw2 < 0, bw2 > SMA14)  → -0.5
        красный (bw2 < 0, bw2 <= SMA14)            → -1
    """
    bw2, sma14 = _mh_bw2(df)
    out = np.zeros(len(df), dtype=float)
    for i in range(len(df)):
        v = bw2.iloc[i]; s = sma14.iloc[i]
        if pd.isna(v) or pd.isna(s):
            out[i] = 0
        elif v > 0:
            out[i] = 1.0 if v >= s else 0.5
        elif v < 0:
            out[i] = -1.0 if v <= s else -0.5
        else:
            out[i] = 0
    return pd.Series(out, index=df.index)


def _rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi_signal(close: pd.Series, period: int = 14) -> pd.Series:
    """Нормализация: clip((rsi - 50) / 50, -1, +1)."""
    rsi = _rsi_wilder(close, period)
    return ((rsi - 50.0) / 50.0).clip(-1, 1).fillna(0)


def _asvk_adjusted_rsi(close: pd.Series) -> pd.Series:
    """ASVK adjusted RSI ema_3 — амплитуда RSI масштабируется coefficient'ом."""
    rsi = _rsi_wilder(close, 14)
    ema_for_coef = rsi.ewm(span=5, adjust=False).mean()
    coef = pd.Series(np.where(rsi >= 50, 1.2, 0.8), index=rsi.index)
    coefficient = (rsi * coef) / ema_for_coef.replace(0, np.nan)
    adj = rsi * coefficient
    return adj.ewm(span=5, adjust=False).mean()


def _asvk_dynamic_levels(
    ema_3: pd.Series, lookback: int = 200
) -> tuple[pd.Series, pd.Series]:
    """ASVK NWE-style adaptive OB/OS levels (above/below)."""
    n = len(ema_3)
    above = np.full(n, np.nan)
    below = np.full(n, np.nan)
    arr = ema_3.to_numpy()
    for i in range(lookback - 1, n):
        win = arr[i - lookback + 1: i + 1]
        win = win[~np.isnan(win)]
        if len(win) < 10:
            continue
        m = win > 50; z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 100/y; c2 = 50/y; c3 = c1-c2
            c5 = (c3/lookback)*z + c3
            above[i] = c5 * y
        m = win < 50; z = m.sum()
        if z > 0:
            y = win[m].mean()
            c1 = 50/y; c2 = 1/y; c3 = c1-c2
            c5 = (c3/lookback)*z + c3
            below[i] = 100 - (c5 * y)
    return pd.Series(above, index=ema_3.index), pd.Series(below, index=ema_3.index)


def asvk_zone_signal(close: pd.Series) -> pd.Series:
    """ASVK red/green zone label:
        +1 — red zone (ema_3 > above)  → bullish sustained move
        -1 — green zone (ema_3 < below) → bearish sustained move
         0 — neutral (между уровнями)
    """
    ema_3 = _asvk_adjusted_rsi(close)
    above, below = _asvk_dynamic_levels(ema_3, lookback=200)
    out = np.zeros(len(close), dtype=float)
    for i in range(len(close)):
        e = ema_3.iloc[i]; a = above.iloc[i]; b = below.iloc[i]
        if pd.isna(e) or pd.isna(a) or pd.isna(b):
            out[i] = 0
        elif e > a:
            out[i] = 1.0
        elif e < b:
            out[i] = -1.0
        else:
            out[i] = 0
    return pd.Series(out, index=close.index)


def build_score_series(df_1h: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Composite momentum score для LONG / SHORT позиций (mean из 4 индикаторов).

    Возвращает (score_long, score_short) — каждое значение ∈ [-1, +1] на каждом
    closed 1h-баре. SHORT = -LONG для всех 4 индикаторов (включая ASVK, где
    red zone = bullish = anti-SHORT)."""
    s_hull = hull_signal(df_1h["close"])
    s_mh = mh_signal(df_1h)
    s_rsi = rsi_signal(df_1h["close"])
    s_asvk = asvk_zone_signal(df_1h["close"])

    score_long = (s_hull + s_mh + s_rsi + s_asvk) / 4.0
    score_short = -score_long
    return score_long, score_short


# ============================================================
# FLOATING TP SIMULATOR — 4 способа выхода
# ============================================================

@dataclass
class TradeResult:
    outcome: str            # "win" / "loss" / "flat" / "no_entry" / "nf" / "open"
    R: float                # +R_cap, -1, или score-exit / max-hold R
    exit_time: pd.Timestamp | None
    exit_reason: str        # "sl_hit" / "cap_hit" / "score_exit" / "max_hold" / ...
    hold_h: float
    max_R: float            # MFE (max favorable excursion) до exit'а


def simulate_floating(
    sig: dict,
    df_1m: pd.DataFrame,
    df_1h: pd.DataFrame,
    score_long: pd.Series,
    score_short: pd.Series,
    *,
    R_cap: float,
    threshold: float,
    confirm: int,
    max_hold_days: int = MAX_HOLD_DAYS,
) -> TradeResult | None:
    """Симулятор сделки с 4 способами закрытия:

      Способ #1 — Hard SL hit:       R = -1.0
      Способ #2 — Hard cap hit:      R = +R_cap (цена дошла до cap-уровня)
      Способ #3 — Score-exit:        momentum развернулся (score <= threshold
                                     на `confirm` consecutive 1h-баров).
                                     Exit на close следующего 1h-бара.
      Способ #4 — Max-hold timeout:  через `max_hold_days` mark-to-market.

    Также применяется no_entry filter: если price дошла до TP_proxy = entry +
    RR_BASELINE × risk до самого entry — сделка отменена (apples-to-apples
    с baseline).
    """
    setup = build_entry_sl(sig)
    if setup is None:
        return None
    entry, sl = setup
    direction = sig["direction"]
    risk = abs(entry - sl)
    if risk <= 0:
        return None

    score_series = score_long if direction == "LONG" else score_short

    # TP_proxy используется ТОЛЬКО для no_entry-проверки, не как exit-уровень
    tp_proxy = entry + RR_BASELINE * risk if direction == "LONG" else entry - RR_BASELINE * risk

    # Способ #2: hard cap уровень
    cap_price = entry + R_cap * risk if direction == "LONG" else entry - R_cap * risk

    # Limit-fill: ждём пока цена коснётся entry
    tf_min = 15 if sig["fvg_tf"] == "15m" else 20
    fill_start = sig["signal_time"] + pd.Timedelta(minutes=tf_min)
    forward = df_1m[df_1m.index >= fill_start]
    if forward.empty:
        return TradeResult("nf", 0.0, None, "no_data", 0, 0)

    h_arr = forward["high"].values.astype(np.float64)
    l_arr = forward["low"].values.astype(np.float64)
    ts_arr = forward.index
    n = len(h_arr)

    if direction == "LONG":
        ent_idxs = np.where(l_arr <= entry)[0]
        tp_pre = np.where(h_arr >= tp_proxy)[0]
    else:
        ent_idxs = np.where(h_arr >= entry)[0]
        tp_pre = np.where(l_arr <= tp_proxy)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i:
        return TradeResult("no_entry", 0.0, None, "tp_proxy_before_entry", 0, 0)
    if ent_i >= n:
        return TradeResult("nf", 0.0, None, "no_fill", 0, 0)

    activation = ts_arr[ent_i]
    end_time = activation + pd.Timedelta(days=max_hold_days)

    # Post-fill окно по 1m (для SL/cap walk + MFE)
    et64 = np.datetime64(activation.tz_localize(None) if activation.tz else activation)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return TradeResult("nf", 0.0, None, "no_post_data", 0, 0)
    post_h = df_1m["high"].values[i0:i1].astype(np.float64)
    post_l = df_1m["low"].values[i0:i1].astype(np.float64)
    post_c = df_1m["close"].values[i0:i1].astype(np.float64)
    post_ts = df_1m.index[i0:i1]

    # 1h checkpoints в окне [activation, end_time]
    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    if h1_after >= h1_end:
        return TradeResult("open", 0.0, None, "no_1h_checkpoints", 0, 0)
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values

    # Walk by 1h checkpoints
    consec_low_score = 0
    sl_exit_idx: int | None = None
    cap_exit_idx: int | None = None
    floating_exit_price: float | None = None
    floating_exit_time: pd.Timestamp | None = None
    max_R = 0.0
    prev_post_idx = 0

    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_post_idx = int(np.searchsorted(post_ts.values, cp64))

        if cur_post_idx > prev_post_idx:
            window_l = post_l[prev_post_idx:cur_post_idx]
            window_h = post_h[prev_post_idx:cur_post_idx]

            if direction == "LONG":
                # MFE tracking
                if len(window_h) > 0:
                    mfe = (window_h.max() - entry) / risk
                    if mfe > max_R: max_R = mfe
                # Способ #1: SL hit (приоритет над cap при равенстве)
                if (window_l <= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(window_l <= sl))
                    break
                # Способ #2: cap hit
                if (window_h >= cap_price).any():
                    cap_exit_idx = prev_post_idx + int(np.argmax(window_h >= cap_price))
                    break
            else:
                if len(window_l) > 0:
                    mfe = (entry - window_l.min()) / risk
                    if mfe > max_R: max_R = mfe
                if (window_h >= sl).any():
                    sl_exit_idx = prev_post_idx + int(np.argmax(window_h >= sl))
                    break
                if (window_l <= cap_price).any():
                    cap_exit_idx = prev_post_idx + int(np.argmax(window_l <= cap_price))
                    break

        prev_post_idx = cur_post_idx

        # Способ #3: score-exit check на закрытом 1h-баре ДО checkpoint cp
        score_idx = score_series.index.searchsorted(cp, side="right") - 1
        if score_idx < 0:
            continue
        s = score_series.iloc[score_idx]
        if pd.isna(s):
            continue
        if s <= threshold:
            consec_low_score += 1
        else:
            consec_low_score = 0
        if consec_low_score >= confirm:
            # exit at close of bar AT cp (последний закрытый 1h до cp)
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                floating_exit_price = float(closes_1h[cp_close_idx])
                floating_exit_time = cp
                break

    # Finalize
    if sl_exit_idx is not None:
        return TradeResult(
            outcome="loss", R=-1.0,
            exit_time=post_ts[sl_exit_idx],
            exit_reason="sl_hit",
            hold_h=(post_ts[sl_exit_idx] - activation).total_seconds() / 3600,
            max_R=max_R,
        )
    if cap_exit_idx is not None:
        return TradeResult(
            outcome="win", R=R_cap,
            exit_time=post_ts[cap_exit_idx],
            exit_reason="cap_hit",
            hold_h=(post_ts[cap_exit_idx] - activation).total_seconds() / 3600,
            max_R=max_R,
        )
    if floating_exit_price is not None:
        if direction == "LONG":
            R = (floating_exit_price - entry) / risk
        else:
            R = (entry - floating_exit_price) / risk
        return TradeResult(
            outcome="win" if R > 0 else ("loss" if R < 0 else "flat"),
            R=float(R),
            exit_time=floating_exit_time,
            exit_reason="score_exit",
            hold_h=(floating_exit_time - activation).total_seconds() / 3600,
            max_R=max_R,
        )
    # Способ #4: max-hold timeout — mark-to-market
    last_close = float(post_c[-1])
    if direction == "LONG":
        R = (last_close - entry) / risk
    else:
        R = (entry - last_close) / risk
    return TradeResult(
        outcome="win" if R > 0 else ("loss" if R < 0 else "flat"),
        R=float(R),
        exit_time=post_ts[-1],
        exit_reason="max_hold",
        hold_h=(post_ts[-1] - activation).total_seconds() / 3600,
        max_R=max_R,
    )


# ============================================================
# Convenience runner: end-to-end для одного символа
# ============================================================

def run_symbol_backtest(
    symbol: str,
    df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m,
) -> list[dict]:
    """End-to-end: detect → SWEPT filter → score → simulate floating.

    Возвращает list of {**sig, **TradeResult fields}. Готово для CSV-экспорта
    или статистики (см. `aggregate_stats` ниже)."""
    cfg = FLOATING_TP_CONFIG[symbol]
    signals = detect_signals_111(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    score_long, score_short = build_score_series(df_1h)

    trades = []
    for sig in signals:
        swept = check_swept(sig, df_1h, df_2h)
        if not swept:
            continue
        result = simulate_floating(
            sig, df_1m, df_1h, score_long, score_short,
            R_cap=cfg["R_cap"],
            threshold=cfg["threshold"],
            confirm=cfg["confirm"],
        )
        if result is None:
            continue
        trades.append({
            **sig,
            "outcome": result.outcome,
            "R": result.R,
            "exit_time": result.exit_time,
            "exit_reason": result.exit_reason,
            "hold_h": result.hold_h,
            "max_R": result.max_R,
        })
    return trades


def aggregate_stats(trades: list[dict]) -> dict:
    """Базовая статистика: n, WR, total R, R/trade, per-exit-reason breakdown."""
    closed = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]
    n = len(closed)
    if n == 0:
        return {"n": 0}
    W = sum(1 for t in closed if t["R"] > 0)
    L = sum(1 for t in closed if t["R"] < 0)
    pnl = sum(t["R"] for t in closed)
    by_reason = defaultdict(lambda: {"n": 0, "R": 0.0})
    for t in closed:
        by_reason[t["exit_reason"]]["n"] += 1
        by_reason[t["exit_reason"]]["R"] += t["R"]
    by_year = defaultdict(float)
    for t in closed:
        y = pd.Timestamp(t["signal_time"]).year
        by_year[y] += t["R"]
    return {
        "n": n, "W": W, "L": L,
        "WR": round(W / n * 100, 2),
        "total_R": round(pnl, 2),
        "R_per_trade": round(pnl / n, 3),
        "bad_years": sum(1 for v in by_year.values() if v < 0),
        "total_years": len(by_year),
        "by_exit_reason": dict(by_reason),
        "by_year": dict(by_year),
    }
