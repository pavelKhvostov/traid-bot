"""Production strategy v3.3 explanation dashboard PNG.

6-panel dashboard:
1. Equity curve (cumulative R) — main top panel
2. WR by asset
3. WR by direction × asset
4. WR by year
5. WR by t_id (sorted by WR)
6. Strategy refinements comparison (BTC vs ETH split + weak-type drop)

v3.3 canon: hit_RR_20 lgb N=1100 (proba >= 0.6088), WR 72.4%, +1288R, RR=2.0
"""
from __future__ import annotations
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd


OUT_DIR = pathlib.Path("/Users/vadim/Desktop/output4")
TRADES_CSV = OUT_DIR / "production_strategy_trades_v33.csv"
OUT_PNG = OUT_DIR / "production_strategy_explanation.png"

RR = 2.0
TARGET = "hit_RR_20"
THRESHOLD = 0.6088
N_GOAL = 1100


def main():
    df = pd.read_csv(TRADES_CSV, parse_dates=["born_dt"])
    print(f"Loaded {len(df)} trades")

    fig = plt.figure(figsize=(22, 16))
    gs = fig.add_gridspec(3, 3, height_ratios=[1.4, 1, 1], hspace=0.42, wspace=0.32)

    # ─── Panel 1: Equity curve ───
    ax1 = fig.add_subplot(gs[0, :])
    df_sorted = df.sort_values("born_dt").reset_index(drop=True)
    df_sorted["cum_R"] = df_sorted.R.cumsum()
    df_sorted["cum_peak"] = df_sorted.cum_R.cummax()
    df_sorted["dd"] = df_sorted.cum_R - df_sorted.cum_peak
    max_dd = df_sorted.dd.min()

    ax1.fill_between(df_sorted.born_dt, df_sorted.cum_R, df_sorted.cum_peak,
                      color="#c0392b", alpha=0.35, label=f"Drawdown (max = {max_dd:.0f}R)")
    ax1.plot(df_sorted.born_dt, df_sorted.cum_R, color="#27ae60", lw=2.5,
              label=f"Cumulative R (Σ = +{df.R.sum():.0f}R)")
    ax1.axhline(0, color="gray", ls="--", alpha=0.5)
    ax1.set_ylabel("Cumulative R", fontsize=14, fontweight="bold")
    ax1.set_title(
        f"v3.3 Production strategy: {TARGET} @ N={N_GOAL} (proba ≥ {THRESHOLD:.4f})  |  "
        f"WR = {df.y_true.mean()*100:.1f}%  |  Σ R = +{df.R.sum():.0f}R  "
        f"|  Max DD = {max_dd:.0f}R  |  ETA = ~14 trades/month",
        fontsize=15, fontweight="bold", pad=12)
    ax1.grid(alpha=0.3)
    ax1.legend(loc="upper left", fontsize=11)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # ─── Panel 2: WR by ASSET ────
    ax2 = fig.add_subplot(gs[1, 0])
    asset_stats = df.groupby("asset").agg(
        n=("R", "count"), wins=("y_true", "sum"), sum_r=("R", "sum")
    ).reset_index()
    asset_stats["wr"] = (asset_stats.wins / asset_stats.n) * 100

    colors = ["#f7931a" if a == "BTC" else "#627eea" for a in asset_stats.asset]
    bars = ax2.bar(asset_stats.asset, asset_stats.wr, color=colors,
                    edgecolor="white", linewidth=1.5, width=0.6)
    ax2.axhline(70, color="#c0392b", ls="--", lw=1.5, label="Goal 70%")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("WR %", fontsize=12, fontweight="bold")
    ax2.set_title("WR by ASSET", fontsize=13, fontweight="bold")
    ax2.grid(axis="y", alpha=0.3)
    ax2.legend(loc="upper left", fontsize=9)

    for bar, row in zip(bars, asset_stats.itertuples()):
        h = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2, h + 2,
                 f"{h:.1f}%\nN={row.n}\nΣ={row.sum_r:.0f}R",
                 ha="center", va="bottom", fontsize=10, fontweight="bold")

    # ─── Panel 3: WR by DIRECTION × ASSET ────
    ax3 = fig.add_subplot(gs[1, 1])
    da_stats = df.groupby(["asset", "direction"]).agg(
        n=("R", "count"), wins=("y_true", "sum"), sum_r=("R", "sum")
    ).reset_index()
    da_stats["wr"] = (da_stats.wins / da_stats.n) * 100
    da_stats["label"] = da_stats.asset + "_" + da_stats.direction
    da_stats = da_stats.sort_values("wr", ascending=False)

    cmap = {"BTC_long": "#f5a047", "BTC_short": "#cc7000",
             "ETH_long": "#80a0e0", "ETH_short": "#3a5a8f"}
    colors_da = [cmap[lbl] for lbl in da_stats.label]
    bars = ax3.bar(da_stats.label, da_stats.wr, color=colors_da,
                    edgecolor="white", linewidth=1.5, width=0.65)
    ax3.axhline(70, color="#c0392b", ls="--", lw=1.5)
    ax3.set_ylim(0, 100)
    ax3.set_ylabel("WR %", fontsize=12, fontweight="bold")
    ax3.set_title("WR by DIRECTION × ASSET", fontsize=13, fontweight="bold")
    ax3.grid(axis="y", alpha=0.3)
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=15, ha="right", fontsize=10)

    for bar, row in zip(bars, da_stats.itertuples()):
        h = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2, h + 2,
                 f"{h:.1f}%\nN={row.n}", ha="center", va="bottom",
                 fontsize=9, fontweight="bold")

    # ─── Panel 4: WR by YEAR ────
    ax4 = fig.add_subplot(gs[1, 2])
    df["year"] = df.born_dt.dt.year
    year_stats = df.groupby("year").agg(
        n=("R", "count"), wins=("y_true", "sum"), sum_r=("R", "sum")
    ).reset_index()
    year_stats["wr"] = (year_stats.wins / year_stats.n) * 100

    colors_y = ["#27ae60" if wr >= 70 else "#e67e22" if wr >= 65 else "#c0392b"
                 for wr in year_stats.wr]
    bars = ax4.bar(year_stats.year.astype(str), year_stats.wr,
                    color=colors_y, edgecolor="white", linewidth=1.5, width=0.6)
    ax4.axhline(70, color="#c0392b", ls="--", lw=1.5, label="Goal 70%")
    ax4.set_ylim(0, 100)
    ax4.set_ylabel("WR %", fontsize=12, fontweight="bold")
    ax4.set_title("WR by YEAR  (regime stress test)", fontsize=13, fontweight="bold")
    ax4.grid(axis="y", alpha=0.3)
    ax4.legend(loc="lower right", fontsize=9)

    for bar, row in zip(bars, year_stats.itertuples()):
        h = bar.get_height()
        ax4.text(bar.get_x() + bar.get_width()/2, h + 2,
                 f"{h:.1f}%\nN={row.n}", ha="center", va="bottom",
                 fontsize=9, fontweight="bold")

    # ─── Panel 5: WR by T-TYPE ────
    ax5 = fig.add_subplot(gs[2, :2])
    type_stats = df.groupby("t_id").agg(
        n=("R", "count"), wins=("y_true", "sum"), sum_r=("R", "sum")
    ).reset_index()
    type_stats["wr"] = (type_stats.wins / type_stats.n) * 100
    type_stats = type_stats.sort_values("wr", ascending=False)

    colors_t = ["#27ae60" if wr >= 75 else "#3498db" if wr >= 70 else
                  "#e67e22" if wr >= 65 else "#c0392b" for wr in type_stats.wr]
    bars = ax5.bar(type_stats.t_id, type_stats.wr, color=colors_t,
                    edgecolor="white", linewidth=1.0, width=0.7)
    ax5.axhline(70, color="#c0392b", ls="--", lw=1.5, label="Goal 70%")
    ax5.set_ylim(0, 100)
    ax5.set_ylabel("WR %", fontsize=12, fontweight="bold")
    ax5.set_title("WR by T-TYPE  (sorted by WR descending)  |  green ≥75%, blue 70-75%, orange 65-70%, red <65%",
                   fontsize=13, fontweight="bold")
    ax5.grid(axis="y", alpha=0.3)
    ax5.legend(loc="upper right", fontsize=9)
    plt.setp(ax5.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=9)

    for bar, row in zip(bars, type_stats.itertuples()):
        h = bar.get_height()
        ax5.text(bar.get_x() + bar.get_width()/2, h + 2,
                 f"N={row.n}", ha="center", va="bottom", fontsize=8)

    # ─── Panel 6: Refinements (v3.3 specific) ───
    ax6 = fig.add_subplot(gs[2, 2])

    base = df.copy()
    eth_only = df[df.asset == "ETH"]
    weak_types_v33 = ["T9b", "T1a", "T7a"]   # WR < 65% in v3.3
    no_weak = df[~df.t_id.isin(weak_types_v33)]
    eth_no_weak = df[(df.asset == "ETH") & (~df.t_id.isin(weak_types_v33))]
    short_only = df[df.direction == "short"]

    refs = []
    for label, sub in [
        ("Base\n(all)", base),
        ("A: ETH\nonly", eth_only),
        ("B: −weak\ntypes", no_weak),
        ("C: SHORT\nonly", short_only),
        ("D: ETH +\nno-weak", eth_no_weak),
    ]:
        n = len(sub)
        wr = sub.y_true.mean() * 100 if n else 0
        sum_r = sub.R.sum()
        refs.append({"label": label, "n": n, "wr": wr, "sum_r": sum_r})

    refs_df = pd.DataFrame(refs)
    width = 0.35
    x = np.arange(len(refs_df))
    ax6_b = ax6.twinx()
    bars1 = ax6.bar(x - width/2, refs_df.wr, width, color="#3498db",
                     label="WR %", edgecolor="white", linewidth=1.0)
    bars2 = ax6_b.bar(x + width/2, refs_df.n, width, color="#e67e22",
                       label="N trades", edgecolor="white", linewidth=1.0)
    ax6.axhline(70, color="#c0392b", ls="--", lw=1.5, alpha=0.7)
    ax6.set_xticks(x)
    ax6.set_xticklabels(refs_df.label, fontsize=9)
    ax6.set_ylabel("WR %", color="#2980b9", fontweight="bold")
    ax6_b.set_ylabel("N trades", color="#d35400", fontweight="bold")
    ax6.set_ylim(50, 85)
    ax6.set_title("Strategy refinements compared (v3.3)", fontsize=13, fontweight="bold")
    ax6.grid(axis="y", alpha=0.3)

    for bar, row in zip(bars1, refs_df.itertuples()):
        h = bar.get_height()
        ax6.text(bar.get_x() + bar.get_width()/2, h + 0.5,
                 f"{h:.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold",
                 color="#1a5490")
    for bar, row in zip(bars2, refs_df.itertuples()):
        h = bar.get_height()
        ax6_b.text(bar.get_x() + bar.get_width()/2, h + 20,
                    f"+{row.sum_r:.0f}R", ha="center", va="bottom",
                    fontsize=8, color="#a04000")

    btc_n = (df.asset == "BTC").sum()
    btc_wr = df[df.asset == "BTC"].y_true.mean() * 100
    btc_r = df[df.asset == "BTC"].R.sum()
    eth_n = (df.asset == "ETH").sum()
    eth_wr = df[df.asset == "ETH"].y_true.mean() * 100
    eth_r = df[df.asset == "ETH"].R.sum()

    fig.suptitle(
        f"v3.3 Production Strategy Explanation  ·  hit_RR_20 lgb @ N=1100 (RR=2.0)  ·  "
        f"BTC+ETH 2020-01 → 2026-06\n"
        f"BTC: N={btc_n}, WR={btc_wr:.1f}%, Σ {btc_r:+.0f}R     │     "
        f"ETH: N={eth_n}, WR={eth_wr:.1f}%, Σ {eth_r:+.0f}R     │     "
        f"PBO=0.55, max DD={max_dd:.0f}R",
        fontsize=14, fontweight="bold", y=0.997)

    plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
    print(f"Saved: {OUT_PNG}")


if __name__ == "__main__":
    main()
