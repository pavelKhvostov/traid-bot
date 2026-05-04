"""Бэктест Strategy 1.1.4 на BTCUSDT.

1.1.4 = 1.1.1 с заменой entry FVG-15m/20m на immediate FVG того же ТФ что и
OB-htf (1h или 2h, как в 1.1.3 v1).

Симуляция: limit-вход = середина FVG-htf. SL = OB_SL_DEPTH inside top-OB.
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

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_4 import detect_strategy_1_1_4_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR_RUNS = [
    (1.0, Path("signals/strategy_1_1_4_3y_RR1.csv")),
    (2.2, Path("signals/strategy_1_1_4_3y_RR2.2.csv")),
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

    # FVG того же ТФ что OB-htf: 1h -> 60min, 2h -> 120min
    tf_minutes = 60 if sig["fvg_tf"] == "1h" else 120
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
        "top_tf": sig.get("top_tf", "1d"),
        "ob_d_time": to_utc3(sig["ob_d_cur_time"]),
        "fvg_macro_time": to_utc3(sig["fvg_macro_c2_time"]),
        "fvg_macro_tf": sig["fvg_macro_tf"],
        "ob_htf_time": to_utc3(sig["ob_htf_cur_time"]),
        "ob_htf_tf": sig["ob_htf_tf"],
        "fvg_time": to_utc3(sig["fvg_c2_time"]),
        "fvg_tf": sig["fvg_tf"],
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
    must_match = [
        "outcome", "activation_time",
        "fvg_time", "fvg_tf", "fvg_top", "fvg_bottom",
    ]

    primary: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["signal_time"], row["direction"], round(float(row["entry"]), 8))
        primary.setdefault(key, []).append(row)

    buckets: list[list[dict]] = []
    for key, group in primary.items():
        sorted_group = sorted(group, key=lambda r: float(r["sl"]))
        entry = float(key[2])
        cur_bucket: list[dict] = []
        cur_first_sl: float | None = None
        cur_outcome: str | None = None
        for r in sorted_group:
            sl = float(r["sl"])
            outc = r["outcome"]
            if cur_first_sl is None:
                cur_bucket = [r]
                cur_first_sl = sl
                cur_outcome = outc
                continue
            close_sl = abs(sl - cur_first_sl) / entry < SL_TOLERANCE
            same_outcome = outc == cur_outcome
            if close_sl and same_outcome:
                cur_bucket.append(r)
            else:
                buckets.append(cur_bucket)
                cur_bucket = [r]
                cur_first_sl = sl
                cur_outcome = outc
        if cur_bucket:
            buckets.append(cur_bucket)

    out: list[dict] = []
    for group in buckets:
        first = group[0]
        for r in group[1:]:
            for f in must_match:
                if r.get(f) != first.get(f):
                    raise AssertionError(
                        f"dedupe mismatch in bucket signal_time={first['signal_time']} "
                        f"dir={first['direction']} entry={first['entry']} "
                        f"sl_range=[{group[0]['sl']}..{group[-1]['sl']}] "
                        f"field={f!r}: {first.get(f)!r} vs {r.get(f)!r}"
                    )

        macro_times = [r["fvg_macro_time"] for r in group]
        macro_tfs = sorted({r["fvg_macro_tf"] for r in group})
        htf_times = [r["ob_htf_time"] for r in group]
        htf_tfs = sorted({r["ob_htf_tf"] for r in group})
        top_tfs = sorted({r["top_tf"] for r in group})
        top_times = [r["ob_d_time"] for r in group]

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
    print(f"[INFO] Strategy 1.1.4 backtest, {SYMBOL}, окно {DAYS_BACK}d, RR={rrs}")
    print()

    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    print(f"  1d={len(df_1d)} 12h={len(df_12h)} 4h={len(df_4h)} 6h={len(df_6h)} "
          f"1h={len(df_1h)} 2h={len(df_2h)} 1m={len(df_1m)}")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    print()
    signals = detect_strategy_1_1_4_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, verbose=True,
    )
    print(f"  signals: {len(signals)}")
    if not signals:
        return

    for rr_ratio, output_path in RR_RUNS:
        print()
        print(f"[INFO] симуляция RR={rr_ratio}")
        rows = [simulate_outcome(s, df_1m, rr_ratio) for s in signals]
        deduped = dedupe_signals(rows)
        print(f"  raw: {len(rows)}  deduped: {len(deduped)}")

        for r in deduped:
            r.pop("signal_time", None)
        df = pd.DataFrame(deduped)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)

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
            cy = closed.copy()
            cy["t"] = pd.to_datetime(cy["fvg_time"])
            cy["year"] = cy["t"].dt.year
            for y in sorted(cy["year"].unique()):
                sub = cy[cy["year"] == y]
                Wy = int((sub["outcome"] == "win").sum())
                Ly = int((sub["outcome"] == "loss").sum())
                wry = Wy / (Wy + Ly) * 100 if (Wy + Ly) else 0
                pnly = Wy * rr_ratio - Ly
                print(f"  {y}: n={Wy+Ly} WR={wry:.1f}% PnL={pnly:+.1f}R")

            d = closed.groupby("direction").agg(n=("outcome", "size"))
            d["w"] = closed.groupby("direction")["outcome"].apply(lambda s: (s == "win").sum())
            d["l"] = d["n"] - d["w"]
            d["wr%"] = (d["w"] / d["n"] * 100).round(1)
            d["pnl"] = d["w"] * rr_ratio - d["l"]
            print()
            print("По направлению:")
            print(d.to_string())


if __name__ == "__main__":
    main()
