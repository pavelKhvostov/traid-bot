---
tags: [session, smc-lib, vwap, vwap-asvk, rb, block-orders, ob, zone-of-interest, forensic, htf-analysis]
date: 2026-05-24
duration: длинная сессия
status: complete
related: [[smc-lib-as-canonical-source]], [[i-rdrb-fvg-combined-d-block-edge-sl-01]], [[2026-05-23-smc-lib-vwap-entry-experiments]], [[12h-fractal-prediction-final-strategy]]
---

# 2026-05-24 — smc-lib canon expansion + VWAPs ASVK introduction

Очень содержательная сессия. Расширили `~/smc-lib/` с 3 до 8 элементов, ввели справочник зон интереса, провели глубокий HTF анализ разворота 23-05, начали изучать VWAP ASVK.

## I. Forensic i-RDRB+FVG WIN-features @ RR=2.2 baseline

Расширение [[2026-05-24-i-rdrb-fvg-evot-vwap-features-sl-optim]] — после compaction добрал статистику по 780 closed trades:

**Топ дискриминаторы WIN (Δ WR от baseline 36.67%):**
- C2 body ≥ 1.5 R_unit: n=45, WR 57.78% (+21.11pp), R/tr +0.849
- F1 ∩ F2 (HTF OB + HTF RDRB): n=111, WR 47.75% (+11.08pp), R/tr +0.528
- EVoT maxV в C1 (раннее объёмное событие): n=73, WR 45.21% (+8.54pp)
- 15m фракталов в зоне = 2: n=18, WR 44.44% (+7.78pp)

**Анти-сигналы:**
- C4 body < 0.3 R: n=26, WR 23.08% (−13.59pp)
- R/ATR ≥ 1.5 (overstretched): WR 30.23%
- C4 overshoot ≥ 1.5R: WR 31.79%

**ICT OB параллель** (`forensic_ict_ob_features_rr22.py`): C2 нашего паттерна геометрически = классическому ICT bullish/bearish OB candle. C4 = displacement, FVG = gap left by displacement. **Зона интереса нашего паттерна и есть классический OB+FVG overlap zone.**

**Опровергнутые ICT-постулаты для нашего паттерна:**
- OB mitigation в armed window: NULL (clean 36.36% vs spent 36.79%)
- OB ∩ FVG overlap: NULL (с overlap 36.53% vs без 36.97%)
- Entry @ overlap midpoint: ХУЖЕ baseline (WR 34.87%)

## II. HTF sweep filter test (паттерн как VC в стиле 1.1.1)

Гипотеза: i-RDRB+FVG = VC, требует C1 (HTF FH/FL sweep) на {4h, 12h, 1d}. **Не подтверждена в строгом виде**:
- UNION sweep на любом HTF: NULL (+0.06pp)
- 1d sweep сольно: +8.33pp на n=20 (но мало)
- Anti-set (без sweep): тот же WR как baseline → отсутствие sweep не делает паттерн хуже

**Direction-asymmetric**: LONG + sweep = +5.27pp; SHORT + sweep = −5.24pp (BTC bullish-bias 6y → bearish FH-sweeps часто continuation, не reversal).

## III. TOTALES data fetched

Скачали через `~/traid-bot/fetch_tv_data.py` (1d/4h/1h/15m, 19464 строк). Пофиксили SSL: `SSL_CERT_FILE=certifi/cacert.pem` в venv. Установлен `tvdatafeed` из git rongardF.

## IV. smc-lib canonical expansion (3 → 8 элементов)

Финальное состояние `~/smc-lib/elements/`:
1. `rdrb/` (был) — 3-свечный RDRB V1/V2
2. `i_rdrb/` (был) — 4-свечный reversal
3. `fvg/` (был) — Fair Value Gap
4. `ob/` (новый) — canon-OB pair, zone из vault canon
5. `ob_liq/` (новый) — OB + Williams 5-bar маркер ликвидности
6. `i_rdrb_fvg/` (новый) — 5-свечный композит (forensic baseline)
7. `block_orders/` (новый) — HTF-OB N+M композит
8. `rb/` (новый) — Rejection Block одиночная свеча

**78 тестов проходят** (полная регрессия).

### IV.1. Block ордеров — несколько итераций правил

История уточнений правила:
1. Изначально: 2+ initial + 1+ counter, last close crosses first open
2. Уточнение: counter STOP на ПЕРВОЙ свече с close-crossing (greedy first-cross)
3. Уточнение: preceding свеча противоположной направленности обязательна
4. Расслабление: N₁ ≥ 1 (раньше ≥ 2), но `(N₁, N₂) ≠ (1, 1)` — иначе это canon-OB
5. **Финальная коррекция зоны**: `[block.low, block.close]` для LONG (включает breaker block + drop area), а **не** body синтетической свечи. Breaker block = подзона `[block.open, block.close]` внутри полной зоны интереса.

Эталон BTC 1h 2026-05-05 LONG: preceding 00:00 MSK (bull) + 01:00-04:00 (2 bear + 2 bull). Зона интереса `[79744.91, 80352.00]` (h=607.09).

### IV.2. RB — sweep правила

Изначально: dom ≥ 2×body AND other < body. **Эталон 2026-04-14 15:00 MSK не прошёл** (other_wick 336 > body 245). Уточнили: **dom ≥ 2×other AND dom > body**. Затем после grid sweep — окончательно зафиксировали K1=2, K2=3 (dom ≥ 2× other AND dom ≥ 3× body).

**Эталон** BTC 12h 2026-04-14 15:00 MSK TOP RB: upper/lower=4.94×, upper/body=6.78×, zone=[74376.52, 76038.00].

**Baseline стратегия** mean-reversion (entry=mid wick, SL=high, TP=low):
- 12h BTC 6y: 608 trades, WR 37.54%, avgRR 1.87, ΣR +37.0

**Entry α-sweep** ([0.05, 0.95]): максимум ΣR = +50.4 при α=0.7 (deep entry). Финальное решение: **α=0.5 оставлен как canon** (геометрический mid простой и понятный).

### IV.3. Справочник `zone_of_interest.md`

Главный лукап для термина «зона интереса». Принцип: **только геометрия зоны, без entry/SL/TP/strategy/backtest stats** (setup-материалы живут в `definition.md` каждого элемента).

8 пунктов (OB, Блок ордеров, RB, ob_liq, марубозу TODO, FVG, FH/FL, RDRB) + раздел «Принципы именования зон».

## V. Анализ разворота 2026-05-23 @ 74289.60 (multi-TF HTF confluence)

Цена развернулась на 23-05 09:00 MSK low 74289.60. Скан зон поддержки на всех TF (1h → 1w):

**Поточечный confluence (1h–6h):**
- 2h RDRB LONG V2 [74277, 74346] — внутри
- 1h RDRB LONG V1 liq [74280, 74305] — внутри
- 1h RB BOTTOM [74174, 74322] — внутри
- 6h RDRB LONG V1 liq [74202, 74451] — внутри (HTF)
- Multiple 3h/4h/6h block_orders LONG drop areas

**HTF supercluster (12h–1w):**
- **1w RDRB LONG V1 liq [73801.79, 74937.52]** (zafiksирован 2026-04-13)
- **1w FVG bullish [73620.12, 80216.01]** untouched с 2024-10-28 (1.5 года!)
- **2d FVG bullish [69500, 74416]** untouched с 2024-11-03
- **1d FVG bullish [70577.91, 74416]** untouched с 2024-11-05
- 1d/2d RB BOTTOM 2026-04-16, 2026-04-19
- 1d/2d block_orders LONG zones (April 2026)

**74289.60 = weekly liq внутри weekly RDRB POI внутри 1.5-летнего untouched 1w/2d FVG.** Идеальная HTF reaction-точка. После отскока цена за ~28 часов поднялась до 77543 (+4.4%).

## VI. Текущее состояние 2026-05-24 15:40 MSK — SHORT cluster выше

Данные обновлены через `~/smc-lib/scripts/update_btc_1m_csv.py --apply` (+1275 1m свечей).

**Текущая цена: 77086.64**. Кластер SHORT-зон прямо над:
- 2h/3h/4h FVG bearish все на 77093.72 (Δ +7!)
- 2d RDRB short V2 [77140, 77437]
- 6h RDRB short V1 [77154, 78430]
- 4h block_orders SHORT [77189, 78200]
- 1h RB TOP [77198, 77372]

Untouched FH на 1h/2h/3h: 77543.15 (только что сделан) / 77584.94 (22-05).

**Оценка SHORT-разворота на 1-3 дня: 75-85%** (сценарий A reversal с текущих + сценарий B sweep FH до 77543/77584 → reversal).

## VII. VWAPs ASVK — introduction

Начали изучение индикатора VWAPs ASVK.

### VII.1. Найден D-фрактал 2026-03-22 = FL @ 67360.66

5-bar Williams N=2 на D-чарте. Low 67360.66 — единственный кандидат, окружён выше с обеих сторон (D 20-03 / 21-03 слева, 23-03 / 24-03 справа).

### VII.2. 4h-фрактал 2026-03-22 23:00 MSK = FL @ 67360.66 (тот же уровень)

Low дня сидит именно в 4h-свече 23:00 MSK. **D- и 4h-фракталы указывают на один и тот же уровень**.

### VII.3. Окно работы — 20×1h внутри 4h-фрактала

Период 2026-03-22 15:00 MSK → 2026-03-23 10:00 MSK (20 1h-свечей внутри 5-bar 4h-фрактала). High 69005.71 (18:00 MSK 22-03 #4), Low 67360.66 (00:00 MSK 23-03 #10).

### VII.4. Оптимальный VWAP anchor — 2026-03-23 09:40 MSK (1m fine sweep)

Anchor выставляется в окне 20h, оценивается forward на ВСЕХ 1500+ 1h-свечах до текущего времени (2 месяца).

**Two sweet spots на 1m granularity:**
- **23-03 09:40 MSK** (победитель): touches 39, rebounds 25 (64.1%), broken+held 12, **score +26**
- 22-03 19:14-19:18 MSK: touches 45, rebounds 26 (57.8%), score +22

Чем 1h-aligned anchor 22-03 20:00 MSK хуже: score +20, rebound rate 56.8%.

**Замечательное совпадение**: VWAP@now (23-03 09:40 anchor) = **74505.18**. Reversal low 23-05 = **74289.60**. Разница 215 поинтов. VWAP, поставленный 2 месяца назад в окне 4h-фрактала, физически выступил магнитом разворота 23-го.

**Текущее**: close 77086 vs VWAP 74505 — Δ +2581. Цена в SHORT-кластере, потенциальный retest VWAP = drop ~3.4%.

### VII.5. Проверка: VWAP от случайных FH/FL — НЕ работает

Тест на свежих 4h FH (24-04 78479) и FL (23-04 76960):
- FH-anchor: score **−2** (!), rebound rate 37.1%
- FL-anchor: score +2, rebound rate 46.2%

**Вывод**: anchor для VWAP должен быть на point of significance (большой fractal, sweep event, HTF zone touch), не на случайной фрактальной точке. Anchor 23-03 09:40 работает потому, что попадает в окно major HTF drop к FL 67360 + start of 2-month bull rally.

## Открытые задачи

1. **Продолжение VWAPs ASVK** — изучение дальше (multi-anchor stacking, dynamic re-anchor?)
2. **SHORT-side feature mining** для i-RDRB+FVG (всё из LONG-side, для SHORT 389 trades)
3. **Композит R/ATR ∩ EVoT ∩ VWAP-FL** — узкий sniper-setup на i-RDRB+FVG
4. **Walk-forward / OOS** split 2020-2023 vs 2024-2026
5. **Свеча марубозу** — порог тела для зоны интереса в `zone_of_interest.md` (TODO #5)
6. **`fractal/` primitive** в smc-lib (Williams N=2)
7. **`maxv/` primitive** в smc-lib (LTF=1m canon из [[12h-fractal-prediction-final-strategy]])

## Артефакты

### Код (`~/smc-lib/`)

- `elements/ob/` — definition.md (4 варианта зон), code.py, 10 тестов
- `elements/ob_liq/` — definition.md, code.py, 6 тестов
- `elements/i_rdrb_fvg/` — definition.md, code.py, 5 тестов
- `elements/block_orders/` — definition.md, code.py, **13 тестов** (включая edge cases)
- `elements/rb/` — definition.md, code.py, 11 тестов + baseline backtest
- `zone_of_interest.md` — справочник 8 пунктов, очищен от setup-данных

### Графики (`~/Desktop/ob-charts/`)

- `rb_2026_04_14_btc_12h.png` — эталон TOP RB
- `rb_2026_05_08_bottom_btc_12h.png` — BOTTOM RB пример
- `rb_2026_04_14_top_alpha07.png`, `rb_2026_05_08_bottom_alpha07.png` — α=0.7 варианты
- `block_orders_2026_05_05_long_btc_1h.png` — зона интереса с breaker block
- `rdrb_2026_05_22_short_v1_btc_1h.png` — POI / block / liq визуализация
- `ob_long_2026_05_23_btc_12h.png`, `ob_short_2026_05_20_btc_12h.png` — OB pair zones
- `vwap_anchored_2026_03_22_20msk.png` — initial 1h-aligned anchor
- `vwap_anchored_2026_03_23_0940msk.png` — final 1m fine anchor
- `vwap_from_4h_fh_fl.png` — illustration of bad anchor choice

### Forensic-скрипты (`~/smc-lib/scripts/`)

- `forensic_win_features_rr22.py` — 20+ features for WIN concentration
- `forensic_ict_ob_features_rr22.py` — ICT-aligned filters (OB mitigation, overlap, etc.)
- `forensic_pattern_as_vc_htf_sweep.py` — sweep filter test
- `sweep_rb_ratios_12h.py`, `sweep_rb_entry_position.py` — RB optimization

### Изменения в стороннем коде

- `~/traid-bot/fetch_tv_data.py` — теперь работает (SSL fix через certifi)
- `~/traid-bot/data/TOTALES_*.csv` — добавлены 4 TF
- `~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv` — догнан до 2026-05-24 15:40 MSK

## Connection summary

```
i-RDRB+FVG forensic (RR=2.2)
    ↓ obnaruzhila
ICT OB структура (C2 = bullish/bearish OB)
    ↓ poshli v
smc-lib элементы (ob, ob_liq, i_rdrb_fvg)
    ↓ rasshirilis' do
block_orders (HTF-OB N+M, multi-iteration rules)
    ↓ vyvelos
RB (1-candle rejection) + α-sweep
    ↓ pomoglo opredelit'
zone_of_interest.md справочник
    ↓ primenili k
анализ разворота 23-05 (multi-TF HTF confluence)
    ↓ podtverdilos'
текущий SHORT-setup на 77086 (1-3 days outlook)
    ↓ paralleln'no
VWAPs ASVK introduction → anchor 23-03 09:40 MSK
    ↓ verifikatsiia
VWAP@now (74505) ≈ reversal low (74289) — оba ukazyvayut na odnu zonu
```

## Ссылки

- [[smc-lib-as-canonical-source]] — оригинальная заметка про библиотеку
- [[i-rdrb-fvg-combined-d-block-edge-sl-01]] — Combined D upgrade
- [[2026-05-23-smc-lib-vwap-entry-experiments]] — предыдущая сессия (VWAP entry experiments)
- [[2026-05-24-i-rdrb-fvg-evot-vwap-features-sl-optim]] — параллельная сессия (feature mining)
- [[12h-fractal-prediction-final-strategy]] — 1.1.1 фрактал стратегия (для VWAP контекста)
- [[универсальные определения OB и FVG]] — vault canon, источник для smc-lib ob/
- [[что такое OB с явно выраженной зоной ликвидности]] — vault canon для ob_liq
- [[три класса зон ликвидность эффективность неэффективность]] — taxonomy
