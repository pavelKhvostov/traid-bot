"""Этап 3: глубокое исследование зон RDRB на BTCUSDT.

Canon-определение ([vault/knowledge/smc/что такое rdrb.md]):

  LONG: m.close > a.high AND c.low < a.high AND c.close > a.high
    Zone bottom = max(c.low, max(a.open, a.close))
    Zone top    = min(a.high, min(c.open, c.close))

  SHORT (зеркально вокруг a.low):
    m.close < a.low AND c.high > a.low AND c.close < a.low
    Zone bottom = max(a.low, max(c.open, c.close))
    Zone top    = min(c.high, min(a.open, a.close))

Это «ложный пробой с возвратом»: anchor задаёт уровень, mid пробивает,
trigger делает retest и закрывается обратно. Зона = пересечение фитиля
trigger и тел anchor (с обрезанием).

Структура анализа:
  A. Базовые: count, RDRB/day, размер %, LONG/SHORT
  B. Жизнь зоны: % touched, median bars to touch
  C. Тип взаимодействия
  D. Эффективность: bounce_1x/2x/3x, max_R, sl_first
  E. Context: size_vs_ATR, vs_EMA200, cluster

TFs: 15m, 20m, 1h, 2h, 4h, 6h, 12h, 1d.
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

from dataclasses import dataclass
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


@dataclass
class RDRBZone:
    direction: str
    bottom: float
    top: float
    anchor_idx: int
    trigger_idx: int


def detect_rdrb(df: pd.DataFrame, idx: int) -> RDRBZone | None:
    """Тройка (a=i-2, m=i-1, c=i) — RDRB?"""
    if idx < 2:
        return None
    a = df.iloc[idx - 2]
    m = df.iloc[idx - 1]
    c = df.iloc[idx]

    a_open = float(a["open"])
    a_close = float(a["close"])
    a_high = float(a["high"])
    a_low = float(a["low"])
    m_close = float(m["close"])
    c_open = float(c["open"])
    c_high = float(c["high"])
    c_low = float(c["low"])
    c_close = float(c["close"])

    if m_close > a_high and c_low < a_high and c_close > a_high:
        zb = max(c_low, max(a_open, a_close))
        zt = min(a_high, min(c_open, c_close))
        if zt <= zb:
            return None
        return RDRBZone("LONG", zb, zt, idx - 2, idx)
    if m_close < a_low and c_high > a_low and c_close < a_low:
        zb = max(a_low, max(c_open, c_close))
        zt = min(c_high, min(a_open, a_close))
        if zt <= zb:
            return None
        return RDRBZone("SHORT", zb, zt, idx - 2, idx)
    return None


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


def detect_all_rdrbs(df: pd.DataFrame) -> list[dict]:
    rdrbs = []
    for idx in range(2, len(df)):
        z = detect_rdrb(df, idx)
        if z is None:
            continue
        a = df.iloc[idx - 2]
        m = df.iloc[idx - 1]
        c = df.iloc[idx]
        mid_p = (z.bottom + z.top) / 2
        size_abs = z.top - z.bottom
        size_pct = size_abs / mid_p * 100 if mid_p > 0 else np.nan
        rdrbs.append({
            "direction": z.direction,
            "anchor_time": df.index[idx - 2],
            "trigger_time": df.index[idx],
            "cur_idx": idx,  # триггер
            "bottom": z.bottom,
            "top": z.top,
            "size_abs": size_abs,
            "size_pct": size_pct,
            "anchor_high": float(a["high"]),
            "anchor_low": float(a["low"]),
            "trigger_open": float(c["open"]),
            "trigger_close": float(c["close"]),
        })
    return rdrbs


def analyze_lifecycle(z_dict: dict, df: pd.DataFrame, lookback: int) -> dict:
    direction = z_dict["direction"]
    bottom = z_dict["bottom"]
    top = z_dict["top"]
    size = z_dict["size_abs"]
    cur_idx = z_dict["cur_idx"]
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


def analyze_tf(tf: str, with_context: bool):
    print(f"\n[{tf}] loading + computing")
    df = load_df_with_compose(tf)
    if df.empty:
        return pd.DataFrame(), {}
    df = df.copy()
    if with_context:
        df["atr14"] = compute_atr(df, 14)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    print(f"  bars: {len(df)}")

    rdrbs = detect_all_rdrbs(df)
    print(f"  found {len(rdrbs)} RDRB zones")

    last_long_idx = -1000
    last_short_idx = -1000
    rows = []
    for r in rdrbs:
        outcome = analyze_lifecycle(r, df, LOOKBACK_BARS)
        row = {**r, **outcome}
        if with_context:
            idx = r["cur_idx"]
            atr = float(df["atr14"].iloc[idx]) if not pd.isna(df["atr14"].iloc[idx]) else np.nan
            em = float(df["ema200"].iloc[idx]) if not pd.isna(df["ema200"].iloc[idx]) else np.nan
            cur_close = r["trigger_close"]
            pos_vs_ema200 = "above" if not pd.isna(em) and cur_close > em else "below" if not pd.isna(em) and cur_close < em else "na"
            size_atr = r["size_abs"] / atr if atr and atr > 0 else np.nan
            if pd.isna(size_atr):
                size_label = "na"
            elif size_atr < 0.3:
                size_label = "small"
            elif size_atr < 1.0:
                size_label = "medium"
            else:
                size_label = "large"

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

            if r["direction"] == "LONG" and pos_vs_ema200 == "above":
                dir_vs_htf = "pro_trend"
            elif r["direction"] == "SHORT" and pos_vs_ema200 == "below":
                dir_vs_htf = "pro_trend"
            elif pos_vs_ema200 == "na":
                dir_vs_htf = "na"
            else:
                dir_vs_htf = "counter_trend"

            if r["direction"] == "LONG":
                bs = idx - last_long_idx
                last_long_idx = idx
            else:
                bs = idx - last_short_idx
                last_short_idx = idx
            cluster_label = "cluster" if bs < 5 else "medium" if bs < 20 else "lone"

            row.update({
                "atr14": atr, "ema200": em, "pos_vs_ema200": pos_vs_ema200,
                "size_atr": size_atr, "size_label": size_label,
                "trend_slope": slope_pct, "trend_label": trend_label,
                "dir_vs_htf": dir_vs_htf,
                "bars_since_same_dir": bs, "cluster_label": cluster_label,
            })
        rows.append(row)
    df_z = pd.DataFrame(rows)
    df_z["tf"] = tf

    n_total = len(df_z)
    n_long = int((df_z["direction"] == "LONG").sum())
    n_short = int((df_z["direction"] == "SHORT").sum())
    days_span = (df.index[-1] - df.index[0]).total_seconds() / 86400
    rdrbs_per_day = n_total / days_span if days_span > 0 else 0
    touched = df_z[df_z["touched"] == True]

    summary = {
        "tf": tf,
        "bars": len(df),
        "days": round(days_span, 1),
        "n_zones": n_total,
        "zones_per_day": round(rdrbs_per_day, 4),
        "n_long": n_long,
        "n_short": n_short,
        "median_size_pct": round(df_z["size_pct"].median(), 4) if n_total else None,
        "n_touched": len(touched),
        "pct_touched": round(len(touched) / n_total * 100, 1) if n_total else 0,
        "median_bars_to_touch": float(touched["bars_to_touch"].median()) if not touched.empty else None,
        "pct_wick": round((touched["touch_kind"] == "wick").mean() * 100, 1) if not touched.empty else 0,
        "pct_close_inside": round((touched["touch_kind"] == "close_inside").mean() * 100, 1) if not touched.empty else 0,
        "pct_pierce": round((touched["touch_kind"] == "pierce").mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_1x": round(touched["bounce_1x"].mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_2x": round(touched["bounce_2x"].mean() * 100, 1) if not touched.empty else 0,
        "pct_bounce_3x": round(touched["bounce_3x"].mean() * 100, 1) if not touched.empty else 0,
        "median_max_R": round(touched["max_bounce_R"].median(), 3) if not touched.empty else None,
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
        pct_pierce=("touch_kind", lambda s: round((s == "pierce").mean() * 100, 1)),
    ).round(2)
    g = g.sort_values("median_R", ascending=False)
    print(f"\n--- {label} ---")
    print(g.to_string())


def main():
    print("=" * 80)
    print("ЭТАП 3 — RDRB: базовый анализ всех TF")
    print("=" * 80)
    summaries = []
    for tf in TFS_ALL:
        df_z, summ = analyze_tf(tf, with_context=False)
        if df_z.empty:
            continue
        df_z.to_csv(OUT_DIR / f"rdrb_{tf}.csv", index=False)
        summaries.append(summ)

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(OUT_DIR / "rdrb_summary.csv", index=False)
    print()
    print(summary_df.to_string(index=False))

    print("\n" + "=" * 80)
    print("ЭТАП 3b — RDRB context (1h, 4h, 1d)")
    print("=" * 80)
    for tf in TFS_CONTEXT:
        df_z, _ = analyze_tf(tf, with_context=True)
        if df_z.empty:
            continue
        df_z.to_csv(OUT_DIR / f"rdrb_context_{tf}.csv", index=False)
        n_total = len(df_z)
        n_t = (df_z["touched"] == True).sum()
        print(f"\n############ TF = {tf}  ({n_total} zones, {n_t} touched) ############")
        report_segment(df_z, "size_label", "RDRB size vs ATR(14)")
        report_segment(df_z, "trend_label", "Trend slope (20 bars)")
        report_segment(df_z, "pos_vs_ema200", "Position vs EMA200")
        report_segment(df_z, "dir_vs_htf", "Direction vs HTF trend")
        report_segment(df_z, "cluster_label", "Cluster vs Lone")
        report_segment(df_z, "touch_kind", "Touch kind (kontrol)")


if __name__ == "__main__":
    main()
