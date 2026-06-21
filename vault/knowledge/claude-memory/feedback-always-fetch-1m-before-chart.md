---
name: feedback-always-fetch-1m-before-chart
description: "При генерации любого графика BTC ВСЕГДА сначала вызывать fetch_btc_1m_missing.py, чтобы данные и текущая цена были актуальны"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3af6f0d9-c3ee-48ba-ae08-4c05d8c82af3
---

При построении ЛЮБОГО чарта (BTC/ETH/SOL) сначала вызывать generic fetch script `~/smc-lib/scripts/fetch_1m_missing.py SYMBOL`, чтобы докачать недостающие 1m свечи из Binance public REST. Только после этого читать CSV и строить график.

**Why:** Пользователь просит видеть актуальную текущую цену и свежие бары. CSV-файл не обновляется автоматически, и без явного fetch'а в чарте будет показано «вчерашнее» состояние рынка. (BTC-specific `fetch_btc_1m_missing.py` deprecated — generic version с CLI-параметром symbol работает для всех.)

**How to apply:**
- Generic fetcher: `python3 ~/smc-lib/scripts/fetch_1m_missing.py BTCUSDT` (или SOLUSDT / ETHUSDT)
- В каждом plot_*.py скрипте, который читает `~/traid-bot/data/<SYMBOL>_1m_vic_vadim.csv`, добавлять в самом начале:
  ```python
  import subprocess, sys, pathlib
  FETCH = pathlib.Path.home() / "smc-lib/scripts/fetch_1m_missing.py"
  symbol = 'BTCUSDT'   # или из CLI: sys.argv[1]
  subprocess.run([sys.executable, str(FETCH), symbol], capture_output=True, text=True, timeout=300)
  ```
- Эталон — `~/smc-lib/expert/chart.py` (parameterized по ASSET CLI-arg).
- Закреплено в [[../smc-lib/chart_format.md|chart_format.md §1]].
- Старый `fetch_btc_1m_missing.py` оставлен как legacy alias, но новые скрипты используют generic.
