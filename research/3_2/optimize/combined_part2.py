"""Combined партия 2 — re-симуляция:

C4 — Dual exit (NWE OR bw2-zero-cross). Расширение H12: к exit добавляем
     второй триггер — bw2 пересёк 0 в противоположную сторону.
     Гипотеза: SHORT-сегмент (где H12 провалился) выйдет в плюс.

C10 — Stoch-cross exit для SHORT: вместо фикс RR=1.75 — выход когда
     rsiMod пересёк stcRsiMod снизу↑ (bull cross на двух Stoch) =
     short-momentum закончился.
"""
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
_RSI_DIR = _ROOT / "research" / "asvk_rsi"
_MH_DIR = _ROOT / "research" / "money_hands"
for d in (_RSI_DIR, _MH_DIR):
    if str(d) not in _sys.path:
        _sys.path.insert(0, str(d))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df
from plot_asvk_rsi import (
    NWE_BANDWIDTH, NWE_BAR, NWE_MULTIPLIER,
    adjusted_rsi, nwe_bands,
)
from plot_money_hands import (
    BW2_SMA_LEN, RSI_STOCH_LEN, SRSI_STOCH_LEN, RSI_SMA, WT_N1, WT_N2,
    sma, stoch, wavetrend_blueWaves,
)

INPUT_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_mh.csv")
OUT_CSV = Path("signals/strategy_3_2_combined_part2.csv")
SYMBOL = "BTCUSDT"
RR = 1.0
TIMEOUT_DAYS = 14


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def simulate_dual_exit(sig, df_1m, df_1h, ema_3, upper, lower, bw2):
    """C4: dual exit — NWE-cross OR bw2 cross zero против сделки."""
    if sig["outcome"] == "not_filled":
        return "not_filled", 0.0, "not_filled"
    activation_time = parse_utc3(sig["activation_time"])
    if activation_time is None:
        return "not_filled", 0.0, "not_filled"
    direction = sig["direction"]
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    risk = abs(entry - sl)
    timeout = activation_time + pd.Timedelta(days=TIMEOUT_DAYS)

    # SL hit на 1m
    sim_1m = df_1m[(df_1m.index >= activation_time) & (df_1m.index <= timeout)]
    sl_t = None
    for ts, c in sim_1m.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG" and l <= sl:
            sl_t = ts
            break
        if direction == "SHORT" and h >= sl:
            sl_t = ts
            break

    # Exits на 1h
    sim_1h = df_1h[(df_1h.index >= activation_time) & (df_1h.index <= timeout)]
    nwe_exit_t = None
    nwe_exit_p = None
    bw2_exit_t = None
    bw2_exit_p = None
    for ts in sim_1h.index:
        em = ema_3.loc[ts] if ts in ema_3.index else None
        up = upper.loc[ts] if ts in upper.index else None
        lo = lower.loc[ts] if ts in lower.index else None
        b = bw2.loc[ts] if ts in bw2.index else None
        if em is None or up is None or lo is None or b is None:
            continue
        if not (np.isnan(em) or np.isnan(up) or np.isnan(lo)):
            if direction == "LONG" and em > up and nwe_exit_t is None:
                nwe_exit_t = ts
                nwe_exit_p = float(sim_1h.loc[ts, "close"])
            if direction == "SHORT" and em < lo and nwe_exit_t is None:
                nwe_exit_t = ts
                nwe_exit_p = float(sim_1h.loc[ts, "close"])
        if not np.isnan(b):
            # bw2 cross 0 против сделки:
            # LONG: bw2 < 0 (медвежьим стал) — выход
            # SHORT: bw2 > 0 (бычьим стал) — выход
            if direction == "LONG" and b < 0 and bw2_exit_t is None:
                bw2_exit_t = ts
                bw2_exit_p = float(sim_1h.loc[ts, "close"])
            if direction == "SHORT" and b > 0 and bw2_exit_t is None:
                bw2_exit_t = ts
                bw2_exit_p = float(sim_1h.loc[ts, "close"])

    candidates = []
    if sl_t is not None:
        candidates.append((sl_t, "sl", sl))
    if nwe_exit_t is not None:
        candidates.append((nwe_exit_t, "nwe", nwe_exit_p))
    if bw2_exit_t is not None:
        candidates.append((bw2_exit_t, "bw2_zero", bw2_exit_p))
    if not candidates:
        return "timeout", 0.0, "timeout"
    candidates.sort(key=lambda x: x[0])
    t, kind, price = candidates[0]
    if direction == "LONG":
        r = (price - entry) / risk
    else:
        r = (entry - price) / risk
    out = "win" if r > 0 else ("loss" if r < 0 else "open")
    return out, r, kind


def simulate_stoch_cross_exit(sig, df_1m, df_1h, rsi_mod, stc_rsi_mod):
    """C10: для SHORT — exit при rsiMod cross stcRsiMod снизу↑ (bull cross).
    Для LONG — оставляем фикс RR=1 (для контроля)."""
    if sig["outcome"] == "not_filled":
        return "not_filled", 0.0, "not_filled"
    activation_time = parse_utc3(sig["activation_time"])
    if activation_time is None:
        return "not_filled", 0.0, "not_filled"
    direction = sig["direction"]
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    risk = abs(entry - sl)
    timeout = activation_time + pd.Timedelta(days=TIMEOUT_DAYS)

    sim_1m = df_1m[(df_1m.index >= activation_time) & (df_1m.index <= timeout)]
    sl_t = None
    for ts, c in sim_1m.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG" and l <= sl:
            sl_t = ts
            break
        if direction == "SHORT" and h >= sl:
            sl_t = ts
            break

    if direction == "SHORT":
        # Stoch cross exit
        sim_1h = df_1h[(df_1h.index >= activation_time) & (df_1h.index <= timeout)]
        cross_t = None
        cross_p = None
        prev_diff = None
        for ts in sim_1h.index:
            r = rsi_mod.loc[ts] if ts in rsi_mod.index else None
            s = stc_rsi_mod.loc[ts] if ts in stc_rsi_mod.index else None
            if r is None or s is None or np.isnan(r) or np.isnan(s):
                prev_diff = None
                continue
            diff = r - s
            if prev_diff is not None and prev_diff <= 0 and diff > 0:
                cross_t = ts
                cross_p = float(sim_1h.loc[ts, "close"])
                break
            prev_diff = diff

        candidates = []
        if sl_t is not None:
            candidates.append((sl_t, "sl", sl))
        if cross_t is not None:
            candidates.append((cross_t, "stoch_cross", cross_p))
        if not candidates:
            return "timeout", 0.0, "timeout"
        candidates.sort(key=lambda x: x[0])
        t, kind, price = candidates[0]
        r_real = (entry - price) / risk
        out = "win" if r_real > 0 else ("loss" if r_real < 0 else "open")
        return out, r_real, kind
    else:
        # LONG — фикс RR=1 (контроль)
        tp = entry + risk
        sim = df_1m[df_1m.index >= activation_time]
        for ts, c in sim.iterrows():
            h, l = float(c["high"]), float(c["low"])
            if l <= sl:
                return "loss", -1.0, "sl"
            if h >= tp:
                return "win", 1.0, "tp"
        return "open", 0.0, "open"


def report(label, sub, RR=RR, key="c4_R", outcome_key="c4_outcome"):
    n = len(sub)
    if n == 0:
        print(f"  {label:<45s}  n=0")
        return
    cl = sub[sub[outcome_key].isin(["win", "loss"])]
    timeouts = (sub[outcome_key] == "timeout").sum()
    if len(cl) == 0:
        print(f"  {label:<45s}  n={n}  no closed")
        return
    w = int((cl[outcome_key] == "win").sum())
    l = len(cl) - w
    wr = w / len(cl) * 100
    total_r = sub[key].sum()
    rt = total_r / n
    print(f"  {label:<45s}  n={n:<3d} W={w} L={l} TO={timeouts}  "
          f"WR={wr:5.1f}%  TotalR={total_r:+5.1f}  R/tr={rt:+.3f}")


def main():
    print(f"[INFO] загрузка {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    print(f"  rows: {len(df)}")

    print(f"[INFO] загрузка {SYMBOL} 1m, 1h")
    df_1m = load_df(SYMBOL, "1m")
    df_1h = load_df(SYMBOL, "1h")

    print("[INFO] ASVK + MH series на 1h")
    ema_3 = adjusted_rsi(df_1h["close"])
    _, upper, lower = nwe_bands(ema_3, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)
    hlc3 = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3
    bw1, bw2, _ = wavetrend_blueWaves(hlc3, WT_N1, WT_N2)
    rsi_mod = sma(stoch(df_1h["close"], df_1h["high"], df_1h["low"], RSI_STOCH_LEN),
                  RSI_SMA)
    stc_rsi = sma(stoch(df_1h["close"], df_1h["high"], df_1h["low"], SRSI_STOCH_LEN),
                  RSI_SMA)

    print("[INFO] симуляция C4 dual-exit")
    c4_results = []
    for _, sig in df.iterrows():
        out, r, kind = simulate_dual_exit(sig, df_1m, df_1h, ema_3, upper, lower, bw2)
        c4_results.append({"c4_outcome": out, "c4_R": r, "c4_exit": kind})

    print("[INFO] симуляция C10 stoch-cross exit (для SHORT)")
    c10_results = []
    for _, sig in df.iterrows():
        out, r, kind = simulate_stoch_cross_exit(sig, df_1m, df_1h, rsi_mod, stc_rsi)
        c10_results.append({"c10_outcome": out, "c10_R": r, "c10_exit": kind})

    full = pd.concat([df.reset_index(drop=True),
                      pd.DataFrame(c4_results),
                      pd.DataFrame(c10_results)], axis=1)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    full.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")

    long_mask = full["direction"] == "LONG"
    short_mask = full["direction"] == "SHORT"

    print()
    print("=" * 100)
    print("C4 — DUAL EXIT (NWE OR bw2-zero-cross)")
    print("=" * 100)
    report("ALL", full, RR, "c4_R", "c4_outcome")
    report("LONG", full[long_mask], RR, "c4_R", "c4_outcome")
    report("SHORT", full[short_mask], RR, "c4_R", "c4_outcome")

    # Распределение exit type
    print()
    print("Распределение exit-типов:")
    for kind in ["sl", "nwe", "bw2_zero", "timeout", "not_filled"]:
        n_kind = (full["c4_exit"] == kind).sum()
        if n_kind > 0:
            sub = full[full["c4_exit"] == kind]
            avg_r = sub["c4_R"].mean()
            print(f"  {kind:<15s}  n={n_kind:<3d}  avg_R={avg_r:+.2f}")

    print()
    print("=" * 100)
    print("C10 — STOCH-CROSS EXIT для SHORT (LONG = фикс RR=1)")
    print("=" * 100)
    report("ALL", full, RR, "c10_R", "c10_outcome")
    report("LONG (фикс RR=1)", full[long_mask], RR, "c10_R", "c10_outcome")
    report("SHORT (Stoch cross)", full[short_mask], RR, "c10_R", "c10_outcome")

    print()
    print("Сравнение SHORT по разным exit-стратегиям:")
    short_sub = full[short_mask]
    s_orig_r = ((short_sub["outcome"] == "win").sum() * RR
                - (short_sub["outcome"] == "loss").sum())
    print(f"  RR=1 фикс (orig):       n={len(short_sub)}  TotalR={s_orig_r:+5.1f}  R/tr={s_orig_r/len(short_sub):+.3f}")
    s_c4 = short_sub["c4_R"].sum()
    print(f"  C4 dual-exit (NWE+bw2): n={len(short_sub)}  TotalR={s_c4:+5.1f}  R/tr={s_c4/len(short_sub):+.3f}")
    s_c10 = short_sub["c10_R"].sum()
    print(f"  C10 stoch-cross:        n={len(short_sub)}  TotalR={s_c10:+5.1f}  R/tr={s_c10/len(short_sub):+.3f}")


if __name__ == "__main__":
    main()
