"""VWAPs agent (placeholder).

Anchored VWAP от фракталов (N_FRACTAL=2). Канон-helper:
indicators/vwap_anchored.py + plot_fhfl_vwap_4h* как reference.

См. memory feedback-anchored-vwap-from-fractals.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from expert_asvk.agents.base import AgentOpinion


@dataclass
class VWAPsAgent:
    name: str = "vwaps"

    def opinion(self, asset: str = "BTC", cut_off_utc: pd.Timestamp | None = None) -> AgentOpinion:
        raise NotImplementedError(
            "vwaps_agent: реализовать через vwap_anchored.py + FH/FL anchors"
        )
