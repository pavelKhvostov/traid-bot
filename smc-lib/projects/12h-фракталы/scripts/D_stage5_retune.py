"""STAGE 5 RETUNE — Find profitable variant of D-layer × Basket strategy.

Variants tested:
    v0: baseline (Stage 5 original — SL 1.5×ATR, TP 5%)
    v1: tighter SL (0.7×ATR) + smaller TP (3%)
    v2: v1 + regime gating (skip shorts if p_bull>0.5, longs if p_bear>0.5)
    v3: v2 + break-even stop (move SL to entry when favor ≥ 1.5%)
    v4: v3 + trailing ATR stop (after favor ≥ 3%, trail SL at 0.5×ATR)
    v5: v4 + LONG-only (BTC bull bias 2020-2026)
    v6: v4 + tier-aware position sizing (Premium 20%, Strong 10%, Standard 5%)

Plus grid search SL/TP for best variant.

Output: comparative table + winner config.
"""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from _lib import load_12h, OUT_DIR

START_EQUITY = 10_000.0
FEE_PER_SIDE = 0.0004
SLIPPAGE_PER_SIDE = 0.0005
TOTAL_COST_RT = 2 * (FEE_PER_SIDE + SLIPPAGE_PER_SIDE)

# ─── Load data ─────────────────────────────────────────────────
print("Loading combined predictions + regime...")
combined = pd.read_parquet(OUT_DIR / "D_stage4_combined.parquet").sort_values("ts_ms").reset_index(drop=True)
regime = pd.read_parquet(OUT_DIR / "D_regime_states.parquet")
combined = combined.merge(regime[["bar_idx", "p_bull", "p_bear", "p_range"]], on="bar_idx", how="left")
print(f"  Events: {len(combined)}")

bars = load_12h()
n = bars["n"]
c = bars["c"]; h = bars["h"]; l = bars["l"]; t = bars["t"]

def atr14(h_, l_, c_):
    tr = np.zeros(len(h_))
    for i in range(1, len(h_)):
        tr[i] = max(h_[i]-l_[i], abs(h_[i]-c_[i-1]), abs(l_[i]-c_[i-1]))
    out = np.zeros(len(h_))
    for i in range(14, len(h_)):
        out[i] = tr[i-14:i+1].mean()
    return out
atr_arr = atr14(h, l, c)


# ─── Generic backtest function ─────────────────────────────────
def backtest(
    events,
    sl_atr_mult=0.7,
    tp_pct=0.03,
    max_hold=4,
    tier_sizing=None,                # dict {"Premium":0.20, "Strong":0.10, "Standard":0.05} or None=const
    const_size=0.10,                 # used if tier_sizing=None
    skip_tier=("Weak",),
    regime_gate=False,
    long_only=False,
    breakeven_at_favor=None,         # float fraction; if favor >= this, move SL to entry
    trail_after_favor=None,          # float; after this favor, trail SL at trail_atr_mult*ATR
    trail_atr_mult=0.5,
    fees=TOTAL_COST_RT,
):
    equity = START_EQUITY
    peak = START_EQUITY
    max_dd = 0.0
    trades = []
    for _, ev in events.iterrows():
        tier = ev["tier"]
        if tier in skip_tier: continue
        direction = ev["direction"]
        if long_only and direction == "short": continue

        if regime_gate:
            if direction == "short" and ev["p_bull"] > 0.5: continue
            if direction == "long" and ev["p_bear"] > 0.5: continue

        bi = int(ev["bar_idx"])
        if bi + max_hold >= n: continue

        # Position size
        if tier_sizing:
            size_frac = tier_sizing.get(tier, 0.05)
        else:
            size_frac = const_size

        entry = c[bi]
        atr_val = atr_arr[bi]
        if atr_val <= 0: continue
        sl_dist = sl_atr_mult * atr_val / entry

        if direction == "short":
            sl_price = entry * (1 + sl_dist)
            tp_price = entry * (1 - tp_pct)
        else:
            sl_price = entry * (1 - sl_dist)
            tp_price = entry * (1 + tp_pct)

        notional = equity * size_frac
        peak_favor = 0.0
        sl_current = sl_price
        exit_price = None; exit_bar = None; exit_reason = None

        for k in range(bi + 1, bi + 1 + max_hold):
            bh, bl = h[k], l[k]
            # Compute current favor with bar high/low
            if direction == "short":
                bar_favor = max(0.0, (entry - bl) / entry)
            else:
                bar_favor = max(0.0, (bh - entry) / entry)
            if bar_favor > peak_favor:
                peak_favor = bar_favor

            # Adjust stop based on peak favor
            if breakeven_at_favor and peak_favor >= breakeven_at_favor:
                if direction == "short":
                    sl_current = min(sl_current, entry)
                else:
                    sl_current = max(sl_current, entry)
            if trail_after_favor and peak_favor >= trail_after_favor:
                # Trail SL by trail_atr_mult × ATR
                trail_dist = trail_atr_mult * atr_arr[k] / c[k]
                if direction == "short":
                    new_sl = c[k] * (1 + trail_dist)
                    sl_current = min(sl_current, new_sl)
                else:
                    new_sl = c[k] * (1 - trail_dist)
                    sl_current = max(sl_current, new_sl)

            # Check exits
            if direction == "short":
                if bh >= sl_current:
                    exit_price = sl_current; exit_reason = "SL"; exit_bar = k; break
                if bl <= tp_price:
                    exit_price = tp_price; exit_reason = "TP"; exit_bar = k; break
            else:
                if bl <= sl_current:
                    exit_price = sl_current; exit_reason = "SL"; exit_bar = k; break
                if bh >= tp_price:
                    exit_price = tp_price; exit_reason = "TP"; exit_bar = k; break

        if exit_price is None:
            exit_bar = bi + max_hold
            exit_price = c[exit_bar]
            exit_reason = "TIMEOUT"

        gross_ret = ((entry - exit_price) / entry) if direction == "short" else ((exit_price - entry) / entry)
        net_ret = gross_ret - fees
        pnl = notional * net_ret
        equity += pnl
        if equity > peak: peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd: max_dd = dd
        trades.append({"net_ret": net_ret, "pnl": pnl, "exit_reason": exit_reason,
                        "tier": tier, "direction": direction,
                        "year": pd.to_datetime(int(ev["ts_ms"]), unit="ms", utc=True).year})

    df = pd.DataFrame(trades)
    if len(df) == 0:
        return {"n": 0, "equity": equity, "return_pct": 0, "win": 0, "sharpe": 0,
                "max_dd": 0, "profit_factor": 0, "trades": df}
    wins = df["net_ret"] > 0
    win_rate = wins.mean() * 100
    avg_ret = df["net_ret"].mean()
    std_ret = df["net_ret"].std()
    sharpe = (avg_ret / std_ret * np.sqrt(60)) if std_ret > 0 else 0  # ~60 trades/year baseline
    profit_factor = (df.loc[wins, "pnl"].sum() / abs(df.loc[~wins, "pnl"].sum())
                     if (~wins).sum() else float("inf"))
    return {
        "n": len(df), "equity": equity,
        "return_pct": (equity - START_EQUITY) / START_EQUITY * 100,
        "win": win_rate, "sharpe": sharpe,
        "max_dd": max_dd * 100, "profit_factor": profit_factor,
        "trades": df,
    }


# ─── Buy-and-hold reference ────────────────────────────────────
combined_clean = combined.dropna(subset=["tier", "p_3", "p_5"]).reset_index(drop=True)
first_bi = int(combined_clean["bar_idx"].iloc[0])
last_bi = int(combined_clean["bar_idx"].iloc[-1])
bh_start = c[first_bi]; bh_end = c[min(last_bi + 4, n - 1)]
bh_return = (bh_end - bh_start) / bh_start * 100
years_period = (t[last_bi] - t[first_bi]) / (365.25 * 24 * 60 * 60 * 1000)
bh_ann = ((bh_end / bh_start) ** (1/years_period) - 1) * 100

print(f"\nBaseline B&H over {years_period:.2f} years: {bh_return:+.1f}%  ({bh_ann:+.1f}% ann)")

# ─── Run variants ──────────────────────────────────────────────
VARIANTS = [
    ("v0 baseline (SL=1.5ATR, TP=5%)",
     dict(sl_atr_mult=1.5, tp_pct=0.05, const_size=0.10)),
    ("v1 tighter (SL=0.7ATR, TP=3%)",
     dict(sl_atr_mult=0.7, tp_pct=0.03, const_size=0.10)),
    ("v2 + regime gating",
     dict(sl_atr_mult=0.7, tp_pct=0.03, const_size=0.10, regime_gate=True)),
    ("v3 + breakeven at 1.5%",
     dict(sl_atr_mult=0.7, tp_pct=0.03, const_size=0.10, regime_gate=True,
          breakeven_at_favor=0.015)),
    ("v4 + trailing after 3%",
     dict(sl_atr_mult=0.7, tp_pct=0.05, const_size=0.10, regime_gate=True,
          breakeven_at_favor=0.015, trail_after_favor=0.03)),
    ("v5 LONG-only + v4",
     dict(sl_atr_mult=0.7, tp_pct=0.05, const_size=0.10, regime_gate=True,
          long_only=True, breakeven_at_favor=0.015, trail_after_favor=0.03)),
    ("v6 tier-sizing + v4",
     dict(sl_atr_mult=0.7, tp_pct=0.05, regime_gate=True,
          tier_sizing={"Premium": 0.20, "Strong": 0.10, "Standard": 0.05},
          breakeven_at_favor=0.015, trail_after_favor=0.03)),
    ("v7 max_hold=8 bars (96h)",
     dict(sl_atr_mult=0.7, tp_pct=0.05, max_hold=8, const_size=0.10, regime_gate=True,
          breakeven_at_favor=0.015, trail_after_favor=0.03)),
    ("v8 Premium+Strong only",
     dict(sl_atr_mult=0.7, tp_pct=0.05, const_size=0.12, regime_gate=True,
          skip_tier=("Weak", "Standard"),
          breakeven_at_favor=0.015, trail_after_favor=0.03)),
]

results = []
for name, cfg in VARIANTS:
    r = backtest(combined_clean, **cfg)
    results.append({"variant": name, **{k: v for k, v in r.items() if k != "trades"}})

results_df = pd.DataFrame(results).set_index("variant")
print("\n" + "=" * 95)
print("VARIANT COMPARISON")
print("=" * 95)
print(f"{'Variant':<40} {'n':>5} {'Ret%':>8} {'Win%':>7} {'PF':>6} {'DD%':>7} {'Sh':>6}")
for _, r in results_df.reset_index().iterrows():
    print(f"  {r['variant']:<38} {r['n']:>5} {r['return_pct']:>+7.1f}% "
          f"{r['win']:>6.1f}% {r['profit_factor']:>5.2f} {r['max_dd']:>6.1f}% {r['sharpe']:>5.2f}")
print(f"\n  Buy-and-hold: {bh_return:+.1f}% return, {bh_ann:+.1f}% ann")

# ─── Grid search для best variant (v4) ─────────────────────────
print("\n" + "=" * 95)
print("GRID SEARCH — SL × TP combinations on v4-style config (regime + trailing)")
print("=" * 95)
SL_GRID = [0.5, 0.7, 1.0, 1.2]
TP_GRID = [0.02, 0.03, 0.04, 0.05]
grid_results = []
for sl in SL_GRID:
    for tp in TP_GRID:
        r = backtest(
            combined_clean,
            sl_atr_mult=sl, tp_pct=tp,
            const_size=0.10, regime_gate=True,
            breakeven_at_favor=0.015,
            trail_after_favor=max(0.02, tp - 0.01),
        )
        grid_results.append({"SL_x_ATR": sl, "TP_pct": tp,
                              "n": r["n"], "return_pct": r["return_pct"],
                              "win": r["win"], "sharpe": r["sharpe"],
                              "max_dd": r["max_dd"], "pf": r["profit_factor"]})
grid_df = pd.DataFrame(grid_results)
print(f"{'SL':>5} {'TP':>5} {'n':>5} {'Ret%':>8} {'Win%':>7} {'PF':>6} {'DD%':>7} {'Sh':>6}")
for _, r in grid_df.iterrows():
    print(f"  {r['SL_x_ATR']:>3.1f} {r['TP_pct']*100:>4.1f}% {int(r['n']):>5} "
          f"{r['return_pct']:>+7.1f}% {r['win']:>6.1f}% "
          f"{r['pf']:>5.2f} {r['max_dd']:>6.1f}% {r['sharpe']:>5.2f}")

# ─── Best variant deep-dive ────────────────────────────────────
best_idx = grid_df["sharpe"].idxmax()
best = grid_df.iloc[best_idx]
print(f"\n  Best by Sharpe: SL={best['SL_x_ATR']:.1f}×ATR, TP={best['TP_pct']*100:.1f}%, "
      f"Sharpe={best['sharpe']:.2f}, Return={best['return_pct']:+.1f}%")

best_ret_idx = grid_df["return_pct"].idxmax()
best_ret = grid_df.iloc[best_ret_idx]
print(f"  Best by Return: SL={best_ret['SL_x_ATR']:.1f}×ATR, TP={best_ret['TP_pct']*100:.1f}%, "
      f"Return={best_ret['return_pct']:+.1f}%, Sharpe={best_ret['sharpe']:.2f}")

# Save
results_df.to_csv(OUT_DIR / "D_stage5_retune_variants.csv")
grid_df.to_csv(OUT_DIR / "D_stage5_retune_grid.csv", index=False)
print(f"\nSaved variants: {OUT_DIR / 'D_stage5_retune_variants.csv'}")
print(f"Saved grid: {OUT_DIR / 'D_stage5_retune_grid.csv'}")
