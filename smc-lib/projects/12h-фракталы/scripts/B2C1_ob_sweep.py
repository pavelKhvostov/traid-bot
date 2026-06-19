"""B2C1 — FIRST 50%-sweep block_orders (multi-TF).

OB-семейство, sub-условие #1. Использует detect_block_orders с (N₁, N₂) ≠ (1,1).
Multi-TF: 12h ∪ D ∪ 2D ∪ 3D ∪ W.
50%-sweep = wick ≥ midpoint zone + close back OUTSIDE.
FIRST = первая 12h-свеча с sweep после создания зоны.
Causal: ✅
"""
from __future__ import annotations
import numpy as np
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.block_orders.code import detect_block_orders
from _lib import load_12h, load_htf_bars, TF_HTF, load_baseline, match_pivots, report, save_fires


# Сканер block_orders: окно ≤ MAX_LEN баров (initial + counter run).
MAX_LEN = 8


def scan_block_orders(tfs=("12h", "D", "2D", "3D", "W")) -> list[dict]:
    zones = []
    for tf in tfs:
        bars = load_htf_bars(tf)
        cans = [Candle(open=b[1], high=b[2], low=b[3], close=b[4], open_time=b[0]) for b in bars]
        tfms = TF_HTF[tf]
        for i in range(len(cans) - 2):
            for win in range(3, min(MAX_LEN + 1, len(cans) - i)):
                bo = detect_block_orders(cans[i : i + win])
                if bo is None: continue
                last_idx = i + win - 1  # counter-stop candle
                zones.append({
                    "tf": tf,
                    "direction": bo.direction,
                    "zlo": bo.zone[0],
                    "zhi": bo.zone[1],
                    "ready_ms": cans[last_idx].open_time + tfms,
                })
                break  # take only one (smallest valid) per i
    return zones


def main():
    bars = load_12h()
    zones = scan_block_orders()
    n12 = bars["n"]
    t12, h12, l12, c12 = bars["t"], bars["h"], bars["l"], bars["c"]
    fires = set()
    for z in zones:
        sp = int(np.searchsorted(t12, z["ready_ms"], side="left"))
        if sp >= n12: continue
        zlo, zhi = z["zlo"], z["zhi"]
        mid = (zlo + zhi) / 2
        for k in range(sp, n12):
            if z["direction"] == "short":
                if h12[k] >= mid and c12[k] < zlo:
                    # First 50% sweep + close OUTSIDE far edge → fire
                    fires.add((k, "short"))
                    break
            else:
                if l12[k] <= mid and c12[k] > zhi:
                    fires.add((k, "long"))
                    break

    # Convert OB block direction to zone-direction matching A4-baseline
    # FH pivot expects "short" zones, FL pivot expects "long" zones — уже совпадает.
    pmap = match_pivots(bars, load_baseline())
    report("B2C1", "OB FIRST 50%-sweep (multi-TF)", fires, pmap)
    save_fires("B2C1", fires, bars)


if __name__ == "__main__":
    main()
