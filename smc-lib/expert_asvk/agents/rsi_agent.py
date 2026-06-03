"""RSI agent (placeholder).

Standard RSI(14) на нескольких ТФ + OB/OS/divergence detection.
Канон-параметры будут уточнены при реализации.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from expert_asvk.agents.base import AgentOpinion


@dataclass
class RSIAgent:
    name: str = "rsi"

    def opinion(self, asset: str = "BTC", cut_off_utc: pd.Timestamp | None = None) -> AgentOpinion:
        raise NotImplementedError(
            "rsi_agent: реализовать через RSI(14) multi-TF + divergence"
        )
