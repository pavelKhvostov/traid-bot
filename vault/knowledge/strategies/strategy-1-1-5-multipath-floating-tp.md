---
tags: [strategy, 1-1-5, floating-tp, multipath, research]
date: 2026-05-17
---

# Strategy 1.1.5 — Multi-path + F6 filter + Floating TP

Дополнение к канону [[project_115_fractal_landscape]] (одобрено 2026-05-11,
WR 47.9%, +106R / 0 bad / 7y). Тут — research-trip по «improve-направлению»:
multi-path union + жёсткий фильтр + floating TP. Результат скромнее канона
по PnL, но подтверждает правило применимости floating TP.

## Что тестировалось (etap_129)

16 chains: `12h/1d fractal × 4h/6h OB-htf × 1h/2h OB-htf × 15m/20m FVG`.
Union dedup по `(signal_time, direction, fvg_b, fvg_t)`, Hull-1h aligned.

Параметры: entry=0.80, sl_pct=0.35 sym, RR=2.0 (strict B5).

## Результаты (BTC 6.3y)

| Этап                          | n   | WR    | PnL    | bad |
|-------------------------------|-----|-------|--------|-----|
| 391 raw → 291 hull_aligned    | —   | —     | —      | —   |
| F0: baseline (hull aligned)   | 125 | 36.8% | +13.0R | 2/7 |
| F1: + EMA-2h pro              | 28  | 50.0% | +14.0R | 2/7 |
| F5: + score>0                 | 104 | 37.5% | +13.0R | 2/7 |
| **F6: EMA AND score>0**       | 24  | 58.3% | +18.0R | 2/7 |
| F6 + floating TP              | 24  | 41.7% | **+31.0R** | 2/7 |
| F6 + BE-ratchet @+1.0R        | 24  | 50.0% | +20.0R | 2/7 |
| F6 + BE-ratchet @+1.5R        | 24  | 50.0% | +16.0R | 2/7 |

Forensic: LONG WR 32.8% / -1R vs SHORT WR 40.3% / +14R (SHORT-преимущество).
EMA pro: WR 50% / +14R vs counter: WR 33% / -1R.

## Ключевой вывод

**Multi-path не масштабирует 1.1.5** — после dedup union сжимается до тех же
~125 setups (single-path уже покрывал почти всё). Канонический detector
`etap_77 → strategies/strategy_1_1_5.py` остаётся базой.

**Floating TP boost +72%** (+18 → +31R) на F6-фильтре подтверждает refined
floating-TP law ([[floating-tp-only-helps-low-wr-strategies]]):
- baseline WR 36.8% < 50% ✓
- continuation после sweep ✓
- → floating работает

## Применимость в live

24 trades за 6.3y = ~4 setups/year. Очень тонкая выборка, **в live не
выносить** — канонический 1.1.5 даёт +106R на полной выборке. Этот
эксперимент — теоретическое подтверждение, что floating TP применим к
1.1.5 (если когда-то понадобится автотрейл).

## Ссылки

- `research/elements_study/etap_128_115_improve.py` — single-path forensic
- `research/elements_study/etap_129_115_multipath_filtered.py` — multipath union
- `research/elements_study/etap_77_115_fractal_tightened.py` — canon detector
- [[project_115_fractal_landscape]] — approved canon
- [[floating-tp-only-helps-low-wr-strategies]] — refined law
- [[4-indicator-momentum-score]] — score build
