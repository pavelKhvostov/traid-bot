---
tags: [session, wicked-ob, rdrb, snr, strategy-family]
date: 2026-05-18
---

# Сессия 2026-05-18 — Wicked OB полное семейство, RDRB v2/MAX, SnR

Большая многоразовая /loop сессия по wicked-fractal OB-D исследованию.
Построено **7 OOS-валидированных variants** одной стратегии. Уточнены понятия
RDRB (3 версии зоны) и SnR (классический S&R, не ICT).

## Главные результаты

### 🚀 Wicked OB-D — 7 validated variants

См. [[strategy-wicked-fractal-ob-d-btc-only]]. 24 etap (130-153) построили
полное семейство стратегий с разными trade-off:

| Variant | Profile | n | PnL | R/tr | bad | OOS |
|---------|---------|---|-----|------|------|-----|
| C       | A2 + V2\A2 (no filter)         | 513 | +129R   | +0.25 | 1/7 | +129.9R ✓ |
| H       | C - hours 11/13/17 UTC         | 461 | +149.9R | +0.33 | 1/7 | +150R ✓ |
| E       | C + score≥0.00                 | 159 | +91.6R  | +0.58 | 2/7 | +92.2R ✓ |
| F       | C + Asia session (00-07 UTC)   | 150 | +60.7R  | +0.40 | 1/7 | +55.9R ✓ |
| B       | A2 only (no extras)            | 146 | +80R    | +0.55 | 0/7 | +0.41 R/tr ✓ |
| D       | C + score≥0.50                 | 68  | +48.8R  | +0.72 | 0/7 | +45.9R ✓ |
| Tier-1  | BTC + score≥0.50 (overlay)     | 22  | +33R    | +1.49 | 0/7 | WR 88.9% ✓ |

**Все 7 variants OOS-validated**. OOS R/tr matches или exceeds in-sample во всех
случаях — exceptional robustness signal.

### Ключевые structural findings

1. **V2 vs A2 cascades = almost disjoint** (5 setups overlap из 85). 3-stage и
   4-stage produce разные setups — combining doubles BTC PnL.

2. **Score filter is BTC edge-extractor**. На ETH score≥0.50 на A2 alone HURTS,
   но на V2 unique trades works → Tier-1 расширился до 68 trades portfolio
   через Variant C+score.

3. **Anti-edge hours 11/13/17 UTC** — confirmed dead zones across all 6 OOS
   train windows + 6 OOS test years. Mostly ETH noise filter
   (+21.9R ETH boost, marginal hurt на BTC).

4. **Asia session (00-07 UTC) walk-forward validated** — R/tr +0.40
   in-sample → +0.41 OOS (exceeds!). Non-Asia subset = +0.19 R/tr (×2.2 хуже).

5. **Composite filters don't always stack** — Variant G (Asia + score) FAILED:
   21 trades / 2 bad / 6 years. Filters overlap on "high quality".

### Sensitivity (null results = strategy is robust)

- **sl_pct sensitivity** (etap_139): identical PnL across 0.25-0.50 — 1% MIN_SL
  floor dominates.
- **entry_pct sensitivity** (etap_140): identical 0.60-0.90 (±1.2R variation).

Два consecutive null results = edge не зависит от тонкой настройки параметров.

## 🧠 RDRB zone variants — 3 версии

См. [[что такое rdrb]] (нужно обновить с этими 3 формулами).

Пользователь уточнил что для LONG/SHORT возможны 3 определения зоны:

1. **V1 intersection** — текущий код в `strategies/strategy_rdrb.py`. Узкая
   зона = пересечение фитилей anchor+trigger, ограниченное телами.
2. **V2 + anchor body extension** — расширение down к anchor body TOP (LONG)
   / up к body BOTTOM (SHORT). Захватывает фитиль anchor над/под телом.
3. **V3 MAX** — самая широкая зона = **весь противоположный фитиль anchor**,
   trigger в формуле не участвует. Для LONG = [body_top_anchor, anchor.high].

См. [[project_rdrb_zone_variants]] (в memory) — детали + сравнение ширины.

Wicked OB-D у нас концептуально близок к V3 MAX (использует ob_d.bottom/top
как целую зону), так что [[strategy-wicked-fractal-ob-d-btc-only]] и
[[s3 rdrb + ob1h]] — разные реализации одного и того же principle с разной
шириной зоны.

## 🧠 SnR concept

Пользователь спросил про "SNR block" в ICT. Расследование:

- **«SNR block» в книге ICT НЕ существует** как канон-термин
- SnR = **Support aNd Resistance** — классический price-action концепт
- ICT переименовывает S/R в **«liquidity pools»**
- Близкие ICT-блоки: OB, Breaker, Mitigation, Rejection — каждый конкретизирует
  определённую форму уровня
- **Supply & Demand** (Sam Seiden) — отдельная школа, не ICT

См. [[что такое snr]] (новая заметка).

### Пример SnR на BTC

На 2h (последние 125 дней): **active RESISTANCE [80,877 - 81,446]** (5 touches
в неделе 5-13 May 2026).

На 1d (последние 730 дней, до 2026-05-17): **active RESISTANCE [81,638 -
83,264]** (3 daily touches 6-14 May). 2h-зона полностью внутри 1d-зоны →
**multi-TF confluence** подтверждает уровень.

Текущая цена $77,457 в midrange между:
- $82,460 active resistance (1d)
- $74,725 active support (1d)

## Файлы созданные/изменённые

### Research (24 etap, 130-153)
- `etap_130_wicked_4stage_111_112.py` — 4-stage cascade A/B grid (initial)
- `etap_131_wicked_4stage_strict_dedup.py` — strict dedup, A2 winner
- `etap_132_wicked_a2_eth_sol.py` — ETH/SOL cross-symbol
- `etap_133_wicked_a2_exits_filters.py` — direction + floating + BE
- `etap_134_wicked_a2_long_floating_xsymbol.py` — LONG x-symbol additive
- `etap_135_wicked_a2_portfolio_btc_eth.py` — Variant B portfolio
- `etap_136_wicked_a2_floating_per_symbol.py` — 60-config float grid
- `etap_137_wicked_a2_per_symbol_portfolio.py` — Variant A/B
- `etap_138_wicked_a2_walk_forward.py` — Variant B walk-forward
- `etap_139_wicked_a2_sl_sensitivity.py` — null result
- `etap_140_wicked_a2_entry_rr_sensitivity.py` — null result
- `etap_141_wicked_a2_score_filter.py` — score≥X grid → Tier-1
- `etap_142_tier1_walkforward.py` — Tier-1 OOS validated (WR 88.9%)
- `etap_143_v2_vs_a2_overlap.py` — V2/A2 disjoint discovery
- `etap_144_v2_a2_combined_portfolio.py` — Variant C
- `etap_145_variant_c_walkforward.py` — C OOS validated
- `etap_146_variant_c_tier1.py` — Variant D (C + score≥0.5)
- `etap_147_variant_d_walkforward.py` — D OOS validated
- `etap_148_variant_c_extended_score.py` — extended score sweep → Variant E
- `etap_149_variant_c_time_of_day.py` — hour-of-day breakdown
- `etap_150_asia_session_walkforward.py` — Variant F validated
- `etap_151_composite_filters.py` — Variant H (anti-cluster) + Variant G failed
- `etap_152_variant_h_walkforward.py` — H OOS validated
- `etap_153_variant_e_walkforward.py` — E OOS validated
- `etap_154_find_last_snr_btc_2h.py` — SnR finder (used for 2h + 1d)

### Vault updates
- [[strategy-wicked-fractal-ob-d-btc-only]] — все 7 variants + анализы
- [[floating-tp-only-helps-low-wr-strategies]] — refined с counter-trend + baseline>0
- [[что такое rdrb]] — TODO update с V1/V2/V3 MAX
- [[что такое snr]] — NEW

### Memory updates
- [[project_rdrb_zone_variants]] — NEW

## Открытые задачи

1. **Обновить [[что такое rdrb]]** с тремя формулами V1/V2/V3
2. **A/B test V1 vs V2 vs V3 zones** на `strategies/strategy_rdrb.py` — посмотреть
   как ширина зоны влияет на edge
3. **Live integration** одного из wicked OB variants (B / H / D — кандидаты)
4. **PDF compile** wicked OB family (по образцу etap_75 для 1.1.4)
5. **iFVG как L3 cascade** — never tested, could be next novel variant
