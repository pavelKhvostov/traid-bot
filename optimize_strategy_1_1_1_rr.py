"""RR-оптимизатор Strategy 1.1.1 на BTCUSDT.

Перебирает RR от RR_START до RR_END шагом RR_STEP, для каждого RR
считает суммарный PnL в R, WR и распределение исходов. Использует
MFE-кэш по 1m timeline, чтобы каждый сигнал симулировался один раз.

Логика timeline simulation:
  - Для каждого deduped сигнала собирается срез df_1m с момента
    activation_time.
  - Для произвольного RR: идём по 1m барам по порядку, для каждого
    проверяем «hit SL?» и «hit TP=entry+/-risk*RR?». Pessimistic:
    в одной минуте SL проверяется ДО TP (как в simulate_outcome).
  - Если ни SL, ни TP не достигнут до конца данных — outcome='open'.

Вывод: CSV с RR-сеткой + PNG с графиком PnL(RR) и WR(RR).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest_strategy_1_1_1 import dedupe_signals, simulate_outcome
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

# ---- константы ----
RR_START = 1.0
RR_END = 10.0
RR_STEP = 0.01
SYMBOL = "BTCUSDT"
DAYS_BACK = 1095

OUT_CSV = Path(f"signals/strategy_1_1_1_rr_optimizer_{SYMBOL}_3y.csv")
OUT_PNG = Path(f"signals/strategy_1_1_1_rr_optimizer_{SYMBOL}_3y.png")

# Baseline для сравнения (Фаза 1 + bucketing) — обновится автоматически
# из реального прогона при RR=1.0.


def collect_signals_and_dedup(df_1m: pd.DataFrame) -> list[dict]:
    print("[INFO] загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_20m = compose_from_base(df_1m, "20m")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d = df_1d[df_1d.index >= cutoff]
    df_12h = df_12h[df_12h.index >= cutoff]

    print("[INFO] детекция сигналов (один раз)")
    sigs = detect_strategy_1_1_1_signals(
        df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=True,
    )
    print(f"  raw signals: {len(sigs)}")

    print("[INFO] симуляция и дедуп (RR=1.0 baseline для активации)")
    rows = [simulate_outcome(s, df_1m, 1.0) for s in sigs]
    deduped = dedupe_signals(rows)
    print(f"  deduped: {len(deduped)}")
    return deduped


def build_timeline_cache(deduped: list[dict], df_1m: pd.DataFrame) -> list[dict]:
    """Для каждого deduped сигнала с outcome != not_filled — кэш 1m баров
    после activation_time как массивы numpy (быстрая итерация)."""
    cache = []
    nf_count = 0
    for r in deduped:
        if r["outcome"] == "not_filled":
            cache.append({"row": r, "filled": False})
            nf_count += 1
            continue
        # activation_time в r — UTC+3 строка "YYYY-MM-DD HH:MM"
        # parse обратно в UTC
        act_utc3 = r["activation_time"]
        act = pd.Timestamp(act_utc3) - pd.Timedelta(hours=3)
        act = act.tz_localize("UTC") if act.tz is None else act
        sub = df_1m[df_1m.index >= act]
        if sub.empty:
            cache.append({"row": r, "filled": False})
            continue
        cache.append({
            "row": r,
            "filled": True,
            "direction": r["direction"],
            "entry": float(r["entry"]),
            "sl": float(r["sl"]),
            "risk": abs(float(r["entry"]) - float(r["sl"])),
            "lows": sub["low"].to_numpy(dtype=float),
            "highs": sub["high"].to_numpy(dtype=float),
        })
    print(f"[INFO] timeline-кэш построен: {len(cache)} сигналов "
          f"({nf_count} not_filled пропущены)")
    return cache


def simulate_for_rr(c: dict, rr: float) -> str:
    """Pessimistic: в одной 1m свече SL проверяется ДО TP (как в
    simulate_outcome). 'open' если ни SL ни TP не достигнут."""
    if not c["filled"]:
        return "not_filled"
    direction = c["direction"]
    entry = c["entry"]
    sl = c["sl"]
    risk = c["risk"]
    if direction == "LONG":
        tp = entry + risk * rr
        # vectorized: ищем первый индекс где low<=sl или high>=tp
        sl_hit = c["lows"] <= sl
        tp_hit = c["highs"] >= tp
    else:
        tp = entry - risk * rr
        sl_hit = c["highs"] >= sl
        tp_hit = c["lows"] <= tp

    sl_idx = sl_hit.argmax() if sl_hit.any() else len(sl_hit)
    tp_idx = tp_hit.argmax() if tp_hit.any() else len(tp_hit)
    sl_first = sl_hit.any() and sl_idx <= tp_idx  # SL первый или одновременно
    tp_first = tp_hit.any() and tp_idx < sl_idx

    if sl_first:
        return "loss"
    if tp_first:
        return "win"
    return "open"


def main() -> None:
    # --render-only: не пересчитывать RR-сетку, читать из существующего CSV
    # и только перерисовать PNG + напечатать summary. Для итераций над
    # визуализацией без 90-секундного recompute.
    if "--render-only" in sys.argv:
        if not OUT_CSV.exists():
            raise SystemExit(f"[ERR] CSV не найден: {OUT_CSV}. Запусти без --render-only.")
        df = pd.read_csv(OUT_CSV)
        n_total = int(df.iloc[0]["n_total"])
        print(f"[INFO] --render-only: загружено {len(df)} строк RR из CSV, "
              f"n_total={n_total}")
        summarize_and_render(df, n_total)
        return

    print(f"[INFO] {SYMBOL}, окно {DAYS_BACK}d, RR={RR_START}..{RR_END} step {RR_STEP}")
    df_1m = load_df(SYMBOL, "1m")
    print(f"  df_1m rows: {len(df_1m)}")
    print()

    deduped = collect_signals_and_dedup(df_1m)
    print()

    print("[INFO] построение timeline-кэша по 1m")
    cache = build_timeline_cache(deduped, df_1m)
    print()

    rr_grid = np.round(np.arange(RR_START, RR_END + RR_STEP / 2, RR_STEP), 4)
    n_total = len(deduped)
    print(f"[INFO] прогон по сетке RR ({len(rr_grid)} точек)")
    t0 = time.time()
    results = []
    for rr in rr_grid:
        wins = losses = nf = openn = 0
        for c in cache:
            o = simulate_for_rr(c, rr)
            if o == "win":
                wins += 1
            elif o == "loss":
                losses += 1
            elif o == "not_filled":
                nf += 1
            else:
                openn += 1
        wr = wins / (wins + losses) * 100 if (wins + losses) else 0.0
        pnl = wins * rr - losses
        results.append({
            "rr": float(rr),
            "n_total": n_total,
            "wins": wins,
            "losses": losses,
            "not_filled": nf,
            "open": openn,
            "wr_pct": round(wr, 2),
            "pnl_r": round(pnl, 2),
        })
    print(f"  готово за {time.time() - t0:.1f}s")
    print()

    df = pd.DataFrame(results)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"[INFO] CSV: {OUT_CSV}")

    summarize_and_render(df, n_total)


WR_COMFORT_THRESHOLD = 50.0  # WR ≥ этого = "комфортная" зона


def summarize_and_render(df: pd.DataFrame, n_total: int) -> None:
    peak = df.loc[df["pnl_r"].idxmax()]
    ge50 = df[df["wr_pct"] >= WR_COMFORT_THRESHOLD]
    sweet = ge50.loc[ge50["pnl_r"].idxmax()] if len(ge50) else peak
    rr_1 = df[df["rr"] == 1.0].iloc[0]
    rr_22 = df[df["rr"].round(2) == 2.20].iloc[0]

    def r_per_trade(row):
        return row["pnl_r"] / n_total if n_total else 0.0

    print()
    print("=" * 70)
    print("== МАТЕМАТИЧЕСКИЙ ПИК ==")
    print("=" * 70)
    print(f"  RR={peak['rr']:.2f}, PnL={peak['pnl_r']:+.1f}R, "
          f"WR={peak['wr_pct']:.1f}%, wins={int(peak['wins'])}, "
          f"losses={int(peak['losses'])}")
    print()
    print("=" * 70)
    print(f"== SWEET SPOT (WR ≥ {WR_COMFORT_THRESHOLD:.0f}%) ==")
    print("=" * 70)
    print(f"  RR={sweet['rr']:.2f}, PnL={sweet['pnl_r']:+.1f}R, "
          f"WR={sweet['wr_pct']:.1f}%, wins={int(sweet['wins'])}, "
          f"losses={int(sweet['losses'])}")
    print()
    print("=" * 70)
    print("== СРАВНЕНИЕ ==")
    print("=" * 70)
    print(f"|        |  n  | wins | losses | WR     | PnL     | R/trade |")
    print(f"|--------|-----|------|--------|--------|---------|---------|")
    for label, row in [("RR=1.0", rr_1), ("sweet", sweet),
                       ("RR=2.2", rr_22), (f"peak", peak)]:
        print(
            f"| {label:<6} | {n_total:<3} | {int(row['wins']):<4} | "
            f"{int(row['losses']):<6} | {row['wr_pct']:>5.1f}% | "
            f"{row['pnl_r']:+6.1f}R | {r_per_trade(row):>6.2f}R  |"
        )

    if peak["rr"] >= RR_END - 0.05:
        print()
        print(f"[WARN] пик на правой границе RR={peak['rr']:.2f} ≈ RR_END={RR_END}.")

    # ===== PNG график =====
    fig, ax_pnl = plt.subplots(figsize=(14, 8), dpi=130)
    ax_wr = ax_pnl.twinx()

    # Зоны WR — фон
    ge50_mask = df["wr_pct"] >= WR_COMFORT_THRESHOLD
    if ge50_mask.any():
        rr_min_comfort = df[ge50_mask]["rr"].min()
        rr_max_comfort = df[ge50_mask]["rr"].max()
        ax_pnl.axvspan(rr_min_comfort, rr_max_comfort,
                       color="#c8e6c9", alpha=0.35, zorder=0,
                       label=f"WR ≥ {WR_COMFORT_THRESHOLD:.0f}% (комфорт)")
    # Светло-красный для остального диапазона (вне comfort)
    if ge50_mask.any():
        if rr_max_comfort < RR_END:
            ax_pnl.axvspan(rr_max_comfort, RR_END,
                           color="#ffcdd2", alpha=0.25, zorder=0,
                           label=f"WR < {WR_COMFORT_THRESHOLD:.0f}% (низкий)")
        if rr_min_comfort > RR_START:
            ax_pnl.axvspan(RR_START, rr_min_comfort,
                           color="#ffcdd2", alpha=0.25, zorder=0)

    # Линии PnL и WR
    ax_pnl.plot(df["rr"], df["pnl_r"], color="#1f4ea8", linewidth=2.2,
                label="PnL (R)", zorder=4)
    ax_wr.plot(df["rr"], df["wr_pct"], color="#2ca02c", linewidth=1.2,
               alpha=0.6, label="WR (%)", zorder=3)

    # Горизонтальная пунктирная серая на WR=50%
    ax_wr.axhline(WR_COMFORT_THRESHOLD, color="#666", linestyle="--",
                  linewidth=1.0, alpha=0.55, zorder=2)
    ax_wr.annotate(
        f"WR={WR_COMFORT_THRESHOLD:.0f}%",
        xy=(RR_END, WR_COMFORT_THRESHOLD),
        xytext=(RR_END - 0.1, WR_COMFORT_THRESHOLD + 1.5),
        fontsize=8, color="#666", ha="right",
    )

    # Вертикаль на математическом пике (красный)
    ax_pnl.axvline(peak["rr"], color="#d62728", linestyle="--",
                   linewidth=1.6, alpha=0.85, zorder=5)
    ax_pnl.annotate(
        f"Математический пик\nRR={peak['rr']:.2f}, PnL={peak['pnl_r']:+.0f}R, "
        f"WR={peak['wr_pct']:.1f}%",
        xy=(peak["rr"], peak["pnl_r"]),
        xytext=(peak["rr"] - 1.6, peak["pnl_r"] - 12),
        fontsize=10, color="#d62728",
        bbox=dict(boxstyle="round,pad=0.45", fc="white",
                  ec="#d62728", alpha=0.92),
        arrowprops=dict(arrowstyle="->", color="#d62728", alpha=0.6),
    )

    # Вертикаль на sweet spot (зелёный)
    ax_pnl.axvline(sweet["rr"], color="#2e7d32", linestyle="--",
                   linewidth=1.6, alpha=0.85, zorder=5)
    ax_pnl.annotate(
        f"Sweet spot (WR≥{WR_COMFORT_THRESHOLD:.0f}%)\n"
        f"RR={sweet['rr']:.2f}, PnL={sweet['pnl_r']:+.0f}R, "
        f"WR={sweet['wr_pct']:.1f}%",
        xy=(sweet["rr"], sweet["pnl_r"]),
        xytext=(sweet["rr"] + 0.3, sweet["pnl_r"] + 18),
        fontsize=10, color="#2e7d32",
        bbox=dict(boxstyle="round,pad=0.45", fc="white",
                  ec="#2e7d32", alpha=0.92),
        arrowprops=dict(arrowstyle="->", color="#2e7d32", alpha=0.6),
    )

    # Маркеры на PnL для RR=1.0 (baseline) и RR=2.2 (гипотеза)
    for rr_marker, color, label_short in [
        (1.0, "#5b6770", "RR=1.0\nbaseline"),
        (2.2, "#7b5fa3", "RR=2.2\nгипотеза"),
    ]:
        row = df.iloc[(df["rr"] - rr_marker).abs().idxmin()]
        ax_pnl.plot(row["rr"], row["pnl_r"], "o", color=color,
                    markersize=8, zorder=6)
        ax_pnl.annotate(
            label_short,
            xy=(row["rr"], row["pnl_r"]),
            xytext=(row["rr"], row["pnl_r"] - 14),
            fontsize=8, color=color, ha="center",
        )

    ax_pnl.set_xlabel("RR (Risk:Reward ratio)", fontsize=12)
    ax_pnl.set_ylabel("PnL в R-единицах", fontsize=12, color="#1f4ea8")
    ax_wr.set_ylabel("Win Rate, %", fontsize=12, color="#2ca02c")
    ax_pnl.tick_params(axis="y", labelcolor="#1f4ea8")
    ax_wr.tick_params(axis="y", labelcolor="#2ca02c")
    ax_pnl.set_xticks(np.arange(RR_START, RR_END + 0.01, 0.5))
    ax_pnl.grid(True, alpha=0.25, zorder=1)
    ax_pnl.set_xlim(RR_START, RR_END)

    fig.suptitle(
        f"Strategy 1.1.1 — оптимизация RR ({SYMBOL}, 3 года, n={n_total} сделки)",
        fontsize=14, y=0.99,
    )
    ax_pnl.set_title(
        f"Зелёная зона: WR ≥ {WR_COMFORT_THRESHOLD:.0f}% (комфортная для торговли)",
        fontsize=10, color="#444",
    )

    # Объединённая легенда
    lines1, labels1 = ax_pnl.get_legend_handles_labels()
    lines2, labels2 = ax_wr.get_legend_handles_labels()
    ax_pnl.legend(lines1 + lines2, labels1 + labels2,
                  loc="upper left", fontsize=10, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(OUT_PNG, bbox_inches="tight")
    plt.close(fig)
    print()
    print(f"[INFO] PNG: {OUT_PNG}")


if __name__ == "__main__":
    main()
