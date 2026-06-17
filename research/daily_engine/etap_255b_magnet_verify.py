"""etap_255b - CLEAN, proximity-controlled test of the weekly-sweep MAGNET claim.

Claim under test (the one thing from etap_255 worth shipping):
  "A weekly liquidity sweep makes the swept prior-week level (PWH/PWL) a MAGNET
   that gets revisited (touched again) more than chance."

Why etap_255's fill% column is NOT evidence: it compares sweep shapes (ref =
ADJACENT just-swept level, ~0.3 week-range from close) against continuation
shapes (ref = FAR opposite level, ~1.1 week-range from close). The fill% gap is
geometric (distance-to-level), not behavioral. See verdict report.

Clean design (apples-to-apples, controls for proximity):
  - Look ONLY at the PWH side (then symmetric PWL side).
  - For EVERY completed ISO week, measure d_high = (PWH - close)/week_range,
    i.e. how far below PWH the week closed, in week-range units. (For the PWL
    side, d_low = (close - PWL)/week_range.)
  - A week "swept" PWH if its HIGH exceeded PWH at some point (regardless of
    where it closed). Non-swept = high never reached PWH.
  - Outcome: did price TOUCH PWH within the next 1 (and 2) weeks? (high >= PWH).
  - Control for proximity: bucket weeks into distance bands of d_high, and
    within each band compare P(touch) for SWEPT vs NON-SWEPT weeks. If swept
    weeks revisit MORE than non-swept weeks AT THE SAME DISTANCE, the magnet is
    real. If revisit rate is explained by distance alone (swept ~= non-swept in
    band), KILL the magnet claim.

  Note: a week that swept PWH but closed back below it is the interesting case;
  but we also include weeks that swept and closed above (those trivially already
  touched - excluded from the "future touch" test by requiring close < PWH so the
  level is genuinely above the close and revisit is a real future event). We
  report both the strict same-band comparison and the pooled logistic-style view.

Run:
  set PYTHONIOENCODING=utf-8
  venv/Scripts/python.exe research/daily_engine/etap_255b_magnet_verify.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
while not (ROOT / "data_manager.py").exists():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from data_manager import load_df  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
# distance bands in week-range units: how far the close sits BELOW PWH (PWH side)
# or ABOVE PWL (PWL side). Only weeks whose close is on the inside of the level
# (level not yet permanently broken at close) qualify.
BANDS = [(0.0, 0.15), (0.15, 0.30), (0.30, 0.50), (0.50, 0.80), (0.80, 1.20)]


def weekly(df1d: pd.DataFrame) -> pd.DataFrame:
    if df1d.index.tz is None:
        df1d = df1d.tz_localize("UTC")
    wk = df1d.resample("W-MON", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return wk


def build(side: str, wk: pd.DataFrame) -> pd.DataFrame:
    """side='high' -> PWH magnet test; side='low' -> PWL magnet test.
    One row per completed week where the level sits on the far side of close
    (genuine future-touch is possible). Strictly-forward outcome."""
    H = wk["high"].values
    L = wk["low"].values
    C = wk["close"].values
    idx = wk.index
    rows = []
    n = len(wk)
    for i in range(1, n):
        pwh = H[i - 1]
        pwl = L[i - 1]
        rng = H[i] - L[i]
        if rng <= 0:
            continue
        if side == "high":
            level = pwh
            close = C[i]
            if not (close < level):          # need level ABOVE close (future touch real)
                continue
            dist = (level - close) / rng     # week-range units, >0
            swept = H[i] > level             # this week's high pierced PWH
            # forward touch: any future week high >= level
            t1 = bool((H[i + 1:i + 2] >= level).any())
            t2 = bool((H[i + 1:i + 3] >= level).any())
        else:
            level = pwl
            close = C[i]
            if not (close > level):
                continue
            dist = (close - level) / rng
            swept = L[i] < level
            t1 = bool((L[i + 1:i + 2] <= level).any())
            t2 = bool((L[i + 1:i + 3] <= level).any())
        rows.append(dict(date=idx[i], side=side, dist=dist, swept=bool(swept),
                         touch1=t1, touch2=t2, year=idx[i].year))
    return pd.DataFrame(rows)


def band_of(d: float) -> str | None:
    for lo, hi in BANDS:
        if lo <= d < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return None


def report_symbol(sym: str) -> dict:
    d = load_df(sym, "1d")
    if d.empty:
        print(f"  {sym}: no data")
        return {}
    wk = weekly(d)
    both = pd.concat([build("high", wk), build("low", wk)], ignore_index=True)
    both["band"] = both["dist"].map(band_of)
    both = both.dropna(subset=["band"])
    print("=" * 78)
    print(f"  {sym}   (weeks where level sits on far side of close, both PWH & PWL)")
    print("=" * 78)

    # ---- proximity-controlled: within each distance band, swept vs non-swept ----
    print(f"  PROXIMITY-CONTROLLED  touch within 1w  /  2w   (n)")
    print(f"  {'band(d/wkR)':<14}{'SWEPT t1':>10}{'t2':>7}{'(n)':>6}"
          f"{'NOSWEEP t1':>12}{'t2':>7}{'(n)':>6}{'  Δt1':>8}")
    deltas1 = []
    for lo, hi in BANDS:
        b = f"{lo:.2f}-{hi:.2f}"
        sub = both[both["band"] == b]
        sw = sub[sub["swept"]]
        ns = sub[~sub["swept"]]
        if len(sw) < 5 or len(ns) < 5:
            print(f"  {b:<14}  (insufficient: swept={len(sw)} nosweep={len(ns)})")
            continue
        s1, s2 = sw["touch1"].mean(), sw["touch2"].mean()
        n1, n2 = ns["touch1"].mean(), ns["touch2"].mean()
        d1 = s1 - n1
        deltas1.append((d1, len(sw)))
        print(f"  {b:<14}{s1:>9.0%}{s2:>7.0%}{len(sw):>6}"
              f"{n1:>11.0%}{n2:>7.0%}{len(ns):>6}{d1:>+8.0%}")
    if deltas1:
        wsum = sum(d * n for d, n in deltas1)
        wn = sum(n for _, n in deltas1)
        wmean = wsum / wn if wn else float("nan")
        print(f"  --> n-weighted mean Δ(touch1, swept-minus-nosweep) = {wmean:+.1%}")

    # ---- per-year stability of the swept revisit rate (touch1) ----
    sw_all = both[both["swept"]]
    print(f"\n  PER-YEAR  swept revisit rate (touch within 1w):")
    yr = sw_all.groupby("year")["touch1"].agg(["mean", "size"])
    line = "   ".join(f"{int(y)}:{r['mean']:.0%}(n{int(r['size'])})"
                      for y, r in yr.iterrows())
    print(f"    {line}")
    return {"deltas1": deltas1}


def main():
    print("\nCLEAN MAGNET TEST: does a weekly sweep revisit the swept level MORE")
    print("than a non-swept week that closed the SAME distance from that level?\n")
    agg = {}
    for sym in SYMBOLS:
        agg[sym] = report_symbol(sym)
        print()
    print("=" * 78)
    print("  CROSS-ASSET SUMMARY (n-weighted mean Δtouch1 swept-minus-nosweep)")
    print("=" * 78)
    for sym in SYMBOLS:
        ds = agg.get(sym, {}).get("deltas1", [])
        if ds:
            wsum = sum(d * n for d, n in ds)
            wn = sum(n for _, n in ds)
            print(f"  {sym}: {wsum / wn:+.1%}")
    print("\nKEEP magnet only if Δtouch1 is positive AND material (>~+8pp) across")
    print(">=2 symbols. Otherwise revisit rate = proximity, not sweep -> KILL.")


if __name__ == "__main__":
    main()
