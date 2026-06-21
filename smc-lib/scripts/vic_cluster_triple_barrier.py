"""ViC cluster reaction — Triple-Barrier (López de Prado Ch 3.4).

Pipeline:
1. Multi-TF maxV (cached from previous run).
2. For each 12h bar T (Lookback bars in):
   a. Compute multi-TF cluster levels (K+ maxV within ±tol)
   b. For each cluster, determine side (resistance/support) from current price
   c. Did this T's high/low touch the cluster?
3. For each TOUCH:
   - Apply Triple-Barrier: pt×ATR profit (reaction), sl×ATR stop (break), t1 bars max
   - Label: +1 (reaction), -1 (break), 0 (timeout)
4. Grid: tol × K × lookback × pt/sl/t1
5. Output: best combo with bounce rate, mean return, sharpe.
"""
from __future__ import annotations
import sys, csv
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.home() / "smc-lib"))

CSV = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MS_M = 60_000
TF_MIN = {"4h": 240, "6h": 360, "12h": 720, "1d": 1440, "2d": 2880, "3d": 4320}
TFS = list(TF_MIN.keys())
MON = int(datetime(2017, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)


def agg(rows, tf_ms, anchor=MON):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in rows:
        b = ts - ((ts - anchor) % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out


def main():
    print("[1/5] Loading maxV cache + 12h bars...")
    df_mv = pd.read_parquet(Path.home() / "Desktop/vic_maxv_per_tf.parquet")
    maxv_per_tf = {tf: list(zip(df_mv[df_mv["tf"]==tf]["ts_ms"].astype("int64"),
                                  df_mv[df_mv["tf"]==tf]["maxV"].astype(float)))
                   for tf in TFS}
    for tf in TFS:
        maxv_per_tf[tf].sort(key=lambda x: x[0])
        print(f"  {tf}: {len(maxv_per_tf[tf])} maxV")

    rows = []
    with CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    bars12 = agg(rows, 720*MS_M)
    n12 = len(bars12)
    ts12 = np.array([b[0] for b in bars12], dtype=np.int64)
    o12 = np.array([b[1] for b in bars12]); h12 = np.array([b[2] for b in bars12])
    l12 = np.array([b[3] for b in bars12]); c12 = np.array([b[4] for b in bars12])
    print(f"  12h bars: {n12}")

    # ATR(14) on 12h
    tr = np.zeros(n12)
    for i in range(1, n12):
        tr[i] = max(h12[i]-l12[i], abs(h12[i]-c12[i-1]), abs(l12[i]-c12[i-1]))
    atr14 = np.zeros(n12)
    for i in range(14, n12):
        atr14[i] = tr[i-13:i+1].mean()

    print("\n[2/5] Pre-build maxV arrays for fast access...")
    mv_ts = {tf: np.array([m[0] for m in maxv_per_tf[tf]], dtype=np.int64) for tf in TFS}
    mv_val = {tf: np.array([m[1] for m in maxv_per_tf[tf]], dtype=float) for tf in TFS}

    def get_cluster_at(t_ms, current_price, tol_pct, K_min, lookback):
        """Find clusters of K+ maxVs within ±tol of each other.
        Returns list of cluster_centers (sorted)."""
        all_mv = []
        for tf in TFS:
            arr = mv_val[tf]
            ts = mv_ts[tf]
            idx = int(np.searchsorted(ts, t_ms, side='left'))
            start = max(0, idx - lookback)
            for v in arr[start:idx]:
                if v > 0 and np.isfinite(v):
                    all_mv.append(v)
        if not all_mv: return []
        all_mv.sort()
        # Sliding-window cluster: find groups of K+ within ±tol pct
        clusters = []
        i = 0
        n = len(all_mv)
        used = [False]*n
        while i < n:
            if used[i]: i += 1; continue
            j = i
            while j < n and all_mv[j] <= all_mv[i] * (1 + 2*tol_pct):
                j += 1
            count = j - i
            if count >= K_min:
                center = sum(all_mv[i:j]) / count
                clusters.append(center)
                for k in range(i, j): used[k] = True
            i += 1
        return clusters

    def triple_barrier(touch_idx, touch_price, side, atr_at, pt, sl, t1):
        """side='resistance' (we expect down move) or 'support' (we expect up move).
        Returns +1 (reaction = PT hit), -1 (break = SL hit), 0 (timeout)."""
        if side == "resistance":
            pt_level = touch_price - pt * atr_at  # profit DOWN
            sl_level = touch_price + sl * atr_at  # break UP
        else:
            pt_level = touch_price + pt * atr_at
            sl_level = touch_price - sl * atr_at
        end = min(n12, touch_idx + t1 + 1)
        for k in range(touch_idx + 1, end):
            if side == "resistance":
                if l12[k] <= pt_level: return +1, k  # reaction
                if h12[k] >= sl_level: return -1, k  # break
            else:
                if h12[k] >= pt_level: return +1, k
                if l12[k] <= sl_level: return -1, k
        return 0, end - 1

    print("\n[3/5] Grid search Triple-Barrier...")
    # Reduce param space
    TOLS = [0.0025, 0.005, 0.0075, 0.01]
    K_MINS = [2, 3, 4]
    LOOKBACKS = [10, 50, 200, 9999]
    PT = 1.5; SL = 1.0; T1 = 12  # 6 days

    grid = []
    for tol in TOLS:
        for K in K_MINS:
            for lb in LOOKBACKS:
                n_touch = n_react = n_break = 0
                returns = []
                # Track which clusters already touched (1 touch per cluster lifecycle)
                # For simplicity: per bar, check each active cluster, count touch once
                # Iterate bars
                touched_cluster_set = set()  # (round(center, 0))
                # use stricter — recompute clusters per bar but only count touch if FIRST time
                for i in range(50, n12 - T1):
                    if atr14[i] <= 0: continue
                    t_ms = int(ts12[i])
                    cur_price = c12[i-1] if i > 0 else c12[i]
                    clusters = get_cluster_at(t_ms, cur_price, tol, K, lb)
                    if not clusters: continue
                    for center in clusters:
                        ck = round(center, 0)
                        # Determine side
                        if cur_price < center:
                            side = "resistance"
                            # touch: high[i] >= center
                            if h12[i] >= center * (1 - tol) and ck not in touched_cluster_set:
                                touched_cluster_set.add(ck)
                                lbl, end_idx = triple_barrier(i, center, side, atr14[i], PT, SL, T1)
                                n_touch += 1
                                if lbl == 1:
                                    n_react += 1
                                    returns.append(PT * atr14[i] / center)
                                elif lbl == -1:
                                    n_break += 1
                                    returns.append(-SL * atr14[i] / center)
                                else:
                                    returns.append((c12[end_idx] - center) / center * (-1 if side=="resistance" else 1))
                        elif cur_price > center:
                            side = "support"
                            if l12[i] <= center * (1 + tol) and ck not in touched_cluster_set:
                                touched_cluster_set.add(ck)
                                lbl, end_idx = triple_barrier(i, center, side, atr14[i], PT, SL, T1)
                                n_touch += 1
                                if lbl == 1:
                                    n_react += 1
                                    returns.append(PT * atr14[i] / center)
                                elif lbl == -1:
                                    n_break += 1
                                    returns.append(-SL * atr14[i] / center)
                                else:
                                    returns.append((c12[end_idx] - center) / center * (1 if side=="support" else -1))
                if n_touch == 0: continue
                p_react = n_react / n_touch
                p_break = n_break / n_touch
                mean_ret = np.mean(returns) * 100 if returns else 0
                std_ret = np.std(returns) * 100 if returns else 1e-9
                sharpe = mean_ret / max(std_ret, 1e-9) * np.sqrt(len(returns)) if len(returns) > 1 else 0
                grid.append({
                    "tol_pct": tol*100, "K": K, "lookback": lb,
                    "n_touch": n_touch, "n_react": n_react, "n_break": n_break,
                    "P_react": p_react, "P_break": p_break,
                    "mean_ret_pct": mean_ret, "sharpe": sharpe,
                })

    df = pd.DataFrame(grid).sort_values("sharpe", ascending=False).reset_index(drop=True)
    out = Path.home() / "Desktop" / "vic_cluster_tb.csv"
    df.to_csv(out, index=False)

    print(f"\n[4/5] Results (sorted by Sharpe):")
    print(df.head(20).to_string(index=False))

    print(f"\n[5/5] By P(react) (with ≥50 touches):")
    print(df[df["n_touch"]>=50].sort_values("P_react", ascending=False).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
