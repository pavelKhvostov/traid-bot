"""Бэктест Strategy 1.1.7 на BTCUSDT — raw baseline (RR=1.0)."""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_7 import RR, detect_strategy_1_1_7_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
OUTPUT = Path("signals/backtest_strategy_1_1_7.csv")

ENTRY_TOLERANCE = 0.005
SL_TOLERANCE = 0.005


def to_utc3(ts) -> str:
    if ts is None or ts == "":
        return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def zone_str(zone: tuple[float, float]) -> str:
    b, t = zone
    return f"{b}-{t}"


def simulate_outcome(sig: dict, df_1m: pd.DataFrame) -> dict:
    direction = sig["direction"]
    entry = sig["entry"]
    sl = sig["sl"]
    tp = sig["tp"]
    signal_time = sig["signal_time"]

    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = signal_time + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]

    activation_time: pd.Timestamp | None = None
    no_entry = False
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if h >= tp or l <= sl:
                if l <= entry:
                    activation_time = ts
                    break
                no_entry = True
                break
            if l <= entry:
                activation_time = ts
                break
        else:
            if l <= tp or h >= sl:
                if h >= entry:
                    activation_time = ts
                    break
                no_entry = True
                break
            if h >= entry:
                activation_time = ts
                break

    base_row = _make_base_row(sig)

    if no_entry:
        return {**base_row, "outcome": "NO_ENTRY", "fill_time": "",
                "exit_time": "", "exit_price": "", "fill_delay_min": "",
                "hit_type": "no_entry", "mfe_pct": 0, "mae_pct": 0,
                "pnl_r": 0.0}

    if activation_time is None:
        return {**base_row, "outcome": "NOT_FILLED", "fill_time": "",
                "exit_time": "", "exit_price": "", "fill_delay_min": "",
                "hit_type": "not_filled", "mfe_pct": 0, "mae_pct": 0,
                "pnl_r": 0.0}

    fill_delay_min = (activation_time - signal_time).total_seconds() / 60
    sim = df_1m[df_1m.index >= activation_time]

    outcome = "OPEN"
    exit_time = None
    exit_price = None
    hit_type = "open"
    mfe = 0.0
    mae = 0.0

    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            mfe = max(mfe, h - entry)
            mae = max(mae, entry - l)
            if l <= sl:
                outcome, exit_time, exit_price, hit_type = "LOSS", ts, sl, "sl"
                break
            if h >= tp:
                outcome, exit_time, exit_price, hit_type = "WIN", ts, tp, "tp"
                break
        else:
            mfe = max(mfe, entry - l)
            mae = max(mae, h - entry)
            if h >= sl:
                outcome, exit_time, exit_price, hit_type = "LOSS", ts, sl, "sl"
                break
            if l <= tp:
                outcome, exit_time, exit_price, hit_type = "WIN", ts, tp, "tp"
                break

    pnl = 1.0 if outcome == "WIN" else (-1.0 if outcome == "LOSS" else 0.0)

    return {
        **base_row,
        "fill_time": to_utc3(activation_time),
        "fill_delay_min": round(fill_delay_min, 2),
        "outcome": outcome,
        "exit_time": to_utc3(exit_time) if exit_time else "",
        "exit_price": exit_price if exit_price is not None else "",
        "hit_type": hit_type,
        "mfe_pct": round(mfe / entry * 100, 4),
        "mae_pct": round(mae / entry * 100, 4),
        "pnl_r": pnl,
    }


def _make_base_row(sig: dict) -> dict:
    risk = sig["risk"]
    entry = sig["entry"]
    return {
        "signal_time": sig["signal_time"],
        "direction": sig["direction"],
        "fractal_time": to_utc3(sig["fractal_time"]),
        "fractal_price": sig["fractal_price"],
        "sweep_time": to_utc3(sig["sweep_time"]),
        "poi_zone": zone_str(sig["poi_zone"]),
        "confirmation_close": to_utc3(sig["confirmation_close"]),
        "invalidation_time": to_utc3(sig["invalidation_time"]) if sig["invalidation_time"] else "",
        "ob_tf": sig["ob_tf"],
        "ob_cur_time": to_utc3(sig["ob_cur_time"]),
        "ob_zone": zone_str(sig["ob_zone"]),
        "fvg_tf": sig["fvg_tf"],
        "fvg_c2_time": to_utc3(sig["fvg_c2_time"]),
        "fvg_zone": zone_str(sig["fvg_zone"]),
        "entry": entry,
        "sl": sig["sl"],
        "tp": sig["tp"],
        "risk": risk,
        "risk_pct": round(risk / entry * 100, 4),
    }


def dedupe_signals(rows: list[dict]) -> list[dict]:
    """Двухэтапный bucketing (entry 0.5%, SL 0.5%). Аналог 1.1.5/1.1.6."""
    must_match = ["outcome", "fill_time"]

    primary_groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["signal_time"], row["direction"])
        primary_groups.setdefault(key, []).append(row)

    primary_buckets: list[list[dict]] = []
    for _key, group in primary_groups.items():
        sorted_by_entry = sorted(group, key=lambda r: float(r["entry"]))
        cur: list[dict] = []
        cur_first_entry: float | None = None
        for r in sorted_by_entry:
            entry = float(r["entry"])
            if cur_first_entry is None:
                cur = [r]
                cur_first_entry = entry
                continue
            if abs(entry - cur_first_entry) / cur_first_entry < ENTRY_TOLERANCE:
                cur.append(r)
            else:
                primary_buckets.append(cur)
                cur = [r]
                cur_first_entry = entry
        if cur:
            primary_buckets.append(cur)

    final_buckets: list[list[dict]] = []
    for primary in primary_buckets:
        entry_first = float(primary[0]["entry"])
        sorted_by_sl = sorted(primary, key=lambda r: float(r["sl"]))
        cur: list[dict] = []
        cur_first_sl: float | None = None
        cur_outcome: str | None = None
        for r in sorted_by_sl:
            sl = float(r["sl"])
            outc = r["outcome"]
            if cur_first_sl is None:
                cur = [r]
                cur_first_sl = sl
                cur_outcome = outc
                continue
            close_sl = abs(sl - cur_first_sl) / entry_first < SL_TOLERANCE
            same_outcome = outc == cur_outcome
            if close_sl and same_outcome:
                cur.append(r)
            else:
                final_buckets.append(cur)
                cur = [r]
                cur_first_sl = sl
                cur_outcome = outc
        if cur:
            final_buckets.append(cur)

    out: list[dict] = []
    for group in final_buckets:
        first = group[0]
        for r in group[1:]:
            for f in must_match:
                if r.get(f) != first.get(f):
                    raise AssertionError(
                        f"dedupe mismatch signal_time={first['signal_time']} "
                        f"dir={first['direction']} entry={first['entry']} "
                        f"field={f!r}: {first.get(f)!r} vs {r.get(f)!r}"
                    )

        ob_tfs = sorted({r["ob_tf"] for r in group})
        fvg_tfs = sorted({r["fvg_tf"] for r in group})

        new = {
            "signal_time": first["signal_time"],
            "direction": first["direction"],
            "fractal_time": first["fractal_time"],
            "fractal_price": first["fractal_price"],
            "sweep_time": first["sweep_time"],
            "poi_zone": first["poi_zone"],
            "confirmation_close": first["confirmation_close"],
            "invalidation_time": first["invalidation_time"],
            "ob_tf": ",".join(ob_tfs),
            "ob_tf_count": len(ob_tfs),
            "ob_cur_time": first["ob_cur_time"],
            "ob_zone": first["ob_zone"],
            "fvg_tf": ",".join(fvg_tfs),
            "fvg_tf_count": len(fvg_tfs),
            "fvg_c2_time": first["fvg_c2_time"],
            "fvg_zone": first["fvg_zone"],
            "entry": first["entry"],
            "sl": first["sl"],
            "tp": first["tp"],
            "risk": first["risk"],
            "risk_pct": first["risk_pct"],
            "fill_time": first["fill_time"],
            "fill_delay_min": first["fill_delay_min"],
            "outcome": first["outcome"],
            "exit_time": first["exit_time"],
            "exit_price": first["exit_price"],
            "hit_type": first["hit_type"],
            "mfe_pct": first["mfe_pct"],
            "mae_pct": first["mae_pct"],
            "pnl_r": first["pnl_r"],
        }
        out.append(new)
    return out


def main():
    print(f"[INFO] Strategy 1.1.7 raw backtest, {SYMBOL}, окно {DAYS_BACK}d, RR={RR}\n")

    print("[INFO] загрузка данных")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_15m = load_df(SYMBOL, "15m")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_15m, "20m")
    df_1m = load_df(SYMBOL, "1m")
    print(f"  4h={len(df_4h)} 1h={len(df_1h)} 2h={len(df_2h)} "
          f"15m={len(df_15m)} 20m={len(df_20m)} 1m={len(df_1m)}")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_4h_f = df_4h[df_4h.index >= cutoff]
    print(f"  4h after cutoff ({cutoff.date()}): {len(df_4h_f)}\n")

    print("[INFO] детект сигналов")
    raw_signals = detect_strategy_1_1_7_signals(
        df_4h=df_4h_f, df_1h=df_1h, df_2h=df_2h,
        df_15m=df_15m, df_20m=df_20m, verbose=True,
    )
    print(f"  raw signals: {len(raw_signals)}")

    if not raw_signals:
        print("[WARN] ни одного сигнала")
        return

    print("\n[INFO] симуляция outcomes (RR=1)")
    rows = [simulate_outcome(s, df_1m) for s in raw_signals]
    print(f"  rows: {len(rows)}")

    deduped = dedupe_signals(rows)
    print(f"  deduped: {len(deduped)}  схлопнуто: {len(rows) - len(deduped)}")

    deduped.sort(key=lambda r: r["signal_time"])
    for r in deduped:
        r.pop("signal_time", None)

    df = pd.DataFrame(deduped)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT, index=False)
    print(f"  записано в {OUTPUT}: {len(df)} строк")

    closed = df[df["outcome"].isin(["WIN", "LOSS"])]
    no_entry = (df["outcome"] == "NO_ENTRY").sum()
    not_filled = (df["outcome"] == "NOT_FILLED").sum()
    open_n = (df["outcome"] == "OPEN").sum()
    W = int((closed["outcome"] == "WIN").sum())
    L = int((closed["outcome"] == "LOSS").sum())
    wr = W / (W + L) * 100 if (W + L) else 0.0
    total_pnl = df["pnl_r"].sum()
    r_per_trade = total_pnl / (W + L) if (W + L) else 0.0

    print()
    print("=" * 72)
    print(f"СВОДКА  Strategy 1.1.7  RR={RR}  окно={DAYS_BACK}d  {SYMBOL}")
    print("=" * 72)
    print(f"  raw       = {len(raw_signals)}")
    print(f"  deduped   = {len(df)}")
    print(f"  closed    = {W + L}  (W={W}  L={L})")
    print(f"  NO_ENTRY  = {no_entry}")
    print(f"  NOT_FILLED= {not_filled}")
    print(f"  OPEN      = {open_n}")
    print(f"  WR        = {wr:.1f}%")
    print(f"  total PnL = {total_pnl:+.1f}R")
    print(f"  R / trade = {r_per_trade:+.3f}")

    print("\nРаспределение ob_tf × fvg_tf:")
    if len(df) > 0:
        combos = (
            df.groupby(["ob_tf", "fvg_tf"]).size()
              .reset_index(name="n").sort_values("n", ascending=False)
        )
        print(combos.to_string(index=False))

    print("\nLONG vs SHORT:")
    for direction in ["LONG", "SHORT"]:
        sub = df[df["direction"] == direction]
        sub_closed = sub[sub["outcome"].isin(["WIN", "LOSS"])]
        sw = int((sub_closed["outcome"] == "WIN").sum())
        sl_n = int((sub_closed["outcome"] == "LOSS").sum())
        swr = sw / (sw + sl_n) * 100 if (sw + sl_n) else 0
        spnl = sub["pnl_r"].sum()
        print(f"  {direction}: total={len(sub)}  closed={sw + sl_n}  "
              f"WR={swr:.1f}%  PnL={spnl:+.1f}R")

    print("\nПо годам (closed):")
    if not closed.empty:
        c = closed.copy()
        c["t"] = pd.to_datetime(c["fvg_c2_time"])
        c["year"] = c["t"].dt.year
        for y in sorted(c["year"].unique()):
            sub = c[c["year"] == y]
            wy = int((sub["outcome"] == "WIN").sum())
            ly = int((sub["outcome"] == "LOSS").sum())
            wry = wy / (wy + ly) * 100 if (wy + ly) else 0
            pnl_y = wy * 1.0 - ly * 1.0
            print(f"  {y}: n={wy + ly}  W={wy}  L={ly}  "
                  f"WR={wry:.1f}%  PnL={pnl_y:+.1f}R")


if __name__ == "__main__":
    main()
