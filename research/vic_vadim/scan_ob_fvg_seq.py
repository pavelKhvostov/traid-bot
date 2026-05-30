"""Скан сетапа на BTC с 2023-01-01:
   OB на ТФ X → FVG того же направления и ТФ образуется на cur, cur+1 или cur+2.
   Параллельно для X ∈ {1h, 2h, 90m}.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2023-01-01", tz="UTC")
TFS = [("1h", "1h"), ("2h", "2h"), ("90m", "90min")]


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def scan(df_tf: pd.DataFrame, label: str) -> list[dict]:
    rows = []
    n = len(df_tf)
    for k in range(1, n):
        ob = detect_ob_pair(df_tf, k)
        if ob is None:
            continue
        # FVG-c2 в индексах k, k+1, k+2 (т.е. сразу или в течение 2 свечей после cur)
        for j in (k, k + 1, k + 2):
            if j >= n:
                break
            fvg = detect_fvg(df_tf, j)
            if fvg is None or fvg.direction != ob.direction:
                continue
            rows.append({
                "tf": label,
                "ob_dir": ob.direction,
                "ob_prev_time": ob.prev_time,
                "ob_cur_time": ob.cur_time,
                "ob_bottom": ob.bottom,
                "ob_top": ob.top,
                "fvg_c0_time": fvg.c0_time,
                "fvg_c2_time": fvg.c2_time,
                "fvg_bottom": fvg.bottom,
                "fvg_top": fvg.top,
                "fvg_offset_bars": j - k,  # 0=на cur, 1=k+1, 2=k+2
            })
            break  # первый совпавший FVG в окне
    return rows


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    print(f"  bars: {len(df_1m):,}  {df_1m.index.min()} → {df_1m.index.max()}", flush=True)

    all_rows = []
    for label, freq in TFS:
        print(f"\n=== {label} ===", flush=True)
        df_tf = resample(df_1m, freq)
        print(f"  {label}-bars: {len(df_tf):,}", flush=True)
        rows = scan(df_tf, label)
        print(f"  setups: {len(rows)}", flush=True)
        if rows:
            df = pd.DataFrame(rows)
            longs = (df["ob_dir"] == "LONG").sum()
            shorts = (df["ob_dir"] == "SHORT").sum()
            print(f"    LONG: {longs}  SHORT: {shorts}", flush=True)
            for off in (0, 1, 2):
                cnt = (df["fvg_offset_bars"] == off).sum()
                print(f"    offset +{off}: {cnt}", flush=True)
            all_rows.extend(rows)

    out = pd.DataFrame(all_rows)
    out_path = ROOT / "signals" / "ob_fvg_seq_BTC_2023.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"\nsaved: {out_path} ({len(out)} rows)")


if __name__ == "__main__":
    main()
