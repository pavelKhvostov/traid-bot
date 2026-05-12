---
tags: [debugging, lookahead, backtest, multi-tf, htf]
date: 2026-05-08
related: [research/elements_study/etap_37_c2v2_audit_oos.py]
---

# HTF lookup в backtest: использовать last CLOSED bar, не forming bar

## Контекст

Когда в LTF-стратегии (например FVG-2h trigger) применяется фильтр на
HTF индикаторе (например Hull MA на 1d), нельзя смотреть значение
индикатора по `asof(signal_time)` без поправки на «закрытость» бара.

В live-режиме Pine `request.security(ticker, "1d", close)` в
non-repainting mode возвращает close **последнего ЗАКРЫТОГО** 1d бара.
Если делать backtest с `df_1d["close"].asof(signal_time)`, мы получим
close бара который СОДЕРЖИТ signal_time — то есть бар, который ещё
не закрылся, и его close — это будущая информация.

## Что было

В etap_36 (2026-05-08, C2v2 first claim):

```python
def hull_trend_label(close, hull, ts):
    c = asof_value(close, ts)              # close[forming_bar] - LOOKAHEAD
    idx = hull.index.searchsorted(ts, side="right") - 1
    if idx < 2: return "na"
    h2 = hull.iloc[idx - 2]               # OK (older data)
    return "up" if c > h2 else "down"
```

При signal_time = 2026-05-05 14:00 UTC:
- `idx` = индекс бара 2026-05-05 (открыт в 00:00, закроется в 2026-05-06 00:00)
- `c = close[idx]` = close 2026-05-05, **известный только в 00:00 след. дня**
- На 14:00 этот close — будущая информация (8-10 часов вперёд)

## Симптом

C2v2 baseline (etap_36 buggy) на BTC RR=1.5:
- WR 49.0%, **+101R**, 0 минусовых лет за 7 — выглядело как breakthrough.

После fix (last closed bar):
- WR 46.6%, **+66R**, 1 минусовый год (2021 -2.5R).
- Inflation **+35R / +53%** от lookahead.

Дополнительно: filter перестаёт работать на ETH OOS вообще (-30R / 4/4 bad
years), что подтверждает не-фундаментальную природу edge'а. На SOL частично
работает (+37R RR=1.5 / 1 bad year).

## Причина

В backtest df_1d.index содержит OPEN times баров. `searchsorted(ts, "right") - 1`
возвращает индекс бара, **внутри которого** находится ts. Этот бар ещё
формируется (если ts ≠ open exact). Его close — будущая информация.

В Pine на LTF при использовании `request.security(_, "1d", close)`:
- `barmerge.lookahead_off` (default) возвращает значение бара, который
  УЖЕ ЗАКРЫЛСЯ к моменту LTF бара
- Это `close[idx_dataframe - 1]` в нашей терминологии

## Правило избегания

**Любой HTF lookup в backtest начинается с `last_closed_idx = idx - 1`:**

```python
def htf_value_safe(htf_series, ts):
    """Получить HTF value, доступное на момент LTF события.

    htf_series.index содержит OPEN times. Бар idx — это бар, ВНУТРИ
    которого находится ts (формируется). last_closed = idx - 1.
    """
    idx = htf_series.index.searchsorted(ts, side="right") - 1
    if idx < 1: return np.nan
    return htf_series.iloc[idx - 1]
```

Если используется Pine `[N]` shift (например HULL[2] = hull 2 бара назад
от текущего):

```python
def hull_with_shift_safe(hull, ts, shift=2):
    """Pine HULL[shift] from last CLOSED bar."""
    idx = hull.index.searchsorted(ts, side="right") - 1
    last_closed = idx - 1
    if last_closed - shift < 0: return np.nan
    return hull.iloc[last_closed - shift]
```

## Где встречается

Везде где в backtest LTF-стратегии используется HTF индикатор:
- Hull MA(78) на 1d ([[asvk-trend-line-hull]]) — этот случай
- EMA200 на 4h при 15m trigger
- Daily-open для ICT premium/discount (дневной open всегда известен в
  момент 00:00, поэтому если ts ≥ 00:00 текущего дня, daily_open[idx]
  известен; но closing values — нет)
- HMA / EHMA / THMA любых длин на любом HTF
- ASVK Custom RSI dynamic levels на HTF
- Money Hands MF на HTF

## Связь с другими pitfall'ами

Похоже на [[lookahead-anchor-confirm-окно-cur_open-cur_close]] — оба
случая используют данные из формирующегося бара. Разница:
- Anchor-confirm: используется значение зоны до её confirmation
- HTF-lookup: используется close/индикатор HTF бара до его close

Аналогичный класс ошибок: [[multi-bar-pattern-confirm-vs-trigger-lookahead]] —
все три выглядят как «использование данных из будущего относительно
момента действия».

## Влияние на найденные edge'ы

### C2v2 (Hull-1d filter поверх C2)

| Symbol | RR | Buggy | Safe | Δ |
|---|---|---|---|---|
| BTC | 1.0 | +111R | +76R | -35R |
| BTC | 1.5 | +101R | +66R | -35R |
| BTC | 2.0 | +87R | +48R | -39R |
| ETH | 1.0 | n/a | -12R | catastrophic |
| ETH | 1.5 | n/a | -30R | catastrophic |
| SOL | 1.5 | n/a | +37R | works |

После fix: BTC всё ещё имеет edge (+13R / RR=1.5 vs baseline), но magnitude
скромнее. ETH полностью провален. SOL работает.

См. [[strategy-c2v2-ob-6h-fvg-2h-pro-hull-1d]] — обновлён с safe-результатами.

### Forensic 1.1.1 (etap_35)

В etap_35 был тот же bug в `hull_trend_label`. Найденные filter-results
(Hull-4h aligned: WR +13.6pp на 1.1.1) **ТОЖЕ требуют re-audit с safe lookup.**
Скорее всего магнитуды inflated. Не критично для verdict (1.1.1 fail
criterion 4 frequency anyway), но честно отметить в [[strategy-1-1-1-honest-audit-failed]].

## TODO

- [ ] Re-run etap_35 forensic с safe Hull lookup → обновить magnitudes
- [ ] Audit все scripts в `research/elements_study/` где используется
      `asof_value()` на HTF близ LTF triggers
- [ ] Helper-функция `htf_safe_value()` в `research/_shared/htf_utils.py`
      для будущих экспериментов
