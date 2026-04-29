"""Grid search оптимальных entry/SL для Strategy 1.1.1.

Параметры:
  - TP price level = const (вычисляется при базовых entry=mid_FVG, SL=OB-D edge, RR=1)
  - entry — позиция в FVG, ±20% от базового 50%, шаг 1% от FVG-zone
    диапазон entry_pct ∈ [30%, 70%]
  - SL — сдвиг ±20% от OB-D edge, шаг 1% от ширины OB-D
    sl_pct > 0 → SL ближе к entry (тугой), sl_pct < 0 → дальше от entry (с буфером)
    LONG SL = OB-D.bottom + sl_pct × OB-D_w (положительный шаг = вверх)
    SHORT SL = OB-D.top - sl_pct × OB-D_w (положительный шаг = вниз)
    защита: SL < entry для LONG, SL > entry для SHORT — иначе combo скип

R-units: 1R = новый risk = |entry - SL| (per-signal). Win = +RR, Loss = -1.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
OUTPUT_PATH = Path("signals/strategy_1_1_1_optimize.csv")
ENTRY_GRID = np.arange(30, 71, 1) / 100.0  # 30%..70% step 1% (base 50%, ±20%)
SL_GRID = np.arange(-20, 21, 1) / 100.0    # -20%..+20% step 1% (base 0%, ±20%)


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    """Подготовить numpy-кэш per signal: highs/lows forward от signal_time+15min."""
    fvg_b, fvg_t = sig["fvg_zone"]
    obd_b, obd_t = sig["ob_d_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]

    if direction == "LONG":
        entry_orig = (fvg_b + fvg_t) / 2
        sl_orig = obd_b
        tp_const = entry_orig + (entry_orig - sl_orig)
    else:
        entry_orig = (fvg_b + fvg_t) / 2
        sl_orig = obd_t
        tp_const = entry_orig - (sl_orig - entry_orig)

    fill_scan_start = sig["signal_time"] + pd.Timedelta(minutes=15)
    forward = df_1m[df_1m.index >= fill_scan_start]
    if forward.empty:
        return None

    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obd_b": float(obd_b), "obd_t": float(obd_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "tp_const": float(tp_const),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate_long(s: dict, entry: float, sl: float, tp: float) -> str:
    highs = s["highs"]
    lows = s["lows"]
    # Fill: первая 1m свеча с low <= entry
    fill_mask = lows <= entry
    if not fill_mask.any():
        return "not_filled"
    fill_idx = int(np.argmax(fill_mask))
    # После fill: SL hit (low <= sl) vs TP hit (high >= tp)
    post_l = lows[fill_idx:]
    post_h = highs[fill_idx:]
    sl_mask = post_l <= sl
    tp_mask = post_h >= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1:
        return "open"
    if sl_first == -1:
        return "win"
    if tp_first == -1:
        return "loss"
    # Тай в одной свече → SL побеждает (как в backtest)
    return "win" if tp_first < sl_first else "loss"


def simulate_short(s: dict, entry: float, sl: float, tp: float) -> str:
    highs = s["highs"]
    lows = s["lows"]
    fill_mask = highs >= entry
    if not fill_mask.any():
        return "not_filled"
    fill_idx = int(np.argmax(fill_mask))
    post_l = lows[fill_idx:]
    post_h = highs[fill_idx:]
    sl_mask = post_h >= sl
    tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1:
        return "open"
    if sl_first == -1:
        return "win"
    if tp_first == -1:
        return "loss"
    return "win" if tp_first < sl_first else "loss"


def main():
    print(f"[INFO] Optimize Strategy 1.1.1, {SYMBOL}, окно {DAYS_BACK}d")
    print(f"  entry grid: {len(ENTRY_GRID)} positions (30%-70% step 1% от FVG, base 50%)")
    print(f"  SL grid: {len(SL_GRID)} positions (-20%..+20% step 1% от OB-D, base 0%)")
    print(f"  total combos: {len(ENTRY_GRID) * len(SL_GRID):,}")
    print()

    print("[INFO] загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_filtered = df_1d[df_1d.index >= cutoff]

    print("[INFO] сбор сигналов")
    signals = detect_strategy_1_1_1_signals(
        df_1d_filtered, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=False,
    )
    print(f"  signals: {len(signals)}")
    if not signals:
        return

    print("[INFO] precompute 1m forward arrays per signal")
    sig_cache = []
    for s in signals:
        c = precompute_signal(s, df_1m)
        if c is not None:
            sig_cache.append(c)
    print(f"  cached: {len(sig_cache)}")

    print()
    print("[INFO] grid search")
    rows = []
    n_combos = len(ENTRY_GRID) * len(SL_GRID)
    progress_step = max(1, n_combos // 20)
    combo_idx = 0
    for ep in ENTRY_GRID:
        for sp in SL_GRID:
            wins = 0
            losses = 0
            not_filled = 0
            skipped = 0
            opened = 0
            pnl_r = 0.0
            rr_sum = 0.0
            n_with_rr = 0
            for s in sig_cache:
                fvg_w = s["fvg_t"] - s["fvg_b"]
                obd_w = s["obd_t"] - s["obd_b"]
                if s["direction"] == "LONG":
                    entry = s["fvg_b"] + ep * fvg_w
                    sl = s["obd_b"] + sp * obd_w  # sp > 0 → выше OB-D.bottom (тугой)
                    tp = s["tp_const"]
                    if sl >= entry or tp <= entry:
                        skipped += 1
                        continue
                    rr = (tp - entry) / (entry - sl)
                    outcome = simulate_long(s, entry, sl, tp)
                else:
                    entry = s["fvg_t"] - ep * fvg_w
                    sl = s["obd_t"] - sp * obd_w  # sp > 0 → ниже OB-D.top (тугой)
                    tp = s["tp_const"]
                    if sl <= entry or tp >= entry:
                        skipped += 1
                        continue
                    rr = (entry - tp) / (sl - entry)
                    outcome = simulate_short(s, entry, sl, tp)
                if outcome == "win":
                    wins += 1
                    pnl_r += rr
                    rr_sum += rr
                    n_with_rr += 1
                elif outcome == "loss":
                    losses += 1
                    pnl_r -= 1.0
                    rr_sum += rr
                    n_with_rr += 1
                elif outcome == "open":
                    opened += 1
                    rr_sum += rr
                    n_with_rr += 1
                else:
                    not_filled += 1
            closed = wins + losses
            wr = wins / closed * 100 if closed else 0
            avg_rr = rr_sum / n_with_rr if n_with_rr else 0
            rows.append({
                "entry_pct": round(ep * 100, 0),
                "sl_pct": round(sp * 100, 0),
                "wins": wins,
                "losses": losses,
                "not_filled": not_filled,
                "open": opened,
                "skipped": skipped,
                "wr_pct": round(wr, 1),
                "avg_rr": round(avg_rr, 3),
                "pnl_r": round(pnl_r, 2),
            })
            combo_idx += 1
            if combo_idx % progress_step == 0:
                print(f"  {combo_idx:,}/{n_combos:,} combos done")

    df = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values("pnl_r", ascending=False).to_csv(OUTPUT_PATH, index=False)
    print(f"  записано в {OUTPUT_PATH}")

    print()
    print("=" * 90)
    print("TOP 15 by PnL (R-units, R = new_risk per trade):")
    print("=" * 90)
    top = df.sort_values("pnl_r", ascending=False).head(15)
    print(top.to_string(index=False))

    print()
    print("=" * 90)
    print("TOP 5 by avg_rr (требуем pnl_r > 0):")
    print("=" * 90)
    pos = df[df["pnl_r"] > 0].sort_values("avg_rr", ascending=False).head(5)
    print(pos.to_string(index=False))

    print()
    print("=" * 90)
    print("Текущая базовая (entry_pct=50, sl_pct=0):")
    print("=" * 90)
    cur = df[(df["entry_pct"] == 50) & (df["sl_pct"] == 0)]
    print(cur.to_string(index=False))


if __name__ == "__main__":
    main()
