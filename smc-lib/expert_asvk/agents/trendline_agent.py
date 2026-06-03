"""TrendLine agent (placeholder).

Канон: HMA 78 + HMA 200 на 12h + D, LIVE values, Правило 7.
Helpers: indicators/trend_line_asvk.py trend_line_hma_78 / trend_line_hma_200.

См. memory feedback-trendline-hma-78-200-default.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from expert_asvk.agents.base import AgentOpinion


@dataclass
class TrendLineAgent:
    name: str = "trendline"

    def opinion(self, asset: str = "BTC", cut_off_utc: pd.Timestamp | None = None) -> AgentOpinion:
        raise NotImplementedError(
            "trendline_agent: реализовать через trend_line_hma_78/200 на 12h+D + Правило 7"
        )
