---
tags: [session, smc-lib, infrastructure, library]
date: 2026-06-17
---

# Сессия 2026-06-17 — раздел библиотеки «поиск-элементов» + PC1 upgrade

Вторая сессия за день (после [[2026-06-17-живой-рынок-v8-v11-cleanup]]). Фокус — вынести проверенные `event_detector_v11` и `snapshot_generator_v6` в новый универсальный раздел библиотеки `~/smc-lib/поиск-элементов/`, очистить snapshot от project-specific context features, оформить аппаратный апгрейд PC1.

## Что сделано

### 1. PC1 hardware upgrade (Ryzen 9 9950X)

- Заменили CPU: **Ryzen 7 7700 (8c/16t) → Ryzen 9 9950X (16c/32t)**, RAM **32GB → 64GB DDR5-5600 (2×32GB)**. AM5 платформа — совместимость без BIOS-сюрпризов.
- LAN IP сменился: `192.168.0.156 → 192.168.0.77`. Обновлён `~/.ssh/config` на Mac.
- Tailscale TCP не работает (`tailscale ping` 8ms работает, но TCP 2222 режется Windows Firewall). Для удалёнки за пределами LAN нужно явно открыть порт на Tailscale-интерфейсе.
- `.wslconfig` лимитировал WSL на 14 потоков (от старого CPU): `processors=14 → 30`. После `wsl --shutdown` подтверждено `nproc=30` + `Mem 58Gi`.
- В smc-lib hardcoded `n_jobs=14` не найдено — править нечего.

### 2. Новый раздел библиотеки `~/smc-lib/поиск-элементов/`

Положили туда **только** проверенные universal-скрипты (синхронизированы Mac ↔ PC1):

| Файл | Размер | Назначение |
|---|---|---|
| `event_detector_v11.py` | 29 KB | детектор 13 SMC элементов × 8 TFs на истории |
| `snapshot_generator_v6.py` | 10 KB | per-anchor active-zone snapshot («что видит ML в момент t») |
| `ошибки.md` | 19 KB | журнал 19 ошибок (#1–#19) с fix-статусами |

См. [[универсальная-библиотека-поиск-элементов-snapshot-агностик]] — архитектурное решение.

### 3. Cleanup snapshot_v6 — убраны project-specific features

User поставил вопрос: «±2% context — для каких целей?» Я разъяснил что использовалось для:
- `in_2pct` per-zone флаг
- `ctx_n_active_{tf}` × 8 (active в ±2%)
- `ctx_n_in_zone_{tf}` × 8 (price_in_zone в ±2%)
- `ctx_n_{BLOCK/INE/LIQ}_in2pct` × 3

User отрезал: ±2% — это снимок «где цена СЕЙЧАС», что для ML тривиально (цена там по определению). Плюс ±2% забивается мелкими 15m/30m зонами. Важное для ML — **откуда цена пришла + куда двинется**, а не «что вокруг неё».

**Что важнее** (отложено на baseline-уровень конкретного проекта, не в snapshot):
- past trajectory: net move за Δt, swept zones на пути, entered_from_side
- forward geometry: asymmetric n_zones_above/below, dist_to_nearest_above/below, cluster strength
- current cluster identity: dominant_tf, n_tfs, role_mix, age_max

**Удалено из snapshot_v6:**
- `in_2pct` per-zone (1)
- `ctx_n_active_{tf}` × 8
- `ctx_n_in_zone_{tf}` × 8
- `ctx_n_{BLOCK/INE/LIQ}_in2pct` × 3
- Константы `CONTEXT_SCOPE_PCT`, `TF_LIST`, `ROLES`

**Сохранено** (universal, project-agnostic):
- per-row scope **±20%** (overlap filter, диапазон досягаемости цены)
- per-zone: `zone_id`, `element_type`, `tf`, `direction`, `role`, `zone_lo/hi`, `last_active_lo/hi`, `level`, `distance_signed_pct`, `price_in_zone`, `dist_to_edge_pct`, `age_ms`, `mit_pct`
- per-anchor: `anchor_ts`, `current_price`

Sanity assertion `last_active_lo ≤ last_active_hi` сохранена (fix #19).

### 4. Sync на PC1

```
~/smc-lib/поиск-элементов/{event_detector_v11.py, snapshot_generator_v6.py, ошибки.md}  ← новый раздел
~/smc-lib/projects/живой-рынок/снапшоты/snapshot_generator_v6.py                          ← рабочая копия (обновлена)
```

MD5 working-copy = library-copy. Готово к перезапуску.

## Архитектурное решение

См. [[универсальная-библиотека-поиск-элементов-snapshot-агностик]].

Граница ответственности:
- **Library (`~/smc-lib/поиск-элементов/`)** = «найти зоны + дать ML инвариантный взгляд на досягаемость». Никакого confluence/density/trajectory.
- **Baseline проекта** = past/forward/cluster features поверх snapshot. Это уже project-specific.

Это два универсальных скрипта на все будущие проекты.

## Ошибки (новых не было)

Ошибка #18 (per-row vs context scope confusion) и #19 (invalid active_zone в LTF) обе из [[2026-06-17-живой-рынок-v8-v11-cleanup]] — журнал перенесён в `~/smc-lib/поиск-элементов/ошибки.md`.

Уточнение по #18: то решение (per-row=±20%, context=±2%) оказалось неполным — context-радиус вообще не нужен в universal snapshot. context переходит на проектный baseline-уровень в виде past/forward/cluster features.

## 5. WSL миграция C: → G: + cleanup всех проектов

User решил: «ни один проект себя не оправдал, чисти всё на PC1».

**Миграция:**
- PowerShell script `migrate-wsl-to-G.ps1` (на `~/Desktop/`): wsl --shutdown → export → unregister → import to `G:\WSL\Ubuntu-22.04\` → restore default user vadim → update netsh portproxy.
- Pitfall: после первого reconnect — banner exchange timeout. Понадобилось user'у перезапустить WSL (`wsl --shutdown` → start → re-update portproxy с новым IP). После этого SSH работал.
- VHDX на C: удалён. C: освободил **+43 GB** (84 → 127 GB free).

**Cleanup `~/smc-lib/projects/*`** (всё снесли — 38 GB):
| Снесено | Размер |
|---|---|
| живой-рынок (parquets v2..v11, snapshots, fib, ml, прочее) | 23 GB |
| ma-rr-predictor | 11 GB |
| vc-ml-predictor | 2.1 GB |
| прометей | 2.1 GB |
| ob-vc-2h | 507 MB |
| trendline-study, vc-daily-forecast, mini-проекты | <100 MB total |

**Что осталось в `~/smc-lib/`** (canon library = 103 MB):
- `elements/` (13 SMC элементов + zone_of_interest.md + tests)
- `поиск-элементов/` (event_detector_v11.py + snapshot_generator_v6.py + ошибки.md)
- `expert/`, `expert_asvk/`, `indicators/`, `literature/`, `patterns/`, `prediction-algo/`
- `mh-ml/`, `pivot-money-hands/`, `candle_patterns/`, `strategies/`, `scripts/`
- `rules.md`, `chart_format.md`, `candle.py`, `conftest.py`, `README.md`

**Что побочно снесено вместе с projects/:**
- ⚠ `~/smc-lib/projects/скользящие/.venv` — Python 3.11 venv с PyTorch 2.11+cu128. Пересоздать когда понадобится ML (uv + cu128 wheel). Memory обновлена.

**Финальные диски PC1:**

| Диск | Free | Назначение |
|---|---|---|
| C: | 127 GB | Windows only |
| **G:** | **1.86 TB** | **WSL VHDX (49 GB) + всё будущее ML** |

## Открытые задачи

- Перезапустить event_detector_v11 + snapshot_v6 на PC1 после cleanup (cleanup только убрал лишние columns, не должно повлиять на core logic, но re-run полезен для чистоты артефактов). 1m CSV придётся сначала скопировать с Mac обратно (`scp ~/traid-bot/data/BTCUSDT_1m_vic_vadim.csv vadim-pc:traid-bot/data/`).
- Пересоздать venv когда нужен будет ML: `cd ~/smc-lib/projects/<new>/ && uv venv --python 3.11 && uv pip install torch --index-url https://download.pytorch.org/whl/cu128`.
- v4 baseline (отложенное): hierarchical multi-stage labels (#15) + LTF context features (#14) + i-FVG canon-based stop (#17) — на уровне baseline проекта, не библиотеки.
- Опционально: `Optimize-VHD -Path G:\WSL\Ubuntu-22.04\ext4.vhdx -Mode Full` чтобы сжать VHDX (внутри 16 GB used, файл 49 GB — после Optimize сожмётся до ~16-20 GB).

## Связанное

- [[2026-06-17-живой-рынок-v8-v11-cleanup]] — предыдущая сессия сегодня
- [[универсальная-библиотека-поиск-элементов-snapshot-агностик]] — decision
- [[ml-snapshot-not-trajectory]] — общий принцип «ML видит snapshot, не trajectory» (теперь сильнее: snapshot инвариантен, trajectory строит проект)
