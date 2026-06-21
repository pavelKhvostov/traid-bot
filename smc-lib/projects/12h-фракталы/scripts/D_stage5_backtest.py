"""STAGE 5 — Realistic backtest of D-layer × Basket strategy.

Trade rules:
    Entry: close of pivot bar (Basket fires + tier classification)
    Stop loss: opposite extreme of pivot bar + ATR buffer
    Take profit: 3% or 5% (by tier)
    Max hold: 4 bars (48h)
    Position size: % equity by tier

Per-tier strategy:
    Premium  : size=15% equity,  TP=5%, SL=adaptive (~1.5% ATR)
    Strong   : size=10% equity,  TP=3%, SL=adaptive
    Standard : size=5% equity,   TP=3%, SL=adaptive
    Weak     : SKIP

Fees: 0.04% taker (Binance perpetual)
Slippage: 0.05% per side

Output:
    Per-trade ledger + equity curve + summary metrics
    Comparison vs Buy-and-Hold
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from _lib import load_12h, OUT_DIR

# ─── Constants ─────────────────────────────────────────────────
START_EQUITY = 10_000.0
FEE_PER_SIDE = 0.0004    # 4 bps Binance taker
SLIPPAGE_PER_SIDE = 0.0005  # 5 bps
TOTAL_COST_PER_TRADE = 2 * (FEE_PER_SIDE + SLIPPAGE_PER_SIDE)  # ~0.18% RT

TIER_RULES = {
    "Premium":  {"size": 0.15, "tp": 0.05, "sl_atr_mult": 1.5},
    "Strong":   {"size": 0.10, "tp": 0.03, "sl_atr_mult": 1.5},
    "Standard": {"size": 0.05, "tp": 0.03, "sl_atr_mult": 1.5},
    "Weak":     None,  # skip
}

MAX_HOLD_BARS = 4

# ─── Load combined predictions ─────────────────────────────────
print("Loading D-layer combined predictions...")
combined = pd.read_parquet(OUT_DIR / "D_stage4_combined.parquet")
print(f"  Events: {len(combined)}")
combined = combined.sort_values("ts_ms").reset_index(drop=True)

bars = load_12h()
n = bars["n"]
c = bars["c"]; h = bars["h"]; l = bars["l"]; t = bars["t"]

# Compute ATR for SL
def atr14(h_, l_, c_):
    tr = np.zeros(len(h_))
    for i in range(1, len(h_)):
        tr[i] = max(h_[i]-l_[i], abs(h_[i]-c_[i-1]), abs(l_[i]-c_[i-1]))
    out = np.zeros(len(h_))
    for i in range(14, len(h_)):
        out[i] = tr[i-14:i+1].mean()
    return out
atr_arr = atr14(h, l, c)

# ─── Simulate trades ──────────────────────────────────────────
print("\nSimulating trades (max hold 4 bars, SL/TP, fees+slippage)...")
ledger = []
equity = START_EQUITY
peak_equity = START_EQUITY
max_dd = 0.0

for _, ev in combined.iterrows():
    tier = ev["tier"]
    rule = TIER_RULES.get(tier)
    if rule is None:
        continue

    bi = int(ev["bar_idx"])
    if bi + MAX_HOLD_BARS >= n:
        continue

    direction = ev["direction"]
    entry_price = c[bi]
    atr_val = atr_arr[bi]
    sl_distance_pct = (rule["sl_atr_mult"] * atr_val) / entry_price
    tp_distance_pct = rule["tp"]

    # SL price
    if direction == "short":
        sl_price = entry_price * (1 + sl_distance_pct)
        tp_price = entry_price * (1 - tp_distance_pct)
    else:
        sl_price = entry_price * (1 - sl_distance_pct)
        tp_price = entry_price * (1 + tp_distance_pct)

    # Position size in equity
    notional = equity * rule["size"]

    # Walk forward
    exit_price = None
    exit_bar = None
    exit_reason = None
    for k in range(bi + 1, bi + 1 + MAX_HOLD_BARS):
        bar_h, bar_l = h[k], l[k]
        if direction == "short":
            # SL hit if high reaches SL price (conservative — intra-bar)
            if bar_h >= sl_price:
                exit_price = sl_price
                exit_bar = k
                exit_reason = "SL"
                break
            # TP hit if low reaches TP price
            if bar_l <= tp_price:
                exit_price = tp_price
                exit_bar = k
                exit_reason = "TP"
                break
        else:
            if bar_l <= sl_price:
                exit_price = sl_price
                exit_bar = k
                exit_reason = "SL"
                break
            if bar_h >= tp_price:
                exit_price = tp_price
                exit_bar = k
                exit_reason = "TP"
                break

    # Force close at last bar
    if exit_price is None:
        exit_bar = bi + MAX_HOLD_BARS
        exit_price = c[exit_bar]
        exit_reason = "TIMEOUT"

    # Compute P&L
    if direction == "short":
        gross_return = (entry_price - exit_price) / entry_price
    else:
        gross_return = (exit_price - entry_price) / entry_price

    net_return = gross_return - TOTAL_COST_PER_TRADE
    pnl_dollars = notional * net_return
    equity_before = equity
    equity += pnl_dollars

    # Drawdown tracking
    if equity > peak_equity: peak_equity = equity
    dd = (peak_equity - equity) / peak_equity
    if dd > max_dd: max_dd = dd

    ledger.append({
        "bar_idx": bi, "ts_ms": int(ev["ts_ms"]),
        "direction": direction, "tier": tier,
        "p_3": ev["p_3"], "p_5": ev["p_5"], "E_pct": ev["E_pct"],
        "entry_price": entry_price, "exit_price": exit_price,
        "sl_pct": sl_distance_pct * 100, "tp_pct": tp_distance_pct * 100,
        "gross_return_pct": gross_return * 100,
        "net_return_pct": net_return * 100,
        "notional": notional, "pnl_dollars": pnl_dollars,
        "equity_after": equity,
        "exit_bar": exit_bar, "hold_bars": exit_bar - bi,
        "exit_reason": exit_reason,
        "confirmed": ev["confirmed"], "realized_move_4b": ev["realized_move"],
    })

led_df = pd.DataFrame(ledger)
print(f"  Trades executed: {len(led_df)}")

# ─── Summary metrics ──────────────────────────────────────────
final_equity = equity
total_return = (final_equity - START_EQUITY) / START_EQUITY * 100

# Time period
first_ms = int(led_df["ts_ms"].iloc[0])
last_ms = int(led_df["ts_ms"].iloc[-1])
years = (last_ms - first_ms) / (365.25 * 24 * 60 * 60 * 1000)
ann_return = ((final_equity / START_EQUITY) ** (1/years) - 1) * 100

# Win rate
wins = led_df["net_return_pct"] > 0
win_rate = wins.mean() * 100
avg_win = led_df.loc[wins, "net_return_pct"].mean() if wins.sum() else 0
avg_loss = led_df.loc[~wins, "net_return_pct"].mean() if (~wins).sum() else 0
profit_factor = (led_df.loc[wins, "pnl_dollars"].sum() /
                 abs(led_df.loc[~wins, "pnl_dollars"].sum())) if (~wins).sum() else float("inf")

# Sharpe (per-trade approximation, annualised)
trade_returns = led_df["net_return_pct"].values / 100
trades_per_year = len(led_df) / years
mean_r = trade_returns.mean()
std_r = trade_returns.std()
sharpe = (mean_r / std_r * np.sqrt(trades_per_year)) if std_r > 0 else 0

# Buy-and-hold comparison
bh_start_price = c[int(led_df["bar_idx"].iloc[0])]
bh_end_price = c[int(led_df["bar_idx"].iloc[-1]) + MAX_HOLD_BARS]
bh_return = (bh_end_price - bh_start_price) / bh_start_price * 100
bh_ann = ((bh_end_price / bh_start_price) ** (1/years) - 1) * 100

print("\n" + "=" * 90)
print("BACKTEST SUMMARY")
print("=" * 90)
print(f"  Period:              {datetime.fromtimestamp(first_ms/1000, timezone.utc):%Y-%m-%d} → "
      f"{datetime.fromtimestamp(last_ms/1000, timezone.utc):%Y-%m-%d}  ({years:.2f} years)")
print(f"  Starting equity:     ${START_EQUITY:,.0f}")
print(f"  Final equity:        ${final_equity:,.0f}")
print(f"  Total trades:        {len(led_df)}  ({trades_per_year:.1f} per year)")
print(f"")
print(f"  Total return:        {total_return:+.2f}%")
print(f"  Annualised return:   {ann_return:+.2f}%")
print(f"  Win rate:            {win_rate:.1f}%")
print(f"  Avg win:             {avg_win:+.2f}%")
print(f"  Avg loss:            {avg_loss:+.2f}%")
print(f"  Profit factor:       {profit_factor:.2f}")
print(f"  Max drawdown:        {max_dd*100:.1f}%")
print(f"  Sharpe (annualised): {sharpe:.2f}")
print(f"")
print(f"  Buy-and-hold return: {bh_return:+.2f}%  ({bh_ann:+.2f}% annualised)")
print(f"  Strategy vs B&H:     {total_return - bh_return:+.2f}pp difference")

# ─── Per-tier breakdown ────────────────────────────────────────
print("\n" + "=" * 90)
print("PER-TIER STATS")
print("=" * 90)
tier_stats = led_df.groupby("tier").agg(
    n=("net_return_pct", "count"),
    win_rate=("net_return_pct", lambda s: round((s > 0).mean() * 100, 1)),
    avg_ret=("net_return_pct", lambda s: round(s.mean(), 2)),
    total_pnl=("pnl_dollars", lambda s: round(s.sum(), 0)),
    avg_win=("net_return_pct", lambda s: round(s[s > 0].mean() if (s > 0).any() else 0, 2)),
    avg_loss=("net_return_pct", lambda s: round(s[s < 0].mean() if (s < 0).any() else 0, 2)),
)
print(tier_stats.reindex(["Premium", "Strong", "Standard"]).to_string())

# ─── Per-exit-reason ────────────────────────────────────────────
print("\n" + "=" * 90)
print("EXIT REASON BREAKDOWN")
print("=" * 90)
exit_stats = led_df.groupby("exit_reason").agg(
    n=("net_return_pct", "count"),
    pct=("net_return_pct", lambda s: round(s.count() / len(led_df) * 100, 1)),
    avg_ret=("net_return_pct", lambda s: round(s.mean(), 2)),
    total_pnl=("pnl_dollars", lambda s: round(s.sum(), 0)),
)
print(exit_stats.to_string())

# ─── Per-year P&L ──────────────────────────────────────────────
led_df["year"] = pd.to_datetime(led_df["ts_ms"], unit="ms", utc=True).dt.year
print("\n" + "=" * 90)
print("PER-YEAR P&L")
print("=" * 90)
year_stats = led_df.groupby("year").agg(
    n=("net_return_pct", "count"),
    win_rate=("net_return_pct", lambda s: round((s > 0).mean() * 100, 1)),
    total_pnl=("pnl_dollars", "sum"),
    avg_ret=("net_return_pct", lambda s: round(s.mean(), 2)),
)
year_stats["total_pnl"] = year_stats["total_pnl"].round(0).astype(int)
print(year_stats.to_string())

# ─── Save ──────────────────────────────────────────────────────
out = OUT_DIR / "D_stage5_backtest_ledger.parquet"
led_df.drop(columns=["year"]).to_parquet(out, index=False)
print(f"\nSaved ledger: {out}")
