"""Экспорт детальной CSV позиций 1.1.2 EXTENDED с финальным конфигом для ручной проверки.

Конфиг:
  - extended_macro_search = True
  - entry_pct = 0.70
  - sl_pct = 0.35 (между ob_htf edge и fvg edge)
  - RR = 1.8
  - no_entry = ON

Поля CSV (для каждой позиции):
  - signal_time, activation_time, exit_time (UTC+3)
  - direction, top_tf, ob_macro_tf, ob_htf_tf, fvg_tf
  - macro_age_class: OLD (cur < top.cur) / NEW (cur >= top.cur)
  - ob_d_top, ob_d_bottom, ob_d_time
  - ob_macro_top, ob_macro_bottom, ob_macro_time
  - ob_htf_top, ob_htf_bottom, ob_htf_time
  - fvg_top, fvg_bottom, fvg_time
  - entry, sl, tp, risk (price), risk_pct
  - outcome (win/loss/no_entry/not_filled/open)
  - hit_type, exit_price
  - mfe_pct, mae_pct, fill_delay_min
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_PCT = 0.70
SL_PCT = 0.35
RR_TARGET = 1.8


def to_utc3(ts) -> str:
    if ts is None or ts == "":
        return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def simulate_position(sig: dict, df_1m: pd.DataFrame) -> dict:
    """Симулирует одну позицию с финальным конфигом, возвращает все поля для CSV."""
    direction = sig["direction"]
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    fw = fvg_t - fvg_b

    if direction == "LONG":
        entry = fvg_b + ENTRY_PCT * fw
        sl = obh_b + SL_PCT * (fvg_b - obh_b)
        if sl >= entry:
            return None
        risk = entry - sl
        tp = entry + RR_TARGET * risk
    else:
        entry = fvg_t - ENTRY_PCT * fw
        sl = obh_t - SL_PCT * (obh_t - fvg_t)
        if sl <= entry:
            return None
        risk = sl - entry
        tp = entry - RR_TARGET * risk

    signal_time = sig["signal_time"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = signal_time + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]

    # No-entry check: TP price reached BEFORE entry-fill
    activation_time = None
    no_entry = False
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        # Check no_entry: TP reached before entry
        if direction == "LONG":
            if h >= tp and (activation_time is None):
                no_entry = True
                break
            if l <= entry:
                activation_time = ts
                break
        else:
            if l <= tp and (activation_time is None):
                no_entry = True
                break
            if h >= entry:
                activation_time = ts
                break

    macro_age_class = "OLD" if sig["ob_macro_cur_time"] < sig["ob_d_cur_time"] else "NEW"

    base_row = {
        "signal_time": to_utc3(signal_time),
        "direction": direction,
        "macro_age_class": macro_age_class,
        "top_tf": sig.get("top_tf", "1d"),
        "ob_d_time": to_utc3(sig["ob_d_cur_time"]),
        "ob_d_top": round(sig["ob_d_zone"][1], 2),
        "ob_d_bottom": round(sig["ob_d_zone"][0], 2),
        "ob_macro_tf": sig["ob_macro_tf"],
        "ob_macro_time": to_utc3(sig["ob_macro_cur_time"]),
        "ob_macro_top": round(sig["ob_macro_zone"][1], 2),
        "ob_macro_bottom": round(sig["ob_macro_zone"][0], 2),
        "ob_htf_tf": sig["ob_htf_tf"],
        "ob_htf_time": to_utc3(sig["ob_htf_cur_time"]),
        "ob_htf_top": round(sig["ob_htf_zone"][1], 2),
        "ob_htf_bottom": round(sig["ob_htf_zone"][0], 2),
        "fvg_tf": sig["fvg_tf"],
        "fvg_time": to_utc3(sig["fvg_c2_time"]),
        "fvg_top": round(fvg_t, 2),
        "fvg_bottom": round(fvg_b, 2),
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "risk_abs": round(risk, 2),
        "risk_pct": round(risk / entry * 100, 4),
        "rr_target": RR_TARGET,
    }

    if no_entry:
        return {**base_row,
                "outcome": "no_entry",
                "activation_time": "",
                "exit_time": "", "exit_price": "",
                "hit_type": "no_entry",
                "fill_delay_min": "",
                "mfe_pct": 0, "mae_pct": 0}

    if activation_time is None:
        return {**base_row,
                "outcome": "not_filled",
                "activation_time": "",
                "exit_time": "", "exit_price": "",
                "hit_type": "not_filled",
                "fill_delay_min": "",
                "mfe_pct": 0, "mae_pct": 0}

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
        "outcome": outcome,
        "activation_time": to_utc3(activation_time),
        "exit_time": to_utc3(exit_time) if exit_time else "",
        "exit_price": round(exit_price, 2) if exit_price is not None else "",
        "hit_type": hit_type or "open",
        "fill_delay_min": round(fill_delay_min, 2),
        "mfe_pct": round(mfe / entry * 100, 4),
        "mae_pct": round(mae / entry * 100, 4),
    }


def main():
    print(f"[INFO] Export 1.1.2 EXTENDED positions, entry={ENTRY_PCT}, sl={SL_PCT}, RR={RR_TARGET}")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    raw = detect_strategy_1_1_2_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        extended_macro_search=True, verbose=False,
    )
    print(f"  raw paths: {len(raw)}")

    # Dedup по (signal_time, direction, entry-as-rounded)
    groups = defaultdict(list)
    for s in raw:
        # NB: dedup ключ включает entry старого детектора (mid FVG, ОЛД), не наш custom entry.
        # Для ручной проверки CSV сделаем dedup по (signal_time, direction, fvg_top, fvg_bottom)
        key = (s["signal_time"], s["direction"], round(s["fvg_zone"][0], 4), round(s["fvg_zone"][1], 4))
        groups[key].append(s)
    deduped = [g[0] for g in groups.values()]
    print(f"  deduped (по signal_time + direction + fvg-zone): {len(deduped)}")

    rows = []
    skipped = 0
    for s in deduped:
        r = simulate_position(s, df_1m)
        if r is None:
            skipped += 1
            continue
        rows.append(r)

    df = pd.DataFrame(rows)
    # Сортируем по signal_time для удобства
    df["_sort"] = pd.to_datetime(df["signal_time"])
    df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
    df.insert(0, "n", range(1, len(df) + 1))

    out = Path("signals/positions_1_1_2_extended_final.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n  saved: {out}")
    print(f"  total positions: {len(df)} (skipped {skipped} с risk≤0)")

    # Краткая сводка
    print()
    print("=" * 80)
    print("Сводка:")
    print("=" * 80)
    counts = df["outcome"].value_counts().to_dict()
    print(f"  outcomes: {counts}")
    closed = df[df["outcome"].isin(["win", "loss"])]
    if len(closed):
        wins = (closed["outcome"] == "win").sum()
        losses = (closed["outcome"] == "loss").sum()
        wr = wins / (wins + losses) * 100
        pnl = wins * RR_TARGET - losses
        print(f"  closed: {wins+losses}  W={wins}  L={losses}  WR={wr:.1f}%  PnL={pnl:+.2f}R")

    # Распределение OLD/NEW macro
    print()
    print("Распределение по типу macro (OLD = до закрытия cur top-OB, NEW = после):")
    age_split = df["macro_age_class"].value_counts().to_dict()
    print(f"  {age_split}")
    for age in ["OLD", "NEW"]:
        sub = df[df["macro_age_class"] == age]
        sub_closed = sub[sub["outcome"].isin(["win", "loss"])]
        if len(sub_closed):
            w = (sub_closed["outcome"] == "win").sum()
            l = (sub_closed["outcome"] == "loss").sum()
            print(f"  {age}: total={len(sub)} closed={w+l} W={w} L={l} WR={w/(w+l)*100:.1f}% "
                  f"PnL={w*RR_TARGET-l:+.2f}R")


if __name__ == "__main__":
    main()
