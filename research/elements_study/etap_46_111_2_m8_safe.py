"""Этап 46: SAFE re-audit лучшего варианта 1.1.2 + Smart Trail M8.

ИСПРАВЛЕНИЕ Bug 1 из etap_45:
  Старый M8: симуляция стартует от signal_time + 15m БЕЗ проверки что
             цена реально дошла до entry (limit order fill). Это
             искусственно включает 24% «фантомных» сделок.

  Новый M8 SAFE: сначала ищем fill_idx в 1m барах (первый бар где
                 low <= entry для LONG / high >= entry для SHORT).
                 Если не найден за 7 дней - "not_filled" (0R).
                 Trail-логика стартует только ПОСЛЕ fill.

Параметры USER:
  entry = 0.70 of FVG, sl = 0.35L/0.65S, min_sl = 1%

Сравнение:
  - V3 baseline RR=1.8 (с no_entry): +78.4R / 6.33y
  - M8 INFLATED (etap_45): +397.6R
  - M8 SAFE (этот скрипт): ?
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

SYMBOL = "BTCUSDT"
DAYS_BACK = 2313
ENTRY_PCT = 0.70
USER_SL_LONG = 0.35
USER_SL_SHORT = 0.65
USER_RR = 1.8
MIN_SL_PCT = 1.0
MAX_HOLD_DAYS = 7

OUT_DIR = Path("research/elements_study/output")


# ---------- Hull MA (lookahead-safe) ----------

def wma_fast(arr, period):
    period = max(int(period), 1)
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    out = np.full_like(arr, np.nan, dtype=float)
    if len(arr) < period: return out
    valid = np.convolve(arr, weights[::-1], mode="valid")
    out[period - 1:] = valid
    return out


def hull_ma(close, length=78):
    arr = close.to_numpy(dtype=float)
    half = max(int(length / 2), 1)
    sqrt_len = max(int(round(np.sqrt(length))), 1)
    raw = 2.0 * wma_fast(arr, half) - wma_fast(arr, length)
    hull = wma_fast(np.where(np.isnan(raw), 0.0, raw), sqrt_len)
    hull[:length + sqrt_len] = np.nan
    return pd.Series(hull, index=close.index)


def hull_label_series(close, hull):
    """label[i] = "up"/"down" based on close[i] vs hull[i-2].
    Каждый label валиден только когда бар i закроется (= в open[i+1])."""
    n = len(close); out = []
    for i in range(n):
        if i < 2:
            out.append("na"); continue
        c = close.iloc[i]; h2 = hull.iloc[i - 2]
        if pd.isna(c) or pd.isna(h2):
            out.append("na")
        else:
            out.append("up" if c > h2 else "down")
    return pd.Series(out, index=close.index)


# ---------- 1.1.2 detection ----------

def check_swept(sig, df_1h, df_2h):
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    pi = df_top.index.get_loc(prev_time)
    if pi < 2: return None
    ci = df_top.index.get_loc(cur_time)
    c1l = float(df_top.iloc[pi]["low"]); c2l = float(df_top.iloc[ci]["low"])
    c1h = float(df_top.iloc[pi]["high"]); c2h = float(df_top.iloc[ci]["high"])
    n1l = float(df_top.iloc[pi-1]["low"]); n2l = float(df_top.iloc[pi-2]["low"])
    n1h = float(df_top.iloc[pi-1]["high"]); n2h = float(df_top.iloc[pi-2]["high"])
    if sig["direction"] == "LONG":
        return min(c1l, c2l) < min(n1l, n2l)
    return max(c1h, c2h) > max(n1h, n2h)


def precompute(sig):
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "signal_time": sig["signal_time"],
        "year": pd.Timestamp(sig["signal_time"]).year,
        "tf_minutes": tf_minutes,
    }


def build_orders(s):
    direction = s["direction"]
    fw = s["fvg_t"] - s["fvg_b"]
    if direction == "LONG":
        entry = s["fvg_b"] + ENTRY_PCT * fw
        sl_lo = s["obh_b"]; sl_hi = s["fvg_b"]
        sl = sl_lo + USER_SL_LONG * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = min(sl, entry - entry * MIN_SL_PCT / 100)
        if sl >= entry: return None
    else:
        entry = s["fvg_t"] - ENTRY_PCT * fw
        sl_hi = s["obh_t"]; sl_lo = s["fvg_t"]
        sl = sl_hi - USER_SL_SHORT * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = max(sl, entry + entry * MIN_SL_PCT / 100)
        if sl <= entry: return None
    return entry, sl


# ---------- M8 SAFE simulator ----------

def simulate_M8_safe(s, entry, sl, df_1m, df_1h, hull_1h_lbl,
                      max_hold_days=MAX_HOLD_DAYS):
    """SAFE M8: первый шаг — найти fill в 1m. Если нет — not_filled.

    Returns dict with outcome, R, reason, hold_h, fill_h.
    """
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0:
        return {"outcome": "invalid", "R": 0.0, "reason": "invalid",
                "hold_h": 0, "fill_h": 0}
    tf_min = s["tf_minutes"]
    entry_window_start = s["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = entry_window_start + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_window_start.tz_localize(None)
                          if entry_window_start.tz else entry_window_start)
    ee64 = np.datetime64(end_time.tz_localize(None)
                          if end_time.tz else end_time)

    # 1m slice
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return {"outcome": "no_data", "R": 0.0, "reason": "no_data",
                "hold_h": 0, "fill_h": 0}

    highs_1m = df_1m["high"].values[i0:i1].astype(np.float64)
    lows_1m = df_1m["low"].values[i0:i1].astype(np.float64)
    times_1m = df_1m.index.values[i0:i1]

    # ШАГ 1 (НОВОЕ): найти fill — первый 1m бар где цена дошла до entry
    if direction == "LONG":
        fill_mask = lows_1m <= entry
    else:
        fill_mask = highs_1m >= entry
    if not fill_mask.any():
        return {"outcome": "not_filled", "R": 0.0, "reason": "not_filled",
                "hold_h": 0, "fill_h": 0}
    fill_idx_1m = int(np.argmax(fill_mask))
    fill_time = pd.Timestamp(times_1m[fill_idx_1m]).tz_localize("UTC")
    fill_h = (fill_time - entry_window_start).total_seconds() / 3600

    # ШАГ 2: после fill, проверка SL и trail-exit на 1h checkpoints
    h0 = df_1h.index.searchsorted(fill_time, side="right")
    h1 = df_1h.index.searchsorted(end_time, side="right")
    if h0 >= h1:
        return {"outcome": "no_checkpoints", "R": 0.0, "reason": "no_data",
                "hold_h": 0, "fill_h": fill_h}
    checkpoints = df_1h.index[h0:h1]
    closes_1h = df_1h["close"].values

    flip_count = 0
    prev_idx_1m_in_window = fill_idx_1m  # начинаем сканировать SL от fill_idx
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_idx_1m = np.searchsorted(times_1m, cp64)
        # SL detection в окне [prev_check, cp]
        if cur_idx_1m > prev_idx_1m_in_window:
            wh = highs_1m[prev_idx_1m_in_window:cur_idx_1m]
            wl = lows_1m[prev_idx_1m_in_window:cur_idx_1m]
            if direction == "LONG" and (wl <= sl).any():
                hold_h = (cp - fill_time).total_seconds() / 3600
                return {"outcome": "loss", "R": -1.0, "reason": "sl_hit",
                        "hold_h": hold_h, "fill_h": fill_h}
            elif direction == "SHORT" and (wh >= sl).any():
                hold_h = (cp - fill_time).total_seconds() / 3600
                return {"outcome": "loss", "R": -1.0, "reason": "sl_hit",
                        "hold_h": hold_h, "fill_h": fill_h}
        prev_idx_1m_in_window = cur_idx_1m

        # Hull-1h label of last closed bar (= bar that ended at cp)
        cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
        if cp_close_idx < 0: continue
        cur_close = closes_1h[cp_close_idx]

        hl_idx = hull_1h_lbl.index.searchsorted(cp, side="right") - 1
        target = hl_idx - 1
        if target < 0: continue
        hl = hull_1h_lbl.iloc[target]

        if direction == "LONG" and hl == "down":
            flip_count += 1
        elif direction == "SHORT" and hl == "up":
            flip_count += 1
        else:
            flip_count = 0

        if flip_count >= 2:
            R = (cur_close - entry) / risk if direction == "LONG" \
                else (entry - cur_close) / risk
            hold_h = (cp - fill_time).total_seconds() / 3600
            return {"outcome": "win" if R > 0 else "loss",
                    "R": R, "reason": "hull_flip_x2",
                    "hold_h": hold_h, "fill_h": fill_h}

    # max_hold reached
    if len(checkpoints) > 0:
        last_cp = checkpoints[-1]
        cp_close_idx = df_1h.index.searchsorted(last_cp, side="right") - 2
        if cp_close_idx >= 0:
            cur_close = closes_1h[cp_close_idx]
            R = (cur_close - entry) / risk if direction == "LONG" \
                else (entry - cur_close) / risk
            hold_h = (last_cp - fill_time).total_seconds() / 3600
            return {"outcome": "win" if R > 0 else "loss",
                    "R": R, "reason": "max_hold",
                    "hold_h": hold_h, "fill_h": fill_h}
    return {"outcome": "open", "R": 0.0, "reason": "open",
            "hold_h": 0, "fill_h": fill_h}


def simulate_M8_inflated(s, entry, sl, df_1m, df_1h, hull_1h_lbl,
                          max_hold_days=MAX_HOLD_DAYS):
    """OLD M8 (без not_filled check) — для воспроизведения etap_45 inflation."""
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0:
        return {"outcome": "invalid", "R": 0.0, "reason": "invalid",
                "hold_h": 0, "fill_h": 0}
    tf_min = s["tf_minutes"]
    entry_time = s["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = entry_time + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_time.tz_localize(None) if entry_time.tz else entry_time)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)

    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0:
        return {"outcome": "no_data", "R": 0.0, "reason": "no_data",
                "hold_h": 0, "fill_h": 0}

    highs_1m = df_1m["high"].values[i0:i1].astype(np.float64)
    lows_1m = df_1m["low"].values[i0:i1].astype(np.float64)
    times_1m = df_1m.index.values[i0:i1]

    h0 = df_1h.index.searchsorted(entry_time, side="right")
    h1 = df_1h.index.searchsorted(end_time, side="right")
    if h0 >= h1:
        return {"outcome": "no_checkpoints", "R": 0.0, "reason": "no_data",
                "hold_h": 0, "fill_h": 0}
    checkpoints = df_1h.index[h0:h1]
    closes_1h = df_1h["close"].values

    flip_count = 0
    prev_idx_1m = 0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_idx_1m = np.searchsorted(times_1m, cp64)
        if cur_idx_1m > prev_idx_1m:
            wh = highs_1m[prev_idx_1m:cur_idx_1m]
            wl = lows_1m[prev_idx_1m:cur_idx_1m]
            if direction == "LONG" and (wl <= sl).any():
                return {"outcome": "loss", "R": -1.0, "reason": "sl_hit",
                        "hold_h": 0, "fill_h": 0}
            elif direction == "SHORT" and (wh >= sl).any():
                return {"outcome": "loss", "R": -1.0, "reason": "sl_hit",
                        "hold_h": 0, "fill_h": 0}
        prev_idx_1m = cur_idx_1m

        cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
        if cp_close_idx < 0: continue
        cur_close = closes_1h[cp_close_idx]

        hl_idx = hull_1h_lbl.index.searchsorted(cp, side="right") - 1
        target = hl_idx - 1
        if target < 0: continue
        hl = hull_1h_lbl.iloc[target]

        if direction == "LONG" and hl == "down":
            flip_count += 1
        elif direction == "SHORT" and hl == "up":
            flip_count += 1
        else:
            flip_count = 0

        if flip_count >= 2:
            R = (cur_close - entry) / risk if direction == "LONG" \
                else (entry - cur_close) / risk
            return {"outcome": "win" if R > 0 else "loss",
                    "R": R, "reason": "hull_flip_x2",
                    "hold_h": 0, "fill_h": 0}

    if len(checkpoints) > 0:
        last_cp = checkpoints[-1]
        cp_close_idx = df_1h.index.searchsorted(last_cp, side="right") - 2
        if cp_close_idx >= 0:
            cur_close = closes_1h[cp_close_idx]
            R = (cur_close - entry) / risk if direction == "LONG" \
                else (entry - cur_close) / risk
            return {"outcome": "win" if R > 0 else "loss",
                    "R": R, "reason": "max_hold",
                    "hold_h": 0, "fill_h": 0}
    return {"outcome": "open", "R": 0.0, "reason": "open",
            "hold_h": 0, "fill_h": 0}


# ---------- main ----------

def main():
    t0 = time.time()
    print("[INFO] загружаем данные")
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

    print("[INFO] Hull-1h labels")
    hull_1h = hull_ma(df_1h["close"], 78)
    hull_1h_lbl = hull_label_series(df_1h["close"], hull_1h)

    print("[INFO] детектируем 1.1.2 + dedup по SWEPT-key")
    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=False)
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept(s, df_1h, df_2h)
        if sw is None: continue
        groups[key].append({"sig": s, "swept": sw})
    all_reps = [paths[0]["sig"] for paths in groups.values()]
    cache = [precompute(s) for s in all_reps]
    print(f"  total signals (deduped): {len(cache)}")

    # Build orders for all setups (entry/SL fixed regardless of mode)
    orders = []
    for s in cache:
        tup = build_orders(s)
        if tup is None: continue
        entry, sl = tup
        orders.append((s, entry, sl))
    print(f"  orders built: {len(orders)}")

    # ============================================================
    # PASS 1 — INFLATED M8 (etap_45 reproduction)
    # ============================================================
    print(f"\n{'='*70}\nPASS 1: M8 INFLATED (etap_45 baseline reproduction)")
    print(f"{'='*70}")
    rows_inf = []
    for s, entry, sl in orders:
        r = simulate_M8_inflated(s, entry, sl, df_1m, df_1h, hull_1h_lbl)
        rows_inf.append({**r, "year": s["year"], "direction": s["direction"]})
    df_inf = pd.DataFrame(rows_inf)
    closed_inf = df_inf[df_inf["outcome"].isin(["win", "loss"])]
    nc = len(closed_inf)
    wr = (closed_inf["R"] > 0).mean() * 100 if nc else 0
    tot = closed_inf["R"].sum()
    yr = closed_inf.groupby("year")["R"].sum()
    bad = (yr < 0).sum()
    print(f"  n_total={len(df_inf)}, closed={nc}, WR={wr:.1f}%, "
          f"total={tot:+.1f}R, R/tr={closed_inf['R'].mean():+.3f}, "
          f"bad_yrs={bad}/{len(yr)}")
    by_reason = closed_inf["reason"].value_counts().to_dict()
    print(f"  exit reasons: {by_reason}")

    # ============================================================
    # PASS 2 — SAFE M8 (с not_filled check)
    # ============================================================
    print(f"\n{'='*70}\nPASS 2: M8 SAFE (с not_filled check)")
    print(f"{'='*70}")
    rows_safe = []
    for s, entry, sl in orders:
        r = simulate_M8_safe(s, entry, sl, df_1m, df_1h, hull_1h_lbl)
        rows_safe.append({**r, "year": s["year"], "direction": s["direction"]})
    df_safe = pd.DataFrame(rows_safe)

    n_total = len(df_safe)
    n_not_filled = (df_safe["outcome"] == "not_filled").sum()
    n_invalid = (df_safe["outcome"] == "invalid").sum()
    n_no_data = (df_safe["outcome"] == "no_data").sum()
    n_open = (df_safe["outcome"] == "open").sum()
    closed_safe = df_safe[df_safe["outcome"].isin(["win", "loss"])]
    nc = len(closed_safe)
    wins = (closed_safe["R"] > 0).sum()
    losses = (closed_safe["R"] < 0).sum()
    wr = wins / nc * 100 if nc else 0
    tot = closed_safe["R"].sum()
    yr = closed_safe.groupby("year")["R"].sum()
    bad = (yr < 0).sum()

    print(f"  n_total={n_total}")
    print(f"    not_filled (limit не сработал): {n_not_filled}  ({n_not_filled/n_total*100:.0f}%)")
    print(f"    invalid (risk<=0):              {n_invalid}")
    print(f"    no_data:                        {n_no_data}")
    print(f"    open (max_hold reached):        {n_open}")
    print(f"    closed (win+loss):              {nc}")
    print()
    print(f"  Из {nc} закрытых:")
    print(f"    wins={wins}, losses={losses}")
    print(f"    WR={wr:.1f}%, total_R={tot:+.1f}, R/tr={closed_safe['R'].mean():+.3f}")
    print(f"    bad_yrs={bad}/{len(yr)}")
    print(f"    avg fill wait: {closed_safe['fill_h'].mean():.1f}h")
    print(f"    avg hold: {closed_safe['hold_h'].mean():.1f}h")
    print()
    by_reason = closed_safe["reason"].value_counts().to_dict()
    print(f"  exit reasons: {by_reason}")

    # Year-by-year detail
    print(f"\n  Год-в-год (M8 SAFE):")
    yrs_full = closed_safe.groupby("year").agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total_R=("R", "sum"))
    yrs_full["WR"] = yrs_full["wins"] / yrs_full["n"] * 100
    yrs_full["R_tr"] = yrs_full["total_R"] / yrs_full["n"]
    for y, r in yrs_full.iterrows():
        flag = "  !" if r["total_R"] < 0 else ""
        print(f"    {int(y)}: n={int(r['n']):>3} WR={r['WR']:5.1f}% "
              f"total={r['total_R']:+5.1f}R R/tr={r['R_tr']:+.3f}{flag}")

    # ============================================================
    # COMPARISON
    # ============================================================
    print(f"\n{'='*70}\nCOMPARISON: INFLATED vs SAFE")
    print(f"{'='*70}")
    closed_inf = df_inf[df_inf["outcome"].isin(["win", "loss"])]
    print(f"  M8 INFLATED (etap_45):  closed={len(closed_inf)},  "
          f"WR={(closed_inf['R'] > 0).mean()*100:.1f}%,  "
          f"total={closed_inf['R'].sum():+.1f}R")
    print(f"  M8 SAFE (этот фикс):    closed={len(closed_safe)},  "
          f"WR={(closed_safe['R'] > 0).mean()*100:.1f}%,  "
          f"total={closed_safe['R'].sum():+.1f}R")
    diff = closed_inf['R'].sum() - closed_safe['R'].sum()
    print(f"  Inflation:              -{diff:.1f}R "
          f"({diff/closed_inf['R'].sum()*100:.0f}% от inflated)")

    # Save trades CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_out = OUT_DIR / "etap46_m8_safe_trades.csv"
    df_safe.to_csv(csv_out, index=False, encoding="utf-8-sig")
    print(f"\n[OK] CSV saved: {csv_out}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
