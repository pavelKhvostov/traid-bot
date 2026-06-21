"""SMC structure features per req #10.

Williams N=2 fractals on multiple TFs → swing hierarchy.
For each event, detect:
  - BOS (Break of Structure) direction + recency + magnitude
  - ChoCh (Change of Character) direction + recency
  - Swing hierarchy: HH/HL/LH/LL count last N swings
  - Premium/Discount classification (Fib 50%)

TFs for structure analysis (per req #4: ≤ 3D):
  4h, 6h, 12h, 1d, 2d, 3d
"""
from __future__ import annotations
import numpy as np


STRUCT_TFS = ["4h", "6h", "12h", "1d", "2d", "3d"]
N_FRACTAL = 2   # Williams N=2 canon


def detect_fractals_n2(highs: np.ndarray, lows: np.ndarray) -> tuple[list, list]:
    """Detect Williams N=2 fractals.

    Returns:
      fh: list of (idx, level) for fractal highs
      fl: list of (idx, level) for fractal lows
    """
    fhs = []
    fls = []
    n = N_FRACTAL
    if len(highs) < 2 * n + 1:
        return fhs, fls
    for i in range(n, len(highs) - n):
        ch = highs[i]; cl = lows[i]
        is_fh = all(ch > highs[i-k] and ch > highs[i+k] for k in range(1, n+1))
        is_fl = all(cl < lows[i-k] and cl < lows[i+k] for k in range(1, n+1))
        if is_fh: fhs.append((i, float(ch)))
        if is_fl: fls.append((i, float(cl)))
    return fhs, fls


def build_structure_features_for_asset(bars: dict[str, np.ndarray],
                                         born_ms_array: np.ndarray) -> dict[str, np.ndarray]:
    """For each event, compute structure features per TF."""
    n_events = len(born_ms_array)
    out = {}

    for tf in STRUCT_TFS:
        if tf not in bars:
            continue
        bar_arr = bars[tf]
        ts_arr = bar_arr[:, 0].astype(np.int64)
        highs = bar_arr[:, 2]
        lows = bar_arr[:, 3]
        closes = bar_arr[:, 4]

        # Compute all fractals on this TF once
        fhs, fls = detect_fractals_n2(highs, lows)
        fh_idx = np.array([f[0] for f in fhs], dtype=np.int64)
        fh_lvl = np.array([f[1] for f in fhs], dtype=np.float64)
        fl_idx = np.array([f[0] for f in fls], dtype=np.int64)
        fl_lvl = np.array([f[1] for f in fls], dtype=np.float64)

        # For each event find idx in this TF
        idx_at_event = np.searchsorted(ts_arr, born_ms_array, side="right") - 1

        # ─── BOS detection ─────────────────
        # BOS_up: close > previous FH after that FH was confirmed
        # BOS_down: close < previous FL after that FL confirmed
        bos_dir = np.full(n_events, np.nan)
        bos_recency = np.full(n_events, np.nan)   # bars since last BOS event
        bos_magnitude = np.full(n_events, np.nan)  # |close - level| / level * 100

        # ─── Swing hierarchy: last 5 fractals labels ─────
        last_fh_recency = np.full(n_events, np.nan)
        last_fl_recency = np.full(n_events, np.nan)
        hh_count_5 = np.full(n_events, np.nan)
        lh_count_5 = np.full(n_events, np.nan)
        ll_count_5 = np.full(n_events, np.nan)
        hl_count_5 = np.full(n_events, np.nan)

        # ─── Premium / Discount (Fib 50% in last swing range) ─────
        prem_disc = np.full(n_events, np.nan)   # 0-1: 0=deep_discount, 1=deep_premium
        prem_disc_label = np.full(n_events, np.nan)  # -2..+2

        # ─── ChoCh detection (simplified) ─────
        # ChoCh_up: in downtrend (last LH < prev LH), price breaks above last LH
        # ChoCh_down: in uptrend (last HL > prev HL), price breaks below last HL
        choch_dir = np.full(n_events, np.nan)
        choch_recency = np.full(n_events, np.nan)

        for i, idx in enumerate(idx_at_event):
            if idx < 5:
                continue
            # Most recent FH and FL with idx confirmation < event idx (need 2 bars after)
            valid_fhs = fh_idx[fh_idx + N_FRACTAL <= idx]
            valid_fls = fl_idx[fl_idx + N_FRACTAL <= idx]
            if len(valid_fhs) < 3 or len(valid_fls) < 3:
                continue

            # last FH / FL
            last_fh_i = valid_fhs[-1]
            last_fl_i = valid_fls[-1]
            last_fh_lvl = fh_lvl[len(valid_fhs)-1] if len(valid_fhs) > 0 else np.nan
            last_fl_lvl = fl_lvl[len(valid_fls)-1] if len(valid_fls) > 0 else np.nan

            last_fh_recency[i] = idx - last_fh_i
            last_fl_recency[i] = idx - last_fl_i

            # BOS: check if close at event > most recent confirmed FH (= bull BOS)
            cur_close = closes[idx]
            if cur_close > last_fh_lvl:
                # Bull BOS — find moment it broke
                # for simplicity: idx is "now". recency = bars since fractal confirmed
                bos_dir[i] = 1
                bos_recency[i] = idx - last_fh_i
                bos_magnitude[i] = (cur_close - last_fh_lvl) / last_fh_lvl * 100
            elif cur_close < last_fl_lvl:
                bos_dir[i] = -1
                bos_recency[i] = idx - last_fl_i
                bos_magnitude[i] = (last_fl_lvl - cur_close) / last_fl_lvl * 100
            else:
                bos_dir[i] = 0

            # Swing hierarchy: last 5 FHs and 5 FLs comparison
            recent_fhs = fh_lvl[:len(valid_fhs)][-5:]
            recent_fls = fl_lvl[:len(valid_fls)][-5:]
            if len(recent_fhs) >= 2:
                diffs = np.diff(recent_fhs)
                hh_count_5[i] = (diffs > 0).sum()   # higher highs
                lh_count_5[i] = (diffs < 0).sum()   # lower highs
            if len(recent_fls) >= 2:
                diffs = np.diff(recent_fls)
                hl_count_5[i] = (diffs > 0).sum()   # higher lows
                ll_count_5[i] = (diffs < 0).sum()   # lower lows

            # Premium / Discount based on swing range [last_fl_lvl, last_fh_lvl]
            if last_fh_lvl > last_fl_lvl + 1e-9:
                pos = (cur_close - last_fl_lvl) / (last_fh_lvl - last_fl_lvl)
                prem_disc[i] = pos
                # label: -2=deep_disc <0.25, -1=mid_disc 0.25-0.5, 0=mid, 1=mid_prem 0.5-0.75, 2=deep_prem >0.75
                if pos < 0.25:
                    prem_disc_label[i] = -2
                elif pos < 0.5:
                    prem_disc_label[i] = -1
                elif pos < 0.75:
                    prem_disc_label[i] = 1
                else:
                    prem_disc_label[i] = 2

            # ChoCh — simplified
            # ChoCh up: last 2 FHs descending (lh<prev lh), now close > last lh
            if len(recent_fhs) >= 2 and recent_fhs[-1] < recent_fhs[-2]:
                if cur_close > recent_fhs[-1]:
                    choch_dir[i] = 1
                    choch_recency[i] = idx - last_fh_i
            # ChoCh down: last 2 FLs ascending, now close < last fl
            if len(recent_fls) >= 2 and recent_fls[-1] > recent_fls[-2]:
                if cur_close < recent_fls[-1]:
                    if np.isnan(choch_dir[i]):
                        choch_dir[i] = -1
                        choch_recency[i] = idx - last_fl_i

        prefix = f"struct_{tf}"
        out[f"{prefix}_bos_dir"] = bos_dir
        out[f"{prefix}_bos_recency"] = bos_recency
        out[f"{prefix}_bos_magnitude"] = bos_magnitude
        out[f"{prefix}_choch_dir"] = choch_dir
        out[f"{prefix}_choch_recency"] = choch_recency
        out[f"{prefix}_last_fh_recency"] = last_fh_recency
        out[f"{prefix}_last_fl_recency"] = last_fl_recency
        out[f"{prefix}_hh_count_5"] = hh_count_5
        out[f"{prefix}_lh_count_5"] = lh_count_5
        out[f"{prefix}_hl_count_5"] = hl_count_5
        out[f"{prefix}_ll_count_5"] = ll_count_5
        out[f"{prefix}_prem_disc"] = prem_disc
        out[f"{prefix}_prem_disc_label"] = prem_disc_label

    # Cross-TF aggregate: how many TFs have BOS up vs down at event time
    bos_up_count = np.zeros(n_events)
    bos_down_count = np.zeros(n_events)
    valid_cnt = np.zeros(n_events, dtype=np.int32)
    for tf in STRUCT_TFS:
        key = f"struct_{tf}_bos_dir"
        if key in out:
            arr = out[key]
            v = ~np.isnan(arr)
            bos_up_count[v] += (arr[v] == 1).astype(np.float64)
            bos_down_count[v] += (arr[v] == -1).astype(np.float64)
            valid_cnt[v] += 1
    out["struct_bos_up_count_cross_tf"] = np.where(valid_cnt > 0, bos_up_count, np.nan)
    out["struct_bos_down_count_cross_tf"] = np.where(valid_cnt > 0, bos_down_count, np.nan)

    # Cross-TF premium/discount alignment
    pd_avg = np.zeros(n_events)
    valid_cnt = np.zeros(n_events, dtype=np.int32)
    for tf in STRUCT_TFS:
        key = f"struct_{tf}_prem_disc"
        if key in out:
            arr = out[key]
            v = ~np.isnan(arr)
            pd_avg[v] += arr[v]
            valid_cnt[v] += 1
    out["struct_prem_disc_avg_cross_tf"] = np.where(valid_cnt > 0, pd_avg / valid_cnt, np.nan)

    return out
