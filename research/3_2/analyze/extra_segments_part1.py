"""ASVK partition 1: H8 (div depth), H10 (RSI vorticity), H11 (bars-since-extreme),
H16 (div OR NWE-extreme), H17 (regime percentile).

Все — pre-entry segmentation, НЕ требуют re-simulation. Использует existing
strategy_3_2_3y_RR1.csv + считает ASVK заново для добавления новых колонок.
Сохраняет enriched CSV part1 с новыми колонками.
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
    BARS_TO_LOOK_BACK, LB_L, LB_R,
    NWE_BANDWIDTH, NWE_BAR, NWE_MULTIPLIER,
    RANGE_LOWER, RANGE_UPPER,
    adjusted_rsi, dynamic_levels,
    nwe_bands, _pivot,
)

SYMBOL = "BTCUSDT"
SIGNALS_CSV = Path("signals/strategy_3_2_3y_RR1.csv")
OUT_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_part1.csv")
RR = 1.0
DIV_WINDOW_HOURS = 6
ROLLING_YEAR_BARS = 24 * 365  # ~ для percentile z_above
H11_LOOKBACK = 100  # bars-since-extreme окно


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def find_divergences_with_depth(osc, low, high, lb_l, lb_r, range_lower, range_upper):
    """Расширенный find_divergences: возвращает (i, center, cur_osc, prev_osc,
    cur_price, prev_price, depth) для каждого типа.

    depth = |Δosc / Δprice| × |Δosc| (нормированная глубина — больше = «жёстче» div).
    """
    pl = _pivot(osc, lb_l, lb_r, "low")
    ph = _pivot(osc, lb_l, lb_r, "high")
    n = len(osc)

    bull, h_bull, bear, h_bear = [], [], [], []

    last_pl = None  # (i, center, osc_v, price_v)
    for i in range(n):
        if not np.isnan(pl.iloc[i]):
            center = i - lb_r
            cur_osc = osc.iloc[center]
            cur_price = low.iloc[center]
            if last_pl is not None:
                bars_since = i - last_pl[0]
                if range_lower <= bars_since <= range_upper:
                    d_osc = cur_osc - last_pl[2]
                    d_price = cur_price - last_pl[3]
                    if d_price != 0:
                        depth = abs(d_osc / d_price * cur_price * 0.01)  # %-нормировка
                    else:
                        depth = abs(d_osc)
                    if cur_price < last_pl[3] and cur_osc > last_pl[2]:
                        bull.append((i, center, cur_osc, last_pl[2], cur_price, last_pl[3], depth))
                    if cur_price > last_pl[3] and cur_osc < last_pl[2]:
                        h_bull.append((i, center, cur_osc, last_pl[2], cur_price, last_pl[3], depth))
            last_pl = (i, center, cur_osc, cur_price)

    last_ph = None
    for i in range(n):
        if not np.isnan(ph.iloc[i]):
            center = i - lb_r
            cur_osc = osc.iloc[center]
            cur_price = high.iloc[center]
            if last_ph is not None:
                bars_since = i - last_ph[0]
                if range_lower <= bars_since <= range_upper:
                    d_osc = cur_osc - last_ph[2]
                    d_price = cur_price - last_ph[3]
                    if d_price != 0:
                        depth = abs(d_osc / d_price * cur_price * 0.01)
                    else:
                        depth = abs(d_osc)
                    if cur_price > last_ph[3] and cur_osc < last_ph[2]:
                        bear.append((i, center, cur_osc, last_ph[2], cur_price, last_ph[3], depth))
                    if cur_price < last_ph[3] and cur_osc > last_ph[2]:
                        h_bear.append((i, center, cur_osc, last_ph[2], cur_price, last_ph[3], depth))
            last_ph = (i, center, cur_osc, cur_price)

    return bull, h_bull, bear, h_bear


def stats(closed: pd.DataFrame, label: str, total: int) -> str:
    n = len(closed)
    if n == 0:
        return f"  {label:<40s}  n=0"
    w = int((closed["outcome"] == "win").sum())
    l = n - w
    wr = w / n * 100
    pnl = w * RR - l
    rt = pnl / n
    share = n / total * 100 if total else 0
    return (f"  {label:<40s}  n={n:<4d} ({share:5.1f}%)  W={w:<3d} L={l:<3d}  "
            f"WR={wr:5.1f}%  PnL={pnl:+6.1f}R  R/tr={rt:+.3f}")


def main():
    print(f"[INFO] загрузка signals: {SIGNALS_CSV}")
    sigs = pd.read_csv(SIGNALS_CSV)
    print(f"  rows: {len(sigs)}")

    print(f"[INFO] загрузка {SYMBOL} 1h")
    df_1h = load_df(SYMBOL, "1h")
    print(f"  bars: {len(df_1h)}")

    print("[INFO] ASVK на всём 1h")
    ema_3 = adjusted_rsi(df_1h["close"])
    above, below = dynamic_levels(ema_3, BARS_TO_LOOK_BACK)
    nwe_mid, upper, lower = nwe_bands(ema_3, NWE_BAR, NWE_BANDWIDTH, NWE_MULTIPLIER)

    bull, h_bull, bear, h_bear = find_divergences_with_depth(
        ema_3, df_1h["low"], df_1h["high"],
        LB_L, LB_R, RANGE_LOWER, RANGE_UPPER,
    )

    # Списки времён confirmation + depths
    def to_records(divs):
        if not divs:
            return pd.DatetimeIndex([], tz="UTC"), np.array([])
        idx = pd.DatetimeIndex([df_1h.index[d[0]] for d in divs], tz="UTC")
        depths = np.array([d[6] for d in divs])
        return idx, depths

    bull_t, bull_d = to_records(bull)
    h_bull_t, h_bull_d = to_records(h_bull)
    bear_t, bear_d = to_records(bear)
    h_bear_t, h_bear_d = to_records(h_bear)
    print(f"  divs: bull={len(bull_t)} h_bull={len(h_bull_t)} "
          f"bear={len(bear_t)} h_bear={len(h_bear_t)}")

    # z_above + percentile
    z_above = (ema_3 > 50).rolling(BARS_TO_LOOK_BACK).sum()
    # Percentile rank: для каждого бара — какой процент значений z за прошедший
    # год был меньше текущего. По сути rolling.rank(pct=True).
    z_pct = z_above.rolling(ROLLING_YEAR_BARS, min_periods=BARS_TO_LOOK_BACK + 1).rank(pct=True)

    # ema_3 in OB / OS history (для H11)
    ob_mask = ema_3 > above
    os_mask = ema_3 < below
    # bars_since_ob[i] = расстояние от i до последнего True в ob_mask[:i+1]
    # cumulative trick: индекс последнего True
    last_ob_idx = pd.Series(np.where(ob_mask, np.arange(len(ema_3)), np.nan), index=ema_3.index).ffill()
    last_os_idx = pd.Series(np.where(os_mask, np.arange(len(ema_3)), np.nan), index=ema_3.index).ffill()
    bars_arr = np.arange(len(ema_3), dtype=float)
    bars_since_ob = pd.Series(bars_arr - last_ob_idx.values, index=ema_3.index)
    bars_since_os = pd.Series(bars_arr - last_os_idx.values, index=ema_3.index)

    print("[INFO] обогащение сигналов новыми колонками")
    new_cols = {
        "rsi_at_signal": [], "above_at_signal": [], "below_at_signal": [],
        "nwe_upper_at_signal": [], "nwe_lower_at_signal": [],
        "z_above_at_signal": [], "z_pct_at_signal": [],
        # H8 — depth
        "max_bull_depth_in_window": [], "max_h_bull_depth_in_window": [],
        "max_bear_depth_in_window": [], "max_h_bear_depth_in_window": [],
        # H10 — vorticity (delta ema_3 между touch_plus1 и signal_time)
        "rsi_at_touch_plus1": [], "rsi_velocity": [],
        # H11 — bars-since-extreme
        "bars_since_ob": [], "bars_since_os": [],
        # NWE extreme bool (для H16)
        "nwe_extreme_aligned": [],
        # legacy bools (для совместимости с предыдущим анализом)
        "bull_div_in_window": [], "h_bull_div_in_window": [],
        "bear_div_in_window": [], "h_bear_div_in_window": [],
    }

    for _, sig in sigs.iterrows():
        st = parse_utc3(sig["signal_time"])
        tt = parse_utc3(sig["touch_time"])
        # touch_plus1_time = touch_time + 4h (по построению 3.2)
        tp1 = tt + pd.Timedelta(hours=4) if tt is not None else None

        idx_pos = df_1h.index.get_indexer([st], method="ffill")[0]
        if idx_pos < 0:
            for k in new_cols:
                new_cols[k].append(np.nan)
            continue

        rsi_v = float(ema_3.iloc[idx_pos])
        above_v = float(above.iloc[idx_pos])
        below_v = float(below.iloc[idx_pos])
        nwe_up = float(upper.iloc[idx_pos])
        nwe_lo = float(lower.iloc[idx_pos])
        new_cols["rsi_at_signal"].append(rsi_v)
        new_cols["above_at_signal"].append(above_v)
        new_cols["below_at_signal"].append(below_v)
        new_cols["nwe_upper_at_signal"].append(nwe_up)
        new_cols["nwe_lower_at_signal"].append(nwe_lo)
        new_cols["z_above_at_signal"].append(float(z_above.iloc[idx_pos]))
        new_cols["z_pct_at_signal"].append(
            float(z_pct.iloc[idx_pos]) if not np.isnan(z_pct.iloc[idx_pos]) else np.nan
        )
        new_cols["bars_since_ob"].append(float(bars_since_ob.iloc[idx_pos]))
        new_cols["bars_since_os"].append(float(bars_since_os.iloc[idx_pos]))

        # touch_plus1 → ema_3 для velocity (H10)
        if tp1 is not None:
            ipos2 = df_1h.index.get_indexer([tp1], method="ffill")[0]
            if ipos2 >= 0:
                rsi_tp1 = float(ema_3.iloc[ipos2])
                new_cols["rsi_at_touch_plus1"].append(rsi_tp1)
                new_cols["rsi_velocity"].append(rsi_v - rsi_tp1)
            else:
                new_cols["rsi_at_touch_plus1"].append(np.nan)
                new_cols["rsi_velocity"].append(np.nan)
        else:
            new_cols["rsi_at_touch_plus1"].append(np.nan)
            new_cols["rsi_velocity"].append(np.nan)

        # Дивергенции в окне [touch - 6h, signal_time]
        div_lo = tt - pd.Timedelta(hours=DIV_WINDOW_HOURS)
        div_hi = st

        def in_win_with_max(times, depths):
            if len(times) == 0:
                return False, np.nan
            mask = (times >= div_lo) & (times <= div_hi)
            if not mask.any():
                return False, np.nan
            return True, float(depths[mask].max())

        bull_in, max_bull = in_win_with_max(bull_t, bull_d)
        h_bull_in, max_h_bull = in_win_with_max(h_bull_t, h_bull_d)
        bear_in, max_bear = in_win_with_max(bear_t, bear_d)
        h_bear_in, max_h_bear = in_win_with_max(h_bear_t, h_bear_d)
        new_cols["bull_div_in_window"].append(bull_in)
        new_cols["h_bull_div_in_window"].append(h_bull_in)
        new_cols["bear_div_in_window"].append(bear_in)
        new_cols["h_bear_div_in_window"].append(h_bear_in)
        new_cols["max_bull_depth_in_window"].append(max_bull)
        new_cols["max_h_bull_depth_in_window"].append(max_h_bull)
        new_cols["max_bear_depth_in_window"].append(max_bear)
        new_cols["max_h_bear_depth_in_window"].append(max_h_bear)

        # NWE extreme (H16)
        if sig["direction"] == "LONG":
            nwe_extreme = rsi_v < nwe_lo
        else:
            nwe_extreme = rsi_v > nwe_up
        new_cols["nwe_extreme_aligned"].append(bool(nwe_extreme))

    enriched = pd.concat([sigs.reset_index(drop=True),
                          pd.DataFrame(new_cols)], axis=1)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")

    closed = enriched[enriched["outcome"].isin(["win", "loss"])].copy()
    total = len(closed)
    long_mask = closed["direction"] == "LONG"
    short_mask = closed["direction"] == "SHORT"

    print()
    print(f"BASELINE  closed={total}  W={int((closed['outcome']=='win').sum())}  "
          f"WR={(closed['outcome']=='win').mean()*100:.1f}%  "
          f"PnL={int((closed['outcome']=='win').sum())*RR - int((closed['outcome']=='loss').sum()):+.1f}R")
    print()

    # ========== H8 — DIV DEPTH ==========
    print("=" * 90)
    print("H8 — DIVERGENCE DEPTH (только сделки с aligned div, по top/bottom 50%)")
    print("=" * 90)
    aligned_long = long_mask & ((closed["bull_div_in_window"]) | (closed["h_bull_div_in_window"]))
    aligned_short = short_mask & ((closed["bear_div_in_window"]) | (closed["h_bear_div_in_window"]))

    # Берём максимум depth между bull и h_bull (для long) / bear и h_bear (для short)
    closed["aligned_depth"] = np.nan
    closed.loc[aligned_long, "aligned_depth"] = closed.loc[aligned_long, [
        "max_bull_depth_in_window", "max_h_bull_depth_in_window"
    ]].max(axis=1)
    closed.loc[aligned_short, "aligned_depth"] = closed.loc[aligned_short, [
        "max_bear_depth_in_window", "max_h_bear_depth_in_window"
    ]].max(axis=1)

    aligned_all = aligned_long | aligned_short
    aligned_df = closed[aligned_all]
    if len(aligned_df) > 0:
        median_depth = aligned_df["aligned_depth"].median()
        deep = aligned_all & (closed["aligned_depth"] >= median_depth)
        shallow = aligned_all & (closed["aligned_depth"] < median_depth)
        print(stats(closed[aligned_all], "ALL aligned div (baseline)", total))
        print(stats(closed[deep], f"DEEP div (depth>={median_depth:.3f})", total))
        print(stats(closed[shallow], f"SHALLOW div (depth<{median_depth:.3f})", total))

    # ========== H10 — RSI VORTICITY ==========
    print()
    print("=" * 90)
    print("H10 — RSI VORTICITY (delta ema_3 между touch_plus1 и signal_time)")
    print("=" * 90)
    vel = closed["rsi_velocity"].dropna()
    if len(vel) > 0:
        # Для LONG: вверх-velocity (vel>0) = rejection с импульсом → confluence
        # Для SHORT: вниз-velocity (vel<0)
        long_strong = long_mask & (closed["rsi_velocity"] > vel.median())
        long_weak = long_mask & (closed["rsi_velocity"] <= vel.median())
        short_strong = short_mask & (closed["rsi_velocity"] < vel.median())
        short_weak = short_mask & (closed["rsi_velocity"] >= vel.median())
        print(f"  median vel={vel.median():.3f}")
        print(stats(closed[long_strong], "LONG + vel > median (vorticity up)", total))
        print(stats(closed[long_weak], "LONG + vel <= median", total))
        print(stats(closed[short_strong], "SHORT + vel < median (vorticity down)", total))
        print(stats(closed[short_weak], "SHORT + vel >= median", total))
        aligned_velocity = long_strong | short_strong
        print(stats(closed[aligned_velocity], "ALL aligned-velocity", total))
        print(stats(closed[~aligned_velocity], "ALL non-aligned-velocity", total))

    # ========== H11 — BARS SINCE EXTREME ==========
    print()
    print("=" * 90)
    print("H11 — BARS SINCE EXTREME (recent OB -> LONG / recent OS -> SHORT)")
    print("=" * 90)
    # «Недавно» = bars_since_X <= 100
    recent_ob_long = long_mask & (closed["bars_since_ob"] <= H11_LOOKBACK)
    no_recent_ob_long = long_mask & (closed["bars_since_ob"] > H11_LOOKBACK)
    recent_os_short = short_mask & (closed["bars_since_os"] <= H11_LOOKBACK)
    no_recent_os_short = short_mask & (closed["bars_since_os"] > H11_LOOKBACK)
    print(stats(closed[recent_ob_long], f"LONG + bars_since_OB<={H11_LOOKBACK}", total))
    print(stats(closed[no_recent_ob_long], f"LONG + bars_since_OB>{H11_LOOKBACK}", total))
    print(stats(closed[recent_os_short], f"SHORT + bars_since_OS<={H11_LOOKBACK}", total))
    print(stats(closed[no_recent_os_short], f"SHORT + bars_since_OS>{H11_LOOKBACK}", total))
    aligned_bse = recent_ob_long | recent_os_short
    print(stats(closed[aligned_bse], "ALL with recent opposite extreme", total))
    print(stats(closed[~aligned_bse], "ALL without", total))

    # ========== H16 — DIV OR NWE-EXTREME ==========
    print()
    print("=" * 90)
    print("H16 — DIV OR NWE-EXTREME (расширение H1)")
    print("=" * 90)
    div_aligned = aligned_long | aligned_short
    nwe_extreme = closed["nwe_extreme_aligned"]
    h16_or = div_aligned | nwe_extreme
    h16_and = div_aligned & nwe_extreme
    print(stats(closed[div_aligned], "div only (H1)", total))
    print(stats(closed[nwe_extreme], "NWE-extreme only (H4)", total))
    print(stats(closed[h16_or], "div OR NWE-extreme", total))
    print(stats(closed[h16_and], "div AND NWE-extreme", total))

    # ========== H17 — Z PERCENTILE REGIME ==========
    print()
    print("=" * 90)
    print("H17 — Z_ABOVE PERCENTILE (rolling 1y; >75% bull / <25% bear)")
    print("=" * 90)
    has_pct = closed["z_pct_at_signal"].notna()
    bull_pct = has_pct & (closed["z_pct_at_signal"] > 0.75)
    bear_pct = has_pct & (closed["z_pct_at_signal"] < 0.25)
    range_pct = has_pct & ~bull_pct & ~bear_pct
    print(stats(closed[bull_pct & long_mask], "LONG  in pct>75 (top tertile)", total))
    print(stats(closed[bull_pct & short_mask], "SHORT in pct>75 (counter)", total))
    print(stats(closed[bear_pct & long_mask], "LONG  in pct<25 (counter)", total))
    print(stats(closed[bear_pct & short_mask], "SHORT in pct<25 (bottom tertile)", total))
    print(stats(closed[range_pct & long_mask], "LONG  range pct", total))
    print(stats(closed[range_pct & short_mask], "SHORT range pct", total))
    aligned_pct = (bull_pct & long_mask) | (bear_pct & short_mask)
    print(stats(closed[aligned_pct], "ALL aligned pct", total))
    print(stats(closed[~aligned_pct], "ALL non-aligned pct", total))


if __name__ == "__main__":
    main()
