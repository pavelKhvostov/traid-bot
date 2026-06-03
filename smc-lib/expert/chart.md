# Экспертный график

> **Назначение.** Канонический композит-чарт для экспертной оценки рыночной структуры BTC. Один кадр содержит: ценовое действие на 6h, потенциальные 12h-пивоты (Pred-12h basket), HMA-78/200 на двух TF, и набор эффективных/проработанных VWAP'ов вокруг текущей цены.
>
> **Статус.** ✅ Канон утверждён 2026-05-28. Эталон-скрипт: [`expert/chart.py`](./expert/chart.py).
>
> Когда пользователь говорит **«представить экспертный график»** или **«экспертный график»** — запускаем `python3 ~/smc-lib/expert/chart.py [ASSET]`, в результате получаем PNG в `~/Desktop/i-rdrb-charts/<asset>_6h_pred12h_basket_<date>.png`.

---

## Состав чарта

### 1. База (по [`chart_format.md`](../chart_format.md))

- 6h BTC, 60 дней до сегодня
- Bull `#01a648` / Bear `#131b1b`, wick = body color, linewidth 1.1, gap 0.5
- Y-шкала справа, шаг 1000 USDT
- X-ticks по понедельникам + сегодня (DD-MM)
- Сетка выкл, отступы симметричные, заголовок жирный 1 строкой
- Текущая цена: красная пунктирная линия + tick на шкале (`#c62828`)
- Сегодняшняя дата: красная плашка на X-оси
- Авто-докачка 1m через `fetch_btc_1m_missing.py`

### 2. Pred-12h basket overlay

- Для каждого потенциального 12h-pivot'а (F1∩F2∩F3 baseline за окно 60 дней + сегодня):
  - **SHORT** (FH high pivot) → ▼ красный (`#c62828`), filled, s=70, **над** high бара (с offset)
  - **LONG** (FL low pivot) → ▲ зелёный (`#2e7d32`), filled, s=70, **под** low бара (с offset)
- НЕ разделяем визуально baseline vs basket vs confirmed — все pivot'ы помечаются одинаково
- НЕ показываем C-флаги или Williams-status

### 3. TrendLine ASVK ([Правило 7](../rules.md#правило-7--trendline-asvk-канонические-length-78-и-200))

| Линия | Цвет | Стиль | TF | Длина |
|---|---|---|---|---|
| HMA-78 12h LIVE | `#4a90d9` (свето-синий) | ─ ─ ─ штриховая | 12h | 78 |
| HMA-200 12h LIVE | `#1a3f6f` (тёмно-синий) | ─ ─ ─ штриховая | 12h | 200 |
| HMA-78 D LIVE | `#4a90d9` | ── сплошная | D | 78 |
| HMA-200 D LIVE | `#1a3f6f` | ── сплошная | D | 200 |

- **Mode**: Hma (Hull MA), source = close
- **Value**: LIVE (HMA[i] = computed on close i-1, strict-causal)
- **Display**: линейная интерполяция между соседними закрытыми HTF-значениями (плавная линия)
- **Linewidth**: `0.8` (тонкая)
- **Z-order**: 1 (задний план)

### 4. VWAPs ASVK ([Правило 6](../rules.md#правило-6--построение-vwaps-asvk-anchored-dynamic-от-d-фрактала))

Anchor-окно: последние **180 дней** D-фракталов (Williams N=2). Method 1 (M1, anchor = pivot close).
Composite effectiveness cascade: `{1h, 2h, 4h, 6h, 8h, 12h}`.

| Категория | Сколько | Цвет | Логика отбора |
|---|---:|---|---|
| **Эффективный под ценой** | 2 | 🟠 `#ff7f0e` | top-2 по composite, фильтр `current_vwap < price` |
| **Эффективный над ценой** | 2 | 🔴 `#c62828` | top-2 по composite, фильтр `current_vwap > price` |
| **Проработанный под ценой** | 1 | 🟣 `#7e57c2` | max `total_interactions`, фильтр `current_vwap < price` |
| **Проработанный над ценой** | 1 | 🟣 `#7e57c2` | max `total_interactions`, фильтр `current_vwap > price` |

- **Линия**: linewidth `0.8`, alpha 0.9, zorder 1
- **Anchor marker** (▲ для FL, ▼ для FH) — если pivot в окне чарта
- **Левая подпись плашкой** (цвета линии, белый текст `SIDE DD-MM-YY`) — если anchor вне окна

### 5. Легенда (upper-left)

| Элемент |
|---|
| SHORT (FH pivot 12h) — ▼ красный |
| LONG (FL pivot 12h) — ▲ зелёный |
| HMA-78 12h LIVE — синий штриховой |
| HMA-200 12h LIVE — тёмно-синий штриховой |
| HMA-78 D LIVE — синий сплошной |
| HMA-200 D LIVE — тёмно-синий сплошной |
| VWAP эффективный — оранжевый |
| VWAP эффективный — красный |
| VWAP проработанный — фиолетовый |

---

## Терминология (канон)

| Имя | Что значит |
|---|---|
| **Эффективный VWAP** | high composite score = reactions/interactions; price respects this level |
| **Проработанный VWAP** | high total_interactions; price visits this level often (independent of outcome) |
| **VWAP под ценой** | `current_vwap < current_price` (action as support) |
| **VWAP над ценой** | `current_vwap > current_price` (action as resistance) |

---

## Артефакты

- **Эталон-скрипт**: [`expert/chart.py`](./expert/chart.py)
- **Output**: `~/Desktop/i-rdrb-charts/btc_6h_pred12h_basket_<YYYY-MM-DD>.png`
- **Зависимости**:
  - `chart_format.md` — базовый формат чарта
  - `rules.md` (Правило 6, 7) — каноны VWAP и HMA
  - `projects/pred12h-fractal-three-candles.md` — F1∩F2∩F3 + C1-C7 basket
  - `indicators/trend_line_asvk.py`, `indicators/vwap_effectiveness.py`
  - `elements/ob_liq/code.py`, `elements/fvg/code.py`, `elements/block_orders/code.py`

---

## Триггер: «представить экспертный график»

При запросе пользователя:
1. Запустить `python3 ~/smc-lib/expert/chart.py`
2. Дождаться сохранения PNG
3. Прочитать и предоставить путь
4. Краткий комментарий: уровни (VWAP support/resistance, ближайшие HMA), потенциальные fresh pivot'ы за последние 24h, текущая цена vs ключевые уровни

---

## История

- **2026-05-28** — канон утверждён, эталон-скрипт зафиксирован
