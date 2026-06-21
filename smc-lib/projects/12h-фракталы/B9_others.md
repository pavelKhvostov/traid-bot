# B9 — Others (catch-all)

Категория «прочее» — собирает примитивные сигналы, не вписывающиеся ни в одну из специализированных B1..B8 категорий зон/индикаторов.

В отличие от других B-блоков, B9 — это не семейство одного концепта, а **разнородная корзина** независимых сигналов. Каждый B9Cx — отдельный, концептуально не связанный с другими, но не достаточный для собственного B-слота.

## Sub-conditions

### B9C1 — P11_count (4-window OR-basket)

Был **C2** → B3 → B7 → **B9C1** (2026-06-06).

`P11_count` — **доля 15-минутных свечей за окно N×15min перед close pivot bar i**, направленных **ПРОТИВ** ожидаемого pivot direction. Когда «мини-структура» внутри pivot bar показывает экстремальный bias против разворота, это contrarian-сигнал на смену.

#### Формальное определение

Для pivot bar i (open at `pt`, close at `pt_end = pt + 12h`):

```
для каждого окна N ∈ {8, 12, 16, 24}:
    window_15m = 15m bars в интервале [pt_end - N*15m, pt_end]
    
    если direction = "high" (FH pivot):
        cnt = количество 15m баров с close < open    (bearish)
    если direction = "low" (FL pivot):
        cnt = количество 15m баров с close > open    (bullish)
    
    P11_{N}x15m = cnt / len(window_15m)
```

Окна и их временные эквиваленты:
- N=8  → 2 часа
- N=12 → 3 часа
- N=16 → 4 часа
- N=24 → 6 часов

#### OR-basket (4 порога)

```
B9C1 = (P11_8x15m  ≥ 0.65)  ∨
       (P11_12x15m ≥ 0.75)  ∨
       (P11_16x15m ≥ 0.65)  ∨
       (P11_24x15m ≥ 0.65)
```

Пороги подобраны эмпирически так, чтобы каждое standalone давало WR ≥ 70%. P11_12 требует более высокий порог (0.75) — узкое 3h окно более шумное.

**Per-window standalone стат (старое окно):**
| окно | threshold | n | WR |
|------|----------:|---:|----:|
| 8×15m (2h)  | ≥ 0.65 | 143 | 74.8% |
| 12×15m (3h) | ≥ 0.75 | 62  | 74.2% |
| 16×15m (4h) | ≥ 0.65 | 86  | 69.8% |
| 24×15m (6h) | ≥ 0.65 | 60  | 73.3% |

**Causality:** ✅ окно `[pt_end - N*15m, pt_end]` целиком внутри 12h бара i. Используются только bars ≤ close бара i.

**Цифры B9C1 (на A4-baseline 1356, canonical 2026-06-06):**
n = 203 · conf = 148 · **WR 72.91%** · Δ +24.31 pp

#### Канон / код
- Реализация: `~/smc-lib/scripts/pred12h_cond2_p11_union.py` (lines 31-36, 150-174)
- Basket builder: `~/smc-lib/scripts/pred12h_basket_c1c2c3.py`

## TODO

- Пересчитать B9C1 (с разбивкой по 4 окнам) на A4-baseline 1356 (окно 2020-01-01 → now)
- Causality-аудит ([[feedback-b-series-strict-causal-i]])
- Возможные B9C2+ (другие «прочие» сигналы, кандидаты):
  - **B9C2** — sweep equal highs / equal lows (EQH/EQL liquidity pool, классическая SMC) — *возможно вынести в Fractal Liquidity B3 вместо?*
  - **B9C3** — TimeOfDay / day-of-week фильтры (NY open, London close, weekend gap)
  - **B9C4** — funding rate divergence (если данные доступны)
  - **B9C5** — exchange flow / netflow данные
  - **B9C6** — другие micro-structure indicators (cumulative delta, order flow, etc.)
- При появлении нескольких связанных B9Cx — выделять в собственный B-блок (как B3 Fractal Liquidity получился из maxV)

## Связанные memories

- [[feedback-b-series-strict-causal-i]] — strict causality для B-серии
- [[project-12h-fractal-new-abc-structure]] — общая A/B/Basket структура
