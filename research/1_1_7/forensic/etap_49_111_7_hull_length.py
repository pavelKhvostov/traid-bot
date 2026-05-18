"""Этап 49 (1.1.7-edition): Hull length sensitivity finer grid.

Phase D в etap_47 показала L160 хорошо на 4h и 1h. Здесь — расширенный
sweep L40..L240 для каждого TF, в т.ч. отдельно LONG vs SHORT.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

_ELEMENTS = _ROOT / "research" / "elements_study"
if str(_ELEMENTS) not in _sys.path:
    _sys.path.insert(0, str(_ELEMENTS))

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from etap_35_strategy_111_forensic import hull_ma

SYMBOL = "BTCUSDT"
HULL_LENGTHS = [40, 60, 80, 100, 120, 140, 160, 180, 200, 240]
TFS = ["1h", "4h", "12h", "1d"]
CSV = "research/1_1_7/forensic/output/etap_47_111_7_trades_features.csv"


def parse_utc3_to_utc(s):
    if pd.isna(s) or s == "":
        return pd.NaT
    return pd.Timestamp(s, tz="UTC")  # signal_time уже в UTC из etap_47


def main():
    df = pd.read_csv(CSV)
    df["ts"] = pd.to_datetime(df["signal_time"], utc=True)
    base_wr = (df["outcome"] == "win").sum() / len(df) * 100
    print(f"[INFO] baseline n={len(df)} WR={base_wr:.1f}% total={df['R'].sum():+.1f}R\n")

    # Preload data
    tf_data = {
        "1d": load_df(SYMBOL, "1d"),
        "4h": load_df(SYMBOL, "4h"),
        "1h": load_df(SYMBOL, "1h"),
    }
    tf_data["12h"] = compose_from_base(tf_data["1h"], "12h")

    # Compute hull labels at signal_time для каждого (tf, length) комбо
    print("[INFO] computing hull labels per trade ...")
    for tf in TFS:
        d = tf_data[tf]
        for L in HULL_LENGTHS:
            h = hull_ma(d["close"], L)
            h2 = h.shift(2)
            close = d["close"]
            # Trend label series.
            labels = pd.Series(
                np.where(close > h2, "up", np.where(close < h2, "down", "na")),
                index=d.index,
            )

            def lookup(ts):
                idx = labels.index.searchsorted(ts, side="right") - 1
                if idx < 1:
                    return "na"
                v = labels.iloc[idx - 1]
                return v if pd.notna(v) else "na"

            df[f"hull_{tf}_L{L}"] = df["ts"].apply(lookup)

    print("[INFO] sweep results (aligned only, n>=20):\n")
    for direction in ["ALL", "LONG", "SHORT"]:
        sub = df if direction == "ALL" else df[df["direction"] == direction]
        n_sub = len(sub)
        wr_sub = (sub["outcome"] == "win").sum() / n_sub * 100
        total_sub = sub["R"].sum()
        print(f"\n=== {direction}  baseline n={n_sub} WR={wr_sub:.1f}% total={total_sub:+.1f}R ===")
        print(f"{'TF':<5} {'L':<5} {'n':<5} {'WR':<8} {'d_pp':<8} {'total':<10} {'avg':<8}")
        results = []
        for tf in TFS:
            for L in HULL_LENGTHS:
                col = f"hull_{tf}_L{L}"
                # aligned: для LONG = up, для SHORT = down
                if direction == "ALL":
                    # use direction-aware alignment
                    cond = (
                        ((sub["direction"] == "LONG") & (sub[col] == "up"))
                        | ((sub["direction"] == "SHORT") & (sub[col] == "down"))
                    )
                elif direction == "LONG":
                    cond = sub[col] == "up"
                else:
                    cond = sub[col] == "down"
                aligned = sub[cond]
                n = len(aligned)
                if n < 15:
                    continue
                wr = (aligned["outcome"] == "win").sum() / n * 100
                total = aligned["R"].sum()
                avg = total / n
                results.append((tf, L, n, wr, wr - wr_sub, total, avg))

        # Печать sorted by d_pp
        results.sort(key=lambda x: x[4], reverse=True)
        for tf, L, n, wr, d, total, avg in results[:10]:
            flag = " ***" if d >= 5 else (" !" if d <= -5 else "")
            print(f"{tf:<5} {L:<5} {n:<5} {wr:<8.1f} {d:+7.1f} {total:+9.1f} {avg:+7.3f}{flag}")


if __name__ == "__main__":
    main()
