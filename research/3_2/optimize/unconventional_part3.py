"""Partition 3: N6 (ATR-normalized SL) и N10 (hybrid TP) — re-симуляция.

N6: SL = c0_low - k * ATR(14_at_signal). Перебираем k ∈ {0.5, 1.0, 1.5, 2.0}.
N10: 50% позиции exit при фикс RR=1, 50% оставляем под dual-exit (NWE OR bw2-zero).
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
from plot_money_hands import WT_N1, WT_N2, wavetrend_blueWaves

INPUT_CSV = Path("signals/strategy_3_2_3y_RR1_unconventional.csv")
OUT_CSV = Path("signals/strategy_3_2_unconventional_p3.csv")
SYMBOL = "BTCUSDT"
TIMEOUT_DAYS = 14


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def simulate_atr_sl(sig, df_1m, df_1h, atr14, k_atr, rr=1.0):
    """N6: SL = original_c0_low - k*ATR (LONG); high+k*ATR (SHORT). Entry/TP по RR."""
    direction = sig["direction"]
    entry = float(sig["entry"])
    fvg_bot = float(sig["fvg_1h_bottom"])
    fvg_top = float(sig["fvg_1h_top"])
    signal_time = parse_utc3(sig["signal_time"])
    if signal_time is None:
        return "not_filled", 0.0
    ipos = df_1h.index.get_indexer([signal_time], method="ffill")[0]
    if ipos < 0:
        return "not_filled", 0.0
    atr = atr14.iloc[ipos]
    if pd.isna(atr) or atr <= 0:
        return "not_filled", 0.0

    # Modified SL — за c0_low/high с буфером k*ATR.
    # Используем оригинальный sl как базу (с0_low / с0_high)
    sl_orig = float(sig["sl"])
    if direction == "LONG":
        sl = sl_orig - k_atr * atr  # ниже (= шире)
        risk = entry - sl
        tp = entry + risk * rr
    else:
        sl = sl_orig + k_atr * atr
        risk = sl - entry
        tp = entry - risk * rr
    if risk <= 0:
        return "not_filled", 0.0

    # Активация — стандартная (с close c2 1h FVG)
    fill_start = signal_time + pd.Timedelta(minutes=60)
    forward = df_1m[df_1m.index >= fill_start]
    activation = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG" and l <= entry:
            activation = ts
            break
        if direction == "SHORT" and h >= entry:
            activation = ts
            break
    if activation is None:
        return "not_filled", 0.0

    timeout = activation + pd.Timedelta(days=TIMEOUT_DAYS)
    sim = df_1m[(df_1m.index >= activation) & (df_1m.index <= timeout)]
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= sl:
                return "loss", -1.0  # фикс -1R по построению (ATR adjusted)
            if h >= tp:
                return "win", rr
        else:
            if h >= sl:
                return "loss", -1.0
            if l <= tp:
                return "win", rr
    return "open", 0.0


def simulate_hybrid_tp(sig, df_1m, df_1h, ema_3, upper, lower, bw2):
    """N10: 50% при фикс RR=1, 50% при dual-exit (NWE OR bw2-zero)."""
    if sig["outcome"] == "not_filled":
        return "not_filled", 0.0
    activation = parse_utc3(sig["activation_time"])
    if activation is None:
        return "not_filled", 0.0
    direction = sig["direction"]
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    tp_fix = float(sig["tp"])
    risk = abs(entry - sl)
    timeout = activation + pd.Timedelta(days=TIMEOUT_DAYS)

    # SL
    sim_1m = df_1m[(df_1m.index >= activation) & (df_1m.index <= timeout)]
    sl_t = None
    tp1_t = None  # фикс TP (50% часть)
    for ts, c in sim_1m.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= sl and sl_t is None:
                sl_t = ts
            if h >= tp_fix and tp1_t is None:
                tp1_t = ts
        else:
            if h >= sl and sl_t is None:
                sl_t = ts
            if l <= tp_fix and tp1_t is None:
                tp1_t = ts
        if sl_t and tp1_t:
            break

    # Dual-exit (NWE OR bw2-zero) для второй половины
    sim_1h = df_1h[(df_1h.index >= activation) & (df_1h.index <= timeout)]
    de_t = None
    de_p = None
    for ts in sim_1h.index:
        em = ema_3.loc[ts] if ts in ema_3.index else None
        up = upper.loc[ts] if ts in upper.index else None
        lo = lower.loc[ts] if ts in lower.index else None
        b = bw2.loc[ts] if ts in bw2.index else None
        if em is None or up is None or lo is None or b is None:
            continue
        if not (np.isnan(em) or np.isnan(up) or np.isnan(lo)):
            if direction == "LONG" and em > up and de_t is None:
                de_t = ts
                de_p = float(sim_1h.loc[ts, "close"])
            if direction == "SHORT" and em < lo and de_t is None:
                de_t = ts
                de_p = float(sim_1h.loc[ts, "close"])
        if not np.isnan(b):
            if direction == "LONG" and b < 0 and de_t is None:
                de_t = ts
                de_p = float(sim_1h.loc[ts, "close"])
            if direction == "SHORT" and b > 0 and de_t is None:
                de_t = ts
                de_p = float(sim_1h.loc[ts, "close"])

    # Логика:
    # 1) Если SL hit ДО любого позитивного exit → 100% позиции в loss = -1R
    # 2) Если TP_fix hit ДО SL → 50% закрыли с +1R, остальные 50% продолжают
    #    - если потом dual-exit срабатывает раньше SL → +50% R от dual exit
    #    - если SL срабатывает раньше → 50% loss → НО SL уже после tp_fix, так что 50% уже closed.
    #      В этой ситуации 50% loss = -0.5R; общий: 0.5*1 + 0.5*(-1) = 0
    # 3) Если dual_exit hit раньше fix_tp и раньше SL → выходим вс 100% по dual.

    candidates = []
    if sl_t:
        candidates.append((sl_t, "sl"))
    if tp1_t:
        candidates.append((tp1_t, "tp_fix"))
    if de_t:
        candidates.append((de_t, "dual"))
    if not candidates:
        return "timeout", 0.0
    candidates.sort(key=lambda x: x[0])
    first_t, first_kind = candidates[0]

    if first_kind == "sl":
        return "loss", -1.0
    if first_kind == "dual":
        if direction == "LONG":
            r = (de_p - entry) / risk
        else:
            r = (entry - de_p) / risk
        return ("win" if r > 0 else "loss"), r
    # first_kind == "tp_fix"
    # 50% закрыли с +1R; ищем что случилось со 2й половиной
    second_candidates = []
    if sl_t and sl_t > first_t:
        second_candidates.append((sl_t, "sl_after_partial"))
    if de_t and de_t > first_t:
        second_candidates.append((de_t, "dual_after_partial"))
    if not second_candidates:
        # 2-я часть никогда не закрылась — таймаут / open
        return "win_partial_open", 0.5  # 50% × 1R только
    second_candidates.sort(key=lambda x: x[0])
    second_t, second_kind = second_candidates[0]
    if second_kind == "sl_after_partial":
        # 50% × 1R + 50% × (-1R) = 0
        return "be", 0.0
    # dual_after_partial
    if direction == "LONG":
        r2 = (de_p - entry) / risk
    else:
        r2 = (entry - de_p) / risk
    total = 0.5 * 1.0 + 0.5 * r2
    return ("win" if total > 0 else "loss"), total


def main():
    print(f"[INFO] загрузка {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)
    print(f"  rows: {len(df)}")

    print(f"[INFO] загрузка {SYMBOL} 1m, 1h")
    df_1m = load_df(SYMBOL, "1m")
    df_1h = load_df(SYMBOL, "1h")

    print("[INFO] ATR(14) на 1h")
    high = df_1h["high"]
    low = df_1h["low"]
    close = df_1h["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()

    print("[INFO] ASVK + MH series для N10")
    ema_3 = adjusted_rsi(df_1h["close"])
    _, upper, lower = nwe_bands(ema_3, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)
    hlc3 = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3
    bw1, bw2, _ = wavetrend_blueWaves(hlc3, WT_N1, WT_N2)

    # ---------- N6: ATR-SL sweep ----------
    print()
    print("=" * 100)
    print("N6 — ATR-NORMALIZED SL  (SL = orig_sl ± k*ATR(14))")
    print("=" * 100)
    print(f"{'k':<6} {'closed':<7} {'WR':<8} {'TotalR':<10} {'R/tr':<8} {'not_filled':<10}")
    for k in [0.0, 0.5, 1.0, 1.5, 2.0]:
        rows = [simulate_atr_sl(s, df_1m, df_1h, atr14, k, rr=1.0)
                for _, s in df.iterrows()]
        outs = [r[0] for r in rows]
        rs = [r[1] for r in rows]
        n_closed = sum(1 for o in outs if o in ("win", "loss"))
        n_w = sum(1 for o in outs if o == "win")
        n_nf = sum(1 for o in outs if o == "not_filled")
        wr = n_w / n_closed * 100 if n_closed else 0
        tot = sum(rs)
        rt = tot / len(rs) if rs else 0
        print(f"{k:<6} {n_closed:<7} {wr:<8.1f} {tot:+10.1f} {rt:+8.3f} {n_nf:<10}")
    print()

    # ---------- N10: Hybrid TP ----------
    print("=" * 100)
    print("N10 — HYBRID TP (50% fix RR=1 + 50% dual-exit)")
    print("=" * 100)
    rows = [simulate_hybrid_tp(s, df_1m, df_1h, ema_3, upper, lower, bw2)
            for _, s in df.iterrows()]
    outs = [r[0] for r in rows]
    rs = [r[1] for r in rows]
    n_total = len([o for o in outs if o != "not_filled"])
    print(f"Outcomes:")
    for o in set(outs):
        n = sum(1 for x in outs if x == o)
        print(f"  {o}: {n}")
    tot = sum(rs)
    rt = tot / len(rs) if rs else 0
    print(f"Hybrid TP total: {tot:+.1f}R  R/tr={rt:+.3f}  на {len(rs)} сделках")

    # comparison
    closed = df[df["outcome"].isin(["win", "loss"])]
    base_w = (closed["outcome"] == "win").sum()
    base_l = (closed["outcome"] == "loss").sum()
    base_total = base_w * 1.0 - base_l
    print()
    print("Сравнение exit-стратегий:")
    print(f"  Baseline RR=1 fixed:        TotalR={base_total:+.1f}R  R/tr={base_total/len(closed):+.3f}")
    print(f"  C4 dual-exit ALL:           TotalR=+90.7R  R/tr=+0.370 (из combined p2)")
    print(f"  N10 hybrid (50f + 50d):     TotalR={tot:+.1f}R  R/tr={rt:+.3f}")

    # save
    df["n10_outcome"] = outs
    df["n10_R"] = rs
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\n[OK] saved: {OUT_CSV}")


if __name__ == "__main__":
    main()
