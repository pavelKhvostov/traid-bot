"""HYBRID TBM:
  extreme=prev (16 типов): NEW rule (Entry = cur.low/high, SL = prev.low/high)
  extreme=cur  (8 типов):  OLD rule (Entry = 0.8/0.2 deep FVG, SL = drop_lo/hi)

Это даёт честную оценку — без микро-R artifacts на extreme=cur.
"""
import sys, pathlib
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent))

OLD = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/tbm_2h_24types.parquet")
NEW = pd.read_parquet(pathlib.Path(__file__).parent.parent / "data/tbm_2h_24_new_entry.parquet")

T_ORDER = [
    "T1a","T1b","T2","T3a","T3b","T4","T5a","T5b","T6","T7a","T7b","T8",
    "T9a","T9b","T10","T11a","T11b","T12","T13a","T13b","T14","T15a","T15b","T16",
]
PREV_TYPES = {"T1a","T1b","T3a","T3b","T5a","T5b","T7a","T7b",
              "T9a","T9b","T11a","T11b","T13a","T13b","T15a","T15b"}

print(f"{'T':<6} {'rule':<5} {'N':>5} {'WR%':>6} {'EV':>9} {'Σ R':>7}")
print("-" * 50)
total_hybrid = 0
hybrid_stats = {}
for t in T_ORDER:
    src = NEW if t in PREV_TYPES else OLD
    rule_name = "NEW" if t in PREV_TYPES else "OLD"
    g = src[src.t_id == t]
    n = len(g)
    n_t = g.touched.sum()
    tg = g[g.touched]
    wins = (tg.outcome == "win").sum()
    losses = (tg.outcome == "loss").sum()
    wr = wins / n_t * 100 if n_t else 0
    ev = (2 * wr / 100) - 1
    total = wins - losses
    total_hybrid += total
    hybrid_stats[t] = (rule_name, n, wr, ev, total)
    print(f"{t:<6} {rule_name:<5} {n:>5} {wr:>5.1f}% {ev:>+8.3f}R {total:>+6}R")

print(f"\nΣ Hybrid: {total_hybrid:+}R за 6y")

# Drop list
print(f"\nNegative EV (drop):")
for t, (rule, n, wr, ev, total) in hybrid_stats.items():
    if total < 0:
        print(f"  {t}: {total:+}R")

# After drop
positives = sum(v[4] for v in hybrid_stats.values() if v[4] >= 0)
print(f"\nΣ без negatives: {positives:+}R за 6y")
