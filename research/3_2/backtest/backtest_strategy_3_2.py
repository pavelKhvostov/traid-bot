"""Бэктест Strategy 3.2 на BTCUSDT, RR=1.0.

Воронка: FVG-4h → first failed-touch (2 свечи rejection) → FVG-1h в 8h окне.
Entry/SL/TP/RR — определены в детекторе и юзером.

Активация (фолл entry-limit): с close c2 FVG-1h = signal_time + 1h.
"""
from __future__ import annotations


# --- repo-root injection ---
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
from strategies.strategy_3_2 import detect_strategy_3_2_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR = 1.0
OUTPUT_CSV = Path("signals/strategy_3_2_3y_RR1.csv")


def to_utc3(ts) -> str:
    if ts is None or ts == "":
        return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def simulate_outcome(sig: dict, df_1m: pd.DataFrame) -> dict:
    direction = sig["direction"]
    entry = sig["entry"]
    sl = sig["sl"]
    tp = sig["tp"]
    risk = sig["risk"]
    signal_time = sig["signal_time"]

    # Активация с close c2 1h FVG.
    fill_scan_start = signal_time + pd.Timedelta(minutes=60)
    forward = df_1m[df_1m.index >= fill_scan_start]

    activation_time = None
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

    base = {
        "signal_time": to_utc3(signal_time),
        "direction": direction,
        "fvg_4h_c2_time": to_utc3(sig["fvg_4h_c2_time"]),
        "fvg_4h_bottom": sig["fvg_4h_zone"][0],
        "fvg_4h_top": sig["fvg_4h_zone"][1],
        "touch_time": to_utc3(sig["touch_time"]),
        "touch_close": sig["touch_close"],
        "touch_plus1_close": sig["touch_plus1_close"],
        "fvg_1h_c0_time": to_utc3(sig["fvg_1h_c0_time"]),
        "fvg_1h_c2_time": to_utc3(sig["fvg_1h_c2_time"]),
        "fvg_1h_bottom": sig["fvg_1h_zone"][0],
        "fvg_1h_top": sig["fvg_1h_zone"][1],
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "risk_pct": round(risk / entry * 100, 4),
    }

    if activation_time is None:
        return {**base, "outcome": "not_filled", "activation_time": "",
                "exit_time": "", "exit_price": "", "hit_type": "not_filled",
                "fill_delay_min": ""}

    fill_delay = (activation_time - signal_time).total_seconds() / 60
    sim = df_1m[df_1m.index >= activation_time]

    outcome, exit_time, exit_price, hit_type = "open", None, None, None
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"
                break
            if h >= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"
                break
        else:
            if h >= sl:
                outcome, exit_time, exit_price, hit_type = "loss", ts, sl, "sl"
                break
            if l <= tp:
                outcome, exit_time, exit_price, hit_type = "win", ts, tp, "tp"
                break

    return {
        **base,
        "activation_time": to_utc3(activation_time),
        "fill_delay_min": round(fill_delay, 2),
        "outcome": outcome,
        "exit_time": to_utc3(exit_time) if exit_time else "",
        "exit_price": exit_price if exit_price is not None else "",
        "hit_type": hit_type or "open",
    }


def main():
    print(f"[INFO] Strategy 3.2 backtest, {SYMBOL}, окно {DAYS_BACK}d, RR={RR}")
    print()

    print("[INFO] загрузка данных")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_1m = load_df(SYMBOL, "1m")
    print(f"  4h={len(df_4h)} 1h={len(df_1h)} 1m={len(df_1m)}")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_4h_cut = df_4h[df_4h.index >= cutoff]
    print(f"  cutoff ({cutoff.date()}): 4h={len(df_4h_cut)}")
    print()

    print("[INFO] прогон детектора")
    signals = detect_strategy_3_2_signals(df_4h_cut, df_1h, verbose=True)

    if not signals:
        print("[WARN] ни одного сигнала")
        return

    print()
    print(f"[INFO] симуляция RR={RR}")
    rows = [simulate_outcome(s, df_1m) for s in signals]
    df = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"  записано: {OUTPUT_CSV} ({len(df)} строк)")

    closed = df[df["outcome"].isin(["win", "loss"])]
    nf = (df["outcome"] == "not_filled").sum()
    op = (df["outcome"] == "open").sum()
    W = int((closed["outcome"] == "win").sum())
    L = int((closed["outcome"] == "loss").sum())
    wr = W / (W + L) * 100 if (W + L) else 0.0
    pnl = W * RR - L

    print()
    print("=" * 60)
    print(f"СВОДКА  RR={RR}  окно={DAYS_BACK}d")
    print("=" * 60)
    print(f"  total={len(df)}  closed={W+L}  not_filled={nf}  open={op}")
    print(f"  W={W}  L={L}  WR={wr:.1f}%  PnL={pnl:+.1f}R")

    if not closed.empty:
        clo = closed.copy()
        clo["t"] = pd.to_datetime(clo["signal_time"])
        clo["year"] = clo["t"].dt.year
        for y in sorted(clo["year"].unique()):
            sub = clo[clo["year"] == y]
            Wy = int((sub["outcome"] == "win").sum())
            Ly = int((sub["outcome"] == "loss").sum())
            wry = Wy / (Wy + Ly) * 100 if (Wy + Ly) else 0
            pnly = Wy * RR - Ly
            print(f"  {y}: n={Wy+Ly} WR={wry:.1f}% PnL={pnly:+.1f}R")
        print()
        print("По направлению:")
        d = closed.groupby("direction").agg(n=("outcome", "size"))
        d["w"] = closed.groupby("direction")["outcome"].apply(lambda s: (s == "win").sum())
        d["l"] = d["n"] - d["w"]
        d["wr%"] = (d["w"] / d["n"] * 100).round(1)
        d["pnl"] = d["w"] * RR - d["l"]
        print(d.to_string())


if __name__ == "__main__":
    main()
