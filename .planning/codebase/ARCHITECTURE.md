# Architecture

**Analysis Date:** 2026-04-27

## Pattern Overview

**Overall:** Event-driven monolithic Python application with module-per-concern layout. No frameworks beyond `asyncio`, `requests`, `websockets`, `pandas`. State is persisted as flat JSON and CSV files (no database, no ORM, no DI container).

**Key Characteristics:**
- Two long-running coroutines run concurrently from `main.py`: `Scanner.ws_loop()` (Binance WebSocket consumer) and `polling_loop()` (Telegram getUpdates poller). Both are launched via `asyncio.gather`.
- Strategies are pure functions that take a normalised DataFrame and return `list[Zone]`. They are registered in a single dispatch table `STRATEGY_MAP` in `scanner.py`.
- Confirmation logic is centralised in `strategies/ob1h_core.py` (single OB-1h confirmation rule applied to all strategies).
- Idempotency / deduplication is enforced through a JSON keystore (`state/sent_signals.json`) keyed by `{strategy}|{symbol}|{source_tf}|{direction}|{confirm_time_iso}`.
- All times are UTC (Binance native). Only closed candles (`k.x == True`) are processed.

## Layers

**Entry Point Layer:**
- Purpose: Process bootstrap, environment validation, admin-startup notification, async orchestration.
- Location: `main.py`
- Contains: `async def main()` only.
- Depends on: `config`, `scanner.Scanner`, `state`, `telegram_bot`.
- Used by: `python main.py` (CLI invocation).

**Orchestration Layer:**
- Purpose: Live scan loop. Consumes Binance kline WebSocket frames, updates CSVs, dispatches strategies, deduplicates and broadcasts signals.
- Location: `scanner.py`
- Contains: `class Scanner` (`startup`, `_prefill_today_signals`, `on_closed_native_candle`, `_recompose`, `_dispatch_strategy`, `ws_loop`), `STRATEGY_MAP`, `_sig_key_str`.
- Depends on: `config`, `data_manager`, `state`, `strategies.*`, `telegram_bot`.
- Used by: `main.py`.

**Strategy Layer:**
- Purpose: Pure detection of trade-zone setups per strategy. Each module exposes a `detect_zones(df, symbol, tf) -> list[Zone]` function.
- Location: `strategies/`
- Contains: `obx4.py`, `fvg.py`, `ob_htf.py`, `rdrb.py`, `fractal.py`, `marubozu.py`, `hammer.py`. Shared confirmation core in `ob1h_core.py`. Shared dataclasses + Telegram rendering in `base.py`.
- Depends on: `pandas`, `strategies.base`.
- Used by: `scanner.py`, backtest scripts (`backtest_year.py`, `full_backtest_new.py`, `full_backtest_obx4.py`, `today_signals.py`, smoke tests).

**Data Layer:**
- Purpose: Binance Spot kline ingestion (REST + WebSocket), CSV persistence, composed-timeframe resampling.
- Location: `data_manager.py`
- Contains: `tf_to_ms`, `tf_to_pandas_rule`, `normalize_df`, `save_df`, `load_df`, `fetch_klines_range`, `fetch_full_history`, `update_df_incrementally`, `compose_from_base`, `get_df`.
- Depends on: `requests`, `pandas`, `config`.
- Used by: `scanner.py`, all backtest / smoke / dashboard scripts.

**State Layer:**
- Purpose: Persistent flat-file state — subscriber list, dedup map, last-signal cache, log file.
- Location: `state.py` (module) + `state/` (directory of JSON / log files).
- Contains: `load_users` / `save_users` / `upsert_user` / `remove_user` / `get_user` / `is_subscribed`, `was_sent` / `mark_sent`, `save_last_signal` / `load_last_signal`, `log_event` (with size-based log rotation).
- Depends on: `config.STATE_DIR`, stdlib (`json`, `pathlib`, `datetime`).
- Used by: `scanner.py`, `telegram_bot.py`, `main.py`.

**Configuration Layer:**
- Purpose: Static constants (symbols, timeframes, paths, history start), `.env` loading, admin allow-list IO.
- Location: `config.py`
- Contains: `SYMBOLS`, `TIMEFRAMES_NATIVE`, `TIMEFRAMES_COMPOSED`, `ALL_TIMEFRAMES`, `DATA_DIR`, `STATE_DIR`, `SIGNALS_DIR`, `HISTORY_START_DATE`, `TELEGRAM_BOT_TOKEN`, `ensure_dirs()`, `load_admins()`, `save_admins()`, `is_admin()`.
- Depends on: `python-dotenv`, stdlib.
- Used by: every other module.

**Telegram I/O Layer:**
- Purpose: All Telegram Bot API interaction — outbound `sendMessage`, signal broadcast, long-poll `getUpdates`, command/keyboard handling, admin commands.
- Location: `telegram_bot.py`
- Contains: `_api`, `send_message`, `send_signal`, `broadcast_signal`, `broadcast`, `signal_inline_kb`, `check_updates`, `polling_loop`, `_handle_message`, `_action_subscribe` / `_action_unsubscribe` / `_action_status` / `_action_whoami`, `BUTTON_TO_ACTION`.
- Depends on: `requests`, `config`, `state`, `strategies.base` (for `render_signal_from_dict`, `tradingview_url`).
- Used by: `scanner.py` (broadcast on signal), `main.py` (startup notify, polling loop).

**Reporting / Backtest Layer (offline tools, not part of live runtime):**
- Purpose: One-shot backtests, dashboards, ad-hoc reports.
- Location: `backtest_year.py`, `full_backtest_new.py`, `full_backtest_obx4.py`, `today_signals.py`, `generate_dashboard.py`, `generate_report.py`, `smoke_test*.py`.
- Used by: human invocation only — not imported by `main.py`.

## Data Flow

**Live Signal Flow (primary path):**

1. `main.py` calls `Scanner().startup()` which:
   - For each `(symbol, tf)` in `SYMBOLS × TIMEFRAMES_NATIVE`, calls `update_df_incrementally` to top-up CSVs from Binance REST.
   - For each composed TF in `TIMEFRAMES_COMPOSED` (`3h` from `1h`, `2d` from `1d`), rebuilds the CSV via `compose_from_base`.
   - Runs `_prefill_today_signals`: scans the last 48h, finds OB-1h confirmations for current-UTC-day zones, and silently `mark_sent`s them so the live loop doesn’t re-broadcast historical setups.
2. `Scanner.ws_loop()` opens a single multiplexed WebSocket `wss://stream.binance.com:9443/stream?streams=<sym>@kline_<tf>/...` covering every `(SYMBOLS × TIMEFRAMES_NATIVE)` pair.
3. On each frame, if `k.x` (candle closed) is true and TF is native:
   - `update_df_incrementally(symbol, tf)` appends the new candle to CSV.
   - `on_closed_native_candle(symbol, tf)` is invoked.
4. `on_closed_native_candle`:
   - Recomposes dependent TFs (`3h` when `1h` closes; `2d` when `1d` closes).
   - When `tf == "1h"`: full re-scan of every strategy across every `STRATEGY_TFS = ["12h","1d","2d","3d"]` for the current UTC day.
   - Otherwise: dispatches only the strategy/TF combos whose source TF matches the closed candle.
5. `_dispatch_strategy` per strategy:
   - Calls `detect(df_htf, symbol, tf)` → `list[Zone]`.
   - For each zone, calls `find_first_confirmation_in_zone(z, df_1h)` from `strategies/ob1h_core.py`.
   - Confirmation must occur on the **last closed 1h candle** (`confirm_time == last_1h_open`).
   - Builds `sig_data` dict, computes dedup key. If `was_sent(key)` → skip.
   - Otherwise: `broadcast_signal(sig_data)` (Telegram fan-out to all users), `mark_sent(key, payload)`, `save_last_signal(payload)`, `log_event("SIGNAL", ...)`.

**Telegram Inbound Flow:**

1. `polling_loop()` calls `check_updates()` every ~2s.
2. `check_updates` reads `state/last_update_id.json`, calls `getUpdates`, and for each message invokes `_handle_message`.
3. `_handle_message` resolves the text/button to an action via `BUTTON_TO_ACTION`, then dispatches: subscribe, unsubscribe, status, whoami, or admin commands (`/users`, `/admin_add`, `/admin_remove`, `/broadcast`).
4. State mutations (`upsert_user`, `remove_user`, `save_admins`) write back to JSON files in `state/`.
5. Last processed `update_id` is persisted to `state/last_update_id.json`.

**State Management:**
- All state is on-disk JSON, read/written on every access (no in-memory cache). This keeps the model trivially restart-safe at the cost of file I/O on every signal.
- Log lines are appended to `state/bot.log`; file is rotated to `state/bot.log.1` when it exceeds 5 MB.

## Key Abstractions

**`Zone` (dataclass):**
- Purpose: A potential setup detected by a strategy on a higher timeframe. Carries `strategy`, `symbol`, `source_tf`, `direction` (`LONG`/`SHORT`), `zone_bottom`, `zone_top`, `trigger_time`, and a free-form `meta` dict.
- Examples: `strategies/base.py` (definition), produced by every `detect_zones` in `strategies/*.py`.
- Pattern: Plain dataclass, immutable in spirit (mutated only at construction). No methods — pure data.

**`Signal` (dataclass):**
- Purpose: A confirmed, dispatch-ready signal. Used by formatting helpers and backtests.
- Examples: `strategies/base.py`. Note: `scanner.py` does not instantiate `Signal` — it builds an equivalent `sig_data` dict and calls `render_signal_from_dict`. `Signal` is used by backtests/reports.

**Strategy interface (informal):**
- Each strategy module exposes `detect_zones(df: pd.DataFrame, symbol: str, source_tf: str) -> list[Zone]`.
- Examples: `strategies/obx4.py`, `strategies/fvg.py`, `strategies/ob_htf.py`, `strategies/rdrb.py`, `strategies/fractal.py`, `strategies/marubozu.py`, `strategies/hammer.py`.
- Pattern: Pure function over a pandas DataFrame. No I/O, no global state.

**OB-1h confirmation core:**
- Purpose: Single source of truth for "did the zone trigger on a 1h order-block?". Returns a dict (`{confirm_time, confirm_close, type, confirm_zone_bottom, confirm_zone_top}`) or `None`.
- Examples: `strategies/ob1h_core.py` — `find_first_confirmation_in_zone`, `find_first_ob1h_in_zone`, `_is_ob1h_long`, `_is_ob1h_short`.
- Pattern: Centralised confirmation rule, applied uniformly across all strategies in `_dispatch_strategy` and `_prefill_today_signals`.

**Dedup key:**
- Format: `f"{strategy}|{symbol}|{source_tf}|{direction}|{confirm_time_iso}"`.
- Implementation: `_sig_key_str` in `scanner.py`; companion `signal_key` / `zone_key` helpers in `strategies/base.py`.
- Backed by `state/sent_signals.json` via `was_sent` / `mark_sent`.

**Strategy dispatch table:**
- `STRATEGY_MAP` in `scanner.py` maps strategy name → `(detect_fn, applicable_tfs)`. Adding a strategy = adding a row here. The single shared TF list `STRATEGY_TFS = ["12h","1d","2d","3d"]` is reused for every entry.

## Entry Points

**Live bot:**
- Location: `main.py`
- Triggers: `python main.py`.
- Responsibilities: validate `TELEGRAM_BOT_TOKEN`, log startup, retire deprecated `state/signals_today.json` if present, instantiate `Scanner` and run `startup()`, notify admins, then `asyncio.gather(scanner.ws_loop(), polling_loop())`.

**Backtest entry points (offline):**
- `backtest_year.py` — yearly backtest.
- `full_backtest_new.py`, `full_backtest_obx4.py` — full-history backtests.
- `today_signals.py` — current-day signal listing.
- `generate_dashboard.py`, `generate_report.py` — HTML report generators (output: `signals_report.html`).
- `smoke_test.py`, `smoke_test_fvg.py`, `smoke_test_obx4.py` — sanity scripts.

## Error Handling

**Strategy:** Defensive, log-and-continue. The live loop is designed to never die from a single bad frame, broadcast failure, or strategy exception.

**Patterns:**
- Network errors in Telegram (`requests.RequestException` in `telegram_bot._api`) are caught and returned as `{"ok": False, "error": ...}`; logged via `log_event("ERROR", ...)` / `log_event("WARN", ...)`.
- WebSocket disconnects in `Scanner.ws_loop` are caught at the top-level `try/except`, logged, and retried after `await asyncio.sleep(5)`.
- Per-frame parsing/dispatch errors are caught individually so one bad message can’t kill the loop.
- Per-user broadcast failures in `broadcast_signal` / `broadcast` are tallied (`ok`, `failed`, `errors`) and reported back, never raised.
- JSON read failures in `state.py` and `config.py` fall back to defaults (empty list / dict) instead of raising.
- Admin-startup notifications are wrapped in `try/except` so a single failed admin notify cannot prevent boot.

## Cross-Cutting Concerns

**Logging:**
- Single helper: `state.log_event(level, msg)`. Levels: `INFO`, `SIGNAL`, `WARN`, `ERROR` (anything else coerced to `INFO`).
- Output: appends to `state/bot.log` AND prints to stdout. Size-based rotation at 5 MB → `state/bot.log.1`.
- All modules import and use `log_event` rather than `print` directly (despite CLAUDE.md guideline mentioning `print()`).

**Validation:**
- `config.ensure_dirs()` is called at import time to guarantee `data/`, `state/`, `signals/` exist.
- `main.py` validates `TELEGRAM_BOT_TOKEN` is set and not the placeholder before starting.
- Candle frames validated by checking `k.x` (closed) and `k.i in TIMEFRAMES_NATIVE` before dispatch.
- User input parsing in `_handle_message` defends against `int()` failures with explicit `try/except ValueError` for admin commands.

**Authentication / Authorisation:**
- Telegram API auth: bot token from `.env` baked into `API_BASE` URL.
- Admin authorisation: `is_admin(chat_id)` checks against `state/admins.json`. Used to gate `/users`, `/admin_add`, `/admin_remove`, `/broadcast`.
- No per-user authentication beyond Telegram's own `chat_id`.
- Subscriber gating: `is_subscribed(chat_id)` (presence in `state/users.json`). Non-subscribers receive only the welcome + Subscribe button.

**Concurrency model:**
- Single-process `asyncio` event loop with two cooperating coroutines (`ws_loop`, `polling_loop`).
- Blocking I/O (CSV read/write, `requests.get`, JSON state files) is offloaded with `asyncio.to_thread(...)`.
- No locks, no async-safe state primitives — read-modify-write of JSON files is racy under high concurrency, but signal volume is low and the design accepts this trade-off.

---

*Architecture analysis: 2026-04-27*
