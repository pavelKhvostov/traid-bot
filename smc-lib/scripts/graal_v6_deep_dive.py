"""Deep dive в граалевой стратегии:
  1. Venn-диаграмма пересечений A, B, C
  2. Распределение r_atr — почему [0.85, 1.05] работает
  3. Поведение mom_4h — какие именно сетапы попадают (same-dir vs counter-dir)
  4. Hour-by-hour breakdown — что не так с 5,6,18,23 MSK
  5. Equity curve, max drawdown, Sharpe для FINAL v1
  6. 5 примеров реальных сетапов с разметкой
"""
from __future__ import annotations
import csv
import pathlib
from datetime import datetime, timezone, timedelta
import statistics

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


HOUR_OK = lambda r: r["hour"] not in (5, 6, 18, 23)
A = lambda r: 0.85 <= r["r_atr"] <= 1.05 and HOUR_OK(r)
B = lambda r: ((r["side"] == "long" and r["mom_4h"] <= -3) or (r["side"] == "short" and r["mom_4h"] >= 3)) and HOUR_OK(r)
C = lambda r: ((r["side"] == "long" and r["mom_4h"] >= 3) or (r["side"] == "short" and r["mom_4h"] <= -3))


def stat(rs):
    w = sum(1 for r in rs if r["out"] == "win")
    l = sum(1 for r in rs if r["out"] == "loss")
    n = w + l
    wr = w / n * 100 if n else 0
    sr = w - l
    return n, w, l, wr, sr


def bk(name, rs, ind=2):
    n, w, l, wr, sr = stat(rs)
    rtr = sr / n if n else 0
    pre = " " * ind
    print(f"{pre}{name:<60} n_set={len(rs):>4}  cl={n:>4}  WR={wr:>5.2f}%  ΣR={sr:>+6.1f}  R/tr={rtr:+.3f}")


print("=" * 100)
print(" 1. VENN — пересечения A, B, C")
print("=" * 100)
buckets = {
    "A only        (sized R/ATR ~1 без момент.)": lambda r: A(r) and not B(r) and not C(r),
    "B only        (counter mom без A)": lambda r: B(r) and not A(r) and not C(r),
    "C only        (same-dir mom без A)": lambda r: C(r) and not A(r) and not B(r),
    "A ∩ B         (A + counter mom)": lambda r: A(r) and B(r) and not C(r),
    "A ∩ C         (A + same-dir mom)": lambda r: A(r) and C(r) and not B(r),
    "B ∩ C         (имп+counter одновр.)": lambda r: B(r) and C(r),  # impossible: same vs opposite — оставлю для проверки
    "A ∩ B ∩ C": lambda r: A(r) and B(r) and C(r),
    "─ none (excluded by FINAL v1)": lambda r: not (A(r) or B(r) or C(r)),
}
for name, pred in buckets.items():
    bk(name, [r for r in rows if pred(r)])

print(f"\n  TOTAL by FINAL v1 (A ∪ B ∪ C):")
bk("included", [r for r in rows if A(r) or B(r) or C(r)])
bk("excluded", [r for r in rows if not (A(r) or B(r) or C(r))])

print("\n=" * 1 + "=" * 99)
print(" 2. R/ATR(20) distribution & WR by fine bin")
print("=" * 100)
r_atr_vals = sorted(r["r_atr"] for r in rows)
print(f"  min={min(r_atr_vals):.2f}  median={statistics.median(r_atr_vals):.2f}  "
      f"p25={r_atr_vals[len(r_atr_vals)//4]:.2f}  p75={r_atr_vals[3*len(r_atr_vals)//4]:.2f}  "
      f"max={max(r_atr_vals):.2f}")
print()
bins = [(0, 0.4), (0.4, 0.55), (0.55, 0.7), (0.7, 0.85), (0.85, 1.0), (1.0, 1.15),
        (1.15, 1.5), (1.5, 2.0), (2.0, 999)]
for lo, hi in bins:
    sub = [r for r in rows if lo <= r["r_atr"] < hi]
    bk(f"r_atr ∈ [{lo:.2f}, {hi:.2f})", sub)


print("\n" + "=" * 100)
print(" 3. mom_4h — что это технически, и как ведут себя бины")
print("=" * 100)
print("  mom_4h = signed consecutive same-color 4h-bars сразу перед C1.")
print("  Положительное = bull-streak, отрицательное = bear-streak.")
print("  Для LONG: mom_4h<0 = открытие против медв. волны (counter); mom_4h>0 = в сторону тренда (same).")
print()
for lo, hi in [(-1e9, -4), (-4, -3), (-3, -2), (-2, -1), (-1, 1), (1, 2), (2, 3), (3, 4), (4, 1e9)]:
    sub = [r for r in rows if lo <= r["mom_4h"] < hi]
    bk(f"mom_4h ∈ [{lo}, {hi})", sub)
    for side in ("long", "short"):
        sub2 = [r for r in sub if r["side"] == side]
        if len(sub2) >= 15: bk(f"   {side.upper()}", sub2, ind=5)


print("\n" + "=" * 100)
print(" 4. Hour-of-day — детально (LONG vs SHORT)")
print("=" * 100)
for h in range(24):
    sub = [r for r in rows if r["hour"] == h]
    n_l = sum(1 for r in sub if r["side"] == "long")
    n_s = sum(1 for r in sub if r["side"] == "short")
    n, w, l, wr, sr = stat(sub)
    if n < 15: continue
    long_sub = [r for r in sub if r["side"] == "long"]
    short_sub = [r for r in sub if r["side"] == "short"]
    _, _, _, wr_l, sr_l = stat(long_sub)
    _, _, _, wr_s, sr_s = stat(short_sub)
    marker = "  ⚠️" if h in (5, 6, 18, 23) else ""
    print(f"  h={h:>2} MSK  cl={n:>3}  WR={wr:>5.2f}%  ΣR={sr:>+5.1f}  | "
          f"LONG ({n_l}): WR={wr_l:>5.2f}% ΣR={sr_l:>+4.1f}  "
          f"SHORT ({n_s}): WR={wr_s:>5.2f}% ΣR={sr_s:>+4.1f}{marker}")


print("\n" + "=" * 100)
print(" 5. Independence test — насколько A, B, C дают independent edge")
print("=" * 100)

def lift(name, pred):
    """Inside pred=True vs pred=False — насколько отличается WR."""
    inside = [r for r in rows if pred(r)]
    outside = [r for r in rows if not pred(r)]
    _, _, _, wri, _ = stat(inside)
    _, _, _, wro, _ = stat(outside)
    print(f"  {name:<54} WR(in)={wri:>5.2f}%  WR(out)={wro:>5.2f}%  ΔWR=+{wri-wro:>+4.2f}pp")

print("Each filter, raw lift over its complement:")
lift("A (r_atr [0.85,1.05] + hour OK)", A)
lift("B (mom_4h counter≥3 + hour OK)", B)
lift("C (mom_4h same-dir≥3)", C)
lift("hour OK alone", HOUR_OK)

print("\nNow conditional — does X still help WITHIN cleaned subset?")
clean = [r for r in rows if HOUR_OK(r)]
print(f"  Cleaned (hour OK): n_cl=", end="")
n, _, _, wr, sr = stat(clean); print(f"{n}, WR={wr:.2f}%, ΣR={sr:+.0f}")
def cond_lift(name, pred):
    inside = [r for r in clean if pred(r)]
    outside = [r for r in clean if not pred(r)]
    _, _, _, wri, _ = stat(inside)
    _, _, _, wro, _ = stat(outside)
    print(f"    {name:<52} WR(in)={wri:>5.2f}%  WR(out)={wro:>5.2f}%  ΔWR=+{wri-wro:>+4.2f}pp")
cond_lift("r_atr [0.85, 1.05] (=A inside cleaned)", lambda r: 0.85 <= r["r_atr"] <= 1.05)
cond_lift("mom_4h counter≥3 (=B inside cleaned)", lambda r: (r["side"] == "long" and r["mom_4h"] <= -3) or (r["side"] == "short" and r["mom_4h"] >= 3))
cond_lift("mom_4h same-dir≥3 (=C inside cleaned)", lambda r: (r["side"] == "long" and r["mom_4h"] >= 3) or (r["side"] == "short" and r["mom_4h"] <= -3))


print("\n" + "=" * 100)
print(" 6. Equity curve & MDD for FINAL v1 (chronological)")
print("=" * 100)
# Need to sort chronologically. Use year then estimate by ordering inside year not avail.
# proxy: keep original CSV order which is chronological (как detected)
v1_trades = [r for r in rows if (A(r) or B(r) or C(r))]
v1_closed = [r for r in v1_trades if r["out"] in ("win", "loss")]

equity = 0.0; peak = 0.0; mdd = 0.0
eq_history = []
for t in v1_closed:
    pnl = 1.0 if t["out"] == "win" else -1.0
    equity += pnl
    eq_history.append(equity)
    if equity > peak: peak = equity
    if peak - equity > mdd: mdd = peak - equity

# Sharpe-like (sample): mean / std of pnl
pnls = [1.0 if t["out"] == "win" else -1.0 for t in v1_closed]
mean = statistics.mean(pnls)
sd = statistics.stdev(pnls) if len(pnls) > 1 else 0
sharpe = (mean / sd) * (252 ** 0.5) if sd > 0 else 0  # daily-eqv if avg 1/day

print(f"  trades: {len(v1_closed)}, final equity: {equity:+.0f}R, peak: {peak:+.0f}R, MDD: {mdd:.0f}R")
print(f"  MDD/Equity ratio: {mdd/equity:.3f}" if equity > 0 else "  N/A")
print(f"  mean R per trade: {mean:+.3f}")
print(f"  Sharpe-style: {sharpe:.2f} (treating trades as daily samples — heuristic)")

# Quick consecutive losses tally
worst_streak = 0; cur = 0
for t in v1_closed:
    if t["out"] == "loss":
        cur += 1; worst_streak = max(worst_streak, cur)
    else:
        cur = 0
print(f"  Worst losing streak: {worst_streak}")

# По годам — равномерность
print("\n  Equity progression by year:")
year_pnl = {}
for t in v1_closed:
    year_pnl.setdefault(t["year"], []).append(1.0 if t["out"] == "win" else -1.0)
for y in sorted(year_pnl):
    s = sum(year_pnl[y])
    print(f"    {y}  n={len(year_pnl[y]):>3}  ΣR={s:+5.0f}  R/tr={s/len(year_pnl[y]):+.3f}")


print("\n" + "=" * 100)
print(" 7. Что внутри 'excluded' (833 setups)?")
print("=" * 100)
excluded = [r for r in rows if not (A(r) or B(r) or C(r))]
bk("Excluded total", excluded)
print()
# Внутри excluded — где сидят потери
print("  Distribution of excluded by reason:")
ex_bad_hour = [r for r in excluded if not HOUR_OK(r)]
ex_low_atr = [r for r in excluded if HOUR_OK(r) and r["r_atr"] < 0.85]
ex_high_atr = [r for r in excluded if HOUR_OK(r) and r["r_atr"] > 1.05]
ex_mid_mom = [r for r in excluded if HOUR_OK(r) and 0.85 <= r["r_atr"] <= 1.05]
bk("  bad hours (5,6,18,23)", ex_bad_hour)
bk("  hour OK, r_atr < 0.85 (tight SL)", ex_low_atr)
bk("  hour OK, r_atr > 1.05 (wide SL)", ex_high_atr)
bk("  hour OK, r_atr in band but no mom signal", ex_mid_mom)
