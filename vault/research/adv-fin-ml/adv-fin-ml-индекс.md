---
type: index
tags: [ml, quant, lopez-de-prado, research, index]
ingested: 2026-06-10
---

# Индекс: Advances in Financial ML (López de Prado) + quant-статьи

Конспекты academic-пачки из `~/Downloads` (10 июня 2026). Ядро — **курс Marcos López de Prado «Advances in Financial Machine Learning» (ORIE 5256, 10 лекций)** + смежные quant-статьи. **Самый релевантный материал для ML-pivot трека** ([[traid-bot-ml-pivot]]): walk-forward, Purged K-Fold, financial features, борьба с overfit — то, что уже используется в MH ML pipeline.

Конвенция: 1 источник/блок = 1 заметка; читать по порядку лекций. Всё прикладывать к нашему MH ML pipeline и гнать через [[7-criteria-of-good-strategy]].

## Курс «Advances in Financial ML» (10 лекций López de Prado)

- [[adv-fin-ml-обзор-lecture1-ten-applications]] — Lec 1/10 + Ten Applications. Эконометрика vs ML, «ML всегда найдёт паттерн даже если его нет», black swans.
- [[adv-fin-ml-lec2-4-bars-labeling-purged-kfold]] — Lec 2-4. ⭐Information-driven bars (dollar/volume/imbalance), Triple-Barrier labeling, **Meta-labeling**, Fractional diff, Ensembles, ⭐**Purged + Embargoed K-Fold**.
- [[adv-fin-ml-lec5-7-betsizing-backtest-overfit-hrp]] — Lec 5-7. Bet sizing из p(x), ⭐dangers of backtest (**CPCV**, **PBO**, Deflated Sharpe), backtest-метрики, **HRP**.
- [[adv-fin-ml-lec8-10-numerai-sadf-entropy-microstructure-meta-strategy]] — Lec 8-10 + Numerai. ⭐**SADF bubble detection**, entropy, microstructure (Kyle/Amihud lambda), HPC/quantum, **Meta-Strategy**, **MDA feature selection**, era-balancing.

## ⭐ Сводка action items для ML-pivot (из всего курса)

Дёшево→дорого: **SADF/CUSUM режим-фича** (крипто-пузыри) · **MDA feature selection** (3064 фич) · **era/month-balancing** (наша боль стабильности) · **Meta-labeling** поверх каскадов · **Embargo** к Purged K-Fold · **Triple-barrier labeling** · **Entropy/Amihud** фичи · **CPCV + Deflated Sharpe + PBO** · **fractional diff** · **dollar/volume bars** (дорого, ломает инфру) · **HRP/meta-allocation** слой.

## Смежные quant-статьи (arXiv)

- [[quant-статьи-arxiv-OTR-mean-reversion-derivatives-portfolio]] — свод 6 статей. ⭐**1408.1159 + 2003.10502** (OTR / closed-form mean-reversion TP/SL — против overfit RR-tuning, ВЫСОКИЙ приоритет). Нишевые: 1508.06182 (quantum), 2302.08819 (LSV деривативы), 2406.01199 (GWB allocation), 2205.04879 (math kernels).

## Общая ML-теория (reference)

- [[neural-networks-nielsen-backprop-reference]] — Nielsen NN&DL глава 2 (backprop). Reference; мы на LightGBM, не НС. Закладка на будущее (sequence-модели).

## Первоисточник курса

- `ssrn-3104847` = обложка **книги López de Prado «Advances in Financial Machine Learning» (2018)** — первоисточник всех 10 лекций. Контент = 4 заметки lec1-10 выше. Отдельно не конспектируется.

## Вне темы quant-трейдинга (каталогизировано, без конспекта)

- `0907.4282` — ❌ Pierre Auger Observatory (физика космических лучей). Случайно попало. Пропущено.
- `2305.02231`, `2503.04739`, `2505.13565` — Trustworthy AI / ethics / democracy (López de Prado соавтор, но это AI-governance, не quant-трейдинг). Не относится к боту. Каталогизировано, без конспекта.
- Рабочие вики Aston (Java/SQL/Keycloak/Supabase/Moodle screencapture в Downloads) — ❌ не проект, не трогаем.

---
Связь: [[traid-bot-ml-pivot]], [[traid-bot-empirical-laws]] (lookahead/overfit — López de Prado об этом же).
