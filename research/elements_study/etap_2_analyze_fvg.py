"""Этап 2: глубокое исследование зон FVG (Fair Value Gap) на BTCUSDT.

Canon-определение ([vault/knowledge/smc/универсальные определения OB и FVG.md]):
  LONG FVG  (i-2, i-1, i): high(i-2) < low(i).   Zone = [high(i-2), low(i)]
  SHORT FVG (i-2, i-1, i): low(i-2) > high(i).   Zone = [high(i), low(i-2)]

Структура анализа аналогична OB (etap_1 + etap_1b):
  A. Базовые: count, FVG/day, размер %, LONG/SHORT баланс
  B. Жизнь зоны: % touched, median bars to touch
  C. Тип взаимодействия: wick / close_inside / pierce
  D. Эффективность: bounce_1x/2x/3x, median max_R, sl_first
  E. Context: size_vs_ATR, vs_EMA200, cluster, c1 body size

TF: 15m, 20m, 1h, 2h, 4h, 6h, 12h, 1d.
Lookback: 50 баров после образования.
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

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_fvg

SYMBOL = "BTCUSDT"
TFS_ALL = ["15m", "20m", "1h", "2h", "4h", "6h", "12h", "1d"]
TFS_CONTEXT = ["1h", "4h", "1d"]  # для контекстного анализа достаточно
LOOKBACK_BARS = 50
START_DATE = "2020-01-01"
TREND_LOOKBACK = 20

OUT_DIR = Path("research/elements_study/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [(high - low),
         (high - prev_close).abs(),
         (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def detect_all_fvgs(df: pd.DataFrame) -> list[dict]:
    """Все FVG на df. Cur idx = i (c2 в формулах)."""
    fvgs = []
    for idx in range(2, len(df)):
        f = detect_fvg(df, idx)
        if f is None:
            continue
        c0 = df.iloc[idx - 2]
        c1 = df.iloc[idx - 1]
        c2 = df.iloc[idx]
        mid = (f.bottom + f.top) / 2
        size_abs = f.top - f.bottom
        size_pct = size_abs / mid * 100 if mid > 0 else np.nan
        fvgs.append({
            "direction": f.direction,
            "c0_time": f.c0_time,
            "c2_time": f.c2_time,
            "cur_idx": idx,
            "bottom": f.bottom,
            "top": f.top,
            "size_abs": size_abs,
            "size_pct": size_pct,
            "c0_open": float(c0["open"]),
            "c0_close": float(c0["close"]),
            "c0_high": float(c0["high"]),
            "c0_low": float(c0["low"]),
            "c1_open": float(c1["open"]),
            "c1_close": float(c1["close"]),
            "c1_high": float(c1["high"]),
            "c1_low": float(c1["low"]),
            "c2_open": float(c2["open"]),
            "c2_close": float(c2["close"]),
        })
    return fvgs


def analyze_lifecycle(fvg_dict: dict, df: pd.DataFrame, lookback: int) -> dict:
    direction = fvg_dict["direction"]
    bottom = fvg_dict["bottom"]
    top = fvg_dict["top"]
    size = fvg_dict["size_abs"]
    cur_idx = fvg_dict["cur_idx"]
    end_idx = min(cur_idx + lookback, len(df) - 1)

    if cur_idx + 1 > end_idx or size <= 0:
        return {"touched": False, "touch_kind": "no_data",
                "bars_to_touch": np.nan, "max_bounce_R": np.nan,
                "bounce_1x": False, "bounce_2x": False, "bounce_3x": False,
                "sl_first_1x": False}

    touch_idx = None
    touch_kind = None
    for j in range(cur_idx + 1, end_idx + 1):
        row = df.iloc[j]
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        if direction == "LONG":
            # Цена приходит сверху-вниз; вход = low(j) <= top
            if l <= top:
                if c < bottom:
                    touch_kind = "pierce"
                elif bottom <= c <= top:
                    touch_kind = "close_inside"
                else:
                    touch_kind = "wick"
                touch_idx = j
                break
        else:
            if h >= bottom:
                if c > top:
                    touch_kind = "pierce"
                elif bottom <= c <= top:
                    touch_kind = "close_inside"
                else:
                    touch_kind = "wick"
                touch_idx = j
                break

    if touch_idx is None:
        return {"touched": False, "touch_kind": "never",
                "bars_to_touch": np.nan, "max_bounce_R": np.nan,
                "bounce_1x": False, "bounce_2x": False, "bounce_3x": False,
                "sl_first_1x": False}

    entry = top if direction == "LONG" else bottom
    sl = bottom if direction == "LONG" else top

    bounce_end = min(touch_idx + lookback, len(df))
    sub = df.iloc[touch_idx: bounce_end]
    sl_first_1x = False
    bounce_1x = False
    bounce_2x = False
    bounce_3x = False
    max_excursion = 0.0
    for _, r in sub.iterrows():
        h = float(r["high"])
        l = float(r["low"])
        if direction == "LONG":
            excursion = h - entry
            if l <= sl and not bounce_1x:
                sl_first_1x = True
            if excursion / size >= 1 and not bounce_1x:
                bounce_1x = True
            if excursion / size >= 2 and not bounce_2x:
                bounce_2x = True
            if excursion / size >= 3 and not bounce_3x:
                bounce_3x = True
            if excursion > max_excursion:
                max_excursion = excursion
        else:
            excursion = entry - l
            if h >= sl and not bounce_1x:
                sl_first_1x = True
            if excursion / size >= 1 and not bounce_1x:
                bounce_1x = True
            if excursion / size >= 2 and not bounce_2x:
                bounce_2x = True
            if excursion / size >= 3 and not bounce_3x:
                bounce_3x = True
            if excursion > max_excursion:
                max_excursion = excursion

    return {
        "touched": True,
        "touch_kind": touch_kind,
        "bars_to_touch": touch_idx - cur_idx,
        "max_bounce_R": max_excursion / size if size > 0 else np.nan,
        "bounce_1x": bounce_1x,
        "bounce_2x": bounce_2x,
        "bounce_3x": bounce_3x,
        "sl_first_1x": sl_first_1x,
    }


def load_df_with_compose(tf: str) -> pd.DataFrame:
    if tf == "20m":
        df_1m = load_df(SYMBOL, "1m")
        df = compose_from_base(df_1m, "20m")
    else:
        df = load_df(SYMBOL, tf)
    df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")]
    return df


def compute_context_for_fvg(df: pd.DataFrame, fvg_dict: dict,
                              atr_series: pd.Series, ema200: pd.Series,
                              last_long_idx: int, last_short_idx: int) -> dict:
    idx = fvg_dict["cur_idx"]
    direction = fvg_dict["direction"]
    size = fvg_dict["size_abs"]
    cur_close = fvg_dict["c2_close"]

    atr = float(atr_series.iloc[idx]) if not pd.isna(atr_series.iloc[idx]) else np.nan
    em = float(ema200.iloc[idx]) if not pd.isna(ema200.iloc[idx]) else np.nan

    pos_vs_ema200 = (
        "above" if not pd.isna(em) and cur_close > em
        else "below" if not pd.isna(em) and cur_close < em
        else "na"
    )
    fvg_size_atr = size / atr if atr and atr > 0 else np.nan
    if pd.isna(fvg_size_atr):
        size_label = "na"
    elif fvg_size_atr < 0.3:
        size_label = "small"
    elif fvg_size_atr < 1.0:
        size_label = "medium"
    else:
        size_label = "large"

    # Trend slope
    if idx >= TREND_LOOKBACK:
        y = df["close"].iloc[idx - TREND_LOOKBACK: idx].values
        x = np.arange(TREND_LOOKBACK)
        slope, _ = np.polyfit(x, y, 1)
        slope_pct = slope / y.mean() * 100
    else:
        slope_pct = np.nan

    if pd.isna(slope_pct):
        trend_label = "na"
    elif slope_pct > 0.05:
        trend_label = "up"
    elif slope_pct < -0.05:
        trend_label = "down"
    else:
        trend_label = "flat"

    if direction == "LONG" and pos_vs_ema200 == "above":
        dir_vs_htf = "pro_trend"
    elif direction == "SHORT" and pos_vs_ema200 == "below":
        dir_vs_htf = "pro_trend"
    elif pos_vs_ema200 == "na":
        dir_vs_htf = "na"
    else:
        dir_vs_htf = "counter_trend"

    # c1 свеча — body size относительно общего диапазона FVG
    c1_body = abs(fvg_dict["c1_close"] - fvg_dict["c1_open"])
    c1_range = fvg_dict["c1_high"] - fvg_dict["c1_low"]
    c1_body_vs_range = c1_body / c1_range if c1_range > 0 else np.nan
    c1_body_vs_size = c1_body / size if size > 0 else np.nan

    # c2 — impulse-свеча образующая gap
    c2_body = abs(fvg_dict["c2_close"] - fvg_dict["c2_open"])
    c2_body_vs_atr = c2_body / atr if atr and atr > 0 else np.nan

    # Cluster vs lone
    if direction == "LONG":
        bars_since_same = idx - last_long_idx
    else:
        bars_since_same = idx - last_short_idx

    if bars_since_same < 5:
        cluster_label = "cluster"
    elif bars_since_same < 20:
        cluster_label = "medium"
    else:
        cluster_label = "lone"

    return {
        "atr14": atr,
        "ema200": em,
        "pos_vs_ema200": pos_vs_ema200,
        "fvg_size_atr": fvg_size_atr,
        "size_label": size_label,
        "trend_slope": slope_pct,
        "trend_label": trend_label,
        "dir_vs_htf": dir_vs_htf,
        "c1_body_vs_range": c1_body_vs_range,
        "c1_body_vs_size": c1_body_vs_size,
        "c2_body_vs_atr": c2_body_vs_atr,
        "bars_since_same_dir": bars_since_same,
        "cluster_label": cluster_label,
    }


def analyze_tf(tf: str, with_context: bool) -> tuple[pd.DataFrame, dict]:
    print(f"\n[{tf}] loading + computing")
    df = load_df_with_compose(tf)
    if df.empty:
        return pd.DataFrame(), {}
    df = df.copy()
    if with_context:
        df["atr14"] = compute_atr(df, 14)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    print(f"  bars: {len(df)}")

    fvgs = detect_all_fvgs(df)
    print(f"  found {len(fvgs)} FVGs")

    last_long_idx = -1000
    last_short_idx = -1000
    rows = []
    for f in fvgs:
        outcome = analyze_lifecycle(f, df, LOOKBACK_BARS)
        row = {**f, **outcome}
        if with_context:
            ctx = compute_context_for_fvg(df, f, df["atr14"], df["ema200"],
                                            last_long_idx, last_short_idx)
            row.update(ctx)
            if f["direction"] == "LONG":
                last_long_idx = f["cur_idx"]
            else:
                last_short_idx = f["cur_idx"]
        rows.append(row)
    df_fvgs = pd.DataFrame(rows)
    df_fvgs["tf"] = tf

    # Aggregate базовые метрики
    n_total = len(df_fvgs)
    n_long = int((df_fvgs["direction"] == "LONG").sum())
    n_short = int((df_fvgs["direction"] == "SHORT").sum())
    days_span = (df.index[-1] - df.index[0]).total_seconds() / 86400
    fvgs_per_day = n_total / days_span if days_span > 0 else 0

    touched = df_fvgs[df_fvgs["touched"] == True]
    n_touched = len(touched)

    summary = {
        "tf": tf,
        "bars": len(df),
        "days": round(days_span, 1),
        "n_fvgs": n_total,
        "fvgs_per_day": round(fvgs_per_day, 3),
        "n_long": n_long,
        "n_short": n_short,
        "median_size_pct": round(df_fvgs["size_pct"].median(), 4),
        "n_touched": n_touched,
        "pct_touched": round(n_touched / n_total * 100, 1) if n_total else 0,
        "median_bars_to_touch": float(touched["bars_to_touch"].median()) if not touched.empty else None,
        "pct_wick": round((touched["touch_kind"] == "wick").mean() * 100, 1) if not touched.empty else 0,
        "pct_close_inside": round((touched["touch_kind"] == "close_inside").mean() * 100, 1) if not touched.empty else 0,
        "pct_pierce": round((touched["touch_kind"] == "pierce").mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_1x": round(touched["bounce_1x"].mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_2x": round(touched["bounce_2x"].mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_3x": round(touched["bounce_3x"].mean() * 100, 1) if not touched.empty else 0,
        "median_max_bounce_R": round(touched["max_bounce_R"].median(), 3) if not touched.empty else None,
        "pct_sl_first": round(touched["sl_first_1x"].mean() * 100, 1) if not touched.empty else 0,
    }
    return df_fvgs, summary


def report_segment(df_fvgs: pd.DataFrame, group_col: str, label: str):
    df_t = df_fvgs[df_fvgs["touched"] == True].copy()
    if df_t.empty or group_col not in df_t.columns:
        return
    g = df_t.groupby(group_col).agg(
        n=("touched", "size"),
        WR_1x=("bounce_1x", lambda s: s.mean() * 100),
        sl_first=("sl_first_1x", lambda s: s.mean() * 100),
        median_R=("max_bounce_R", "median"),
        pct_pierce=("touch_kind", lambda s: (s == "pierce").mean() * 100),
    ).round(2)
    g = g.sort_values("median_R", ascending=False)
    print(f"\n--- {label} ---")
    print(g.to_string())


def main():
    print("=" * 80)
    print("ЭТАП 2 — FVG: базовый анализ всех TF")
    print("=" * 80)
    summaries = []
    for tf in TFS_ALL:
        df_fvgs, summ = analyze_tf(tf, with_context=False)
        if df_fvgs.empty:
            continue
        df_fvgs.to_csv(OUT_DIR / f"fvg_{tf}.csv", index=False)
        summaries.append(summ)

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(OUT_DIR / "fvg_summary.csv", index=False)
    print()
    print("СВОДКА:")
    print(summary_df.to_string(index=False))

    print("\n" + "=" * 80)
    print("ЭТАП 2b — FVG context (1h, 4h, 1d)")
    print("=" * 80)

    for tf in TFS_CONTEXT:
        df_fvgs, _ = analyze_tf(tf, with_context=True)
        if df_fvgs.empty:
            continue
        df_fvgs.to_csv(OUT_DIR / f"fvg_context_{tf}.csv", index=False)
        n_total = len(df_fvgs)
        n_touched = (df_fvgs["touched"] == True).sum()
        print(f"\n############ TF = {tf}  ({n_total} FVGs, {n_touched} touched) ############")
        report_segment(df_fvgs, "size_label", "FVG size vs ATR(14)")
        report_segment(df_fvgs, "trend_label", "Trend slope (20 bars)")
        report_segment(df_fvgs, "pos_vs_ema200", "Position vs EMA200")
        report_segment(df_fvgs, "dir_vs_htf", "Direction vs HTF trend")
        report_segment(df_fvgs, "cluster_label", "Cluster vs Lone (same dir)")
        report_segment(df_fvgs, "touch_kind", "Touch kind (kontrol)")


if __name__ == "__main__":
    main()
