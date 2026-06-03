---
name: 12h-fractal-prediction-final-strategy
description: "Final strategy for predicting HH/LL fractal on 12h BTC — C1 (sweep_FH ∪ OB_sweep) ∩ C2 (sweep_maxV[i])"
metadata: 
  node_type: memory
  type: project
  originSessionId: bd69e36f-0485-4922-92c1-f1eee5815475
---

Финальная стратегия (зафиксирована 2026-05-20, in-sample 6y BTC):
**Предсказание HH/LL Билл-Уильямс-фрактала на свече `i` 12h BTC.**

**Условия (оба на одной свече `i`):**
- **C1.** Либо sweep_FH (HH) / sweep_FL (LL), либо OB_sweep (SHORT для HH /
  LONG для LL) на каком-то ТФ ∈ {12h, 1d, 2d, 3d, W=пн-пн}. Sweep =
  wick через level + close обратно. Зоны/фракталы немитигированные.
- **C2.** Sweep maxV(i-1): wick свечи `i` пробивает maxV предыдущей
  12h-свечи + close обратно. maxV = close **1m**-свечи с макс. dirVolume
  (LTF=1m по решению пользователя 2026-05-20; отступает от Pine canon
  15m для D-chart — см. [[vic-maxv-расходился-с-pine-индикатором-из-за-1m-вместо-15m]]).

**Результаты (baseline P=13.7%):**
- Core HH (FH∪OB): 81.9% (n=83 за 6y, ~14/год)
- Core LL (FL∪OB): 73.4% (n=94, ~16/год)
- Sniper HH (FH∩OB): 90.3% (n=31, ~5/год)
- Sniper LL (FL∩OB): 68.3% (n=41, ~7/год)

**Why:** maxV закрыл треугольник классификации зон пользователя (ликвидность
FH/FL + эффективность maxV) и стал сильнейшим C2 (+20-30pp над C1 solo).
FVG / OB-liq / RDRB / LTF OB-FVG-iFVG / свеча i-1 — отклонены или слабее.

**C3 (доп. LTF-фильтр поверх Core) — не используется** (решение 2026-05-20).
Хотя HH Core ∩ iFVG(1h-2h) даёт прорыв 96.4% (n=28), C3 сужает recall и
почти ничего не даёт для LL. Финальная стратегия = C1 ∪ C2, без C3.

**ASVK Custom RSI zone (OB/OS) как C3 — также отклонён** (2026-05-21).
Прогон на LTF {1h, 2h, 4h, 6h} показал жёсткое сжатие: -86% сетапов
(176→25), precision поднимается до 92% но при том же уровне точности
Sniper-Core (sweep_FH ∩ OB_sweep ∩ maxV[i]) даёт больше объёма (n=31).
Дополнительно — anti-сигналы сильнее direct: LL ∩ ASVK OB 1h = 92.31%
(контр-интуитивно), указывает на возможный артефакт адаптивных уровней.

**How to apply:**
- При вопросах по предсказанию фрактала на 12h BTC использовать
  именно эту комбинацию как канон.
- Полный canon: `vault/knowledge/strategies/12h фрактал — эмпирика снятия
  зон 6y BTC.md`.
- Артефакты: `research/vic_vadim/predict_fractal_maxv.py` (финальный),
  + 11 вспомогательных скриптов.
- Открыто: walk-forward / OOS / ETH-SOL / entry-SL-TP / live integration /
  переcчёт maxV на 5m (точный Pine для 12h-chart).
