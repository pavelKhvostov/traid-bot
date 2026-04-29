"""Бэктест Strategy 1.1.1 на BTCUSDT.

Логика:
  - Сбор сигналов через strategies.strategy_1_1_1.detect_strategy_1_1_1_signals
  - Симуляция: limit-вход = середина FVG-15m. Ждём fill на 1m (price касается entry).
    Потом SL/TP на 1m. SL = край OB-D. RR=1.0.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095  # 3 года
SYMBOL = "BTCUSDT"
RR_RUNS = [
    (1.0, Path("signals/strategy_1_1_1_3y_RR1.csv")),
    (2.2, Path("signals/strategy_1_1_1_3y_RR2.2.csv")),
]


def to_utc3(ts) -> str:
    """UTC timestamp -> 'YYYY-MM-DD HH:MM' в UTC+3 (Москва)."""
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

    # Активация: с момента close c2 свечи entry-FVG.
    # signal_time — open_time свечи c2; close = open + tf_minutes.
    # Хардкод +15min ломал 20m FVG (5-мин look-ahead, см.
    # strategy-1-1-1-look-ahead-15min-vs-tf_duration.md).
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
        # signal_time (raw UTC) — для dedup-ключа. Из CSV убирается перед записью.
        "signal_time": signal_time,
        # Top-уровень: 1d или 12h (параллельные top-OB ветки).
        "top_tf": sig.get("top_tf", "1d"),
        # Ключевые времена (UTC+3): когда сформирована соответствующая зона.
        # ob_d_time — cur_time top-OB (1d или 12h), legacy-имя сохранено.
        "ob_d_time": to_utc3(sig["ob_d_cur_time"]),
        "fvg_macro_time": to_utc3(sig["fvg_macro_c2_time"]),
        "fvg_macro_tf": sig["fvg_macro_tf"],  # 4h или 6h
        "ob_htf_time": to_utc3(sig["ob_htf_cur_time"]),
        "ob_htf_tf": sig["ob_htf_tf"],  # 1h или 2h (что сработало раньше)
        "fvg_time": to_utc3(sig["fvg_c2_time"]),
        "fvg_tf": sig["fvg_tf"],  # 15m или 20m (что сработало раньше)
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "risk_pct": round(risk / entry * 100, 4),
        "ob_d_bottom": sig["ob_d_zone"][0],
        "ob_d_top": sig["ob_d_zone"][1],
        "fvg_macro_top": sig["fvg_macro_zone"][1],
        "fvg_macro_bottom": sig["fvg_macro_zone"][0],
        "intersection_top": sig["intersection_zone"][1],
        "intersection_bottom": sig["intersection_zone"][0],
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
    """Группировка по (signal_time, direction, round(entry, 8), round(sl, 8)).

    На одну (confirm-свеча, направление, цена входа, SL) — одна строка CSV.
    Метаданные о параллельных macro/htf путях схлопываются в *_count и
    *_tf через запятую. Разные SL на одной entry = разные трейды (разный
    risk/TP), остаются как разные строки. См.
    strategy-1-1-1-разные-sl-на-одном-entry.md.
    """
    must_match = [
        "entry", "sl", "tp", "risk_pct",
        "outcome", "activation_time", "exit_time", "exit_price",
        "hit_type", "mfe_pct", "mae_pct", "fill_delay_min",
        "fvg_time", "fvg_tf",
        "fvg_top", "fvg_bottom",
    ]

    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (
            row["signal_time"],
            row["direction"],
            round(float(row["entry"]), 8),
            round(float(row["sl"]), 8),
        )
        groups.setdefault(key, []).append(row)

    out: list[dict] = []
    for key, group in groups.items():
        first = group[0]
        # Assert одинаковости outcome-определяющих полей
        for r in group[1:]:
            for f in must_match:
                if r.get(f) != first.get(f):
                    raise AssertionError(
                        f"dedupe mismatch on key={key} field={f!r}: "
                        f"{first.get(f)!r} vs {r.get(f)!r}"
                    )

        macro_times = [r["fvg_macro_time"] for r in group]
        macro_tfs = sorted({r["fvg_macro_tf"] for r in group})
        htf_times = [r["ob_htf_time"] for r in group]
        htf_tfs = sorted({r["ob_htf_tf"] for r in group})
        top_tfs = sorted({r["top_tf"] for r in group})
        top_times = [r["ob_d_time"] for r in group]

        # Реконструируем строку с явным порядком полей: count после tf.
        new = {
            "signal_time": first["signal_time"],
            "top_tf": ",".join(top_tfs),
            "top_tf_count": len(top_tfs),
            "ob_d_time": min(top_times),
            "fvg_macro_time": min(macro_times),
            "fvg_macro_tf": ",".join(macro_tfs),
            "fvg_macro_count": len({t for t in macro_times}),
            "ob_htf_time": min(htf_times),
            "ob_htf_tf": ",".join(htf_tfs),
            "ob_htf_count": len({t for t in htf_times}),
            "fvg_time": first["fvg_time"],
            "fvg_tf": first["fvg_tf"],
            "direction": first["direction"],
            "entry": first["entry"],
            "sl": first["sl"],
            "tp": first["tp"],
            "risk_pct": first["risk_pct"],
            "ob_d_bottom": first["ob_d_bottom"],
            "ob_d_top": first["ob_d_top"],
            "fvg_macro_top": first["fvg_macro_top"],
            "fvg_macro_bottom": first["fvg_macro_bottom"],
            "intersection_top": first["intersection_top"],
            "intersection_bottom": first["intersection_bottom"],
            "ob_htf_top": first["ob_htf_top"],
            "ob_htf_bottom": first["ob_htf_bottom"],
            "fvg_top": first["fvg_top"],
            "fvg_bottom": first["fvg_bottom"],
            "activation_time": first["activation_time"],
            "fill_delay_min": first["fill_delay_min"],
            "outcome": first["outcome"],
            "exit_time": first["exit_time"],
            "exit_price": first["exit_price"],
            "hit_type": first["hit_type"],
            "mfe_pct": first["mfe_pct"],
            "mae_pct": first["mae_pct"],
        }
        out.append(new)
    return out


def main():
    rrs = [r for r, _ in RR_RUNS]
    print(f"[INFO] Strategy 1.1.1 backtest, {SYMBOL}, окно {DAYS_BACK}d, RR={rrs}")
    print()

    print("[INFO] загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")  # 6h из 1h, выравнено по эпохе (00,06,12,18 UTC)
    df_2h = compose_from_base(df_1h, "2h")  # 2h из 1h, выравнено по эпохе (00:00, 02:00...)
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")  # ресемпл 1m -> 20m, выравнено по эпохе
    print(f"  1d={len(df_1d)} 12h={len(df_12h)} 4h={len(df_4h)} 6h={len(df_6h)} "
          f"1h={len(df_1h)} 2h={len(df_2h)} "
          f"15m={len(df_15m)} 20m={len(df_20m)} 1m={len(df_1m)}")

    # Ограничить df_1d и df_12h последними DAYS_BACK
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_filtered = df_1d[df_1d.index >= cutoff]
    df_12h_filtered = df_12h[df_12h.index >= cutoff]
    print(f"  after cutoff ({cutoff.date()}): "
          f"1d={len(df_1d_filtered)}  12h={len(df_12h_filtered)}")

    print()
    print("[INFO] сбор сигналов (один раз — не зависит от RR)")
    signals = detect_strategy_1_1_1_signals(
        df_1d_filtered, df_12h_filtered,
        df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=True,
    )
    print(f"  signals: {len(signals)}")

    if not signals:
        print("[WARN] ни одного сигнала")
        return

    # Симуляция отдельно для каждого RR — отдельный CSV.
    for rr_ratio, output_path in RR_RUNS:
        print()
        print(f"[INFO] симуляция RR={rr_ratio}")
        rows = [simulate_outcome(s, df_1m, rr_ratio) for s in signals]
        deduped = dedupe_signals(rows)
        n_groups_multi = sum(
            1 for r in deduped
            if r["fvg_macro_count"] > 1 or r["ob_htf_count"] > 1
        )
        print(f"  raw: {len(rows)}  deduped: {len(deduped)}  "
              f"схлопнуто: {len(rows) - len(deduped)}  "
              f"групп с count>1: {n_groups_multi}")

        # signal_time нужен только для dedup-ключа — из CSV убираем.
        for r in deduped:
            r.pop("signal_time", None)

        df = pd.DataFrame(deduped)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"  записано в {output_path}: {len(deduped)} строк")

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
            # fvg_time = момент сигнала (UTC+3 'YYYY-MM-DD HH:MM').
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
