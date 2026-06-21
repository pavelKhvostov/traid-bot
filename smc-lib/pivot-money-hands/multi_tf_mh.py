"""
Multi-TF снимок MoneyHands.

Берём 1m OHLCV → ресемплим в N выбранных TF → на каждом TF считаем
MoneyHands (bw2, color, MF, rsi_mod, stc_rsi_mod) → возвращаем
состояние на последнем ЗАКРЫТОМ баре каждого TF.

Используется наш resample.py (strict cut-off, Monday-anchored W) и
индикатор из smc-lib/indicators/money_hands_asvk.py.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

# Подключаем smc-lib и prediction-algo
SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from indicators.money_hands_asvk import money_hands  # noqa: E402
from resample import resample_many  # noqa: E402

# Канонический набор для исследования pivot'ов через MoneyHands
PIVOT_TFS: tuple[str, ...] = ("3d", "1d", "12h", "8h", "4h", "2h", "1h")

MH_FIELDS: tuple[str, ...] = ("bw2", "color", "mf", "rsi_mod", "stc_rsi_mod")


@dataclass(frozen=True)
class MHState:
    """Состояние MoneyHands на одном баре одного TF."""
    tf: str
    bar_open_ts: pd.Timestamp     # время открытия последнего закрытого бара
    bw2: float | None
    color: str | None              # 'green' / 'white_weak_bull' / 'red' / 'white_weak_bear' / 'neutral' / None
    mf: float | None
    rsi_mod: float | None
    stc_rsi_mod: float | None

    def to_flat_dict(self) -> dict:
        """Расплющить в dict с префиксом tf: {f"mh_{tf}_{field}": value}."""
        out = {f"mh_{self.tf}_open_ts": self.bar_open_ts}
        for fld in MH_FIELDS:
            out[f"mh_{self.tf}_{fld}"] = getattr(self, fld)
        return out


def _mh_state_for_tf(df_tf: pd.DataFrame, tf: str) -> MHState | None:
    """Посчитать MoneyHands на df_tf и вернуть состояние ПОСЛЕДНЕГО бара."""
    if df_tf.empty:
        return None
    bars = list(zip(
        df_tf["open"].astype(float),
        df_tf["high"].astype(float),
        df_tf["low"].astype(float),
        df_tf["close"].astype(float),
        df_tf["volume"].astype(float),
    ))
    res = money_hands(bars)
    if not res["bw2"]:
        return None
    i = len(bars) - 1
    return MHState(
        tf=tf,
        bar_open_ts=df_tf.index[i],
        bw2=res["bw2"][i],
        color=res["color"][i],
        mf=res["mf"][i],
        rsi_mod=res["rsi_mod"][i],
        stc_rsi_mod=res["stc_rsi_mod"][i],
    )


def mh_snapshot(
    df_1m: pd.DataFrame,
    cut_off_ts: pd.Timestamp,
    tfs: Iterable[str] = PIVOT_TFS,
) -> dict[str, MHState | None]:
    """
    Снять multi-TF MoneyHands на cut_off_ts.

    Returns: {tf → MHState | None}. None если на этом TF недостаточно баров
    (нужно минимум 60 для MF SMA60 + 4 для bw2 SMA4 + 14 для bw2_sma14 + 81 для stc).
    """
    resampled = resample_many(df_1m, list(tfs), cut_off_ts)
    out: dict[str, MHState | None] = {}
    for tf, df_tf in resampled.items():
        out[tf] = _mh_state_for_tf(df_tf, tf)
    return out


def mh_snapshot_flat(
    df_1m: pd.DataFrame,
    cut_off_ts: pd.Timestamp,
    tfs: Iterable[str] = PIVOT_TFS,
) -> dict:
    """Плоский dict со всеми фичами под префиксами mh_<tf>_<field>."""
    snap = mh_snapshot(df_1m, cut_off_ts, tfs)
    out: dict = {"cut_off_ts": cut_off_ts}
    for tf, state in snap.items():
        if state is None:
            for fld in MH_FIELDS:
                out[f"mh_{tf}_{fld}"] = None
            out[f"mh_{tf}_open_ts"] = None
        else:
            out.update(state.to_flat_dict())
    return out
