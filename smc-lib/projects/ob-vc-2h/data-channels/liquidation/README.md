# Liquidation channel — realistic situation

## What's available historically (free)

| Source | Free? | Historical depth | Notes |
|---|---|---|---|
| **Binance allForceOrders REST** | yes | ❌ DECOMMISSIONED | API removed (2023) |
| **Binance WebSocket forceOrder** | yes | live only | use live_collector.py |
| **Coinglass v4 API** | requires free API key | ~5y on free tier | rate-limited 30 req/min |
| **Coinalyze API** | requires free API key | ~3y | rate-limited |
| **Bybit liquidation WebSocket** | yes | live only | similar to Binance |
| **Tardis.dev** | ❌ paid | full | $$$ |

## Strategy for v1.5

1. **Start live_collector.py NOW** → накапливаем с этого момента
   - В 3-6 месяцев будет статистика для v2 ML
2. **For v1.5 ML на 9.4k events** — liquidation channel = NaN
   - Принимаем missing channel в LightGBM
   - Не делаем фичи на этом канале до накопления

## Optional: получить Coinglass key

Если хочешь добавить liquidation history сейчас (1-2 года):
1. Зарегистрироваться https://coinglass.com → API → Get Free Key
2. Положить ключ в `data-channels/liquidation/coinglass_key.txt`
3. Запустить `python3 fetch_coinglass.py` (создам после получения ключа)

## Running live collector

```bash
# foreground (для теста):
cd ~/smc-lib/projects/ob-vc/data-channels/liquidation
python3 live_collector.py

# или background daemon:
nohup python3 live_collector.py > collector.log 2>&1 &
```

Output: `live/YYYY-MM-DD.parquet` (одна в день).
