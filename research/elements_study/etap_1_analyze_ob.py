"""Этап 1: детальный анализ зон Order Block (OB) на BTCUSDT по всем TF.

Использует canon-определение OB из vault/knowledge/smc/универсальные определения
OB и FVG.md (импорт detect_ob_pair из strategies/strategy_1_1_1.py).

Для каждого TF:
  A. Базовые: count, count/day, размер %, LONG/SHORT баланс
  B. Жизнь зоны: время до first-touch, % never-touched
  C. Взаимодействие: wick-only / close-inside / pierce-through
  D. Эффективность mean-reversion: отскок до 1x/2x/3x размера зоны до
     противоположного пробоя

Параметры:
  LOOKBACK_BARS — сколько баров вперёд смотрим для оценки отскока (50)
  TF list — все нативные + 20m composed

Output:
  research/elements_study/output/ob_<tf>.csv — per-OB raw данные
  research/elements_study/output/ob_summary.csv — агрегаты по TF
  research/elements_study/output/ob_report.md — текстовый отчёт
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
from strategies.strategy_1_1_1 import detect_ob_pair

SYMBOL = "BTCUSDT"
TFS_NATIVE = ["15m", "1h", "2h", "4h", "6h", "12h", "1d"]
TF_20M_FROM_1M = "20m"
LOOKBACK_BARS = 50         # сколько баров вперёд смотрим для оценки отскока
START_DATE = "2020-01-01"

OUT_DIR = Path("research/elements_study/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def detect_all_obs(df: pd.DataFrame) -> list[dict]:
    """Все OB на df (попарно (i-1, i))."""
    obs = []
    for idx in range(1, len(df)):
        ob = detect_ob_pair(df, idx)
        if ob is None:
            continue
        prev = df.iloc[idx - 1]
        cur = df.iloc[idx]
        mid_price = (ob.bottom + ob.top) / 2
        size_abs = ob.top - ob.bottom
        size_pct = size_abs / mid_price * 100 if mid_price > 0 else np.nan
        obs.append({
            "direction": ob.direction,
            "prev_time": ob.prev_time,
            "cur_time": ob.cur_time,
            "cur_idx": idx,  # позиция cur в df
            "bottom": ob.bottom,
            "top": ob.top,
            "size_abs": size_abs,
            "size_pct": size_pct,
            "prev_open": float(prev["open"]),
            "prev_close": float(prev["close"]),
            "cur_open": float(cur["open"]),
            "cur_close": float(cur["close"]),
        })
    return obs


def analyze_ob_lifecycle(ob: dict, df: pd.DataFrame, lookback: int) -> dict:
    """Для одного OB найти first-touch и оценить отскок.

    Search window: [cur_idx + 1, cur_idx + lookback] (lookback ≈ N баров).
    """
    direction = ob["direction"]
    bottom = ob["bottom"]
    top = ob["top"]
    size = ob["size_abs"]
    cur_idx = ob["cur_idx"]
    end_idx = min(cur_idx + lookback, len(df) - 1)

    if cur_idx + 1 > end_idx:
        return {
            "touched": False, "touch_kind": "no_data", "bars_to_touch": np.nan,
            "max_bounce_R": np.nan, "sl_hit_before_bounce_1x": np.nan,
            "bounce_1x": False, "bounce_2x": False, "bounce_3x": False,
        }

    touch_idx = None
    touch_kind = None  # wick / close_inside / pierce / no_touch
    for j in range(cur_idx + 1, end_idx + 1):
        row = df.iloc[j]
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])

        if direction == "LONG":
            # Цена пришла к зоне сверху: low(j) <= top
            if l <= top:
                # Тип касания
                if c < bottom:
                    touch_kind = "pierce"  # пробила насквозь
                elif bottom <= c <= top:
                    touch_kind = "close_inside"
                else:
                    touch_kind = "wick"
                touch_idx = j
                break
        else:  # SHORT
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
        return {
            "touched": False, "touch_kind": "never", "bars_to_touch": np.nan,
            "max_bounce_R": np.nan, "sl_hit_before_bounce_1x": np.nan,
            "bounce_1x": False, "bounce_2x": False, "bounce_3x": False,
        }

    # Эффективность: считаем максимальное движение от entry в нужную сторону
    # Entry conventions:
    #   LONG: entry = top (цена пришла сверху, "first touch" = top)
    #   SHORT: entry = bottom
    # SL: противоположная граница (LONG: bottom; SHORT: top)
    # bounce_R = max profitable excursion / size
    entry = top if direction == "LONG" else bottom
    sl = bottom if direction == "LONG" else top

    # После touch_idx — смотрим bars [touch_idx, touch_idx + lookback)
    bounce_end = min(touch_idx + lookback, len(df))
    sub = df.iloc[touch_idx: bounce_end]

    # Идём посимвольно: на каждой свече проверяем,
    # достигнут ли bounce X (1x, 2x, 3x) ДО pierce (SL hit)
    sl_hit_before_bounce_1x = False
    bounce_1x = False
    bounce_2x = False
    bounce_3x = False
    max_excursion = 0.0
    for _, r in sub.iterrows():
        h = float(r["high"])
        l = float(r["low"])
        if direction == "LONG":
            # Профит = high - entry
            excursion = h - entry
            adverse = entry - l
            # SL: low <= sl (т.е. цена ушла под нижний край зоны)
            if l <= sl and not bounce_1x:
                sl_hit_before_bounce_1x = True
                # break — для bounce_X считаем исчерпанным
                # но max_excursion уже зафиксировали, не break
            if excursion / size >= 1 and not bounce_1x:
                bounce_1x = True
            if excursion / size >= 2 and not bounce_2x:
                bounce_2x = True
            if excursion / size >= 3 and not bounce_3x:
                bounce_3x = True
            if excursion > max_excursion:
                max_excursion = excursion
        else:  # SHORT
            excursion = entry - l
            adverse = h - entry
            if h >= sl and not bounce_1x:
                sl_hit_before_bounce_1x = True
            if excursion / size >= 1 and not bounce_1x:
                bounce_1x = True
            if excursion / size >= 2 and not bounce_2x:
                bounce_2x = True
            if excursion / size >= 3 and not bounce_3x:
                bounce_3x = True
            if excursion > max_excursion:
                max_excursion = excursion

    max_bounce_R = max_excursion / size if size > 0 else np.nan
    bars_to_touch = touch_idx - cur_idx

    return {
        "touched": True,
        "touch_kind": touch_kind,
        "bars_to_touch": bars_to_touch,
        "max_bounce_R": max_bounce_R,
        "sl_hit_before_bounce_1x": sl_hit_before_bounce_1x,
        "bounce_1x": bounce_1x,
        "bounce_2x": bounce_2x,
        "bounce_3x": bounce_3x,
    }


def load_df_with_compose(tf: str) -> pd.DataFrame:
    """Загрузить df для данного TF (с фильтром >= START_DATE)."""
    if tf == "20m":
        df_1m = load_df(SYMBOL, "1m")
        df = compose_from_base(df_1m, "20m")
    else:
        df = load_df(SYMBOL, tf)
    start = pd.Timestamp(START_DATE, tz="UTC")
    df = df[df.index >= start]
    return df


def analyze_tf(tf: str) -> tuple[pd.DataFrame, dict]:
    print(f"\n[{tf}] loading data...")
    df = load_df_with_compose(tf)
    if df.empty:
        print(f"  empty df")
        return pd.DataFrame(), {}
    print(f"  bars: {len(df)} from {df.index[0]} to {df.index[-1]}")

    print(f"  detecting OBs...")
    obs = detect_all_obs(df)
    print(f"  found {len(obs)} OBs")

    print(f"  analyzing lifecycle (lookback {LOOKBACK_BARS} bars)...")
    enriched = []
    for ob in obs:
        life = analyze_ob_lifecycle(ob, df, LOOKBACK_BARS)
        enriched.append({**ob, **life})
    df_obs = pd.DataFrame(enriched)
    df_obs["tf"] = tf

    # Aggregate
    n_total = len(df_obs)
    n_long = int((df_obs["direction"] == "LONG").sum())
    n_short = int((df_obs["direction"] == "SHORT").sum())
    days_span = (df.index[-1] - df.index[0]).total_seconds() / 86400
    obs_per_day = n_total / days_span if days_span > 0 else 0

    touched = df_obs[df_obs["touched"] == True]
    n_touched = len(touched)
    pct_touched = n_touched / n_total * 100 if n_total else 0

    # Touch kinds (среди тех, что коснулись)
    n_wick = int((touched["touch_kind"] == "wick").sum())
    n_close_inside = int((touched["touch_kind"] == "close_inside").sum())
    n_pierce = int((touched["touch_kind"] == "pierce").sum())

    # Bounce stats — только среди коснувшихся
    n_bounce_1x = int(touched["bounce_1x"].sum())
    n_bounce_2x = int(touched["bounce_2x"].sum())
    n_bounce_3x = int(touched["bounce_3x"].sum())
    n_sl_hit_first = int(touched["sl_hit_before_bounce_1x"].sum())

    median_size_pct = df_obs["size_pct"].median()
    median_bars_to_touch = touched["bars_to_touch"].median() if not touched.empty else np.nan
    median_max_bounce_R = touched["max_bounce_R"].median() if not touched.empty else np.nan

    summary = {
        "tf": tf,
        "bars": len(df),
        "days": round(days_span, 1),
        "n_obs": n_total,
        "obs_per_day": round(obs_per_day, 3),
        "n_long": n_long,
        "n_short": n_short,
        "median_size_pct": round(median_size_pct, 4) if not pd.isna(median_size_pct) else None,
        "n_touched": n_touched,
        "pct_touched": round(pct_touched, 1),
        "median_bars_to_touch": median_bars_to_touch if not pd.isna(median_bars_to_touch) else None,
        "n_wick": n_wick,
        "n_close_inside": n_close_inside,
        "n_pierce": n_pierce,
        "pct_wick": round(n_wick / n_touched * 100, 1) if n_touched else 0,
        "pct_close_inside": round(n_close_inside / n_touched * 100, 1) if n_touched else 0,
        "pct_pierce": round(n_pierce / n_touched * 100, 1) if n_touched else 0,
        "pct_bounce_1x": round(n_bounce_1x / n_touched * 100, 1) if n_touched else 0,
        "pct_bounce_2x": round(n_bounce_2x / n_touched * 100, 1) if n_touched else 0,
        "pct_bounce_3x": round(n_bounce_3x / n_touched * 100, 1) if n_touched else 0,
        "median_max_bounce_R": round(median_max_bounce_R, 3) if not pd.isna(median_max_bounce_R) else None,
        "pct_sl_hit_first": round(n_sl_hit_first / n_touched * 100, 1) if n_touched else 0,
    }
    return df_obs, summary


def main():
    all_summaries = []
    all_dfs = []
    for tf in [*TFS_NATIVE[:1], TF_20M_FROM_1M, *TFS_NATIVE[1:]]:
        # Порядок: 15m, 20m, 1h, 2h, 4h, 6h, 12h, 1d
        df_obs, summary = analyze_tf(tf)
        if df_obs.empty:
            continue
        df_obs.to_csv(OUT_DIR / f"ob_{tf}.csv", index=False)
        all_summaries.append(summary)
        all_dfs.append(df_obs)
        print(f"  saved ob_{tf}.csv ({len(df_obs)} rows)")

    if not all_summaries:
        print("[ERR] no data")
        return
    summary_df = pd.DataFrame(all_summaries)
    summary_df.to_csv(OUT_DIR / "ob_summary.csv", index=False)
    print(f"\n[OK] summary saved to {OUT_DIR / 'ob_summary.csv'}")
    print()
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
