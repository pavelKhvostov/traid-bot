# 12h-fractal-new

Прогноз формирования Williams n=2 фрактала на BTC 12h.
Структурированная переработка проекта `pred12h-fractal-three-candles` (архив — там же канон).

## 📊 Структура проекта (canonical PNG)

**Файл:** [`structure.png`](./structure.png) — единая визуальная карта проекта (A cascade + 9 B-блоков inline).

**Триггеры разговора** для показа PNG:
- «структура проекта 12h фракталы»
- «покажи структуру 12h фракталы»
- «структура проекта»  *(в контексте 12h-fractal-new)*
- «как выглядит проект»  *(в этом же контексте)*

**Скрипт генерации:** `~/smc-lib/scripts/plot_pred12h_structure.py` →
выходной файл `~/Desktop/i-rdrb-charts/pred12h_structure.png` + копия в `structure.png` рядом с каноном.

**Обновлять PNG в проекте:** после изменений в скрипте — пересоздать canonical copy:
```bash
python3 ~/smc-lib/scripts/plot_pred12h_structure.py
cp ~/Desktop/i-rdrb-charts/pred12h_structure.png ~/smc-lib/projects/12h-fractal-new/structure.png
```

## Структура

```
A  (cascade)           — отбор кандидатов на pivot bar
   A1  Pre-W           3-свечный локальный экстремум
   A2  ext_5           5 свечей левее меньший экстремум  (был F1)
   A3  color           смена цвета i-1,i ∨ 3 подряд однонапр. (no doji)  (был F2)
   A4  body+wick       убирает признаки марубозу  (был F3)

B  (primitive signal blocks) — независимые SMC-условия на pivot, **strictly causal (только i-N..i)**
   B1  FVG              (был C4; canon v4: B1C1..B1C6)
   B2  OB               (был C7 block_orders; B2C1=OB sweep, B2C2=ob_liq sweep)
   B3  Fractal Liquidity (B3C1=maxV sweep; будущие B3C2+ — Williams/EQH/EQL sweeps)
   B4  HMA              (HMA-семейство: B4C1=HMA-78, B4C2=HMA-200)
   B5  VWAP             (был B8; B5C1 = ≥2 W-aligned swept VWAPs)
   B6  RSI              (planned, B6Cx TBD — оверкуплено/перепродано/divergence)
   B7  MoneyHands       (planned, B7Cx TBD — pivot money hands cascade)
   B8  Power Zone       (был C9 → B9; B8C1 = reverse force divergence ∪3)
   B9  Others           (catch-all: B9C1 = P11_count 4-window OR-basket)

Basket                — OR-union B1..B9, финальная фильтрация на predicted pivot

Sub-blocks внутри B (compound notation):
   B1 = B1C1 ∪ B1C2 ∪ ... ∪ B1C6        (6 causal sub-conditions FVG)
```

## Текущие цифры

Окно: **2020-01-01 → текущий момент** · 4 698 12h-баров.

### A cascade (отсекаем лишнее)

| stage | n | conf | WR |
|---|---:|---:|---:|
| A1 Pre-W | 3 099 | 1 289 | 41.59% |
| A2 ext_5 | 2 031 | 866 | 42.64% |
| A3 color | 1 507 | 677 | 44.92% |
| **A4 body+wick** | **1 356** | **659** | **48.60%** ← baseline |

### B-blocks union WR (canonical 2026-06-06, окно 2020-01-01 → now)

| B | name | n | conf | WR | Δ baseline |
|---|---|---:|---:|---:|---:|
| B1 | FVG (B1C1..B1C6) | 226 | 162 | **71.68%** | +23.08 pp |
| B2 | OB (B2C1 + B2C2) | 105 | 79 | **75.24%** | +26.64 pp |
| B3 | Fractal Liquidity (B3C1 maxV) | 375 | 282 | **75.20%** | +26.60 pp |
| B4 | HMA (B4C1 + B4C2) | 234 | 157 | 67.09% | +18.49 pp |
| B5 | VWAP (B5C1) | 95 | 76 | **80.00%** | +31.40 pp |
| B6 | RSI *(planned, no B6Cx yet)* | — | — | — | — |
| B7 | MoneyHands *(planned, no B7Cx yet)* | — | — | — | — |
| B8 | Power Zone (B8C1 force div ∪3) | 63 | 52 | **82.54%** | +33.94 pp |
| B9 | Others (B9C1 P11 4-window OR) | 203 | 148 | 72.91% | +24.31 pp |

### Sub-conditions BxCy (per filter)

| Cx | filter | n | conf | WR | Δ |
|---|---|---:|---:|---:|---:|
| B1C1 | S100 / WIDE | 35 | 33 | **94.29%** | +45.69 |
| B1C2 | S50 / AGE-WIDE | 63 | 55 | 87.30% | +38.70 |
| B1C3 | S70 / AGE50 | 130 | 98 | 75.38% | +26.78 |
| B1C4 | S50 / HTF-WIDE | 53 | 41 | 77.36% | +28.76 |
| B1C5 | S50 + vol_z ≥ +2σ | 66 | 48 | 72.73% | +24.13 |
| B1C6 | S50 → retest ≤3b | 38 | 26 | 68.42% | +19.82 |
| B2C1 | OB FIRST 50%-sweep multi-TF | 58 | 52 | **89.66%** | +41.06 |
| B2C2 | ob_liq FIRST 50%-sweep multi-TF | 73 | 50 | 68.49% | +19.89 |
| B3C1 | maxV sweep (i-1) | 375 | 282 | 75.20% | +26.60 |
| B4C1 | HMA-78 sweep (12h ∪ D) LIVE | 194 | 128 | 65.98% | +17.38 |
| B4C2 | HMA-200 sweep D LIVE | 54 | 42 | 77.78% | +29.18 |
| B5C1 | ≥2 W-aligned swept VWAPs | 95 | 76 | 80.00% | +31.40 |
| B8C1 | Reverse Force Divergence (∪3) | 63 | 52 | 82.54% | +33.94 |
| B9C1 | P11_count 4-window OR | 203 | 148 | 72.91% | +24.31 |

### Basket (OR-union B1∪..∪B9)

| version | n | conf | WR | Δ от baseline |
|---|---:|---:|---:|---:|
| **Basket_v3** (canonical, causal-only, 2026-06-06) | **724** | **483** | **66.71%** | **+18.11 pp** |
| ~~Basket_v2~~ (старое окно, lookahead inc.) | 654 | 437 | 66.8% | +18.2 |

**Selectivity:** 724 / 1356 ≈ 53% A4-baseline отфильтровано в basket.

## Файлы

| Документ | Содержание |
|---|---|
| [A_cascade.md](./A_cascade.md) | A1..A4 cascade, оптимизированный код |
| [B1_fvg.md](./B1_fvg.md) | B1 FVG + sub-basket D1..D7 (полный канон) |
| [B2_ob.md](./B2_ob.md) | B2 OB (Order Block) — B2C1 + B2C2 (ob_liq) |
| [B3_fractal_liquidity.md](./B3_fractal_liquidity.md) | B3 Fractal Liquidity — B3C1 = maxV sweep |
| [B4_hma.md](./B4_hma.md) | B4 HMA — B4C1 (HMA-78) + B4C2 (HMA-200) |
| [B5_vwap.md](./B5_vwap.md) | B5 VWAP — B5C1 (≥2 W-aligned swept VWAPs) |
| [B6_rsi.md](./B6_rsi.md) | B6 RSI (planned — B6Cx ещё не реализованы) |
| [B7_moneyhands.md](./B7_moneyhands.md) | B7 MoneyHands (planned — B7Cx ещё не реализованы) |
| [B8_power_zone.md](./B8_power_zone.md) | B8 Power Zone — B8C1 (reverse force divergence ∪3) |
| [B9_others.md](./B9_others.md) | B9 Others (catch-all) — B9C1 (P11_count 4-window OR-basket) |
| [Basket.md](./Basket.md) | Basket логика, OR-union B1..B9, история |
| [scripts.md](./scripts.md) | Карта скриптов (источники для A/B/C) |

## Канонический архив (источник истории)

- `~/smc-lib/projects/pred12h-fractal-three-candles.md` — старый канон (F1..F3 / C1..C9 / D1..D6 v2) сохранён как есть, **не править**.
- Все decision-логи и эксперименты до 2026-06-06 — там.

## Memory

- [[feedback-pred12h-window-and-noimp]] — окно 2020-01-01 → now, NO imp
- [[12h-fractal-filter-F1-F2]] — устаревшее имя для A-cascade
- [[pred12h-c4-subbasket-architecture]] — устаревшее имя для B1 sub-basket
- [[12h-fractal-orbasket-c1-c5]] — устаревшее имя для Basket

При первой правке этих memories — переименовать в `*-A`, `*-B1`, `*-Basket` соответственно.

## История

- **2026-06-06**: создание new-структуры A/B/Basket; B1 переработан в B1_v3 = B1C1..B1C7 (255/74.12%). D-нотация подкорзин deprecated — заменена на B1Cx compound notation.
- **2026-06-06 (фикс)**: **B1_v4 = B1C1..B1C6** (226/71.68%) — удалён REJ_BAR за нарушение causality (использовал bar i+1). Закреплено правило strict causality для B-серии (memory [[feedback-b-series-strict-causal-i]]).
- **2026-06-06 (swap)**: **B2 ↔ B7** меняются местами. B2 = OB (Order Block, был C7 block_orders) — продвинут на 2-е место как вторая основная зона интереса после FVG. B7 = maxV (был C1). Все B теперь имеют формат BxCy для sub-conditions (B2C1 = базовый OB sweep).
- **2026-06-06 (merge)**: **ob_liq** (был B4) перенесён в B2 как **B2C2** — структурно ob_liq в OB-семействе (оба класса «блок»). B4 = RESERVED slot. B5..B9 нумерация без изменений.
- **2026-06-06 (swap)**: **B3 ↔ B7**. Новый **B3 = Fractal Liquidity** (3-я зона интереса по таксономии), B3C1 = maxV sweep (перешёл из бывшего B7). P11_count переехал на B7.
- **2026-06-06 (merge)**: **HMA-200** (был B6) перенесён в B5 как **B5C2** — оба HMA-индикатора (78 и 200) объединены в одно семейство. B6 = RESERVED slot. B7..B9 нумерация без изменений.
- **2026-06-06 (swap)**: **B4 ↔ B5**. HMA-семейство переехало с B5 на **B4** (теперь B4C1 = HMA-78, B4C2 = HMA-200). B5 = RESERVED slot.
- **2026-06-06 (swap)**: **B5 (reserved) ↔ B8 (VWAP)**. VWAP переезжает в **B5** (B5C1 = ≥2 W-aligned swept VWAPs). B8 = RESERVED slot.
- **2026-06-06 (swap)**: **B8 (reserved) ↔ B9 (force_div)**. Force divergence переезжает в **B8** под новым именем **Power Zone** (B8C1 = reverse force divergence ∪3). B9 = RESERVED slot.
- **2026-06-06 (swap)**: **B7 (P11) ↔ B9 (reserved)**. P11_count переезжает в **B9C1**. B9 = **Others** (catch-all category для разнородных «прочих» примитивов; B9Cx могут быть концептуально не связаны). B7 = RESERVED slot.
- **2026-06-06 (name)**: **B6 = RSI**, **B7 = MoneyHands**. Названия закреплены, но sub-conditions (B6Cx / B7Cx) пока **не реализованы**. Это «named placeholders» — slot занят концептуально, имплементация впереди.
