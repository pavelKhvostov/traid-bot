"""Pересимуляция i-RDRB+FVG zone-mitigation с persistent limit
(никаких no_entry — лимит ждёт fill бесконечно).

Сравнение с cancel-on-TP-логикой по BTC и ETH 1h, 6 лет.
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

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
]
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def simulate(direction, entry, sl, tp, post_lo, post_hi, persistent: bool):
    """Если persistent — нет no_entry (limit ждёт fill бесконечно).
    Иначе — cancel при tp_pre < e_idx."""
    m = len(post_lo)
    if direction == "LONG":
        entry_idxs = np.where(post_lo <= entry)[0]
        tp_idxs = np.where(post_hi >= tp)[0]
    else:
        entry_idxs = np.where(post_hi >= entry)[0]
        tp_idxs = np.where(post_lo <= tp)[0]
    e_idx = int(entry_idxs[0]) if entry_idxs.size else m + 1
    tp_pre = int(tp_idxs[0]) if tp_idxs.size else m + 1
    if not persistent and tp_pre < e_idx:
        return "no_entry"
    if e_idx >= m:
        return "not_filled"
    post2_lo = post_lo[e_idx:]; post2_hi = post_hi[e_idx:]
    if direction == "LONG":
        sl_mask = post2_lo <= sl; tp_mask = post2_hi >= tp
    else:
        sl_mask = post2_hi >= sl; tp_mask = post2_lo <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def scan(df_1h, df_1m, persistent: bool):
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    idx = df_1h.index
    lo1 = df_1m["low"].to_numpy(); hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index

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

        signal_time = idx[k + 2] + pd.Timedelta(minutes=60)
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mit"}); continue
        mit_idx = sp + int(mit_hits[0])
        outcome = simulate(i_dir, entry, sl, tp,
                            lo1[mit_idx:], hi1[mit_idx:], persistent)
        rows.append({"dir": i_dir, "outcome": outcome})
    return pd.DataFrame(rows)


def summary(df, label, asset):
    total = len(df)
    w = int((df["outcome"] == "win").sum())
    l = int((df["outcome"] == "loss").sum())
    no_mit = int((df["outcome"] == "no_mit").sum())
    ne = int((df["outcome"] == "no_entry").sum())
    nf = int((df["outcome"] == "not_filled").sum())
    op = int((df["outcome"] == "open").sum())
    closed = w + l
    wr = w / closed * 100 if closed else 0
    r = w * RR - l
    return {"asset": asset, "label": label, "total": total,
            "no_mit": no_mit, "no_entry": ne, "not_filled": nf, "open": op,
            "closed": closed, "W": w, "L": l, "WR": wr, "ΣR": r,
            "R/trade": r/closed if closed else 0}


def main():
    all_rows = []
    for asset, path in ASSETS:
        print(f"\nloading {asset} 1m...", flush=True)
        df_1m = load_1m(path)
        df_1m = df_1m[df_1m.index >= START]
        df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        }).dropna(subset=["close"])

        print(f"  scan cancel-on-TP...", flush=True)
        df_c = scan(df_1h, df_1m, persistent=False)
        s_c = summary(df_c, "cancel (baseline)", asset)
        all_rows.append(s_c)

        print(f"  scan persistent limit...", flush=True)
        df_p = scan(df_1h, df_1m, persistent=True)
        s_p = summary(df_p, "persistent", asset)
        all_rows.append(s_p)

    print(f"\n{'asset':>5} {'mode':>22}  {'total':>5} {'noM':>4} {'noE':>4} {'open':>4} "
          f"{'closed':>6} {'WR%':>6} {'ΣR':>8} {'R/tr':>7}")
    for s in all_rows:
        print(f"{s['asset']:>5} {s['label']:>22}  {s['total']:>5} {s['no_mit']:>4} "
              f"{s['no_entry']:>4} {s['open']:>4} {s['closed']:>6} {s['WR']:>5.2f}% "
              f"{s['ΣR']:>+8.2f} {s['R/trade']:>+7.3f}")

    # портфель
    print("\n=== Σ портфель (BTC + ETH) ===")
    for label in ("cancel (baseline)", "persistent"):
        subs = [s for s in all_rows if s["label"] == label]
        w = sum(s["W"] for s in subs)
        l = sum(s["L"] for s in subs)
        ne = sum(s["no_entry"] for s in subs)
        op = sum(s["open"] for s in subs)
        closed = w + l
        wr = w/closed*100 if closed else 0
        r = w*RR - l
        print(f"  {label:>22}: closed={closed}  W={w} L={l}  noE={ne}  open={op}  "
              f"WR={wr:.2f}%  ΣR={r:+.2f}  R/tr={r/closed if closed else 0:+.3f}")


if __name__ == "__main__":
    main()
