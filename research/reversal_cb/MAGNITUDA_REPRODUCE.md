# Стратегия «МАГНИТУДА» — спецификация и точное воспроизведение

> Для другого Claude Code (ветка Вадима): этот документ позволяет воспроизвести модуль **один-в-один**.
> Всё, что нужно — репозиторий `traid-bot`, данные в `data/`, и `venv` с пакетами ниже. Код — в `research/reversal_cb/`.

**Что это.** «Магнитуда» — самообучаемая (purged walk-forward) + самоисправляемая CatBoost-стратегия поиска
**разворотных точек** на крипте (BTC/ETH/SOL). Торгуемое ядро = комбо из двух сторон:
- **① Магнитуда-Long** — 8h, бычьи развороты, RR-бакет [2.5, 4).
- **② Магнитуда-Short** — 12h, медвежьи развороты, RR-бакет [1.5, 4).

⚠️ **Не путать** с `magnitude_engine` (`research/ta_laws/`) — то описательное исследование «размер хода предсказуем».
«Магнитуда» здесь — **торговая стратегия**; имя дано потому, что её edge управляется волатильностью/режимом.

---

## 0. Окружение
- Python 3.13, `venv/`. Пакеты: `pandas 2.2.x`, `numpy`, `catboost 1.2.10`, `scikit-learn` (isotonic, KMeans, DecisionTree).
- GPU CatBoost опционален (`task_type="GPU"`); во всех скриптах есть CPU-fallback. torch не нужен.
- Запуск (Windows): `set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/<script>.py`.

## 1. Данные
`data/{BTCUSDT,ETHUSDT,SOLUSDT}_{6h,8h,12h}.csv`, колонки: `open_time, open, high, low, close, volume` (UTC).
Период ~2020 → 2026-06. Свежие бары для live — Binance public klines (`api.binance.com/api/v3/klines`).

## 2. Определение разворота (LABEL — точно, как задал юзер)
Свеча `i` — **бычий разворот**, если от её `close[i]` цена дала **+3% РАНЬШЕ**, чем появилась свеча,
обновившая её минимум (`low[j] < low[i]`). Зеркально для **медвежьего** (−3% раньше `high[j] > high[i]`).
First-passage, окно `CAP = 120` баров:
```
long:  стоп = low[i];  цель = close[i]*(1+0.03);  риск = (close[i]-low[i])/close[i]
short: стоп = high[i];  цель = close[i]*(1-0.03);  риск = (high[i]-close[i])/close[i]
скан j=i+1..i+CAP: long → если low[j]<стоп: LOSS; если high[j]>=цель: WIN; иначе TIMEOUT (выход по close[end])
RR = 0.03 / риск   (варьируется! тугой стоп → высокий RR — это ключ к монетизации)
```
**АСИММЕТРИЯ** (стоп близко = свой low, цель +3% далеко) → label НЕ монетка-по-построению.
Базовая частота разворота ~0.29 (long 0.25–0.34, short 0.22–0.37). Канон: `reversal_analysis.label_long`, `reversal_module.label_and_outcome`.

## 3. Фичи (22 шт, ВСЕ известны на закрытии бара — без утечки). Канон: `reversal_analysis.feats()`
`rng=high-low; pc=close.shift(1)`
- Геометрия/отвержение: `clv=((c-l)-(h-c))/rng`, `lwick=(min(o,c)-l)/rng`, `body=|c-o|/rng`, **`c2l=(c-l)/c`** (механический конфаунд!).
- Моментум/экстеншн: `ret1/ret3/ret6=c/c.shift(k)-1`, `dd20=c/max(high,20)-1`, `posrange20=(c-min(low,20))/(max(high,20)-min(low,20))`, `dist_ema20/50/100=c/ema(c,n)-1`, `rsi`=Wilder RSI(14) (ewm alpha=1/14), `consec_dn`=длина серии down-close.
- Вола/режим: `atr_pct=ATR(14)/c`, `atr_ptile`=rolling(100) перцентиль ATR, `range_exp=rng/mean(rng,20)`.
- Объём: `vol_z=(v-mean(v,96))/std(v,96)`, `vol_climax=v/mean(v,20)`.
- Ликвидность: `swept=low<min(low,5).shift(1)`, `sweep_depth=clip((min5-low)/c,0,)`, `left_pivot=(low<=low.shift(1))&(low<=low.shift(2))`.

`FEATS` (порядок в `reversal_module.py`): c2l, clv, lwick, body, ret1, ret3, ret6, dd20, posrange20, dist_ema20,
dist_ema50, dist_ema100, rsi, consec_dn, atr_pct, atr_ptile, range_exp, vol_z, vol_climax, swept, sweep_depth, left_pivot.

## 4. Модель + отбор
- **CatBoost** classifier: `iterations=350–400, depth=6, learning_rate=0.05, loss=Logloss, random_seed=7`.
  Для калибровки вероятностей — **без** class-weights (`cb_nw` в `ev_rescue.py`); в базовом модуле — `auto_class_weights="Balanced"`.
- **Селектор-флаг:** reversal-likelihood = `proba`; порог = **70-й перцентиль OOS-proba** (top-30% уверенности), per-asset.
- **RR-фильтр (КЛЮЧ):** считать `RR=0.03/риск`, оставлять только ① long `RR∈[2.5,4)`, ② short `RR∈[1.5,4)`.
  (Edge в СРЕДНЕМ RR. Экстрим RR>4 = шум+косты; RR<1.5 = далёкий стоп, RR≈1.)
- **Сделка/косты:** вход=close, стоп=свой low/high, TP=±3%. `cost_R=rt/риск`. taker `win=loss=0.0010`; maker `win=0.0002, loss=0.0010`.

## 5. Самообучение/самоисправление + СТЕНЫ валидации (обязательно — иначе мираж)
- **Purged walk-forward** (`ev_rescue.wf_raw`): edges=`linspace(0.4n, n, 7)` → 6 фолдов; train=`[:te0-embargo]`,
  **embargo=CAP=120** (горизонт label), test=`[te0:te1]`. Это и есть «самообучение вперёд во времени».
- **Самоисправление:** мета-лейблинг (`reversal_module`), таксономия + дерево на знак R (`reversal_taxonomy.py`).
  ВЕРДИКТ: оба **НЕ улучшают net-R OOS** (знак R не предсказуем по фичам сверх RR-измерения). Единственный работающий
  отбор = структурный RR-бакет. Мета-фильтр сверху не нужен.
- **Killer-контроли:** base-rate, permutation-null, time-shuffle, год-стабильность, **cross-asset (≥2/3)**,
  **matched-random-null** (флагнутые vs случайные в том же RR-бакете), **block-bootstrap** (CI net-R с учётом
  кластеризации сделок), регим-сплит (вола×тренд). Метрика — **accuracy/precision + НЕТТО-R**, не AUC.

## 6. Скрипты (`research/reversal_cb/`) — порядок воспроизведения
1. `reversal_analysis.py` — label + сила факторов (Cohen's d, decile-lift) + add-тест на конфаунд c2l.
2. `reversal_module.py` — базовый CatBoost-модуль (purged WF + мета + диагностика ошибок), precision/recall/net-R.
3. `ev_rescue.py` — EV-отбор + isotonic-калибровка (НЕ спас; для справки).
4. `rr_native.py` — RR-монетизация на НАТУРАЛЬНОМ барьере, RR-бакеты vs null (тут проступают ① и ②).
5. `rr_confirm.py` — perm-null + год + OOS по кандидатам.
6. `rr_harden.py` — block-bootstrap + режим + порог + RR-соседи.
7. `rr_monthly.py` — помесячный R (по месяцу выхода), Sharpe, maxDD.
8. `rr_regime.py` — режим-атрибуция (вола/тренд BTC; режим-ставка vs крепчание модели).
9. `rr_correlation.py` — корреляция с боевой корзиной (111/112/115/32/A_irdrb) + прирост Sharpe.
10. `rr_taxonomy.py` — RR-фокус самоисправления (категории по mean-R + дерево на знак R).
11. `vol_gate.py` — ВОЛА-ГЕЙТ (брать только при низкой воле; улучшение, см. §8).
12. `reversal_live.py` / `rr_live_signals.py` — live-инференс (свежие klines → сигналы за период).

## 7. Ключевые результаты (для сверки воспроизведения)
- **Классификация = настоящий навык:** precision-lift **1.4–1.9×** над base, permutation-null=base (p≈0), cross-asset.
- **Но net-R≈0 на всём сигнале** (вола-RR-конфаунд: уверенность модели = волатильность → +3% чаще, но стоп далёкий → RR≈1).
- **Деньги — в средне-RR бакетах** (натуральный барьер):
  - **① 8h LONG RR[2.5,4):** net-R **+0.248** (taker), OOS≥2024 +0.242, cross 3/3 (BTC+0.18 p≈0.07, ETH+0.38 p≈0.04).
    ⚠️ хрупок: сосед [2,2.5) отрицателен; широкий флагнутый long в 2026 терял.
  - **② 12h SHORT RR[1.5,4):** net-R **+0.092**, OOS≥2024 +0.110, n=638, BTC **p=0.002**/SOL **p=0.004** (ETH слаб). Стабильнее.
- **Помесячно комбо:** avg +2.43R/мес, 60% плюс-мес, Sharpe 1.28, maxDD −24R. **Концентрация:** 2023 −5R, 2024 −2R
  (флэт), 2025 +67R, 2026 +39R → не всепогодно.
- **Регим:** edge живёт в **низкой воле/ренже/медведе**; long платит в быке, short в медведе (тренд-хедж). Высоковола-бык глушит.
- **Корреляция с корзиной ≈ 0** (+0.01) → диверсификатор: Sharpe корзины **3.82 → 4.30**, maxDD −4.3→−3.2R, опт. доля ~15–20%.
- НЕ помогают (проверено): больше фич, мета-лейблинг, precision-фильтр, EV-отбор, ATR-стоп (сплющивает RR=бета).

## 8. Улучшения — что проверено и итог
- ❌ **Вола-гейт** (`vol_gate.py`): гейт сигналов по низкой воле монотонно СНИЖАЕТ Sharpe (1.28→0.87) и ΣR — все режимы +EV,
  гейтить нечего. Отклонён.
- ❌ **Фаза-детектор / эквити-гейт** (`rr_phases.py`): дескриптивно «плохо в сильном-аптренде+высоковоле, хорошо во флэте»;
  но walk-forward гейты не бьют базу робастно (на 2 плохих периодах невалидируемо), own-equity не предсказывает.
  И гейтить нельзя в принципе — плохие фазы Магнитуды = хорошие для трендовых каскадов (сломается диверсификация).
- ✅ **MAKER-исполнение** (`maker_exec.py`) — ЕДИНСТВЕННЫЙ выживший рычаг: лимит-вход ~0.10% + TP лимиткой, стоп market.
  Sharpe 1.28→**1.68**, net-R +0.13→+0.19, чинит 2024, fill 97%, НЕ режет сделки. Пол = cost-only (дешевле комиссии) Sharpe 1.46.
  ⚠️ 0.20% хуже 0.10% (sweet-spot); 97% fill слегка оптимистично; maker 2bps = rebate-тариф. Истина между 1.46 и 1.68.
  ⚠️ ЛОВУШКА (см. known-pitfalls): лимит-вход и стоп оценивать ОДНИМ сканом, иначе lookahead раздувает Sharpe (было 2.95).
- Дополнит. скрипты: `rr_phases.py` (фазы), `maker_exec.py` (исполнение). Регим-угол закрыт; maker — в финал-спеку.

## 9. Честные кавеаты (обязательно для воспроизводящего)
- Скромный/**пограничный** edge (perm-p лонга 0.07–0.11), 2 ячейки из ~40 проверенных (мультисравнение; смягчено
  cross-asset+OOS-независимостью). Уровень = **малый сайз + live-скелет**, не «лей капитал».
- Headline-числа корзины/комбо в `rr_correlation`/`rr_monthly` — **gross** (нетто кратно ниже). Вывод о диверсификации
  (corr≈0, Sharpe↑, DD↓) к этому устойчив; абсолютные уровни — нет.
- **Режим-условно:** деньги в низкой воле/ренже; в сильном бычьем-высоковолатильном тренде стратегия флэтует.
- Лучшая монетизация = **~15% некоррелированный слив в боевую корзину**, НЕ standalone-продукт.

## 10. Воспроизвести с нуля (TL;DR)
```
1) убедиться в data/{BTC,ETH,SOL}USDT_{8h,12h}.csv
2) venv + pip install pandas numpy catboost scikit-learn
3) python research/reversal_cb/reversal_analysis.py   # факторы
4) python research/reversal_cb/rr_native.py            # RR-бакеты vs null -> ① и ② проступят
5) python research/reversal_cb/rr_confirm.py           # perm-null+год+OOS
6) python research/reversal_cb/rr_harden.py            # block-bootstrap+режим+порог
7) python research/reversal_cb/rr_monthly.py           # помесячно/Sharpe
8) python research/reversal_cb/rr_correlation.py       # диверсификация к корзине
9) python research/reversal_cb/vol_gate.py             # улучшение
```
Числа должны совпасть с §7 (CatBoost-GPU может дать ±мелочь от seed/устройства; порядок и знаки — стабильны).
