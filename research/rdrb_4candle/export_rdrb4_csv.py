"""Export all RDRB-4 structures to CSV (full history, BTCUSDT, 1h + 2h)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scan_rdrb4 import scan

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "rdrb4_all.csv"


def main():
    rows = []
    for tf in ["1h", "2h"]:
        df = pd.read_csv(ROOT / "data" / f"BTCUSDT_{tf}.csv", parse_dates=["open_time"])
        rows.extend(scan(df, tf))

    out = pd.DataFrame(rows)
    out["rdrb_formed_utc3"] = (
        out["c4_time"] + pd.to_timedelta(out["tf"].map({"1h": 1, "2h": 2}), unit="h")
    ).dt.tz_convert("Etc/GMT-3")
    out["rdrb_formed_utc3"] = out["rdrb_formed_utc3"].dt.tz_localize(None)
    out = out[["tf", "dir", "rdrb_formed_utc3", "zone_low", "zone_high"]]
    out = out.sort_values("rdrb_formed_utc3").reset_index(drop=True)
    out.to_csv(OUT, index=False)

    print(f"Saved {len(out)} rows -> {OUT}")
    print(f"\nBy TF / dir:")
    print(out.groupby(["tf", "dir"]).size())
    print(f"\nDate range: {out['rdrb_formed_utc3'].min()} -> {out['rdrb_formed_utc3'].max()}")


if __name__ == "__main__":
    main()
