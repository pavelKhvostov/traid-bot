"""B8C1 — Reverse Force Divergence (∪3).

Power Zone sub-condition.
Использует pre-computed force values: buyer_tf / seller_tf на 9 TFs (1h, 2h, 4h, 6h, 8h, 12h, D, 2D, 3D).
net = Σ(buyer - seller) across TFs; net_w2 = net(i) + net(i-1).

Conditions (OR):
    c9a: FL pivot ∧ net ≤ -1000      (selling exhaustion)
    c9b: FH pivot ∧ net ≥ +500       (buyer exhaustion — asymmetric threshold)
    c9c: FL pivot ∧ net_w2 ≤ -2000   (strong 2-bar seller bias)

Causal: ✅ (forces past-only; net_w2 — текущий + предыдущий бар).
Per memory [[feedback-expert-force-opinion-trigger]].
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from _lib import load_12h, load_baseline, match_pivots, report, save_fires

FORCE_PARQUET = pathlib.Path.home() / "Desktop/force_all_bars_per_tf.parquet"
TF_LIST = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "2d", "3d"]


def main():
    bars = load_12h()
    fdf = pd.read_parquet(FORCE_PARQUET)
    fdf["buyer_total"] = sum(fdf[f"buyer_{tf}"] for tf in TF_LIST)
    fdf["seller_total"] = sum(fdf[f"seller_{tf}"] for tf in TF_LIST)
    fdf["net"] = fdf["buyer_total"] - fdf["seller_total"]
    fdf["net_w2"] = fdf["net"].rolling(2).sum()
    fmap = fdf.set_index("open_ts_ms")[["net", "net_w2"]].to_dict("index")

    t12 = bars["t"]; n12 = bars["n"]
    fires = set()
    for i in range(n12):
        ts = int(t12[i])
        if ts not in fmap: continue
        net = fmap[ts]["net"]
        netw2 = fmap[ts]["net_w2"]
        if np.isnan(net): continue
        # c9b: FH (short zone) — buyer exhaustion at top
        if net >= 500:
            fires.add((i, "short"))
        # c9a + c9c: FL (long zone) — seller exhaustion at bottom
        if net <= -1000:
            fires.add((i, "long"))
        if not np.isnan(netw2) and netw2 <= -2000:
            fires.add((i, "long"))

    pmap = match_pivots(bars, load_baseline())
    report("B8C1", "Reverse Force Divergence (∪3)", fires, pmap)
    save_fires("B8C1", fires, bars)


if __name__ == "__main__":
    main()
