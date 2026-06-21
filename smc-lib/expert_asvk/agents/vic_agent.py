"""VIC agent (placeholder).

VIC = maxV / sweep_maxV — индикатор «силы фрактала». Канон в
indicators/vic_asvk.py. Связан с 12h fractal prediction strategy
(см. memory 12h-fractal-prediction-final-strategy).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from expert_asvk.agents.base import AgentOpinion


@dataclass
class VICAgent:
    name: str = "vic"

    def opinion(self, asset: str = "BTC", cut_off_utc: pd.Timestamp | None = None) -> AgentOpinion:
        raise NotImplementedError(
            "vic_agent: реализовать через vic_asvk.py + sweep_maxV анализ"
        )
