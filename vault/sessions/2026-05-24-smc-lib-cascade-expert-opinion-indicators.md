---
tags: [session, smc-lib, expert-opinion, cascade, indicators, asvk, vwap, marubozu, fractal, i-fvg]
date: 2026-05-24
duration: очень длинная сессия (вечер→ночь)
status: complete
related: [[2026-05-24-smc-lib-canon-vwap-asvk-introduction]], [[smc-lib-as-canonical-source]], [[expert-opinion-multi-tf-cascade-methodology]]
---

# 2026-05-24 — smc-lib expansion + expert opinion methodology + indicators layer

Очень длинная сессия. Расширили smc-lib с 8 до **11 primitive-элементов**, оформили **методологию формирования экспертного заключения** (multi-TF cascade W→15m) с полной реализацией, и интегрировали **10 индикаторов** (включая 4 ASVK + VWAPs ranking).

## I. SMC-lib — новые элементы (8 → 11)

### 1. OB обновлён: breaker_block subzone

[`elements/ob/`] синхронизирован с `block_orders` `(N₁=1, N₂=1)` случаем:
- LONG `zone = [min(prev.low, cur.low), cur.close]` (было `[..., prev.open]`)
- Добавлено поле `breaker_block: Interval` = `[prev.open, cur.close]` LONG / `[cur.close, prev.open]` SHORT
- Drop area / rally area — подзоны в definition.md
- **`ob_liq` оставлен со своей узкой зоной** (drop area only) — by design, см. [[feedback-ob-vs-ob-liq-zones-differ]]

### 2. Раздел "Правила" + `rules.md`

Создан `~/smc-lib/rules.md` как cross-element справочник (по аналогии с `zone_of_interest.md`). В каждый `definition.md` добавлена секция "Правила" → ссылка на rules.md.

**Правило 1 — Закрепление цены за уровнем**:
- Пробойная свеча close за уровнем (желательно большое тело)
- Подтверждающая свеча close за уровнем (минимум 2 свечи)

### 3. i_fvg (Inverse FVG) — 9-й элемент

`elements/i_fvg/` — composite: FVG-B противоположного направления первой касается ранее untouched FVG-A. Зона интереса = **overlap A ∩ B**. Роль A инвертирует. Direction = direction(B).

API: `detect_i_fvg(a_c1, a_c2, a_c3, between, b_c1, b_c2, b_c3) → IFVG | None`.

10 тестов. Canon: [[inverse-fvg-definition]] (2026-05-13).

### 4. marubozu — 10-й элемент (canon: Pine WICK.ED, не body/range ≥ 0.95!)

`elements/marubozu/` — одиночная свеча без фитиля **со стороны open**:
- LONG: `open == low AND close > open`
- SHORT: `open == high AND close < open`
- Зона = тело свечи

**КРИТИЧЕСКОЕ изменение canon** относительно vault `marubozu тело 95 процентов.md`:
- Старый канон (body/range ≥ 0.95) **deprecated**
- Pine WICK.ED разрешает **произвольный** противоположный фитиль (open-side rule only)
- На BTC 90m за 6 лет: 893 marubozu по Pine vs ~10× меньше по старому канону

13 тестов. См. [[feedback-marubozu-canon-pine-wicked]].

**Trading-модель** (для marubozu и других inefficiency-зон):

🧲 Главный принцип ([[feedback-untraded-area-is-magnet]]):
> Непроторгованная область = магнит, притягивающий цену.

Уточнено двухступенчатой коррекцией пользователя:
1. Marubozu — это аномалия, цена стремится её исправить
2. **Цель цены = уровень open** (точечный), НЕ всё тело
3. После касания open → продолжение исходного импульса

**Real example в definition.md**: LONG marubozu BTC 90m 2026-05-19 19:30 MSK (O=L=76 611.99). Спустя 5 баров (2026-05-20 03:00 MSK) цена коснулась 76 516.74 (sweep open), проторговала уровень → LONG continuation +1.33% за 10 баров.

См. [[feedback-marubozu-is-imbalance-not-support]].

### 5. fractal — 11-й элемент (Williams N=2 canon)

`elements/fractal/` — strict swing point на (2N+1)-bar окне:
- N=2 (5-bar Williams BW) — default
- FH: `center.high` строго > всех 2N соседей
- FL: зеркально
- **Единственный primitive с точечной зоной** (level: float, не Interval)
- Класс = liquidity

14 тестов.

Уточнены 2 fundamental свойства фрактальной ликвидности ([[feedback-fractal-liquidity-strength-and-sweep]]):
1. **Сила = TF × возраст × cluster**; возраст U-образный (свежий и слишком старый → слабее)
2. **Sweep — TF-relative** (wick на своём ТФ); HTF wick "проглатывает" LTF события

LuxAlgo "Liquidity Swings" — measurement layer над FH/FL, **не переопределяет** primitive (N=14 у LuxAlgo — внутренний параметр индикатора).

## II. Expert Opinion methodology

Главный артефакт сессии. **Multi-TF top-down каскад** для построения мнения о движении цены.

Главный принцип ([[feedback-expert-opinion-is-multi-tf-cascade]]):
> Экспертное заключение всегда строится top-down: W → 3D → 2D → D → 12h → 6h → 4h → 2h → 1h → 15m. Не на одном ТФ.

Доку: `~/smc-lib/expert_opinion.md` (10 шагов pipeline + 8 секций output + что НЕ делать).
Реализация: `~/smc-lib/scripts/expert_opinion.py` (3.1s на полный 10-TF каскад).

См. [[expert-opinion-multi-tf-cascade-methodology]] — detail note.

## III. Indicators layer — 10 модулей

`~/smc-lib/indicators/`:

| Модуль | Что | Источник canon |
|---|---|---|
| `atr.py` | ATR Wilder | стандарт |
| `ema.py` | EMA Pine-style (adjust=False) | стандарт |
| `cumulative_delta.py` | Williams A/D proxy | стандарт |
| `volume_profile.py` | POC + VAH/VAL (70%) | стандарт |
| `vwap_anchored.py` | Anchored VWAP | моя реализация |
| `vwap_effectiveness.py` | **Per-TF reactions/breaks scoring** + composite | новое |
| `vic_asvk.py` | VIC ASVK (maxV + delta + norm, auto LTF) | порт vic_levels.py + canon vault |
| `trend_line_asvk.py` | Hull MA (HMA/EHMA/THMA) + MHULL+SHULL+color | порт research/asvk_trend_line |
| `rsi_asvk.py` | Adjusted RSI + adaptive OB/OS + NWE channel | порт research/asvk_rsi |
| `money_hands_asvk.py` | WaveTrend bw2 + color state + HA Money Flow + двойной Stoch | порт research/money_hands |

**VWAPs ranking логика** (новое):
- Anchor на каждом D-фрактале за последний 1 год (~98 фракталов)
- VWAP считается на каждом ТФ каскада
- Effectiveness per TF = `reactions / (reactions + breaks)` где:
  - reaction = bar взаимодействовал с VWAP, close остался на той же стороне
  - break = close сменил сторону
- Composite = weighted avg по `log(1 + interactions)` через все ТФ
- Selection: 2 closest + 6 most effective + 2 farthest

`auto_ltf_minutes` для VIC: D→15m, 12h→10m, 6h→5m, 4h→3m, 2h→3m, 1h→1m. Canon сверка с vault.

## IV. Текущее BTC mining: expert opinion в action

На состоянии 2026-05-24 20:33 MSK, close 76 627:

**Cascade trend regime:**
```
W   CONTRACTION   3D UPTREND   2D UPTREND   
D   DOWNTREND    12h DOWNTREND  6h DOWNTREND  4h DOWNTREND
2h  EXPANSION    1h EXPANSION   15m CONTRACTION
```

**Главные индикаторные находки:**
- D + 12h RSI ASVK в **зелёной зоне** (adaptive OS) — bears exhausted
- 6h Hull **flipped UP** — первый MTF reversal signal
- 2h MH GREEN + 1h VIC delta +117 — LTF momentum bullish
- **VWAPs cluster 76 100–76 700** — 7 effective VWAPs сходятся ровно на цене (massive support)

**Мнение:** Bullish bias ~60-65% для завершения D-retracement в HTF uptrend.
- Trigger A: 1h close > 77 543 (today's 1h FH HH)
- Path: 78 200 → 78 600 (D FVG) → 80 500 (D FVG) → 82 850 (3D ATH)
- Alt B (~25-30%): D close < 76 100 → 74 938 → 73 724 → reversal

## V. Артефакты сессии

**smc-lib новое:**
- `elements/i_fvg/` (3 файла, 10 тестов)
- `elements/marubozu/` (3 файла, 13 тестов)
- `elements/fractal/` (3 файла, 14 тестов)
- `indicators/` (10 модулей)
- `rules.md` (общие правила, Правило 1)
- `expert_opinion.md` (методология)
- `scripts/expert_opinion.py` (cascade runner)
- `scripts/fetch_btc_1m_missing.py` (curl-based fetcher)
- `scripts/survey_zones_d_2026_04_04_now.py`
- `scripts/plot_zones_d_2026_04_04_now.py` (3-панельный обзор)
- `scripts/plot_marubozu_2026_05_19_interaction.py` (real example)
- `scripts/find_last_3_marubozu_90m.py`
- `scripts/plot_d_10_fractals_vwap.py`

**Картинки (PNG в `~/Desktop/i-rdrb-charts/`):**
- `ob_zone_example.png`
- `block_orders_zone_example.png`
- `rdrb_zone_example.png`
- `fvg_zone_example.png`
- `ifvg_zone_example.png`
- `ob_liq_zone_example.png`
- `marubozu_2026_05_19_interaction.png`
- `zones_d_2026_04_04_now.png`
- `d_10_fractals_vwap.png`

**Тесты smc-lib:** 106 → итог (было 69 в начале сессии)

## VI. Memory updates (auto-memory)

Сохранены 7 feedback-memory:
- [[feedback-anchored-vwap-from-fractals]]
- [[feedback-ob-vs-ob-liq-zones-differ]]
- [[feedback-marubozu-canon-pine-wicked]]
- [[feedback-marubozu-is-imbalance-not-support]]
- [[feedback-untraded-area-is-magnet]] 🧲 — **fundamental SMC principle**
- [[feedback-fractal-liquidity-strength-and-sweep]]
- [[feedback-expert-opinion-is-multi-tf-cascade]]

## VII. Что осталось / TODO

- Volume Profile bucket size auto-tuning (сейчас ATR/10, может нужна калибровка)
- VWAP effectiveness: формула эффективности comp-score близка для разных anchor'ов (0.54-0.56 кластер) — нужна более дискриминирующая метрика?
- Графики каскада с overlay индикаторов (готов код, не запускал)
- `elements/snr/` — было отложено пользователем
- `elements/maxv/` — VIC ASVK как primitive (а не только indicator)
- Real LuxAlgo Liquidity Swings — если потребуется как activity-layer над fractal

## Связи

- [[2026-05-24-smc-lib-canon-vwap-asvk-introduction]] — предыдущая сессия (5 элементов smc-lib + zone_of_interest)
- [[expert-opinion-multi-tf-cascade-methodology]] — методология как durable knowledge note
- [[smc-lib-as-canonical-source]] — принцип canonical source
- [[vic-asvk-indicator-python]] — canon VIC, источник порта
- [[asvk-custom-rsi]] — canon RSI ASVK
- [[asvk-trend-line-hull]] — canon Hull MA
- [[money-hands-asvk]] — canon Money Hands
- [[inverse-fvg-definition]] — canon i_fvg
- [[zone-class-liquidity-inefficiency-efficiency]] — три класса зон
