"""C2: i-RDRB+FVG setup на 1h формирует OB на 4h того же направления.

Проверка: ищем OB-4h pair (prev_4h, cur_4h), у которой cur_time лежит в
окне setup'а (от open(#1) до close(#5) + 4h, чтобы захватить только что
закрытый 4h-bar после setup'а).

Direction matching: OB direction == i_dir.

BTC + ETH 1h, 6 лет, entry=0.9, SL=0.2, RR=1.4.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from strategies.strategy_rdrb import detect_rdrb
from strategies.strategy_1_1_1 import detect_fvg, detect_ob_pair

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
    ("SOLUSDT", ROOT / "data" / "SOLUSDT_1m_vic_vadim.csv"),
]
START = pd.Timestamp("2020-05-15", tz="UTC")
ENTRY_FRAC = 0.9
SL_FRAC = 0.2
RR = 1.4


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def scan(df_1h, df_4h, df_1m):
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    closes = df_1h["close"].to_numpy()
    idx_1h = df_1h.index
    idx_4h = df_4h.index
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

        # Окно времени setup'а: от open(#1) до close(#5)
        win_start = idx_1h[k - 2]
        win_end = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        # 4h-bars, у которых cur_time в [win_start, win_end + 4h] — чтобы захватить
        # только что закрывшийся 4h-bar
        sp4 = int(idx_4h.searchsorted(win_start, side="left"))
        ep4 = int(idx_4h.searchsorted(win_end + pd.Timedelta(hours=4), side="right"))

        # Проверка: есть ли OB-4h pair direction-matching, cur в окне
        ob4h_match = False
        for ci in range(max(sp4, 1), min(ep4, len(idx_4h))):
            ob = detect_ob_pair(df_4h, ci)
            if ob is None: continue
            if ob.direction == i_dir:
                ob4h_match = True; break

        # Geometry + execution
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

        signal_time = idx_1h[k + 2] + pd.Timedelta(minutes=60)
        sp = int(idx1.searchsorted(signal_time, side="left"))
        if sp >= len(idx1): continue
        if i_dir == "LONG":
            mit_hits = np.where(lo1[sp:] <= zone_t)[0]
        else:
            mit_hits = np.where(hi1[sp:] >= zone_b)[0]
        if mit_hits.size == 0:
            rows.append({"dir": i_dir, "outcome": "no_mit", "ob4h": ob4h_match}); continue
        mit_idx = sp + int(mit_hits[0])
        post_lo = lo1[mit_idx:]; post_hi = hi1[mit_idx:]
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
            rows.append({"dir": i_dir, "outcome": "no_entry", "ob4h": ob4h_match}); continue
        if e_idx >= m:
            rows.append({"dir": i_dir, "outcome": "not_filled", "ob4h": ob4h_match}); continue
        post2_lo = post_lo[e_idx:]; post2_hi = post_hi[e_idx:]
        if i_dir == "LONG":
            sl_mask = post2_lo <= sl; tp_mask_a = post2_hi >= tp
        else:
            sl_mask = post2_hi >= sl; tp_mask_a = post2_lo <= tp
        sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
        tp_first = int(np.argmax(tp_mask_a)) if tp_mask_a.any() else -1
        if sl_first == -1 and tp_first == -1: outcome = "open"
        elif sl_first == -1: outcome = "win"
        elif tp_first == -1: outcome = "loss"
        else: outcome = "win" if tp_first < sl_first else "loss"
        rows.append({"dir": i_dir, "outcome": outcome, "ob4h": ob4h_match})

    return pd.DataFrame(rows)


def stats(df, label):
    closed = df[df["outcome"].isin(["win", "loss"])]
    w = int((closed["outcome"] == "win").sum())
    l = int((closed["outcome"] == "loss").sum())
    n = w + l
    wr = w/n*100 if n else 0; r = w*RR - l
    return {"label": label, "total": len(df), "closed": n,
            "W": w, "L": l, "WR": wr, "ΣR": r, "R/tr": r/n if n else 0}


def main():
    all_rows = []
    for asset, path in ASSETS:
        print(f"\n=== {asset} ===", flush=True)
        df_1m = load_1m(path)
        df_1m = df_1m[df_1m.index >= START]
        df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
            "open":"first","high":"max","low":"min","close":"last","volume":"sum"
        }).dropna(subset=["close"])
        df_4h = df_1m.resample("4h", origin="epoch", label="left", closed="left").agg({
            "open":"first","high":"max","low":"min","close":"last","volume":"sum"
        }).dropna(subset=["close"])
        print(f"  1h={len(df_1h):,}, 4h={len(df_4h):,}")
        df = scan(df_1h, df_4h, df_1m)
        base = stats(df, f"{asset} baseline")
        match = stats(df[df["ob4h"] == True], f"{asset} OB-4h match")
        nomatch = stats(df[df["ob4h"] == False], f"{asset} no OB-4h")
        all_rows.extend([base, match, nomatch])
        for r in (base, match, nomatch):
            print(f"  {r['label']:>26}: total={r['total']:>4} closed={r['closed']:>4} "
                  f"W={r['W']:>3} L={r['L']:>3} WR={r['WR']:>5.2f}% ΣR={r['ΣR']:>+7.2f} R/tr={r['R/tr']:>+6.3f}")

    print(f"\n=== Σ портфель (BTC + ETH) ===")
    for kind in ("baseline", "OB-4h match", "no OB-4h"):
        subs = [s for s in all_rows if kind in s["label"]]
        w = sum(s["W"] for s in subs); l = sum(s["L"] for s in subs)
        n = w + l
        wr = w/n*100 if n else 0; r = w*RR - l
        print(f"  Σ {kind:>12}: closed={n:>4} W={w:>3} L={l:>3} WR={wr:>5.2f}% ΣR={r:>+7.2f} R/tr={r/n if n else 0:>+6.3f}")


if __name__ == "__main__":
    main()
