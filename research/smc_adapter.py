"""Адаптер к smc-lib Вадима: его канон-детекторы + zone-engine из НАШИХ pandas-пайплайнов.

Мост между его Candle-/zones-кодом и нашим pandas-миром. Один раз настраивает sys.path,
ре-экспортит канон-детекторы (тесты 150/150) и его zone-движок (precompute/snapshot),
+ ПРАВИЛО-БАЗИРОВАННЫЙ скорер силы зон по его законам (TF × возраст × proximity × роль × cluster).

Использование:
    from research.smc_adapter import (precompute_zone_events, snapshot_from_events,
                                      ActiveZone, zone_confluence)
    ev, resampled = precompute_zone_events(df_1m, tfs=("1h","4h","12h","1d"), types=ZTYPES_FAST)
    zones = snapshot_from_events(ev, resampled, df_1m, cut_off_ts)      # каузально
    score = zone_confluence(zones, price, fade_dir="UP")
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMC = ROOT / "smc-lib"
SMC_PRED = SMC / "prediction-algo"
for p in (str(SMC), str(SMC_PRED)):
    if p not in sys.path:
        sys.path.insert(0, p)

# --- его канон (Candle-уровень) ---
from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob  # noqa: E402
from elements.fvg.code import detect_fvg  # noqa: E402
from elements.fractal.code import detect_fractal  # noqa: E402
from elements.rdrb.code import detect_rdrb  # noqa: E402

# --- его zone-движок (pandas-уровень) ---
from zones import (  # noqa: E402
    ActiveZone, precompute_zone_events, snapshot_from_events, df_to_candles,
)

# роли зон по его таксономии (КЛЮЧИ = его _SCANNERS, регистрозависимы!)
ROLE = {
    "fractal": "liquidity", "RB": "liquidity", "ob_liq": "liquidity",
    "FVG": "inefficiency", "iFVG": "inefficiency", "marubozu": "inefficiency",
    "OB": "block", "RDRB": "block", "block_orders": "block", "iRDRB": "block", "ob_vc": "block",
}
# монотонные TF-веса (его force v3: старший ТФ значимее; кап как у него)
TF_W = {"1h": 1.0, "2h": 2.0, "4h": 4.0, "6h": 6.0, "12h": 12.0, "1d": 13.0, "2d": 13.0, "3d": 13.0}
# быстрый набор типов для экспериментов (его ключи; без дорогих ob_vc cross-TF / iFVG max_gap)
ZTYPES_FAST = ("OB", "FVG", "fractal", "RDRB", "ob_liq", "marubozu")


def to_candles(df):
    """pandas df (open/high/low/close[/open_time]) -> list[Candle]. Обёртка над его df_to_candles."""
    return df_to_candles(df)


def _maturity(age_bars: int) -> float:
    """U-образная зрелость зоны (его закон фрактала): свежая слаба, зрелая макс, старая слаба."""
    if age_bars < 2:
        return 0.4
    if age_bars <= 40:
        return 1.0
    if age_bars <= 120:
        return 0.7
    return 0.4


def zone_confluence(zones: list, price: float, fade_dir: str, max_dist_pct: float = 4.0) -> dict:
    """Сила конфлюэнса зон ПО НАПРАВЛЕНИЮ сделки (fade_dir = куда ждём ход).

    Поддерживающие сделку зоны (по его логике реакции/магнита):
      - fade UP (ждём отскок вверх): block/liquidity зоны НА/ПОД ценой (опора снизу) — реакция вверх;
      - fade DOWN: block/liquidity зоны НА/НАД ценой (сопротивление сверху) — реакция вниз.
    Вклад зоны = TF_W × proximity × maturity × role_w. Возврат score + разбивка.
    """
    want_side = {"UP": ("below", "inside"), "DOWN": ("above", "inside")}[fade_dir]
    score = 0.0
    n_block = n_liq = n_ineff = 0
    contributors = []
    for z in zones:
        if z.distance_pct > max_dist_pct or z.side not in want_side:
            continue
        role = ROLE.get(z.type, "block")
        role_w = {"block": 1.0, "liquidity": 0.7, "inefficiency": 0.6}[role]
        prox = max(0.0, 1.0 - z.distance_pct / max_dist_pct)      # ближе → сильнее
        contrib = TF_W.get(z.tf, 1.0) * (0.4 + 0.6 * prox) * _maturity(z.age_bars) * role_w
        score += contrib
        if role == "block":
            n_block += 1
        elif role == "liquidity":
            n_liq += 1
        else:
            n_ineff += 1
        contributors.append((z.tf, z.type, round(z.distance_pct, 2), round(contrib, 2)))
    # cluster-бонус: несколько зон рядом усиливают (его закон cluster)
    cluster = n_block + n_liq + n_ineff
    if cluster >= 3:
        score *= 1.15
    return {"score": round(score, 3), "n_block": n_block, "n_liq": n_liq,
            "n_ineff": n_ineff, "n_total": cluster, "contributors": contributors[:8]}


__all__ = ["Candle", "detect_ob", "detect_fvg", "detect_fractal", "detect_rdrb",
           "ActiveZone", "precompute_zone_events", "snapshot_from_events", "to_candles",
           "zone_confluence", "ROLE", "TF_W", "ZTYPES_FAST"]
