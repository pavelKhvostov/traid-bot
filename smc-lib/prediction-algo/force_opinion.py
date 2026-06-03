"""
Каноническое экспертное заключение ПО СИЛЕ (Phase 4 framework).

Отличие от ~/smc-lib/prediction-algo/zones_opinion.py:
  - zones_opinion = «куда дойдёт цена» (P_hit_D, кластеры зон, базовый прогноз)
  - force_opinion = «на чьей стороне сила» (Multi-TF force, anchors, BIAS classification)

Триггер: «экспертное заключение по силе» → run_force_opinion(...) или CLI.

Output:
  1. Header: price, cut-off MSK, total zones
  2. Per-TF force table (BUYER vs SELLER, NET, dominant side) на 9 ТФ
  3. Total summary: n_TFs_BUYER_wins, total_NET, 3D dominance
  4. Top 5 LONG / Top 5 SHORT zones with strength scores
  5. Historical Zone Memory: aged 30d+/60d+/90d+ zones в local band
  6. BIAS classification:
     - UNANIMOUS BUYER/SELLER (9/9 TFs consensus)
     - HTF/LTF CONFLICT (HTF dominant но LTF flipped) = PIVOT signature
     - WEAK BIAS (margin <100)
     - BALANCED (no dominant side)
  7. Expert verdict с reasoning

Formula:
  strength(zone) = TF_weight × age_factor × class_weight × proximity × mitigation_modifier

Базовый канон Phase 4 (см. ~/smc-lib/projects/PHASE4_SPEC.md).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_btc_1m
from zones import (
    ALL_TYPES, ActiveZone,
    precompute_zone_events, snapshot_from_events,
)


SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))

# Phase 4 force framework constants
SMC_TFS = ("1h", "2h", "4h", "6h", "8h", "12h", "1d", "2d", "3d")
TF_WEIGHT = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "8h": 8,
              "12h": 12, "1d": 24, "2d": 48, "3d": 72}
TF_MIN = {"1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
           "12h": 720, "1d": 1440, "2d": 2880, "3d": 4320}
CLASS_MAP = {
    "OB": "block", "ob_vc": "block", "block_orders": "block",
    "FVG": "inefficiency", "iFVG": "inefficiency", "RDRB": "inefficiency",
    "iRDRB": "inefficiency", "marubozu": "inefficiency",
    "fractal": "liquidity", "ob_liq": "liquidity",
}
CLASS_W = {"block": 3, "inefficiency": 2, "liquidity": 1}

PROXIMITY_PCT = 3.0       # zones считаются «near price» если distance_pct < 3%
HISTORIC_BAND_PCT = 2.0   # historic memory ищется в ±2% от цены
LTF_TIER = ("1h", "2h")
MTF_TIER = ("4h", "6h", "8h", "12h")
HTF_TIER = ("1d", "2d", "3d")


def zone_strength(z: ActiveZone) -> float:
    """Phase 4 формула силы зоны."""
    age_h = z.age_bars * TF_MIN.get(z.tf, 60) / 60.0
    cls = CLASS_MAP.get(z.type, "block")
    proximity = max(0.3, 1 - abs(z.distance_pct) / PROXIMITY_PCT)
    if z.mitigation_model == "sweep":
        mit_w = 0.5
    elif z.mitigation_model == "wick-fill":
        mit_w = 0.7
    else:
        mit_w = 1.0
    return (TF_WEIGHT.get(z.tf, 1)
            * (1 + (age_h / 24) ** 0.4)
            * CLASS_W[cls]
            * proximity
            * mit_w)


@dataclass
class TFForce:
    tf: str
    buyer: float
    seller: float

    @property
    def net(self) -> float:
        return self.buyer - self.seller

    @property
    def dominant(self) -> str:
        if self.net > 0.5:
            return "BUYER"
        if self.net < -0.5:
            return "SELLER"
        return "—"


@dataclass
class ForceOpinion:
    cut_off_utc: pd.Timestamp
    cut_off_msk: pd.Timestamp
    price_now: float
    n_zones: int
    per_tf: dict[str, TFForce]
    total_buyer: float
    total_seller: float
    n_TFs_buyer_wins: int
    bias_classification: str
    top_long: list[tuple[ActiveZone, float]]
    top_short: list[tuple[ActiveZone, float]]
    historic_band: dict
    verdict_text: str
    text: str

    @property
    def total_net(self) -> float:
        return self.total_buyer - self.total_seller


def _fetch_latest_1m() -> None:
    fetch = SMC_LIB / "scripts" / "fetch_1m_missing.py"
    if not fetch.exists():
        return
    subprocess.run(
        [sys.executable, str(fetch), "BTCUSDT"],
        capture_output=True, text=True, timeout=120,
    )


def _classify_bias(per_tf: dict[str, TFForce], total_net: float, n_buyer_wins: int) -> str:
    """5-категорий классификация."""
    if n_buyer_wins >= 8:
        return "UNANIMOUS BULLISH"
    if n_buyer_wins <= 1:
        return "UNANIMOUS BEARISH"
    htf_buyer = sum(1 for tf in HTF_TIER if per_tf[tf].net > 0)
    htf_seller = len(HTF_TIER) - htf_buyer
    ltf_buyer = sum(1 for tf in LTF_TIER if per_tf[tf].net > 0)
    ltf_seller = len(LTF_TIER) - ltf_buyer
    # PIVOT signature: HTF dominant in one direction, LTF flipped opposite
    if htf_buyer == 3 and ltf_seller >= 1:
        return "PIVOT signature (HTF BUYER + LTF flip)"
    if htf_seller == 3 and ltf_buyer >= 1:
        return "PIVOT signature (HTF SELLER + LTF flip)"
    if abs(total_net) < 100:
        return "BALANCED (weak bias)"
    if total_net > 0:
        return "HTF BULLISH bias"
    return "HTF BEARISH bias"


def _format_text(op: ForceOpinion) -> str:
    L: list[str] = []
    L.append("=" * 70)
    L.append("  ЭКСПЕРТНОЕ ЗАКЛЮЧЕНИЕ ПО СИЛЕ (Phase 4 framework)")
    L.append("=" * 70)
    L.append(f"  BTC = {op.price_now:,.0f}   |   {op.cut_off_msk.strftime('%d-%m-%Y %H:%M')} MSK")
    L.append(f"  Активных зон (всего): {op.n_zones}")
    L.append("")

    L.append("ПО ТФ — БАЛАНС BUYER vs SELLER (within ±3%)")
    L.append("-" * 70)
    L.append(f"  {'TF':>4}  {'BUYER':>10}  {'SELLER':>10}  {'NET':>10}  Dominant")
    for tf in SMC_TFS:
        f = op.per_tf[tf]
        sign = "+" if f.net >= 0 else ""
        marker = "★" if abs(f.net) > 100 else " "
        L.append(f"  {f.tf:>4}  {f.buyer:>10.1f}  {f.seller:>10.1f}  {sign}{f.net:>9.1f}  {f.dominant} {marker}")
    sign = "+" if op.total_net >= 0 else ""
    overall = "BUYER" if op.total_net > 0 else "SELLER" if op.total_net < 0 else "—"
    L.append(f"  {'TOT':>4}  {op.total_buyer:>10.1f}  {op.total_seller:>10.1f}  {sign}{op.total_net:>9.1f}  {overall}")
    L.append("")

    L.append(f"  n_TFs BUYER wins: {op.n_TFs_buyer_wins}/9")
    f3d = op.per_tf["3d"]
    L.append(f"  3D dominance: BUYER={f3d.buyer:.1f}  SELLER={f3d.seller:.1f}  net={f3d.net:+.1f}")
    L.append("")

    L.append("BIAS CLASSIFICATION")
    L.append("-" * 70)
    L.append(f"  → {op.bias_classification}")
    L.append("")

    if op.top_long:
        L.append("TOP 5 LONG zones (within 2.5%)")
        L.append("-" * 70)
        for z, s in op.top_long:
            age_h = z.age_bars * TF_MIN.get(z.tf, 60) / 60
            L.append(f"  {z.tf:>3} {z.type:>13}  [{z.lo:.0f}; {z.hi:.0f}]"
                     f"  age={age_h:>5.0f}h  dist={z.distance_pct:+.2f}%  str={s:.1f}")
        L.append("")

    if op.top_short:
        L.append("TOP 5 SHORT zones (within 2.5%)")
        L.append("-" * 70)
        for z, s in op.top_short:
            age_h = z.age_bars * TF_MIN.get(z.tf, 60) / 60
            L.append(f"  {z.tf:>3} {z.type:>13}  [{z.lo:.0f}; {z.hi:.0f}]"
                     f"  age={age_h:>5.0f}h  dist={z.distance_pct:+.2f}%  str={s:.1f}")
        L.append("")

    h = op.historic_band
    L.append(f"HISTORICAL ZONE MEMORY (band ±{HISTORIC_BAND_PCT}%)")
    L.append("-" * 70)
    L.append(f"  zones aged 30d+:  {h['aged_30d']:>3}")
    L.append(f"  zones aged 60d+:  {h['aged_60d']:>3}")
    L.append(f"  zones aged 90d+:  {h['aged_90d']:>3}")
    L.append(f"  oldest zone:      {h['oldest_d']:>3.0f} days")
    L.append("")

    L.append("ЗАКЛЮЧЕНИЕ ЭКСПЕРТА")
    L.append("-" * 70)
    for line in op.verdict_text.split("\n"):
        L.append(f"  {line}")
    L.append("")
    return "\n".join(L)


def _build_verdict(op_data: dict) -> str:
    """Текстовый verdict на основе bias classification и силы зон."""
    bias = op_data["bias"]
    total_net = op_data["total_net"]
    f3d = op_data["per_tf"]["3d"]
    top_long = op_data["top_long"]
    top_short = op_data["top_short"]

    lines: list[str] = []

    if bias == "UNANIMOUS BULLISH":
        lines.append("ВСЕ 9 ТФ дают BUYER — uniform consensus, без LTF/HTF конфликтов.")
        lines.append("Структурно — сильнейшая bullish позиция.")
        if top_short:
            lines.append(f"Resistance ceiling: {top_short[0][0].lo:.0f}–{top_short[0][0].hi:.0f} "
                         f"({top_short[0][0].tf} {top_short[0][0].type}).")
        lines.append("Прогноз: отскок / continuation вверх.")
    elif bias == "UNANIMOUS BEARISH":
        lines.append("ВСЕ 9 ТФ дают SELLER — uniform consensus.")
        if top_long:
            lines.append(f"Support floor: {top_long[0][0].lo:.0f}–{top_long[0][0].hi:.0f} "
                         f"({top_long[0][0].tf} {top_long[0][0].type}).")
        lines.append("Прогноз: продолжение вниз.")
    elif "PIVOT signature" in bias:
        if "HTF BUYER" in bias:
            lines.append("HTF (1d/2d/3d) ВСЕ BUYER, но LTF (1h/2h) flipped в SELLER.")
            lines.append("Это классическая PIVOT signature: HTF держит, LTF sweep'ит стопы.")
            if top_long:
                z = top_long[0][0]
                lines.append(f"Главная structural support: {z.lo:.0f}–{z.hi:.0f} ({z.tf} {z.type}).")
            lines.append("Прогноз: bullish reversal вероятен, ожидать окончания LTF sweep.")
            lines.append("Risk: pierce/close НИЖЕ support floor invalidates setup.")
        else:
            lines.append("HTF (1d/2d/3d) ВСЕ SELLER, но LTF (1h/2h) flipped в BUYER.")
            lines.append("PIVOT signature: HTF давит вниз, LTF делает контр-rally.")
            if top_short:
                z = top_short[0][0]
                lines.append(f"Главная structural resistance: {z.lo:.0f}–{z.hi:.0f} ({z.tf} {z.type}).")
            lines.append("Прогноз: bearish reversal вероятен после LTF exhaustion.")
    elif bias == "BALANCED (weak bias)":
        lines.append(f"Баланс сил почти равный (NET={total_net:+.0f}).")
        lines.append("Нет ясного structural bias — рынок в равновесии.")
        lines.append("Прогноз: range-bound / scalp. Без direction conviction.")
    elif bias == "HTF BULLISH bias":
        lines.append(f"HTF сторона дает BUYER (NET={total_net:+.0f}), но не uniform.")
        if f3d.net > 0:
            lines.append(f"3D NET=+{f3d.net:.0f} — institutional bid'ы доминируют.")
        if top_long:
            z = top_long[0][0]
            lines.append(f"Anchor: {z.tf} {z.type} [{z.lo:.0f}; {z.hi:.0f}] str={top_long[0][1]:.0f}.")
        lines.append("Прогноз: умеренный bullish bias, лонг от support зон.")
    elif bias == "HTF BEARISH bias":
        lines.append(f"HTF сторона дает SELLER (NET={total_net:+.0f}).")
        if f3d.net < 0:
            lines.append(f"3D NET={f3d.net:.0f} — institutional offers доминируют.")
        if top_short:
            z = top_short[0][0]
            lines.append(f"Anchor: {z.tf} {z.type} [{z.lo:.0f}; {z.hi:.0f}] str={top_short[0][1]:.0f}.")
        lines.append("Прогноз: умеренный bearish bias, шорт от resistance зон.")

    return "\n".join(lines)


def run_force_opinion(
    cut_off_msk: str | pd.Timestamp | None = None,
    train_days: int = 365,
    fetch: bool = True,
    tfs: tuple[str, ...] = SMC_TFS,
) -> ForceOpinion:
    """Главный API. Если cut_off_msk=None — берётся последний 1m bar.

    Args:
        cut_off_msk: MSK timestamp как строка ('YYYY-MM-DD HH:MM') или Timestamp
                     или None для текущего момента.
        train_days: сколько дней истории грузить для precompute (default 365).
        fetch: вызвать fetch_1m_missing.py перед загрузкой.
        tfs: какие ТФ использовать (default 9 SMC_TFS).
    """
    if fetch:
        _fetch_latest_1m()

    df_1m_full = load_btc_1m()
    # cut-off
    if cut_off_msk is None:
        cut_utc = df_1m_full.index[-1] + pd.Timedelta(minutes=1)
    elif isinstance(cut_off_msk, str):
        cut_utc = pd.Timestamp(cut_off_msk, tz="UTC") - pd.Timedelta(hours=3)
    else:
        cut_utc = pd.Timestamp(cut_off_msk).tz_convert("UTC")
        cut_utc = cut_utc - pd.Timedelta(hours=3)

    # Slice 1m для precompute speed
    win_start = cut_utc - pd.Timedelta(days=train_days)
    df_1m = df_1m_full.loc[win_start:cut_utc]
    if df_1m.empty:
        raise ValueError(f"No 1m data in window {win_start} -> {cut_utc}")

    cut_msk = cut_utc + pd.Timedelta(hours=3)
    df_pre = df_1m.loc[df_1m.index < cut_utc]
    price_now = float(df_pre["close"].iloc[-1])

    events, resampled = precompute_zone_events(df_1m, tfs=tfs, types=ALL_TYPES)
    zones = snapshot_from_events(events, resampled, df_1m, cut_utc)

    # Per-TF force
    per_tf: dict[str, TFForce] = {}
    total_buyer = total_seller = 0.0
    n_buyer_wins = 0
    for tf in SMC_TFS:
        tz = [z for z in zones if z.tf == tf and abs(z.distance_pct) < PROXIMITY_PCT]
        b = sum(zone_strength(z) for z in tz if z.direction.lower() == "long")
        s = sum(zone_strength(z) for z in tz if z.direction.lower() == "short")
        per_tf[tf] = TFForce(tf=tf, buyer=b, seller=s)
        total_buyer += b
        total_seller += s
        if b - s > 0:
            n_buyer_wins += 1

    total_net = total_buyer - total_seller
    bias = _classify_bias(per_tf, total_net, n_buyer_wins)

    # Top zones
    longs = sorted(
        [(z, zone_strength(z)) for z in zones
         if z.direction.lower() == "long" and abs(z.distance_pct) < 2.5],
        key=lambda x: -x[1],
    )[:5]
    shorts = sorted(
        [(z, zone_strength(z)) for z in zones
         if z.direction.lower() == "short" and abs(z.distance_pct) < 2.5],
        key=lambda x: -x[1],
    )[:5]

    # Historical band
    band = [z for z in zones if abs(z.distance_pct) < HISTORIC_BAND_PCT
            and z.tf in MTF_TIER + HTF_TIER]
    ages_d = [(z, z.age_bars * TF_MIN.get(z.tf, 60) / 60 / 24) for z in band]
    historic_band = {
        "aged_30d": sum(1 for _, d in ages_d if d >= 30),
        "aged_60d": sum(1 for _, d in ages_d if d >= 60),
        "aged_90d": sum(1 for _, d in ages_d if d >= 90),
        "oldest_d": max((d for _, d in ages_d), default=0.0),
    }

    op_data = {
        "bias": bias, "total_net": total_net, "per_tf": per_tf,
        "top_long": longs, "top_short": shorts,
    }
    verdict_text = _build_verdict(op_data)

    op = ForceOpinion(
        cut_off_utc=cut_utc, cut_off_msk=cut_msk, price_now=price_now,
        n_zones=len(zones),
        per_tf=per_tf,
        total_buyer=total_buyer, total_seller=total_seller,
        n_TFs_buyer_wins=n_buyer_wins,
        bias_classification=bias,
        top_long=longs, top_short=shorts,
        historic_band=historic_band,
        verdict_text=verdict_text,
        text="",
    )
    op.text = _format_text(op)
    return op


def main() -> None:
    p = argparse.ArgumentParser(description="Force opinion (Phase 4 framework)")
    p.add_argument("--cut-off", default=None,
                   help="MSK timestamp 'YYYY-MM-DD HH:MM' (default: latest 1m bar)")
    p.add_argument("--train-days", type=int, default=365)
    p.add_argument("--no-fetch", action="store_true")
    args = p.parse_args()

    op = run_force_opinion(
        cut_off_msk=args.cut_off,
        train_days=args.train_days,
        fetch=not args.no_fetch,
    )
    print(op.text)


if __name__ == "__main__":
    main()
