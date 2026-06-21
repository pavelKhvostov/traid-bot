"""
Cascade / time-resonance features.

Идея: bw2 на каждом TF пересекает 0 → начало новой фазы (волна).
Cascade — это упорядоченное во времени переключение многих TF в одну
сторону. Если HTF (3d/1d) переключились первыми, потом 12h/8h, потом
4h/2h/1h — это «накопительный» резонанс.

Здесь вычисляем для каждого 1h bar следующие фичи:
  - {tf}_bars_since_bull_cross: бар на TF где bw2 в последний раз
    пересёк 0 снизу вверх (бычий cross). Перевод в часы 1h.
  - {tf}_bars_since_bear_cross: то же для медвежьего cross.
  - cascade_bull_freshness: min из {bull_age} по 7 TF.
    Низкое значение → один из TF только что флипнул bull.
  - cascade_bull_completeness: max{bull_age}.
    Низкое → ВСЕ TF недавно флипнули bull (тесный кластер).
  - cascade_bull_spread: max - min (разброс времени).
    Низкий spread + низкий max → синхронный cascade.
  - cascade_bear_* — то же зеркально.

Для практики: LONG-contrarian при bear-cascade с низким max (свежий накопленный
медвежий резонанс) должен давать сильнее edge чем без учёта свежести.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from indicators.money_hands_asvk import money_hands  # noqa: E402
from resample import resample_many  # noqa: E402

from multi_tf_mh import PIVOT_TFS  # noqa: E402

TF_HOURS = {"3d": 72, "1d": 24, "12h": 12, "8h": 8, "4h": 4, "2h": 2, "1h": 1}


def _zero_crossings(bw2: list[float | None]) -> list[tuple[int, str]]:
    """Найти позиции где bw2 пересекает 0. Возвращает (idx, direction)."""
    out = []
    prev = None
    for i, v in enumerate(bw2):
        if v is None:
            prev = None
            continue
        if prev is not None:
            if prev <= 0 and v > 0:
                out.append((i, "bull"))
            elif prev >= 0 and v < 0:
                out.append((i, "bear"))
        prev = v
    return out


def _compute_cross_age_series(
    df_tf: pd.DataFrame, bw2: list[float | None]
) -> pd.DataFrame:
    """Для каждого бара TF вычислить age (в БАРАХ TF) последнего bull/bear cross."""
    crosses = _zero_crossings(bw2)
    bull_age = []
    bear_age = []
    last_bull_idx = None
    last_bear_idx = None
    cross_by_idx: dict[int, str] = {idx: d for idx, d in crosses}
    for i in range(len(df_tf)):
        if i in cross_by_idx:
            if cross_by_idx[i] == "bull":
                last_bull_idx = i
            else:
                last_bear_idx = i
        bull_age.append(i - last_bull_idx if last_bull_idx is not None else None)
        bear_age.append(i - last_bear_idx if last_bear_idx is not None else None)
    return pd.DataFrame({
        "bull_age_bars": bull_age,
        "bear_age_bars": bear_age,
    }, index=df_tf.index)


def precompute_cross_ages(
    df_1m: pd.DataFrame,
    tfs: tuple[str, ...] = PIVOT_TFS,
    end_ts: pd.Timestamp | None = None,
) -> dict[str, pd.DataFrame]:
    """Для каждого TF: посчитать MH, найти crosses, вернуть age-series."""
    if end_ts is None:
        end_ts = df_1m.index[-1] + pd.Timedelta(minutes=1)
    resampled = resample_many(df_1m, list(tfs), end_ts)
    out: dict[str, pd.DataFrame] = {}
    for tf, df_tf in resampled.items():
        if df_tf.empty:
            out[tf] = df_tf.iloc[0:0]
            continue
        bars = list(zip(
            df_tf["open"].astype(float),
            df_tf["high"].astype(float),
            df_tf["low"].astype(float),
            df_tf["close"].astype(float),
            df_tf["volume"].astype(float),
        ))
        res = money_hands(bars)
        out[tf] = _compute_cross_age_series(df_tf, res["bw2"])
    return out


def add_cascade_features(
    ds: pd.DataFrame,
    cross_ages_by_tf: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Добавить к ds:
      mh_<tf>_bull_age_h, mh_<tf>_bear_age_h — age в ЧАСАХ (BAR * TF_HOURS)
      cascade_bull_freshness, cascade_bull_completeness, cascade_bull_spread
      cascade_bear_freshness, cascade_bear_completeness, cascade_bear_spread
    Используем для lookup тот же подход что в dataset.py (bar_open ≤ ts).
    """
    out = ds.copy()
    out["bar_ts"] = pd.to_datetime(out["bar_ts"], utc=True)
    cut_offs = out["bar_ts"] + pd.Timedelta(hours=1)  # закрытие 1h bar

    age_data: dict[str, dict] = {}
    for tf in PIVOT_TFS:
        ah = cross_ages_by_tf.get(tf)
        if ah is None or ah.empty:
            age_data[tf] = {"bull": [None]*len(cut_offs), "bear": [None]*len(cut_offs)}
            continue
        tf_td = pd.Timedelta(hours=TF_HOURS[tf])
        bulls = []; bears = []
        # Pre-sort: ah.index is sorted ascending
        idx_arr = ah.index.values
        bull_vals = ah["bull_age_bars"].to_numpy()
        bear_vals = ah["bear_age_bars"].to_numpy()
        for ts in cut_offs:
            mask_close = (ah.index + tf_td) <= ts
            if not mask_close.any():
                bulls.append(None); bears.append(None); continue
            mask_arr = np.asarray(mask_close)
            last_pos = mask_arr.nonzero()[0][-1]
            bvals = bull_vals[last_pos]
            evals = bear_vals[last_pos]
            bulls.append(bvals * TF_HOURS[tf] if bvals is not None and not pd.isna(bvals) else None)
            bears.append(evals * TF_HOURS[tf] if evals is not None and not pd.isna(evals) else None)
        age_data[tf] = {"bull": bulls, "bear": bears}
        out[f"mh_{tf}_bull_age_h"] = bulls
        out[f"mh_{tf}_bear_age_h"] = bears

    # cascade aggregates
    bull_cols = [f"mh_{tf}_bull_age_h" for tf in PIVOT_TFS]
    bear_cols = [f"mh_{tf}_bear_age_h" for tf in PIVOT_TFS]
    bull_df = out[bull_cols].apply(pd.to_numeric, errors="coerce")
    bear_df = out[bear_cols].apply(pd.to_numeric, errors="coerce")

    out["cascade_bull_freshness"] = bull_df.min(axis=1)        # ближайший флип bull
    out["cascade_bull_completeness"] = bull_df.max(axis=1)     # старейший bull (= когда последний из TF переключился bull)
    out["cascade_bull_spread"] = bull_df.max(axis=1) - bull_df.min(axis=1)
    out["cascade_bull_count_valid"] = bull_df.notna().sum(axis=1)

    out["cascade_bear_freshness"] = bear_df.min(axis=1)
    out["cascade_bear_completeness"] = bear_df.max(axis=1)
    out["cascade_bear_spread"] = bear_df.max(axis=1) - bear_df.min(axis=1)
    out["cascade_bear_count_valid"] = bear_df.notna().sum(axis=1)

    return out
