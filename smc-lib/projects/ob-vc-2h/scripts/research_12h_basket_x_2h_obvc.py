"""Confluence: 12h-fractal-new basket × 2h ob_vc setups.

Question: when 12h-basket fires (predicting fractal at candle i), do 2h ob_vc
setups also form WITHIN the i-th 12h candle window?

Window: [bar_i.open_time, bar_i.open_time + 12h)
Direction match: basket.direction == ob_vc.direction

Outputs:
  - % basket events with co-located 2h ob_vc
  - WR of ob_vc setups inside basket window vs outside
"""
import pathlib, time
import numpy as np
import pandas as pd

t0 = time.time()
BASKET = pd.read_parquet("/Users/vadim/Desktop/12h-fractal-new-out/basket_only_with_score.parquet")
OBVC = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/bulkowski_features.parquet")

print(f"Basket events: {len(BASKET)}  (LONG {len(BASKET[BASKET.direction=='long'])} / SHORT {len(BASKET[BASKET.direction=='short'])})")
print(f"2h ob_vc setups (post A1): {len(OBVC)}")

# Per basket: window = [ts_i, ts_i + 12h)
TF_12H_MS = 12 * 3600 * 1000

# Sort obvc by born_ms for fast bisect
OBVC_sorted = OBVC.sort_values("born_ms").reset_index(drop=True)
obvc_born = OBVC_sorted.born_ms.values
obvc_dir = OBVC_sorted.direction.values
obvc_R = OBVC_sorted.R.values
obvc_touched = OBVC_sorted.touched.values
obvc_B1 = OBVC_sorted.B1_aligned.values

# Tag ob_vc with basket flag
obvc_in_basket = np.zeros(len(OBVC_sorted), dtype=bool)
obvc_basket_confirmed = np.zeros(len(OBVC_sorted), dtype=bool)

basket_with_obvc = 0
basket_with_obvc_per_dir = {"long": 0, "short": 0}
basket_confirmed_with_obvc = 0

for _, b in BASKET.iterrows():
    win_lo = int(b.ts_ms)
    win_hi = win_lo + TF_12H_MS
    direction = b.direction
    i_lo = np.searchsorted(obvc_born, win_lo, side="left")
    i_hi = np.searchsorted(obvc_born, win_hi, side="left")
    if i_hi <= i_lo: continue
    same_dir_mask = obvc_dir[i_lo:i_hi] == direction
    n_same = same_dir_mask.sum()
    if n_same > 0:
        basket_with_obvc += 1
        basket_with_obvc_per_dir[direction] += 1
        if b.confirmed:
            basket_confirmed_with_obvc += 1
        for offset in np.where(same_dir_mask)[0]:
            obvc_in_basket[i_lo + offset] = True
            if b.confirmed:
                obvc_basket_confirmed[i_lo + offset] = True

print(f"\n{'='*80}")
print(f"BASKET → 2h ob_vc COVERAGE")
print(f"{'='*80}")
print(f"Basket events with ≥1 same-dir 2h ob_vc in [ts_i, ts_i+12h):")
print(f"  Total:     {basket_with_obvc:>4} / {len(BASKET):>4}  ({basket_with_obvc/len(BASKET)*100:.1f}%)")
print(f"  LONG:      {basket_with_obvc_per_dir['long']:>4} / {(BASKET.direction=='long').sum():>4}  ({basket_with_obvc_per_dir['long']/(BASKET.direction=='long').sum()*100:.1f}%)")
print(f"  SHORT:     {basket_with_obvc_per_dir['short']:>4} / {(BASKET.direction=='short').sum():>4}  ({basket_with_obvc_per_dir['short']/(BASKET.direction=='short').sum()*100:.1f}%)")
print(f"  Confirmed: {basket_confirmed_with_obvc:>4} / {BASKET.confirmed.sum():>4}  ({basket_confirmed_with_obvc/BASKET.confirmed.sum()*100:.1f}%)")

print(f"\n{'='*80}")
print(f"2h ob_vc INSIDE vs OUTSIDE basket-i windows")
print(f"{'='*80}")

def wr_stats(mask, label):
    sub = OBVC_sorted[mask]
    nt = sub.touched.sum()
    w = (sub.R==1).sum(); l = (sub.R==-1).sum()
    wr = w/nt*100 if nt else 0
    ev = (2*wr/100) - 1
    print(f"{label:<42} N={len(sub):>5} touch={nt:>5} WR={wr:>5.1f}% EV={ev:>+6.3f}R Σ={w-l:>+6}R")
    return wr, w-l

wr_stats(np.ones(len(OBVC_sorted), dtype=bool), "ALL post-A1 (baseline)")
wr_stats(obvc_in_basket, "INSIDE basket-i window (any basket)")
wr_stats(obvc_basket_confirmed, "INSIDE basket-i CONFIRMED window")
wr_stats(~obvc_in_basket, "OUTSIDE basket-i window")
print()
wr_stats(obvc_B1, "B1 baseline (Tier 1)")
wr_stats(obvc_B1 & obvc_in_basket, "B1 + INSIDE basket-i (any)")
wr_stats(obvc_B1 & obvc_basket_confirmed, "B1 + INSIDE basket-i CONFIRMED")
wr_stats(obvc_in_basket & ~obvc_B1, "INSIDE basket-i but NOT B1")

print(f"\nElapsed: {time.time()-t0:.1f}s")
