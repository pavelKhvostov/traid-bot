---
name: feedback-heavy-compute-on-pc
description: "Правило 9 (smc-lib/rules.md): сложные вычисления упаковывать в архив и запускать на отдельном Windows PC (Ryzen 7 7700 + RTX 5070 Ti + 32 GB), не на MacBook Air M5"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f4db015b-597b-4328-ad33-5010538fa5f2
---

**Сложные вычислительные процессы выносить с MacBook Air M5 на отдельные Windows-PC (два доступны).** Я формирую архив (код + данные + requirements + README), пользователь переносит и запускает на PC, возвращает output для анализа.

**Why:** MacBook Air M5 — рабочая интерактивная машина, без CUDA GPU и с ограниченным RAM. У пользователя есть **два выделенных Windows PC** для heavy compute (уточнено 2026-05-29):
- **PC1**: Ryzen 7 7700 OEM (8C/16T), 32 GB DDR5, **RTX 5070 Ti** — топовая GPU
- **PC2**: i5-14600KF (14C/20T), 32 GB DDR5, RTX 4070 — больше CPU потоков

Уже использовали workflow для регенерации `btc_full.csv` (PC1).

**How to apply:** Когда задача требует:
- Walk-forward на 5+ лет с несколькими конфигами (>30 мин runtime на M5)
- Тренировку LightGBM/XGBoost на >1M строк
- Любое GPU-ML (PyTorch/TF обучение)
- Multi-symbol полный rebuild
- Peak RAM > 8 GB

→ **НЕ запускать на Mac**, а формировать архив `~/Desktop/compute-archives/compute-YYYY-MM-DD-task-slug.zip`:

1. Python-скрипт(ы) с pathlib paths (cross-platform)
2. `requirements.txt` с pinned versions
3. Данные или явные инструкции их скопировать
4. README с командой запуска и expected output
5. Output-папка `./output/`

**Выбор PC под задачу:**
- **GPU-heavy ML** (LSTM/Transformer/deep RL) → **PC1** (RTX 5070 Ti)
- **Grid-search / hyperparameter sweep** → **PC2** (20 threads)
- **Walk-forward suites с multiprocessing** → **PC2** (14 cores)
- **Generic ML training** (LightGBM/XGBoost) → любой PC
- В README архива указывать рекомендуемый PC

**⚡ Параллелизм (target: 80-90% CPU usage):**
- **Inner n_jobs** в библиотечных моделях (LightGBM `n_jobs=-1` или explicit)
- **Outer parallelism** через `joblib.Parallel(n_jobs, backend="threading")` для независимых задач (retrains/horizons/configs)
- Total threads (Outer × Inner) ≤ total_PC_threads (избегать oversubscription)
- Рекомендация для **PC2 (20T):** Outer × Inner = 6 × 3 = 18 (как для MH walk-forward 2026-05-29)
- Рекомендация для **PC1 (16T):** Outer × Inner = 4 × 4 = 16
- **НЕ использовать** sklearn `HistGradientBoostingRegressor` для heavy compute (плохо параллелится <20% CPU) — заменять на **LightGBM**

**Pitfalls для Windows-PC:**
- CP1251 console — НЕ использовать unicode (Δ, ★, 🔥) в print(); заменять ASCII или добавить `chcp 65001 >nul` в .bat
- Path separator — pathlib, не hardcoded `/`
- GPU — `device = "cuda"` (не MPS); проверять `torch.cuda.is_available()`
- .bat файлы — **CRLF line endings** (не LF), иначе cmd может молча закрыться
- Cyrillic username path → pip может валиться на сборке из source (`--only-binary :all:` или wheel-only version)

**Что остаётся на Mac (НЕ выносить):**
- Экспертные заключения (zones_opinion, expert/opinion, expert/chart)
- Inference на одной точке времени (cli.py)
- Plot-скрипты для одиночных графиков
- Любая интерактивная разработка/дебаг

**Канон:** `~/smc-lib/rules.md` → Правило 9.

## Connections

- [[prediction-algo-roadmap-5-questions]] — все 5+ задач roadmap пойдут через этот workflow
- [[prediction-algo-final-results]] — текущая модель ещё запускалась на Mac, новые ML-расширения уйдут на PC
