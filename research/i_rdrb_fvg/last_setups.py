"""Последние N i-RDRB+FVG сетапов на BTC 1h — координаты для отрисовки на TV.

Печатает по каждому: времена C1/C5, block, FVG-зона, entry/SL/TP(RR2), направление.
Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/i_rdrb_fvg/last_setups.py [N] [TF] [SYMBOL]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_i_rdrb_fvg import detect_all_i_rdrb_fvg  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
TF = sys.argv[2] if len(sys.argv) > 2 else "1h"
SYM = sys.argv[3] if len(sys.argv) > 3 else "BTCUSDT"
RR = 2.0
FREQ = {"1h": "1h", "2h": "2h", "4h": "4h", "12h": "12h"}[TF]


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def main():
    tf_sec = {"1h": 3600, "2h": 7200, "4h": 14400, "12h": 43200}[TF]
    right_bars = 18
    df = rs(load_1m(SYM), FREQ)
    sigs = detect_all_i_rdrb_fvg(df)
    print(f"{SYM} {TF}: всего сетапов {len(sigs)}, последние {N} (data до {df.index[-1]}):\n")
    for s in sigs[-N:]:
        tp = s.entry + RR * s.risk if s.direction == "LONG" else s.entry - RR * s.risk
        c1u = int(s.c1_time.timestamp())
        c3u = int(s.c3_time.timestamp())
        c5u = int(s.c5_time.timestamp())
        rightu = c5u + right_bars * tf_sec
        print(f"--- {s.direction}  C1={s.c1_time:%Y-%m-%d %H:%M}  C5={s.c5_time:%Y-%m-%d %H:%M}")
        print(f"    block   = [{s.block[0]:.1f} .. {s.block[1]:.1f}]")
        print(f"    fvg     = [{s.fvg_zone[0]:.1f} .. {s.fvg_zone[1]:.1f}]")
        print(f"    pattern = [{s.pattern_low:.1f} .. {s.pattern_high:.1f}]")
        print(f"    ENTRY={s.entry:.1f}  SL={s.sl:.1f}  TP(RR2)={tp:.1f}  risk={s.risk:.1f}")
        print(f"    UNIX c1={c1u} c3={c3u} c5={c5u} right={rightu}")
        print(f"    DRAW entry={s.entry:.1f} sl={s.sl:.1f} tp={tp:.1f} "
              f"blk_b={s.block[0]:.1f} blk_t={s.block[1]:.1f} "
              f"fvg_b={s.fvg_zone[0]:.1f} fvg_t={s.fvg_zone[1]:.1f}")


if __name__ == "__main__":
    main()
