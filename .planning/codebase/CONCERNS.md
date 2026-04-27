# Codebase Concerns

**Analysis Date:** 2026-04-27

This audit consolidates findings from `REVIEW.md` (snapshot 2026-04-24) and a fresh review of the
live source tree. Items are categorized by severity and impact.

---

## Tech Debt

**Two-format DataFrame contract (lowercase vs reference/Capitalized):**
- Issue: `data_manager.load_df` returns a lowercase OHLCV frame with a `DatetimeIndex`, while
  strategy detectors and `ob1h_core` consume a Capitalized `Open/High/Low/Close/Volume` schema
  with an explicit `Open time` column. The adapter `to_ref_format` lives inside a strategy file
  and is imported by `scanner.py`. Easy to forget when adding a new code path.
- Files: `data_manager.py:69` (`load_df`), `strategies/obx4.py` (`to_ref_format`),
  `scanner.py:21` (import), `strategies/ob1h_core.py`
- Impact: Whole class of silent bugs (KeyError on `Open time` or wrong index type) when a new
  detector or scan path is added without the adapter.
- Fix approach: Move `to_ref_format` to `strategies/base.py` (or `data_manager.py`) and have
  `load_df` return ref-format consistently; or migrate detectors to lowercase. Either direction
  is fine — the duplication is the problem (REVIEW M-3 / L-2).

**`state.*` JSON re-read on every call:**
- Issue: `load_users`, `load_sent_signals`, `was_sent`, `mark_sent`, `save_users`,
  `save_sent_signals` parse the entire JSON file on every invocation. During a broadcast of N
  signals to M users, each `was_sent → mark_sent → load_users` chain re-reads
  `sent_signals.json` (already 3.4 MB / 108k lines) and `users.json` repeatedly.
- Files: `state.py:39` (`load_users`), `state.py:118` (`load_sent_signals`),
  `state.py:126` (`was_sent`), `state.py:130` (`mark_sent`)
- Impact: O(N·K·|sent|) disk reads. Currently negligible (few subscribers), but degrades
  superlinearly with growth.
- Fix approach: In-memory cache with write-through; or migrate dedup keys to a `set` in memory
  with periodic flush (REVIEW H-2).

**`sent_signals.json` has no retention policy:**
- Issue: Dedup keys accumulate indefinitely; the file is already 3,566,654 bytes / ~108k lines
  after a few days of operation. Each `mark_sent` rewrites the whole file.
- Files: `state.py:130` (`mark_sent`), `state/sent_signals.json`
- Impact: Disk write latency grows linearly; eventually each broadcast iteration becomes slow.
- Fix approach: Drop entries older than 30 days during `mark_sent` or via a daily janitor task
  (REVIEW invariant 7).

**Reference originals committed alongside refactored code:**
- Issue: `reference/{obx4_original.py, fvg_original.py, fractal_vasya_original.py,
  rdrb_original.py}` (~58 KB) live in the tracked tree as historical originals.
- Files: `reference/*.py`
- Impact: Repository noise; readers may grep these and act on stale logic.
- Fix approach: Either delete (Git history retains them) or move to a clearly archival path and
  document their non-authoritative status.

**Multiple parallel backtest entrypoints:**
- Issue: `backtest_year.py`, `full_backtest_new.py`, `full_backtest_obx4.py`,
  `smoke_test.py`, `smoke_test_fvg.py`, `smoke_test_obx4.py` — six top-level scripts with
  overlapping responsibilities and no shared CLI.
- Files: `backtest_year.py`, `full_backtest_new.py`, `full_backtest_obx4.py`, `smoke_test*.py`
- Impact: Drift between scripts; unclear which is canonical.
- Fix approach: Consolidate into a single `backtest.py` with subcommands, or document which is
  authoritative.

**Duplicate signal-payload dict shapes:**
- Issue: `_signal_payload` and `_sig_to_dict` (and the inline `sig_data` in
  `scanner._dispatch_strategy`) build similar-but-different field sets for `mark_sent` and for
  `broadcast_signal`. Easy to drift.
- Files: `scanner.py:206` (inline payload), `strategies/base.py`
- Impact: A new field added in one place is silently absent in the other.
- Fix approach: Single dataclass / TypedDict for the on-the-wire signal (REVIEW L-1).

**Scanner imports include detectors that may never be active per environment:**
- Issue: `scanner.py:19` imports `fractal, fvg, hammer, marubozu, ob_htf, obx4, rdrb`. If any
  detector raises at import time (e.g. dependency missing), the entire bot fails to start.
- Files: `scanner.py:19`
- Impact: Coupling — one broken strategy kills the live bot.
- Fix approach: Lazy-import strategies inside `STRATEGY_MAP` builder, or wrap in try/except with
  a `log_event("WARN", ...)`.

---

## Known Bugs

**`_prefill_today_signals` not re-run across UTC midnight (REVIEW H-1):**
- Symptoms: After a continuous run that crosses 00:00 UTC, the silent prefill marker is never
  reissued for the new day. On a mid-day restart, today's OBs are missing from `sent_signals`,
  so the only protection is the "main rule" `confirm_time == last_1h_open`, which accepts a
  single OB. Outcome: occasional unwanted re-broadcast of a today-OB on restart.
- Files: `scanner.py:67` (single call from `startup`), `scanner.py:69` (`_prefill_today_signals`)
- Trigger: Bot uptime spans UTC midnight, then restarts later that same day.
- Workaround: Restart immediately after midnight, or accept the rare duplicate.

**`last_1h_open` may be stale relative to dispatched higher-tf event (REVIEW M-2):**
- Symptoms: When a 4h/2h candle closes, `_dispatch_strategy` reads `df_1h.iloc[-1]["Open time"]`
  without first refreshing the 1h CSV. If the matching 1h-close event arrived later, the OB
  for the freshly closed 1h is missed — the equality check fails.
- Files: `scanner.py:142` (`df_1h = to_ref_format(load_df(symbol, "1h"))`),
  `scanner.py:193` (`last_1h_open = ...`)
- Trigger: Two WS events for the same symbol within milliseconds; thread scheduling.
- Workaround: None automatic — restart triggers prefill catch-up.
- Fix: Force `update_df_incrementally(symbol, "1h")` at the top of `on_closed_native_candle`
  when `tf != "1h"`.

**`was_sent → mark_sent` race between concurrent threads (REVIEW M-1):**
- Symptoms: When `1h` and `2h` candles close at the same UTC second (e.g. 02:00), two
  `asyncio.to_thread(self.on_closed_native_candle, ...)` workers run in parallel. Both can pass
  `was_sent` before either calls `mark_sent`, producing a duplicate broadcast.
- Files: `scanner.py:222-241` (the `if was_sent → broadcast → mark_sent` block),
  `scanner.py:285-286` (parallel `to_thread` dispatch)
- Trigger: Native-tf alignment (1h+2h+4h all closing on the 4h/2h boundary).
- Workaround: Low probability in practice; no mitigation in code.
- Fix: `threading.Lock` around the critical section in `_dispatch_strategy`.

**No graceful shutdown — WS not closed on SIGINT (REVIEW L-6):**
- Symptoms: `Ctrl+C` propagates as `KeyboardInterrupt` in `main.py:58`, but `ws_loop` never
  invokes `ws.close()`. Pending in-flight packets may be lost; Binance sees a dropped
  connection.
- Files: `main.py:56` (try/except KeyboardInterrupt only), `scanner.py:262` (`ws_loop`)
- Workaround: Restart will re-prefill within the 48h window.
- Fix: Asyncio cancellation-aware shutdown that awaits `ws.close()` and final `log_event`.

---

## Security Considerations

**Secrets in plaintext `.env` at project root:**
- Risk: `TELEGRAM_BOT_TOKEN` and `ADMIN_CHAT_ID` live in `.env` (90 bytes). The file is
  correctly listed in `.gitignore:3` and is NOT tracked by Git (`git ls-files` confirms). No
  evidence of token leakage in commits.
- Files: `.env` (existence noted only — contents not quoted)
- Current mitigation: `.gitignore` covers `.env`. `config.py:7` uses `python-dotenv`.
- Recommendations:
  - Add a `.env.example` with placeholder values to document required keys.
  - Consider OS keychain or a secret manager for production deploys (not just `.env`).
  - Validate at startup that the token is non-empty (already partially done in `main.py:13`).
  - On token compromise, rotate via BotFather; nothing in the repo enforces rotation.

**No authentication beyond `chat_id` allow-list:**
- Risk: Admin commands (`/users`, `/admin_add`, `/admin_remove`, `/broadcast`) gate on
  `is_admin(chat_id)` which reads `state/admins.json`. Anyone able to write to that file (local
  disk, deploy host) becomes an admin.
- Files: `telegram_bot.py:269` (admin command gate), `config.py:34` (`load_admins`)
- Current mitigation: File-system permissions (implicit).
- Recommendations: Document required FS permissions on deploy; consider signing
  `admins.json` or pulling from env.

**`/broadcast` accepts arbitrary HTML:**
- Risk: `send_message` uses `parse_mode=HTML`. The admin `/broadcast` text is forwarded to all
  subscribers without escaping. Any admin can inject unrestricted HTML, including links.
- Files: `telegram_bot.py:54-66` (`send_message`), `telegram_bot.py:107` (`broadcast`),
  `telegram_bot.py:313` (admin `/broadcast` handler)
- Current mitigation: Admin-only.
- Recommendations: This is acceptable for a trusted-admin bot, but document the trust model.

**Synchronous `requests.post` to Telegram with 30s timeout, no retry/backoff:**
- Risk: Network blip → broadcast partial failure with no retry. Hostile/DNS issues block the
  scanner thread for up to 30 s per user.
- Files: `telegram_bot.py:43-47` (`_api`), `telegram_bot.py:87` (`broadcast_signal`)
- Current mitigation: Per-user try/except so one failure does not abort the loop.
- Recommendations: Add bounded retry on 5xx + 429; consider `aiohttp` async parallel.

**No rate-limit handling for Telegram (REVIEW Not Verified):**
- Risk: Telegram enforces ~30 msg/s globally per bot. Above ~50 subscribers, a single broadcast
  iteration can hit `429 Too Many Requests`. Current code logs WARN and moves on.
- Files: `telegram_bot.py:87-104`
- Recommendations: Honour `retry_after` from 429 responses; introduce a token-bucket sender.

**No input validation on Binance WS payloads:**
- Risk: `scanner.py:271-282` parses `msg["data"]["k"]` defensively (with `.get`) but assumes
  numeric correctness downstream. Malformed messages slip through to `update_df_incrementally`.
- Files: `scanner.py:271-286`
- Current mitigation: Outer `try/except Exception as e` logs and continues.

**`requests` HTTPS without certificate pinning:**
- Risk: Standard CA chain, no pinning for `api.telegram.org` or `api.binance.com`. MITM via
  rogue CA is theoretically possible.
- Files: `telegram_bot.py:44`, `data_manager.py:100`
- Current mitigation: HTTPS + system trust store.
- Recommendations: Acceptable for this risk profile; pinning is overkill for a hobby bot.

---

## Performance Bottlenecks

**Blocking broadcast inside scanner thread (REVIEW H-3):**
- Problem: `broadcast_signal` is called synchronously from
  `asyncio.to_thread(self.on_closed_native_candle, ...)`. With 100 users × ~200 ms per
  `requests.post`, a single broadcast occupies one worker thread for ~20 s.
- Files: `scanner.py:226` (`broadcast_signal(sig_data)`),
  `telegram_bot.py:87-104` (sequential per-user loop)
- Cause: Sequential `requests.post` per user.
- Improvement path: Move to `aiohttp` with `asyncio.gather` and per-user tasks, or push to a
  separate queue/worker.

**Whole-file rewrite for every `mark_sent`:**
- Problem: `_write_json(SENT_PATH, d)` rewrites the entire 3.4 MB JSON file on each new key.
- Files: `state.py:122` (`save_sent_signals`), `state.py:130` (`mark_sent`)
- Cause: No append-only log or DB.
- Improvement path: Append-only JSONL with periodic compaction; or SQLite for dedup keys.

**`load_users` JSON parse on every send:**
- Problem: `broadcast_signal` calls `load_users()` once per signal, but each
  `_action_*`/`is_subscribed`/`upsert_user`/`get_user` call also reparses `users.json`.
- Files: `state.py:69` (`get_user`), `state.py:76` (`is_subscribed`), `state.py:80`
  (`upsert_user`)
- Improvement path: Cache parsed users with `mtime` invalidation.

**`generate_dashboard.py` reads full `bot.log` (REVIEW L-5):**
- Problem: `tail -1000` semantics implemented as `read_text().splitlines()[-1000:]`.
- Files: `generate_dashboard.py`
- Improvement path: `seek(end - N)` reverse-read; not urgent at 5 MB rotation cap.

**`update_df_incrementally` issues sync `requests.get` with `time.sleep(0.15)` (REVIEW L-4):**
- Problem: Per-batch `0.15 s` sleep blocks the worker thread (not the event loop).
- Files: `data_manager.py:114`
- Improvement path: Acceptable for the current batch volume; revisit only on full re-bootstrap.

---

## Fragile Areas

**`scanner._dispatch_strategy` "main rule" `confirm_time == last_1h_open`:**
- Files: `scanner.py:201`
- Why fragile: Equality on UTC `Timestamp` objects from two independently loaded DataFrames.
  Any timezone normalisation drift, resample-induced shift, or out-of-order `update_df` causes
  a silent miss (no log, no metric).
- Safe modification: Always compare with `pd.Timestamp.tz_convert("UTC")` and assert
  invariants; add a debug log when the comparison rejects a candidate (currently silent).
- Test coverage: None — the project explicitly opts out of tests (`CLAUDE.md` "Чего НЕ делать").

**Composed timeframes (3h, 2d) recomputed on every base close:**
- Files: `scanner.py:138-140` (`_recompose`), `data_manager.py:167` (`compose_from_base`)
- Why fragile: Resample uses `origin="epoch", label="left", closed="left"`. Any change to those
  flags shifts every composed bar's `Open time` and breaks `was_sent` keys retroactively.
- Safe modification: Treat the resample params as a frozen contract; document them in
  `data_manager.py`. Do not change without a `sent_signals.json` migration.

**`signal_key` vs `_sig_key_str` naming (REVIEW "что не менять", item 5):**
- Files: `scanner.py:42` (`_sig_key_str`), `strategies/ob1h_core.py`
- Why fragile: Different format between scanner-level and core-level keys (scanner uses
  `meta["source_tf"]`, core may use `timeframe`). Easy to swap mistakenly.
- Safe modification: Rename one of them and add a docstring; keys touched by `mark_sent`
  must remain byte-identical.

**`asyncio.to_thread` + shared file state without locking:**
- Files: `scanner.py:285-286` (concurrent dispatch), `state.py` (no locks)
- Why fragile: All state writes are unsynchronised. Concurrency invariants rely on the GIL plus
  the fact that JSON writes are single `f.write` calls — but `_write_json` performs
  `json.dump(..., indent=2)` which is many writes inside an `open(...)` context. A second
  writer can interleave and corrupt the file.
- Safe modification: Add a module-level `threading.Lock` to `_write_json` (cheap, near-zero
  overhead at current load).

**`update_df_incrementally` silently truncates the last unclosed candle:**
- Files: `data_manager.py:158-161`
- Why fragile: Heuristic `last_open_ms + step > now_ms`. Clock skew between local host and
  Binance can drop a freshly-closed candle that triggered the WS event.
- Safe modification: Trust WS `k["x"]==True` as truth and accept the bar regardless of clock.

---

## Scaling Limits

**Subscribers (REVIEW Not Verified):**
- Current capacity: A few subscribers (single-digit confirmed in production).
- Limit: ~50–100 before sequential `requests.post` per broadcast hits Telegram's 30 msg/s.
- Scaling path: Async parallel sender + retry-after handling. See "Performance Bottlenecks".

**`sent_signals.json` size:**
- Current capacity: ~108k keys, ~3.4 MB.
- Limit: At ~50 MB the per-`mark_sent` rewrite latency becomes user-visible (~hundreds of ms).
- Scaling path: Retention + compaction, or SQLite.

**Disk usage from CSVs (REVIEW Not Verified):**
- Current capacity: ~38 MB across 30 files, growing daily.
- Limit: A bootstrap from `HISTORY_START_DATE = "2022-01-01"` for additional symbols/tfs would
  multiply this.
- Scaling path: Switch CSV → Parquet for ~5–10× compression.

**Single Binance WS connection for 24 streams:**
- Current capacity: 3 symbols × 8 native tfs = 24 streams over a single connection.
- Limit: Binance enforces 1024 streams per connection — far above current load.
- Scaling path: None needed.

---

## Dependencies at Risk

**`requirements.txt` is unpinned beyond top-level:**
- Files: `requirements.txt` (69 bytes — minimal pin)
- Risk: `pandas`, `requests`, `websockets`, `python-dotenv` floats; a transitive update can
  break `pd.resample(..., origin="epoch", label="left", closed="left")` semantics.
- Impact: Reproducibility / drift between dev and prod.
- Migration plan: Generate `requirements.lock` via `pip freeze > requirements.lock` and commit.

**`requests` (sync) used inside an async app:**
- Files: `telegram_bot.py:8`, `data_manager.py:13`
- Risk: `requests` is in maintenance mode; Python 3.13 compatibility is fine but the synchronous
  pattern forces `asyncio.to_thread` everywhere.
- Migration plan: Migrate to `httpx.AsyncClient` (drop-in API), gain async + connection pooling.

**`python-telegram-bot` not used:**
- Files: `telegram_bot.py` (rolls its own `requests.post`-based client)
- Risk: Manual handling of `getUpdates` offsets, no support for retry-after/429, no high-level
  abstractions. Each Telegram API change requires manual updates.
- Migration plan: Adopt `python-telegram-bot` v21+ (async-native) and drop the custom polling.

---

## Missing Critical Features

**No metrics / health endpoint:**
- Problem: No way to assert "bot is alive" beyond reading `state/bot.log`. Cannot integrate with
  external uptime monitors.
- Blocks: External alerting on WS disconnect, no SLA visibility.

**No persistent crash trace:**
- Problem: `try/except Exception as e: log_event("ERROR", ...)` everywhere — but tracebacks are
  not captured (only `repr(e)`).
- Files: `scanner.py:250`, `scanner.py:287`, `scanner.py:289`, `telegram_bot.py:348`,
  `telegram_bot.py:360`, `main.py:25`
- Blocks: Post-mortem debugging from logs alone is impossible — no stack frames.
- Fix approach: `log_event("ERROR", traceback.format_exc())` in critical handlers.

**No user-removal automation on `Forbidden: bot was blocked` (REVIEW M-5):**
- Problem: When a user blocks the bot, every subsequent broadcast logs WARN forever.
- Files: `telegram_bot.py:65` (logs the failure), `telegram_bot.py:87-104`
- Blocks: Log noise; future scaling friction.
- Fix approach: Inspect `description` for `"blocked"` / `"chat not found"` and call
  `remove_user(uid)`.

**No re-prefill on UTC midnight crossing (REVIEW H-1, also listed under Bugs):**
- Problem: See "Known Bugs" above.
- Blocks: Confidence in 24/7 unattended operation.

---

## Test Coverage Gaps

The project explicitly disclaims tests in `CLAUDE.md` ("Не покрывать тестами — проект
одноразовый, проверка = живые сигналы"). The `smoke_test*.py` files are ad-hoc scripts, not
a test suite, and no test runner is configured.

**Untested critical paths:**
- `scanner._dispatch_strategy` "main rule" (`confirm_time == last_1h_open`)
  — files: `scanner.py:176-251`
  — risk: A regression silently drops every signal; the only signal is "users complain".
- Dedup key construction (`_sig_key_str`)
  — files: `scanner.py:42`
  — risk: A format tweak invalidates all existing `sent_signals.json` keys.
- `compose_from_base` resample contract
  — files: `data_manager.py:167`
  — risk: Composed-tf bar boundaries shift; OB detection breaks invisibly.
- `_prefill_today_signals` cutoff/today filter
  — files: `scanner.py:69`
  — risk: Either over-marks (suppresses legitimate signals) or under-marks (duplicate sends).
- Telegram broadcast retry / failure handling
  — files: `telegram_bot.py:87-125`
  — risk: Silent partial broadcast on network blip.

**Priority:** Medium. Given the project philosophy, a thin pytest layer around the four items
above (pure-function tests against fixture CSVs) would catch every class of bug seen so far
without violating the "no test framework" rule.

---

## Repository Hygiene

**`signals_report.html` (23 MB) on disk but NOT in Git:**
- File: `signals_report.html` (23,506,574 bytes / ~22 MB on disk)
- Status: Listed in `.gitignore:14`. Confirmed via `git ls-files` — file is NOT tracked. Good.
- Concern: The artifact still occupies developer working trees and is regenerated by
  `generate_report.py`. Anyone cloning fresh will not see it; anyone running the report locally
  produces a 22 MB transient file.
- Recommendation: No action required — gitignore handles it. Optionally route output to a
  `dist/` or `out/` directory to keep the repo root tidy.

**`__pycache__/` present at project root:**
- File: `__pycache__/`
- Status: Listed in `.gitignore:4`. Confirmed not tracked.
- Concern: None — informational only.

**Backtest CSVs in `signals/` (~9 MB) not in Git:**
- Files: `signals/backtest_*.csv`
- Status: `signals/` is gitignored (`.gitignore:11`). Confirmed not tracked.
- Concern: None — informational only.

**`venv/` shipped at root but ignored:**
- Files: `venv/`
- Status: `.gitignore:2`. Not tracked.
- Concern: None.

**`.DS_Store` in `.gitignore` but a file exists at the project root:**
- File: `.DS_Store`
- Status: macOS metadata. Ignored by `.gitignore:5`. Not tracked.
- Concern: None.

---

*Concerns audit: 2026-04-27*
