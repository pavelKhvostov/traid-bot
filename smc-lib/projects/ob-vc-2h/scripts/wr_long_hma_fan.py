"""HMA fan order analysis for LONG 2h ob_vc.

Perfect bull fan: HMA-50 > HMA-78 > HMA-100 > HMA-144 > HMA-200
Perfect bear fan: HMA-50 < HMA-78 < HMA-100 < HMA-144 < HMA-200

Test:
  - Per-TF fan score (0=fully bear, 4=fully bull) — # of consecutive ordered pairs
  - Multi-TF combined fan
  - Partial alignments
"""
import sys, pathlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone

DATA = pathlib.Path(__file__).parent.parent / "data"
df = pd.read_parquet(DATA / "hma_features_long.parquet")
dec = df[df.R.isin([1, -1])].copy()
print(f"Decisive LONG: N={len(dec)}  W={(dec.R==1).sum()}  L={(dec.R==-1).sum()}")

CUT = int(datetime(2023, 6, 6, tzinfo=timezone.utc).timestamp() * 1000)
TFS = ["2h", "4h", "12h", "1d"]
LENS = [50, 78, 100, 144, 200]


def fan_score(row, tf):
    """Score 0-4: # of consecutive ordered pairs (bull direction).
    Bull pair: HMA_short > HMA_long for (50,78), (78,100), (100,144), (144,200).
    """
    vals = [row[f"hma_{tf}_{L}"] for L in LENS]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals): return None
    score = sum(1 for k in range(4) if vals[k] > vals[k+1])
    return score


# Compute fan scores
for tf in TFS:
    dec[f"fan_{tf}"] = dec.apply(lambda r: fan_score(r, tf), axis=1)

# Distribution
print(f"\nFan score distribution per TF:")
for tf in TFS:
    counts = dec[f"fan_{tf}"].value_counts().sort_index()
    print(f"  {tf}: {dict(counts)}")


def stat(mask, lbl, ref):
    s = dec[mask]
    if len(s) < 10: print(f"  {lbl:<55} N={len(s)} (skip)"); return
    nt=s.touched.sum(); w=(s.R==1).sum(); l=(s.R==-1).sum()
    wr = w/nt*100 if nt else 0
    lift = wr - ref
    flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else ("❌" if lift <= -3 else ""))
    print(f"  {lbl:<55} N={len(s):>4} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")


def report(df_l, title):
    print(f"\n{'='*100}\n{title}\n{'='*100}")
    bw=(df_l.R==1).sum(); bl=(df_l.R==-1).sum(); bnt=df_l.touched.sum()
    bwr = bw/bnt*100 if bnt else 0
    print(f"BASELINE: N={len(df_l)} WR={bwr:.1f}%")

    def s(mask, lbl):
        ss = df_l[mask]
        if len(ss) < 10: return
        nt=ss.touched.sum(); w=(ss.R==1).sum(); l=(ss.R==-1).sum()
        wr = w/nt*100 if nt else 0
        lift = wr - bwr
        flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else ("❌" if lift <= -3 else ""))
        print(f"  {lbl:<55} N={len(ss):>4} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")

    # Per-TF fan score
    for tf in TFS:
        print(f"\n--- {tf} fan score buckets ---")
        for k in [0, 1, 2, 3, 4]:
            s(df_l[f"fan_{tf}"] == k, f"{tf} fan = {k} ({'all bear' if k==0 else 'all bull' if k==4 else 'mixed'})")

    # Multi-TF perfect bull (all TFs fan == 4)
    print(f"\n--- Multi-TF alignments ---")
    all_bull = np.ones(len(df_l), dtype=bool)
    for tf in TFS: all_bull = all_bull & (df_l[f"fan_{tf}"] == 4)
    s(all_bull, "ALL 4 TFs PERFECT BULL fan (fan=4 everywhere)")
    all_bear = np.ones(len(df_l), dtype=bool)
    for tf in TFS: all_bear = all_bear & (df_l[f"fan_{tf}"] == 0)
    s(all_bear, "ALL 4 TFs PERFECT BEAR fan (fan=0 everywhere)")

    # Sum of fan scores across TFs
    df_l = df_l.copy()
    df_l["fan_total"] = df_l[[f"fan_{tf}" for tf in TFS]].sum(axis=1)
    for total in range(17):
        m = df_l.fan_total == total
        if m.sum() < 20: continue
        ss = df_l[m]
        nt=ss.touched.sum(); w=(ss.R==1).sum(); l=(ss.R==-1).sum()
        wr = w/nt*100 if nt else 0
        lift = wr - bwr
        flag = "⭐" if lift >= 3 else ("✓" if lift >= 1 else ("❌" if lift <= -3 else ""))
        print(f"  fan_total = {total:<2}                                          N={len(ss):>4} WR={wr:>5.1f}% Σ={w-l:>+4}R ({lift:+.1f}pp) {flag}")

    # Bull regimes (fan ≥ 3 on multiple TFs)
    print(f"\n--- Confluence (fan ≥ X on TFs) ---")
    for thr in [3, 4]:
        for n_tf in [2, 3, 4]:
            mask_count = np.zeros(len(df_l), dtype=int)
            for tf in TFS:
                mask_count = mask_count + (df_l[f"fan_{tf}"] >= thr).fillna(False).astype(int)
            s(mask_count >= n_tf, f"fan≥{thr} on ≥{n_tf} TFs (out of 4)")


report(dec, "FULL 6y LONG")
report(dec[dec.born_ms >= CUT].copy(), "SUBSET 2023-06-06+ LONG")

# Strongest bear fan as potential LONG buy (mean reversion)
print(f"\n{'='*100}\nSPECIAL: Deep bear regimes (counter-trend LONG)\n{'='*100}")
sub = dec[dec.born_ms >= CUT].copy()
ref = (sub.R==1).sum()/sub.touched.sum()*100 if sub.touched.sum() else 0
print(f"Subset baseline: WR={ref:.1f}%")

# All 4 TFs perfect bear (fan=0)
deep_bear_sub = np.ones(len(sub), dtype=bool)
for tf in TFS: deep_bear_sub = deep_bear_sub & (sub[f"fan_{tf}"] == 0)
ss = sub[deep_bear_sub]
if len(ss) >= 10:
    nt=ss.touched.sum(); w=(ss.R==1).sum(); l=(ss.R==-1).sum()
    wr = w/nt*100 if nt else 0
    print(f"  ALL 4 TFs PERFECT BEAR (subset 2023+): N={len(ss)} WR={wr:.1f}% Σ={w-l:+}R (lift {wr-ref:+.1f}pp)")

# Save
dec.to_parquet(DATA / "hma_fan_long.parquet")
print(f"\nSaved.")
