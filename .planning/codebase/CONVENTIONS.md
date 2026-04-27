# Coding Conventions

**Analysis Date:** 2026-04-27

## Naming Patterns

**Files:**
- All Python files use lowercase `snake_case.py`. Examples: `data_manager.py`, `telegram_bot.py`, `today_signals.py`, `full_backtest_new.py`.
- Strategy modules live in `strategies/` and are named after the strategy in lowercase: `obx4.py`, `fvg.py`, `ob_htf.py`, `rdrb.py`, `fractal.py`, `marubozu.py`, `hammer.py`.
- Smoke/diagnostic scripts use the `smoke_test_*.py` prefix at project root.
- Backtest scripts use the `*_backtest*.py` / `backtest_*.py` naming at project root: `backtest_year.py`, `full_backtest_new.py`, `full_backtest_obx4.py`.

**Functions:**
- `snake_case` for all functions: `fetch_klines_range`, `compose_from_base`, `detect_obx4_bullish`, `find_first_confirmation_in_zone`.
- Private/internal helpers prefixed with `_`: `_normalize_df` in `strategies/obx4.py`, `_fmt_price` / `_fmt_confirm` / `_render` in `strategies/base.py`, `_csv_path` in `data_manager.py`, `_read_json` / `_write_json` / `_now_iso` / `_rotate_log_if_needed` in `state.py`, `_prep_history` / `_save_csv` / `_signal_to_row` in `full_backtest_new.py`.
- Public detector entry point in every strategy is `detect_zones(df, symbol, tf) -> list[Zone]` (see `strategies/fvg.py:10`, `strategies/obx4.py:244`).

**Variables:**
- `snake_case` for locals: `start_ms`, `end_ms`, `df_htf`, `df_1h`, `last_open_ms`, `today_start`.
- Time-related variables consistently use `_ms` suffix for epoch milliseconds and `_iso` suffix for ISO-8601 strings (`confirm_iso`, `last_ts`).
- DataFrames are named `df`, `df_htf` (higher-timeframe), `df_1h`, `df_tf`, `df_1h_raw` vs `df_1h` (after `to_ref_format`).

**Types / Constants:**
- Module-level constants in `UPPER_SNAKE_CASE`: `BINANCE_KLINES_URL`, `BINANCE_WS_BASE`, `KLINE_COLUMNS`, `STRATEGY_TFS`, `STRATEGY_MAP`, `CSV_COLUMNS`, `SYMBOLS`, `TIMEFRAMES_NATIVE`, `TIMEFRAMES_COMPOSED`, `HISTORY_START_DATE`, `LOG_ROTATE_BYTES`.
- Dataclasses (PascalCase): `Signal`, `Zone` in `strategies/base.py`.
- Strategy-name string keys are `UPPER_CASE`: `"OBX4"`, `"FVG"`, `"OB_HTF"`, `"RDRB"`, `"FRACTAL"`, `"MARUBOZU"`, `"HAMMER"`.
- Direction strings are `"LONG"` / `"SHORT"` (uppercase) at the public Zone/Signal layer; raw detectors may use `"bullish"` / `"bearish"` internally and convert on the way out (see `strategies/obx4.py:255`).

## Code Style

**Formatting:**
- No formatter config detected (no `.prettierrc`, no `pyproject.toml`, no `ruff.toml`, no `.editorconfig`).
- De-facto style: 4-space indent, double-quoted strings, trailing commas in multi-line literals, blank lines between top-level functions.
- Line length is loose; long f-strings are split across lines using implicit string concatenation:
  ```python
  print(f"[SMOKE] first: {df.index[0].isoformat()} O={first_row['open']} H={first_row['high']} "
        f"L={first_row['low']} C={first_row['close']} V={first_row['volume']}")
  ```

**Linting:**
- No linter configured. No `ruff`, `flake8`, `mypy`, or `pylint` config files.
- Type hints are used pragmatically (see below) but never type-checked in CI.

**Python version:**
- Python 3.13 per `CLAUDE.md`. Modern union syntax `int | None`, `list[dict]`, `dict[str, int]` is used freely (see `data_manager.py:85`, `state.py:69`).
- Every module starts with `from __future__ import annotations` (see `data_manager.py:6`, `scanner.py:3`, `strategies/base.py:2`, all `smoke_test_*.py`).

## Import Organization

**Order (observed in every module):**
1. `from __future__ import annotations`
2. Standard library: `import asyncio`, `import json`, `import time`, `from datetime import ...`, `from pathlib import Path`.
3. Third-party: `import pandas as pd`, `import requests`, `import websockets`.
4. First-party (project): `from config import ...`, `from data_manager import ...`, `from state import ...`, `from strategies import ...`, `from strategies.base import ...`, `from strategies.ob1h_core import ...`, `from telegram_bot import ...`.

Each group separated by a blank line. Example: `scanner.py:3-22`.

**Path Aliases:**
- None. Plain top-level package imports — the project root is on `sys.path` because scripts are run from the project directory.
- `strategies/__init__.py` re-exports submodules so `from strategies import fractal, fvg, hammer, marubozu, ob_htf, obx4, rdrb` works (see `scanner.py:19`).

## Error Handling

**Patterns:**
- Smoke tests raise `RuntimeError` on infrastructure failures with Russian messages:
  ```python
  if df.empty:
      raise RuntimeError("Binance вернул пустой ответ")
  if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
      raise RuntimeError("TELEGRAM_BOT_TOKEN / ADMIN_CHAT_ID не прочитаны из .env")
  ```
  (`smoke_test.py:22`, `smoke_test.py:39`).
- Live loops swallow exceptions and log them with `log_event("ERROR", f"... {e!r}")`, then continue. See `scanner.py:250` (broadcast failure) and `scanner.py:287` (per-message WS failures).
- WS reconnect loop catches everything, logs, sleeps 5s, retries: `scanner.py:289-291`.
- I/O helpers use narrow `except` clauses with explicit error tuples and silent fallbacks:
  ```python
  except (json.JSONDecodeError, OSError):
      return default
  except (ValueError, json.JSONDecodeError, OSError):
      return []
  ```
  (`state.py:23`, `config.py:40`).
- Network calls use `requests.get(..., timeout=30)` + `r.raise_for_status()` (`data_manager.py:100-101`) or wrap in `try/except requests.RequestException` returning a fake `{"ok": False, "error": ...}` dict (`telegram_bot.py:43-47`).
- WebSocket message parsing uses `try: msg = json.loads(raw); except ValueError: continue` to skip malformed frames (`scanner.py:272-275`).

**Anti-pattern guard:** Bare `except Exception as e:` is used only at top-level loop boundaries (WS, broadcast). Not used inside business logic.

## Logging

**Framework:** Custom `log_event(level, msg)` in `state.py:159`. Writes to `state/bot.log` AND prints to stdout. Levels: `INFO`, `SIGNAL`, `WARN`, `ERROR` (anything else coerced to `INFO`).

Log file rotates at 5 MB (`LOG_ROTATE_BYTES = 5 * 1024 * 1024`) — backup goes to `state/bot.log.1`, only one backup kept (`state.py:148-156`).

**Patterns:**
- Format: `{iso_utc} [{LEVEL}] {message}` (e.g. `2026-04-27T10:00:00+00:00 [SIGNAL] OBX4 BTCUSDT 4h LONG ...`).
- Plain `print()` is also used in scripts (smoke_test, backtests) with bracketed tag prefixes: `[SMOKE]`, `[OBX4]`, `[FVG]`, `[DATA]`, `[INFO]`, `[WARN]`. This matches the `CLAUDE.md` rule: "Логи — обычный `print()`, формат `[TAG] сообщение`."
- Use `log_event` in long-running daemon code (scanner, telegram_bot). Use `print()` in one-shot scripts (smoke tests, backtests).

## Comments

**When to Comment:**
- Module docstrings are mandatory and Russian. Every file starts with a triple-quoted one-line summary in Russian: `"""Live-сканер: bootstrap + WS-поток закрытых свечей + диспатч в стратегии."""` (`scanner.py:1`).
- Inline comments are Russian and explain *why*, not *what*: `# щадяще к rate-limit` (`data_manager.py:114`), `# отсекаем незакрытую текущую свечу` (`data_manager.py:125`), `# Главное правило: подтверждающая свеча = последняя закрытая 1h.` (`scanner.py:200`).
- `CLAUDE.md` explicitly permits Russian comments.

**JSDoc/TSDoc:**
- N/A (Python). Function docstrings are short, one-line, Russian, only on non-trivial helpers (`data_manager.py:25,33,41`, `strategies/obx4.py:197-201`).

## Function Design

**Size:** Small. Most functions are 5–30 lines. The biggest are `_dispatch_strategy` (~75 lines, `scanner.py:176`) and `detect_obx4_bullish` (~50 lines, `strategies/obx4.py:78`). No 200-line monsters.

**Parameters:**
- Positional + keyword. Type-hinted in public functions: `def fetch_klines_range(symbol: str, tf: str, start_ms: int, end_ms: int | None = None, limit: int = 1000) -> pd.DataFrame:`.
- Defaults are simple immutables. `field(default_factory=dict)` used for dataclass dict fields (`strategies/base.py:45,57`).

**Return Values:**
- Functions return early on empty/invalid input rather than raising:
  ```python
  if df is None or df.empty:
      return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
  ```
  (`data_manager.py:43-44`).
- Detectors return `list[Zone]` (possibly empty), never `None`.
- `find_first_confirmation_in_zone` returns `dict | None` — callers must `if confirmation is None: continue`.

## Module Design

**Exports:**
- No `__all__`. Everything not prefixed with `_` is considered public.
- Strategy modules expose `detect_zones(df, symbol, tf) -> list[Zone]` as the contract used by `scanner.STRATEGY_MAP` and `full_backtest_new.STRATEGIES`.

**Barrel Files:**
- `strategies/__init__.py` exists but is minimal; submodules are imported by full path: `from strategies import fractal, fvg, hammer, marubozu, ob_htf, obx4, rdrb` (`scanner.py:19`, `full_backtest_new.py:10`).
- No re-exports from project root.

## Data Conventions

**Time:**
- Everything in UTC, per `CLAUDE.md`. `pd.Timestamp.utcnow()` is normalized with `.tz_localize("UTC")` if naive (see `scanner.py:71-72`).
- Epoch milliseconds (`*_ms`) for Binance API. Pandas `Timestamp` (utc=True) for in-memory. ISO-8601 strings for state JSON keys.

**DataFrames:**
- Two formats coexist:
  1. `data_manager` format: lowercase columns (`open, high, low, close, volume`) with `DatetimeIndex` named `open_time`.
  2. Reference/legacy format: capitalized (`Open, High, Low, Close, Volume`) with explicit `Open time` column.
  Conversion: `strategies.obx4.to_ref_format(df)` (`strategies/obx4.py:232`). Detectors that came from reference monoliths consume the reference format; converters live in each strategy.

**State persistence:**
- JSON files in `state/`: `users.json`, `sent_signals.json`, `last_signal.json`, `admins.json`, `last_update_id.json`. Pretty-printed with `indent=2`, `ensure_ascii=False`.
- CSV files in `data/` (one file per `{SYMBOL}_{TF}.csv`) and `signals/` (backtest outputs).
- No databases, no ORM. `CLAUDE.md` forbids them explicitly.

**Dedup keys:**
- Canonical signal key: `f"{strategy}|{symbol}|{source_tf}|{direction}|{confirm_time_iso}"` (`scanner.py:42`, `strategies/base.py:60`).

---

*Convention analysis: 2026-04-27*
