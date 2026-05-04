"""RDRB «конфетка» — стек фильтров найденных через анализ winners vs losers.

Фильтры (по убыванию importance):
  L1: fvg_pos in [0.5, 0.75)        — FVG в средней части OB-htf zone
  L2: triple confluence (1d)       — BTC/TOTALES/USDT.D mom 1d AGREES
  L3: hour_utc in [8, 12)           — London open

Показываем incremental impact для каждой комбинации фильтров.

Параметры trade'а: entry=0.95, sl=0.35, RR=2.2.
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

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_rdrb import detect_strategy_rdrb_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR = 2.2
ENTRY_PCT = 0.95
SL_PCT = 0.35


def daily_momentum(df, ts, lookback):
    if df.empty: return 0
    day = ts.normalize()
    prev = day - pd.Timedelta(days=lookback)
    n = df[df.index <= day]; p = df[df.index <= prev]
    if n.empty or p.empty: return 0
    delta = float(n["close"].iloc[-1]) - float(p["close"].iloc[-1])
    return 1 if delta > 0 else (-1 if delta < 0 else 0)


def simulate_one(sig, df_1m):
    direction = sig["direction"]
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    rdrb_b, rdrb_t = sig["rdrb_zone"]
    if direction == "LONG":
        entry = fvg_b + ENTRY_PCT * (fvg_t - fvg_b)
        sl = obh_b + SL_PCT * (rdrb_b - obh_b)
        if sl >= entry: return "skipped"
        risk = entry - sl
        tp = entry + risk * RR
    else:
        entry = fvg_t - ENTRY_PCT * (fvg_t - fvg_b)
        sl = obh_t + SL_PCT * (rdrb_t - obh_t)
        if sl <= entry: return "skipped"
        risk = sl - entry
        tp = entry - risk * RR
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    activation = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= entry: activation = ts; break
        else:
            if h >= entry: activation = ts; break
    if activation is None: return "not_filled"
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
    pnl = wins * rr - losses
    rpt = pnl / nc if nc else 0
    return {"n": n, "closed": nc, "wins": wins, "losses": losses,
            "wr": round(wr, 1), "pnl": round(pnl, 1),
            "r_per_trade": round(rpt, 3)}


def main():
    print(f"[INFO] RDRB «конфетка» filter stack, RR={RR}, entry={ENTRY_PCT}, sl={SL_PCT}")
    print()

    print("[INFO] загрузка")
    df_btc_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    df_tot = load_df("TOTALES", "1d")
    df_usd = load_df("USDT_D", "1d")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_btc_1d[df_btc_1d.index >= cutoff - pd.Timedelta(days=5)]
    df_12h_f = df_12h[df_12h.index >= cutoff - pd.Timedelta(days=5)]
    df_1h_f = df_1h[df_1h.index >= cutoff - pd.Timedelta(days=2)]
    df_2h_f = df_2h[df_2h.index >= cutoff - pd.Timedelta(days=2)]
    df_15m_f = df_15m[df_15m.index >= cutoff - pd.Timedelta(days=2)]
    df_20m_f = df_20m[df_20m.index >= cutoff - pd.Timedelta(days=2)]

    print("[INFO] детект + симуляция + features")
    signals = detect_strategy_rdrb_signals(
        df_1d_f, df_12h_f, df_1h_f, df_2h_f, df_15m_f, df_20m_f, verbose=False,
    )
    rows = []
    for s in signals:
        outcome = simulate_one(s, df_1m)
        if outcome == "skipped":
            continue
        sig_t = pd.Timestamp(s["signal_time"])
        if sig_t.tz is None:
            sig_t = sig_t.tz_localize("UTC")
        sign = 1 if s["direction"] == "LONG" else -1
        # fvg_pos
        fvg_b, fvg_t = s["fvg_zone"]
        obh_b, obh_t = s["ob_htf_zone"]
        obh_w = obh_t - obh_b
        if s["direction"] == "LONG":
            fvg_pos = (fvg_t - obh_b) / obh_w if obh_w else 0
        else:
            fvg_pos = (obh_t - fvg_b) / obh_w if obh_w else 0
        # confluence
        tot_mom = daily_momentum(df_tot, sig_t, 1)
        usd_mom = daily_momentum(df_usd, sig_t, 1)
        triple = (tot_mom == sign) and (usd_mom == -sign)
        rows.append({
            "outcome": outcome,
            "direction": s["direction"],
            "fvg_pos": round(fvg_pos, 3),
            "triple": triple,
            "hour_utc": sig_t.hour,
        })
    print(f"  total: {len(rows)}")

    # Filter combinations
    L1 = lambda r: 0.5 <= r["fvg_pos"] < 0.75
    L2 = lambda r: r["triple"]
    L3 = lambda r: 8 <= r["hour_utc"] < 12

    combinations = [
        ("Baseline (no filter)",                 lambda r: True),
        ("L1: fvg_pos in [0.5, 0.75)",            L1),
        ("L2: triple confluence (1d)",           L2),
        ("L3: hour in [8, 12) UTC",               L3),
        ("L1 + L2",                              lambda r: L1(r) and L2(r)),
        ("L1 + L3",                              lambda r: L1(r) and L3(r)),
        ("L2 + L3",                              lambda r: L2(r) and L3(r)),
        ("L1 + L2 + L3 (full stack)",            lambda r: L1(r) and L2(r) and L3(r)),
        ("L1 OR L2 (или один из двух)",          lambda r: L1(r) or L2(r)),
    ]

    print()
    print("=" * 100)
    print(f"{'Filter':<40} | {'n':>4} {'closed':>6} {'WR':>6} {'PnL':>8} {'R/trade':>8}")
    print("=" * 100)
    for label, predicate in combinations:
        sub = [r for r in rows if predicate(r)]
        s = stats(sub)
        print(f"{label:<40} | {s['n']:>4} {s['closed']:>6} {s['wr']:>5.1f}% "
              f"{s['pnl']:>+7.1f}R {s['r_per_trade']:>+7.3f}")

    # Подробный разбор лучшего
    print()
    print("=" * 100)
    print("L1+L2 (best — fvg_pos middle + 1d confluence) — детально:")
    print("=" * 100)
    sub = [r for r in rows if L1(r) and L2(r)]
    print(f"  Total: {len(sub)}")
    for dirn in ["LONG", "SHORT"]:
        s = stats([r for r in sub if r["direction"] == dirn])
        print(f"  {dirn}: n={s['n']:3d} closed={s['closed']:3d} WR={s['wr']:5.1f}% PnL={s['pnl']:+5.1f}R")


if __name__ == "__main__":
    main()
