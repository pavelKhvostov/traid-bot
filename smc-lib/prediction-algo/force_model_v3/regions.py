"""
Force-search regions per 12h candle.

Канон:
  prior BULL (close > open) → baseline_short = prior.HIGH
  prior BEAR (close < open) → baseline_short = prior.LOW
  (определяется из 12h prior candle)

SHORT region [prior.HIGH .. current.HIGH] — если current.HIGH > prior.HIGH
LONG region  [current.LOW .. prior.LOW]  — если current.LOW < prior.LOW

См. [[feedback-candle-zone-liquidity-methodology]].
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CandleRegions:
    candle_open_ts: pd.Timestamp
    candle_open: float
    candle_high: float
    candle_low: float
    candle_close: float
    prior_high: float
    prior_low: float
    prior_dir: str  # "bull" | "bear"
    short_lo: float | None  # = prior.high if region exists, else None
    short_hi: float | None  # = candle.high if region exists, else None
    long_lo: float | None   # = candle.low if region exists, else None
    long_hi: float | None   # = prior.low if region exists, else None

    @property
    def has_short(self) -> bool:
        return self.short_lo is not None

    @property
    def has_long(self) -> bool:
        return self.long_lo is not None


def compute_regions(df_12h: pd.DataFrame, candle_open_ts: pd.Timestamp) -> CandleRegions | None:
    """Compute force-search regions for given 12h candle. None если prior отсутствует."""
    if candle_open_ts not in df_12h.index:
        return None
    prior_mask = df_12h.index < candle_open_ts
    if not prior_mask.any():
        return None
    prior_ts = df_12h.index[prior_mask][-1]
    prior = df_12h.loc[prior_ts]
    cur = df_12h.loc[candle_open_ts]

    pH = float(prior["high"]); pL = float(prior["low"])
    cH = float(cur["high"]);   cL = float(cur["low"])
    pO = float(prior["open"]); pC = float(prior["close"])
    prior_dir = "bull" if pC > pO else "bear"

    short_lo = pH if cH > pH else None
    short_hi = cH if cH > pH else None
    long_lo = cL if cL < pL else None
    long_hi = pL if cL < pL else None

    return CandleRegions(
        candle_open_ts=candle_open_ts,
        candle_open=float(cur["open"]),
        candle_high=cH, candle_low=cL,
        candle_close=float(cur["close"]),
        prior_high=pH, prior_low=pL, prior_dir=prior_dir,
        short_lo=short_lo, short_hi=short_hi,
        long_lo=long_lo, long_hi=long_hi,
    )
