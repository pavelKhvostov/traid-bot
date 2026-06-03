"""Money Hands agent (placeholder).

После PC2 screening + full WF top-20 — встроить лучший конфиг MHParams и
multi-TF state-machine (bw2/MF/RSI/STC across 7-8 TFs).

См. memory pivot-money-hands-long-cascade-rule (LONG-cascade 62.9% accuracy).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from expert_asvk.agents.base import AgentOpinion


@dataclass
class MoneyHandsAgent:
    name: str = "money_hands"

    def opinion(self, asset: str = "BTC", cut_off_utc: pd.Timestamp | None = None) -> AgentOpinion:
        raise NotImplementedError(
            "money_hands_agent: ожидает результаты screening PC2 + full WF top-20"
        )
