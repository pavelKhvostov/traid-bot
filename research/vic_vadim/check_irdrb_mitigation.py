"""Митигация зоны интереса i-RDRB+FVG (BTC, 2023+, 3 ТФ).

Митигация = касание (touch):
  LONG:  low_1m ≤ zone_top    (zone_top = low(c2 FVG))
  SHORT: high_1m ≥ zone_bottom (zone_bottom = high(c2 FVG))

Сканируем БЕЗ окна — до конца данных. Выдаём:
- % митигированных setup'ов
- distribution времени до митигации (часы): median, p25, p75, p95, max
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb
from strategies.strategy_1_1_1 import detect_fvg

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2023-01-01", tz="UTC")
TFS = [("1h", "1h", 60), ("2h", "2h", 120), ("90m", "90min", 90)]


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def scan_tf(df_tf: pd.DataFrame, df_1m: pd.DataFrame, tf_min: int, label: str) -> dict:
    n = len(df_tf)
    highs = df_tf["high"].to_numpy()
    lows = df_tf["low"].to_numpy()
    closes = df_tf["close"].to_numpy()
    idx = df_tf.index
    df_1m_lo = df_1m["low"].to_numpy()
    df_1m_hi = df_1m["high"].to_numpy()
    df_1m_idx = df_1m.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_tf, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_tf, k + 2)
        if fvg is None or fvg.direction != i_dir: continue
        if i_dir == "LONG":
            zone_b = float(min(lows[k - 2], lows[k - 1], lows[k], lows[k + 1]))
            zone_t = float(lows[k + 2])
        else:
            zone_t = float(max(highs[k - 2], highs[k - 1], highs[k], highs[k + 1]))
            zone_b = float(highs[k + 2])
        if zone_t <= zone_b: continue

        start_time = idx[k + 2] + pd.Timedelta(minutes=tf_min)
        sp = int(df_1m_idx.searchsorted(start_time, side="left"))
        if sp >= len(df_1m_idx): continue
        if i_dir == "LONG":
            hits = np.where(df_1m_lo[sp:] <= zone_t)[0]
        else:
            hits = np.where(df_1m_hi[sp:] >= zone_b)[0]
        if hits.size == 0:
            rows.append({"dir": i_dir, "mitigated": False, "hours": np.nan})
        else:
            mit_time = df_1m_idx[sp + int(hits[0])]
            hours = (mit_time - start_time).total_seconds() / 3600
            rows.append({"dir": i_dir, "mitigated": True, "hours": hours})

    df = pd.DataFrame(rows)
    out = ROOT / "signals" / f"irdrb_mitigation_{label}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    total = len(df)
    mit = int(df["mitigated"].sum())
    pct = mit / total * 100 if total else 0
    hrs = df[df["mitigated"]]["hours"]
    s = {"tf": label, "total": total, "mit": mit, "pct": pct,
         "median": hrs.median(), "p25": hrs.quantile(.25), "p75": hrs.quantile(.75),
         "p95": hrs.quantile(.95), "max": hrs.max(), "mean": hrs.mean()}
    # по направлениям
    for d in ("LONG", "SHORT"):
        sub = df[df["dir"] == d]
        s[f"{d}_n"] = len(sub)
        s[f"{d}_mit"] = int(sub["mitigated"].sum())
        s[f"{d}_pct"] = s[f"{d}_mit"] / s[f"{d}_n"] * 100 if s[f"{d}_n"] else 0
        s[f"{d}_med"] = sub[sub["mitigated"]]["hours"].median()
    return s


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    print(f"  bars: {len(df_1m):,}  end: {df_1m.index.max()}", flush=True)

    summaries = []
    for label, freq, tf_min in TFS:
        df_tf = resample(df_1m, freq)
        s = scan_tf(df_tf, df_1m, tf_min, label)
        summaries.append(s)

    print(f"\n{'TF':>5} {'total':>5} {'mit':>4} {'mit%':>6}  "
          f"{'median':>7} {'p25':>6} {'p75':>6} {'p95':>7} {'max':>7}  "
          f"{'L_mit%':>6} {'S_mit%':>6}")
    for s in summaries:
        print(f"{s['tf']:>5} {s['total']:>5} {s['mit']:>4} {s['pct']:>5.1f}%  "
              f"{s['median']:>6.1f}h {s['p25']:>5.1f}h {s['p75']:>5.1f}h {s['p95']:>6.1f}h {s['max']:>6.1f}h  "
              f"{s['LONG_pct']:>5.1f}% {s['SHORT_pct']:>5.1f}%")


if __name__ == "__main__":
    main()
