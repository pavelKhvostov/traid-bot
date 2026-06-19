"""Fetch cross-asset OHLCV for ML context features.

Channels:
  - DXY            (Dollar index)        -> yfinance "DX-Y.NYB"
  - US10Y          (10-year yield)       -> yfinance "^TNX"
  - SPX            (S&P 500)             -> yfinance "^GSPC"
  - GOLD           (gold futures)        -> yfinance "GC=F"
  - ETHBTC         (ETH/BTC perpetual)   -> Binance ETHBTC spot klines
  - TOTAL_MCAP     (crypto total mcap)   -> CoinGecko global market data
  - BTC_DOMINANCE  (BTC dominance %)     -> CoinGecko global market data

Granularity: 1d for macro (sufficient for ML feature on 2h ob_vc events).

Output: ~/smc-lib/projects/ob-vc/data-channels/cross_asset/{NAME}_1d.parquet
  columns: ts_ms, open, high, low, close, volume (if available)
"""
from __future__ import annotations
import pathlib
import subprocess
import sys
import time
import json
from datetime import datetime, timezone

import pandas as pd

OUT_DIR = pathlib.Path(__file__).resolve().parent
START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _curl_json(url: str) -> dict | list:
    for attempt in range(5):
        try:
            r = subprocess.run(["curl", "-sS", "--connect-timeout", "10",
                                 "--max-time", "30", url],
                                capture_output=True, text=True, timeout=45)
            if r.returncode == 0 and r.stdout.strip()[:1] in ("[", "{"):
                return json.loads(r.stdout)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def fetch_binance_klines(symbol: str, interval: str = "1d") -> pd.DataFrame:
    URL = "https://api.binance.com/api/v3/klines"
    all_rows = []
    cursor = START_MS
    now_ms = int(time.time() * 1000)
    while cursor < now_ms:
        url = f"{URL}?symbol={symbol}&interval={interval}&startTime={cursor}&limit=1000"
        chunk = _curl_json(url)
        if not chunk:
            break
        all_rows.extend(chunk)
        last = chunk[-1][0]
        if last <= cursor:
            break
        cursor = last + 1
        time.sleep(0.10)
    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows, columns=[
        "ts_ms", "open", "high", "low", "close", "volume",
        "close_ts_ms", "qav", "n_trades", "tbb", "tbq", "ignore"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c])
    df["ts_ms"] = df["ts_ms"].astype(int)
    return df[["ts_ms", "open", "high", "low", "close", "volume"]].drop_duplicates(subset="ts_ms")


def fetch_yfinance(ticker: str, name: str) -> pd.DataFrame:
    """Use Yahoo Finance v8 chart API directly (no auth)."""
    p1 = START_MS // 1000
    p2 = int(time.time())
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d&events=history")
    # yahoo needs UA
    for attempt in range(5):
        try:
            r = subprocess.run(["curl", "-sS",
                                 "-H", "User-Agent: Mozilla/5.0",
                                 "--connect-timeout", "10", "--max-time", "30",
                                 url], capture_output=True, text=True, timeout=45)
            if r.returncode == 0 and r.stdout.strip().startswith("{"):
                data = json.loads(r.stdout)
                if data.get("chart", {}).get("error"):
                    print(f"  {name} yahoo error: {data['chart']['error']}")
                    return pd.DataFrame()
                break
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2 * (attempt + 1))
    else:
        return pd.DataFrame()

    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q  = res["indicators"]["quote"][0]
    df = pd.DataFrame({
        "ts_ms": [int(t)*1000 for t in ts],
        "open":  q.get("open", []),
        "high":  q.get("high", []),
        "low":   q.get("low", []),
        "close": q.get("close", []),
        "volume": q.get("volume", []),
    })
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df


def fetch_coingecko_global() -> pd.DataFrame:
    """Coingecko global has only current snapshot via free API; for history need /coins/markets per asset.
    Build proxy: total_mcap = BTC_mcap / BTC_dominance.
    Better: use 'global market cap chart' if it exists -- /global/market_cap_chart but that's paid pro.

    For v1 we fetch BTC dominance daily from CoinGecko's free /global endpoint snapshots — fall back gracefully.
    """
    url = "https://api.coingecko.com/api/v3/global"
    try:
        d = _curl_json(url)["data"]
        snap = {
            "ts_ms": int(time.time()*1000),
            "btc_dominance": d["market_cap_percentage"]["btc"],
            "eth_dominance": d["market_cap_percentage"]["eth"],
            "total_mcap_usd": d["total_market_cap"]["usd"],
            "total_volume_usd": d["total_volume"]["usd"],
        }
        return pd.DataFrame([snap])
    except Exception as e:
        print(f"  coingecko global failed: {e}")
        return pd.DataFrame()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("─" * 60)
    print("Cross-asset fetch")
    print("─" * 60)

    # 1. Binance ETHBTC
    print("\n[ETHBTC] Binance spot 1d...")
    df = fetch_binance_klines("ETHBTC", "1d")
    if not df.empty:
        out = OUT_DIR / "ETHBTC_1d.parquet"
        df.to_parquet(out, index=False)
        print(f"  rows: {len(df):,}  saved -> {out.name}")

    # 2. Yahoo Finance tickers
    tickers = [
        ("DX-Y.NYB", "DXY"),
        ("^TNX",     "US10Y"),
        ("^GSPC",    "SPX"),
        ("GC=F",     "GOLD"),
    ]
    for ticker, name in tickers:
        print(f"\n[{name}] yfinance {ticker}...")
        df = fetch_yfinance(ticker, name)
        if not df.empty:
            out = OUT_DIR / f"{name}_1d.parquet"
            df.to_parquet(out, index=False)
            print(f"  rows: {len(df):,}  saved -> {out.name}")
        else:
            print(f"  {name}: no data")

    # 3. Coingecko global (snapshot for now)
    print("\n[Coingecko global] BTC dominance snapshot...")
    snap = fetch_coingecko_global()
    if not snap.empty:
        out = OUT_DIR / "coingecko_global_snapshot.parquet"
        snap.to_parquet(out, index=False)
        print(f"  saved -> {out.name}  (snapshot only; full history requires paid CoinGecko Pro)")
        for k, v in snap.iloc[0].items():
            print(f"    {k}: {v}")

    print("\n" + "─" * 60)
    print("Cross-asset done")
    print("─" * 60)


if __name__ == "__main__":
    main()
