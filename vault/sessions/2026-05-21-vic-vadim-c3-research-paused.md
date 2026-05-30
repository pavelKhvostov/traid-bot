---
tags: [session, vic-vadim, c3, paused]
date: 2026-05-21
status: paused
related: [[2026-05-21-vic-vadim-12h-fractal-finalize]], [[стратегия ViC Vadim 12h вариант 1]]
---

# 2026-05-21 (продолжение) — ViC Vadim 12h: исследование C3, пауза

Продолжение [[2026-05-21-vic-vadim-12h-fractal-finalize]]. После
финализации Core (C1 + C2) и cross-asset валидации на BTC+ETH, проведено
исследование третьего условия (C3) как дополнительного фильтра. Пользователь
поставил **паузу** до утверждения формы. SOL-fetch не завершён (сетевые
ошибки Binance).

## Что проверено по C3 (хронология)

### 1. ASVK Custom RSI ([[asvk-custom-rsi]]) — отклонён

См. `research/vic_vadim/predict_fractal_c3_asvk_rsi.py`. Проверены зоны
OB/OS на LTF {1h, 2h, 4h, 6h} поверх BTC Core.

- Лучшие direct: HH ∩ OB 4h = 91.67% (n=12), LL ∩ OB 1h = ? Не сработало
  ни одного case для прямой LL ∩ OS (баланс ETH тоже пострадал).
- Сюрпризно: **anti-сигналы сильнее direct** — LL ∩ ASVK OB (anti) 1h =
  92.31% (n=13).
- Совокупное сжатие до n=25 за 6y (-86% от Core 176). Sniper-Core уже
  даёт сравнимую precision при больших n.
- **Отклонено** 2026-05-21.

### 2. Money Hands ASVK ([[money-hands-asvk]]) — варианты, не утверждено

См. `predict_fractal_c3_money_hands.py` / `_eth.py`. Проверено 5 форм
(A1 узкая фаза, A2 широкая bw2<>SMA, A3 затухание, B уровень ±60, C
Money Flow) на LTF {1h, 2h, 4h, 6h}.

**BTC top:**
- HH ∩ MF<0 (4h) = **96.43%** (n=28)
- HH ∩ 🔴 A1 (1h) = 92.31% (n=39)
- LL ∩ 🟢 A1 (1h) = 88.10% (n=42)

**Cross-asset (ETH) показал что HH MF<0 (4h) — BTC-specific** (ETH 70%).

**Universal cross-asset best:**
- HH ∩ ⚪after🟢 A3 (4h) — BTC 93.33% / ETH 81.25% — Σ=31, ~87% средне
- LL ∩ 🟢 A1 (1h) — BTC 88.10% / ETH 83.87% — Σ=73, ~86% средне
- Combined Σ 104, ~86.5% precision (-65% от Core 296)

**Варианты использования:**
| Вариант | Σ n BTC+ETH | precision | Δ n |
|---------|-------------|-----------|-----|
| V0 без C3 (Core) | 296 | 77.0% | 0% |
| V1 (C3 LL only, A1🟢 1h) | 220 | 80.7% | -26% |
| V2 (A2 мягкий обе стороны) | 257 | 78.5% | -13% |
| V4 (жёсткий: HH A3 4h + LL A1 1h) | 104 | 86.3% | -65% |

### 3. ASVK Trend Line — Hull MA-78 ([[asvk-trend-line-hull]]) — варианты, не утверждено

См. `predict_fractal_c3_trendline.py` / `_eth.py`. Проверено направление
цвета Hull (close > SHULL → GREEN; иначе RED) на LTF {1h, 2h, 4h, 6h, 1d}.

**BTC top (direct):**
- HH ∩ Hull RED 1h = 85.53% (n=76, keep 90%) — минимальная потеря
- LL ∩ Hull GREEN 1h = 79.22% (n=77, keep 84%)
- HH ∩ Hull RED 1d = 85.71% (n=28) — узкое

**Cross-asset (ETH):**
- LL ∩ Hull GREEN 1h: BTC 79.2% / ETH 79.6% — **самый стабильный** ⭐
- HH ∩ Hull RED 1d: BTC 85.7% / ETH 80.8% — стабильный
- HH ∩ Hull RED 1h: BTC 85.5% / ETH 73.6% — BTC-specific

**Варианты Hull:**
| Вариант | Σ n BTC+ETH | precision | Δ n |
|---------|-------------|-----------|-----|
| Hull C (LL GREEN 1h only) | 273 | 79.1% | **-8%** ⭐ |
| Hull A (1h both) | 255 | 79.7% | -14% |
| Hull D (HH 1d + LL 1h) | 180 | 80.6% | -39% |
| Hull B (1d both) | 115 | 80.1% | -61% |

### 4. SOL — fetch не завершён

`research/vic_vadim/fetch_sol_1m.py` (с retry 8× exponential backoff)
несколько раз падает на Binance API timeouts/ChunkedEncodingError при
скачивании 3.18M баров 1m. Кэш `data/SOLUSDT_1m_vic_vadim.csv` не создан.

Скрипты SOL подготовлены (`optimize_mlt_sol.py`,
`predict_fractal_c3_money_hands_sol.py`,
`predict_fractal_c3_trendline_sol.py`) — заработают сразу после успешного
fetch.

## Сравнение всех C3-кандидатов

| C3-кандидат | Σ BTC+ETH n | средняя precision | Δ n vs Core |
|---|---|---|---|
| Без C3 (Core) | 296 | 77.0% | 0% |
| **Hull C (LL GREEN 1h only)** | **273** | **79.1%** | **-8%** ⭐ |
| Hull A (1h both) | 255 | 79.7% | -14% |
| Money Hands V2 (A2 мягкий) | 257 | 78.5% | -13% |
| Money Hands V1 (LL A1🟢 1h) | 220 | 80.7% | -26% |
| Hull D (1d HH + 1h LL) | 180 | 80.6% | -39% |
| Hull B (1d both) | 115 | 80.1% | -61% |
| Money Hands V4 (жёсткий) | 104 | 86.3% | -65% |
| ASVK RSI (жёсткий) | 25 BTC | 92.0% | -86% (отклонён) |

## Состояние стратегии

**Core (mlt=45, LTF=16m maxV)** утверждён ранее, не меняется. **C3 — в
исследовании, форма не выбрана.** Пользователь видит компромисс
precision↑/coverage↓ для разных вариантов.

## Открытые вопросы / задачи

1. **Утвердить форму C3** или окончательно отказаться (Core достаточен).
2. **SOL завершить fetch и прогнать** все C3-варианты для тройной cross-
   asset проверки. Возможны решения:
   - Использовать Binance Vision (архивные дампы)
   - Разбить fetch на меньшие порции с большими retries
   - Использовать другой источник
3. **Walk-forward / Entry-SL-TP** — на паузе до выбора C3.

## Артефакты добавлены в `research/vic_vadim/` (этой сессией)

- `predict_fractal_c3_asvk_rsi.py` — ASVK RSI (отклонён)
- `predict_fractal_c3_money_hands.py` / `_eth.py` / `_sol.py` (SOL pending)
- `predict_fractal_c3_trendline.py` / `_eth.py` / `_sol.py` (SOL pending)
- `optimize_mlt_sol.py` — SOL версия optimization (заготовка)
- `fetch_sol_1m.py` — fetch SOL 1m с retries (не завершён)

## Связи

- [[2026-05-21-vic-vadim-12h-fractal-finalize]] — основная сессия с
  Core-стратегией и BTC+ETH.
- [[стратегия ViC Vadim 12h вариант 1]] — strategy spec.
- [[asvk-custom-rsi]] / [[money-hands-asvk]] / [[asvk-trend-line-hull]] —
  индикаторные источники C3.
