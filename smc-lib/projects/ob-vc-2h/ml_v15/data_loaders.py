"""Unified channel loaders — lazy-loaded singletons keyed by channel name.

Each loader returns sorted DataFrame with at least:
  - ts column (named per channel: funding_time_ms / ts_ms / event_ms)
  - value columns specific to the channel
"""
from __future__ import annotations
import pathlib
from functools import lru_cache

import pandas as pd


REPO = pathlib.Path("/Users/vadim/smc-lib/projects/ob-vc/data-channels")


@lru_cache(maxsize=None)
def load_funding(asset: str) -> pd.DataFrame:
    """asset = 'BTC' or 'ETH' (or full SYMBOL like BTCUSDT)."""
    sym = asset if asset.endswith("USDT") else f"{asset}USDT"
    p = REPO / "funding" / f"{sym}_funding.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p).sort_values("funding_time_ms").reset_index(drop=True)
    return df


@lru_cache(maxsize=None)
def load_oi(asset: str) -> pd.DataFrame:
    sym = asset if asset.endswith("USDT") else f"{asset}USDT"
    p = REPO / "oi" / f"{sym}_oi_1h.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p).sort_values("ts_ms").reset_index(drop=True)


@lru_cache(maxsize=None)
def load_dvol(asset: str) -> pd.DataFrame:
    """asset = 'BTC' or 'ETH'."""
    cur = asset.replace("USDT", "")
    p = REPO / "options" / f"{cur}_dvol_1h.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p).sort_values("ts_ms").reset_index(drop=True)


@lru_cache(maxsize=None)
def load_cross(name: str) -> pd.DataFrame:
    """name = ETHBTC | DXY | US10Y | SPX | GOLD"""
    p = REPO / "cross_asset" / f"{name}_1d.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p).sort_values("ts_ms").reset_index(drop=True)


@lru_cache(maxsize=None)
def load_macro() -> pd.DataFrame:
    p = REPO / "macro" / "macro_calendar.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p).sort_values("event_ms").reset_index(drop=True)


CROSS_NAMES = ["ETHBTC", "DXY", "US10Y", "SPX", "GOLD"]


def all_channels_summary():
    """Diagnostic: print coverage for all channels."""
    print("─" * 60)
    print("All channels summary")
    print("─" * 60)
    for asset in ("BTC", "ETH"):
        f = load_funding(asset)
        o = load_oi(asset)
        d = load_dvol(asset)
        print(f"{asset}:")
        print(f"  funding: {len(f):>5,} rows  ({_first_last(f, 'funding_time_ms')})")
        print(f"  OI:      {len(o):>5,} rows  ({_first_last(o, 'ts_ms')})")
        print(f"  DVOL:    {len(d):>5,} rows  ({_first_last(d, 'ts_ms')})")
    for n in CROSS_NAMES:
        c = load_cross(n)
        print(f"  cross/{n}: {len(c):>5,} rows  ({_first_last(c, 'ts_ms')})")
    m = load_macro()
    print(f"  macro events: {len(m):>5,}  ({_first_last(m, 'event_ms')})")


def _first_last(df, col):
    if df.empty:
        return "empty"
    import datetime as dt
    f = dt.datetime.fromtimestamp(df[col].iloc[0]/1000, tz=dt.timezone.utc).date()
    l = dt.datetime.fromtimestamp(df[col].iloc[-1]/1000, tz=dt.timezone.utc).date()
    return f"{f} -> {l}"


if __name__ == "__main__":
    all_channels_summary()
