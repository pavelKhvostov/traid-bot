"""Entry-backtest i-RDRB+FVG зоны интереса на BTC с 2023-01-01.

Setup как в check_irdrb_fvg.py (5 свечей: V1 RDRB → инверсия → FVG того же
направления что i-RDRB).

Зона интереса (LONG):
  bottom = min(low #1..#4) — низший экстремум setup'а
  top    = low(#5)         — low FVG c2 свечи
Зеркально для SHORT (top=max(high #1..#4), bottom=high(#5)).

Параметры execution (доли ширины зоны):
  entry = bottom + 0.9*width (LONG) / top - 0.9*width (SHORT)
  SL    = bottom + 0.2*width (LONG) / top - 0.2*width (SHORT)
  TP    = entry + risk (LONG)        / entry - risk    (SHORT)        # RR=1
  risk  = 0.7*width

Симуляция на 1m с no_entry-логикой и таймстопом TIME_STOP_BARS свечей того же ТФ.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb
from strategies.strategy_1_1_1 import detect_fvg

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2023-01-01", tz="UTC")
TFS = [("1h", "1h", 60), ("2h", "2h", 120), ("90m", "90min", 90)]

ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.0
TIME_STOP_BARS = 20


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def simulate(direction: str, entry: float, sl: float, tp: float,
             fill_start: pd.Timestamp, stop_time: pd.Timestamp,
             df_1m: pd.DataFrame) -> str:
    fwd = df_1m[(df_1m.index >= fill_start) & (df_1m.index <= stop_time)]
    if fwd.empty:
        return "no_data"
    h = fwd["high"].values; l = fwd["low"].values
    n = len(h)
    if direction == "LONG":
        entry_idxs = np.where(l <= entry)[0]
        tp_idxs = np.where(h >= tp)[0]
    else:
        entry_idxs = np.where(h >= entry)[0]
        tp_idxs = np.where(l <= tp)[0]
    entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
    tp_pre = int(tp_idxs[0]) if tp_idxs.size else n + 1
    if tp_pre < entry_idx:
        return "no_entry"
    if entry_idx >= n:
        return "not_filled"
    post_l = l[entry_idx:]; post_h = h[entry_idx:]
    if direction == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "timeout"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def scan_tf(df_tf: pd.DataFrame, df_1m: pd.DataFrame, tf_min: int, label: str) -> dict:
    n = len(df_tf)
    highs = df_tf["high"].to_numpy()
    lows = df_tf["low"].to_numpy()
    closes = df_tf["close"].to_numpy()
    idx = df_tf.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_tf, k, zone_version="V1")
        if rdrb is None:
            continue
        c4_close = closes[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_tf, k + 2)
        if fvg is None or fvg.direction != i_dir:
            continue
        # Зона интереса
        if i_dir == "LONG":
            zone_b = float(min(lows[k - 2], lows[k - 1], lows[k], lows[k + 1]))
            zone_t = float(lows[k + 2])
        else:
            zone_t = float(max(highs[k - 2], highs[k - 1], highs[k], highs[k + 1]))
            zone_b = float(highs[k + 2])
        if zone_t <= zone_b:
            rows.append({"outcome": "bad_zone", "dir": i_dir}); continue
        width = zone_t - zone_b
        if i_dir == "LONG":
            entry = zone_b + ENTRY_FRAC * width
            sl = zone_b + SL_FRAC * width
            risk = entry - sl
            tp = entry + RR * risk
        else:
            entry = zone_t - ENTRY_FRAC * width
            sl = zone_t - SL_FRAC * width
            risk = sl - entry
            tp = entry - RR * risk
        fill_start = idx[k + 2] + pd.Timedelta(minutes=tf_min)
        stop_time = fill_start + pd.Timedelta(minutes=tf_min * TIME_STOP_BARS)
        outcome = simulate(i_dir, entry, sl, tp, fill_start, stop_time, df_1m)
        rows.append({"outcome": outcome, "dir": i_dir,
                     "i_time": idx[k - 2], "fvg_c2_time": idx[k + 2],
                     "zone_b": zone_b, "zone_t": zone_t, "width_pct": width/entry*100,
                     "entry": entry, "sl": sl, "tp": tp})
    df = pd.DataFrame(rows)
    out = ROOT / "signals" / f"irdrb_fvg_zone_{label}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    total = len(df)
    win = int((df["outcome"] == "win").sum())
    loss = int((df["outcome"] == "loss").sum())
    ne = int((df["outcome"] == "no_entry").sum())
    nf = int((df["outcome"] == "not_filled").sum())
    to = int((df["outcome"] == "timeout").sum())
    bad = int((df["outcome"] == "bad_zone").sum())
    closed = win + loss
    wr = win / closed * 100 if closed else 0
    sum_r = win * RR - loss
    return {"tf": label, "total": total, "win": win, "loss": loss,
            "no_entry": ne, "not_filled": nf, "timeout": to, "bad": bad,
            "closed": closed, "wr": wr, "sum_r": sum_r,
            "long_total": int((df["dir"] == "LONG").sum()),
            "short_total": int((df["dir"] == "SHORT").sum()),
            "long_win": int(((df["dir"] == "LONG") & (df["outcome"] == "win")).sum()),
            "long_loss": int(((df["dir"] == "LONG") & (df["outcome"] == "loss")).sum()),
            "short_win": int(((df["dir"] == "SHORT") & (df["outcome"] == "win")).sum()),
            "short_loss": int(((df["dir"] == "SHORT") & (df["outcome"] == "loss")).sum())}


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    print(f"  bars: {len(df_1m):,}", flush=True)

    summaries = []
    for label, freq, tf_min in TFS:
        df_tf = resample(df_1m, freq)
        print(f"\n=== {label} ({len(df_tf):,} bars) ===", flush=True)
        s = scan_tf(df_tf, df_1m, tf_min, label)
        L_wr = s["long_win"] / (s["long_win"]+s["long_loss"]) * 100 if (s["long_win"]+s["long_loss"]) else 0
        S_wr = s["short_win"] / (s["short_win"]+s["short_loss"]) * 100 if (s["short_win"]+s["short_loss"]) else 0
        print(f"  total={s['total']}  no_entry={s['no_entry']}  not_filled={s['not_filled']}  timeout={s['timeout']}  bad={s['bad']}")
        print(f"  closed={s['closed']}  WR={s['wr']:.1f}%  ΣR={s['sum_r']:+.2f}")
        print(f"    LONG  n={s['long_total']} win={s['long_win']} loss={s['long_loss']} WR={L_wr:.1f}%")
        print(f"    SHORT n={s['short_total']} win={s['short_win']} loss={s['short_loss']} WR={S_wr:.1f}%")
        summaries.append(s)

    print("\n=== SUMMARY ===")
    print(f"{'TF':>5} {'total':>5} {'closed':>6} {'WR%':>5} {'ΣR':>6}  {'L_WR':>5} {'S_WR':>5}")
    for s in summaries:
        L_wr = s["long_win"] / (s["long_win"]+s["long_loss"]) * 100 if (s["long_win"]+s["long_loss"]) else 0
        S_wr = s["short_win"] / (s["short_win"]+s["short_loss"]) * 100 if (s["short_win"]+s["short_loss"]) else 0
        print(f"{s['tf']:>5} {s['total']:>5} {s['closed']:>6} {s['wr']:>5.1f} {s['sum_r']:>+6.2f}  {L_wr:>5.1f} {S_wr:>5.1f}")


if __name__ == "__main__":
    main()
