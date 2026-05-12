"""ASVK RSI-метрики на каждый сигнал 3.2 + сегментированный отчёт по 7 гипотезам.

Загружает signals/strategy_3_2_3y_RR1.csv, расширяет колонками RSI на момент
signal_time, считает WR/PnL по сегментам, печатает сводку и сохраняет
расширенный CSV.

Гипотезы (см. чат 2026-05-06):
  H1 — divergence в окне [touch_time-6h, signal_time]
  H2 — режим по z_above (bull/range/bear)
  H3 — ema_3 в OB/OS зоне vs current_value_above/below
  H4 — ema_3 пробил NWE-канал
  H5 — структурный shift между fvg_4h.c2_time и signal_time
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
if str(_RSI_DIR) not in _sys.path:
    _sys.path.insert(0, str(_RSI_DIR))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df
from plot_asvk_rsi import (
    BARS_TO_LOOK_BACK,
    LB_L, LB_R, LOCAL_EMA_LEN,
    NWE_BANDWIDTH, NWE_BAR, NWE_MULTIPLIER,
    RANGE_LOWER, RANGE_UPPER,
    adjusted_rsi, dynamic_levels, find_divergences,
    local_extrema_ema, nwe_bands,
)

SYMBOL = "BTCUSDT"
SIGNALS_CSV = Path("signals/strategy_3_2_3y_RR1.csv")
OUT_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk.csv")
RR = 1.0


def parse_utc3(ts_str: str) -> pd.Timestamp | None:
    if not ts_str or pd.isna(ts_str):
        return None
    return pd.Timestamp(ts_str, tz="UTC") - pd.Timedelta(hours=3)


def stats(closed: pd.DataFrame, label: str, total_closed: int) -> str:
    n = len(closed)
    if n == 0:
        return f"  {label:<35s}  n=0"
    w = int((closed["outcome"] == "win").sum())
    l = n - w
    wr = w / n * 100
    pnl = w * RR - l
    share = n / total_closed * 100 if total_closed else 0
    return (f"  {label:<35s}  n={n:<4d} ({share:5.1f}%)  "
            f"W={w:<3d} L={l:<3d}  WR={wr:5.1f}%  PnL={pnl:+6.1f}R")


def segment_report(df_closed: pd.DataFrame, mask, group_a_label: str, group_b_label: str = None):
    total = len(df_closed)
    print(stats(df_closed[mask], group_a_label, total))
    if group_b_label is not None:
        print(stats(df_closed[~mask], group_b_label, total))


def main():
    print(f"[INFO] загрузка {SIGNALS_CSV}")
    sigs = pd.read_csv(SIGNALS_CSV)
    print(f"  rows: {len(sigs)}")

    print(f"[INFO] загрузка {SYMBOL} 1h")
    df_1h = load_df(SYMBOL, "1h")
    print(f"  bars: {len(df_1h)}")

    print("[INFO] расчёт ASVK RSI на всём 1h")
    ema_3 = adjusted_rsi(df_1h["close"])
    above, below = dynamic_levels(ema_3, BARS_TO_LOOK_BACK)
    nwe_mid, upper, lower = nwe_bands(ema_3, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)
    bull, h_bull, bear, h_bear = find_divergences(
        ema_3, df_1h["low"], df_1h["high"],
        LB_L, LB_R, RANGE_LOWER, RANGE_UPPER,
    )
    ema_l_struct, ema_h_struct = local_extrema_ema(ema_3, LOCAL_EMA_LEN)

    # z_above counter — rolling count(ema_3 > 50, 200)
    z_above = (ema_3 > 50).rolling(BARS_TO_LOOK_BACK).sum()

    # Дивергенции → списки UTC-времён confirmation (когда div стала известна = idx i,
    # т.е. df_1h.index[i] = время свечи следом за center).
    def to_times(divs):
        return pd.DatetimeIndex(
            [df_1h.index[d[0] + LB_R] for d in divs] if divs else [],
            tz="UTC",
        )
    bull_times = to_times(bull)
    h_bull_times = to_times(h_bull)
    bear_times = to_times(bear)
    h_bear_times = to_times(h_bear)
    print(f"  divs: bull={len(bull_times)} h_bull={len(h_bull_times)} "
          f"bear={len(bear_times)} h_bear={len(h_bear_times)}")

    # Структурные shifts: моменты, когда emaL/emaH меняются.
    struct_l_change = (ema_l_struct != ema_l_struct.shift(1)) & ema_l_struct.notna()
    struct_h_change = (ema_h_struct != ema_h_struct.shift(1)) & ema_h_struct.notna()
    struct_low_times = df_1h.index[struct_l_change.values]
    struct_high_times = df_1h.index[struct_h_change.values]

    print("[INFO] обогащение сигналов")
    new_cols = {
        "rsi_at_signal": [],
        "above_at_signal": [],
        "below_at_signal": [],
        "nwe_upper_at_signal": [],
        "nwe_lower_at_signal": [],
        "z_above_at_signal": [],
        "bull_div_in_window": [],
        "h_bull_div_in_window": [],
        "bear_div_in_window": [],
        "h_bear_div_in_window": [],
        "structure_shift_long_in_window": [],
        "structure_shift_short_in_window": [],
    }
    div_window_h = 6  # H1: окно [touch_time - 6h, signal_time]

    for _, sig in sigs.iterrows():
        st = parse_utc3(sig["signal_time"])
        tt = parse_utc3(sig["touch_time"])
        fvg_c2 = parse_utc3(sig["fvg_4h_c2_time"])
        direction = sig["direction"]

        # Точка-снимок индикаторов на signal_time (берём бар СРАЗУ ДО или НА signal_time:
        # signal_time = open_time c2 1h FVG; индикатор на этом баре уже валиден).
        idx_pos = df_1h.index.get_indexer([st], method="ffill")[0]
        if idx_pos < 0:
            for k in new_cols:
                new_cols[k].append(np.nan)
            continue

        new_cols["rsi_at_signal"].append(float(ema_3.iloc[idx_pos]))
        new_cols["above_at_signal"].append(float(above.iloc[idx_pos]))
        new_cols["below_at_signal"].append(float(below.iloc[idx_pos]))
        new_cols["nwe_upper_at_signal"].append(float(upper.iloc[idx_pos]))
        new_cols["nwe_lower_at_signal"].append(float(lower.iloc[idx_pos]))
        new_cols["z_above_at_signal"].append(float(z_above.iloc[idx_pos]))

        div_lo = tt - pd.Timedelta(hours=div_window_h)
        div_hi = st
        in_div_window = lambda times: bool(((times >= div_lo) & (times <= div_hi)).any())
        new_cols["bull_div_in_window"].append(in_div_window(bull_times))
        new_cols["h_bull_div_in_window"].append(in_div_window(h_bull_times))
        new_cols["bear_div_in_window"].append(in_div_window(bear_times))
        new_cols["h_bear_div_in_window"].append(in_div_window(h_bear_times))

        # Structure shift в окне [fvg_4h.c2_time, signal_time]
        sl_lo = fvg_c2
        sl_hi = st
        in_struct = lambda times: bool(((times >= sl_lo) & (times <= sl_hi)).any())
        new_cols["structure_shift_long_in_window"].append(in_struct(struct_low_times))
        new_cols["structure_shift_short_in_window"].append(in_struct(struct_high_times))

    enriched = pd.concat([sigs, pd.DataFrame(new_cols)], axis=1)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved enriched CSV: {OUT_CSV}")

    # ========== СЕГМЕНТНЫЙ ОТЧЁТ ==========
    closed = enriched[enriched["outcome"].isin(["win", "loss"])].copy()
    print()
    print("=" * 78)
    print(f"BASELINE 3.2  RR={RR}  closed={len(closed)}")
    print("=" * 78)
    w = int((closed["outcome"] == "win").sum())
    l = len(closed) - w
    wr = w / len(closed) * 100 if len(closed) else 0
    print(f"  total: W={w}  L={l}  WR={wr:.1f}%  PnL={w*RR - l:+.1f}R")

    print()
    print("=" * 78)
    print("H1 — DIVERGENCE в окне [touch-6h, signal]")
    print("=" * 78)
    print("  LONG-сегмент (нужны bull/h_bull):")
    long_mask = closed["direction"] == "LONG"
    long_div = closed["bull_div_in_window"] | closed["h_bull_div_in_window"]
    long_closed = closed[long_mask]
    if len(long_closed):
        print(stats(long_closed[long_div[long_mask]], "  LONG + div", len(long_closed)))
        print(stats(long_closed[~long_div[long_mask]], "  LONG no div", len(long_closed)))
    print("  SHORT-сегмент (нужны bear/h_bear):")
    short_mask = closed["direction"] == "SHORT"
    short_div = closed["bear_div_in_window"] | closed["h_bear_div_in_window"]
    short_closed = closed[short_mask]
    if len(short_closed):
        print(stats(short_closed[short_div[short_mask]], "  SHORT + div", len(short_closed)))
        print(stats(short_closed[~short_div[short_mask]], "  SHORT no div", len(short_closed)))
    print("  TOTAL:")
    div_aligned = (long_mask & long_div) | (short_mask & short_div)
    print(stats(closed[div_aligned], "ALL with aligned div", len(closed)))
    print(stats(closed[~div_aligned], "ALL without div", len(closed)))

    print()
    print("=" * 78)
    print("H2 — РЕЖИМ по z_above (cnt ema_3>50 за 200 баров; max=200)")
    print("=" * 78)
    bull_regime = closed["z_above_at_signal"] > 130
    bear_regime = closed["z_above_at_signal"] < 70
    range_regime = ~bull_regime & ~bear_regime
    print("  Bull regime (z>130) — pro-trend для LONG, counter для SHORT:")
    print(stats(closed[bull_regime & long_mask], "  LONG (pro-trend)", len(closed)))
    print(stats(closed[bull_regime & short_mask], "  SHORT (counter-trend)", len(closed)))
    print("  Bear regime (z<70):")
    print(stats(closed[bear_regime & long_mask], "  LONG (counter-trend)", len(closed)))
    print(stats(closed[bear_regime & short_mask], "  SHORT (pro-trend)", len(closed)))
    print("  Range (70<=z<=130):")
    print(stats(closed[range_regime & long_mask], "  LONG (range)", len(closed)))
    print(stats(closed[range_regime & short_mask], "  SHORT (range)", len(closed)))
    print("  Только pro-trend сегменты:")
    pro_trend = (bull_regime & long_mask) | (bear_regime & short_mask)
    print(stats(closed[pro_trend], "PRO-TREND only", len(closed)))
    print(stats(closed[~pro_trend], "non pro-trend", len(closed)))

    print()
    print("=" * 78)
    print("H3 — ema_3 в OB/OS зоне на signal_time")
    print("=" * 78)
    long_in_os = long_mask & (closed["rsi_at_signal"] < closed["below_at_signal"])
    long_not_os = long_mask & ~(closed["rsi_at_signal"] < closed["below_at_signal"])
    short_in_ob = short_mask & (closed["rsi_at_signal"] > closed["above_at_signal"])
    short_not_ob = short_mask & ~(closed["rsi_at_signal"] > closed["above_at_signal"])
    print(stats(closed[long_in_os], "LONG + ema_3<below (OS)", len(closed)))
    print(stats(closed[long_not_os], "LONG outside OS", len(closed)))
    print(stats(closed[short_in_ob], "SHORT + ema_3>above (OB)", len(closed)))
    print(stats(closed[short_not_ob], "SHORT outside OB", len(closed)))
    aligned = long_in_os | short_in_ob
    print(stats(closed[aligned], "ALL aligned (in extreme)", len(closed)))
    print(stats(closed[~aligned], "ALL not aligned", len(closed)))

    print()
    print("=" * 78)
    print("H4 — ema_3 vs NWE bands на signal_time")
    print("=" * 78)
    long_below_nwe = long_mask & (closed["rsi_at_signal"] < closed["nwe_lower_at_signal"])
    short_above_nwe = short_mask & (closed["rsi_at_signal"] > closed["nwe_upper_at_signal"])
    print(stats(closed[long_below_nwe], "LONG + ema_3<nwe_lower", len(closed)))
    print(stats(closed[long_mask & ~long_below_nwe[long_mask].reindex(closed.index, fill_value=False)],
                "LONG inside/above nwe_lower", len(closed)))
    print(stats(closed[short_above_nwe], "SHORT + ema_3>nwe_upper", len(closed)))
    nwe_aligned = long_below_nwe | short_above_nwe
    print(stats(closed[nwe_aligned], "ALL aligned (NWE extreme)", len(closed)))
    print(stats(closed[~nwe_aligned], "ALL not aligned", len(closed)))

    print()
    print("=" * 78)
    print("H5 — STRUCTURE SHIFT в окне [fvg_4h.c2, signal_time]")
    print("=" * 78)
    long_struct = long_mask & closed["structure_shift_long_in_window"]
    short_struct = short_mask & closed["structure_shift_short_in_window"]
    print(stats(closed[long_struct], "LONG + struct shift up", len(closed)))
    print(stats(closed[short_struct], "SHORT + struct shift down", len(closed)))
    struct_aligned = long_struct | short_struct
    print(stats(closed[struct_aligned], "ALL with struct shift", len(closed)))
    print(stats(closed[~struct_aligned], "ALL without", len(closed)))

    print()
    print("=" * 78)
    print("ИТОГ — top сегменты с edge >= baseline (+5% WR или PnL/trade > 0.10R)")
    print("=" * 78)
    candidates = []
    baseline_wr = wr
    candidates.append(("H1: ALL with aligned div", closed[div_aligned]))
    candidates.append(("H2: PRO-TREND only", closed[pro_trend]))
    candidates.append(("H3: ALL in extreme zone", closed[aligned]))
    candidates.append(("H4: ALL NWE extreme", closed[nwe_aligned]))
    candidates.append(("H5: ALL with struct shift", closed[struct_aligned]))
    rows = []
    for label, df_seg in candidates:
        n = len(df_seg)
        if n == 0:
            continue
        w_ = int((df_seg["outcome"] == "win").sum())
        l_ = n - w_
        wr_ = w_ / n * 100
        pnl_ = w_ * RR - l_
        rows.append((label, n, wr_, pnl_, pnl_ / n))
    rows.sort(key=lambda r: -r[4])  # by R/trade
    print(f"  baseline: n={len(closed)}  WR={baseline_wr:.1f}%  R/trade={(w*RR - l)/len(closed):.3f}")
    print()
    for label, n, wr_, pnl_, rt in rows:
        marker = "*" if (wr_ >= baseline_wr + 3 or rt >= 0.10) else " "
        print(f"  {marker} {label:<35s}  n={n:<4d}  WR={wr_:5.1f}%  "
              f"PnL={pnl_:+6.1f}R  R/trade={rt:+.3f}")


if __name__ == "__main__":
    main()
