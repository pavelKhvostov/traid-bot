"""Этап 1b: контекст образования OB — какие условия делают зону «хорошей».

Для каждого OB добавляем context-features:
  1. Trend slope (linreg на close за 20 баров)
  2. Position vs EMA200 (above/below)
  3. OB size relative to ATR14 (small/medium/large)
  4. Cur engulfs prev? (impulse strength)
  5. Cur body % of prev range
  6. Bars since last OB same direction (cluster vs lone)
  7. Direction vs HTF trend (pro-trend vs counter-trend)

Затем сегментируем и сравниваем WR (bounce_1x, sl_hit_first, median_max_R).

TF: 1h, 4h, 1d (репрезентативный набор; 15m избыточно).
Lookback после OB: 50 баров (как в etap_1).
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

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair

SYMBOL = "BTCUSDT"
TFS = ["1h", "4h", "1d"]
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


def compute_trend_slope(df: pd.DataFrame, idx: int, lookback: int = 20) -> float:
    """Линейная регрессия close за последние `lookback` баров.
    Возвращает slope in % от mean price."""
    if idx < lookback:
        return np.nan
    y = df["close"].iloc[idx - lookback: idx].values
    x = np.arange(lookback)
    if len(y) < 3:
        return np.nan
    slope, _ = np.polyfit(x, y, 1)
    mean_p = y.mean()
    return slope / mean_p * 100  # % per bar


def analyze_lifecycle(ob_dict: dict, df: pd.DataFrame, lookback: int):
    """Тот же lifecycle что в etap_1, но возвращает только нужное."""
    direction = ob_dict["direction"]
    bottom = ob_dict["bottom"]
    top = ob_dict["top"]
    size = ob_dict["size_abs"]
    cur_idx = ob_dict["cur_idx"]
    end_idx = min(cur_idx + lookback, len(df) - 1)

    if cur_idx + 1 > end_idx or size <= 0:
        return {"touched": False, "bounce_1x": False, "sl_first_1x": False,
                "max_bounce_R": np.nan, "touch_kind": "no_data"}

    touch_idx = None
    touch_kind = None
    for j in range(cur_idx + 1, end_idx + 1):
        row = df.iloc[j]
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        if direction == "LONG":
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
        return {"touched": False, "bounce_1x": False, "sl_first_1x": False,
                "max_bounce_R": np.nan, "touch_kind": "never"}

    entry = top if direction == "LONG" else bottom
    sl = bottom if direction == "LONG" else top

    bounce_end = min(touch_idx + lookback, len(df))
    sub = df.iloc[touch_idx: bounce_end]
    bounce_1x = False
    sl_first_1x = False
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
            if excursion > max_excursion:
                max_excursion = excursion
        else:
            excursion = entry - l
            if h >= sl and not bounce_1x:
                sl_first_1x = True
            if excursion / size >= 1 and not bounce_1x:
                bounce_1x = True
            if excursion > max_excursion:
                max_excursion = excursion

    return {
        "touched": True,
        "touch_kind": touch_kind,
        "bounce_1x": bounce_1x,
        "sl_first_1x": sl_first_1x,
        "max_bounce_R": max_excursion / size if size > 0 else np.nan,
    }


def analyze_tf(tf: str) -> pd.DataFrame:
    print(f"\n[{tf}] loading data + computing indicators")
    df = load_df(SYMBOL, tf)
    df = df[df.index >= pd.Timestamp(START_DATE, tz="UTC")]
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["atr14"] = compute_atr(df, 14)
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    print(f"  bars: {len(df)}")

    print(f"  detecting OBs + features...")
    last_long_idx = -1000
    last_short_idx = -1000
    rows = []
    for idx in range(1, len(df)):
        ob = detect_ob_pair(df, idx)
        if ob is None:
            continue
        prev = df.iloc[idx - 1]
        cur = df.iloc[idx]
        atr = float(df["atr14"].iloc[idx]) if not pd.isna(df["atr14"].iloc[idx]) else np.nan
        ema200 = float(df["ema200"].iloc[idx]) if not pd.isna(df["ema200"].iloc[idx]) else np.nan
        cur_close = float(cur["close"])
        cur_open = float(cur["open"])
        prev_open = float(prev["open"])
        prev_close = float(prev["close"])

        prev_range = float(prev["high"]) - float(prev["low"])
        cur_range = float(cur["high"]) - float(cur["low"])
        prev_body = abs(prev_close - prev_open)
        cur_body = abs(cur_close - cur_open)
        ob_size = ob.top - ob.bottom

        # Trend slope за TREND_LOOKBACK баров
        trend_slope = compute_trend_slope(df, idx, TREND_LOOKBACK)

        # Position vs EMA200
        pos_vs_ema200 = (
            "above" if cur_close > ema200
            else "below" if cur_close < ema200
            else "at"
        ) if not pd.isna(ema200) else "na"

        # OB size vs ATR14 (relative)
        ob_size_atr = ob_size / atr if atr and atr > 0 else np.nan

        # Cur engulfs prev (по body)
        prev_body_top = max(prev_open, prev_close)
        prev_body_bot = min(prev_open, prev_close)
        cur_body_top = max(cur_open, cur_close)
        cur_body_bot = min(cur_open, cur_close)
        cur_engulfs_prev = (cur_body_top >= prev_body_top
                            and cur_body_bot <= prev_body_bot)

        # Cur body относительно prev range
        cur_body_vs_prev_range = cur_body / prev_range if prev_range > 0 else np.nan

        # Bars since last OB same direction
        if ob.direction == "LONG":
            bars_since_same_dir = idx - last_long_idx
            last_long_idx = idx
        else:
            bars_since_same_dir = idx - last_short_idx
            last_short_idx = idx

        # Trend direction по slope
        if pd.isna(trend_slope):
            trend_label = "na"
        elif trend_slope > 0.05:  # >0.05% per bar
            trend_label = "up"
        elif trend_slope < -0.05:
            trend_label = "down"
        else:
            trend_label = "flat"

        # Direction vs HTF trend
        if ob.direction == "LONG" and pos_vs_ema200 == "above":
            dir_vs_htf = "pro_trend"
        elif ob.direction == "SHORT" and pos_vs_ema200 == "below":
            dir_vs_htf = "pro_trend"
        elif pos_vs_ema200 == "na":
            dir_vs_htf = "na"
        else:
            dir_vs_htf = "counter_trend"

        ob_size_atr_label = (
            "small" if pd.notna(ob_size_atr) and ob_size_atr < 0.3
            else "medium" if pd.notna(ob_size_atr) and ob_size_atr < 1.0
            else "large" if pd.notna(ob_size_atr)
            else "na"
        )

        cluster_label = (
            "cluster" if bars_since_same_dir < 5
            else "medium" if bars_since_same_dir < 20
            else "lone"
        )

        ob_dict = {
            "direction": ob.direction,
            "bottom": ob.bottom,
            "top": ob.top,
            "size_abs": ob_size,
            "cur_idx": idx,
            "cur_time": ob.cur_time,
            "trend_slope": trend_slope,
            "trend_label": trend_label,
            "pos_vs_ema200": pos_vs_ema200,
            "ob_size_atr": ob_size_atr,
            "ob_size_atr_label": ob_size_atr_label,
            "cur_engulfs_prev": cur_engulfs_prev,
            "cur_body_vs_prev_range": cur_body_vs_prev_range,
            "bars_since_same_dir": bars_since_same_dir,
            "cluster_label": cluster_label,
            "dir_vs_htf": dir_vs_htf,
        }

        # Outcome
        oc = analyze_lifecycle(ob_dict, df, LOOKBACK_BARS)
        rows.append({**ob_dict, **oc})

    df_obs = pd.DataFrame(rows)
    df_obs["tf"] = tf
    return df_obs


def report_segment(df_obs: pd.DataFrame, group_col: str, label: str):
    """Сегментация по фиче. Возвращает строки для печати."""
    df_t = df_obs[df_obs["touched"] == True].copy()
    g = df_t.groupby(group_col).agg(
        n=("touched", "size"),
        bounce_1x=("bounce_1x", lambda s: s.mean() * 100),
        sl_first_1x=("sl_first_1x", lambda s: s.mean() * 100),
        median_max_R=("max_bounce_R", "median"),
        pct_pierce=("touch_kind", lambda s: (s == "pierce").mean() * 100),
    ).round(2)
    g = g.sort_values("median_max_R", ascending=False)
    print(f"\n--- {label} (group={group_col}) ---")
    print(g.to_string())
    return g


def main():
    all_tf = []
    for tf in TFS:
        df_obs = analyze_tf(tf)
        if df_obs.empty:
            continue
        df_obs.to_csv(OUT_DIR / f"ob_context_{tf}.csv", index=False)
        all_tf.append(df_obs)

    print("\n" + "=" * 80)
    print("СЕГМЕНТАЦИИ — каждый TF отдельно")
    print("=" * 80)

    for df_obs in all_tf:
        tf = df_obs["tf"].iloc[0]
        n_total = len(df_obs)
        n_touched = (df_obs["touched"] == True).sum()
        print(f"\n############ TF = {tf} ({n_total} OB, {n_touched} touched) ############")
        report_segment(df_obs, "trend_label", "Trend slope (20 bars)")
        report_segment(df_obs, "pos_vs_ema200", "Position vs EMA200")
        report_segment(df_obs, "dir_vs_htf", "Direction vs HTF trend (EMA200)")
        report_segment(df_obs, "ob_size_atr_label", "OB size vs ATR(14)")
        report_segment(df_obs, "cur_engulfs_prev", "Cur engulfs prev (impulse)")
        report_segment(df_obs, "cluster_label", "Cluster vs Lone (same dir)")
        report_segment(df_obs, "touch_kind", "Touch kind (kontrol)")


if __name__ == "__main__":
    main()
