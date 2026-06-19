"""L2+L3: Path-dependent TBM on Andrey's 305 OOS signals + Equity curve.

For each signal at time T:
  side=LONG:  entry = close at T,  TP = entry × (1 + tp_pct/100),  SL = entry × (1 - sl_pct/100)
  side=SHORT: entry = close at T,  TP = entry × (1 - tp_pct/100),  SL = entry × (1 + sl_pct/100)

Walk forward through 1m bars within [T, T + 7d]:
  если first touch TP → label=+1, exit=TP price
  если first touch SL → label=-1, exit=SL price
  если ничего за 7d → label=0, exit=last close

Multi-tp grid: TP ∈ {2, 3, 4, 5}%, SL ∈ {0.75, 1.0, 1.5, 2.0}%
Default: TP=3%, SL=1.5% (RR=2:1)

Output:
  ~/Desktop/andrey_tbm_results.csv (per-signal)
  ~/Desktop/andrey_tbm_grid.csv (TP×SL summary)
  ~/Desktop/andrey_equity_curve.png
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SIG_PATH = Path.home() / "Desktop" / "etap_173_signals_caught.csv"
CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT_DIR = Path.home() / "Desktop"

T1_DAYS = 7  # 7-day max hold
HOLD_MS = T1_DAYS * 24 * 3600 * 1000
FEES_BPS = 5      # 0.05% per trade (in basis points × 2 sides = 0.1% total round-trip)
SLIPPAGE_BPS = 2  # 0.02% slippage on entry

# === Load signals ===
print("[1/5] Loading signals...")
df_sig = pd.read_csv(SIG_PATH, parse_dates=["time_utc"])
df_sig["time_ms"] = df_sig["time_utc"].apply(lambda t: int(t.timestamp() * 1000))
df_sig = df_sig.sort_values("time_ms").reset_index(drop=True)
print(f"  Signals: {len(df_sig)}")
print(f"  Period: {df_sig['time_utc'].min()} → {df_sig['time_utc'].max()}")

# === Load 1m BTC (only the OOS window) ===
print("[2/5] Loading 1m BTC over OOS window...")
min_ts = df_sig["time_ms"].min()
max_ts = df_sig["time_ms"].max() + HOLD_MS + 60_000

rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        ts = int(datetime.fromisoformat(r[0]).timestamp() * 1000)
        if ts < min_ts: continue
        if ts > max_ts: break
        rows.append((ts, float(r[2]), float(r[3]), float(r[4])))  # ts, high, low, close
print(f"  1m bars: {len(rows):,}")

ts_arr = np.array([r[0] for r in rows], dtype=np.int64)
hi_arr = np.array([r[1] for r in rows], dtype=np.float64)
lo_arr = np.array([r[2] for r in rows], dtype=np.float64)
cl_arr = np.array([r[3] for r in rows], dtype=np.float64)

# === TBM simulator ===
def simulate(entry_ts, entry_price, side, tp_pct, sl_pct):
    """Returns (label, exit_ts, exit_price, holding_min, realized_R)."""
    risk = sl_pct / 100.0
    # TP/SL prices
    if side == "LONG":
        tp = entry_price * (1 + tp_pct/100)
        sl = entry_price * (1 - sl_pct/100)
    else:
        tp = entry_price * (1 - tp_pct/100)
        sl = entry_price * (1 + sl_pct/100)

    i = int(np.searchsorted(ts_arr, entry_ts, side='right'))  # bar AFTER entry
    end_ts = entry_ts + HOLD_MS
    while i < len(ts_arr) and ts_arr[i] <= end_ts:
        h, l = hi_arr[i], lo_arr[i]
        if side == "LONG":
            hit_tp = h >= tp
            hit_sl = l <= sl
        else:
            hit_tp = l <= tp
            hit_sl = h >= sl
        if hit_tp and hit_sl:
            # worst case: assume SL first
            return (-1, ts_arr[i], sl, (ts_arr[i]-entry_ts)/60_000, -1.0)
        if hit_sl:
            return (-1, ts_arr[i], sl, (ts_arr[i]-entry_ts)/60_000, -1.0)
        if hit_tp:
            R = tp_pct / sl_pct
            return (1, ts_arr[i], tp, (ts_arr[i]-entry_ts)/60_000, R)
        i += 1
    # timeout: close at last bar
    if i >= len(ts_arr): i = len(ts_arr) - 1
    last_close = cl_arr[i]
    pnl_pct = ((last_close - entry_price) / entry_price * 100) * (1 if side == "LONG" else -1)
    R = pnl_pct / sl_pct
    return (0, ts_arr[i], last_close, (ts_arr[i]-entry_ts)/60_000, R)

# === Run TBM with default (TP=3%, SL=1.5%) ===
print("[3/5] Running TBM TP=3% SL=1.5% on 305 signals...")
results = []
for _, s in df_sig.iterrows():
    entry_ts = s["time_ms"]
    # Entry on next 1m after signal time (no within-bar lookahead)
    i_entry = int(np.searchsorted(ts_arr, entry_ts, side='right'))
    if i_entry >= len(ts_arr): continue
    entry_price = cl_arr[i_entry] * (1 + (SLIPPAGE_BPS/10000) * (1 if s["side"]=="LONG" else -1))

    label, exit_ts, exit_price, hold_min, R = simulate(ts_arr[i_entry], entry_price, s["side"], 3.0, 1.5)
    fees_R = (FEES_BPS / 10000) * 2 * 100 / 1.5  # round-trip fees in R units
    R_net = R - fees_R

    results.append({
        "time": s["time_utc"], "side": s["side"], "tier": s["tier"], "p_main": s["p_main"],
        "entry_price": entry_price, "exit_price": exit_price,
        "label": label, "R_gross": R, "R_net": R_net,
        "holding_min": hold_min,
        "hit_3_andrey": s["hit_3"],
    })

df_r = pd.DataFrame(results)
df_r.to_csv(OUT_DIR / "andrey_tbm_results.csv", index=False)
print(f"  Per-signal results saved: {OUT_DIR / 'andrey_tbm_results.csv'}")

# === Stats ===
print(f"\n  Label distribution:")
print(df_r["label"].value_counts().sort_index())
wins = (df_r["label"] == 1).sum()
losses = (df_r["label"] == -1).sum()
timeouts = (df_r["label"] == 0).sum()
print(f"  Wins: {wins} ({wins/len(df_r)*100:.1f}%)")
print(f"  Losses: {losses} ({losses/len(df_r)*100:.1f}%)")
print(f"  Timeouts: {timeouts} ({timeouts/len(df_r)*100:.1f}%)")
print(f"\n  Comparison vs Andrey's hit_3 (path-free):")
print(f"    Andrey hit_3 = 1: {df_r['hit_3_andrey'].sum()}")
print(f"    TBM win:        {wins}  ({wins/df_r['hit_3_andrey'].sum()*100:.0f}% of Andrey's hit_3)")

# Per-tier analysis
print(f"\n  Per-tier WR / EV (gross R / net R):")
tier_stats = []
for tier in ["A_sniper", "B_strong", "C_signal", "D_watch", "E_weak", "F_min"]:
    sub = df_r[df_r["tier"] == tier]
    if sub.empty: continue
    wr = (sub["label"] == 1).mean() * 100
    avg_R_gross = sub["R_gross"].mean()
    avg_R_net = sub["R_net"].mean()
    total_R = sub["R_net"].sum()
    tier_stats.append({"tier": tier, "n": len(sub), "WR%": round(wr,1),
                       "avg_R_gross": round(avg_R_gross,3), "avg_R_net": round(avg_R_net,3),
                       "total_R_net": round(total_R,1)})
    print(f"    {tier:<10} n={len(sub):>3}  WR={wr:>5.1f}%  R_gross={avg_R_gross:+.3f}  R_net={avg_R_net:+.3f}  total={total_R:+.1f}R")
pd.DataFrame(tier_stats).to_csv(OUT_DIR / "andrey_tbm_per_tier.csv", index=False)

# === TP/SL grid ===
print(f"\n[4/5] TP/SL grid sensitivity (thr ≥ 0.6 = tiers A+B+C, n=103)...")
sub_top = df_sig[df_sig["tier"].isin(["A_sniper", "B_strong", "C_signal"])]
grid_results = []
for tp_pct in [2, 3, 4, 5]:
    for sl_pct in [0.75, 1.0, 1.5, 2.0]:
        wins_g, losses_g, timeouts_g = 0, 0, 0
        rs = []
        for _, s in sub_top.iterrows():
            entry_ts = s["time_ms"]
            i_entry = int(np.searchsorted(ts_arr, entry_ts, side='right'))
            if i_entry >= len(ts_arr): continue
            entry_price = cl_arr[i_entry] * (1 + (SLIPPAGE_BPS/10000) * (1 if s["side"]=="LONG" else -1))
            label, _, _, _, R = simulate(ts_arr[i_entry], entry_price, s["side"], tp_pct, sl_pct)
            fees_R = (FEES_BPS / 10000) * 2 * 100 / sl_pct
            rs.append(R - fees_R)
            if label == 1: wins_g += 1
            elif label == -1: losses_g += 1
            else: timeouts_g += 1
        n = wins_g + losses_g + timeouts_g
        wr_g = wins_g / n * 100
        total_R = sum(rs)
        avg_R = total_R / n
        grid_results.append({
            "TP_pct": tp_pct, "SL_pct": sl_pct, "RR": tp_pct/sl_pct,
            "n": n, "WR%": round(wr_g, 1),
            "avg_R_net": round(avg_R, 3), "total_R_net": round(total_R, 1),
        })

df_grid = pd.DataFrame(grid_results)
df_grid.to_csv(OUT_DIR / "andrey_tbm_grid.csv", index=False)
print(df_grid.to_string(index=False))

# === Equity curve ===
print(f"\n[5/5] Equity curve...")
df_r = df_r.sort_values("time").reset_index(drop=True)
df_r["cumR_all"] = df_r["R_net"].cumsum()

# Per-tier cumulative
fig, ax = plt.subplots(figsize=(14, 7))
top_tiers = ["A_sniper", "B_strong", "C_signal"]
mid_tiers = ["D_watch"]
low_tiers = ["E_weak", "F_min"]

colors = {"A_sniper": "#01a648", "B_strong": "#2196f3", "C_signal": "#9c27b0",
          "D_watch": "#ff9800", "E_weak": "#9e9e9e", "F_min": "#666"}

for tier in ["A_sniper", "B_strong", "C_signal", "D_watch", "E_weak", "F_min"]:
    sub = df_r[df_r["tier"] == tier].sort_values("time").copy()
    if sub.empty: continue
    sub["cumR"] = sub["R_net"].cumsum()
    ax.plot(sub["time"], sub["cumR"], label=f"{tier} (n={len(sub)}, {sub['cumR'].iloc[-1]:+.1f}R)",
            color=colors[tier], lw=1.5)

# All signals
ax.plot(df_r["time"], df_r["cumR_all"], label=f"ALL (n={len(df_r)}, {df_r['cumR_all'].iloc[-1]:+.1f}R)",
        color="#000", lw=2.5, alpha=0.7)
# Top tiers combined
top = df_r[df_r["tier"].isin(top_tiers)].sort_values("time").copy()
top["cumR_top"] = top["R_net"].cumsum()
ax.plot(top["time"], top["cumR_top"], label=f"A+B+C (n={len(top)}, {top['cumR_top'].iloc[-1]:+.1f}R)",
        color="#01a648", lw=2.5, ls="--")

ax.axhline(0, color="gray", lw=0.5, alpha=0.5)
ax.set_xlabel("Date")
ax.set_ylabel("Cumulative R (net of fees + slippage)")
ax.set_title(f"Andrey etap_173 OOS Equity Curve | TP=3%, SL=1.5%, fees=0.1%, slip=0.02%\n"
             f"Period: 2025-01-05 → 2026-05-21 (1.37 years)")
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, alpha=0.2)
plt.tight_layout()
plt.savefig(OUT_DIR / "andrey_equity_curve.png", dpi=140)
print(f"  Equity curve: {OUT_DIR / 'andrey_equity_curve.png'}")

# Sharpe / DD per tier band
print(f"\n  Risk-adjusted stats:")
def stats_for(sub_df, label):
    if len(sub_df) < 5: return
    rs = sub_df["R_net"].values
    total = rs.sum()
    avg = rs.mean()
    std = rs.std()
    sharpe = avg / std * np.sqrt(252 / (1.37 / (len(rs) / 252)) if len(rs) > 5 else 1) if std > 0 else 0
    # Simpler: annualize by sqrt(n_per_year)
    n_per_yr = len(rs) / 1.37
    sharpe_annual = avg / std * np.sqrt(n_per_yr) if std > 0 else 0
    cum = np.cumsum(rs)
    dd = cum - np.maximum.accumulate(cum)
    max_dd = dd.min()
    print(f"    {label:<25} n={len(rs):>3} total={total:+.1f}R avg={avg:+.3f}R std={std:.3f} "
          f"Sharpe_ann={sharpe_annual:.2f} MaxDD={max_dd:.1f}R")

stats_for(df_r, "ALL")
stats_for(df_r[df_r["tier"].isin(top_tiers)], "A+B+C (thr≥0.6)")
stats_for(df_r[df_r["tier"].isin(["A_sniper","B_strong"])], "A+B (thr≥0.7)")
stats_for(df_r[df_r["tier"]=="A_sniper"], "A_sniper only (thr≥0.8)")

print(f"\n  Done.")
