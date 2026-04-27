# External Integrations

**Analysis Date:** 2026-04-27

## APIs & External Services

**Market Data (Binance Spot — public, no API key required):**
- Binance REST klines — historical and incremental candle download.
  - SDK/Client: raw `requests.get` calls in `data_manager.py:fetch_klines_range` and `data_manager.py:fetch_full_history`.
  - Endpoint: `https://api.binance.com/api/v3/klines` (constant `BINANCE_KLINES_URL` in `data_manager.py:16`).
  - Params: `symbol`, `interval`, `startTime`, `endTime`, `limit=1000`. Batched pagination with `time.sleep(0.15)` between pages for rate-limit politeness (`data_manager.py:114`).
  - Auth: none (public endpoint).

- Binance WebSocket combined streams — live closed-candle events.
  - SDK/Client: `websockets` library in `scanner.py:ws_loop`.
  - Endpoint: `wss://stream.binance.com:9443/stream` (constant `BINANCE_WS_BASE` in `scanner.py:24`).
  - Streams: built dynamically as `{symbol_lower}@kline_{tf}` for each (symbol, native_tf) pair (`scanner.py:_stream_names`). With 3 symbols × 8 native TFs = 24 streams subscribed.
  - Reconnect: `while True` loop with `await asyncio.sleep(5)` on disconnect (`scanner.py:289-291`); `ping_interval=30, ping_timeout=15`.
  - Filtering: only acts on `k["x"] == True` (closed-candle flag) per `scanner.py:278`.

**Telegram Bot API:**
- Used for sending signals, broadcasts, and handling user commands.
  - SDK/Client: raw `requests.post` in `telegram_bot.py:_api`.
  - Endpoint base: `https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}` (constant `API_BASE` in `telegram_bot.py:21`).
  - Auth: bot token via env var `TELEGRAM_BOT_TOKEN` (loaded in `config.py:21`).
  - Methods used: `sendMessage` (HTML parse mode, web previews disabled, optional reply markup), `getUpdates` (long-poll style, but called with `timeout=0` from a 2s asyncio loop in `polling_loop`).
  - Update offset persisted to `state/last_update_id.json` (`telegram_bot.py:LAST_UPDATE_PATH`).

**TradingView (deep links only, no API):**
- Outbound chart URLs embedded in inline keyboards.
  - Implementation: `strategies/base.py:tradingview_url` returns `https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}&interval={...}`.
  - Used in `telegram_bot.py:signal_inline_kb` to attach a "📊 TradingView" button to every signal message.

## Data Storage

**Databases:**
- None. Project explicitly avoids databases (`CLAUDE.md`: "Никаких ORM, базы данных").

**File Storage (local filesystem only):**
- OHLCV candles: `data/{SYMBOL}_{TF}.csv` — written by `data_manager.py:save_df`, read by `data_manager.py:load_df`. 30 files present (3 symbols × 10 timeframes).
- State JSON files in `state/`:
  - `users.json` — subscriber list (list of `{id, username, first_name, joined_at, last_active}`).
  - `sent_signals.json` — dedup map keyed `{strategy}|{symbol}|{tf}|{direction}|{confirm_time_iso}` → payload.
  - `last_signal.json` — most recent broadcasted signal payload.
  - `admins.json` — list of admin chat IDs.
  - `last_update_id.json` — Telegram `getUpdates` offset cursor.
  - `bot.log` — append-only log; rotated to `bot.log.1` at 5 MB by `state.py:_rotate_log_if_needed`.
- Generated reports: `signals_report.html`, `dashboard.html` (built by `generate_report.py`, `generate_dashboard.py`).

**Caching:**
- None as a separate layer. CSV files act as the cache for Binance REST history (incremental updates via `update_df_incrementally`).

## Authentication & Identity

**Auth Provider:**
- None. The bot has no user authentication beyond Telegram chat identity (Telegram delivers `chat_id` and `from.username` in updates).
- Authorization model:
  - Subscribers: any user who triggers `/start` or "▶️ Подписаться" is added to `state/users.json` via `state.py:upsert_user`.
  - Admins: chat IDs listed in `state/admins.json`, checked by `config.py:is_admin`. Managed in-band via `/admin_add <id>` and `/admin_remove <id>` slash commands (`telegram_bot.py:281-310`), gated by `is_admin(chat_id)`.
  - Admin-only commands: `/users`, `/admin_add`, `/admin_remove`, `/broadcast` (`telegram_bot.py:269`).

## Monitoring & Observability

**Error Tracking:**
- None. No Sentry / Rollbar / Bugsnag integration.

**Logs:**
- Custom append-only logger at `state/bot.log` via `state.py:log_event` (writes both to file and `print()`).
- Levels: INFO, SIGNAL, WARN, ERROR (normalized in `state.py:159-162`).
- Rotation: single backup file `bot.log.1` swapped at 5 MB (`LOG_ROTATE_BYTES = 5 * 1024 * 1024`).
- Admin startup notification: bot sends an HTML "🤖 Бот запущен" summary to every admin in `state/admins.json` on boot (`main.py:34-45`).

## CI/CD & Deployment

**Hosting:**
- Not specified. No deployment manifests in repo.

**CI Pipeline:**
- None. No `.github/`, `.gitlab-ci.yml`, `circleci`, or other CI configs.

## Environment Configuration

**Required env vars:**
- `TELEGRAM_BOT_TOKEN` — Telegram Bot API token. Read in `config.py:21`; validated as non-empty and not equal to placeholder `"replace_me_with_real_bot_token"` in `main.py:13`.

**Other env vars referenced in docs but not in code:**
- `ADMIN_CHAT_ID` — mentioned in `CLAUDE.md` as a `.env` value, but actual admin storage is `state/admins.json` (no `os.getenv("ADMIN_CHAT_ID")` call exists).

**Secrets location:**
- `.env` file at project root (gitignored via `.gitignore` line 2).
- No secret manager integration; the token sits on the filesystem in plaintext.

## Webhooks & Callbacks

**Incoming:**
- None. The bot uses Telegram long-poll (`getUpdates` in `telegram_bot.py:check_updates`) on a 2-second asyncio interval — there is no HTTP server listening for webhook deliveries.

**Outgoing:**
- Telegram `sendMessage` calls (per-signal, per-broadcast) — see `telegram_bot.py:send_message`, `broadcast_signal`, `broadcast`.
- No outbound webhooks to third-party services.

---

*Integration audit: 2026-04-27*
