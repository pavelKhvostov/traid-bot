# Strategy 1.1.1

Каскадная стратегия: macro-зона на HTF → entry-зона внутри неё на LTF → trigger по касанию на 1m.

## Версии

| Версия | Где | Что |
|---|---|---|
| **v1** | `~/traid-bot/strategies/strategy_1_1_1.py` | Production. Macro: `OB-{1d,12h}+FVG-{4h,6h}` (ad-hoc композит). Entry: `OB-{1h,2h}+FVG-{15m,20m}`. WR 54.8%, +46.8R на 3y BTC |
| **v2** (design) | [`strategy_1_1_1_v2.py`](strategy_1_1_1_v2.py), [`strategy-1-1-1-v2.md`](strategy-1-1-1-v2.md) | Унификация: обе ступени = canon `ob_vc` (macro D/12h+4h/6h → entry 1h/2h+15m/20m). Floating TP из etap108. bb-модель как фильтр. Design 4/8 вопросов |
| **floating reference** | [`strategy_1_1_1_floating.py`](strategy_1_1_1_floating.py) + [`.pdf`](strategy_1_1_1_floating.pdf) | **Production reference от разработчика (etap108)**. v1 детектор + Floating TP simulator (4-indicator score). Total 6y: **+428.9R** (vs baseline +317.8R). **НЕ редактировать** |
| **v1rules backtest** | [`strategy_ob_vc_v1rules/`](strategy_ob_vc_v1rules/) | Backtest harness: 7 правил из floating (без SWEPT, confluence, cascade) на `ob_vc` событиях. Фиксирует strict lookahead-safe `fill_start` через `strict_detection_ts` |

## Архитектура каскада (v2)

```
1. Macro detection: ob_vc(HTF=D/12h, LTF=4h/6h)
   → macro_zone = OB-часть

2. Entry detection: ob_vc(HTF=1h/2h, LTF=15m/20m)
   + entry.zone ⊆ macro_zone, same direction
   → entry_zone = entry_ob_vc.zone

3. Trigger: касание entry_zone на 1m → сигнал
```

## Trade rules

| параметр | значение |
|---|---|
| Entry | `fvg_bottom + 0.80 × (fvg_top - fvg_bottom)` (mid 80% FVG-LTF) |
| SL | `ob_htf_bottom + 0.35 × (fvg_bottom - ob_htf_bottom)` (symmetric 35%) |
| Exit | Floating TP из etap108 (4-indicator score) — обязательно для V2 |

Полная спека V2 в [`strategy-1-1-1-v2.md`](strategy-1-1-1-v2.md).

## Связи

- Canon ob_vc: [`elements/ob_vc/`](../../elements/ob_vc/)
- Strict detection timing: feedback-memo `ob_vc-strict-detection-timing`
- bb-модель фильтр: [`projects/bounce-or-break.md`](../../projects/bounce-or-break.md)
- Импортёры floating: `projects/bb_dataset/builder_v{2,3}_parallel.py`, `strategy_ob_vc_v1rules/backtest.py`
