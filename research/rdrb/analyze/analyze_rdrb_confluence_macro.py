"""Macro confluence-анализ Strategy RDRB через daily-momentum.

Аналог analyze_1_1_1_confluence_macro.py, но загружает сигналы из RDRB CSV.

Для каждого RDRB BTC-сигнала смотрим:
  - TOTALES daily direction за N дней до сигнала (same direction)
  - USDT.D daily direction за N дней (mirror direction — USDT.D зеркальна крипте)

Подгруппы:
  - TOTALES match (only)
  - USDT.D mirror (only)
  - Triple confluence (оба совпали)
  - Any sync (любой из двух)
  - No sync (оба макро против)
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
# --- end repo-root injection ---

from pathlib import Path

import pandas as pd

from data_manager import load_df

DAYS_BACK = 1095
LOOKBACK_DAYS_LIST = [1, 3, 7]
CSV_PATH = Path("signals/strategy_rdrb_3y_RR1.csv")


def load_rdrb_signals_from_csv() -> list[dict]:
    """Deduped RDRB-сигналы из ОБЕИХ CSV (RR=1 и RR=2.2). Каждый сигнал
    получает 2 outcome — для каждого RR. На RR=2.2 часть RR=1-побед
    откатывается в loss (цена прошла +1R и развернулась)."""
    csv1 = CSV_PATH
    csv22 = Path("signals/strategy_rdrb_3y_RR2.2.csv")
    df1 = pd.read_csv(csv1)
    df22 = pd.read_csv(csv22) if csv22.exists() else pd.DataFrame()

    def _key(row):
        return (row["fvg_time"], row["direction"], round(float(row["entry"]), 2))

    map22 = {_key(r): r["outcome"] for _, r in df22.iterrows()} if not df22.empty else {}
    out = []
    for _, row in df1.iterrows():
        t_utc3 = pd.to_datetime(row["fvg_time"])
        t_utc = (t_utc3 - pd.Timedelta(hours=3)).tz_localize("UTC")
        out.append({
            "signal_time": t_utc,
            "direction": row["direction"],
            "outcome_rr1": row["outcome"],
            "outcome_rr2.2": map22.get(_key(row)),
        })
    return out


def daily_momentum_at(df_1d: pd.DataFrame, ts: pd.Timestamp, lookback_days: int) -> int:
    """sign(close(D-1) - close(D-1-lookback)). Использует строгое < day,
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


def stats(rows: list[dict]) -> dict:
    """pnl_rr1 и pnl_rr2.2 считаются ОТДЕЛЬНО — по соответствующему outcome."""
    n = len(rows)
    closed1 = [r for r in rows if r["outcome_rr1"] in ("win", "loss")]
    w1 = sum(1 for r in closed1 if r["outcome_rr1"] == "win")
    l1 = len(closed1) - w1
    wr1 = w1 / len(closed1) * 100 if closed1 else 0
    closed22 = [r for r in rows if r["outcome_rr2.2"] in ("win", "loss")]
    w22 = sum(1 for r in closed22 if r["outcome_rr2.2"] == "win")
    l22 = len(closed22) - w22
    wr22 = w22 / len(closed22) * 100 if closed22 else 0
    return {
        "total": n,
        "rr1_closed": len(closed1), "rr1_wr": round(wr1, 1),
        "rr1_pnl": round(w1 - l1, 1),
        "rr22_closed": len(closed22), "rr22_wr": round(wr22, 1),
        "rr22_pnl": round(w22 * 2.2 - l22, 1),
    }


def main() -> None:
    print(f"[INFO] Strategy RDRB confluence macro, lookback days: {LOOKBACK_DAYS_LIST}")
    print()

    print(f"[INFO] загрузка RDRB сигналов из {CSV_PATH}")
    rdrb = load_rdrb_signals_from_csv()
    print(f"  total: {len(rdrb)}")

    df_totales_1d = load_df("TOTALES", "1d")
    df_usdtd_1d = load_df("USDT_D", "1d")
    print(f"  TOTALES 1d range: {df_totales_1d.index[0]} - {df_totales_1d.index[-1]}")
    print(f"  USDT_D 1d range: {df_usdtd_1d.index[0]} - {df_usdtd_1d.index[-1]}")
    print()

    print("=" * 90)
    print("Baseline - все RDRB сигналы")
    print("=" * 90)
    bs = stats(rdrb)
    print(f"  Total: {bs['total']}")
    print(f"  RR=1.0: closed={bs['rr1_closed']:3d} WR={bs['rr1_wr']:5.1f}% PnL={bs['rr1_pnl']:+5.1f}R")
    print(f"  RR=2.2: closed={bs['rr22_closed']:3d} WR={bs['rr22_wr']:5.1f}% PnL={bs['rr22_pnl']:+6.1f}R")

    for N in LOOKBACK_DAYS_LIST:
        print()
        print("=" * 90)
        print(f"Lookback {N}d - direction = sign(close(t) - close(t-{N}d))")
        print("=" * 90)

        for r in rdrb:
            tot_dir = daily_momentum_at(df_totales_1d, r["signal_time"], N)
            usd_dir = daily_momentum_at(df_usdtd_1d, r["signal_time"], N)
            sign = 1 if r["direction"] == "LONG" else -1
            r["totales_match"] = (tot_dir == sign)
            r["usdtd_mirror_match"] = (usd_dir == -sign)

        only_totales = [r for r in rdrb if r["totales_match"] and not r["usdtd_mirror_match"]]
        only_usdtd = [r for r in rdrb if r["usdtd_mirror_match"] and not r["totales_match"]]
        triple = [r for r in rdrb if r["totales_match"] and r["usdtd_mirror_match"]]
        any_sync = [r for r in rdrb if r["totales_match"] or r["usdtd_mirror_match"]]
        no_sync = [r for r in rdrb if not r["totales_match"] and not r["usdtd_mirror_match"]]

        rows = [
            ("RDRB + TOTALES match (only)",  only_totales),
            ("RDRB + USDT.D mirror (only)",  only_usdtd),
            ("Triple confluence",            triple),
            ("Any sync",                     any_sync),
            ("No sync",                      no_sync),
        ]
        for label, group in rows:
            st = stats(group)
            pct = len(group) / len(rdrb) * 100 if rdrb else 0
            print(f"  {label:30}: n={st['total']:3d} ({pct:4.1f}%)  "
                  f"RR=1: {st['rr1_closed']:3d}cl WR={st['rr1_wr']:5.1f}% "
                  f"PnL={st['rr1_pnl']:+5.1f}R | "
                  f"RR=2.2: {st['rr22_closed']:3d}cl WR={st['rr22_wr']:5.1f}% "
                  f"PnL={st['rr22_pnl']:+6.1f}R")


if __name__ == "__main__":
    main()
