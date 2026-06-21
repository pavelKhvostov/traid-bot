"""Graal v4 — triple combinations + train/test split + per-year stability.

Use cached features from graal_v3 CSV.
"""
from __future__ import annotations
import csv
import pathlib

IN = pathlib.Path.home() / "Desktop/i-rdrb-charts/graal_v3_features_1094.csv"
rows = []
with IN.open() as f:
    rd = csv.DictReader(f)
    for r in rd:
        for k in ("pos_5d", "pos_20d", "ema50", "ema200", "r_atr", "atr_p"):
            r[k] = float(r[k])
        for k in ("ema_d", "cascade", "mom_4h", "mom_12h", "hour", "weekday", "year"):
            r[k] = int(r[k])
        rows.append(r)
print(f"Loaded {len(rows)} setups from cache")


def stat(rs):
    w = sum(1 for r in rs if r["out"] == "win")
    l = sum(1 for r in rs if r["out"] == "loss")
    n = w + l
    wr = w / n * 100 if n else 0
    sr = w - l
    return n, wr, sr


def bk(name, rs):
    n, wr, sr = stat(rs)
    rtr = sr / n if n else 0
    print(f"  {name:<80} cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


# Define candidate predicates
def asym(feat, lo_l, hi_l, lo_s, hi_s):
    def pred(r, _feat=feat, _ll=lo_l, _hl=hi_l, _ls=lo_s, _hs=hi_s):
        v = r[_feat]
        if r["side"] == "long":
            return _ll <= v < _hl
        else:
            return _ls <= v < _hs
    return pred


candidates = []

# pos_5d asymmetric
for k in [0.10, 0.15, 0.20, 0.25, 0.30]:
    candidates.append((f"pos5d<{k}|>{1-k}", asym("pos_5d", 0, k, 1-k, 1.01)))
# pos_20d
for k in [0.10, 0.20, 0.30]:
    candidates.append((f"pos20d<{k}|>{1-k}", asym("pos_20d", 0, k, 1-k, 1.01)))

# r_atr bands
for lo, hi in [(0.55, 1.05), (0.7, 1.05), (0.85, 1.05), (0.55, 0.85)]:
    candidates.append((f"r_atr[{lo},{hi}]", lambda r, l=lo, h=hi: l <= r["r_atr"] <= h))

# atr_p (volatility regime)
for lo in [0.5, 0.65, 0.75]:
    candidates.append((f"atr_p>={lo}", lambda r, l=lo: r["atr_p"] >= l))
candidates.append(("atr_p<0.25", lambda r: r["atr_p"] < 0.25))

# cascade
for c in [1, 2, 3]:
    candidates.append((f"cascade>={c}", lambda r, c=c: r["cascade"] >= c))
candidates.append(("cascade==3", lambda r: r["cascade"] == 3))
candidates.append(("cascade==1", lambda r: r["cascade"] == 1))

# Momentum (same-dir)
candidates.append(("mom4h same-dir>=2", lambda r: (r["side"] == "long" and r["mom_4h"] >= 2) or (r["side"] == "short" and r["mom_4h"] <= -2)))
candidates.append(("mom4h same-dir>=3", lambda r: (r["side"] == "long" and r["mom_4h"] >= 3) or (r["side"] == "short" and r["mom_4h"] <= -3)))
candidates.append(("mom4h counter<=-2 LONG|>=2 SHORT", lambda r: (r["side"] == "long" and r["mom_4h"] <= -2) or (r["side"] == "short" and r["mom_4h"] >= 2)))
candidates.append(("mom4h counter<=-3 LONG|>=3 SHORT", lambda r: (r["side"] == "long" and r["mom_4h"] <= -3) or (r["side"] == "short" and r["mom_4h"] >= 3)))
candidates.append(("mom12h counter<=-2 LONG|>=2 SHORT", lambda r: (r["side"] == "long" and r["mom_12h"] <= -2) or (r["side"] == "short" and r["mom_12h"] >= 2)))

# EMA distance
candidates.append(("ema50 counter<0 LONG|>0 SHORT (bounce)",
                   lambda r: (r["side"] == "long" and r["ema50"] < 0) or (r["side"] == "short" and r["ema50"] > 0)))
candidates.append(("ema200 deep counter<-3 LONG|>3 SHORT",
                   lambda r: (r["side"] == "long" and r["ema200"] < -3) or (r["side"] == "short" and r["ema200"] > 3)))

# EMA daily trend align
candidates.append(("ema_d=1 LONG | ema_d=-1 SHORT", lambda r: (r["side"] == "long" and r["ema_d"] == 1) or (r["side"] == "short" and r["ema_d"] == -1)))

# Time of day
candidates.append(("hour MSK 13..21 (US)", lambda r: 13 <= r["hour"] <= 21))
candidates.append(("hour MSK 7..14 (EU)", lambda r: 7 <= r["hour"] <= 14))
candidates.append(("hour exclude 5,6,18,23", lambda r: r["hour"] not in (5, 6, 18, 23)))

print(f"\nCandidates: {len(candidates)}")


# === Triple combinations brute-force ===
print("\n" + "=" * 100)
print(" TOP triples (n_closed>=80, sorted by composite score)")
print("=" * 100)

triples = []
N = len(candidates)
for i in range(N):
    for j in range(i+1, N):
        for k in range(j+1, N):
            na, pa = candidates[i]
            nb, pb = candidates[j]
            nc, pc = candidates[k]
            sub = [r for r in rows if pa(r) and pb(r) and pc(r)]
            n, wr, sr = stat(sub)
            if n < 80: continue
            rtr = sr / n
            # composite score: weighted WR + R/tr
            score = wr + 50 * rtr
            triples.append((score, wr, sr, n, rtr, f"{na} & {nb} & {nc}"))

triples.sort(key=lambda x: -x[0])
print(f"  Total valid triples: {len(triples)}")
print()
for sc, wr, sr, n, rtr, nm in triples[:30]:
    print(f"  cl={n:>3}  WR={wr:>5.2f}%  ΣR={sr:>+5.1f}  R/tr={rtr:+.3f}  | {nm}")


# === Train/Test split ===
print("\n" + "=" * 100)
print(" TRAIN (2020-2023, n=618) → TEST (2024-2026, n=476)")
print("=" * 100)

train = [r for r in rows if r["year"] <= 2023]
test = [r for r in rows if r["year"] >= 2024]
print(f"Train: {len(train)} setups, Test: {len(test)} setups\n")

bk("Baseline TRAIN", train)
bk("Baseline TEST", test)
print()

# Evaluate top 20 train pairs on test
print("\n--- Top single+pair filters on TRAIN, validated on TEST ---")
all_simple = []
for i in range(N):
    n_a, pa = candidates[i]
    train_sub = [r for r in train if pa(r)]
    n_t, wr_t, sr_t = stat(train_sub)
    if n_t < 80: continue
    test_sub = [r for r in test if pa(r)]
    n_te, wr_te, sr_te = stat(test_sub)
    all_simple.append((wr_t, n_t, sr_t, wr_te, n_te, sr_te, n_a))

print("\n>>> SINGLE filters: train→test")
all_simple.sort(key=lambda x: -x[0])
print(f"  {'name':<60}  TRAIN(cl/WR/ΣR)             TEST(cl/WR/ΣR)")
for wr_t, n_t, sr_t, wr_te, n_te, sr_te, nm in all_simple[:25]:
    print(f"  {nm:<60}  {n_t:>3}/{wr_t:>5.1f}%/{sr_t:>+5.1f}R  →  {n_te:>3}/{wr_te:>5.1f}%/{sr_te:>+5.1f}R")

# Pairs
print("\n>>> PAIR filters (top by train R/tr, n_train>=80) — validated on TEST")
all_pairs = []
for i in range(N):
    for j in range(i+1, N):
        n_a, pa = candidates[i]
        n_b, pb = candidates[j]
        train_sub = [r for r in train if pa(r) and pb(r)]
        n_t, wr_t, sr_t = stat(train_sub)
        if n_t < 60: continue
        test_sub = [r for r in test if pa(r) and pb(r)]
        n_te, wr_te, sr_te = stat(test_sub)
        rtr_t = sr_t / n_t if n_t else 0
        rtr_te = sr_te / n_te if n_te else 0
        all_pairs.append((rtr_t, n_t, wr_t, sr_t, n_te, wr_te, sr_te, rtr_te, f"{n_a} & {n_b}"))

all_pairs.sort(key=lambda x: -x[0])
print(f"  {'name':<78}  TRAIN(cl/WR/ΣR/R-tr)         TEST(cl/WR/ΣR/R-tr)")
for rtr_t, n_t, wr_t, sr_t, n_te, wr_te, sr_te, rtr_te, nm in all_pairs[:25]:
    print(f"  {nm:<78}  {n_t:>3}/{wr_t:>5.1f}%/{sr_t:>+5.1f}R/{rtr_t:+.2f}  →  {n_te:>3}/{wr_te:>5.1f}%/{sr_te:>+5.1f}R/{rtr_te:+.2f}")


# === Per-year stability of the top filter ===
print("\n" + "=" * 100)
print(" Per-year breakdown for top candidate filters")
print("=" * 100)

def per_year(label, pred):
    print(f"\n--- {label} ---")
    for y in sorted(set(r["year"] for r in rows)):
        sub = [r for r in rows if r["year"] == y and pred(r)]
        n, wr, sr = stat(sub)
        rtr = sr/n if n else 0
        print(f"  {y}  cl={n:>3}  WR={wr:>5.2f}%  ΣR={sr:>+5.1f}  R/tr={rtr:+.3f}")

per_year("pos5d extreme + r_atr [0.55, 1.05]",
         lambda r: ((r["side"] == "long" and r["pos_5d"] < 0.20) or (r["side"] == "short" and r["pos_5d"] > 0.80)) and 0.55 <= r["r_atr"] <= 1.05)

per_year("r_atr [0.85, 1.05]",
         lambda r: 0.85 <= r["r_atr"] <= 1.05)

per_year("pos5d extreme + atr_p>=0.5",
         lambda r: ((r["side"] == "long" and r["pos_5d"] < 0.20) or (r["side"] == "short" and r["pos_5d"] > 0.80)) and r["atr_p"] >= 0.5)

per_year("cascade==3",
         lambda r: r["cascade"] == 3)

per_year("mom4h ≥3 same-dir",
         lambda r: (r["side"] == "long" and r["mom_4h"] >= 2) or (r["side"] == "short" and r["mom_4h"] <= -2))
