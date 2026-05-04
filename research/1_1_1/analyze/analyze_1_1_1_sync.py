"""Анализ синхронизации Strategy 1.1.1 между BTCUSDT, TOTALES и USDT.D.

Гипотеза: confluence сигналов с разных источников = более надёжный сетап.

USDT.D зеркальна рынку — её LONG = bearish крипты. Поэтому:
  BTC LONG    + TOTALES LONG  + USDT.D SHORT  = full bullish confluence
  BTC SHORT   + TOTALES SHORT + USDT.D LONG   = full bearish confluence

Замеряем:
  - Сколько BTC-сигналов имеют sync с TOTALES (same direction) в окне ±24h
  - Сколько имеют sync с USDT.D (mirror direction)
  - Сколько имеют triple sync
  - WR / PnL BTC-сигналов в каждой подгруппе vs baseline (все BTC)
"""
from __future__ import annotations


# --- repo-root injection (Phase 3 refactor) ---
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
_BT_DIR = _ROOT / "research" / "1_1_1" / "backtest"
if str(_BT_DIR) not in _sys.path:
    _sys.path.insert(0, str(_BT_DIR))
# --- end repo-root injection ---

from pathlib import Path

import pandas as pd

from backtest_strategy_1_1_1 import simulate_outcome
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095
SYNC_WINDOWS_HOURS = [6, 12, 24]


def _empty_ohlc() -> pd.DataFrame:
    """Пустой OHLC-фрейм с DatetimeIndex (для совместимости с детектором)."""
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex([], tz="UTC", name="open_time")
    return df


def load_btc_from_csv() -> list[dict]:
    """Deduped 146 BTC-сигналов из RR=1 CSV. signal_time = fvg_time (UTC+3) - 3h."""
    csv = Path("signals/strategy_1_1_1_3y_RR1.csv")
    df = pd.read_csv(csv)
    out = []
    for _, row in df.iterrows():
        t_utc3 = pd.to_datetime(row["fvg_time"])
        t_utc = (t_utc3 - pd.Timedelta(hours=3)).tz_localize("UTC")
        out.append({
            "signal_time": t_utc,
            "direction": row["direction"],
            "outcome": row["outcome"],
            "entry": float(row["entry"]),
        })
    return out


def collect_signals_for(name: str, has_1m: bool, days_back: int = DAYS_BACK) -> list[dict]:
    """Прогон детектора. has_1m=False для CRYPTOCAP (нет 1m → нет 20m)."""
    df_1d = load_df(name, "1d")
    df_4h = load_df(name, "4h")
    df_1h = load_df(name, "1h")
    df_15m = load_df(name, "15m")
    if any(df.empty for df in (df_1d, df_4h, df_1h, df_15m)):
        print(f"[ERROR] {name}: пустые CSV")
        return []

    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")

    if has_1m:
        df_1m = load_df(name, "1m")
        df_20m = compose_from_base(df_1m, "20m") if not df_1m.empty else _empty_ohlc()
    else:
        df_20m = _empty_ohlc()  # нет 1m → 20m не используется

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=days_back)
    df_1d_filtered = df_1d[df_1d.index >= cutoff]

    signals = detect_strategy_1_1_1_signals(
        df_1d_filtered, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=False,
    )
    return signals


def normalize_signals(signals: list[dict]) -> list[dict]:
    """Оставляем только нужные поля для sync-анализа."""
    return [
        {
            "signal_time": pd.Timestamp(s["signal_time"]).tz_convert("UTC") if pd.Timestamp(s["signal_time"]).tz is not None else pd.Timestamp(s["signal_time"]).tz_localize("UTC"),
            "direction": s["direction"],
            "entry": s["entry"],
            "sl": s["sl"],
            "ob_htf_tf": s["ob_htf_tf"],
            "fvg_tf": s["fvg_tf"],
        }
        for s in signals
    ]


def find_sync(
    btc_sig: dict, other_sigs: list[dict], same_direction: bool, window_hours: int,
) -> dict | None:
    """Ищем в other_sigs сигнал в окне ±window_hours от btc.signal_time
    с нужным направлением. same_direction=False → mirror (USDT.D)."""
    btc_dir = btc_sig["direction"]
    target_dir = btc_dir if same_direction else ("SHORT" if btc_dir == "LONG" else "LONG")
    btc_t = btc_sig["signal_time"]
    win = pd.Timedelta(hours=window_hours)
    for s in other_sigs:
        if s["direction"] != target_dir:
            continue
        if abs(s["signal_time"] - btc_t) <= win:
            return s
    return None


def stats_for(rows: list[dict]) -> dict:
    """WR/PnL только для RR=1.0 — outcomes здесь это RR=1 симуляция.

    pnl_rr2.2 НЕ считаем: на RR=2.2 часть RR=1-побед откатывается в loss
    (цена прошла +1R и развернулась). Без отдельной симуляции на RR=2.2
    мы можем считать только RR=1 honest. Если нужен RR=2.2 — используй
    analyze_1_1_1_confluence_macro.py с ОБОИМИ CSV.
    """
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    n = len(rows)
    nc = len(closed)
    wins = sum(1 for r in closed if r["outcome"] == "win")
    losses = nc - wins
    wr = wins / nc * 100 if nc else 0.0
    pnl_rr1 = wins * 1.0 - losses
    return {
        "total": n, "closed": nc, "wins": wins, "losses": losses,
        "wr_pct": round(wr, 1),
        "pnl_rr1": round(pnl_rr1, 1),
    }


def main() -> None:
    print(f"[INFO] окно: {DAYS_BACK} дней, sync windows: {SYNC_WINDOWS_HOURS}h")
    print()

    # Определяем общее окно — самая поздняя 15m start между источниками.
    starts = []
    for name in ["BTCUSDT", "TOTALES", "USDT_D"]:
        df = load_df(name, "15m")
        if not df.empty:
            starts.append((name, df.index[0]))
    common_start = max(s for _, s in starts)
    print(f"[INFO] 15m start dates:")
    for name, s in starts:
        print(f"    {name}: {s}")
    print(f"[INFO] common analysis start: {common_start}")
    print()

    # Дополнительно — окно где есть только TOTALES (без USDT.D)
    totales_start = next(s for n, s in starts if n == "TOTALES")

    print("[INFO] BTC сигналы из CSV (deduped, 146)")
    btc_all = load_btc_from_csv()
    print(f"  total: {len(btc_all)}")
    btc_outcomes = [r for r in btc_all if r["signal_time"] >= common_start]
    print(f"  in common-3way window (>={common_start.date()}): {len(btc_outcomes)}")
    btc_totales_window = [r for r in btc_all if r["signal_time"] >= totales_start]
    print(f"  in TOTALES-only window (>={totales_start.date()}): {len(btc_totales_window)}")

    print("[INFO] TOTALES детект")
    totales_signals = normalize_signals(collect_signals_for("TOTALES", has_1m=False))
    print(f"  signals: {len(totales_signals)}")

    print("[INFO] USDT_D детект")
    usdtd_signals = normalize_signals(collect_signals_for("USDT_D", has_1m=False))
    print(f"  signals: {len(usdtd_signals)}")

    # ------------ ANALYSIS 1: TOTALES-only window (52 дня) ------------
    print()
    print("#" * 90)
    print(f"# ANALYSIS 1 — TOTALES-only window (>= {totales_start.date()}, 52 дней)")
    print(f"# Baseline: {stats_for(btc_totales_window)}")
    print("#" * 90)
    for win_h in SYNC_WINDOWS_HOURS:
        print()
        print(f"-- Sync window ±{win_h}h (TOTALES only, same direction) --")
        with_match = []
        without = []
        for r in btc_totales_window:
            m = find_sync(r, totales_signals, same_direction=True, window_hours=win_h)
            (with_match if m else without).append(r)
        st_match = stats_for(with_match)
        st_no = stats_for(without)
        print(f"  TOTALES match    : n={st_match['total']:3d}  closed={st_match['closed']:3d}  "
              f"WR={st_match['wr_pct']:5.1f}%  PnL@1={st_match['pnl_rr1']:+5.1f}R")
        print(f"  No TOTALES match : n={st_no['total']:3d}  closed={st_no['closed']:3d}  "
              f"WR={st_no['wr_pct']:5.1f}%  PnL@1={st_no['pnl_rr1']:+5.1f}R")

    # ------------ ANALYSIS 2: full 3-way confluence (17 дней) ------------
    print()
    print("#" * 90)
    print(f"# ANALYSIS 2 — full 3-way confluence window (>= {common_start.date()}, 17 дней)")
    print("#" * 90)
    print()
    print("=" * 90)
    print("Baseline — все BTC сигналы в окне")
    print("=" * 90)
    print(stats_for(btc_outcomes))

    for win_h in SYNC_WINDOWS_HOURS:
        print()
        print("=" * 90)
        print(f"Sync window ±{win_h}h")
        print("=" * 90)

        # Маркируем BTC-сигналы по наличию sync
        for r in btc_outcomes:
            r["sync_totales"] = find_sync(r, totales_signals, same_direction=True, window_hours=win_h) is not None
            r["sync_usdtd_mirror"] = find_sync(r, usdtd_signals, same_direction=False, window_hours=win_h) is not None

        only_totales = [r for r in btc_outcomes if r["sync_totales"] and not r["sync_usdtd_mirror"]]
        only_usdtd = [r for r in btc_outcomes if r["sync_usdtd_mirror"] and not r["sync_totales"]]
        triple = [r for r in btc_outcomes if r["sync_totales"] and r["sync_usdtd_mirror"]]
        any_sync = [r for r in btc_outcomes if r["sync_totales"] or r["sync_usdtd_mirror"]]
        no_sync = [r for r in btc_outcomes if not r["sync_totales"] and not r["sync_usdtd_mirror"]]

        rows = [
            ("BTC + TOTALES (only)", only_totales),
            ("BTC + USDT.D mirror (only)", only_usdtd),
            ("Triple confluence", triple),
            ("Any sync", any_sync),
            ("No sync (BTC solo)", no_sync),
        ]
        for label, group in rows:
            st = stats_for(group)
            print(f"  {label:32}: n={st['total']:3d}  closed={st['closed']:3d}  "
                  f"WR={st['wr_pct']:5.1f}%  PnL@1={st['pnl_rr1']:+5.1f}R")


if __name__ == "__main__":
    main()
