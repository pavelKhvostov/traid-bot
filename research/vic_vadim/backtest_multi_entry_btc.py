"""Multi-entry стратегия на i-RDRB+FVG (BTC 1h, 6 лет).

Entry-1: 0.4 V1.zone ширины от V1.bottom (LONG) / V1.top (SHORT)
Entry-2: 0.8 FVG-15m ширины от FVG.bottom (LONG) / FVG.top (SHORT)
         FVG-15m ищется в свечах setup'а #1..#5, direction = i_dir
SL-1: EVoT max-winner-PRICE свечей #2..#4 (для LONG = max_bear_price, для SHORT = max_bull_price)
SL-2: для LONG = min(low #1..#4) + 0.2·(V1.zone_bottom − min(low #1..#4))
      для SHORT зеркально

4 комбинации: Entry × SL = E1×SL1, E1×SL2, E2×SL1, E2×SL2
RR = 1.4, симуляция: после signal_time, no_entry-логика.
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
RR = 1.4
ENTRY1_FRAC = 0.4  # в V1 зоне
ENTRY2_FRAC = 0.8  # в FVG-15m
SL2_FRAC = 0.8     # 0.8 расстояния от min_setup до V1.zone_bottom


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def find_fvg_15m_in_setup(df_15m, setup_open_t, setup_close_t, direction):
    """Ищет FVG-15m с direction = direction внутри окна [setup_open_t, setup_close_t].
    Возвращает (bottom, top) или None."""
    seg = df_15m[(df_15m.index >= setup_open_t) & (df_15m.index <= setup_close_t)]
    for k in range(2, len(seg)):
        f = detect_fvg(seg, k)
        if f is None or f.direction != direction: continue
        return f.bottom, f.top
    return None


def evot_max_price(df_1m, t_start, t_end, i_dir):
    """EVoT max winner-price на 1m свечах в [t_start, t_end].
    Для LONG возвращает max_bear_price (поддержка); для SHORT max_bull_price."""
    seg = df_1m[(df_1m.index >= t_start) & (df_1m.index < t_end)]
    if seg.empty: return None
    if i_dir == "LONG":
        bear = seg[seg["close"] < seg["open"]]
        if bear.empty: return None
        return float(bear.loc[bear["volume"].idxmax(), "close"])
    else:
        bull = seg[seg["close"] > seg["open"]]
        if bull.empty: return None
        return float(bull.loc[bull["volume"].idxmax(), "close"])


def simulate(direction, entry, sl, tp, signal_time, df_1m):
    """Симуляция: после signal_time ждём fill, потом SL/TP. no_entry если TP до entry."""
    if direction == "LONG" and not (sl < entry < tp): return "bad_geometry"
    if direction == "SHORT" and not (sl > entry > tp): return "bad_geometry"
    fwd = df_1m[df_1m.index >= signal_time]
    if fwd.empty: return "no_data"
    h = fwd["high"].values; l = fwd["low"].values
    n = len(h)
    if direction == "LONG":
        ei = np.where(l <= entry)[0]; ti = np.where(h >= tp)[0]
    else:
        ei = np.where(h >= entry)[0]; ti = np.where(l <= tp)[0]
    e_idx = int(ei[0]) if ei.size else n + 1
    tp_pre = int(ti[0]) if ti.size else n + 1
    if tp_pre < e_idx: return "no_entry"
    if e_idx >= n: return "not_filled"
    p2l = l[e_idx:]; p2h = h[e_idx:]
    if direction == "LONG":
        slm = p2l <= sl; tpm = p2h >= tp
    else:
        slm = p2h >= sl; tpm = p2l <= tp
    sf = int(np.argmax(slm)) if slm.any() else -1
    tf = int(np.argmax(tpm)) if tpm.any() else -1
    if sf == -1 and tf == -1: return "open"
    if sf == -1: return "win"
    if tf == -1: return "loss"
    return "win" if tf < sf else "loss"


def scan():
    df_1m = load_1m(CACHE)
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])
    df_15m = df_1m.resample("15min", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])

    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    idx = df_1h.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_1h, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_1h, k + 2)
        if fvg is None or fvg.direction != i_dir: continue

        # V1 зона
        v1_b = rdrb.bottom; v1_t = rdrb.top
        v1_width = v1_t - v1_b
        if v1_width <= 0: continue

        # Entry-1: 0.4 V1
        if i_dir == "LONG":
            entry_1 = v1_b + ENTRY1_FRAC * v1_width
        else:
            entry_1 = v1_t - ENTRY1_FRAC * v1_width

        # FVG-15m в setup'е (#1..#5 = k-2..k+2)
        setup_open_t = idx[k - 2]
        setup_close_t = idx[k + 2] + pd.Timedelta(minutes=60)
        fvg15 = find_fvg_15m_in_setup(df_15m, setup_open_t, setup_close_t, i_dir)
        entry_2 = None
        if fvg15 is not None:
            f15_b, f15_t = fvg15
            f15_w = f15_t - f15_b
            if i_dir == "LONG":
                entry_2 = f15_b + ENTRY2_FRAC * f15_w
            else:
                entry_2 = f15_t - ENTRY2_FRAC * f15_w

        # SL-1: EVoT max winner свечей #2..#4
        evot_t_start = idx[k - 1]  # open #2
        evot_t_end = idx[k + 1] + pd.Timedelta(minutes=60)  # close #4
        sl_1 = evot_max_price(df_1m, evot_t_start, evot_t_end, i_dir)

        # SL-2: 0.8 от min_setup до V1.zone_bottom (LONG)
        if i_dir == "LONG":
            min_setup = float(min(lows[k-2], lows[k-1], lows[k], lows[k+1]))
            dist = v1_b - min_setup
            sl_2 = v1_b - SL2_FRAC * dist if dist > 0 else None  # ≈ min_setup + 0.2*dist
        else:
            max_setup = float(max(highs[k-2], highs[k-1], highs[k], highs[k+1]))
            dist = max_setup - v1_t
            sl_2 = v1_t + SL2_FRAC * dist if dist > 0 else None

        signal_time = idx[k + 2] + pd.Timedelta(minutes=60)

        # 4 combos
        out = {"dir": i_dir, "i_time": idx[k - 2],
               "entry_1": entry_1, "entry_2": entry_2,
               "sl_1": sl_1, "sl_2": sl_2}

        for entry_label, entry_val in [("E1", entry_1), ("E2", entry_2)]:
            for sl_label, sl_val in [("SL1", sl_1), ("SL2", sl_2)]:
                key = f"{entry_label}_{sl_label}"
                if entry_val is None or sl_val is None:
                    out[key] = "no_geom"; continue
                # risk
                if i_dir == "LONG":
                    risk = entry_val - sl_val
                    tp = entry_val + RR * risk
                else:
                    risk = sl_val - entry_val
                    tp = entry_val - RR * risk
                if risk <= 0:
                    out[key] = "bad_geometry"; continue
                out[key] = simulate(i_dir, entry_val, sl_val, tp, signal_time, df_1m)
        rows.append(out)
    return pd.DataFrame(rows)


def stats(df, col):
    closed = df[df[col].isin(["win", "loss"])]
    w = int((closed[col] == "win").sum())
    l = len(closed) - w
    n = w + l
    wr = w/n*100 if n else 0
    sR = w*RR - l
    bad = int((df[col] == "no_geom").sum()) + int((df[col] == "bad_geometry").sum())
    ne = int((df[col] == "no_entry").sum())
    nf = int((df[col] == "not_filled").sum())
    op = int((df[col] == "open").sum())
    return {"n_total": len(df), "no_geom": bad, "no_entry": ne, "not_filled": nf,
            "open": op, "closed": n, "W": w, "L": l, "WR": wr, "ΣR": sR,
            "R/tr": sR/n if n else 0}


def main():
    print("scanning BTC 1h...", flush=True)
    df = scan()
    print(f"setups detected: {len(df)}\n")

    for col in ["E1_SL1", "E1_SL2", "E2_SL1", "E2_SL2"]:
        s = stats(df, col)
        print(f"=== {col} (entry-{'1 (V1 0.4)' if 'E1' in col else '2 (FVG15 0.8)'}, "
              f"SL-{'1 (EVoT)' if 'SL1' in col else '2 (0.8 dist)'}) ===")
        print(f"  total={s['n_total']} no_geom={s['no_geom']} no_entry={s['no_entry']} "
              f"not_filled={s['not_filled']} open={s['open']}")
        print(f"  closed={s['closed']} W={s['W']} L={s['L']} WR={s['WR']:.2f}% "
              f"ΣR={s['ΣR']:+.2f} R/tr={s['R/tr']:+.3f}\n")

    # Baseline для сравнения
    print(f"=== Baseline (entry=0.9 zone, SL=0.2 zone, RR=1.4) ===")
    print(f"  closed=730 W=367 L=363 WR=50.27% ΣR=+150.80 R/tr=+0.207\n")

    out = ROOT / "signals" / "multi_entry_btc.csv"
    df.to_csv(out, index=False)
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
