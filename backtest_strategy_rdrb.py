"""Бэктест Strategy RDRB на BTCUSDT.

Структура — копия backtest_strategy_1_1_1.py, изменены:
- Detector -> detect_strategy_rdrb_signals.
- CSV-колонки: rdrb_tf / rdrb_anchor_time / rdrb_trigger_time / rdrb_top/bottom
  вместо top_tf / ob_d_time / fvg_macro_*.
- Dedup ключ — (signal_time, direction, entry) с bucketing по SL (как в 1.1.1).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_rdrb import detect_strategy_rdrb_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR_RUNS = [
    (1.0, Path("signals/strategy_rdrb_3y_RR1.csv")),
    (2.2, Path("signals/strategy_rdrb_3y_RR2.2.csv")),
]
SL_TOLERANCE = 0.005


def to_utc3(ts) -> str:
    if ts is None or ts == "":
        return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def simulate_outcome(sig: dict, df_1m: pd.DataFrame, rr_ratio: float) -> dict:
    direction = sig["direction"]
    entry = sig["entry"]
    sl = sig["sl"]
    risk = sig["risk"]
    signal_time = sig["signal_time"]

    if direction == "LONG":
        tp = entry + risk * rr_ratio
    else:
        tp = entry - risk * rr_ratio

    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = signal_time + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]

    activation_time: pd.Timestamp | None = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= entry:
                activation_time = ts
                break
        else:
            if h >= entry:
                activation_time = ts
                break

    base_row = {
        "signal_time": signal_time,
        "rdrb_tf": sig["rdrb_tf"],
        "rdrb_anchor_time": to_utc3(sig["rdrb_anchor_time"]),
        "rdrb_trigger_time": to_utc3(sig["rdrb_trigger_time"]),
        "ob_htf_time": to_utc3(sig["ob_htf_cur_time"]),
        "ob_htf_tf": sig["ob_htf_tf"],
        "fvg_time": to_utc3(sig["fvg_c2_time"]),
        "fvg_tf": sig["fvg_tf"],
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "risk_pct": round(risk / entry * 100, 4),
        "rdrb_top": sig["rdrb_zone"][1],
        "rdrb_bottom": sig["rdrb_zone"][0],
        "ob_htf_top": sig["ob_htf_zone"][1],
        "ob_htf_bottom": sig["ob_htf_zone"][0],
        "fvg_top": sig["fvg_zone"][1],
        "fvg_bottom": sig["fvg_zone"][0],
    }

    if activation_time is None:
        return {**base_row, "outcome": "not_filled", "activation_time": "",
                "exit_time": "", "exit_price": "", "fill_delay_min": "",
                "hit_type": "not_filled", "mfe_pct": 0, "mae_pct": 0}

    fill_delay_min = (activation_time - signal_time).total_seconds() / 60
    sim = df_1m[df_1m.index >= activation_time]

    outcome = "open"
    exit_time = None
    exit_price = None
    hit_type = None
    mfe = 0.0
    mae = 0.0

    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            mfe = max(mfe, h - entry)
            mae = max(mae, entry - l)
            if l <= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"
                break
            if h >= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"
                break
        else:
            mfe = max(mfe, entry - l)
            mae = max(mae, h - entry)
            if h >= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"
                break
            if l <= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"
                break

    return {
        **base_row,
        "activation_time": to_utc3(activation_time),
        "fill_delay_min": round(fill_delay_min, 2),
        "outcome": outcome,
        "exit_time": to_utc3(exit_time) if exit_time else "",
        "exit_price": exit_price if exit_price is not None else "",
        "hit_type": hit_type or "open",
        "mfe_pct": round(mfe / entry * 100, 4),
        "mae_pct": round(mae / entry * 100, 4),
    }


def dedupe_signals(rows: list[dict]) -> list[dict]:
    """Тот же two-stage dedup что в 1.1.1: primary (signal_time, direction, entry) +
    bucketing по SL с tolerance 0.5% от entry. Outcome обязан совпадать в bucket'е.
    """
    must_match = ["outcome", "activation_time",
                  "fvg_time", "fvg_tf", "fvg_top", "fvg_bottom"]

    primary: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["signal_time"], row["direction"], round(float(row["entry"]), 8))
        primary.setdefault(key, []).append(row)

    result: list[dict] = []
    for key, group in primary.items():
        group.sort(key=lambda r: float(r["sl"]))
        buckets: list[list[dict]] = []
        cur_bucket: list[dict] = []
        cur_first_sl: float | None = None
        entry = float(group[0]["entry"])
        for r in group:
            sl = float(r["sl"])
            if cur_first_sl is None or abs(sl - cur_first_sl) / entry < SL_TOLERANCE:
                if cur_first_sl is None:
                    cur_first_sl = sl
                cur_bucket.append(r)
            else:
                buckets.append(cur_bucket)
                cur_bucket = [r]
                cur_first_sl = sl
        if cur_bucket:
            buckets.append(cur_bucket)

        for bucket in buckets:
            # Если outcomes/activation_time различаются внутри bucket'а — это
            # реально разные трейды (граничные случаи когда SL в пределах
            # 0.5% даёт win vs loss). Сплитим по outcome чтобы не терять.
            by_outcome: dict[str, list[dict]] = {}
            for b in bucket:
                by_outcome.setdefault(b["outcome"], []).append(b)

            for sub_bucket in by_outcome.values():
                base = sub_bucket[0]
                # Внутри одного outcome ещё проверяем activation_time/fvg_*
                for fld in [f for f in must_match if f != "outcome"]:
                    vals = {b.get(fld) for b in sub_bucket}
                    if len(vals) > 1:
                        # Не падаем — берём first и логируем
                        print(f"[WARN] dedup divergent {fld} in bucket key={key}: {vals}")

                rdrb_tfs = sorted({b["rdrb_tf"] for b in sub_bucket})
                htf_tfs = sorted({b["ob_htf_tf"] for b in sub_bucket})
                collapsed = dict(base)
                collapsed["rdrb_tf"] = ",".join(rdrb_tfs)
                collapsed["rdrb_tf_count"] = len(rdrb_tfs)
                collapsed["ob_htf_tf"] = ",".join(htf_tfs)
                collapsed["ob_htf_tf_count"] = len(htf_tfs)
                result.append(collapsed)

    # Сортируем по времени для удобства
    result.sort(key=lambda r: r["signal_time"])
    return result


def main():
    rrs = [r for r, _ in RR_RUNS]
    print(f"[INFO] Strategy RDRB backtest, {SYMBOL}, окно {DAYS_BACK}d, RR={rrs}")
    print()

    print("[INFO] загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    print(f"  1d={len(df_1d)} 12h={len(df_12h)} 1h={len(df_1h)} 2h={len(df_2h)} "
          f"15m={len(df_15m)} 20m={len(df_20m)} 1m={len(df_1m)}")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)

    df_1d_f = df_1d[df_1d.index >= cutoff - pd.Timedelta(days=5)]
    df_12h_f = df_12h[df_12h.index >= cutoff - pd.Timedelta(days=5)]
    df_1h_f = df_1h[df_1h.index >= cutoff - pd.Timedelta(days=2)]
    df_2h_f = df_2h[df_2h.index >= cutoff - pd.Timedelta(days=2)]
    df_15m_f = df_15m[df_15m.index >= cutoff - pd.Timedelta(days=2)]
    df_20m_f = df_20m[df_20m.index >= cutoff - pd.Timedelta(days=2)]

    print()
    print("[INFO] сбор сигналов (один раз — не зависит от RR)")
    signals = detect_strategy_rdrb_signals(
        df_1d_f, df_12h_f, df_1h_f, df_2h_f, df_15m_f, df_20m_f,
        verbose=True,
    )
    print(f"  signals raw: {len(signals)}")
    if not signals:
        print("[WARN] ни одного сигнала")
        return

    for rr_ratio, output_path in RR_RUNS:
        print()
        print(f"[INFO] симуляция RR={rr_ratio}")
        rows = [simulate_outcome(s, df_1m, rr_ratio) for s in signals]
        deduped = dedupe_signals(rows)
        df = pd.DataFrame(deduped)
        # Уберём signal_time (raw UTC) перед записью — в CSV есть UTC+3 версии.
        df = df.drop(columns=["signal_time"], errors="ignore")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"  raw: {len(rows)}  deduped: {len(deduped)}  записано -> {output_path}")

        closed = df[df["outcome"].isin(["win", "loss"])]
        nf = (df["outcome"] == "not_filled").sum()
        op = (df["outcome"] == "open").sum()
        W = int((closed["outcome"] == "win").sum())
        L = int((closed["outcome"] == "loss").sum())
        wr = W / (W + L) * 100 if (W + L) else 0.0
        pnl = W * rr_ratio - L

        print()
        print("=" * 60)
        print(f"СВОДКА  RR={rr_ratio}  окно={DAYS_BACK}d")
        print("=" * 60)
        print(f"  total={len(df)}  closed={W+L}  not_filled={nf}  open={op}")
        print(f"  W={W} L={L} WR={wr:.1f}%  PnL={pnl:+.1f}R")

        if not closed.empty:
            closed_y = closed.copy()
            closed_y["t"] = pd.to_datetime(closed_y["fvg_time"])
            closed_y["year"] = closed_y["t"].dt.year
            for y in sorted(closed_y["year"].unique()):
                sub = closed_y[closed_y["year"] == y]
                Wy = int((sub["outcome"] == "win").sum())
                Ly = int((sub["outcome"] == "loss").sum())
                wry = Wy / (Wy + Ly) * 100 if (Wy + Ly) else 0
                pnly = Wy * rr_ratio - Ly
                print(f"  {y}: n={Wy+Ly} WR={wry:.1f}% PnL={pnly:+.1f}R")

            print()
            d = closed.groupby("direction").agg(n=("outcome","size"))
            d["w"] = closed.groupby("direction")["outcome"].apply(lambda s: (s=="win").sum())
            d["l"] = d["n"] - d["w"]
            d["wr%"] = (d["w"]/d["n"]*100).round(1)
            d["pnl"] = d["w"]*rr_ratio - d["l"]
            print("По направлению:")
            print(d.to_string())


if __name__ == "__main__":
    main()
