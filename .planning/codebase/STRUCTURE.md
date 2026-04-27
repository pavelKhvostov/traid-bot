# Codebase Structure

**Analysis Date:** 2026-04-27

## Directory Layout

```
trading-signals-bot/
├── .env                       # TELEGRAM_BOT_TOKEN (do not commit / read)
├── .gitignore
├── CLAUDE.md                  # Project brief / agent instructions
├── README.md                  # Human-facing project docs
├── REVIEW.md                  # Engineering review notes
├── requirements.txt           # Python deps (pandas, requests, websockets, python-dotenv)
├── main.py                    # Entry point — async startup + ws_loop + polling_loop
├── scanner.py                 # Live scanner: WS consumer + strategy dispatch + dedup
├── telegram_bot.py            # Telegram API I/O + command handler + polling loop
├── data_manager.py            # Binance REST + CSV persistence + TF resampling
├── state.py                   # JSON state IO (users, sent_signals, last_signal, log)
├── config.py                  # Constants, .env loader, admin file IO
├── backtest_year.py           # Offline backtest (yearly)
├── full_backtest_new.py       # Offline backtest (full history, all strategies)
├── full_backtest_obx4.py      # Offline backtest (OBX4 only)
├── today_signals.py           # Today-only signal listing
├── generate_dashboard.py      # HTML dashboard generator
├── generate_report.py         # HTML report generator
├── signals_report.html        # Generated report (large, gitignored ideally)
├── smoke_test.py              # Sanity check
├── smoke_test_fvg.py          # Sanity check (FVG)
├── smoke_test_obx4.py         # Sanity check (OBX4)
├── strategies/                # Strategy modules + shared primitives
│   ├── __init__.py            # Empty (modules imported individually)
│   ├── base.py                # Signal/Zone dataclasses + Telegram rendering
│   ├── ob1h_core.py           # Shared OB-1h confirmation logic
│   ├── obx4.py                # OBX4 strategy
│   ├── fvg.py                 # FVG 4H→1H strategy
│   ├── ob_htf.py              # OB on higher TF strategy
│   ├── rdrb.py                # Red Day Reversal Bar strategy
│   ├── fractal.py             # Fractal/Vasya/FVG strategy
│   ├── marubozu.py            # Marubozu strategy
│   └── hammer.py              # Hammer strategy
├── data/                      # Binance kline CSVs, one per (symbol, tf)
│   ├── BTCUSDT_1h.csv ... BTCUSDT_3d.csv
│   ├── ETHUSDT_1h.csv ... ETHUSDT_3d.csv
│   └── SOLUSDT_1h.csv ... SOLUSDT_3d.csv
├── signals/                   # Backtest output CSVs
│   ├── backtest_fractal.csv
│   ├── backtest_fvg.csv
│   ├── backtest_ob_htf.csv
│   ├── backtest_obx4.csv
│   ├── backtest_rdrb.csv
│   └── obx4_backtest_full.csv
├── state/                     # Runtime persistent state (JSON + log)
│   ├── admins.json            # list[int] — admin chat_ids
│   ├── users.json             # list[dict] — subscribers
│   ├── sent_signals.json      # dedup map: dedup_key → payload
│   ├── last_signal.json       # last broadcast payload
│   ├── last_update_id.json    # Telegram getUpdates offset
│   └── bot.log                # rotating log (5 MB → bot.log.1)
├── reference/                 # Original monolithic strategy scripts (source-of-truth math)
│   ├── obx4_original.py
│   ├── fvg_original.py
│   ├── fractal_vasya_original.py
│   └── rdrb_original.py
├── .planning/                 # GSD planning artefacts (this directory)
│   └── codebase/              # ARCHITECTURE.md, STRUCTURE.md, etc.
├── .claude/                   # Claude Code project config
└── venv/                      # Local virtualenv (gitignored)
```

## Directory Purposes

**`/` (project root):**
- Purpose: All live runtime modules + offline tooling (flat layout, no `src/` wrapper).
- Contains: Python modules (entry, scanner, telegram, data, state, config), backtests, smoke tests, generated artefacts, project docs.
- Key files: `main.py`, `scanner.py`, `telegram_bot.py`, `data_manager.py`, `state.py`, `config.py`.

**`strategies/`:**
- Purpose: One module per strategy, plus shared primitives.
- Contains: Strategy detector functions (`detect_zones`), shared dataclasses (`Signal`, `Zone`), shared OB-1h confirmation core, Telegram render helpers.
- Key files: `strategies/base.py`, `strategies/ob1h_core.py`, `strategies/obx4.py`.

**`data/`:**
- Purpose: Binance Spot kline cache. One CSV per `(symbol, timeframe)`. Auto-managed by `data_manager.py`.
- Contains: CSVs named `{SYMBOL}_{tf}.csv` (e.g. `BTCUSDT_4h.csv`). Columns: `open_time, open, high, low, close, volume`.
- Key files: All CSVs are derivable; safe to delete and re-bootstrap.

**`signals/`:**
- Purpose: Output of offline backtests (one CSV per strategy run).
- Contains: `backtest_*.csv`.
- Key files: Generated, not source.

**`state/`:**
- Purpose: Runtime mutable state. Treated as the bot's "database".
- Contains: `users.json`, `admins.json`, `sent_signals.json`, `last_signal.json`, `last_update_id.json`, `bot.log`(`.1`).
- Key files: Critical — back up before destructive operations.

**`reference/`:**
- Purpose: Original monolithic implementations of each strategy. Authoritative source for the math; modules in `strategies/` were extracted from these.
- Contains: `*_original.py`. Read-only reference, not imported.

**`.planning/codebase/`:**
- Purpose: GSD codebase mapping documents (this file lives here).
- Contains: `ARCHITECTURE.md`, `STRUCTURE.md`, and other GSD-generated docs.

**`.claude/`:**
- Purpose: Claude Code project configuration / commands / skills.

**`venv/`:**
- Purpose: Local Python virtualenv. Not committed.

## Key File Locations

**Entry Points:**
- `main.py`: Live bot entrypoint.
- `backtest_year.py`, `full_backtest_new.py`, `full_backtest_obx4.py`, `today_signals.py`: Offline analytics entrypoints.
- `generate_dashboard.py`, `generate_report.py`: HTML report generators.
- `smoke_test.py`, `smoke_test_fvg.py`, `smoke_test_obx4.py`: Quick sanity checks.

**Configuration:**
- `config.py`: All static constants and `.env` loading.
- `.env`: Secret token (do not read or commit).
- `requirements.txt`: Python dependencies.

**Core Logic:**
- `scanner.py`: Orchestration (`Scanner` class, `STRATEGY_MAP`, dispatch, dedup, broadcast).
- `data_manager.py`: Binance REST + CSV cache + composed-TF resampling.
- `state.py`: JSON state I/O + logging.
- `telegram_bot.py`: Telegram API + command handlers + polling.
- `strategies/base.py`: `Signal`, `Zone`, signal rendering, dedup-key helpers, TradingView URL builder.
- `strategies/ob1h_core.py`: Shared confirmation core for every strategy.

**Strategy implementations:**
- `strategies/obx4.py`, `strategies/fvg.py`, `strategies/ob_htf.py`, `strategies/rdrb.py`, `strategies/fractal.py`, `strategies/marubozu.py`, `strategies/hammer.py`.

**Testing:**
- No real test suite. Smoke scripts in project root: `smoke_test.py`, `smoke_test_fvg.py`, `smoke_test_obx4.py`. CLAUDE.md explicitly states: live signals are the verification mechanism.

## Naming Conventions

**Files:**
- Modules: `lower_snake_case.py` (e.g., `data_manager.py`, `telegram_bot.py`).
- Strategy modules: short lowercase strategy id (e.g., `obx4.py`, `fvg.py`, `ob_htf.py`, `rdrb.py`, `fractal.py`).
- Reference originals: `{name}_original.py`.
- Smoke tests: `smoke_test[_<strategy>].py` (note: prefix `smoke_test_`, not `test_` — they are not pytest-discoverable).
- Backtests: `full_backtest_<scope>.py`, `backtest_<scope>.py`.
- Data CSVs: `{SYMBOL}_{tf}.csv` (uppercase symbol, lowercase TF, e.g. `BTCUSDT_4h.csv`).
- Backtest CSVs: `backtest_<strategy>.csv` in `signals/`.
- State files: `<concept>.json` in `state/` (e.g., `users.json`, `sent_signals.json`).

**Directories:**
- All lowercase. Flat structure — no nested subpackages.

**Code identifiers:**
- Functions / variables: `snake_case`.
- Classes: `PascalCase` (`Scanner`, `Signal`, `Zone`).
- Constants: `UPPER_SNAKE_CASE` (`SYMBOLS`, `TIMEFRAMES_NATIVE`, `STRATEGY_MAP`, `STRATEGY_TFS`, `BINANCE_WS_BASE`).
- Private helpers: `_leading_underscore` (e.g., `_sig_key_str`, `_dispatch_strategy`, `_handle_message`, `_action_subscribe`).
- Strategy detectors: every strategy module exposes `detect_zones(df, symbol, source_tf) -> list[Zone]`.
- Strategy IDs in code use `UPPER_SNAKE` keys: `"OBX4"`, `"FVG"`, `"OB_HTF"`, `"RDRB"`, `"FRACTAL"`, `"MARUBOZU"`, `"HAMMER"`.
- Direction constants: literal strings `"LONG"` / `"SHORT"`.
- Timeframe strings: lowercase Binance format — `"1h"`, `"2h"`, `"4h"`, `"6h"`, `"8h"`, `"12h"`, `"1d"`, `"2d"`, `"3d"`. The composed TFs (`3h`, `2d`) are listed in `TIMEFRAMES_COMPOSED`.

## Where to Add New Code

**New strategy:**
- Implementation: create `strategies/<name>.py` exposing `def detect_zones(df: pd.DataFrame, symbol: str, source_tf: str) -> list[Zone]`. Reuse `Zone` from `strategies/base.py`.
- Wire-up: import the module at the top of `scanner.py` and add an entry to `STRATEGY_MAP`. Use `STRATEGY_TFS` — do not introduce a per-strategy TF list (CLAUDE.md guidance).
- Telegram rendering: if a new strategy needs an emoji, add to `STRATEGY_ICONS` in `strategies/base.py`.
- Backtest harness: add to existing `full_backtest_new.py` if needed; consider a smoke test `smoke_test_<name>.py`.
- Reference math: keep monolithic origin in `reference/<name>_original.py` if extracted from a prior file.

**New symbol or timeframe:**
- Symbol: add to `SYMBOLS` in `config.py`. Add icon to `ASSET_ICONS` in `strategies/base.py`. Bootstrap data via `Scanner.startup()` (it will REST-fetch on first run).
- Native TF: add to `TIMEFRAMES_NATIVE` in `config.py`. The WebSocket subscription list is auto-derived in `Scanner._stream_names`.
- Composed TF: add to `TIMEFRAMES_COMPOSED` mapping `composed → base`. Add a `_recompose` trigger in `Scanner.on_closed_native_candle` if the base TF is not already wired (currently `1h → 3h` and `1d → 2d`).

**New Telegram command:**
- Implement an `_action_<name>(chat_id, ...)` function in `telegram_bot.py`.
- Add a row to `BUTTON_TO_ACTION` mapping the trigger string (slash command and/or button label, lowercase) to the action key.
- Dispatch the new action in `_handle_message`.
- Admin-only commands: add the slash command to the `head in (...)` admin gate and check `is_admin(chat_id)`.

**New persisted state field:**
- Add a JSON file path constant in `state.py` (alongside `USERS_PATH`, `SENT_PATH`, etc.).
- Add `load_*` / `save_*` / mutation helpers using the existing `_read_json` / `_write_json` pattern.
- Update the dedup key format only if absolutely necessary — it would invalidate `state/sent_signals.json`.

**New utility / helper:**
- If shared by strategies: add to `strategies/base.py` or a new module under `strategies/`.
- If shared by runtime modules (scanner, telegram, state): add to the module that owns the concept; do not introduce a `utils.py` grab-bag.
- If purely data-fetch: extend `data_manager.py`.

**New backtest / report:**
- Add as a top-level script (`<purpose>.py`) following the existing pattern. Do not create a `backtests/` subdirectory.
- Output CSVs go to `signals/backtest_<name>.csv`.

## Special Directories

**`data/`:**
- Purpose: Binance kline cache (CSVs).
- Generated: Yes (by `data_manager.update_df_incrementally` and `compose_from_base`).
- Committed: Currently committed; can be regenerated from REST. Treat as cache.

**`state/`:**
- Purpose: Runtime mutable state.
- Generated: Yes (by `state.py` and `telegram_bot.py`).
- Committed: Should NOT be committed (`users.json`, `admins.json`, logs are environment-specific). Verify `.gitignore` coverage before any commit.

**`signals/`:**
- Purpose: Backtest output.
- Generated: Yes (by backtest scripts).
- Committed: Optional — derived data.

**`reference/`:**
- Purpose: Read-only originals of strategy implementations.
- Generated: No.
- Committed: Yes — authoritative math reference.

**`venv/`:**
- Purpose: Local Python virtualenv.
- Generated: Yes.
- Committed: No.

**`__pycache__/`:**
- Purpose: Python bytecode cache.
- Generated: Yes.
- Committed: No.

---

*Structure analysis: 2026-04-27*
