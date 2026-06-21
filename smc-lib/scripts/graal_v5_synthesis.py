"""Graal v5 — синтез финальной стратегии из robust signals.

Шаги:
  1. Загрузить features из v3 cache.
  2. Определить robust filters (валидированы train/test, монотонны per-year).
  3. Попробовать OR-комбинации robust filters → larger coverage.
  4. Найти ANTI-filter — что точно убивает edge → exclusion.
  5. Финальная синтез-стратегия с per-year breakdown + tr/мес.
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
print(f"Loaded {len(rows)} setups\n")


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
    print(f"  {name:<72} cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


def per_year(label, pred):
    print(f"\n=== {label} ===")
    bk("ALL", [r for r in rows if pred(r)])
    for side in ("long", "short"):
        sub = [r for r in rows if r["side"] == side and pred(r)]
        if sub: bk(f"  {side.upper()}", sub)
    print("  --- per year ---")
    for y in sorted(set(r["year"] for r in rows)):
        sub = [r for r in rows if r["year"] == y and pred(r)]
        n, wr, sr = stat(sub)
        rtr = sr/n if n else 0
        print(f"    {y}  cl={n:>3}  WR={wr:>5.2f}%  ΣR={sr:>+5.1f}  R/tr={rtr:+.3f}")


# === Define robust signals ===
HOUR_OK = lambda r: r["hour"] not in (5, 6, 18, 23)

def filter_A(r):
    """A — sized R/ATR + hour OK. Самый стабильный по магнитуде."""
    return 0.85 <= r["r_atr"] <= 1.05 and HOUR_OK(r)

def filter_B(r):
    """B — strong counter-trend mom_4h + hour OK. Mean-reversion exhaustion."""
    return ((r["side"] == "long" and r["mom_4h"] <= -3) or (r["side"] == "short" and r["mom_4h"] >= 3)) and HOUR_OK(r)

def filter_C(r):
    """C — strong same-dir mom_4h (impulse continuation). Per-year стабилен."""
    return (r["side"] == "long" and r["mom_4h"] >= 3) or (r["side"] == "short" and r["mom_4h"] <= -3)

def filter_D(r):
    """D — wider r_atr band [0.55, 1.05] — captures more setups."""
    return 0.55 <= r["r_atr"] <= 1.05 and HOUR_OK(r)


print("=" * 90)
print(" Step 1: Each robust filter on full 6y")
print("=" * 90)
per_year("FILTER A: r_atr ∈ [0.85, 1.05] AND hour∉{5,6,18,23}", filter_A)
per_year("FILTER B: |mom_4h|≥3 counter-dir AND hour OK (exhaustion bounce)", filter_B)
per_year("FILTER C: |mom_4h|≥3 same-dir (trend impulse)", filter_C)
per_year("FILTER D: r_atr ∈ [0.55, 1.05] AND hour OK (wider)", filter_D)


print("\n" + "=" * 90)
print(" Step 2: OR-combinations of robust filters")
print("=" * 90)
per_year("A ∪ B", lambda r: filter_A(r) or filter_B(r))
per_year("A ∪ C", lambda r: filter_A(r) or filter_C(r))
per_year("A ∪ B ∪ C", lambda r: filter_A(r) or filter_B(r) or filter_C(r))
per_year("D ∪ C", lambda r: filter_D(r) or filter_C(r))
per_year("D ∪ B ∪ C", lambda r: filter_D(r) or filter_B(r) or filter_C(r))


print("\n" + "=" * 90)
print(" Step 3: Search ANTI-filter (WR < 50% clusters with n>=80)")
print("=" * 90)
# Iterate single conditions and find ones with WR<50%
anti_candidates = []
preds = [
    ("hour ∈ {5,6,18,23}", lambda r: r["hour"] in (5, 6, 18, 23)),
    ("hour ∈ {5,6}", lambda r: r["hour"] in (5, 6)),
    ("hour ∈ {18,23}", lambda r: r["hour"] in (18, 23)),
    ("r_atr > 1.05", lambda r: r["r_atr"] > 1.05),
    ("r_atr < 0.55", lambda r: r["r_atr"] < 0.55),
    ("atr_p ∈ [0.25, 0.5)", lambda r: 0.25 <= r["atr_p"] < 0.5),
    ("cascade==2", lambda r: r["cascade"] == 2),
    ("pos5d ∈ [0.6, 0.8)", lambda r: 0.6 <= r["pos_5d"] < 0.8),
    ("mom4h ∈ [1,3)", lambda r: 1 <= r["mom_4h"] < 3),
    ("mom4h ∈ (-3,-1]", lambda r: -3 < r["mom_4h"] <= -1),
    ("ema50 ∈ [1, 3)", lambda r: 1 <= r["ema50"] < 3),
    ("year >= 2025", lambda r: r["year"] >= 2025),
    ("weekday ∈ {Thu, Sat}", lambda r: r["weekday"] in (3, 5)),
    # asymmetric counter to good signals
    ("(LONG ema_d=-1) | (SHORT ema_d=1) (against macro)",
     lambda r: (r["side"] == "long" and r["ema_d"] == -1) or (r["side"] == "short" and r["ema_d"] == 1)),
    ("LONG ema50>1 (price stretched up) | SHORT ema50<-1",
     lambda r: (r["side"] == "long" and r["ema50"] > 1) or (r["side"] == "short" and r["ema50"] < -1)),
]
for name, p in preds:
    sub = [r for r in rows if p(r)]
    n, wr, sr = stat(sub)
    if n >= 80 and wr < 55:
        anti_candidates.append((wr, sr, n, name, p))
anti_candidates.sort(key=lambda x: x[0])
print("\nLoser-cluster candidates (sorted by ascending WR):")
for wr, sr, n, name, _ in anti_candidates[:15]:
    rtr = sr / n
    print(f"  {name:<60} cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


print("\n" + "=" * 90)
print(" Step 4: Apply anti-filter (EXCLUDE losers) on full 6y")
print("=" * 90)

# Compose anti = OR of strongest losers
def anti(r):
    return (
        r["hour"] in (5, 6, 18, 23)  # bad hours
        or (1 <= r["mom_4h"] < 3 and r["side"] == "short")  # short into mild bull momentum
        or (-3 < r["mom_4h"] <= -1 and r["side"] == "long")  # long into mild bear momentum
    )

per_year("After EXCLUDING anti (bad hours + mild adverse momentum)", lambda r: not anti(r))

# Also try: positive filter inside the anti-excluded set
def positive_inside_anti_excluded(r):
    if anti(r): return False
    # within the cleaned set, require ANY of robust filters
    return filter_A(r) or filter_B(r) or filter_C(r) or 0.55 <= r["r_atr"] <= 1.05

per_year("Anti-excluded AND (A∪B∪C∪r_atr[0.55,1.05])", positive_inside_anti_excluded)


print("\n" + "=" * 90)
print(" Step 5: Final candidate strategy")
print("=" * 90)

# Best practical: union of robust positive filters + exclude losers
def final_v1(r):
    if r["hour"] in (5, 6, 18, 23): return False
    return filter_A(r) or filter_B(r) or filter_C(r)

per_year("FINAL v1: (A ∪ B ∪ C) AND hour OK", final_v1)

# Wider variant: D ∪ C ∪ B with hour exclude
def final_v2(r):
    if r["hour"] in (5, 6, 18, 23): return False
    return filter_D(r) or filter_B(r) or filter_C(r)

per_year("FINAL v2: (D ∪ B ∪ C) AND hour OK [wider r_atr]", final_v2)

# Train/test verification for final
print("\n=== TRAIN/TEST verification of FINAL candidates ===")
def trte(label, pred):
    train = [r for r in rows if r["year"] <= 2023 and pred(r)]
    test = [r for r in rows if r["year"] >= 2024 and pred(r)]
    n_tr, wr_tr, sr_tr = stat(train)
    n_te, wr_te, sr_te = stat(test)
    rtr_tr = sr_tr/n_tr if n_tr else 0
    rtr_te = sr_te/n_te if n_te else 0
    print(f"  {label}")
    print(f"     TRAIN: cl={n_tr:>3}  WR={wr_tr:>5.2f}%  ΣR={sr_tr:>+5.1f}  R/tr={rtr_tr:+.3f}")
    print(f"     TEST : cl={n_te:>3}  WR={wr_te:>5.2f}%  ΣR={sr_te:>+5.1f}  R/tr={rtr_te:+.3f}")

trte("FINAL v1 (A∪B∪C, hour OK)", final_v1)
trte("FINAL v2 (D∪B∪C, hour OK)", final_v2)
trte("Just D (r_atr [0.55,1.05] + hour OK)", filter_D)
trte("Just A (r_atr [0.85,1.05] + hour OK)", filter_A)
trte("Just C (mom4h ≥3 same-dir)", filter_C)
trte("Just B (mom4h |≥3| counter + hour OK)", filter_B)

# Trades per month for final
print("\n--- Trades/мес for FINAL candidates ---")
months_total = 72
for label, pred in [("FINAL v1", final_v1), ("FINAL v2", final_v2),
                    ("D only", filter_D), ("A only", filter_A),
                    ("C only", filter_C), ("B only", filter_B),
                    ("baseline", lambda r: True)]:
    n_set = len([r for r in rows if pred(r)])
    print(f"  {label:<24} setups={n_set:>4}   per month={n_set/months_total:.2f}")
