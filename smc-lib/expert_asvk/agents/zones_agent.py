"""Zones agent — wraps prediction-algo/zones_opinion.py.

Returns AgentOpinion built from the canonical ZonesOpinion output.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SMC_LIB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from zones_opinion import run_zones_opinion  # noqa: E402

from expert_asvk.agents.base import AgentOpinion, Level, Direction


@dataclass
class ZonesAgent:
    name: str = "zones"

    def opinion(self, asset: str = "BTC", cut_off_utc: pd.Timestamp | None = None) -> AgentOpinion:
        if asset != "BTC":
            raise NotImplementedError("zones_opinion.py пока BTC-only")
        op = run_zones_opinion()

        if op.base_target is None:
            direction = Direction.NEUTRAL
            conviction = 0.0
            reasoning = "Нет значимых кластеров — нейтральная позиция."
        else:
            direction = Direction.BEARISH if op.base_target.side == "below" else Direction.BULLISH
            own = op.base_target.max_p_d
            other = op.counter_target.max_p_d if op.counter_target else 0.0
            conviction = max(0.0, min(1.0, own - other + 0.5))
            reasoning = (
                f"Базовая цель: [{op.base_target.lo:.0f}, {op.base_target.hi:.0f}] "
                f"P_D={own:.2f}, противоп. {other:.2f} (margin {own-other:+.2f}). "
                f"{len(op.base_target.zones)} зон ({'/'.join(op.base_target.types)})."
            )

        levels: list[Level] = []
        if op.base_target is not None:
            levels.append(Level(
                price=op.base_target.representative_level,
                role="target",
                probability=op.base_target.max_p_d,
                distance_pct=(-1 if op.base_target.side == "below" else 1) * op.base_target.distance_pct,
                note=f"first-target {op.base_target.side}",
            ))
        for c in op.chain_after_base:
            levels.append(Level(
                price=c.representative_level,
                role="magnet",
                probability=c.max_p_d,
                distance_pct=(-1 if c.side == "below" else 1) * c.distance_pct,
                note="chain after base",
            ))
        if op.counter_target is not None:
            levels.append(Level(
                price=op.counter_target.representative_level,
                role="resistance" if op.counter_target.side == "above" else "support",
                probability=op.counter_target.max_p_d,
                distance_pct=(-1 if op.counter_target.side == "below" else 1) * op.counter_target.distance_pct,
                note="counter-target / отскок",
            ))

        invalidation: Level | None = None
        if op.base_target is not None:
            other_side = op.clusters_above if op.base_target.side == "below" else op.clusters_below
            if other_side:
                first = other_side[0]
                invalidation = Level(
                    price=first.representative_level,
                    role="invalidation",
                    probability=first.max_p_d,
                    distance_pct=(-1 if first.side == "below" else 1) * first.distance_pct,
                    note=f"break {first.side} отменяет базовый",
                )

        return AgentOpinion(
            agent_name=self.name,
            asset=asset,
            cut_off_utc=op.cut_off_utc,
            price_now=op.price_now,
            direction=direction,
            conviction=conviction,
            timeframe="multi(1h/4h/12h/1d)",
            levels=levels,
            invalidation=invalidation,
            reasoning=reasoning,
            raw={"zones_opinion_text": op.text, "n_zones": op.n_zones},
        )


if __name__ == "__main__":
    ag = ZonesAgent()
    op = ag.opinion()
    print(f"[{op.agent_name}] {op.asset} {op.cut_off_msk().strftime('%d-%m-%Y %H:%M MSK')}")
    print(f"  price={op.price_now:,.0f}  dir={op.direction.value}  conviction={op.conviction:.2f}")
    print(f"  TF: {op.timeframe}")
    print(f"  reasoning: {op.reasoning}")
    if op.invalidation:
        print(f"  invalidation: {op.invalidation.price:.0f} ({op.invalidation.note})")
    for lv in op.levels:
        print(f"  {lv.role:11s} {lv.price:>8.0f}  P={lv.probability:.2f}  ({lv.distance_pct:+.2f}%, {lv.note})")
