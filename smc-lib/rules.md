# Правила — справочник по элементам

> **Назначение.** Общие правила, характеризующие особые условия и закономерности рынка. Применимы ко всем SMC-элементам и паттернам (не специфичны для конкретного элемента).

---

## Правило 1 — Закрепление цены за уровнем

**Определение.** Закрепление цены — ситуация, при которой котировки пробивают важный уровень (поддержки или сопротивления) и остаются за его пределами.

**Условия закрепления:**

- **Пробойная свеча** — должна пробить уровень и уверенно закрыться за его пределами. Желательно с большим телом, а не длинной тенью (тень = отвергнутый пробой).
- **Подтверждающие свечи** — как минимум **три** последующие свечи имеют **и открытие, и закрытие** за пробитым уровнем. Доказывают, что цена не вернулась обратно (т. е. пробой не ложный).

**Минимум для закрепления** = 4 последовательные свечи: пробойная + 3 подтверждающие (у каждой из 3 — open и close за уровнем).

---

## Правило 2 — Заполнение зоны интереса (mitigation)

**Определение.** Заполнение (mitigation) зоны интереса — изменение её актуального состояния при взаимодействии с ценой: частичное сжатие, полное потребление или одноразовая отработка точечного уровня. Конкретная модель зависит от типа зоны.

### Модель 1 — Wick-fill (постепенное сжатие)

При каждом касании wick'ом зона сжимается до точки максимального проникновения. Кумулятивно — каждое последующее касание сжимает ещё больше.

- **LONG zone** `[zone_lo, zone_hi]` (support снизу): при `low ≤ zone_hi`
  - `low > zone_lo` → зона сжимается до `[zone_lo, low]`
  - `low ≤ zone_lo` → **CONSUMED**
- **SHORT zone** `[zone_lo, zone_hi]` (resistance сверху): при `high ≥ zone_lo`
  - `high < zone_hi` → зона сжимается до `[high, zone_hi]`
  - `high ≥ zone_hi` → **CONSUMED**

**Семантика.** Institutional zones (OB / FVG / RDRB / block_orders) могут тестироваться многократно — каждое касание потребляет часть untraded liquidity.

### Модель 2 — First-touch (одноразовое потребление)

Первое касание wick'ом любого уровня зоны → зона полностью **CONSUMED** (без постепенного сжатия).

**Семантика.** Одноразовые rejection-маркеры (RB, liquidity-marker ob_liq) — функция «отработана» при первом контакте, далее зона не actionable.

### Модель 3 — Sweep (касание точечного level)

Wick касается или проходит за level → **CONSUMED**.

- **Fractal:** FH swept = `high > level`; FL swept = `low < level`.
- **Marubozu (open level):** bull (`open == low`) — `low ≤ open`; bear (`open == high`) — `high ≥ open`.
- **VWAP (anchored):** SHORT (от FH) — `high(t) > VWAP(t)`; LONG (от FL) — `low(t) < VWAP(t)`. Уровень `VWAP(t)` time-varying (дрейфует с накоплением volume).

**Семантика.** Точечная liquidity (fractal stops) или imbalance-target (marubozu open) или equilibrium-line (anchored VWAP) — однократный stop hunt / тест уровня.

### Привязка моделей к элементам

| Группа | Модель |
|---|---|
| OB, block_orders, FVG, i-FVG, RDRB POI, i-RDRB POI | wick-fill |
| RB, ob_liq | first-touch |
| Fractal (level), Marubozu (open), **VWAP (anchored)** | sweep |

Полная сводная таблица и геометрия зон — [`elements/zone_of_interest.md`](./elements/zone_of_interest.md), раздел «Mitigation».

---

## Правило 3 — [ARCHIVED 2026-06-14]

⚠ Правило 3 (VC — Volume Confirmation) **архивировано** и перенесено в `~/smc-lib/projects/_корзина/rule_3_vc_volume_confirmation.md`. Концепция VC как самостоятельного предикат-правила deprecated.

**Зональная реализация остаётся:** элемент `elements/ob_vc/` со своим расширенным каноном (см. `elements/ob_vc/definition.md`). Standalone VC predicate (`vc/`) — historical artifact.

Нумерация остальных правил **не меняется** (Правила 4–13 сохраняют свои номера для устойчивости backlinks).

---

## Правило 4 — [ARCHIVED 2026-06-14]

⚠ Правило 4 (LTF FVG усиливает значимость HTF OB, было в разработке) **архивировано** и перенесено в `~/smc-lib/projects/_корзина/rule_4_ltf_fvg_strengthens_htf_ob.md`. Концепция частично перешла в элемент `elements/ob_vc/` через partial overlap и condition #5 spatial range.

---

## Правило 5 — [ARCHIVED 2026-06-14]

⚠ Правило 5 (Основная стратегия ASVK — VC внутри HTF-зоны) **архивировано** и перенесено в `~/smc-lib/projects/_корзина/rule_5_asvk_strategy_vc_in_htf_zone.md`. Конкретные инстанциации стратегии (1.1.1 и др.) остаются в стратегических заметках проектов ASVK.

---

## Правило 6 — Построение VWAPs ASVK (anchored, dynamic от D-фрактала)

**Принцип.** Anchored VWAP от D-фрактала строится с **динамическим** anchor'ом в окне свечи `i+1` (бар, следующий за пивотом). Anchor пересчитывается с шагом **15m**, при появлении каждой новой свечи выбирается позиция, дающая лучший результат.

### Параметры

| Параметр | Значение |
|---|---|
| **Базовый объект** | Подтверждённый D-фрактал (Williams N=2) |
| **Диапазон anchor** | Внутри D-свечи `i+1` (бар сразу после пивота). Размер = 24h |
| **Шаг сетки** | 15m → **96 candidate positions** (0h, +0:15, +0:30, …, +23:45) |
| **Re-evaluation cadence** | На закрытии **каждой новой свечи** (LTF cascade или 15m baseline) |
| **Критерий «лучше»** | **Max composite effectiveness** (см. `~/smc-lib/indicators/vwap_effectiveness.py`) |
| **Anchor drift** | Anchor может перемещаться в пределах окна `i+1` от bar к bar, **сохраняя только финальный выбор для текущего момента** |

### Алгоритм

```
для D-фрактала f:
  anchor_window = [f.pivot_close, f.pivot_close + 24h]
  candidates = [anchor_window.start + k * 15m  for k in 0..95]   # 96 anchor-кандидатов

  на закрытии каждой новой свечи (любого TF cascade):
    for c in candidates (только те, у которых c ≤ now):
      compute composite_c = composite_effectiveness(c, LTF cascade)
    current_anchor = argmax_c (composite_c)
    use VWAP(current_anchor) как актуальный уровень
```

### Семантика

- **Раннее время фрактала** (мало новых баров после `i+1`): кандидаты совпадают, выбор почти произвольный — может прыгать.
- **Через 1-3 дня** после `i+1`: cascade накапливает interactions → composite дифференцируется → выбор стабилизируется.
- **Долгосрочно**: anchor «фиксируется» в определённой 15m-позиции, дающей максимум respect.

Это **forward-adaptive** методология: индикатор не lookahead-биасный (для t = текущий момент использует только данные ≤ t), но сам anchor выбирается оптимально под наблюдаемую историю.

### Расхождение с Method 1 (close pivot)

| Метрика | M1 (close pivot, фикс.) | Правило 6 (динамический) |
|---|---|---|
| Среднее composite на 100 D-фракталах | 0.528 | до 0.552 (M2_best ex-post) |
| Детерминизм | да | нет (anchor drift) |
| Простота расчёта | один anchor | 96 кандидатов, переоценка |
| Применимость | сразу | требует bar-by-bar recalc |

Правило 6 — **canonical способ** построения VWAPs ASVK. M1 — упрощённая baseline.

### Cascade для composite

Default: **1h, 2h, 4h, 6h, 8h, 12h** (6 LTF, все ниже D anchor TF).

### Артефакты

- Code: `~/smc-lib/indicators/vwap_anchored.py` (statika, базовая формула)
- Effectiveness scoring: `~/smc-lib/indicators/vwap_effectiveness.py`
- Test scripts: `~/smc-lib/scripts/vwap_strategy_d_50_anchors.py`, `vwap_compare_methods_d_100.py`
- Реализация dynamic-anchor: **TBD** (расширение vwap_anchored.py для bar-by-bar selection из 96 кандидатов)

---

## Правило 7 — TrendLine ASVK: канонические length 78 и 200

**Принцип.** При использовании TrendLine ASVK (Hull MA) везде в библиотеке/проектах **по умолчанию применяются две длины: 78 и 200**. Любые другие значения требуют явного обоснования.

### Параметры

| Параметр | Значение | Применение |
|---|---|---|
| **Mode** | `Hma` (Hull MA) | default; `Ehma`/`Thma` — только если явно указано |
| **Length 1** | **78** | основной TrendLine (= 49 × 1.6 в Pine-нотации) |
| **Length 2** | **200** | медленный TrendLine |
| **Source** | `close` | default |
| **Value semantics** | **LIVE** (с close предыдущего бара) | strict-causal: HMA[i] = значение, отображаемое на чарте в момент формирования бара i до его close |
| **Таймфреймы (типовые)** | 12h, D | other TF допустимы, но эталон — эти |

### Семантика LIVE

> Значение индикатора на pivot bar `i` = значение, вычисленное при close предыдущего бара (i-1). Это то значение, которое отображается на чарте во время формирования бара `i`, до его close. Strict-causal — нет lookahead-биаса.

### Триггеры взаимодействия

| Событие | Условие | Direction |
|---|---|---|
| **Sweep level** | wick(bar) пересекает HMA(i) И close(bar) обратно за уровень | FH ↔ SHORT wick сверху; FL ↔ LONG wick снизу |
| **Cross** | close меняет сторону HMA относительно предыдущего бара | direction = новая сторона |

### Происхождение

Эти параметры приняты в проекте **Pred-12h** (см. [`projects/pred12h-fractal-three-candles.md`](./projects/pred12h-fractal-three-candles.md)):
- **С5** = sweep HMA-78 на (12h ∪ D), LIVE → P(W) **67.0%**, 5 imp
- **С6** = sweep HMA-200 на D, LIVE → P(W) **81.6%**, 1 imp

### Артефакты

- Code: `~/smc-lib/indicators/trend_line_asvk.py`
  - `trend_line_hma_78(closes)` — helper для length=78
  - `trend_line_hma_200(closes)` — helper для length=200
- Pine reference: `~/traid-bot/research/asvk_trend_line/plot_asvk_trend_line.py`

### Прочее

При появлении нового кандидата длины (например 100 или 50) сначала проверяем edge vs canon 78/200 на baseline; принимается только при существенном lift и не как замена, а как дополнительный slot.

---

## Правило 8 — Движение цены

**Принцип.** Цена движется как **магнит между двумя классами зон** — скоплениями ликвидности и ценовыми неэффективностями. Крупный капитал использует эти зоны для исполнения заявок, формируя базовую механику движения любого финансового рынка.

### Два класса притяжения

| Класс | Метафора | Что это | Канон-элементы |
|---|---|---|---|
| **Ликвидность** | ⛽ Топливо | Скопления ордеров (стопы розницы, лимитки) — крупный игрок «собирает» их для набора позиции | `fractal`, `rb`, `ob_liq.liq_zone` |
| **Неэффективность** | 🧲 Магнит | Дисбаланс buyers/sellers — резкое импульсное движение, рынок не успел сформировать справедливую цену | `fvg`, `i_fvg`, `marubozu` (тело) |

> Третий класс — **блок** (OB, RDRB, block_orders, ob_liq.zone) — это **точки исполнения** institutional orders («наторгованный блок»), а не магниты. См. [[memory:zone-class-liquidity-inefficiency-block|таксономия классов]].

> ⚠ Историческое название этого класса — **efficiency** (до 2026-05-29). Переименован в **«блок»** для согласованности с пользовательским термином «блок наторгованный» (maxV ASVK).

### Цикл движения цены (3 фазы)

```
Phase 1: Сбор ликвидности
  ↓ цена идёт к liquidity-зоне (стопам/лимиткам)
  ↓ wick-импульс снимает ордера
  ↓ крупный игрок набирает позицию против розницы

Phase 2: Заполнение неэффективности
  ↓ после snap-back цена возвращается к ближайшему inefficiency-магниту
  ↓ FVG/i-FVG/marubozu заполняется → справедливая цена восстановлена
  ↓ имбаланс закрыт

Phase 3: Поход к новой цели
  ↓ после mitigation отбрасывается от блок-зоны (OB/RDRB/block_orders)
  ↓ direction: к следующей liquidity-цели (FH/FL противоположной стороны)
  ↓ цикл повторяется на новом уровне
```

### Семантика для зон (как использовать в анализе)

| Тип взаимодействия | Что значит |
|---|---|
| **Sweep liquidity** (Phase 1) | Wick через fractal/rb/ob_liq.liq_zone — крупный игрок «съел» стопы. После sweep — потенциальный reversal |
| **Fill inefficiency** (Phase 2) | Wick-fill FVG/i-FVG или sweep marubozu open — закрытие имбаланса. Логичный intermediate-target |
| **React on блок** (Phase 3) | Touch OB/RDRB/block_orders с continuation — institutional order сработал, отскок в направлении HTF-тренда |

### Применение

1. **Идентифицируй классы**: на каждой зоне near price — это liquidity / inefficiency / блок?
2. **Найди ближайшую liquidity** (магнит для Phase 1) — куда цена «пойдёт за стопами»
3. **Найди ближайшую inefficiency** (магнит для Phase 2) — куда возвратится после sweep
4. **Найди блок-уровень** — где institutional орден будет исполнен, точка реакции
5. **Цикл прогноз**: liquidity → inefficiency → блок → next liquidity

### Композиция с другими правилами

| Правило | Связь |
|---|---|
| [[Правило 1]] (закрепление) | Phase 3 завершается closing-confirmation за блок-уровнем |
| [[Правило 2]] (mitigation) | Inefficiency-зоны mitigated через wick-fill; liquidity — first-touch / sweep |
| [[Правило 5 (ARCHIVED)]] (стратегия ASVK) | Phase 3 (reaction на блок-зоне) + VC = entry-сигнал |
| [[Правило 6]] (VWAPs) | Inefficiency-уровень часто совпадает с эффективным VWAP — confluence-магнит |
| [[Правило 7]] (TrendLine) | HMA-cross определяет direction Phase 3 (к какой следующей liquidity-цели) |

### Связи (memories)

- [[memory:feedback-untraded-area-is-magnet]] — fundamental SMC принцип: непроторгованная область притягивает цену
- [[memory:zone-class-liquidity-inefficiency-block]] — таксономия трёх классов
- [[memory:feedback-fractal-liquidity-strength-and-sweep]] — сила liquidity = TF × возраст × cluster; HTF sweep «проглатывает» LTF

### Practical-чек для каждой зоны

При анализе зоны спрашивай:
1. К какому классу относится? (liquidity / inefficiency / блок)
2. Mitigated или actionable? (Правило 2)
3. На каком TF? (HTF доминирует)
4. Расположена `above` / `inside` / `below` относительно цены?
5. Если liquidity или inefficiency → это **магнит**
6. Если блок → это **точка реакции**, не магнит

> **Главное**: цена не двигается «случайно», и не только «по трендам/уровням». Она **охотится за топливом** (liquidity) и **заполняет пустоты** (inefficiency). Блок-зоны — это места, где institutional капитал ставит/исполняет ордера.

---

## Правило 9 — Heavy compute на PC1/PC2; правила взаимодействия

**Принцип.** Mac M5 = интерактив, экспертные заключения, plots. **Heavy ML / GPU / walk-forward / multi-symbol** — на PC1/PC2 через live SSH. Mac пишет код / inference / анализ результатов.

### Hardware

| Машина | Назначение | Спецификация |
|---|---|---|
| **MacBook Air M5** | Интерактив, plots, lightweight inference, экспертные заключения | M5 SoC, macOS |
| **PC1** | GPU-ML (топовая GPU), deep learning | Ryzen 7 7700 (16T), **RTX 5070 Ti**, 32 GB, Windows 11 + WSL2 |
| **PC2** | Multi-thread CPU (grid-search, walk-forward) | **i5-14600KF (20T)**, RTX 4070, 32 GB DDR5, Windows 11 + WSL2 |

### Выбор PC под задачу

| Задача | PC | Почему |
|---|---|---|
| GPU-ML (Transformer/TCN/LSTM/deep RL) | **PC1** | RTX 5070 Ti |
| Grid-search / hyperparam sweep | **PC2** | 20 потоков |
| Walk-forward suites | **PC2** | 14 cores |
| Generic LightGBM/XGBoost | любой | похоже |

**Правило по нагрузке:** на PC1 — **до 2 light tasks** ИЛИ **1 heavy**. На PC2 — **только 1 task** (RAM 15 GB WSL constraint).

### Что выносить на PC

| Категория | Примеры |
|---|---|
| **GPU-ML** | LSTM/Transformer/TCN на 1m OHLCV, deep sequence models |
| **Heavy training** | LightGBM/XGBoost на >1M строк, hyperparam sweep |
| **Walk-forward suites** | 6y BTC × несколько cadence/window |
| **Multi-symbol** | Полный 1m re-labelling, BTC+ETH+SOL rebuilds |
| **Backtests** | 6y стратегии с execution + slippage |

### Что НЕ выносить (остаётся на Mac)

- Экспертные заключения (`zones_opinion.py`, `expert/opinion.py`, `expert/chart.py`)
- Plot-скрипты одиночных графиков
- Inference на одной точке времени (cli.py)
- Любая интерактивная работа / debug

---

## 🔌 Подключение к PC

### Сетевые пути (по приоритету)

| Метод | Address | Когда работает | Когда падает |
|---|---|---|---|
| **1. LAN SSH** | `192.168.0.X:2222` (Wi-Fi/Ethernet) | DHCP стабильный | После reboot IP может сменится |
| **2. Tailscale SSH** | `100.X.X.X:2222` | если daemon up на Windows | Сбивает VPN (happ-tun перехватывает TCP) |

### SSH config (Mac side)

`~/.ssh/config`:
```
Host vadim-pc
    HostName 192.168.0.156   # ⚠ обновлять после reboot если DHCP сменил
    User vadim
    Port 2222
    IdentityFile ~/.ssh/id_ed25519

Host vadim-pc2
    HostName 192.168.0.75
    User vadim
    Port 2222
    IdentityFile ~/.ssh/id_ed25519
```

### Топология (WSL2 NAT mode)

```
Mac → Windows host (192.168.0.X:2222) ─[netsh portproxy]─→ WSL2 (192.168.85.X:2222) → sshd
                                                                ↑
                                                       vEthernet (WSL Hyper-V firewall)
```

WSL2 в **NAT mode** (не mirrored — последний ломал OOBE при VPN на хосте per [[reference-pc-remote-access]]).

Tailscale IP на Mac: `100.74.207.26`. На PC1: `100.90.234.65`. На PC2: `100.100.38.71`.

---

## 🔄 Post-reboot recovery checklist

Когда SSH timeout после reboot Windows — **последовательно**:

### 1. Проверить достижимость на L3

```bash
# С Mac:
ping -c 2 192.168.0.156          # PC1 LAN IP — жив ли
ping -c 2 100.90.234.65           # PC1 Tailscale — жив ли
tailscale status                    # видны ли все пиры
```

Если **оба ping fail** → user не залогинен в Windows, либо PC выключен.

### 2. Узнать новый Windows IP (DHCP мог сменить)

На PC1 PowerShell:
```powershell
ipconfig | findstr IPv4
```

Если **`192.168.0.X` сменился** — обновить `~/.ssh/config` HostName на Mac.

### 3. Проверить Tailscale daemon

На PC1:
```powershell
tailscale status
```
Если все peers с trailing `-` → `tailscale up`.

### 4. Узнать новый WSL IP (WSL2 NAT subnet тоже DHCP)

```powershell
wsl hostname -I
```

Обычно `192.168.85.X` или `172.X.X.X`.

### 5. Восстановить netsh portproxy (НЕ persistent если WSL IP сменился)

```powershell
netsh interface portproxy reset
netsh interface portproxy add v4tov4 listenport=2222 listenaddress=0.0.0.0 connectport=2222 connectaddress=<WSL_IP>
netsh interface portproxy show all   # verify
```

### 6. Hyper-V firewall (КРИТИЧНО — сбрасывается на Block)

```powershell
Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore | Select Name, DefaultInboundAction
# Если DefaultInboundAction: Block →
Set-NetFirewallHyperVVMSetting -Name "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}" -DefaultInboundAction Allow
```

VMSetting GUID может быть другим — взять из `Get-NetFirewallHyperVVMSetting`.

### 7. Static route на WSL subnet (если sing-tun VPN перехватывает)

```powershell
Get-NetAdapter -Name "vEthernet (WSL*" | Select ifIndex
New-NetRoute -DestinationPrefix "192.168.85.0/24" -InterfaceIndex <ifIndex> -NextHop "0.0.0.0" -RouteMetric 1
```

### 8. Final test

```bash
# С Mac:
ssh vadim-pc 'echo OK; uptime'
```

Если работает → переход к запуску задач.

---

## ⚠ VPN interference (Happ / sing-tun)

VPN на Windows (Happ + sing-tun TUN driver) **перехватывает весь TCP outbound**. Симптомы:

| Симптом | Причина | Решение |
|---|---|---|
| `ping` работает, `ssh` timeout | sing-tun интерсептит TCP но не ICMP | bypass list в Happ |
| `tailscale ping → pong`, но `ssh` timeout | Tailscale OK, Windows→WSL forward хайджачен | bypass `192.168.85.0/24` |
| `Connection closed by remote` без banner exchange | sing-tun сбрасывает forward connection | bypass или отключить VPN на время |

**Обязательно в Happ → Settings → Bypass / Direct routes:**
- `192.168.0.0/16` — вся локальная сеть
- `192.168.85.0/24` — WSL subnet (NAT)
- `192.168.80.0/24` — vEthernet WSL host
- `100.64.0.0/10` — Tailscale CGNAT

Альтернатива — отключить Happ на время heavy compute (через GUI или `Disable-NetAdapter -Name happ-tun`).

---

## 💾 Saved state — что выживает crash/reboot

| Артефакт | Survives | Где |
|---|---|---|
| JSON results | ✅ | `~/smc-lib/projects/.../results/` |
| Per-fold `*.npy` (probs/labels/indices) | ✅ | per-fold autosave |
| Model checkpoints (`.pt`) | ✅ если сохранены | `phase3_checkpoint/`, `~/.cache/...` |
| Training mid-fold | ❌ | без epoch-checkpoint потеряется |
| Queue/bash scripts (background) | ❌ | надо перезапускать |
| netsh portproxy | ⚠ persistent правило, но если WSL IP сменился — не работает |
| Hyper-V firewall settings | ❌ | сбрасываются на Block после reboot |
| Static routes `New-NetRoute` | ⚠ persistent (default PolicyStore) | проверять после reboot |
| Tailscale auth | ✅ | login persistent |
| WSL2 systemd ssh enabled | ✅ | sshd auto-start при запуске WSL |
| WSL2 auto-start on Windows boot | ❌ | требует Task Scheduler настройку |

### Workflow для длинных задач (>1 час)

- **Per-fold autosave** в training scripts: после каждого fold → `np.save(probs)`, `np.save(labels)`, `JSON results.append(...)` flush на disk
- **Resume capability:** при restart проверить `ls results/` → пропустить уже завершённые folds → продолжить с следующего
- **Queue scripts** (например `wait for vc_lean → run phase3_train`) теряются → re-launch вручную

---

## ⚡ Параллелизм (CPU loading)

**Цель — CPU 80-90%** во время вычислений. «PC должен дымиться». Если <30% — недогружен, переоптимизировать.

| Уровень | Механизм | Применение |
|---|---|---|
| **Inner** (intra-model) | `n_jobs=-1` | LightGBM, XGBoost, RandomForest |
| **Outer** (independent tasks) | `joblib.Parallel(backend=threading или loky)` | Multi-seed, multi-fold, multi-config |
| **Vectorization** | numpy / pandas | Feature engineering |

### Threading config по PC

| PC | Total threads | Outer × Inner | Target loading |
|---|---|---|---|
| **PC1** (16T) | 16 | 4×4 или 8×2 = 16 | 90-100% |
| **PC2** (20T) | 20 | 6×3 или 4×5 = 18-20 | 90% |

**Outer × Inner НЕ должно превышать total threads** (oversubscription = context switching = замедление).

### Выбор библиотек

| Библиотека | Параллелизм | Использовать |
|---|---|---|
| **LightGBM** (`n_jobs=-1`) | ✅ excellent OpenMP | **Default** для tabular ML |
| **XGBoost** (`n_jobs=-1`) | ✅ good OpenMP | Альтернатива LightGBM |
| sklearn `HistGradientBoostingRegressor` | ⚠ <50% cores | Только если нет LightGBM |
| sklearn `RandomForestClassifier` (`n_jobs=-1`) | ✅ хорошо | OK |
| **PyTorch** | GPU родной, CPU `torch.set_num_threads()` | GPU-heavy |
| Чистый Python loops | ❌ single-thread | НЕ использовать |

### Pitfalls

| Pitfall | Симптом | Решение |
|---|---|---|
| sklearn HGBR default | CPU <20% на 20T | LightGBM `n_jobs=-1` |
| Sequential horizons/configs | CPU плохо нагружен | `joblib.Parallel` outer |
| Oversubscription (Outer × Inner > total) | CPU 100% но slower | Снизить Outer×Inner ≤ total |
| Default `n_jobs=1` | Один поток | Явно `n_jobs=-1` |
| `joblib backend="loky"` с большими numpy | Pickling overhead | `backend="threading"` |

### Cancellation strategy

Если PC <30% CPU и runtime растягивается — **отменить и перезапустить с оптимизацией ВЫГОДНЕЕ чем ждать**. Пример (2026-05-29):
- HGBR sequential 3064 features = 10-18 ч
- LightGBM parallel n_jobs=3 × 6 horizons = 1-2 ч
- Решение перезапустить экономит 8-16 ч.

---

## Windows pitfalls (при создании скриптов для PC)

- ⚠ **CP1251 console** — не использовать Unicode (Δ, ★, 🔥) в `print()`; ASCII или `chcp 65001`
- ⚠ Path separator — `pathlib.Path` или `os.path.join`, не hardcoded `/`
- ⚠ GPU check — `torch.cuda.is_available()` и `device = "cuda"` (не MPS)
- ⚠ **CRLF line endings** в `.bat` (Mac пишет LF → Windows cmd может не парсить)
- ⚠ Cyrillic username path → `pip install --only-binary=:all:` (wheels only)

---

## Триггеры применения Правила 9

| Сигнал | Действие |
|---|---|
| Walk-forward suite 5+ лет, >1 cadence | → PC |
| LightGBM/XGBoost на 1M+ строк | → PC |
| GPU-ML (PyTorch/TensorFlow обучение) | → PC |
| Multi-symbol полный rebuild | → PC |
| Estimated runtime > 30 мин на M5 | → PC |
| Estimated peak RAM > 8 GB | → PC |
| Iterative dev/debug | → Mac (даже медленнее) |

---

## Правило 10 — Канонический формат вывода «элементов библиотеки»

**Принцип.** При запросе пользователя показать «**элементы библиотеки**» (или «покажи элементы», «какие элементы», «что в `elements/`») использовать **строго фиксированный 4-секционный формат**. Не упрощать, не пропускать секции, не менять порядок колонок.

### Триггеры применения

| Фраза пользователя | Действие |
|---|---|
| «**элементы библиотеки**» | → формат Правило 10 |
| «покажи элементы» / «какие элементы» / «что в elements/» | → формат Правило 10 |
| «список элементов» / «инвентарь зон» | → формат Правило 10 |

### Источник истины

- Слаги: `ls ~/smc-lib/elements/*/`
- Заголовки: первая строка `definition.md` каждой папки
- Сигнатуры детекторов: `grep "^def " ~/smc-lib/elements/*/code.py`
- Класс зоны: [[Правило 8]] + [[memory:zone-class-liquidity-inefficiency-block]]
- Mitigation: [[Правило 2]]
- Активные в prediction-algo: `~/smc-lib/prediction-algo/zones.py` константа `ALL_TYPES`

### Исключения (НЕ показывать в перечне)

Папки в `elements/`, которые **не отображаются** при выводе по триггерам Правила 10:

| Слаг | Почему исключён |
|---|---|
| `ob_sweep_liq_4candles` | Retrospective event/marker — фиксирует уже свершившийся sweep. Не forward-looking zone, используется как feature в детекции/labelling других элементов, но не как самостоятельная зона интереса. Зафиксировано 2026-05-29 |
| `rb` | Исключён из перечня по решению пользователя 2026-05-29. Папка остаётся на диске, детектор работает. В `ALL_TYPES` для prediction-algo остаётся (если иное не указано) |

Эти папки остаются на диске (полезны как feature/context), но в Rule 10 output для них нет строки. Если потребуется отдельный перечень «retrospective markers» — он формируется по другому триггеру.

### Формат вывода (4 секции, именно в этом порядке)

#### Секция 1 — Главная таблица «Элементы»

**Порядок строк — строго по классу зоны** (по циклу Правила 8: liquidity → inefficiency → блок → composite). Внутри класса — по сложности (от простого к составному) или по алфавиту слага. Между группами — заголовочная строка с emoji класса для визуального разделения.

**Колонки (унифицированы 2026-05-29):**
- `Слаг` — snake_case как имя папки
- `Заголовок` — из definition.md
- `Свечей` — минимум для детекции
- `Mitigation` — wick-fill / first-touch / sweep
- `Геометрия` — **range** (диапазон `[lo, hi]`) или **level** (точечный уровень-значение). Это **главная различающая ось** — фрактал и марубозу выступают как уровень (значение), потому что за диапазоном точно не знаем где разворот; все остальные имеют чёткий диапазон.
- `Направление` — **всегда `long / short`** (трейдинговое ожидание после взаимодействия). Внутренние code-метки исторически разные (high/low у фрактала, top/bottom у RB) → mapping см. ниже.

Колонка `Класс` НЕ нужна внутри таблицы — класс задан заголовком группы.

### Mapping внутренних code-меток → отображаемое направление

В коде `direction` field у `ActiveZone` использует исторические значения. Display всегда сводит к `long/short`:

| Элемент | Internal `direction` | Display `Направление` | Семантика |
|---|---|---|---|
| OB, block_orders, FVG, i_fvg, RDRB, i_rdrb, ob_liq, marubozu, ob_vc | `long` / `short` | long / short | без изменений |
| **RB** | `bottom` / `top` | **long / short** | bottom = support (long), top = resistance (short) |
| **fractal** | `low` / `high` | **long / short** | FL sweep → long setup, FH sweep → short setup |

Шаблон:

```
### ⛽ Liquidity (топливо — Phase 1 в Правиле 8)
| Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление |
|---|---|---|---|---|---|
| rb | RB (Rejection Block) | 1 | first-touch | range | long / short |
| fractal | Fractal (Williams) | 2N+1 (def 5) | sweep | **level** | long / short |

### 🧲 Inefficiency (магнит — Phase 2)
| Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление |
|---|---|---|---|---|---|
| fvg | FVG (Fair Value Gap) | 3 | wick-fill | range | long / short |
| i_fvg | i-FVG (Inverse FVG) | 6+ | wick-fill на `overlap(shrunk_A, B.zone)` (canon v2 2026-06-15) | range | long / short |

### 🎯 Блок (точка реакции — Phase 3)
| Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление |
|---|---|---|---|---|---|
| ob | OB (Order Block) | 2 | wick-fill | range | long / short |
| block_orders | Блок ордеров | 3+ (N₁+N₂+1) | wick-fill | range | long / short |
| rdrb | RDRB | 3 | wick-fill (POI) | range | long / short |
| i_rdrb | i-RDRB | 4 | wick-fill (наследует RDRB) | range | long / short |

### Composite (multi-class)
| Слаг | Заголовок | Свечей | Mitigation | Геометрия | Направление | Композит классов |
|---|---|---|---|---|---|---|
| ob_liq | OB с уровнем ликвидности | 2 | first-touch | range | long / short | 🎯 блок (zone) + ⛽ liquidity (liq_zone) |
| marubozu | Marubozu | 1 | sweep (open) | **level** | long / short | 🧲 inefficiency (body) + ⛽ liquidity (open level) |
```

В composite-группе добавляется седьмая колонка «Композит классов».

#### Секция 2 — Структура каждого элемента

Code block с layout папки + что лежит:

```
~/smc-lib/elements/<slug>/
├── definition.md   — canon: что это, геометрия зоны, условия, mitigation
└── code.py         — детектор detect_<slug>(...) → <Element> | None
```

#### Секция 3 — Сигнатуры детекторов

Таблица: `Элемент | Сигнатура | Возврат` по каждому элементу.

#### Секция 4 — Что используется в prediction-algo

Цитата константы `ALL_TYPES` из `zones.py` + пояснение что исключено и почему. Обязательно указать причину исключения `ob_sweep_liq_4candles` (retrospective event).

#### Секция 5 — Не-элементы (рядом с `elements/`)

Краткая ссылка на:
- `~/smc-lib/patterns/` — полные setup-паттерны (i_rdrb_fvg, run_3candles_sweep)
- `~/smc-lib/elements/ob_vc/` — Volume Confirmation (предикат, не зона; см. [[Правило 3 (ARCHIVED)]])
- `~/smc-lib/indicators/` — VWAP, HMA TrendLine, MoneyHands и др.

### Что НЕ включать

- Историю изменений каждого элемента (это в session-notes)
- Подробную геометрию зон (это в `elements/zone_of_interest.md`, ссылаться)
- Trading strategy / entry / SL — это уровень патернов, не элементов
- Тестовое покрытие построчно (можно одной строкой «test-файлов нет» — это статус-факт)

### Почему именно так

Пользователь хочет **быстро восстановить инвентарь** при работе с библиотекой. Структура «таблица → структура → API → активность → соседи» отвечает на 4 типичных вопроса в одном выводе:
1. Что у нас есть? → секция 1
2. Где это лежит? → секция 2
3. Как этим пользоваться? → секция 3
4. Что реально работает в production? → секция 4
5. Что рядом, но не элементы? → секция 5

Зафиксировано 2026-05-29 после успешного презентационного формата в сессии reverification + roadmap.

---

## Правило 11 — [ARCHIVED 2026-06-14]

⚠ Правило 11 (Компрессия — эффективное ценообразование, было в разработке) **архивировано** и перенесено в `~/smc-lib/projects/_корзина/rule_11_compression_efficient_pricing.md`. Концепция компрессии deprecated как самостоятельное правило.

---

## Правило 12 — [ARCHIVED 2026-06-14]

⚠ Правило 12 (Макроиндикаторы TOTALES и USDT.D) **архивировано** и перенесено в `~/smc-lib/projects/_корзина/rule_12_macro_totales_usdtd.md`. Macro features whitelist остаётся в memory `feedback-macro-features-preference`.

---

## Правило 13 — Канонический формат «Ключевые выводы из чтения»

**Принцип.** При запросе пользователя «**изучи книги**», «**ключевые выводы из чтения**», «**прочитай и сделай выводы**», «**что взять из литературы**» — использовать строго фиксированный формат **action-oriented findings** (не summary). Цель — actionable items для immediate work, не литературное резюме.

### Триггеры применения

| Фраза пользователя | Действие |
|---|---|
| «**изучи** [книги/литературу/PDFs]» | → формат Правило 13 |
| «**ключевые выводы из чтения**» / «**что взять из чтения**» | → формат Правило 13 |
| «**прочитай и сделай выводы**» / «**summary книги**» | → формат Правило 13 |
| «**что применить из** [книги]» | → формат Правило 13 |

### Формат вывода

Заголовок секции: `## Ключевые выводы из чтения`

Под каждую книгу — **одна секция** в порядке релевантности (⭐⭐⭐ → ⭐). Каждая секция:

#### 1. Заголовок секции:
```
### 🎯 <Автор / Краткое имя книги> — <направление применения>
```

Emoji выбирается по характеру книги:
- 🎯 — ML/quant/инфраструктура
- 📊 — volume/orderflow/microstructure
- 🕯 — candlestick/price action
- 📈 — chart patterns / classic TA

Стрелка `→ направление применения` указывает **куда мы это применим** в нашей кодовой базе (force-model, vc/, elements/, etc.).

#### 2. Тело секции — ТОЛЬКО ОДНА из форм:

**Форма A — Таблица (chapter / what to apply):**

```
| Глава / раздел | Что применять (action item) |
|---|---|
| Ch X — <название> | <конкретное действие в нашем коде> |
```

**Форма B — Bullet list (новые primitives / patterns):**

```
N novel <element_type> candidates:
- `slug_1` — короткое определение детектора
- `slug_2` — короткое определение
...
**<concept_name> = <our_existing_concept>** — те же концепции, разная терминология.
```

**Форма C — Краткая ссылка на полный note-файл** (если preview / частичный материал):

```
Preview only — для serious use нужна full edition. <Краткий список потенциального применения, если будет full>.
```

### Структура секции (обязательная)

Каждая секция должна включать:
1. **Заголовок** с emoji + направлением применения (1 строка)
2. **Тело** — таблица (A) ИЛИ bullet list (B) ИЛИ ссылка (C)
3. (опционально) короткий **commentary** на 1-2 предложения с insights

### Что нельзя

- ❌ Длинный summary книги (краткое summary — в `notes_<имя>.md`)
- ❌ Биография автора, история издания
- ❌ Концепции БЕЗ привязки к нашему коду
- ❌ Reading order tips (это для `README.md` библиотеки)

### Что обязательно

- ✓ Каждый action item должен указывать **конкретно** на наш файл/модуль/класс
- ✓ Приоритет ⭐ выставлен и виден
- ✓ Cross-references на наши existing modules через `~/smc-lib/...` paths

### Источник истины

- Детальные заметки по каждой книге: `~/smc-lib/literature/notes_<имя>.md`
- Каталог литературы: `~/smc-lib/literature/README.md`
- Этот формат для вывода в **чат пользователю**, не для записи в файлы

### Связи

- `[[Правило 10]]` — аналогичный канонический формат для «элементов библиотеки»
- `~/smc-lib/literature/` — раздел литература (создан 2026-06-03)
- `[[memory:feedback-elements-library-output-format]]` — родственный feedback memory для формата элементов

---

## Правило 14 — TF anchor canon (Binance/TV standard)

**Принцип.** Все агрегирующие TF в проектах используют **anchor = 0 UTC** (Binance/TradingView standard), кроме **W** (anchor = понедельник 00:00 UTC = TV-стандарт). МСК = UTC+3 (без DST). Зафиксировано 2026-06-14 после верификации на live TV-чарте.

### Сетка boundaries

Все open_time даны в **МСК** (отображаются именно так согласно [[memory:display-time-in-utc-plus-3]]). Соответствующее UTC получается вычитанием 3 часов.

| TF | UTC anchor | МСК boundaries (open_time) | Закрытие последнего бара суток |
|---|---|---|---|
| **1m, 5m, 15m, 30m, 1h, 90m** | anchor-neutral | сетка совпадает независимо от выбора anchor 0 vs CME | — |
| **2h** | 0 UTC | 03, 05, 07, 09, 11, 13, 15, 17, 19, 21, 23, 01 | 03:00 МСК |
| **3h** | 0 UTC | 03, 06, 09, 12, 15, 18, 21, 00 | 03:00 МСК |
| **4h** | 0 UTC | **03, 07, 11, 15, 19, 23** | 03:00 МСК |
| **6h** | 0 UTC | 03, 09, 15, 21 | 03:00 МСК |
| **8h** | 0 UTC | 03, 11, 19 | 03:00 МСК |
| **12h** | 0 UTC | **03, 15** | 03:00 МСК |
| **1D** | 0 UTC | **03** (раз в сутки) | 03:00 МСК |
| **2D** | epoch (1970-01-01 Чт 00:00 UTC) | continuous 48h cycle от epoch — НЕ Mon-reset | переменное |
| **3D** | epoch (1970-01-01 Чт 00:00 UTC) | continuous 72h cycle от epoch — НЕ Mon-reset | переменное |
| **W** | **Monday 00:00 UTC** | пн **03:00** → след. пн 03:00 (TV-стандарт) | пн 03:00 МСК |

### Исключения и спец-кейсы

| TF | Особенность |
|---|---|
| **W** | TV использует Mon-anchor, не epoch. При composeе из LTF: `origin=pd.Timestamp("1970-01-05", tz="UTC")` (понедельник). НЕ `origin='epoch'`. |
| **2D, 3D** | continuous 48h/72h от epoch — **все weekday-кейсы валидны**. Не привязаны к Mon/Thu. См. [[memory:feedback-3d-resample-monday-reset]] (filename misleading, content correct). |
| **M (Monthly)** | TV-стандарт — 1-е число месяца 00:00 UTC = 1-е 03:00 МСК. Зафиксировать при первом использовании в проекте. |
| **CME-anchor** | НЕ используется. Если попадётся data, конвертировать к UTC anchor=0 до aggregation. |

### Алгоритм aggregation 1m → HTF

```python
anchor = 0  # UTC midnight для не-W
b = ts - ((ts - anchor) % tf_ms)
```

Для **W**:
```python
import pandas as pd
df.resample('7D', origin=pd.Timestamp("1970-01-05", tz="UTC"), label='left').agg(...)
```

### Verification protocol (КРИТИЧЕСКИ ВАЖНО)

⚠ Перед изменением фундаментального параметра (anchor) — **подтверждать ≥2 независимыми signals**:
- open_time бара ≥1 + close_time бара ≥1 + length бара
- Желательно — sample на ≥3 разных временных промежутках (разные дни)

**Не верить одиночному user-datapoint** про «OB cur.open = HH:MM МСК» — typo или неточное воспоминание возможны.

### Lesson 2026-06-07 (incident)

Ошибочно сменил anchor на 02:00 МСК (= 23 UTC, CME-anchor) на основе одного user-datapoint про «OB cur.open = 22:00 МСК». Это привело к пересчёту ob-vc и 12h-fractal-new под неправильный anchor. User затем подтвердил **12h closes в 15:00 МСК** → правильный anchor = UTC midnight.

С тех пор требуется ≥2 signals перед сменой anchor.

### Live verification BTCUSDT 2026-06-14

Полная проверка всех TF на live TradingView (BINANCE:BTCUSDT). Все совпало с каноном.

**W (Weekly):**
| ts UNIX | UTC | МСК | weekday |
|---|---|---|---|
| 1779667200 | 2026-05-25 00:00 | 2026-05-25 03:00 | пн |
| 1780272000 | 2026-06-01 00:00 | 2026-06-01 03:00 | пн |
| 1780876800 | 2026-06-08 00:00 | 2026-06-08 03:00 | пн |

W open = понедельник 03:00 МСК ✓ (TV Mon-anchor)

**3D:**
| ts UNIX | UTC | МСК | weekday |
|---|---|---|---|
| 1780704000 | 2026-06-06 00:00 | 2026-06-06 03:00 | сб |
| 1780963200 | 2026-06-09 00:00 | 2026-06-09 03:00 | вт |
| 1781222400 | 2026-06-12 00:00 | 2026-06-12 03:00 | пт |

3D = continuous 72h цикл от epoch (Thu 1970-01-01) — weekday меняется, всегда 03:00 МСК ✓

**2D:**
| ts UNIX | UTC | МСК | weekday |
|---|---|---|---|
| 1781049600 | 2026-06-09 00:00 | 2026-06-09 03:00 | вт |
| 1781222400 | 2026-06-12 00:00 | 2026-06-12 03:00 | пт |  — пропуск: тут шаг 3 дня?? нет, это 2D на другую дату |
| 1781395200 | 2026-06-14 00:00 | 2026-06-14 03:00 | вс |

Примечание: 1781049600 → 1781222400 = 2 дня (verified: 1781222400-1781049600 = 172800s = 2 days). Шаг 2 дня ✓. 2D = continuous 48h от epoch, weekday меняется.

**D (Daily):**
| ts UNIX | UTC | МСК | weekday |
|---|---|---|---|
| 1781222400 | 2026-06-12 00:00 | 2026-06-12 03:00 | пт |
| 1781308800 | 2026-06-13 00:00 | 2026-06-13 03:00 | сб |
| 1781395200 | 2026-06-14 00:00 | 2026-06-14 03:00 | вс |

D open = 03:00 МСК ежедневно ✓

**12h:**
| ts UNIX | UTC | МСК |
|---|---|---|
| 1781352000 | 2026-06-13 12:00 | 2026-06-13 **15:00** |
| 1781395200 | 2026-06-14 00:00 | 2026-06-14 **03:00** |
| 1781438400 | 2026-06-14 12:00 | 2026-06-14 **15:00** |

12h boundaries = **03 и 15** МСК ✓

**6h:**
| ts UNIX | UTC | МСК |
|---|---|---|
| 1781395200 | 2026-06-14 00:00 | 03:00 |
| 1781416800 | 2026-06-14 06:00 | 09:00 |
| 1781438400 | 2026-06-14 12:00 | 15:00 |
| 1781460000 | 2026-06-14 18:00 | 21:00 |

6h boundaries = **03, 09, 15, 21** МСК ✓

**4h:**
| ts UNIX | UTC | МСК |
|---|---|---|
| 1781424000 | 2026-06-14 08:00 | 11:00 |
| 1781438400 | 2026-06-14 12:00 | 15:00 |
| 1781452800 | 2026-06-14 16:00 | 19:00 |
| 1781467200 | 2026-06-14 20:00 | 23:00 |

4h boundaries = **03, 07, 11, 15, 19, 23** МСК ✓

**2h:**
| ts UNIX | UTC | МСК |
|---|---|---|
| 1781445600 | 2026-06-14 14:00 | 17:00 |
| 1781452800 | 2026-06-14 16:00 | 19:00 |
| 1781460000 | 2026-06-14 18:00 | 21:00 |
| 1781467200 | 2026-06-14 20:00 | 23:00 |

2h boundaries = **03, 05, 07, 09, 11, 13, 15, 17, 19, 21, 23, 01** МСК ✓

**90m:**
| ts UNIX | UTC | МСК |
|---|---|---|
| 1781449200 | 2026-06-14 15:00 | 18:00 |
| 1781454600 | 2026-06-14 16:30 | 19:30 |
| 1781460000 | 2026-06-14 18:00 | 21:00 |
| 1781465400 | 2026-06-14 19:30 | 22:30 |

90m boundaries (anchor=0 UTC, 16 баров в сутки):
- UTC: 00:00, 01:30, 03:00, 04:30, 06:00, 07:30, 09:00, 10:30, 12:00, 13:30, 15:00, 16:30, 18:00, 19:30, 21:00, 22:30
- **МСК: 03:00, 04:30, 06:00, 07:30, 09:00, 10:30, 12:00, 13:30, 15:00, 16:30, 18:00, 19:30, 21:00, 22:30, 00:00, 01:30** ✓

**1h:**
| ts UNIX | UTC | МСК |
|---|---|---|
| 1781456400 | 2026-06-14 17:00 | 20:00 |
| 1781460000 | 2026-06-14 18:00 | 21:00 |
| 1781463600 | 2026-06-14 19:00 | 22:00 |
| 1781467200 | 2026-06-14 20:00 | 23:00 |

1h boundaries — каждый час HH:00 UTC = (HH+3):00 МСК ✓ (anchor-neutral в практическом смысле)

### Аналогичная проверка для других TF

90m, 1h, 15m, 30m, 5m, 1m — anchor-neutral на практике (любой anchor 0 vs CME даёт одинаковые boundaries), не требуют дополнительной верификации.

Verification полностью подтвердила canon. Никаких рассогласований.

### Связи

- `[[memory:feedback-htf-anchor-global-rule]]` — feedback memory с этим же правилом (живая ссылка)
- `[[memory:display-time-in-utc-plus-3]]` — отображение времени в чате (МСК)
- `[[memory:weekly-tf-anchor-monday]]` — W-исключение из anchor=0
- `[[memory:feedback-3d-resample-monday-reset]]` — 3D continuous 72h epoch
- `[[memory:btc-data-1m-csv]]` — BTC 1m CSV в UTC (data files stay UTC)
- `~/smc-lib/projects/12h-фракталы/_lib.py::load_htf_bars` — anchor=0 для non-W
- `~/smc-lib/projects/ob-vc-2h/_lib.py::USER_HTF_ANCHOR_MS = 0`

---

## Правило 15 — ob_vc entry canon (deep по n_FVG, wait-window, LIVE индикаторы)

**Принцип.** Канон расчёта entry / SL / TP для `ob_vc` setup'ов с тремя обязательными компонентами:

1. **Два варианта entry** в зависимости от `n_FVG` per-LTF (Type A vs Type B).
2. **Wait-window** между `born_ms` и `entry_fill_ms` ОБЯЗАТЕЛЬНО анализируется как видимая часть графика.
3. **Все индикаторы расчётные LIVE** на момент `entry_ms` per TF (closed HTF bars + 1m partial close), НИКАКОГО FINAL close незакрытого HTF бара.

Консолидировано 2026-06-14 из трёх memory: `feedback-ob-vc-entry-rule-deep`, `feedback-wait-window-before-entry-analyzed`, `feedback-hma-live-per-tf-at-entry`.

### 15.1 — Entry формулы по n_FVG (два варианта)

| n_FVG (per-LTF) | Тип | deep | смысл |
|---|---|---|---|
| **1** | Type A | **0.2** | shallow — близко к верху/низу FVG, первое касание |
| **≥2** | Type B | **0.8** | глубокий — confluence FVGs, цена обычно проходит глубже |

**LONG:**
```
chosen FVG = top-FVG на конкретном LTF (max fvg_hi)
entry      = fvg_hi − deep × (fvg_hi − fvg_lo)
SL         = drop_lo  (= low_OB_VC = min(prev.low, cur.low))
TP         = entry + 1.7 × R          где R = entry − SL
```

**SHORT** (зеркально):
```
chosen FVG = bottom-FVG (min fvg_lo)
entry      = fvg_lo + deep × (fvg_hi − fvg_lo)
SL         = drop_hi  (= high_OB_VC = max(prev.high, cur.high))
TP         = entry − 1.7 × R
```

**Фиксированные параметры:**
- **RR = 1.7** (R/R-фиксированный для production canon)
- **Лимит живёт 14 дней** (TBM horizon); если не fill — skip setup
- **Order placement** в момент `born_ms` (strict detection timing)
- **n_FVG считается per-LTF** — отдельно для каждого LTF (НЕ cross-LTF суммирование)

См. `[[memory:feedback-ob-vc-n-fvg-per-ltf]]` для per-LTF semantics.

### 15.2 — Wait-window [born_ms → entry_fill_ms]

**Между born_ms (setup сформирован) и entry_fill_ms (касание entry лимит-ордером) — ВСЕГДА анализируется как видимая часть графика для решения.**

Это **не lookahead** — все 1m бары полностью известны на момент `entry_fill_ms` (закрытый интервал).

#### Архитектура (визуал)

```
T_born_ms (setup сформирован, лимит размещён)
       ↓
   [WAIT-WINDOW — обязательно учитываем!]
       ↓
T_entry_fill_ms (цена коснулась entry — момент решения ML / факт сделки)
       ↓
T_exit (TP / SL)
```

#### Минимальный набор wait-features (для ML / анализа)

| Feature | Что |
|---|---|
| `fill_delay_min` | длительность ожидания в минутах |
| `wait_max_high_pct` | самый высокий high в окне (% от entry) |
| `wait_min_low_pct` | самый низкий low (% от entry) |
| `wait_net_move_pct` | close-to-close движение |
| `wait_volume_total` | суммарный объём |
| `wait_volatility_change_pct` | изменение волатильности |
| `wait_directional_efficiency` | насколько прямолинейно цена шла |
| `wait_touched_sl_before_entry` | задела ли SL до входа (= setup invalidated) |
| `wait_bars_count_15m / _1h / _4h` | сколько баров сформировалось |

#### Семантика

- Если цена «спокойно» дошла к entry — clean setup, выше P(win)
- Если overshoot / spike / SL touch — setup ослаблен или invalidated
- Без wait-window ML смотрит только snapshot at born_ms — слепое пятно от часов до дней

Empirically: переход с `born_ms` anchor на `entry_fill_ms` anchor дал **+0.12 AUC** в v3 ob_vc pipeline. Wait-features (`wait_directional_efficiency` #1, `wait_max_high_pct` #2) — топ permutation importance после honest fix.

### 15.3 — Индикаторы расчётные LIVE per TF

**ВСЕ HTF индикаторы (HMA, EMA, MA, VWAP, RSI, ATR и др.) ОБЯЗАНЫ считаться LIVE на момент `entry_ms` отдельно для каждого TF.**

«LIVE» = как PineScript показывает в реальном времени:
1. Все **полностью закрытые** HTF бары — их true close
2. **Текущий бар в процессе** — его «running close» = 1m close в момент `entry_ms`
3. Indicator вычисляется на series: `[closed_HTF_closes, current_1m_close_at_entry_ms]`
4. Применяется **для каждого TF отдельно** (15m, 20m, 1h, 90m, 2h, 4h, 6h, 12h, 1D, 2D, 3D) — у каждого свой `closed_idx` и свой `partial`.

#### ❌ Lookahead-BUG (запрещено)

```python
# BUG: использует FINAL close ещё не закрытого HTF бара (future leak)
idx = searchsorted(ts_arr, entry_ms, side="right") - 1   # бар СОДЕРЖАЩИЙ entry_ms
close = closes[idx]                                       # FINAL close in-progress бара ← FUTURE!
hma = hma_series[idx]                                     # HMA на этом future close
```

Lookahead: до **72h в будущем** для 3D TF, до 24h для 1D, до 12h для 12h.

#### ✅ HONEST (live partial-bar)

```python
# Cutoff = ПОСЛЕДНИЙ ЗАКРЫТЫЙ HTF бар
closed_idx = searchsorted(ts_arr, entry_ms - tf_ms, side="right") - 1
partial_close = close_1m at entry_ms                                 # текущая цена
series = closes[:closed_idx+1] + [partial_close]                     # closed + virtual partial
indicator_live = indicator_np(series, params)[-1]                    # value at virtual end
```

Реализация: `~/smc-lib/projects/ob-vc-2h/ml_v3/features/hma_at_entry_honest.py`, функция `hma_value_at_virtual_partial()`.

#### Чек-лист при добавлении любой indicator-feature

- [ ] Cutoff = `entry_ms - tf_ms` (НЕ просто `entry_ms`)
- [ ] Каждый TF обрабатывается отдельно (свой `tf_ms`, свой `closed_idx`)
- [ ] Partial-bar update применён → нет stale данных
- [ ] Derivatives (slope5/20, slope_accel) используют indicator from CLOSED bars only
- [ ] Cross-TF features: live indicator values для обоих TF в паре

### 15.4 — Lesson 2026-06-09 (urgent context)

**v3.3 production canon ob_vc strategy (WR 72.4%, +1288R, AUC 0.79) был ПОСТРОЕН НА НАРУШЕНИИ этого правила.**

- Bug в `hma_at_entry.py` использовал FINAL close in-progress HTF бара (lookahead до 72h на 3D)
- После fix реальный AUC = 0.54, WR ~38%
- Strategy была сохранена в библиотеку, нарисованы PNG, всё на иллюзии
- Пользователь несколько раз спрашивал «не смотрим в будущее?» — было подтверждено "honest" без проверки кода

**Lesson:** при AUC > 0.65 на multi-day directional crypto target — первое действие проверить feature builder на этот bug.

### 15.5 — Связи

- `[[memory:feedback-ob-vc-entry-rule-deep]]` — entry deep по n_FVG (15.1)
- `[[memory:feedback-ob-vc-n-fvg-per-ltf]]` — n_FVG считается per-LTF
- `[[memory:feedback-wait-window-before-entry-analyzed]]` — wait-window canon (15.2)
- `[[memory:feedback-hma-live-per-tf-at-entry]]` — LIVE indicators canon (15.3)
- `[[memory:feedback-ml-lookahead-must-verify]]` — общее правило verify before answer
- `[[memory:feedback-ob-vc-strict-detection-timing]]` — strict timing для entry detection
- `[[memory:ob-vc-v33-production-canon]]` — DEPRECATED canon (тот самый lookahead bug)
- `[[Правило 7]]` — TrendLine ASVK LIVE HMA (узкий случай 15.3 для HMA-78/200)
- `[[Правило 14]]` — TF anchor canon (используется для tf_ms в формулах cutoff)
- Production canon doc: `~/smc-lib/projects/ob-vc-2h/ml_v3/production_strategy_v3.md`

---

## Правило 16 — ML обучение на ПОЛНОМ наборе активных зон (без caps)

**Принцип.** Любая ML/предиктивная модель, которая работает с SMC-элементами для торговых решений, ДОЛЖНА видеть **ВСЕ активные зоны** на момент anchor'а — без artifical caps по возрасту, количеству или TF. Иначе модель не сможет обнаружить **скопления уровней** (cluster confluence) — фундаментальный SMC-сигнал силы зоны.

### 16.1 Что значит «активная зона»

Zone является **активной** на момент `t` тогда и только тогда, когда:

1. Был **born event** для этой zone в момент `t_birth ≤ t` (canon detection произошла)
2. **НЕ было retire event** между `t_birth` и `t`:
   - `fill_full` (wick прошёл насквозь — Модель 1 wick-fill consumed)
   - `sweep` (wick за level — Модель 3)
   - `first_touch` (первое касание — Модель 2)
   - `break` (close beyond opposite border)
   - `liq_first_touch` (liq marker для ob_liq)
3. Если был `fill_partial` — zone **остаётся активной**, но `mit_count` инкрементится (передаётся как feature)

→ Zone $30K из 2023 если не consumed → ОСТАЁТСЯ активной в 2026. Должна быть в state модели.

### 16.2 Что ЗАПРЕЩЕНО в state-tracking

| Anti-pattern | Почему вредно |
|---|---|
| **Age cap** (drop zones старше N дней) | HTF zones (D/W) живут годами и критичны при retest. Забывая их — теряем главные magnit-точки. |
| **`MAX_BARS_BACK` lookback cap на TF** | LTF zones из прошлого года могут быть actionable. Отбрасывая их — теряем context. |
| **Total state cap** (drop oldest N zones) | Выкидывает старые HTF magnits. Confluence count занижается → ML не видит cluster strength. |
| **Filter «только последние N events»** | Хронологически старые born events с не-consumed zones — это активные zones. Их пропуск = incomplete state. |

### 16.3 Что РАЗРЕШЕНО для performance

| Pattern | Когда применять |
|---|---|
| **Price range scope** (per-anchor ±$X) | Global state хранит ВСЕ active zones. Per-anchor processing работает с подmножеством в ±$X от current price. Дешевле и не теряет информации — когда цена сместится, zones из global state попадут в scope автоматически. **⚠ Filter ДОЛЖЕН проверять interval overlap, не center**: zone попадает в scope если `max(zone_lo, price - X) ≤ min(zone_hi, price + X)`. Иначе zone с center снаружи range но краем внутри будет пропущена. |
| **Lazy materialization** (вычислять features только для zones in scope) | Не строить full feature matrix для всех zones при каждом anchor — только для relevant. |
| **Spatial indexing** | Сортировка zones по `zone_lo`, binary search для overlap detection. |

### 16.4 Обязательное retire detection для ВСЕХ zone-элементов

| Элемент | Retire actions (обязательны в event detector) |
|---|---|
| fractal | sweep |
| ob | fill_full, break |
| fvg | fill_full |
| marubozu | sweep (open level) |
| rdrb | fill_full |
| i_rdrb | fill_full |
| block_orders | fill_full |
| i_fvg | fill_full |
| ob_liq | liq_first_touch (для liq_zone marker) |
| **breaker_block** | **fill_full** (после armed) — обязательно |
| **mitigation_block** | **fill_full** (после armed) — обязательно |
| ob_vc | fill_full HTF OB.zone |
| rb | first_touch |

→ Если retire detection отсутствует для какого-либо элемента — zones этого типа накапливаются как **shadow noise** в state, искажая cluster confluence и feature importance.

### 16.5 Симптомы нарушения правила

Если ML модель обучается на incomplete state, симптомы:

1. **Feature importance показывает `dist_pct_abs` или `nearest_X_dist` как доминирующее** (× 5-25 над остальными)
2. **`overlap_count` / `confluence_score` имеет low importance** (модель не видит реальный cluster strength)
3. **Top-1 accuracy «выглядит хорошо»** (25-30%) но это distance proxy, не реальный edge
4. **При наложении output constraint (4h+ only)** accuracy резко падает (>10 pp) — артефакт distance shortcut

### 16.6 Связи

- `[[Правило 2]]` — mitigation models (wick-fill / first-touch / sweep) — define retire events
- `[[Правило 8]]` — Движение цены — магнит между классами зон, cluster confluence — фундаментальный сигнал
- `[[memory:feedback-untraded-area-is-magnet]]` — fundamental магнит
- `[[memory:zone-class-liquidity-inefficiency-block]]` — таксономия 3 классов для роли определения
- Live application: `~/smc-lib/projects/живой-рынок/`
