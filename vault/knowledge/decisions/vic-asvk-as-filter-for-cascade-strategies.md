---
tags: [decision, vic-asvk, filter, forensic, strategy-1-1-4]
date: 2026-05-13
---

# ViC ASVK как фильтр для каскадных стратегий

Forensic-анализ ViC признаков на закрытых сделках 1.1.4 BFJK (115 trades). Цель — найти скрытую логику отделяющую WIN от LOSS.

## Лучший single-feature filter

**|maxV-1d distance| > 1 ATR-1h** (entry далеко от dominant volume zone предыдущего дня):

| | n | WR | total | avg |
|---|---|----|----|-----|
| Baseline 1.1.4 | 115 | 64.3% | +107R | +0.93 |
| **|maxV_1d| > 1 ATR** | **68** | **70.6%** | +76R | **+1.12** |

**+6.3pp WR**, +0.19R/trade. Frac kept: 59%.

## Signed direction split (на 1.1.4)

| Direction | maxV vs entry | n | WR | avg R |
|-----------|---------------|---|-----|-------|
| LONG | maxV ABOVE entry (dist > 1 ATR) | 10 | **90.0%** | **+1.70R** |
| LONG | maxV BELOW entry | 21 | 66.7% | +1.00R |
| LONG | maxV NEAR entry | 21 | 38.1% | +0.14R ❌ |
| SHORT | maxV ABOVE entry | 27 | 55.6% | +0.67R |
| SHORT | maxV BELOW entry (dist > 1 ATR) | 10 | **100%** | **+2.00R** |
| SHORT | maxV NEAR entry | 26 | 69.2% | +1.08R |

**Скрытая логика**: когда **price уже extended от вчерашнего volume center** → setup в фазе **continuation**, WR 90-100% (но n=10/класс — wide CI).

Anti-pattern: entry в зоне maxV-1d (±1 ATR) на LONG → WR 38% (катастрофа).

## Что НЕ работает

- delta_1h alignment: counter лучше aligned (n=11, шум)
- ViC divergence: WR 88.9% но n=9, шум
- Combination filters обычно overfit (multiple testing)
- Direct directional maxV filter (filter J) хуже simple |dist|>1 filter B

## Aудит (multiple testing risk)

- 36 сравнений → ~1.8 ожидаемых false positives при α=0.05
- Sample n=115 → SE WR ±4.7pp, 95% CI ±10pp
- Только эффекты > 10pp с n>=20 — "вероятно реальные"
- Lookahead clean (проверка через etap_92): фичи рассчитаны на prev closed bar

## Применение в live

Live-интеграция (TBD):
1. Добавить расчёт maxV-1d в `multi_strategy_scanner.py`
2. Перед broadcast 1.1.4 setup: вычислить |entry - maxV-1d| / ATR-1h
3. Если в пределах 1 ATR → silent (или low-confidence сигнал)

См. [[vic-asvk-indicator-python]] для канонической реализации.

## Связи

- [[vic-asvk-indicator-python]]
- [[strategy-1-1-4-bfjk-portfolio]]
- [[ifvg-7-concepts-tested]] — C2 surprise (iFVG-against = POSITIVE)
- [[2026-05-13-live-bot-vic-ifvg-strategies-117-118]]
