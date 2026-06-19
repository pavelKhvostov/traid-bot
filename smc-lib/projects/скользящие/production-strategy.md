# Production Strategy

## Конфигурация для real trading

### Hybrid Signal (Recommended)

Используем **разные ансамбли для разных направлений**:

```python
# Configuration
LONG_ENSEMBLE  = "v4+regime-feat 60d labels 4-seed"     # сильнее на LONG
SHORT_ENSEMBLE = "v4+regime-feat 48h strict anchored"   # сильнее на SHORT

LONG_STRATEGY = {
    "threshold": 0.50,
    "cooldown_h": 12,
    "regime_filter": lambda r: r != "CHOP",  # skip CHOP regime
}

SHORT_STRATEGY = {
    "threshold": 0.45,
    "cooldown_h": 12,
    "seed_consensus": "4/4 > 0.45",  # all 4 seeds must agree
}
```

### Expected performance (backtest)

| Side | Sig/мес | WR | Expectancy/trade |
|---|---|---|---|
| LONG | 5-7 | 55-60% | +1.20R |
| SHORT | 5 | 61.6% | +1.46R |
| **Combined** | **10-12** | **~55-60%** | **+1.20-1.40R** |

**Monthly expectancy:** 10-12 trades × 1.20R = +12-14R/мес  
**На 1% risk per trade:** **+12-14% месяц теоретически**

После transaction costs (0.5% round-trip):
- WR effective ≈ 53-58%
- Monthly expectancy ≈ +10-12R/мес = **+10-12% реалистично**

## Position Sizing

### По ATR (volatility-adjusted):

```python
def position_size(entry_price, atr_14_1h, bankroll, risk_pct=0.01):
    """
    risk_pct = 0.01 → 1% of bankroll per trade
    SL = entry - 1*ATR (для LONG) или entry + 1*ATR (для SHORT)
    """
    sl_distance = atr_14_1h  # approximate SL
    risk_amount = bankroll * risk_pct
    position_size_usd = risk_amount / (sl_distance / entry_price)
    return position_size_usd
```

### По fixed %:

```python
# Static 1% risk per trade
sl_pct = 0.01  # 1% от entry
risk_amount = bankroll * 0.01
position_size = risk_amount / sl_pct
# = bankroll (full bankroll exposure at 1% SL)
```

Рекомендую **ATR-based** — учитывает текущую волатильность.

## Pre-Launch Checklist

### Phase 1 — Honest Out-of-sample Audit ⚠ MUST DO
- [ ] Прогнать best ensemble (v4+regime-feat 4-seed) на test holdout **2026-04-01 → 2026-06-12** 
- [ ] Применить cluster strategy (thr=0.50, cooldown 12h, skip CHOP)
- [ ] Compute top-1% WR mean
- [ ] **Decision gate:**
  - ≥ 50% → proceed Phase 2
  - 45-50% → marginal, нужно дополнительное research
  - < 45% → возврат к research

### Phase 2 — Execution Simulation
- [ ] Backtester с **0.05% taker fee** Binance
- [ ] **0.05% slippage** modeling
- [ ] **Funding rate** на perps (если шортим)
- [ ] **Position sizing** на ATR
- [ ] **Drawdown analysis** (max DD, Sharpe, Sortino)
- [ ] Compute **net** PnL после всех costs

### Phase 3 — Paper Trading (1-2 месяца)
- [ ] Live model запуск каждый час
- [ ] Apply cluster strategy in real-time
- [ ] **НЕ отправляем реальные ордера**
- [ ] Имитируем entries/exits в spreadsheet
- [ ] Сравниваем с backtest WR (должны быть близки)
- [ ] Decision gate: paper WR ≥ backtest − 5pp

### Phase 4 — Live Micro (3+ месяца)
- [ ] Start with **0.1-0.5% от bank** per trade (микро-сайз)
- [ ] Bot или ручной запуск
- [ ] **Логировать каждую сделку**
- [ ] **Weekly review** WR vs backtest
- [ ] Если WR ≥ 50% → постепенно увеличить size до 1%
- [ ] Если WR < 45% → пересмотр модели

### Phase 5 — Production Scale
- [ ] Risk per trade: **1% от bank**
- [ ] Max concurrent positions: **3** (диверсификация)
- [ ] Auto-stop при DD > 15%
- [ ] Monthly review WR + retrain model на новых данных

## Risk Management

### Drawdown protection:

```python
MAX_DRAWDOWN = 0.15  # 15% от peak balance
MAX_LOSING_STREAK = 7  # после 7 losses пауза 24ч
DAILY_LOSS_LIMIT = 0.03  # max 3% loss in single day → stop
```

### Position management:

- **Open trade per asset only one** (не открывать второй BTC LONG если есть)
- **Skip new signal если existing position** на том же ассете в том же направлении
- **Reverse signal** (LONG → SHORT) — закрыть first, потом ждать новый сигнал

## Что МОЖНО автоматизировать

### Easy (1-2 дня):
- Live model inference (load ONNX/TorchScript)
- Apply cluster strategy
- Send Telegram notification: "BTC LONG signal at $X, TP $Y, SL $Z"

### Medium (1-2 недели):
- Auto-execute orders на Binance via API
- Position tracking (open/close logs)
- Performance dashboard (web app)

### Hard (1-2 месяца):
- Adaptive thresholds (online learning)
- Multi-asset universal model
- Hedging strategy (correlated assets)

## Что НЕ делать (правила гигиены)

❌ **НЕ trade без paper trading 1-2 мес**
❌ **НЕ увеличивать size после wins** (psychological trap)
❌ **НЕ trade на CHOP-региме** (модель там слабее)
❌ **НЕ ignore drawdown protection**
❌ **НЕ retrain модель часто на свежих данных** без проверки (overfit to recent)
❌ **НЕ перешагнуть Phase 4 → 5 без 3 месяцев успешных microtest'ов**

## Психология

Backtest 55% WR при RR=3:1 — это:
- 5 wins из 10 → +15R
- 5 losses из 10 → −5R
- Net: **+10R per 10 trades** = +1R/trade

Но **на лосс-стримах**:
- 5 losses подряд = −5R (5% drawdown на 1% risk)
- 7 losses подряд = −7R (7% drawdown)
- Это **математически возможно** даже при 55% WR

Готов ли психологически на 5-7 losses подряд? Если нет — **не запускай**.

## Когда возвращаться к research

Поводы для пересмотра модели:
1. **Live WR < 45%** на 1-3 мес periode → модель broken
2. **3 регим-shift месяца подряд** (например, mania start) → model никогда не видела этого
3. **Sharpe < 1.0 после 3 мес live** → edge marginal
4. **Drawdown > 25%** → risk management failure

## Honest disclaimer

Backtest WR ≠ Live WR. Реалистично ожидать:
- Live WR ≈ Backtest WR − **5-10pp**
- Live Sharpe ≈ Backtest Sharpe × **0.5-0.7**

Если backtest 55% WR → live 45-50% реалистично.
Если backtest expectancy +1.20R → live ~+0.5-0.8R.

Хорошая стратегия = **+0.5R per trade live** = +5-10R/мес = **+5-10% годовых** на bankroll (после правильного scaling).

Это **скромно но возможно**.

## Финальная мысль

Эта модель ≠ деньги. Это **инструмент для отбора сетапов**. Trader все ещё должен:
- Управлять риском
- Контролировать эмоции
- Не торговать когда уставший / в плохом настроении
- Регулярно ревьювить performance

**ML edge - 30%. Risk management + discipline - 70%.**
