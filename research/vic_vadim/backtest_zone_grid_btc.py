"""Grid search лучшей зоны для entry/SL на BTC 1h.

Entry-зоны (5 кандидатов) × fractions {0.2, 0.5, 0.8}:
  Z1 zone_interest:  [min(low #1..#4), low(#5)] (LONG) — baseline
  Z2 V1_RDRB:        [V1.bottom, V1.top] — узкая
  Z3 V2_RDRB:        V1 + anchor body extension (шире)
  Z4 all_setup:      [min(low #1..#5), max(high #1..#5)] — full range
  Z5 FVG_1h:         FVG-1h на (#3,#4,#5) direction-aware (если есть)

SL-локации (6 кандидатов, single price):
  S1 zone_b_int:    min(low #1..#4) (= zone_bottom interest) — baseline
  S2 zb_minus_atr:  zone_b - 0.5 × ATR(1h, 14)
  S3 V1_bottom:     V1.zone_bottom (LONG)
  S4 anchor_low:    low #1
  S5 mid_low:       low #2
  S6 inversion_low: low #4

Для SHORT — зеркально (по high соответствующих свечей).
RR = 1.4. Без таймстопа. No_entry-логика (TP до entry → cancel).
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

CACHE = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
START = pd.Timestamp("2020-05-15", tz="UTC")
RR = 1.4
ATR_PERIOD = 14
ENTRY_FRACS = [0.2, 0.5, 0.8]


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def compute_atr(df, period=14):
    h = df["high"]; l = df["low"]; c = df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean().to_numpy()


def simulate(direction, entry, sl, tp, signal_time, df_1m):
    if direction == "LONG" and not (sl < entry < tp): return "bad_geom"
    if direction == "SHORT" and not (sl > entry > tp): return "bad_geom"
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
    df_1m = load_1m()
    df_1m = df_1m[df_1m.index >= START]
    df_1h = df_1m.resample("1h", origin="epoch", label="left", closed="left").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna(subset=["close"])
    atr = compute_atr(df_1h, ATR_PERIOD)
    n = len(df_1h)
    highs = df_1h["high"].to_numpy(); lows = df_1h["low"].to_numpy()
    opens_a = df_1h["open"].to_numpy(); closes_a = df_1h["close"].to_numpy()
    idx = df_1h.index

    rows = []
    for k in range(2, n - 5):
        rdrb = detect_rdrb(df_1h, k, zone_version="V1")
        if rdrb is None: continue
        c4_close = closes_a[k + 1]
        if rdrb.direction == "LONG":
            if not (c4_close < rdrb.bottom): continue
            i_dir = "SHORT"
        else:
            if not (c4_close > rdrb.top): continue
            i_dir = "LONG"
        fvg = detect_fvg(df_1h, k + 2)
        if fvg is None or fvg.direction != i_dir: continue

        # Сbор зон
        # Z1: zone_interest
        if i_dir == "LONG":
            z1_b = float(min(lows[k-2], lows[k-1], lows[k], lows[k+1]))
            z1_t = float(lows[k+2])
        else:
            z1_t = float(max(highs[k-2], highs[k-1], highs[k], highs[k+1]))
            z1_b = float(highs[k+2])
        if z1_t <= z1_b: continue

        # Z2: V1
        z2_b, z2_t = rdrb.bottom, rdrb.top
        if z2_t <= z2_b: continue

        # Z3: V2 (V1 + anchor body extension)
        a_open = opens_a[k-2]; a_close = closes_a[k-2]
        a_body_top = max(a_open, a_close); a_body_bottom = min(a_open, a_close)
        if rdrb.direction == "LONG":
            # V1 LONG: V2 zone_bottom расширяется до a_body_top
            z3_b = a_body_top; z3_t = z2_t
        else:
            # V1 SHORT: V2 zone_top расширяется до a_body_bottom
            z3_t = a_body_bottom; z3_b = z2_b
        if z3_t <= z3_b: continue

        # Z4: all_setup [min low, max high] #1..#5
        if i_dir == "LONG":
            z4_b = float(min(lows[k-2:k+3]))
            z4_t = float(max(highs[k-2:k+3]))
        else:
            z4_b = float(min(lows[k-2:k+3]))
            z4_t = float(max(highs[k-2:k+3]))
        if z4_t <= z4_b: continue

        # Z5: FVG-1h на (#3,#4,#5) direction-aware
        fvg_1h_345 = detect_fvg(df_1h, k + 2)  # триплет k, k+1, k+2
        if fvg_1h_345 is not None and fvg_1h_345.direction == i_dir:
            z5_b = fvg_1h_345.bottom; z5_t = fvg_1h_345.top
        else:
            z5_b = None; z5_t = None

        # SL-локации (single price)
        if i_dir == "LONG":
            sl_S1 = float(min(lows[k-2], lows[k-1], lows[k], lows[k+1]))  # zone_b interest
            sl_S2 = sl_S1 - 0.5 * atr[k] if not np.isnan(atr[k]) else None
            sl_S3 = z2_b  # V1.bottom
            sl_S4 = float(lows[k-2])  # anchor.low
            sl_S5 = float(lows[k-1])  # mid.low
            sl_S6 = float(lows[k+1])  # inversion.low
        else:
            sl_S1 = float(max(highs[k-2], highs[k-1], highs[k], highs[k+1]))
            sl_S2 = sl_S1 + 0.5 * atr[k] if not np.isnan(atr[k]) else None
            sl_S3 = z2_t
            sl_S4 = float(highs[k-2])
            sl_S5 = float(highs[k-1])
            sl_S6 = float(highs[k+1])

        signal_time = idx[k + 2] + pd.Timedelta(minutes=60)

        zones = {
            "Z1_zone_int": (z1_b, z1_t),
            "Z2_V1": (z2_b, z2_t),
            "Z3_V2": (z3_b, z3_t),
            "Z4_setup": (z4_b, z4_t),
            "Z5_FVG_1h": (z5_b, z5_t) if z5_b is not None else None,
        }
        sl_levels = {"S1_z_int": sl_S1, "S2_atr": sl_S2,
                     "S3_V1_b": sl_S3, "S4_anchor": sl_S4,
                     "S5_mid": sl_S5, "S6_inv": sl_S6}

        row = {"dir": i_dir, "i_time": idx[k - 2]}
        for z_name, z in zones.items():
            if z is None:
                for ef in ENTRY_FRACS:
                    for s_name in sl_levels:
                        row[f"{z_name}_e{ef}_{s_name}"] = "no_zone"
                continue
            z_b, z_t = z
            z_w = z_t - z_b
            if z_w <= 0:
                for ef in ENTRY_FRACS:
                    for s_name in sl_levels:
                        row[f"{z_name}_e{ef}_{s_name}"] = "no_zone"
                continue
            for ef in ENTRY_FRACS:
                if i_dir == "LONG":
                    entry = z_b + ef * z_w
                else:
                    entry = z_t - ef * z_w
                for s_name, sl_val in sl_levels.items():
                    if sl_val is None:
                        row[f"{z_name}_e{ef}_{s_name}"] = "no_sl"; continue
                    if i_dir == "LONG":
                        if sl_val >= entry:
                            row[f"{z_name}_e{ef}_{s_name}"] = "bad_geom"; continue
                        risk = entry - sl_val; tp = entry + RR * risk
                    else:
                        if sl_val <= entry:
                            row[f"{z_name}_e{ef}_{s_name}"] = "bad_geom"; continue
                        risk = sl_val - entry; tp = entry - RR * risk
                    row[f"{z_name}_e{ef}_{s_name}"] = simulate(i_dir, entry, sl_val, tp, signal_time, df_1m)
        rows.append(row)
    return pd.DataFrame(rows)


def stats(df, col):
    closed = df[df[col].isin(["win", "loss"])]
    w = int((closed[col] == "win").sum())
    l = len(closed) - w
    n = w + l
    wr = w/n*100 if n else 0
    sR = w*RR - l
    return {"n": n, "W": w, "L": l, "WR": wr, "ΣR": sR, "R/tr": sR/n if n else 0}


def main():
    print("scanning BTC 1h...", flush=True)
    df = scan()
    print(f"setups: {len(df)}\n")

    # Все combo columns
    combo_cols = [c for c in df.columns if c.startswith(("Z1_", "Z2_", "Z3_", "Z4_", "Z5_"))]
    results = []
    for col in combo_cols:
        s = stats(df, col)
        results.append({"combo": col, **s})

    # Сортируем по ΣR
    results.sort(key=lambda x: -x["ΣR"])
    print(f"=== TOP-20 по ΣR ===")
    print(f"  {'combo':>28} {'n':>4} {'W':>4} {'L':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7} {'R/yr':>7}")
    for r in results[:20]:
        print(f"  {r['combo']:>28} {r['n']:>4} {r['W']:>4} {r['L']:>4} "
              f"{r['WR']:>6.2f} {r['ΣR']:>+8.2f} {r['R/tr']:>+7.3f} {r['ΣR']/6:>+7.2f}")

    print(f"\n=== TOP-10 по R/trade (n ≥ 100) ===")
    results_filtered = [r for r in results if r["n"] >= 100]
    results_filtered.sort(key=lambda x: -x["R/tr"])
    print(f"  {'combo':>28} {'n':>4} {'WR%':>6} {'ΣR':>8} {'R/tr':>7}")
    for r in results_filtered[:10]:
        print(f"  {r['combo']:>28} {r['n']:>4} {r['WR']:>6.2f} {r['ΣR']:>+8.2f} {r['R/tr']:>+7.3f}")

    print(f"\n=== Baseline (Z1_e0.9, S1_z_int approximation) для сравнения ===")
    # baseline: zone_interest entry=0.9 (но у нас фракции 0.2/0.5/0.8 — ближайший 0.8)
    s = stats(df, "Z1_zone_int_e0.8_S1_z_int")
    print(f"  Z1 e0.8 S1: n={s['n']} W={s['W']} L={s['L']} WR={s['WR']:.2f}% ΣR={s['ΣR']:+.2f}")

    out = ROOT / "signals" / "zone_grid_btc.csv"
    df.to_csv(out, index=False)
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
