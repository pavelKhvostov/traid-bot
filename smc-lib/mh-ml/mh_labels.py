"""Multi-horizon labels для MH ML.

Для каждой 15m timestamp вычисляем forward % move на 6 горизонтах:
  pct_1h, pct_4h, pct_12h, pct_24h, pct_48h, pct_96h

Также возвращаем sign-classification labels (UP=1, DOWN=0).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SMC_LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))
from resample import resample_one  # noqa: E402


HORIZONS_HOURS: tuple[int, ...] = (1, 4, 12, 24, 48, 96)


def build_labels(
    df_1m: pd.DataFrame,
    target_freq: str = "15m",
    horizons_hours: tuple[int, ...] = HORIZONS_HOURS,
) -> pd.DataFrame:
    """Build forward-move labels индексированные по 15m timestamps.

    Returns DataFrame с колонками:
        pct_{h}h    — actual forward % return от close(t) до close(t+h)
        sign_{h}h   — 1 если pct>0 else 0
        magnitude_{h}h — |pct|, для magnitude-bucket classification

    Если timestamp t+h выходит за конец данных — соответствующая ячейка NaN.
    """
    end_ts = df_1m.index[-1] + pd.Timedelta(minutes=1)
    grid_df = resample_one(df_1m, target_freq, end_ts)
    closes = grid_df["close"]
    bars_per_hour = 4  # 60min / 15min = 4

    out = pd.DataFrame(index=closes.index)
    for h in horizons_hours:
        shift = h * bars_per_hour
        future = closes.shift(-shift)
        pct = (future / closes - 1.0) * 100.0    # в процентах
        out[f"pct_{h}h"] = pct
        out[f"sign_{h}h"] = (pct > 0).astype("int8")
        out[f"magnitude_{h}h"] = pct.abs()
    return out
