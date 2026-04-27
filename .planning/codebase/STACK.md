# Technology Stack

**Analysis Date:** 2026-04-27

## Languages

**Primary:**
- Python 3.13 — Entire codebase (bot, scanner, strategies, data layer, backtests). Modern syntax used (`int | None` PEP 604 unions, `from __future__ import annotations`, `list[int]` PEP 585 generics).

**Secondary:**
- HTML — Generated reports (`signals_report.html`, `dashboard.html`) produced by `generate_report.py` and `generate_dashboard.py`.
- CSV — On-disk format for OHLCV candle storage in `data/`.
- JSON — On-disk state format in `state/` (users, sent signals, admins, last update id, last signal).

## Runtime

**Environment:**
- CPython 3.13 (per `CLAUDE.md` style guide).
- Single long-running process: `python main.py` launches `asyncio.run(main())` which fans out to `scanner.ws_loop()` + `polling_loop()` via `asyncio.gather`.
- Local virtualenv at `venv/` (gitignored).

**Package Manager:**
- pip (standard) — no Poetry / uv / Pipenv detected.
- Lockfile: missing (only `requirements.txt` with pinned versions — no `requirements.lock` / `pip-tools` artifacts).

## Frameworks

**Core:**
- No web/application framework. The bot is a hand-rolled asyncio loop in `main.py`.
- Telegram interaction is implemented directly against the HTTP Bot API via `requests` in `telegram_bot.py` (no `python-telegram-bot`, `aiogram`, or `pyTelegramBotAPI`).
- WebSocket consumption is direct `websockets` client in `scanner.py:ws_loop` (no exchange SDK such as `python-binance` or `ccxt`).

**Testing:**
- No test framework configured. Smoke scripts only: `smoke_test.py`, `smoke_test_fvg.py`, `smoke_test_obx4.py` (executed manually, not via pytest/unittest).
- `CLAUDE.md` explicitly states: "Не покрывать тестами — проект одноразовый, проверка = живые сигналы."

**Build/Dev:**
- No build tooling. No `pyproject.toml`, `setup.py`, `setup.cfg`, `Makefile`, `Dockerfile`, or CI config files in the project root.
- No linter/formatter config (`ruff`, `black`, `flake8`, `mypy`) checked in.

## Key Dependencies

**Critical** (from `requirements.txt`):
- `pandas==2.2.3` — All time-series math: OHLCV frames, `resample(origin='epoch')` for composed timeframes (3h, 2d), datetime indexing in UTC. Used in `data_manager.py`, `scanner.py`, every strategy module.
- `requests==2.32.3` — Synchronous HTTP for both Binance REST klines (`data_manager.py:fetch_klines_range`) and Telegram Bot API (`telegram_bot.py:_api`).
- `websockets==13.1` — Async client for Binance combined-stream WebSocket (`scanner.py:ws_loop`, endpoint `wss://stream.binance.com:9443/stream`).
- `python-dotenv==1.0.1` — Loads `.env` once at import time in `config.py:load_dotenv()`.

**Infrastructure:**
- Python stdlib only beyond the four pinned deps: `asyncio`, `json`, `pathlib`, `datetime`, `dataclasses`, `time`, `os`.
- No database driver, no ORM, no Redis/Celery client, no logging framework — by explicit design (`CLAUDE.md`: "Никаких ORM, базы данных, Docker — всё в CSV и JSON").

## Configuration

**Environment:**
- `.env` file at project root (present, gitignored). Loaded by `config.py` via `load_dotenv()`.
- Required env var: `TELEGRAM_BOT_TOKEN` (read in `config.py:21`, validated at startup in `main.py:13`).
- No other env vars consumed by code (`ADMIN_CHAT_ID` is referenced in `CLAUDE.md` but admins are actually persisted in `state/admins.json` via `config.py:load_admins`).

**Static Configuration** (hardcoded in `config.py`):
- `SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]`.
- `TIMEFRAMES_NATIVE = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d"]`.
- `TIMEFRAMES_COMPOSED = {"3h": "1h", "2d": "1d"}` — composed via pandas resample from native base.
- `HISTORY_START_DATE = "2022-01-01"` — bootstrap horizon.
- Paths: `DATA_DIR=./data`, `STATE_DIR=./state`, `SIGNALS_DIR=./signals` (auto-created by `ensure_dirs()` at import).

**Scanner Configuration** (hardcoded in `scanner.py`):
- `STRATEGY_TFS = ["12h", "1d", "2d", "3d"]` — applied uniformly to all 7 strategies.
- `STRATEGY_MAP` registers: OBX4, FVG, OB_HTF, RDRB, FRACTAL, MARUBOZU, HAMMER.

**Build:**
- No build configuration files.

## Platform Requirements

**Development:**
- Python 3.13 interpreter.
- `pip install -r requirements.txt` into local `venv/`.
- Outbound HTTPS access to `api.binance.com` and `api.telegram.org`; outbound WSS access to `stream.binance.com:9443`.
- Local writable `./data/`, `./state/`, `./signals/` directories.

**Production:**
- No deployment tooling shipped (no Dockerfile, no systemd unit, no Procfile, no cloud manifests).
- Runs as a foreground Python process; persists everything to local CSV/JSON files. Project explicitly avoids Docker per `CLAUDE.md`.

---

*Stack analysis: 2026-04-27*
