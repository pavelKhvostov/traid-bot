---
tags: [research, refactoring, plan]
date: 2026-05-04
status: phase-2-output
---

# Proposed structure — research-стенд 1.1.x

Phase 2 output. **Никаких изменений на диске** — только план для утверждения.

---

## 2.1. Целевая структура

```
research/
├── _shared/
│   └── backtest_year.py            # обёртка для прогона любого бэктеста по году
├── 1_1_1/
│   ├── backtest/                   # 2 файла
│   ├── optimize/                   # 6 файлов
│   ├── analyze/                    # 5 файлов
│   └── README.md
├── 1_1_2/
│   ├── backtest/                   # 2 файла (incl. _extended)
│   ├── optimize/                   # 6 файлов
│   ├── analyze/                    # 5 файлов
│   ├── export/                     # 1 файл
│   └── README.md
├── 1_1_3/
│   ├── backtest/                   # 1 файл
│   ├── optimize/                   # 7 файлов (v1/v2/new_geometry)
│   ├── compare/                    # 1 файл
│   └── README.md
├── 1_1_4/                          # WIP — только backtest
│   ├── backtest/                   # 1 файл
│   └── README.md (status: WIP)
├── 1_2_0/                          # новая ветка (EMA + sweep)
│   ├── backtest/                   # 1 файл
│   ├── tune/                       # 1 файл
│   └── README.md
├── rdrb/                           # 5 RDRB-вариантов
│   ├── backtest/                   # 5 файлов
│   ├── analyze/                    # 2 файла
│   ├── optimize/                   # 1 файл
│   └── README.md
└── vic/                            # вне scope текущего рефакторинга, но переезжает
    ├── backtest/                   # 2 файла
    ├── optimize/                   # 2 файла
    └── README.md (status: out-of-scope)
```

**Не трогаем (остаются в корне):**
- `strategies/`, `tests/`, `data/`, `signals/`, `state/`, `vault/`, `.planning/`
- Live-инфра: `main.py`, `scanner.py`, `vic_scanner.py`, `telegram_bot.py`, `data_manager.py`, `config.py`, `state.py`, `vic_levels.py`
- Live-обвязка для 1.1.1: `strategy_1_1_1_confluence.py`, `strategy_1_1_1_scanner.py`
- Admin/data utilities: `admin_delete_last.py`, `fetch_tv_data.py`, `fetch_eth_sol_history.py`
- Manual reports: `generate_report.py`, `generate_dashboard.py`, `today_signals.py`, `full_backtest_new.py`
- Конфиг: `requirements.txt`, `README.md`, `CLAUDE.md`, `.env`, `.gitignore`

---

## 2.2. Полная таблица перемещений (49 файлов)

### research/_shared/ (1 файл)

| Было | Станет |
|---|---|
| `backtest_year.py` | `research/_shared/backtest_year.py` |

### research/1_1_1/ (13 файлов)

| Было | Станет |
|---|---|
| `backtest_strategy_1_1_1.py` | `research/1_1_1/backtest/backtest_strategy_1_1_1.py` |
| `backtest_1_1_1_sl_on_htf.py` | `research/1_1_1/backtest/backtest_1_1_1_sl_on_htf.py` |
| `optimize_strategy_1_1_1.py` | `research/1_1_1/optimize/optimize_strategy_1_1_1.py` |
| `optimize_strategy_1_1_1_rr.py` | `research/1_1_1/optimize/optimize_strategy_1_1_1_rr.py` |
| `optimize_1_1_1_3stage.py` | `research/1_1_1/optimize/optimize_1_1_1_3stage.py` |
| `optimize_1_1_1_swept_stage1.py` | `research/1_1_1/optimize/optimize_1_1_1_swept_stage1.py` |
| `optimize_1_1_1_swept_stage2.py` | `research/1_1_1/optimize/optimize_1_1_1_swept_stage2.py` |
| `optimize_1_1_1_swept_stage3.py` | `research/1_1_1/optimize/optimize_1_1_1_swept_stage3.py` |
| `analyze_1_1_1_confluence_macro.py` | `research/1_1_1/analyze/analyze_1_1_1_confluence_macro.py` |
| `analyze_1_1_1_ob_swept.py` | `research/1_1_1/analyze/analyze_1_1_1_ob_swept.py` |
| `analyze_1_1_1_swept_monthly.py` | `research/1_1_1/analyze/analyze_1_1_1_swept_monthly.py` |
| `analyze_1_1_1_swept_multi_asset.py` | `research/1_1_1/analyze/analyze_1_1_1_swept_multi_asset.py` |
| `analyze_1_1_1_sync.py` | `research/1_1_1/analyze/analyze_1_1_1_sync.py` |

### research/1_1_2/ (14 файлов)

| Было | Станет |
|---|---|
| `backtest_strategy_1_1_2.py` | `research/1_1_2/backtest/backtest_strategy_1_1_2.py` |
| `backtest_strategy_1_1_2_extended.py` | `research/1_1_2/backtest/backtest_strategy_1_1_2_extended.py` |
| `optimize_1_1_2_stage1_compare.py` | `research/1_1_2/optimize/optimize_1_1_2_stage1_compare.py` |
| `optimize_1_1_2_stage2.py` | `research/1_1_2/optimize/optimize_1_1_2_stage2.py` |
| `optimize_1_1_2_stage2_swept.py` | `research/1_1_2/optimize/optimize_1_1_2_stage2_swept.py` |
| `optimize_1_1_2_stage3.py` | `research/1_1_2/optimize/optimize_1_1_2_stage3.py` |
| `optimize_1_1_2_stages.py` | `research/1_1_2/optimize/optimize_1_1_2_stages.py` |
| `optimize_1_1_2_swept_stage1.py` | `research/1_1_2/optimize/optimize_1_1_2_swept_stage1.py` |
| `analyze_1_1_2_all_monthly.py` | `research/1_1_2/analyze/analyze_1_1_2_all_monthly.py` |
| `analyze_1_1_2_extended_final.py` | `research/1_1_2/analyze/analyze_1_1_2_extended_final.py` |
| `analyze_1_1_2_extended_sensitivity.py` | `research/1_1_2/analyze/analyze_1_1_2_extended_sensitivity.py` |
| `analyze_1_1_2_no_entry.py` | `research/1_1_2/analyze/analyze_1_1_2_no_entry.py` |
| `analyze_1_1_2_ob_swept.py` | `research/1_1_2/analyze/analyze_1_1_2_ob_swept.py` |
| `export_1_1_2_extended_positions.py` | `research/1_1_2/export/export_1_1_2_extended_positions.py` |

### research/1_1_3/ (9 файлов)

| Было | Станет |
|---|---|
| `backtest_strategy_1_1_3.py` | `research/1_1_3/backtest/backtest_strategy_1_1_3.py` |
| `optimize_1_1_3_new_geometry.py` | `research/1_1_3/optimize/optimize_1_1_3_new_geometry.py` |
| `optimize_1_1_3_stage1_compare.py` | `research/1_1_3/optimize/optimize_1_1_3_stage1_compare.py` |
| `optimize_1_1_3_v1_stage1_clean.py` | `research/1_1_3/optimize/optimize_1_1_3_v1_stage1_clean.py` |
| `optimize_1_1_3_v1_stage2_compare_ep.py` | `research/1_1_3/optimize/optimize_1_1_3_v1_stage2_compare_ep.py` |
| `optimize_1_1_3_v1_stage2_extended_entry.py` | `research/1_1_3/optimize/optimize_1_1_3_v1_stage2_extended_entry.py` |
| `optimize_1_1_3_v1_stage3_compare_ep.py` | `research/1_1_3/optimize/optimize_1_1_3_v1_stage3_compare_ep.py` |
| `optimize_1_1_3_v2_stage2.py` | `research/1_1_3/optimize/optimize_1_1_3_v2_stage2.py` |
| `compare_1_1_3_fvg_variants.py` | `research/1_1_3/compare/compare_1_1_3_fvg_variants.py` |

### research/1_1_4/ (1 файл, status: WIP)

| Было | Станет |
|---|---|
| `backtest_strategy_1_1_4.py` | `research/1_1_4/backtest/backtest_strategy_1_1_4.py` |

### research/1_2_0/ (2 файла)

| Было | Станет |
|---|---|
| `backtest_strategy_1_2_0.py` | `research/1_2_0/backtest/backtest_strategy_1_2_0.py` |
| `tune_strategy_1_2_0.py` | `research/1_2_0/tune/tune_strategy_1_2_0.py` |

### research/rdrb/ (8 файлов)

| Было | Станет |
|---|---|
| `backtest_strategy_rdrb.py` | `research/rdrb/backtest/backtest_strategy_rdrb.py` |
| `backtest_strategy_rdrb_premium.py` | `research/rdrb/backtest/backtest_strategy_rdrb_premium.py` |
| `backtest_strategy_rdrb_trend.py` | `research/rdrb/backtest/backtest_strategy_rdrb_trend.py` |
| `backtest_strategy_rdrb_wick.py` | `research/rdrb/backtest/backtest_strategy_rdrb_wick.py` |
| `backtest_rdrb_konfetka.py` | `research/rdrb/backtest/backtest_rdrb_konfetka.py` |
| `analyze_rdrb_confluence_macro.py` | `research/rdrb/analyze/analyze_rdrb_confluence_macro.py` |
| `analyze_rdrb_winners_losers.py` | `research/rdrb/analyze/analyze_rdrb_winners_losers.py` |
| `optimize_rdrb_entry_sl.py` | `research/rdrb/optimize/optimize_rdrb_entry_sl.py` |

### research/vic/ (4 файла, out-of-scope но переезжает)

| Было | Станет |
|---|---|
| `backtest_vic_bos.py` | `research/vic/backtest/backtest_vic_bos.py` |
| `backtest_vic_evot.py` | `research/vic/backtest/backtest_vic_evot.py` |
| `optimize_vic_entry_sl.py` | `research/vic/optimize/optimize_vic_entry_sl.py` |
| `optimize_vic_yearly.py` | `research/vic/optimize/optimize_vic_yearly.py` |

**ИТОГО: 49 файлов** (1 shared + 13 + 14 + 9 + 1 + 2 + 8 + 4).

---

## 2.3. Импорты после `git mv` — что и как чинить

### Проблема: 49 скриптов импортируют из корня

- 47 импортируют `from data_manager import ...`
- 44 импортируют `from strategies.<strategy_X> import ...`
- 5 cross-research импортов **внутри 1.1.1** (`from backtest_strategy_1_1_1 import dedupe_signals/simulate_outcome/to_utc3`)
- 1 cross-research **trace_2604 → backtest_vic_bos** (но trace_2604 — кандидат на удаление)

### Имя папок начинается с цифры — Python-пакетная схема не подходит

`research.1_1_1.backtest` — невалидный идентификатор. Если хочется package-mode — нужно префикс (например `v1_1_1`). Я предлагаю **другой путь**.

### Предлагаю: `sys.path` injection в каждом перемещённом скрипте

В начало каждого `.py` добавляется (между `__future__` и остальными импортами):

```python
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[3]   # research/<v>/<sub>/file.py → repo root
sys.path.insert(0, str(_ROOT))
```

Для `research/_shared/X.py` parents=2.

После этого все `from data_manager import ...`, `from strategies.X import ...` продолжают работать.

### Cross-research импорты внутри 1.1.1

5 файлов делают `from backtest_strategy_1_1_1 import simulate_outcome/dedupe_signals`. После git mv `backtest_strategy_1_1_1.py` → `research/1_1_1/backtest/`, нужно дополнительно:

```python
sys.path.insert(0, str(_ROOT / "research" / "1_1_1" / "backtest"))
```

Это добавляется в:
- `research/1_1_1/backtest/backtest_1_1_1_sl_on_htf.py`
- `research/1_1_1/optimize/optimize_strategy_1_1_1_rr.py`
- `research/1_1_1/analyze/analyze_1_1_1_confluence_macro.py`
- `research/1_1_1/analyze/analyze_1_1_1_ob_swept.py`
- `research/1_1_1/analyze/analyze_1_1_1_sync.py`

Запуск из корня: `./venv/bin/python research/1_1_1/backtest/backtest_strategy_1_1_1.py` — работает без `cd`, без `python -m`.

**Альтернатива (если хочется чище):** переименовать папки `1_1_1/` → `v1_1_1/` (и т.д.), создать `__init__.py` в каждой, использовать `python -m research.v1_1_1.backtest.backtest_strategy_1_1_1`. Это чище, но требует доп. изменения способа запуска. Жду твоё мнение.

---

## 2.4. Кандидаты на удаление (НЕ удаляем в этой фазе)

Эти файлы вернулись после переименования папки `trading-signals-bot` → `traid-bot` (cleanup-коммит `chore/cleanup-2026-05-01` не был смерджен). Все они подтверждены как мусор в прошлой сессии:

| Файл | Причина | Размер |
|---|---|---:|
| `smoke_test.py` | старый смоук-тест (apr 23), нет импортов | 2 KB |
| `smoke_test_fvg.py` | то же | 2 KB |
| `smoke_test_obx4.py` | то же | 2 KB |
| `full_backtest_obx4.py` | старый бэктест OBX4, нет импортов | 4 KB |
| `dump_ob_d_fvg_4h.py` | одноразовый дамп OB-D + FVG-4h, нет импортов | 3 KB |
| `trace_2604.py` | отладка конкретной даты, нет импортов | 2 KB |
| `trace_jan1.py` | отладка конкретной даты, нет импортов | 5 KB |
| `REVIEW.md` | code review snapshot 2026-04-24, устарел после мерджа Андрея | 14 KB |

**Делать в отдельной фазе** (не в Phase 3) — это очистка корня, не перемещение research.

---

## 2.5. Кандидаты на объединение (НЕ объединяем сейчас)

### 1.1.2 — analyze extended (2 файла → 1)

`analyze_1_1_2_extended_final.py` и `analyze_1_1_2_extended_sensitivity.py` — оба про extended-вариант. Можно слить в один с argparse `--mode={final,sensitivity}`. **Не делаем**, только список.

### 1.1.3 — v1 серия (4 файла → 1)

`optimize_1_1_3_v1_stage1_clean.py`, `_v1_stage2_compare_ep.py`, `_v1_stage2_extended_entry.py`, `_v1_stage3_compare_ep.py` — серия экспериментов с одной геометрией v1, разные stage'ы. Может быть слита в `optimize_1_1_3_v1_stages.py` с argparse `--stage={1,2,2_ext,3}`. **Не делаем**.

### 1.1.2 — optimize stages (5 файлов → возможно сжать)

`optimize_1_1_2_stage1_compare.py`, `_stage2.py`, `_stage2_swept.py`, `_stage3.py`, `_stages.py`, `_swept_stage1.py` — 6 скриптов с overlapping логикой. Без чтения всех — гипотеза что можно объединить в 2 (по модам ALL и SWEPT). **Не делаем**, требует анализа.

### НЕ объединять

- 5 RDRB-вариантов (`base/premium/trend/wick/konfetka`) — это **разные стратегии**, не дубли. Каждая — отдельный эксперимент с разной логикой фильтров.
- Stage1/2/3 для 1.1.1 — три разных этапа оптимизации, последовательно зависят. Объединение усложнит чтение.

---

## 2.6. План для Phase 3

**Один коммит = одно перемещение** (Pavel требование).

1. Создать пустые папки + `.gitkeep` (1 коммит).
2. По одному файлу: `git mv X` → правка sys.path в перемещённом файле → коммит `move(<group>): X.py → research/...`.
3. После всех 49 git mv — пробежать `python -m py_compile` на всём дереве (1 коммит для финальной правки если нужно).
4. README.md в каждой папке `research/<v>/` — одна сводка (1 коммит).

Итого ~52 коммита. Все легко-обратимы через `git revert`.

---

## Жду от Pavel'а

1. **Подтверждение целевой структуры** (раздел 2.1).
2. **Решение по импортам:** sys.path injection (мой выбор) vs `python -m research.v1_1_1...` (требует переименования папок и `__init__.py`)?
3. **Решение по кандидатам на удаление** (раздел 2.4) — делать сразу после Phase 4 или отдельной задачей позже?
4. **Решение по cutoff** для воспроизводимости в Phase 4 — захардкодить `cutoff = 2023-05-08T00:00Z` в скриптах (это отдельная не-stratlogic правка), или прогнать в тот же день?
