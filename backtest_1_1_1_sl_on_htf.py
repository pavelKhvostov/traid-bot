"""Тест Strategy 1.1.1 с SL внутри OB-htf (вместо top-OB), RR=2.2 + confluence.

Изменения относительно стандартного бэктеста 1.1.1:
  - SL вычисляется НЕ через top-OB зону (1d/12h), а через **OB-htf** (1h/2h):
    LONG  SL = ob_htf.bottom + 15% × (ob_htf.top - ob_htf.bottom)
    SHORT SL = ob_htf.top    - 15% × (ob_htf.top - ob_htf.bottom)
  - RR=2.2 (только эта).
  - На выходе — таблица confluence через 1d/3d/7d daily-momentum
    TOTALES (same direction) и USDT.D (mirror).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest_strategy_1_1_1 import (
    dedupe_signals,
    simulate_outcome as orig_simulate,
    to_utc3,
)
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import OB_SL_DEPTH, detect_strategy_1_1_1_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR_RATIO = 2.2
OUTPUT_PATH = Path("signals/strategy_1_1_1_sl_htf_3y_RR2.2.csv")
LOOKBACK_DAYS_LIST = [1, 3, 7]


def patch_sl_for_htf(sig: dict) -> dict:
    """Возвращает копию sig с SL пересчитанным относительно ob_htf zone."""
    ob_htf_bottom, ob_htf_top = sig["ob_htf_zone"]
    depth = ob_htf_top - ob_htf_bottom
    if sig["direction"] == "LONG":
        new_sl = ob_htf_bottom + depth * OB_SL_DEPTH
    else:
        new_sl = ob_htf_top - depth * OB_SL_DEPTH
    new_sig = dict(sig)
    new_sig["sl"] = float(new_sl)
    new_sig["risk"] = abs(float(sig["entry"]) - new_sl)
    return new_sig


def daily_momentum_at(df_1d: pd.DataFrame, ts: pd.Timestamp, lookback_days: int) -> int:
    """sign(close(D-1) - close(D-1-lookback)). Используем строгое < day,
    чтобы не подсматривать в незакрытую свечу signal-day (lookahead fix)."""
    if df_1d.empty:
        return 0
    day = ts.normalize()
    prev_day = day - pd.Timedelta(days=lookback_days)
    close_now = df_1d[df_1d.index < day]      # ← строгое < (фикс lookahead)
    close_prev = df_1d[df_1d.index < prev_day]
    if close_now.empty or close_prev.empty:
        return 0
    delta = float(close_now["close"].iloc[-1]) - float(close_prev["close"].iloc[-1])
    return 1 if delta > 0 else (-1 if delta < 0 else 0)


def stats(rows: list[dict], rr: float) -> dict:
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    n = len(rows)
    nc = len(closed)
    wins = sum(1 for r in closed if r["outcome"] == "win")
    losses = nc - wins
    wr = wins / nc * 100 if nc else 0.0
    return {
        "total": n, "closed": nc, "wins": wins, "losses": losses,
        "wr_pct": round(wr, 1),
        f"pnl_rr{rr}": round(wins * rr - losses, 1),
    }


def main() -> None:
    print(f"[INFO] Strategy 1.1.1 SL-on-HTF + confluence, RR={RR_RATIO}")
    print()

    print("[INFO] загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]

    print("[INFO] сбор сигналов")
    signals = detect_strategy_1_1_1_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=False,
    )
    print(f"  raw: {len(signals)}")

    print(f"[INFO] симуляция RR={RR_RATIO} с SL на ob_htf...")
    rows: list[dict] = []
    skipped = 0
    for s in signals:
        patched = patch_sl_for_htf(s)
        if patched["risk"] <= 0:
            skipped += 1
            continue
        try:
            out = orig_simulate(patched, df_1m, RR_RATIO)
        except Exception as e:
            print(f"  simulate error: {e!r}")
            continue
        rows.append(out)
    if skipped:
        print(f"  skipped ({skipped}): risk<=0 (entry below new SL — обычно редкий случай)")

    deduped = dedupe_signals(rows)
    df = pd.DataFrame(deduped).drop(columns=["signal_time"], errors="ignore")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"  raw rows: {len(rows)}, deduped: {len(deduped)} -> {OUTPUT_PATH}")

    print()
    print("=" * 90)
    print(f"СВОДКА RR={RR_RATIO}, SL=15% inside от ob_htf (вместо top-OB)")
    print("=" * 90)
    st = stats(deduped, RR_RATIO)
    print(st)
    closed = [r for r in deduped if r["outcome"] in ("win", "loss")]

    # По годам
    print()
    print("По годам:")
    closed_y = pd.DataFrame(closed).copy()
    closed_y["t"] = pd.to_datetime(closed_y["fvg_time"])
    closed_y["year"] = closed_y["t"].dt.year
    for y in sorted(closed_y["year"].unique()):
        sub = closed_y[closed_y["year"] == y].to_dict("records")
        s = stats(sub, RR_RATIO)
        print(f"  {y}: n={s['closed']:3d} WR={s['wr_pct']:5.1f}% PnL={s[f'pnl_rr{RR_RATIO}']:+5.1f}R")

    # По направлению
    print()
    print("По направлению:")
    for dirn in ["LONG", "SHORT"]:
        sub = [r for r in deduped if r["direction"] == dirn]
        s = stats(sub, RR_RATIO)
        print(f"  {dirn}: n={s['total']:3d}/closed={s['closed']:3d} "
              f"WR={s['wr_pct']:5.1f}% PnL={s[f'pnl_rr{RR_RATIO}']:+5.1f}R")

    # Confluence (TOTALES + USDT.D daily momentum)
    print()
    print("=" * 90)
    print("CONFLUENCE через daily-momentum TOTALES + USDT.D mirror")
    print("=" * 90)

    df_totales_1d = load_df("TOTALES", "1d")
    df_usdtd_1d = load_df("USDT_D", "1d")

    # Нормализуем signal_time для confluence (UTC+3 fvg_time → UTC)
    sig_times = []
    for r in deduped:
        t_utc3 = pd.to_datetime(r["fvg_time"])
        t_utc = (t_utc3 - pd.Timedelta(hours=3)).tz_localize("UTC")
        sig_times.append(t_utc)

    for N in LOOKBACK_DAYS_LIST:
        print()
        print(f"--- Lookback {N}d ---")
        groups = {"triple": [], "any": [], "no_sync": []}
        for r, t in zip(deduped, sig_times):
            sign = 1 if r["direction"] == "LONG" else -1
            tot_dir = daily_momentum_at(df_totales_1d, t, N)
            usd_dir = daily_momentum_at(df_usdtd_1d, t, N)
            tot_match = (tot_dir == sign)
            usd_mirror = (usd_dir == -sign)
            if tot_match and usd_mirror:
                groups["triple"].append(r)
            if tot_match or usd_mirror:
                groups["any"].append(r)
            if not tot_match and not usd_mirror:
                groups["no_sync"].append(r)

        for label in ["triple", "any", "no_sync"]:
            s = stats(groups[label], RR_RATIO)
            pct = s["total"] / len(deduped) * 100 if deduped else 0
            print(f"  {label:10}: n={s['total']:3d} ({pct:4.1f}%)  "
                  f"closed={s['closed']:3d}  WR={s['wr_pct']:5.1f}%  "
                  f"PnL={s[f'pnl_rr{RR_RATIO}']:+6.1f}R")


if __name__ == "__main__":
    main()
