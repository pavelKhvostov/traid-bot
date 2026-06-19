# B6 — RSI (planned)

Закреплённое название для блока B6. **Sub-conditions (B6Cx) ещё не реализованы.**

## Идея

Использование Relative Strength Index (RSI) как контр-индикатора для предсказания pivot:
- На FH (top): RSI overbought (≥ 70 или экстремальные значения) → buyer exhaustion
- На FL (bottom): RSI oversold (≤ 30 или экстремальные значения) → seller exhaustion

«Снятие RSI» — расхождение между RSI и ценой (бычья / медвежья дивергенция) тоже может быть признаком pivot.

## Кандидаты на B6Cx

(Пока не реализовано. Формализм и параметры — TBD.)

- **B6C1** — overbought/oversold на 12h: RSI(14) ≥ 70 для FH / ≤ 30 для FL
- **B6C2** — RSI divergence (higher high price + lower high RSI для FH; зеркально для FL)
- **B6C3** — multi-TF RSI confluence (3D + D + 12h overbought одновременно)
- **B6C4** — RSI stoch (stochastic RSI) с экстремальными значениями
- **B6C5** — RSI cross/breakout (выход RSI из overbought/oversold зоны на pivot bar)

## Связанные memories

- [[mh-screening-best-config-not-lazybear]] — RSI/StochRSI screening config (rsi_stoch=50 как ключевая ось)
- [[feedback-rsi-cumulative-fresh-exit-edge]] — RSI cumulative fresh-exit standalone P(W) 60-62% (единственная structural feature с чистым edge на pred12h)

## TODO

- Зафиксировать формальное определение каждого B6Cx
- Проверить, какие RSI-параметры уже считаются в проекте (см. memories выше)
- Causality-аудит ([[feedback-b-series-strict-causal-i]])
- Подключить к Basket evaluator
