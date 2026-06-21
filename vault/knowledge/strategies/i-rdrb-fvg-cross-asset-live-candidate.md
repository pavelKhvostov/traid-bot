---
tags: [strategy, i-rdrb, fvg, cross-asset, combined-d, live-candidate]
date: 2026-06-19
status: validated-cross-asset (live-candidate, не подключён)
related: [[i-rdrb-fvg-combined-d-block-edge-sl-01]], [[i-rdrb-fvg-v2-definition]]
---

# i-RDRB+FVG — cross-asset валидация (Combined-D) → live-кандидат №1

Достроил канонический i-RDRB+FVG (5 свечей, V1) до полноценной цепочки проекта:
**детектор в `strategies/` + тесты + cross-asset бэктест**. Главный пробел прежних
заметок ([[i-rdrb-fvg-combined-d-block-edge-sl-01]] = BTC-only 6y) закрыт.

## Что построено

- `strategies/strategy_i_rdrb_fvg.py` — pandas-детектор `detect_i_rdrb_fvg(df, idx, zone_version)`.
  Переиспользует канон `strategy_rdrb.detect_rdrb` + `strategy_1_1_1.detect_fvg`.
  C1=idx-2..C5=idx+2; i-RDRB (C4 разворот за block + цвет) + FVG(C3,C4,C5) того же направления.
  Entry/SL = **Combined-D** (entry на block edge, SL = pattern_extreme ± 0.1 к block).
- `tests/test_strategy_i_rdrb_fvg.py` — 8 тестов (LONG/SHORT happy + 4 edge + causal-locality). Зелёные.
- `research/i_rdrb_fvg/backtest_cross_asset.py` — BTC/ETH/SOL, год-разбивка, RR-сетка, clean-structure.
  Методология 1:1 с `smc-lib/scripts/backtest_combined_d_full.py` (limit-fill от close C5, SL/TP на 1m).

## Результат (TF=1h — сильнее 2h)

| Символ | closed | WR% | sumR @RR1 | лучший RR | LONG R | SHORT R | +лет |
|---|---|---|---|---|---|---|---|
| BTC | 825 | 57.7% | **+127.0** | +144 @RR2 | +96 | **+31** | 6/7 |
| ETH | 786 | 56.1% | **+96.0** | +145 @RR2.5 | +35 | **+61** | ~4/6 |
| SOL | 786 | 51.4% | +22.0 | +37 @RR2.5 | +22 | 0 | маргинал |

- **BTC +127R воспроизводит валидированный Combined-D (+122.6R/6y)** → pandas-порт верен.
- **Переносится cross-asset** — все 3 в плюс на 1h при всех RR (книжные одиночки умирали на ETH/SOL).
- **НЕ bull-drift**: на BTC и ETH SHORT-сторона положительна (ETH SHORT +61 > LONG!). Это отличает от
  убитого ICT double-FVG (там SHORT ~0). Двусторонний edge = структурный паттерн, а не дрейф.
- BTC робастен по годам; ETH солидно, но деградирует в 2024-26 (особ. при высоком RR); SOL маргинален
  и год-нестабилен (LONG-only, SHORT=0) → FLAT/малый сайз или исключить.

## clean-structure фильтр — НЕ подтверждён

Proxy (одиночный same-dir OB-1h ∩ block) НЕ воспроизвёл V2 block-orders anti-filter из
[[i-rdrb-fvg-v2-definition]]: dirty-корзина крошечная (43/54/42), сепарации нет. Настоящий
block_orders — отдельный smc-lib элемент; буст-фильтр пока не доказан на этой конфигурации.

## Вердикт

✅ **Живая цепочка, live-кандидат №1.** Единственная из проверенных, что переносится cross-asset с
двусторонним edge. Рекомендация к подключению: BTC (RR≈2) + ETH (RR≈2.5), SOL — FLAT/малый сайз.
Грейд-sizing (доказанный риск-рычаг) применим сверху.

## Связи
- [[i-rdrb-fvg-combined-d-block-edge-sl-01]] — entry/SL канон (BTC 6y baseline)
- [[i-rdrb-fvg-v2-definition]] — V2 6-свечной вариант + block-orders фильтр
- [[грейд-как-правило-размера-pnl-и-непереносимость-на-1-1-2]] — risk-рычаг сверху
