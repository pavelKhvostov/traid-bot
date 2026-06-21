"""Cross-join baseline 1275 × Bulkowski signals (etap_172) — standalone WR per pattern.

Tests for each window N ∈ {1, 3, 5, 10} 12h-bars:
  For each pattern P and direction match D:
    keep      = # baseline events with pattern P (side=D) fired in [t-N*12h, t]
    conf      = # of those that are Williams-confirmed
    P(W)      = conf / keep
    imp_caught = # of important pivots (out of 18)

Direction map:  long pattern → FL (low pivot);  short pattern → FH (high pivot)

Output: stdout table + ~/Desktop/baseline_bulkowski_xjoin.csv
"""
from __future__ import annotations
import pandas as pd
from pathlib import Path

BASE = Path.home() / "Desktop" / "baseline_1267.parquet"
SIG = Path.home() / "Desktop" / "etap_172_signals.csv"
OUT = Path.home() / "Desktop" / "baseline_bulkowski_xjoin.csv"

TF12_MS = 12 * 3600_000

print("[1/3] Loading...")
df_base = pd.read_parquet(BASE)
df_sig = pd.read_csv(SIG, parse_dates=["time"])
df_sig["ts_ms"] = df_sig["time"].apply(lambda t: int(t.timestamp() * 1000))
print(f"  Baseline: {len(df_base)}; Bulkowski signals: {len(df_sig)}")
print(f"  Periods: {df_sig['period'].value_counts().to_dict()}")
print(f"  Patterns: {sorted(df_sig['pattern'].unique())}")

# Direction: long → low pivot (FL); short → high pivot (FH)
DIR_MAP = {"long": "low", "short": "high"}

patterns = sorted(df_sig["pattern"].unique())
windows = [1, 3, 5, 10]

print("\n[2/3] Cross-joining...")
results = []
for pat in patterns:
    for side, expected_dir in DIR_MAP.items():
        sig_sub = df_sig[(df_sig["pattern"] == pat) & (df_sig["side"] == side)]
        if sig_sub.empty: continue
        sig_ts = sig_sub["ts_ms"].values

        base_sub = df_base[df_base["direction"] == expected_dir].copy()
        for N in windows:
            w_ms = N * TF12_MS
            # For each baseline event: is there a signal within [ts - w_ms, ts]?
            # Vectorized: for each base_ts, find max sig_ts ≤ base_ts; if (base_ts - max_sig_ts) ≤ w_ms → caught
            base_ts = base_sub["ts"].values
            confirmed = base_sub["confirmed"].values
            important = base_sub["is_important"].values

            # Sort signals
            sig_ts_sorted = sorted(sig_ts)
            import bisect
            caught_mask = []
            for t in base_ts:
                idx = bisect.bisect_right(sig_ts_sorted, t)
                if idx == 0:
                    caught_mask.append(False)
                else:
                    last_sig = sig_ts_sorted[idx - 1]
                    caught_mask.append((t - last_sig) <= w_ms and (t - last_sig) >= 0)
            import numpy as np
            caught_mask = np.array(caught_mask)
            keep = caught_mask.sum()
            conf = (caught_mask & confirmed).sum()
            imp_caught = (caught_mask & important & confirmed).sum()
            p_w = conf / keep * 100 if keep > 0 else 0.0
            results.append({
                "pattern": pat, "side": side, "target_dir": expected_dir,
                "window_bars": N, "keep": int(keep), "conf": int(conf),
                "P_W_pct": round(p_w, 1),
                "imp_caught": int(imp_caught),
                "n_signals": len(sig_sub),
            })

df_out = pd.DataFrame(results)
df_out.to_csv(OUT, index=False)

print("\n[3/3] Results — Standalone WR per pattern per window")
print("="*100)

# Pretty print grouped by pattern
print("\n=== Window N=5 (recommended starting point) ===")
n5 = df_out[df_out["window_bars"] == 5].sort_values(["target_dir", "P_W_pct"], ascending=[True, False])
print(f"\n{'Pattern':<15} {'Side':<7} {'Dir':<5} {'keep':>5} {'conf':>5} {'P(W)%':>7} {'imp':>4} {'n_sig':>6}")
print("-"*70)
for _, r in n5.iterrows():
    flag = "★" if r["P_W_pct"] >= 70 else (" " if r["P_W_pct"] >= 60 else "·")
    print(f"{flag} {r['pattern']:<13} {r['side']:<7} {r['target_dir']:<5} {r['keep']:>5} {r['conf']:>5} {r['P_W_pct']:>6.1f}% {r['imp_caught']:>4} {r['n_signals']:>6}")

print("\n=== Window sensitivity (top 5 patterns by N=5 P(W)) ===")
top5 = n5.head(5)["pattern"].tolist()
print(f"\n{'Pattern':<15} {'Side':<7} {'N=1':<15} {'N=3':<15} {'N=5':<15} {'N=10':<15}")
print("-"*100)
for pat in top5:
    for side in ["long", "short"]:
        sub = df_out[(df_out["pattern"] == pat) & (df_out["side"] == side)]
        if sub.empty: continue
        line = f"{pat:<15} {side:<7}"
        for N in windows:
            row = sub[sub["window_bars"] == N].iloc[0]
            line += f" {row['keep']:>3}/{row['conf']:>3} {row['P_W_pct']:>5.1f}%"
        print(line)

print(f"\n→ Saved: {OUT}")

# Baseline comparison
base_conf_pct = df_base["confirmed"].mean() * 100
base_imp_conf = df_base[df_base["is_important"] & df_base["confirmed"]].shape[0]
print(f"\nBaseline: {len(df_base)} events / {df_base['confirmed'].sum()} conf / {base_conf_pct:.1f}% / {base_imp_conf}/18 imp")
print(f"Lift threshold: WR ≥ 60% (canon admission), ≥ 70% strong")
