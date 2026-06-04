---
tags: [session, bulkowski, pattern-detection, etap-172, ml-pivot]
date: 2026-06-03
strategy: ml-pivot-detection
---

# Bulkowski Encyclopedia 3rd Ed. → 12 reversal детекторов на BTC 12h → etap_172

Продолжение ML-ветки pivot detection (etap_160..171). Цель неизменна: **искать
точки разворота на ранних стадиях** (НЕ trade execution с RR), мин. 2-3 сигнала/мес.
Чистая методология (без lookahead, Purged K-Fold CV).

## Что сделано

### 1. Распарсили Bulkowski "Encyclopedia of Chart Patterns" 3rd Ed.

PDF в 2076 страниц (превысил 600-страничный лимит Read-tool). Разрезал через
`pypdf` на 4 части по ~520 страниц, запустил **4 параллельных агента** на извлечение
статистики:

| Часть | Главы | Найдено |
|---|---|---|
| 1 (pp.1-520) | Ch.1-21 | Big M, Big W, Broadening (3 variants), **BARR Bottom/Top**, **Cup with Handle** |
| 2 (pp.521-1040) | Ch.22-44 | Diamond Top/Bottom, **DB Eve&Eve**, H&S Top/Bottom (+complex), Horn Top/Bottom |
| 3 (pp.1041-1560) | Ch.45-66 | Island, **Pipe Top/Bottom**, Rectangle, **Rounding Top/Bottom**, Scallops, Three Falling Peaks, Triangles |
| 4 (pp.1561-2076) | Ch.67-75 + Stats Summary + Glossary + Index | Triple Top/Bottom, V-Top/Bottom, Wedges + **Top-10 master tables** + **busted patterns methodology** |

Файлы:
- `d:/Users/Andrew/Downloads/bulkowski_split/bulkowski_part{1..4}_*.pdf`
- Консолидированный референс: [bulkowski_master_stats.md](../../research/elements_study/refs/bulkowski_master_stats.md)

### 2. Top-10 master tables (Statistics Summary, p.~1561)

**Bull market UP breakout (longs):** Rounding Bottom (4.3% fail / +47.8%), Cup with Handle (5.3% / +53.6%), H&S Bottom Complex (6.6% / +47%), Rounding Top up (8.9% / +54.6%), **Big W** (9.3% / +46.1%), **BARR Bottom** (9.4% / +55.1%).

**Bull market DOWN breakout (shorts):** **BARR Top** (13.6% / -17.2%), **Big M** (14.3% / -16.6%), **Diamond Top** (15% / -17.2%), V-Top Extended, Diamond Bottom down, H&S Top Complex, **H&S Top** (18.8% / -16.1%).

**Busted edge** (паттерн обанкротился → разворот в противоположную сторону):
- H&S Top single-bust → **+67%** (top edge)
- Triple Top → +60%, DT Eve&Eve → +54%, Rect Bottom busted → +68%

### 3. Выбрали top-12 для BTC 12h ML

См. [[bulkowski-top-12-patterns-for-btc-12h]].

**Long (7):** BARR Bottom, Rounding Bottom, Cup with Handle, Big W, DB Eve&Eve, H&S Bottom, V-Bottom.
**Short (6):** BARR Top, Big M, H&S Top, Diamond Top, V-Top, Triple Top.

### 4. Реализовали 13 детекторов в etap_172

См. [[bulkowski-reversal-detectors-btc-12h-baseline]].

Файл: [etap_172_bulkowski_patterns.py](../../research/elements_study/etap_172_bulkowski_patterns.py).

Каждый детектор — чистая функция `detect_<name>(df, i, lookback)` → `dict | None`.
Все компоненты (peaks/valleys) confirmed по фракталу N=2 → нет lookahead'а
([[multi-bar-pattern-confirm-vs-trigger-lookahead]]).

Breakout = `close[i]` пересекает confirmation line **впервые** (фильтр `close[i-1]`).

### 5. Прогнали Bulkowski-style backtest на BTC 12h

Период: 2020-01-01 → 2024-12-31 (TRAIN), 2025-01-01 → 2026-05-30 (OOS).

**Ultimate extreme** определён как у Bulkowski: максимум favor до 20% контр-движения.

**Результаты TRAIN (520 сигналов от 11 детекторов):**

| Паттерн | n | fail% | avg_mov% | bust% | half_tgt% |
|---|---|---|---|---|---|
| hs_bottom (long) | 30 | **13.3** | **+31.62** | 60 | 83 |
| big_w (long) | 89 | 16.9 | +29.83 | 52 | **90** |
| db_eve_eve (long) | 49 | 16.3 | +29.62 | 53 | 90 |
| v_bottom (long) | 42 | 14.3 | +26.62 | 45 | 83 |
| barr_bottom (long) | 7 | 28.6 | +27.32 | 29 | 71 |
| diamond_top (short) | 19 | 26.3 | +25.54 | 32 | 68 |
| v_top (short) | 23 | 17.4 | +20.18 | 52 | 78 |
| hs_top (short) | 30 | 13.3 | +18.35 | 53 | 87 |
| barr_top (short) | 13 | 23.1 | +17.95 | 39 | 54 |
| big_m (short) | 87 | 20.7 | +16.04 | 59 | **90** |
| triple_top (short) | 23 | 26.1 | +15.51 | 52 | 74 |

**Top-5 по комбинированному edge (объём × precision × move):**
1. **big_w** (89, +29.8%, 17% fail) — король по объёму
2. **db_eve_eve** (49, +29.6%, 16% fail)
3. **v_bottom** (42, +26.6%, 14% fail) — best fail rate
4. **hs_bottom** (30, +31.6%, 13% fail) — best avg move
5. **big_m** (87, +16%, 21% fail) — единственный short с массой

**OOS findings**: на bullish 2025 году short'ы (hs_top, big_m) показали bust 76-88% — busted-multi-bust сценарий характерен для трендового рынка.

CSV: [etap_172_stats.csv](../../research/elements_study/output/etap_172_stats.csv), [etap_172_signals.csv](../../research/elements_study/output/etap_172_signals.csv).

### 6. Закрыли вопрос про "250 сетапов до книг"

Раскопал прогрессию количества сигналов через все этапы:

| Версия | Что добавлено | thr=0.3 | thr=0.5 | thr=0.6 | thr=0.7 |
|---|---|---|---|---|---|
| etap_163 baseline | индикаторы + зоны | **252** | 126 | 79 | 57 |
| etap_165 | +USDT.D + sweep history | 319 | 199 | 159 | 122 |
| etap_167 | +zone strength | 326 | 215 | 154 | 100 |
| etap_170 | +Lopez Purged CV | 306 | 188 | 148 | 101 |
| etap_171 | +VSA + Nison | **316** | 194 | 151 | 107 |

**Главный эффект книг**: модель стала разборчивее **без потери объёма**. На равных
порогах кол-во сигналов растёт; precision (long) при thr=0.6 поднялся с 53% → 62%.
Lopez (etap_170) намеренно срезал часть (215→188 на thr=0.5) — это Purged CV +
sample weights отсеивают переобученные предсказания.

### 7. Обновили данные до текущего момента

BTC 1h/1d/12h докачаны до 2026-06-03 16:00 UTC (было 2026-05-30). USDT.D — свежий.

**Pitfall**: `requests` падал с `Missing dependencies for SOCKS support`. Лечится
явным сбросом `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` env vars в subprocess. См.
[[known-pitfalls]].

## Главные технические решения

- **PDF chunking strategy**: для книг >600 страниц режем через `pypdf` на части
  ≤520 страниц, потом параллельные агенты на каждую. 2076 стр → 4 части → 4 агента → ~5 минут на полное извлечение.
- **Bulkowski's "ultimate" metric перенесён как есть**: 20% counter-move от пика
  определяет ultimate high/low. На крипте 12h работает adequately, но bust rate
  выше (50-60%) чем в книге (15-30%) — крипта более whipsaw-склонна.
- **etap_172 — pure detection layer**: НЕТ trade logic (SL/TP/RR), НЕТ
  межпаттерных фильтров. Один бар может породить несколько сигналов одновременно
  (big_w + hs_bottom на одной свече). Логика комбинирования — это ML-задача etap_173.

## Открытые задачи

1. **etap_173 — добавить top-5 паттернов как фичи в etap_171** (270 → 285 фичей).
   Сравнить AUC + precision@P≥0.7. Каждый паттерн закодировать как 3 фичи:
   `pattern_fired_<name>` (binary), `bars_since_<name>` (decay), `height_pct_<name>`.
2. **Loose thresholds для rounding_bottom и cup_handle** — на BTC 12h они не находятся
   (слишком строгие R²). Попробовать R² ≥ 0.40 (вместо 0.55) и расширить lookback до 80.
3. **Busted-flag фичи**: для top-shorts (hs_top, big_m, triple_top) добавить флаг
   "паттерн обанкротился → паттерн → reverse-long вероятен". На OOS busted rate 76-88%
   намекает на сильный contra-edge.
4. **Перезапуск etap_172 на свежих данных** (2026-06-03) — должно добавиться
   ~7 новых 12h-свечей, возможно новые сигналы для OOS.

## Pitfalls новые (минор)

1. **`reset_index` после `compose_from_base` теряет имя колонки** — индекс может быть
   безымянным, `df['time']` падает. Лечится: `rename(columns={df.columns[0]: 'time'})`.
2. **SOCKS proxy блокирует Binance API requests** — нужен явный `NO_PROXY=*` +
   `os.environ.pop('HTTP_PROXY', ...)` перед `update_df_incrementally`.

## Артефакты

- `research/elements_study/refs/bulkowski_master_stats.md` — консолидированная
  справка по 75 паттернам книги
- `research/elements_study/etap_172_bulkowski_patterns.py` — 13 детекторов +
  Bulkowski-style backtest
- `research/elements_study/output/etap_172_stats.csv` — статистика per-pattern × period
- `research/elements_study/output/etap_172_signals.csv` — 520 raw сигналов с outcomes
- `research/elements_study/output/etap_172_run.log`
- `d:/Users/Andrew/Downloads/bulkowski_split/bulkowski_part{1..4}_*.pdf` — splits

## Связанные заметки

- [[bulkowski-top-12-patterns-for-btc-12h]] — почему именно эти 12 паттернов
- [[bulkowski-reversal-detectors-btc-12h-baseline]] — спецификация etap_172 baseline
- [[multi-bar-pattern-confirm-vs-trigger-lookahead]] — pitfall, который соблюдён в детекторах
- [[htf-lookup-must-use-last-closed-bar-not-forming]] — pitfall lookahead'а HTF
- Предыдущие сессии серии: etap_171 VSA+Nison, etap_170 Lopez, etap_168 Murphy
