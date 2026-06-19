"""Preview: align all available v1.5 channels with one ob_vc 2h event.

Example: BTC T1a setup 2026-06-05 23:00 МСК (= 20:00 UTC) — известный
канон-пример из памяти.

Shows snapshot of each channel at born_ms (= cur_close = 21:00 UTC + 4h fract delay).
For each channel: value at T (born), value at T-6h, T-1d, T-3d, T-1w — это
quasi-sequence для понимания, как «жил» рынок в окрестности setup.
"""
from __future__ import annotations
import pathlib
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd


CHANNELS = pathlib.Path(__file__).resolve().parent
MSK = timezone(timedelta(hours=3))


# T1a example: 2026-06-05 23:00 МСК LONG ob_vc, born ~01:00 МСК 06-06
EVENT_T = int(datetime(2026, 6, 6, 1, 0, tzinfo=MSK).timestamp() * 1000)
EVENT_LABEL = "BTC T1a LONG · born 2026-06-06 01:00 МСК (= 22:00 UTC)"


def load(p: pathlib.Path) -> pd.DataFrame:
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def snapshot(df: pd.DataFrame, t_col: str, value_cols: list[str], target_ms: int) -> dict:
    """Return value(s) at last record <= target_ms."""
    if df.empty:
        return {c: None for c in value_cols}
    sub = df[df[t_col] <= target_ms]
    if sub.empty:
        return {c: None for c in value_cols}
    last = sub.iloc[-1]
    return {c: float(last[c]) if pd.notna(last[c]) else None for c in value_cols}


def quasi_seq(df: pd.DataFrame, t_col: str, value_cols: list[str], born_ms: int) -> pd.DataFrame:
    """Snapshot at T, T-6h, T-1d, T-3d, T-1w."""
    offsets = [
        ("T",     0),
        ("T-6h",  6*3600*1000),
        ("T-1d",  24*3600*1000),
        ("T-3d",  3*24*3600*1000),
        ("T-1w",  7*24*3600*1000),
    ]
    out = []
    for lbl, off in offsets:
        snap = snapshot(df, t_col, value_cols, born_ms - off)
        out.append({"t": lbl, **snap})
    return pd.DataFrame(out)


def main():
    print("=" * 72)
    print(f"Alignment preview: {EVENT_LABEL}")
    print(f"  born_ms = {EVENT_T}  ({datetime.fromtimestamp(EVENT_T/1000, tz=timezone.utc).isoformat()})")
    print("=" * 72)

    # 1. Funding
    print("\n── FUNDING RATE (Binance perp, BTC) ──")
    f = load(CHANNELS / "funding" / "BTCUSDT_funding.parquet")
    qs = quasi_seq(f, "funding_time_ms", ["funding_rate"], EVENT_T)
    qs["funding_rate_bp"] = qs["funding_rate"] * 1e4
    print(qs[["t", "funding_rate_bp"]].to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    # Trend
    last_30d = f[(f.funding_time_ms <= EVENT_T) & (f.funding_time_ms >= EVENT_T - 30*86400*1000)]
    if not last_30d.empty:
        avg30 = last_30d.funding_rate.mean() * 1e4
        print(f"  30d avg: {avg30:+.2f} bp")

    # 2. OI (Bybit perp)
    print("\n── OPEN INTEREST (Bybit perp, BTC, contracts) ──")
    oi = load(CHANNELS / "oi" / "BTCUSDT_oi_1h.parquet")
    if oi.empty:
        print("  (not yet fetched / unavailable for this date)")
    else:
        qs = quasi_seq(oi, "ts_ms", ["open_interest_coin"], EVENT_T)
        qs["oi_btc"] = qs["open_interest_coin"]
        print(qs[["t", "oi_btc"]].to_string(index=False, float_format=lambda x: f"{x:,.0f}"))
        # 30-day stats
        last_30d = oi[(oi.ts_ms <= EVENT_T) & (oi.ts_ms >= EVENT_T - 30*86400*1000)]
        if not last_30d.empty:
            print(f"  30d avg: {last_30d.open_interest_coin.mean():,.0f}  min: {last_30d.open_interest_coin.min():,.0f}  max: {last_30d.open_interest_coin.max():,.0f}")

    # 2b. Options DVOL (Deribit BTC implied volatility index)
    print("\n── OPTIONS IV (Deribit DVOL, BTC, %) ──")
    dvol = load(CHANNELS / "options" / "BTC_dvol_1h.parquet")
    if dvol.empty:
        print("  (not yet fetched)")
    else:
        qs = quasi_seq(dvol, "ts_ms", ["close"], EVENT_T)
        qs["dvol_pct"] = qs["close"]
        print(qs[["t", "dvol_pct"]].to_string(index=False, float_format=lambda x: f"{x:.1f}"))
        last_30d = dvol[(dvol.ts_ms <= EVENT_T) & (dvol.ts_ms >= EVENT_T - 30*86400*1000)]
        if not last_30d.empty:
            avg30 = last_30d.close.mean()
            now = qs[qs.t == "T"]["dvol_pct"].iloc[0]
            if now is not None:
                z = (now - avg30) / last_30d.close.std() if last_30d.close.std() else 0
                print(f"  30d avg: {avg30:.1f}%  z-score now: {z:+.2f}")

    # 3. Cross-asset
    print("\n── CROSS-ASSET ──")
    for name in ("ETHBTC", "DXY", "US10Y", "SPX", "GOLD"):
        p = CHANNELS / "cross_asset" / f"{name}_1d.parquet"
        df = load(p)
        if df.empty:
            print(f"  {name}: missing")
            continue
        qs = quasi_seq(df, "ts_ms", ["close"], EVENT_T)
        line = "  " + name.ljust(8) + " "
        for _, row in qs.iterrows():
            v = row.close
            if v is None:
                line += f" {row.t}=NaN   "
            else:
                line += f" {row.t}={v:>9.2f}  "
        print(line)

    # 4. Macro
    print("\n── MACRO CALENDAR ──")
    mc = load(CHANNELS / "macro" / "macro_calendar.parquet")
    # last event before born + next event after
    prev = mc[mc.event_ms <= EVENT_T].tail(3)
    nxt  = mc[mc.event_ms >  EVENT_T].head(3)
    def fmt(r):
        dt = datetime.fromtimestamp(r.event_ms/1000, tz=timezone.utc)
        hours_diff = (r.event_ms - EVENT_T) / 1000 / 3600
        return f"  {dt.strftime('%Y-%m-%d %H:%M UTC')}  {r.event_type:<5}  ({hours_diff:+.1f}h from event)"
    print("  Most recent past events:")
    for _, r in prev.iterrows():
        print(fmt(r))
    print("  Next upcoming events:")
    for _, r in nxt.iterrows():
        print(fmt(r))

    print("\n" + "=" * 72)
    print("Preview done")
    print("=" * 72)


if __name__ == "__main__":
    main()
