"""Entry-backtest i-RDRB+FVG зоны интереса с ожиданием митигации.

Workflow:
  1. Setup детектируется (i-RDRB + FVG того же направления что i-RDRB)
  2. Зона интереса (LONG: bottom=min(low #1..#4), top=low(#5); SHORT зеркально)
  3. Ждём митигации (touch zone_top для LONG / zone_bottom для SHORT) — без таймстопа
  4. После митигации активируем сетап: entry=0.9, SL=0.2, RR=1 (доли ширины зоны)
  5. Симуляция (без таймстопа): no_entry (TP до entry → cancel), win, loss

BTC, 2023-01-01 → конец данных, ТФ ∈ {1h, 2h, 90m}.
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
START = pd.Timestamp("2020-05-15", tz="UTC")
TFS = [("1h", "1h", 60)]

ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def scan_tf(df_tf: pd.DataFrame, df_1m: pd.DataFrame, tf_min: int, label: str) -> dict:
    n = len(df_tf)
    highs = df_tf["high"].to_numpy()
    lows = df_tf["low"].to_numpy()
    closes = df_tf["close"].to_numpy()
    idx = df_tf.index
    lo1 = df_1m["low"].to_numpy()
    hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_tf, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_tf, k + 2)
        if fvg is None or fvg.direction != i_dir: continue
        if i_dir == "LONG":
            zone_b = float(min(lows[k - 2], lows[k - 1], lows[k], lows[k + 1]))
            zone_t = float(lows[k + 2])
        else:
            zone_t = float(max(highs[k - 2], highs[k - 1], highs[k], highs[k + 1]))
            zone_b = float(highs[k + 2])
        if zone_t <= zone_b: continue
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

        # Митигация: первое touch zone_top (LONG) / zone_bottom (SHORT) после FVG.c2 close
        start_time = idx[k + 2] + pd.Timedelta(minutes=tf_min)
        sp = int(idx1.searchsorted(start_time, side="left"))
        if sp >= len(idx1):
            rows.append({"dir": i_dir, "outcome": "no_data"}); continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mitigation"}); continue
        mit_idx = sp + int(mit_hits[0])
        mit_time = idx1[mit_idx]

        # После митигации (включая ту же 1m-свечу) ждём fill или no_entry (TP до entry).
        post_lo = lo1[mit_idx:]
        post_hi = hi1[mit_idx:]
        m = len(post_lo)
        if i_dir == "LONG":
            entry_idxs = np.where(post_lo <= entry)[0]
            tp_idxs = np.where(post_hi >= tp)[0]
        else:
            entry_idxs = np.where(post_hi >= entry)[0]
            tp_idxs = np.where(post_lo <= tp)[0]
        e_idx = int(entry_idxs[0]) if entry_idxs.size else m + 1
        tp_pre = int(tp_idxs[0]) if tp_idxs.size else m + 1
        if tp_pre < e_idx:
            rows.append({"dir": i_dir, "outcome": "no_entry",
                         "mit_time": mit_time}); continue
        if e_idx >= m:
            rows.append({"dir": i_dir, "outcome": "not_filled",
                         "mit_time": mit_time}); continue
        # fill happened; scan SL/TP after
        post2_lo = post_lo[e_idx:]
        post2_hi = post_hi[e_idx:]
        if i_dir == "LONG":
            sl_mask = post2_lo <= sl; tp_mask = post2_hi >= tp
        else:
            sl_mask = post2_hi >= sl; tp_mask = post2_lo <= tp
        sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
        tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
        if sl_first == -1 and tp_first == -1:
            outcome = "open"
        elif sl_first == -1:
            outcome = "win"
        elif tp_first == -1:
            outcome = "loss"
        else:
            outcome = "win" if tp_first < sl_first else "loss"
        rows.append({"dir": i_dir, "outcome": outcome,
                     "mit_time": mit_time,
                     "i_time": idx[k - 2], "fvg_c2_time": idx[k + 2],
                     "zone_b": zone_b, "zone_t": zone_t,
                     "entry": entry, "sl": sl, "tp": tp,
                     "width_pct": width / entry * 100})

    df = pd.DataFrame(rows)
    out = ROOT / "signals" / f"irdrb_fvg_mit_zone_{label}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    total = len(df)
    win = int((df["outcome"] == "win").sum())
    loss = int((df["outcome"] == "loss").sum())
    no_mit = int((df["outcome"] == "no_mitigation").sum())
    ne = int((df["outcome"] == "no_entry").sum())
    nf = int((df["outcome"] == "not_filled").sum())
    op = int((df["outcome"] == "open").sum())
    closed = win + loss
    wr = win / closed * 100 if closed else 0
    sum_r = win * RR - loss

    def by_dir(d):
        sub = df[df["dir"] == d]
        w = int((sub["outcome"] == "win").sum())
        l = int((sub["outcome"] == "loss").sum())
        return len(sub), w, l, (w/(w+l)*100 if (w+l) else 0), w*RR - l
    L_n, L_w, L_l, L_wr, L_r = by_dir("LONG")
    S_n, S_w, S_l, S_wr, S_r = by_dir("SHORT")

    return {"tf": label, "total": total, "no_mit": no_mit, "no_entry": ne,
            "not_filled": nf, "open": op, "closed": closed, "wr": wr, "sum_r": sum_r,
            "L_n": L_n, "L_w": L_w, "L_l": L_l, "L_wr": L_wr, "L_r": L_r,
            "S_n": S_n, "S_w": S_w, "S_l": S_l, "S_wr": S_wr, "S_r": S_r}


def main():
    print("loading BTC 1m...", flush=True)
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    print(f"  bars: {len(df_1m):,}  end: {df_1m.index.max()}", flush=True)

    summaries = []
    for label, freq, tf_min in TFS:
        df_tf = resample(df_1m, freq)
        print(f"\n=== {label} ({len(df_tf):,} bars) ===", flush=True)
        s = scan_tf(df_tf, df_1m, tf_min, label)
        print(f"  total={s['total']}  no_mit={s['no_mit']}  no_entry={s['no_entry']}  "
              f"not_filled={s['not_filled']}  open={s['open']}")
        print(f"  closed={s['closed']}  WR={s['wr']:.1f}%  ΣR={s['sum_r']:+.2f}")
        print(f"    LONG  n={s['L_n']} W={s['L_w']} L={s['L_l']} WR={s['L_wr']:.1f}% ΣR={s['L_r']:+.2f}")
        print(f"    SHORT n={s['S_n']} W={s['S_w']} L={s['S_l']} WR={s['S_wr']:.1f}% ΣR={s['S_r']:+.2f}")
        summaries.append(s)

    print("\n=== SUMMARY ===")
    print(f"{'TF':>5} {'tot':>4} {'noM':>4} {'noE':>4} {'open':>4} {'closed':>6} {'WR%':>5} {'ΣR':>7}  "
          f"{'L_WR':>5} {'L_R':>6}  {'S_WR':>5} {'S_R':>6}")
    for s in summaries:
        print(f"{s['tf']:>5} {s['total']:>4} {s['no_mit']:>4} {s['no_entry']:>4} {s['open']:>4} "
              f"{s['closed']:>6} {s['wr']:>5.1f} {s['sum_r']:>+7.2f}  "
              f"{s['L_wr']:>5.1f} {s['L_r']:>+6.2f}  {s['S_wr']:>5.1f} {s['S_r']:>+6.2f}")


if __name__ == "__main__":
    main()
