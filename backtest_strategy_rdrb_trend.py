"""RDRB шаг 3: HTF trend alignment — counter-trend filter.

Гипотеза: RDRB лучше работает как разворот после движения. Поэтому:
  LONG  RDRB только если BTC 1d-моментум ВНИЗ за N дней (counter-trend up)
  SHORT RDRB только если BTC 1d-моментум ВВЕРХ за N дней (counter-trend down)

Сравниваем 3 подгруппы по каждому lookback (1d / 3d / 7d):
  Counter-trend  : trend против signal direction
  Trend follow   : trend по signal direction (same as confluence)
  Flat/no-opinion: 1d-моментум = 0 (редко)

Параметры trade'а: entry=0.95, sl=0.35, RR=2.2.
"""
from __future__ import annotations

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_rdrb import detect_strategy_rdrb_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR = 2.2
ENTRY_PCT = 0.95
SL_PCT = 0.35
LOOKBACKS = [1, 3, 7]


def daily_momentum(df: pd.DataFrame, ts: pd.Timestamp, lookback: int) -> int:
    if df.empty:
        return 0
    day = ts.normalize()
    prev = day - pd.Timedelta(days=lookback)
    n = df[df.index <= day]
    p = df[df.index <= prev]
    if n.empty or p.empty:
        return 0
    delta = float(n["close"].iloc[-1]) - float(p["close"].iloc[-1])
    return 1 if delta > 0 else (-1 if delta < 0 else 0)


def simulate_one(sig: dict, df_1m: pd.DataFrame) -> str:
    direction = sig["direction"]
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    rdrb_b, rdrb_t = sig["rdrb_zone"]
    if direction == "LONG":
        entry = fvg_b + ENTRY_PCT * (fvg_t - fvg_b)
        sl = obh_b + SL_PCT * (rdrb_b - obh_b)
        if sl >= entry:
            return "skipped"
        risk = entry - sl
        tp = entry + risk * RR
    else:
        entry = fvg_t - ENTRY_PCT * (fvg_t - fvg_b)
        sl = obh_t + SL_PCT * (rdrb_t - obh_t)
        if sl <= entry:
            return "skipped"
        risk = sl - entry
        tp = entry - risk * RR

    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]
    activation = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= entry: activation = ts; break
        else:
            if h >= entry: activation = ts; break
    if activation is None:
        return "not_filled"
    sim = df_1m[df_1m.index >= activation]
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= sl: return "loss"
            if h >= tp: return "win"
        else:
            if h >= sl: return "loss"
            if l <= tp: return "win"
    return "open"


def stats(rows, rr=RR):
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    n = len(rows); nc = len(closed)
    wins = sum(1 for r in closed if r["outcome"] == "win")
    losses = nc - wins
    wr = wins / nc * 100 if nc else 0.0
    return {"n": n, "closed": nc, "wins": wins, "losses": losses,
            "wr": round(wr, 1), "pnl": round(wins * rr - losses, 1)}


def main() -> None:
    print(f"[INFO] RDRB HTF trend filter sweep, RR={RR}, entry={ENTRY_PCT}, sl={SL_PCT}")
    print()

    print("[INFO] загрузка")
    df_1d_btc = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d_btc[df_1d_btc.index >= cutoff - pd.Timedelta(days=5)]
    df_12h_f = df_12h[df_12h.index >= cutoff - pd.Timedelta(days=5)]
    df_1h_f = df_1h[df_1h.index >= cutoff - pd.Timedelta(days=2)]
    df_2h_f = df_2h[df_2h.index >= cutoff - pd.Timedelta(days=2)]
    df_15m_f = df_15m[df_15m.index >= cutoff - pd.Timedelta(days=2)]
    df_20m_f = df_20m[df_20m.index >= cutoff - pd.Timedelta(days=2)]

    print("[INFO] детект RDRB")
    signals = detect_strategy_rdrb_signals(
        df_1d_f, df_12h_f, df_1h_f, df_2h_f, df_15m_f, df_20m_f, verbose=False,
    )
    print(f"  raw: {len(signals)}")

    # Симулируем все, считаем BTC daily momentum для каждого
    print("[INFO] симуляция + momentum")
    rows = []
    for s in signals:
        outcome = simulate_one(s, df_1m)
        if outcome == "skipped":
            continue
        sig_t = pd.Timestamp(s["signal_time"])
        if sig_t.tz is None:
            sig_t = sig_t.tz_localize("UTC")
        sign = 1 if s["direction"] == "LONG" else -1
        moms = {}
        for N in LOOKBACKS:
            m = daily_momentum(df_1d_btc, sig_t, N)
            moms[f"mom_{N}d"] = m
            # counter-trend = momentum AGAINST signal
            moms[f"counter_{N}d"] = (m == -sign)
            moms[f"follow_{N}d"] = (m == sign)
        rows.append({"outcome": outcome, "direction": s["direction"], **moms})
    print(f"  всего: {len(rows)}")

    print()
    print("=" * 100)
    print(f"{'lookback':>10} | {'COUNTER-trend (BTC mom против signal)':^36} | {'TREND-follow (BTC mom за signal)':^32}")
    print(f"{'':>10} | {'n':>4} {'closed':>6} {'WR':>6} {'PnL':>7} | {'n':>4} {'closed':>6} {'WR':>6} {'PnL':>7}")
    print("=" * 100)
    for N in LOOKBACKS:
        counter = [r for r in rows if r[f"counter_{N}d"]]
        follow = [r for r in rows if r[f"follow_{N}d"]]
        s_c = stats(counter)
        s_f = stats(follow)
        print(f"{N:>10}d | {s_c['n']:>4} {s_c['closed']:>6} {s_c['wr']:>5.1f}% {s_c['pnl']:>+6.1f}R "
              f"| {s_f['n']:>4} {s_f['closed']:>6} {s_f['wr']:>5.1f}% {s_f['pnl']:>+6.1f}R")

    # Baseline для сравнения
    print()
    s_all = stats(rows)
    print(f"BASELINE (без фильтра): n={s_all['n']} closed={s_all['closed']} "
          f"WR={s_all['wr']}% PnL={s_all['pnl']:+}R")

    # Counter-trend разделённый по direction
    print()
    print("Counter-trend разделённый по LONG/SHORT (lookback 7d):")
    for dirn in ["LONG", "SHORT"]:
        sub = [r for r in rows if r["direction"] == dirn and r["counter_7d"]]
        s = stats(sub)
        print(f"  {dirn}: n={s['n']:3d} closed={s['closed']:3d} WR={s['wr']:5.1f}% PnL={s['pnl']:+5.1f}R")


if __name__ == "__main__":
    main()
