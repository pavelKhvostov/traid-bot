"""Base contract for Expert ASVK agents.

Every agent (zones, money_hands, rsi, trendline, vic, vwaps, ...) returns
an AgentOpinion. Orchestrator aggregates these into a final verdict.

Agents are INDEPENDENT: they do not call each other and do not see other
agents' opinions. Fusion happens only at the orchestrator level.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import pandas as pd


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class Level:
    """Цена-уровень с вероятностью/контекстом (target / support / resistance)."""
    price: float
    role: str               # "target" / "support" / "resistance" / "invalidation" / "magnet"
    probability: float | None = None     # P that level is reached / holds, [0,1]
    distance_pct: float | None = None    # signed distance from current price (%)
    note: str = ""


@dataclass
class AgentOpinion:
    """Унифицированный output одного агента.

    Все агенты возвращают эту структуру, что бы они ни анализировали.
    """
    agent_name: str                       # "zones" / "money_hands" / "rsi" / ...
    asset: str                            # "BTC" / "ETH" / ...
    cut_off_utc: pd.Timestamp             # cut-off момент анализа
    price_now: float                      # цена в момент cut_off

    direction: Direction                  # главный bias агента
    conviction: float                     # 0.0 - 1.0; насколько агент уверен
    timeframe: str                        # фокус-ТФ агента (e.g. "1h" / "1d" / "multi")

    levels: list[Level] = field(default_factory=list)
    invalidation: Level | None = None     # одна явная invalidation если есть

    reasoning: str = ""                   # short text (1-3 предложения)
    raw: dict = field(default_factory=dict)  # raw agent-specific payload (для отладки/orchestrator)

    def cut_off_msk(self) -> pd.Timestamp:
        return self.cut_off_utc + pd.Timedelta(hours=3)


class Agent(Protocol):
    """Контракт для агента. Агент — callable: `agent.opinion(...) -> AgentOpinion`."""
    name: str

    def opinion(self, asset: str = "BTC", cut_off_utc: pd.Timestamp | None = None) -> AgentOpinion:
        ...
