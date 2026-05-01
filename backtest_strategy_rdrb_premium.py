"""RDRB Premium = базовая RDRB + L0-фильтр Daily OB.

Идея: RDRB-зона должна пересекаться с **активной** 1d OB того же направления.
Активная = OB сформирована до RDRB triger И НЕ инвалидирована 1d-close'ом
(LONG: ни одна 1d не закрылась < ob.bottom; SHORT: > ob.top).

Lookback для поиска OB-D: последние 30 дней до RDRB trigger.

Параметры (best from grid search RR=2.2):
  entry_pct = 0.95   (entry почти у FVG-15m края, ближнего к рынку)
  sl_pct    = 0.35   (35% от ob_htf к rdrb границе — wider SL)
  RR        = 2.2

Сравнение со стандартным RDRB (без L0):
  RDRB plain:    124 closed, WR 40.3%, +36R baseline / +47.6R triple confluence
  RDRB Premium:  ?

На каждом запуске печатается incremental impact фильтра.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, zones_overlap
from strategies.strategy_rdrb import detect_strategy_rdrb_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR = 2.2
ENTRY_PCT = 0.95
SL_PCT = 0.35
OB_D_LOOKBACK_DAYS = 30
OUTPUT_PATH = Path("signals/strategy_rdrb_premium_3y_RR2.2.csv")
LOOKBACK_DAYS_LIST = [1, 3, 7]


def find_active_1d_ob(df_1d: pd.DataFrame, rdrb_direction: str,
                      rdrb_zone: tuple, rdrb_trigger: pd.Timestamp) -> dict | None:
    """Активная 1d OB того же направления что RDRB, перекрывающая RDRB зону.

    Перебираем 1d свечи в последних OB_D_LOOKBACK_DAYS до trigger'а RDRB.
    OB активна если ни одна 1d-свеча между OB cur+1d и RDRB trigger не
    закрылась за пределами OB зоны (LONG: close < bottom / SHORT: close > top).
    """
    cutoff = rdrb_trigger - pd.Timedelta(days=OB_D_LOOKBACK_DAYS)
    df_window = df_1d[(df_1d.index >= cutoff) & (df_1d.index < rdrb_trigger)]
    rdrb_b, rdrb_t = rdrb_zone

    for idx in range(1, len(df_window)):
        ob = detect_ob_pair(df_window, idx)
        if ob is None or ob.direction != rdrb_direction:
            continue
        if not zones_overlap(ob.bottom, ob.top, rdrb_b, rdrb_t):
            continue

        # Invalidation check
        check_start = ob.cur_time + pd.Timedelta(days=1)
        df_chk = df_1d[(df_1d.index >= check_start) & (df_1d.index < rdrb_trigger)]
        invalidated = False
        for _, row in df_chk.iterrows():
            cl = float(row["close"])
            if rdrb_direction == "LONG" and cl < ob.bottom:
                invalidated = True
                break
            if rdrb_direction == "SHORT" and cl > ob.top:
                invalidated = True
                break
        if invalidated:
            continue
        return {"prev_time": ob.prev_time, "cur_time": ob.cur_time,
                "bottom": ob.bottom, "top": ob.top}
    return None


def daily_momentum(df: pd.DataFrame, ts: pd.Timestamp, lookback: int) -> int:
    if df.empty:
        return 0
    day = ts.normalize()
    prev_day = day - pd.Timedelta(days=lookback)
    n = df[df.index <= day]
    p = df[df.index <= prev_day]
    if n.empty or p.empty:
        return 0
    delta = float(n["close"].iloc[-1]) - float(p["close"].iloc[-1])
    return 1 if delta > 0 else (-1 if delta < 0 else 0)


def simulate_with_params(sig: dict, df_1m: pd.DataFrame, entry_pct: float,
                         sl_pct: float, rr: float) -> dict:
    """Симуляция с переопределёнными entry/SL для RDRB Premium."""
    direction = sig["direction"]
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    rdrb_b, rdrb_t = sig["rdrb_zone"]

    if direction == "LONG":
        entry = fvg_b + entry_pct * (fvg_t - fvg_b)
        sl = obh_b + sl_pct * (rdrb_b - obh_b)
        if sl >= entry:
            return {"outcome": "skipped"}
        risk = entry - sl
        tp = entry + risk * rr
    else:
        entry = fvg_t - entry_pct * (fvg_t - fvg_b)
        sl = obh_t + sl_pct * (rdrb_t - obh_t)
        if sl <= entry:
            return {"outcome": "skipped"}
        risk = sl - entry
        tp = entry - risk * rr

    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]

    activation_time = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= entry:
                activation_time = ts; break
        else:
            if h >= entry:
                activation_time = ts; break

    if activation_time is None:
        return {"outcome": "not_filled", "entry": entry, "sl": sl, "tp": tp}

    sim = df_1m[df_1m.index >= activation_time]
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= sl:
                return {"outcome": "loss", "entry": entry, "sl": sl, "tp": tp}
            if h >= tp:
                return {"outcome": "win", "entry": entry, "sl": sl, "tp": tp}
        else:
            if h >= sl:
                return {"outcome": "loss", "entry": entry, "sl": sl, "tp": tp}
            if l <= tp:
                return {"outcome": "win", "entry": entry, "sl": sl, "tp": tp}
    return {"outcome": "open", "entry": entry, "sl": sl, "tp": tp}


def stats(rows: list[dict], rr: float) -> dict:
    closed = [r for r in rows if r.get("outcome") in ("win", "loss")]
    n = len(rows)
    nc = len(closed)
    wins = sum(1 for r in closed if r["outcome"] == "win")
    losses = nc - wins
    wr = wins / nc * 100 if nc else 0.0
    return {
        "total": n, "closed": nc, "wins": wins, "losses": losses,
        "wr_pct": round(wr, 1), "pnl": round(wins * rr - losses, 1),
    }


def main() -> None:
    print(f"[INFO] RDRB Premium @ RR={RR}, entry_pct={ENTRY_PCT}, sl_pct={SL_PCT}")
    print(f"[INFO] L0 фильтр: Daily OB lookback={OB_D_LOOKBACK_DAYS}d")
    print()

    print("[INFO] загрузка")
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")

    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff - pd.Timedelta(days=5)]
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

    # Применяем L0 — Daily OB filter
    print()
    print("[INFO] L0 фильтр Daily OB")
    passed = []
    skipped_no_ob = 0
    for s in signals:
        ob_d = find_active_1d_ob(df_1d, s["direction"], s["rdrb_zone"], s["rdrb_trigger_time"])
        if ob_d is None:
            skipped_no_ob += 1
            continue
        s = dict(s)
        s["ob_d"] = ob_d
        passed.append(s)
    print(f"  prошли: {len(passed)}  отсеяны: {skipped_no_ob}")
    print(f"  retention: {len(passed) / len(signals) * 100:.1f}%")

    # Симуляция с oprimal entry/SL
    print()
    print(f"[INFO] симуляция (entry={ENTRY_PCT}, sl={SL_PCT}, RR={RR})")
    rows = []
    for s in passed:
        out = simulate_with_params(s, df_1m, ENTRY_PCT, SL_PCT, RR)
        if out["outcome"] == "skipped":
            continue
        # Confluence
        sign = 1 if s["direction"] == "LONG" else -1
        df_tot = load_df("TOTALES", "1d")
        df_usd = load_df("USDT_D", "1d")
        sig_t = pd.Timestamp(s["signal_time"])
        if sig_t.tz is None:
            sig_t = sig_t.tz_localize("UTC")
        rec = {
            "signal_time": sig_t.isoformat(),
            "direction": s["direction"],
            "outcome": out["outcome"],
            "rdrb_tf": s["rdrb_tf"],
            "ob_htf_tf": s["ob_htf_tf"],
            "fvg_tf": s["fvg_tf"],
            "entry": out["entry"], "sl": out["sl"], "tp": out["tp"],
            "rdrb_zone": s["rdrb_zone"],
            "ob_d_zone": (s["ob_d"]["bottom"], s["ob_d"]["top"]),
        }
        # Cache momentum (можно один раз вне цикла, но для краткости здесь)
        for N in LOOKBACK_DAYS_LIST:
            tot = daily_momentum(df_tot, sig_t, N)
            usd = daily_momentum(df_usd, sig_t, N)
            rec[f"triple_{N}d"] = (tot == sign) and (usd == -sign)
        rows.append(rec)

    df = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"  записано: {len(rows)} строк -> {OUTPUT_PATH}")

    # Сводка
    print()
    print("=" * 90)
    print(f"СВОДКА RDRB Premium (с L0 Daily OB filter), RR={RR}")
    print("=" * 90)
    s_all = stats(rows, RR)
    print(f"Baseline:  total={s_all['total']:3d} closed={s_all['closed']:3d}  "
          f"WR={s_all['wr_pct']:5.1f}%  PnL={s_all['pnl']:+6.1f}R")

    # Confluence breakdown
    for N in LOOKBACK_DAYS_LIST:
        triple = [r for r in rows if r.get(f"triple_{N}d")]
        no_sync_filter = [r for r in rows if not r.get(f"triple_{N}d")]
        s_tr = stats(triple, RR)
        s_no = stats(no_sync_filter, RR)
        print(f"\nLookback {N}d:")
        print(f"  Triple:  n={s_tr['total']:3d} closed={s_tr['closed']:3d} "
              f"WR={s_tr['wr_pct']:5.1f}% PnL={s_tr['pnl']:+6.1f}R")
        print(f"  No-sync: n={s_no['total']:3d} closed={s_no['closed']:3d} "
              f"WR={s_no['wr_pct']:5.1f}% PnL={s_no['pnl']:+6.1f}R")

    # По годам
    print()
    print("По годам (baseline):")
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    if closed:
        df_c = pd.DataFrame(closed)
        df_c["t"] = pd.to_datetime(df_c["signal_time"])
        df_c["year"] = df_c["t"].dt.year
        for y in sorted(df_c["year"].unique()):
            sub = df_c[df_c["year"] == y].to_dict("records")
            s = stats(sub, RR)
            print(f"  {y}: n={s['closed']:3d} WR={s['wr_pct']:5.1f}% PnL={s['pnl']:+5.1f}R")


if __name__ == "__main__":
    main()
