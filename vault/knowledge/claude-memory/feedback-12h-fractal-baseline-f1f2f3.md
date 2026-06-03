---
name: feedback-12h-fractal-baseline-f1f2f3
description: Для статистики 12h Pred-фракталов baseline = F1∩F2∩F3 (1266 / P=48.9% / 18/18 imp). Утверждено 2026-05-26. Не разворачивать таблицу от raw bars / pre-Williams.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3af6f0d9-c3ee-48ba-ae08-4c05d8c82af3
---

# Baseline для статистики 12h Pred-фракталов = F1∩F2∩F3

Утверждено пользователем 2026-05-26.

## Правило

Когда пользователь просит статистику по 12h Pred-фракталам — таблицу строить **начиная с F1∩F2∩F3**, а не с raw 12h bars / pre-Williams / F1 / F1∩F2.

Baseline в числах (6y BTC in-sample):
- **n = 1 266** (≈17.6 / мес)
- **conf (Williams-успешные) = 619** (≈8.6 / мес)
- **not conf (Williams-неуспешные) = 647** (≈9.0 / мес)
- **P(Williams) = 48.9%**
- **imp recall = 18/18** (все ground truth сохранены)

## Формат таблицы

Минимальная шапка:

| Конфигурация | n | conf | not conf | P(W) | Δ vs base | imp/18 |
|---|---:|---:|---:|---:|---:|---:|
| F1∩F2∩F3 (baseline) | 1 266 | 619 | 647 | 48.9% | — | 18/18 |

## Why

Пользователь явно зафиксировал F1∩F2∩F3 как «honest baseline без потерь recall». Стадии 0–3 (pre-Williams, F1, F1∩F2) — пройденный материал; их раскрытие в каждой следующей таблице создаёт шум.

## How to apply

- Первая строка любой статтаблицы по 12h фракталам: **F1∩F2∩F3 = 1 266 / 48.9% / 18/18**.
- Сравнения (Δ pp) считать от P=48.9%.
- Imp recall указывать как `imp/18` (а не `imp/16` — это было только для F4-подмножества).
- Стадии до F3 упоминать только если пользователь явно запросил «всю воронку с начала» или если обсуждается изменение в F1/F2/F3.

## Related

- [[12h-fractal-filter-f1-f2]] — полный канон цепочки F1∩F2∩F3 (definitions, why each step)
- [[vc-volume-confirmation-definition]] — VC, используется в F5
