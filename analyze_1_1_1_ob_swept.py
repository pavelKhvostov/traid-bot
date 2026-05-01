"""Сплит 1.1.1 сигналов по 'swept liquidity' на OB-htf свечах.

DEDUPED-уровень: считаем по 146 уникальным трейдам, не по 237 raw.
Каждый deduped трейд может иметь несколько путей (1h+2h в OB-htf).
Группа = SWEPT если ХОТЯ БЫ ОДИН путь даёт swept.

Условие SWEPT (для каждого OB-htf пути):
  LONG:  min(low(c1), low(c2)) < min(low(c1-1), low(c1-2))
  SHORT: max(high(c1), high(c2)) > max(high(c1-1), high(c1-2))

Считаем для обоих RR (1.0 и 2.2) WR/PnL по двум подгруппам.
"""
from __future__ import annotations

import pandas as pd

from backtest_strategy_1_1_1 import simulate_outcome
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"


def check_swept(sig: dict, df_1h: pd.DataFrame, df_2h: pd.DataFrame) -> bool | None:
    """Возвращает True/False или None если данных не хватает."""
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2:
        return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1_low = float(df_top.iloc[prev_idx]["low"])
    c2_low = float(df_top.iloc[cur_idx]["low"])
    c1_high = float(df_top.iloc[prev_idx]["high"])
    c2_high = float(df_top.iloc[cur_idx]["high"])
    n1_low = float(df_top.iloc[prev_idx - 1]["low"])
    n2_low = float(df_top.iloc[prev_idx - 2]["low"])
    n1_high = float(df_top.iloc[prev_idx - 1]["high"])
    n2_high = float(df_top.iloc[prev_idx - 2]["high"])

    if sig["direction"] == "LONG":
        ob_low = min(c1_low, c2_low)
        return ob_low < min(n1_low, n2_low)
    else:
        ob_high = max(c1_high, c2_high)
        return ob_high > max(n1_high, n2_high)


def stats(rows: list[dict], rr: float) -> dict:
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    n = len(rows); nc = len(closed)
    wins = sum(1 for r in closed if r["outcome"] == "win")
    losses = nc - wins
    wr = wins / nc * 100 if nc else 0.0
    pnl = wins * rr - losses
    return {
        "n": n, "closed": nc, "wins": wins, "losses": losses,
        "wr": round(wr, 1), "pnl": round(pnl, 1),
    }


def main() -> None:
    print(f"[INFO] split 1.1.1 by OB-htf swept liquidity")
    print()

    print("[INFO] загрузка")
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
    print("[INFO] детект сигналов")
    signals = detect_strategy_1_1_1_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )
    print(f"  raw signals: {len(signals)}")

    # Группируем raw signals по deduped key, проверяем swept для каждого пути
    print("[INFO] симуляция RR=1.0 и RR=2.2 + группировка по deduped key")
    raw_rows = []
    for s in signals:
        out1 = simulate_outcome(s, df_1m, rr_ratio=1.0)
        out22 = simulate_outcome(s, df_1m, rr_ratio=2.2)
        sw = check_swept(s, df_1h, df_2h)
        if sw is None:
            continue
        raw_rows.append({
            "key": (s["signal_time"], s["direction"], round(float(s["entry"]), 2)),
            "direction": s["direction"],
            "ob_htf_tf": s["ob_htf_tf"],
            "outcome_rr1": out1["outcome"],
            "outcome_rr22": out22["outcome"],
            "swept": sw,
        })

    # Group by key
    from collections import defaultdict
    groups = defaultdict(list)
    for r in raw_rows:
        groups[r["key"]].append(r)

    rows = []
    for key, paths in groups.items():
        any_swept = any(p["swept"] for p in paths)
        rows.append({
            "direction": paths[0]["direction"],
            "outcome_rr1": paths[0]["outcome_rr1"],
            "outcome_rr22": paths[0]["outcome_rr22"],
            "swept": any_swept,
            "n_paths": len(paths),
            "n_swept_paths": sum(1 for p in paths if p["swept"]),
        })
    print(f"  raw paths: {len(raw_rows)}")
    print(f"  deduped trades: {len(rows)}")

    swept_rows = [{"outcome": r["outcome_rr1"]} for r in rows if r["swept"]]
    not_swept_rows = [{"outcome": r["outcome_rr1"]} for r in rows if not r["swept"]]
    swept_rows22 = [{"outcome": r["outcome_rr22"]} for r in rows if r["swept"]]
    not_swept_rows22 = [{"outcome": r["outcome_rr22"]} for r in rows if not r["swept"]]

    print()
    print("=" * 90)
    print("DEDUPED трейды — split по swept")
    print("=" * 90)
    print(f"  Total: {len(rows)}")
    print(f"  SWEPT     (хотя бы один путь OB-htf swept): {len(swept_rows)} ({len(swept_rows) / len(rows) * 100:.0f}%)")
    print(f"  NOT-SWEPT (ни один путь не swept):           {len(not_swept_rows)} ({len(not_swept_rows) / len(rows) * 100:.0f}%)")

    print()
    print("=" * 90)
    print("RR=1.0")
    print("=" * 90)
    s_sw = stats(swept_rows, 1.0)
    s_no = stats(not_swept_rows, 1.0)
    print(f"  SWEPT:     n={s_sw['n']:3d} closed={s_sw['closed']:3d} W={s_sw['wins']:3d} L={s_sw['losses']:3d} WR={s_sw['wr']:5.1f}% PnL={s_sw['pnl']:+5.1f}R")
    print(f"  NOT-SWEPT: n={s_no['n']:3d} closed={s_no['closed']:3d} W={s_no['wins']:3d} L={s_no['losses']:3d} WR={s_no['wr']:5.1f}% PnL={s_no['pnl']:+5.1f}R")

    print()
    print("=" * 90)
    print("RR=2.2")
    print("=" * 90)
    s_sw22 = stats(swept_rows22, 2.2)
    s_no22 = stats(not_swept_rows22, 2.2)
    print(f"  SWEPT:     n={s_sw22['n']:3d} closed={s_sw22['closed']:3d} W={s_sw22['wins']:3d} L={s_sw22['losses']:3d} WR={s_sw22['wr']:5.1f}% PnL={s_sw22['pnl']:+6.1f}R")
    print(f"  NOT-SWEPT: n={s_no22['n']:3d} closed={s_no22['closed']:3d} W={s_no22['wins']:3d} L={s_no22['losses']:3d} WR={s_no22['wr']:5.1f}% PnL={s_no22['pnl']:+6.1f}R")

    # По направлениям
    print()
    print("=" * 90)
    print("По направлению (RR=1.0):")
    print("=" * 90)
    for dirn in ["LONG", "SHORT"]:
        for sw_label, sw_val in [("SWEPT", True), ("NOT-SWEPT", False)]:
            sub = [{"outcome": r["outcome_rr1"]} for r in rows
                   if r["direction"] == dirn and r["swept"] == sw_val]
            s = stats(sub, 1.0)
            print(f"  {dirn} {sw_label}: n={s['n']:3d} closed={s['closed']:3d} "
                  f"WR={s['wr']:5.1f}% PnL={s['pnl']:+5.1f}R")


if __name__ == "__main__":
    main()
