"""Трассировка детекции OB-D Jan 1 2026 + последующих FVG-4h, OB-1h, FVG-15m."""
import pandas as pd
from data_manager import load_df
from strategies.strategy_1_1_1 import (
    detect_ob_pair, detect_fvg, find_search_end_1h, zones_overlap,
)


def main():
    df_1d = load_df("BTCUSDT", "1d")
    df_4h = load_df("BTCUSDT", "4h")
    df_1h = load_df("BTCUSDT", "1h")
    df_15m = load_df("BTCUSDT", "15m")

    # Find idx of OB-D with cur=Jan 1 2026
    target_cur = pd.Timestamp("2026-01-01", tz="UTC")
    cur_idx = df_1d.index.get_loc(target_cur)
    print(f"Daily candle index for Jan 1: {cur_idx}")

    ob_d = detect_ob_pair(df_1d, cur_idx)
    if ob_d is None:
        print("OB-D NOT detected!")
        return
    print(f"OB-D: {ob_d.direction}, zone [{ob_d.bottom:.2f}, {ob_d.top:.2f}]")
    print(f"  prev: {ob_d.prev_time}, cur: {ob_d.cur_time}")

    # FVG-4h search
    fvg_search_start = ob_d.prev_time
    fvg_search_end = ob_d.cur_time + pd.Timedelta(hours=20)
    df_4h_window = df_4h[(df_4h.index >= fvg_search_start) & (df_4h.index <= fvg_search_end)]
    print(f"\n4h window {fvg_search_start} - {fvg_search_end}: {len(df_4h_window)} candles")

    valid_fvgs = []
    for j in range(2, len(df_4h_window)):
        f = detect_fvg(df_4h_window, j)
        if f is None:
            continue
        if f.direction != ob_d.direction:
            continue
        # c2 in cur day
        if not (ob_d.cur_time <= f.c2_time < ob_d.cur_time + pd.Timedelta(days=1)):
            continue
        if ob_d.direction == "LONG":
            if not (ob_d.bottom <= f.bottom <= ob_d.top):
                continue
        else:
            if not (ob_d.bottom <= f.top <= ob_d.top):
                continue
        valid_fvgs.append(f)
        print(f"  FVG-4h candidate: c0={f.c0_time}, c2={f.c2_time}, zone [{f.bottom:.2f}, {f.top:.2f}]")

    if not valid_fvgs:
        print("No valid FVG-4h!")
        return

    for fvg_4h in valid_fvgs:
        print(f"\n=== FVG-4h c2={fvg_4h.c2_time} zone=[{fvg_4h.bottom:.2f}, {fvg_4h.top:.2f}] ===")
        search_start = (ob_d.cur_time + pd.Timedelta(days=1)).normalize()
        df_1h_window = df_1h[df_1h.index >= search_start]
        print(f"  1h window starts: {search_start}, total bars: {len(df_1h_window)}")

        end_idx_1h = find_search_end_1h(
            df_1h_window, ob_d.direction, fvg_4h.top, fvg_4h.bottom,
        )
        df_1h_search = df_1h_window.iloc[:end_idx_1h]
        if len(df_1h_search) > 0:
            print(f"  1h search ends at idx {end_idx_1h}, last bar: {df_1h_search.index[-1]}")
        else:
            print(f"  1h search empty (end_idx={end_idx_1h})")
            continue

        # Look for Jan 21 00:00 OB-1h
        target_1h = pd.Timestamp("2026-01-21 00:00", tz="UTC")
        if target_1h not in df_1h_search.index:
            print(f"  Jan 21 00:00 NOT in search window. Last bar: {df_1h_search.index[-1]}")
            continue
        target_idx = df_1h_search.index.get_loc(target_1h)
        cand = detect_ob_pair(df_1h_search, target_idx)
        if cand is None:
            print(f"  No OB pair at Jan 21 00:00")
            continue
        print(f"  OB-1h at Jan 21 00:00: {cand.direction}, zone [{cand.bottom:.2f}, {cand.top:.2f}]")

        ob1h_in_fvg4h = zones_overlap(cand.bottom, cand.top, fvg_4h.bottom, fvg_4h.top)
        ob1h_in_obd = zones_overlap(cand.bottom, cand.top, ob_d.bottom, ob_d.top)
        print(f"  OB-1h overlaps FVG-4h: {ob1h_in_fvg4h}")
        print(f"  OB-1h overlaps OB-D: {ob1h_in_obd}")

        if not (ob1h_in_fvg4h and ob1h_in_obd):
            print("  Zone constraints failed!")
            continue

        # Check if any earlier OB-1h was already detected
        print(f"  Checking earlier OB-1h candidates in window:")
        for h_idx in range(1, target_idx + 1):
            c = detect_ob_pair(df_1h_search, h_idx)
            if c is None or c.direction != ob_d.direction:
                continue
            ov_fvg = zones_overlap(c.bottom, c.top, fvg_4h.bottom, fvg_4h.top)
            ov_obd = zones_overlap(c.bottom, c.top, ob_d.bottom, ob_d.top)
            if ov_fvg and ov_obd:
                print(f"    Earlier OB-1h at idx {h_idx} ({df_1h_search.index[h_idx]}): zone [{c.bottom:.2f}, {c.top:.2f}]")
                # check FVG-15m
                fvg_15m_start = c.prev_time
                fvg_15m_end = c.cur_time + pd.Timedelta(minutes=45)
                df_15m_w = df_15m[(df_15m.index >= fvg_15m_start) & (df_15m.index <= fvg_15m_end)]
                fvg_15m_found = None
                for k in range(2, len(df_15m_w)):
                    ff = detect_fvg(df_15m_w, k)
                    if ff is None or ff.direction != ob_d.direction:
                        continue
                    if not zones_overlap(ff.bottom, ff.top, c.bottom, c.top):
                        continue
                    fvg_15m_found = ff
                    break
                if fvg_15m_found is not None:
                    print(f"      FVG-15m FOUND -> SIGNAL at {fvg_15m_found.c2_time}")
                    break
                else:
                    print(f"      No FVG-15m in time range")


if __name__ == "__main__":
    main()
