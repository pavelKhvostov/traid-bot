# Testing Patterns

**Analysis Date:** 2026-04-27

## Test Framework

**Runner:**
- None. There is no `pytest`, `unittest`, `nose`, or any other automated test framework configured.
- No `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg`, `conftest.py`, or `tests/` directory exists.
- `requirements.txt` has only `pandas`, `requests`, `websockets`, `python-dotenv` — no test dependencies.

**Assertion Library:**
- None. Verification is performed via plain `raise RuntimeError(...)` and human-readable `print(...)` output.

**Run Commands:**
```bash
python smoke_test.py            # Binance fetch + Telegram round-trip check
python smoke_test_fvg.py        # FVG strategy: zones + ob1h confirmations
python smoke_test_obx4.py       # OBX4 strategy: zones + ob1h confirmations
python full_backtest_new.py     # Full historical backtest, 7 strategies, all symbols
python full_backtest_obx4.py    # OBX4-only historical backtest
python backtest_year.py         # Last-365-days backtest, 7 strategies, all symbols
python today_signals.py         # Replay today's signals (sanity check)
```

This matches the explicit project policy in `CLAUDE.md:85`: **"Не покрывать тестами — проект одноразовый, проверка = живые сигналы."** ("Don't cover with tests — the project is one-shot, verification = live signals.")

## Test File Organization

**Location:**
- All verification scripts live at the **project root** (not in a `tests/` folder).
- Smoke scripts: `/Users/pavelhvostov/Desktop/traiding/trading-signals-bot/smoke_test.py`, `smoke_test_fvg.py`, `smoke_test_obx4.py`.
- Backtest scripts: `backtest_year.py`, `full_backtest_new.py`, `full_backtest_obx4.py`, `today_signals.py`.

**Naming:**
- Smoke checks: `smoke_test.py` (infrastructure) and `smoke_test_<strategy>.py` (per-strategy).
- Backtests: `full_backtest_<scope>.py` for full-history, `backtest_<window>.py` for windowed (e.g. `backtest_year.py`).

**Structure:**
```
trading-signals-bot/
├── smoke_test.py              # Binance REST + Telegram sendMessage round-trip
├── smoke_test_fvg.py          # FVG.detect_zones + ob1h_core.scan_zones_to_signals
├── smoke_test_obx4.py         # OBX4.detect_zones + ob1h_core.scan_zones_to_signals
├── backtest_year.py           # Last 365 days, all 7 strategies, all 3 symbols → signals/backtest_year_*.csv
├── full_backtest_new.py       # Entire history, 7 strategies via scan_zones_to_signals → signals/backtest_*.csv
├── full_backtest_obx4.py      # OBX4-only entire history → signals/obx4_backtest_full.csv
├── today_signals.py           # Replay UTC-day signals
└── signals/                   # Backtest output CSVs (committed)
    ├── backtest_fractal.csv
    ├── backtest_fvg.csv
    ├── backtest_ob_htf.csv
    ├── backtest_obx4.csv
    ├── backtest_rdrb.csv
    └── obx4_backtest_full.csv
```

## Test Structure

**Suite Organization:**
Every script follows the same shape:

```python
"""Short Russian docstring describing what this script verifies."""
from __future__ import annotations

# imports: stdlib → third-party → project

def main() -> None:
    # 1. Configure (symbol, tf, cutoff)
    # 2. Load/refresh data via data_manager
    # 3. Run detectors / scan_zones_to_signals / find_first_confirmation_in_zone
    # 4. Print human-readable summary with [TAG] prefixes
    # 5. (For backtests) Write CSVs to signals/

if __name__ == "__main__":
    main()
```

Real example from `smoke_test_obx4.py:11-44`:
```python
def main() -> None:
    symbol, source_tf = "BTCUSDT", "4h"

    print(f"[OBX4] загружаем историю {symbol} {source_tf}...")
    df_htf = update_df_incrementally(symbol, source_tf)
    print(f"[OBX4] {source_tf}: {len(df_htf)} свечей")
    if df_htf.empty:
        raise RuntimeError("Пустой df_htf")

    zones = obx4.detect_zones(df_htf, symbol, source_tf)
    print(f"[OBX4] зон OBX4 найдено: {len(zones)} ...")

    df_1h_raw = update_df_incrementally(symbol, "1h")
    df_1h = to_ref_format(df_1h_raw)

    signals = scan_zones_to_signals(zones, df_1h)
    print(f"[OBX4] сработавших OB 1h сигналов: {len(signals)} из {len(zones)} зон")

    last5 = sorted(signals, key=lambda s: s.confirm_time)[-5:]
    if last5:
        for s in last5:
            print(f"{s.confirm_time.isoformat()}  {s.direction:<5}  ...")
        print(format_signal_telegram(last5[-1]))
```

**Patterns:**
- **Setup:** Real data via `update_df_incrementally(symbol, tf)` — actually hits Binance REST. No fixtures, no mocks.
- **Teardown:** None. CSVs in `data/` and `signals/` are persistent side-effects, intentionally re-used between runs.
- **Assertion:** `raise RuntimeError("...")` for hard failures (`smoke_test.py:22`, `smoke_test.py:39`, `smoke_test.py:44`, `smoke_test_obx4.py:18`). Otherwise visual eyeballing of `print()` output and committed CSVs.
- **Side effects:** Smoke tests send a real message to `ADMIN_CHAT_ID` via Telegram (`smoke_test.py:42`).

## Mocking

**Framework:** None. No `unittest.mock`, no `pytest-mock`, no recorded HTTP fixtures (no `vcr`, no `requests-mock`).

**Patterns:**
- All "tests" run against the **live** Binance public API and a **live** Telegram bot. The whole point of `smoke_test.py` is to verify the real round-trip works:
  ```python
  resp = send_message(text, ADMIN_CHAT_ID)
  if not resp.get("ok"):
      raise RuntimeError(f"Telegram sendMessage failed: {resp}")
  ```
  (`smoke_test.py:42-44`).

**What to Mock:**
- Nothing. Per project policy, verification is live-only.

**What NOT to Mock:**
- Binance REST (`https://api.binance.com/api/v3/klines` — public, no auth needed).
- Telegram Bot API (smoke checks rely on a real `TELEGRAM_BOT_TOKEN` from `.env`).

If isolation is ever needed, the seam is `data_manager.fetch_klines_range` (the only HTTP entry point for klines) and `telegram_bot._api` (the only HTTP entry point for Telegram).

## Fixtures and Factories

**Test Data:**
- Real CSVs in `data/{SYMBOL}_{TF}.csv`, populated by `update_df_incrementally` on first run. Re-used by all subsequent runs.
- Backtest output CSVs in `signals/` are versioned in git as the canonical "expected output" — diffing them is how regressions get spotted.

**Location:**
- Live data cache: `/Users/pavelhvostov/Desktop/traiding/trading-signals-bot/data/`
- Backtest results: `/Users/pavelhvostov/Desktop/traiding/trading-signals-bot/signals/`

**No factory functions.** Dataclasses (`Signal`, `Zone` in `strategies/base.py:37,48`) are constructed directly inside detectors with literal kwargs.

## Coverage

**Requirements:** None enforced. No coverage tool installed (no `coverage.py`, no `.coveragerc`, no codecov config).

**View Coverage:**
- N/A.

**Effective coverage proxy:** Diffing freshly-generated `signals/backtest_*.csv` against the committed versions:
```bash
python full_backtest_new.py
git diff signals/
```
If the CSV diffs are unexpectedly non-zero, behavior changed.

## Test Types

**Unit Tests:**
- None.

**Integration Tests:**
- The smoke scripts (`smoke_test*.py`) are integration tests in spirit: they exercise `data_manager` → `strategies.<x>` → `strategies.ob1h_core` → `strategies.base.format_signal_telegram` end-to-end against real Binance data, and `smoke_test.py` additionally exercises the Telegram path.

**E2E Tests:**
- The `main.py` daemon itself (scanner + WS + Telegram + state) is the E2E test. Verification is "did subscribers receive correct signals."
- The 365-day backtest (`backtest_year.py`) is an E2E historical replay — it walks the same `find_first_confirmation_in_zone` code path the live scanner uses (`scanner.py:195`, `backtest_year.py:154`).

**Backtest scripts (E2E historical replay):**
- `full_backtest_new.py` — runs `scan_zones_to_signals` over the full history of every `(symbol, strategy, tf)` tuple and writes one CSV per strategy to `signals/backtest_<name>.csv`. Output columns: `strategy, symbol, source_tf, direction, trigger_time_utc, zone_bottom, zone_top, first_return_time_utc, ob1h_prev_time_utc, ob1h_cur_time_utc, ob1h_cur_close, zone_age_hours` (see `full_backtest_new.py:29-35`).
- `backtest_year.py` — same but constrained to `cutoff = utcnow - 365 days` and uses `find_first_confirmation_in_zone` (the exact function the live scanner uses). Outputs `signals/backtest_year_<name>.csv` plus a combined `signals/backtest_year_all.csv`. Columns include `confirm_type` (`OB-1h | FVG-1h | RDRB-1h`) so confirmation-type distribution can be audited (see `backtest_year.py:30-46`).
- `full_backtest_obx4.py` — single-strategy variant kept around for parity checks against the original reference implementation.

## Common Patterns

**Async Testing:**
- N/A. The smoke/backtest scripts are all synchronous. Async code lives only in `scanner.py` (WS loop) and `telegram_bot.py` (polling), and is verified by running `main.py` live.

**Error Testing:**
- Failure mode in scripts: `raise RuntimeError("Russian explanation")`. No assertion of specific exception types; the goal is fast visible failure on infrastructure problems:
  ```python
  if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
      raise RuntimeError("TELEGRAM_BOT_TOKEN / ADMIN_CHAT_ID не прочитаны из .env")
  ```
  (`smoke_test.py:38-39`).

**Output Conventions:**
- Tag-prefixed `print()` messages: `[SMOKE]`, `[OBX4]`, `[FVG]`, `[DATA]`, `[INFO]`, `[WARN]`. The same convention used by `state.log_event`.
- Backtests print a final block titled `========== ИТОГО ==========` with per-strategy / per-symbol totals (see `backtest_year.py:184-188`, `full_backtest_new.py:115-118`).
- Smoke tests end with `print("[SMOKE] done ✅")` on success.

## When Adding Verification

**For a new strategy:** Add `smoke_test_<name>.py` at project root, modeled on `smoke_test_obx4.py`. Register the strategy in `full_backtest_new.STRATEGIES` and `backtest_year.STRATEGIES` so it appears in the historical CSVs.

**For new infra (e.g. new data source):** Add a `smoke_test_<infra>.py` modeled on `smoke_test.py` — fetch real data, raise `RuntimeError` on failure, print summary to stdout.

**Do NOT:**
- Add a `tests/` directory or `pytest`. The project explicitly rejects this in `CLAUDE.md:85`.
- Mock Binance or Telegram. The whole verification model assumes live calls.
- Delete CSVs in `signals/` casually — they are the regression baseline.

---

*Testing analysis: 2026-04-27*
