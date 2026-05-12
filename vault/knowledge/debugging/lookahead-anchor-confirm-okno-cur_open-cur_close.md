---
tags: [debugging, pitfall, lookahead, smc, backtest]
date: 2026-05-08
session: [[2026-05-08-elements-study-grid-search-production-setup]]
---

# Lookahead bug: anchor confirmed at cur_close, не cur_open

## Что было

В `research/elements_study/etap_14_full_grid.py` (и etap_15) при поиске
LTF-триггеров в зоне HTF-анкора использовалась `a["time"]` как начало окна:

```python
a_start = a["time"]   # = ob.cur_time = OPEN time of cur candle
a_end = a_start + a_life
```

Но `ob.cur_time` это **open_time** свечи cur. OB подтверждается ТОЛЬКО ПОСЛЕ
закрытия cur, то есть в `cur_time + tf_anchor`.

Триггеры, попадавшие в окно `(cur_open, cur_close)`, использовали
ещё-не-сформированный анкор — невидимый в реальном времени.

## Симптом

Grid search показал якобы выдающихся кандидатов:

| Setup | RR | WR (с bug) | WR (после фикса) |
|---|---|---|---|
| OB-6h × FVG-15m | 1.5 | 58.7%, +559R | **36.0%, −119R** |
| OB-12h × FVG-15m | 1.0 | 77.7%, +329R | 49.5%, −6R |
| OB-1d × FVG-15m | 2.0 | 67.4%, +285R | **26.1%, −65R** |

77% WR на 593 сделках за 6 лет — слишком красиво, чтобы быть правдой.
После фикса edge не просто ушёл — стал отрицательным. Внутри окна
формирования OB (6-24 часа) цена систематически идёт В сторону зоны
(сама механика «встречи цены с уровнем»), что давало искусственно
завышенный WR.

## Причина

Размер ущерба зависит от **(tf_anchor) × (tf_trigger)**:

| Anchor | Trigger | "Нелегальное" окно | Баров с лукахедом / анкор |
|---|---|---|---|
| OB-1d | FVG-15m | 24h | до 96 |
| OB-12h | FVG-15m | 12h | до 48 |
| OB-6h | FVG-15m | 6h | до 24 |
| OB-4h | FVG-1h | 4h | до 4 |

Старая production-кандидат (OB-4h × FVG-1h pro RR=1.0) изменилась
минимально: WR 54.4 → 56.2%, +93R → +103R. Маленькое окно × маленькое
число LTF-баров не давало систематического смещения.

Для FVG-15m триггера эффект был катастрофический — по сути все «топ»
результаты были артефактом.

## Правило избегания

При построении HTF×LTF setup'ов в backtest:

```python
a_tf_td = pd.Timedelta(anchor_tf)
a_start = a["time"] + a_tf_td   # cur_close — момент когда анкор виден
a_end = a["time"] + life        # life отсчитывается от cur_open (как в etap_13)
```

Эталон-pattern в `etap_13_ob_size_sweep.py:99-100`:
```python
ob_start = ob["ob_time"] + pd.Timedelta(hours=4)  # = cur_close для 4h
ob_end = ob["ob_time"] + pd.Timedelta(days=HTF_LIFE_DAYS)
```

**RED FLAG в коде:** `a_start = ...["time"]` без добавления `+ tf` —
проверять немедленно.

## Связь с уже-известными pitfall

Это частный случай:
- [[trigger_time равен open_time плюс tf]] — общий принцип
- [[главное правило ob только на последней закрытой 1h]] — live-аналог

Главное правило vault уже было сформулировано, но при написании нового
research-кода в этап 14 я его не применила. Урок — **перед каждым новым
backtest-скриптом перечитывать known-pitfalls целиком**, не только
«что-то релевантное».

## Источник

Сессия [[2026-05-08-elements-study-grid-search-production-setup]],
коммит fix в etap_14/etap_15 после grid v1.
