"""Этап 4: фракталы Билла Уильямса (FH = HH-фрактал, FL = LL-фрактал) на BTCUSDT.

Canon ([vault/knowledge/smc/фракталы билла уильямса.md]):
  HH-фрактал (FH): high[i] > high[k] для k ∈ {i-2, i-1, i+1, i+2}
  LL-фрактал (FL): low[i]  < low[k]  для k ∈ {i-2, i-1, i+1, i+2}
  Подтверждается на close i+2.

Особенность: фрактал — это **уровень** (одно число), не зона. Поэтому
метрики bounce/SL через ATR(14) на момент образования.

Анализ:
  A. Базовые: count, FH/FL/day, median LL/HH в %, баланс
  B. Жизнь уровня: % touched, median bars to touch
  C. Тип взаимодействия:
     - wick: high(j)>=level (FH) И close<level → respect
     - sweep: close>=level (FH) → пробой
  D. Эффективность: bounce_1x_ATR / 2x / 3x, sl_first
  E. Контекст

TFs: 15m, 20m, 1h, 2h, 4h, 6h, 12h, 1d.
Lookback: 50 баров после подтверждения (после i+2).
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

SYMBOL = "BTCUSDT"
TFS_ALL = ["15m", "20m", "1h", "2h", "4h", "6h", "12h", "1d"]
TFS_CONTEXT = ["1h", "4h", "1d"]
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


def is_hh_fractal(df: pd.DataFrame, i: int) -> bool:
    if i < 2 or i + 2 >= len(df):
        return False
    hi = float(df["high"].iloc[i])
    for k in (i - 2, i - 1, i + 1, i + 2):
        if hi <= float(df["high"].iloc[k]):
            return False
    return True


def is_ll_fractal(df: pd.DataFrame, i: int) -> bool:
    if i < 2 or i + 2 >= len(df):
        return False
    lo = float(df["low"].iloc[i])
    for k in (i - 2, i - 1, i + 1, i + 2):
        if lo >= float(df["low"].iloc[k]):
            return False
    return True


def detect_all_fractals(df: pd.DataFrame) -> list[dict]:
    fractals = []
    for i in range(2, len(df) - 2):
        is_hh = is_hh_fractal(df, i)
        is_ll = is_ll_fractal(df, i)
        if not (is_hh or is_ll):
            continue
        # Может быть и HH и LL одновременно (редко) — игнорируем такие
        if is_hh and is_ll:
            continue
        if is_hh:
            level = float(df["high"].iloc[i])
            ftype = "FH"
            direction = "SHORT"  # SHORT-сетап от HH-уровня
        else:
            level = float(df["low"].iloc[i])
            ftype = "FL"
            direction = "LONG"
        fractals.append({
            "fractal_type": ftype,
            "direction": direction,
            "fractal_idx": i,
            "fractal_time": df.index[i],
            "level": level,
            "confirmation_idx": i + 2,
            "confirmation_time": df.index[i + 2],
        })
    return fractals


def analyze_lifecycle(f_dict: dict, df: pd.DataFrame, atr_series: pd.Series,
                      lookback: int) -> dict:
    direction = f_dict["direction"]
    level = f_dict["level"]
    confirm_idx = f_dict["confirmation_idx"]
    end_idx = min(confirm_idx + lookback, len(df) - 1)
    atr = float(atr_series.iloc[confirm_idx]) if not pd.isna(atr_series.iloc[confirm_idx]) else np.nan

    if confirm_idx + 1 > end_idx or pd.isna(atr) or atr <= 0:
        return {"touched": False, "touch_kind": "no_data",
                "bars_to_touch": np.nan, "atr_at_confirm": atr,
                "max_bounce_R": np.nan, "bounce_1x": False,
                "bounce_2x": False, "bounce_3x": False, "sl_first_1x": False}

    touch_idx = None
    touch_kind = None
    for j in range(confirm_idx + 1, end_idx + 1):
        row = df.iloc[j]
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        if direction == "SHORT":  # FH = HH-fractal — SHORT setup
            # Touch = high >= level
            if h >= level:
                if c >= level:
                    touch_kind = "sweep"  # close выше уровня — пробой
                else:
                    touch_kind = "wick"   # close ниже = respect
                touch_idx = j
                break
        else:  # LONG (FL)
            if l <= level:
                if c <= level:
                    touch_kind = "sweep"
                else:
                    touch_kind = "wick"
                touch_idx = j
                break

    if touch_idx is None:
        return {"touched": False, "touch_kind": "never",
                "bars_to_touch": np.nan, "atr_at_confirm": atr,
                "max_bounce_R": np.nan, "bounce_1x": False,
                "bounce_2x": False, "bounce_3x": False, "sl_first_1x": False}

    # Entry = level (на касании). SL = level + 1·ATR в обратную сторону (типичный sweep stop).
    entry = level
    sl_distance = atr  # в R-units (ATR)
    if direction == "SHORT":
        sl = entry + sl_distance
    else:
        sl = entry - sl_distance

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
        if direction == "SHORT":
            excursion = entry - l  # SHORT profit
            if h >= sl and not bounce_1x:
                sl_first_1x = True
            if excursion / atr >= 1 and not bounce_1x:
                bounce_1x = True
            if excursion / atr >= 2 and not bounce_2x:
                bounce_2x = True
            if excursion / atr >= 3 and not bounce_3x:
                bounce_3x = True
            if excursion > max_excursion:
                max_excursion = excursion
        else:
            excursion = h - entry  # LONG profit
            if l <= sl and not bounce_1x:
                sl_first_1x = True
            if excursion / atr >= 1 and not bounce_1x:
                bounce_1x = True
            if excursion / atr >= 2 and not bounce_2x:
                bounce_2x = True
            if excursion / atr >= 3 and not bounce_3x:
                bounce_3x = True
            if excursion > max_excursion:
                max_excursion = excursion

    return {
        "touched": True,
        "touch_kind": touch_kind,
        "bars_to_touch": touch_idx - confirm_idx,
        "atr_at_confirm": atr,
        "max_bounce_R": max_excursion / atr if atr > 0 else np.nan,
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


def analyze_tf(tf: str, with_context: bool):
    print(f"\n[{tf}] loading + computing")
    df = load_df_with_compose(tf)
    if df.empty:
        return pd.DataFrame(), {}
    df = df.copy()
    df["atr14"] = compute_atr(df, 14)
    if with_context:
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    print(f"  bars: {len(df)}")

    fractals = detect_all_fractals(df)
    print(f"  found {len(fractals)} fractals (FH+FL)")

    last_fh_idx = -1000
    last_fl_idx = -1000
    rows = []
    for f in fractals:
        outcome = analyze_lifecycle(f, df, df["atr14"], LOOKBACK_BARS)
        row = {**f, **outcome}
        if with_context:
            idx = f["confirmation_idx"]
            cur_close = float(df["close"].iloc[idx])
            em = float(df["ema200"].iloc[idx]) if not pd.isna(df["ema200"].iloc[idx]) else np.nan
            pos_vs_ema200 = (
                "above" if not pd.isna(em) and cur_close > em
                else "below" if not pd.isna(em) and cur_close < em
                else "na"
            )

            if idx >= TREND_LOOKBACK:
                y = df["close"].iloc[idx - TREND_LOOKBACK: idx].values
                slope, _ = np.polyfit(np.arange(TREND_LOOKBACK), y, 1)
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

            if f["direction"] == "LONG" and pos_vs_ema200 == "above":
                dir_vs_htf = "pro_trend"
            elif f["direction"] == "SHORT" and pos_vs_ema200 == "below":
                dir_vs_htf = "pro_trend"
            elif pos_vs_ema200 == "na":
                dir_vs_htf = "na"
            else:
                dir_vs_htf = "counter_trend"

            if f["fractal_type"] == "FH":
                bs = idx - last_fh_idx
                last_fh_idx = idx
            else:
                bs = idx - last_fl_idx
                last_fl_idx = idx
            cluster_label = "cluster" if bs < 5 else "medium" if bs < 20 else "lone"

            row.update({
                "ema200": em,
                "pos_vs_ema200": pos_vs_ema200,
                "trend_slope": slope_pct,
                "trend_label": trend_label,
                "dir_vs_htf": dir_vs_htf,
                "bars_since_same_type": bs,
                "cluster_label": cluster_label,
            })
        rows.append(row)
    df_z = pd.DataFrame(rows)
    df_z["tf"] = tf

    n_total = len(df_z)
    n_fh = int((df_z["fractal_type"] == "FH").sum())
    n_fl = int((df_z["fractal_type"] == "FL").sum())
    days_span = (df.index[-1] - df.index[0]).total_seconds() / 86400
    per_day = n_total / days_span if days_span > 0 else 0
    touched = df_z[df_z["touched"] == True]

    summary = {
        "tf": tf,
        "bars": len(df),
        "days": round(days_span, 1),
        "n_fractals": n_total,
        "fractals_per_day": round(per_day, 4),
        "n_FH": n_fh,
        "n_FL": n_fl,
        "median_atr_at_confirm": round(df_z["atr_at_confirm"].median(), 3) if n_total else None,
        "n_touched": len(touched),
        "pct_touched": round(len(touched) / n_total * 100, 1) if n_total else 0,
        "median_bars_to_touch": float(touched["bars_to_touch"].median()) if not touched.empty else None,
        "pct_wick": round((touched["touch_kind"] == "wick").mean() * 100, 1) if not touched.empty else 0,
        "pct_sweep": round((touched["touch_kind"] == "sweep").mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_1x_atr": round(touched["bounce_1x"].mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_2x_atr": round(touched["bounce_2x"].mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_3x_atr": round(touched["bounce_3x"].mean() * 100, 1) if not touched.empty else 0,
        "median_max_R_atr": round(touched["max_bounce_R"].median(), 3) if not touched.empty else None,
        "pct_sl_first": round(touched["sl_first_1x"].mean() * 100, 1) if not touched.empty else 0,
    }
    return df_z, summary


def report_segment(df_z: pd.DataFrame, group_col: str, label: str):
    df_t = df_z[df_z["touched"] == True].copy()
    if df_t.empty or group_col not in df_t.columns:
        return
    g = df_t.groupby(group_col).agg(
        n=("touched", "size"),
        WR_1x=("bounce_1x", lambda s: round(s.mean() * 100, 1)),
        sl_first=("sl_first_1x", lambda s: round(s.mean() * 100, 1)),
        median_R=("max_bounce_R", "median"),
        pct_sweep=("touch_kind", lambda s: round((s == "sweep").mean() * 100, 1)),
    ).round(2)
    g = g.sort_values("median_R", ascending=False)
    print(f"\n--- {label} ---")
    print(g.to_string())


def main():
    print("=" * 80)
    print("ЭТАП 4 — Fractals (FH/FL): basic per TF")
    print("=" * 80)
    summaries = []
    for tf in TFS_ALL:
        df_z, summ = analyze_tf(tf, with_context=False)
        if df_z.empty:
            continue
        df_z.to_csv(OUT_DIR / f"fractals_{tf}.csv", index=False)
        summaries.append(summ)

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(OUT_DIR / "fractals_summary.csv", index=False)
    print()
    print(summary_df.to_string(index=False))

    print("\n" + "=" * 80)
    print("ЭТАП 4b — Fractals context (1h, 4h, 1d)")
    print("=" * 80)
    for tf in TFS_CONTEXT:
        df_z, _ = analyze_tf(tf, with_context=True)
        if df_z.empty:
            continue
        df_z.to_csv(OUT_DIR / f"fractals_context_{tf}.csv", index=False)
        n_total = len(df_z)
        n_t = (df_z["touched"] == True).sum()
        print(f"\n############ TF = {tf}  ({n_total} fractals, {n_t} touched) ############")
        report_segment(df_z, "fractal_type", "FH vs FL")
        report_segment(df_z, "trend_label", "Trend slope")
        report_segment(df_z, "pos_vs_ema200", "Pos vs EMA200")
        report_segment(df_z, "dir_vs_htf", "Direction vs HTF trend")
        report_segment(df_z, "cluster_label", "Cluster vs Lone")
        report_segment(df_z, "touch_kind", "Touch kind")


if __name__ == "__main__":
    main()
