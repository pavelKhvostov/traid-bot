"""Financial backtest — STRATEGY A (i-RDRB+FVG), key=A_irdrb.

Pools BTC+ETH+SOL on 1h (canonical TF for this chain), runs an RR grid and
computes monthly risk-return metrics.

Methodology (matches the validated sim engines in
research/i_rdrb_fvg/backtest_cross_asset.py and
research/vic_vadim/backtest_irdrb_fvg_mit_rr_grid.py):
  - signals from strategies.strategy_i_rdrb_fvg.detect_all_i_rdrb_fvg (Combined-D
    entry/sl/risk, canon V1, 5 candles).
  - arm bar = C5; limit fill scanned on 1m starting at c5_time + tf_minutes
    (NO entry-bar lookahead — fill found from a bar strictly after C5 close).
  - SL/TP scanned on 1m from the FILL bar forward (NO entry-bar lookahead):
    pnl = +RR if TP touched first, -1 if SL touched first; tie on a bar -> loss.
  - drop signals not filled within MAX_HOLD, or filled but never resolved (open).
  - dedup signals by (signal_time, direction, round(entry, 6)).
  - pool the 3 assets, then compute per-RR wr / total_R / n_closed + MONTHLY
    metrics grouped by calendar month (UTC) of the signal_time.

Run: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/fin_A_irdrb.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.strategy_i_rdrb_fvg import detect_all_i_rdrb_fvg  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TF_FREQ = "1h"
TF_MIN = 60
RR_GRID = [1.0, 1.5, 2.0, 2.2, 2.5, 3.0, 3.5]
MAX_HOLD_MIN = 30 * 24 * 60  # 30 days, same as cross-asset engine


def load_1m(sym: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = (df.index.tz_convert("UTC") if df.index.tz
                else df.index.tz_localize("UTC"))
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum",
    }).dropna(subset=["close"])


def precompute(df_tf: pd.DataFrame, df_1m: pd.DataFrame, tf_min: int):
    """Per signal: fill index on 1m + metadata (RR-independent).

    Fill scan starts at c5_time + tf_min (strictly after C5 close), so the
    fill (and everything after) never peeks inside the C5/signal bar.
    """
    lo1 = df_1m["low"].to_numpy()
    hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index
    n1 = len(lo1)
    sigs = detect_all_i_rdrb_fvg(df_tf)
    out = []
    seen = set()
    for s in sigs:
        # dedup by (signal_time, direction, round(entry, 6))
        key = (s.c5_time.value, s.direction, round(float(s.entry), 6))
        if key in seen:
            continue
        seen.add(key)

        arm = s.c5_time + pd.Timedelta(minutes=tf_min)
        sp = int(idx1.searchsorted(arm, side="left"))
        if sp >= n1:
            continue
        end = min(sp + MAX_HOLD_MIN, n1)
        if s.direction == "LONG":
            hit = np.where(lo1[sp:end] <= s.entry)[0]
        else:
            hit = np.where(hi1[sp:end] >= s.entry)[0]
        if hit.size == 0:
            f = -1  # not filled within MAX_HOLD
        else:
            f = sp + int(hit[0])
        out.append({
            "dir": s.direction,
            "entry": float(s.entry),
            "sl": float(s.sl),
            "risk": float(s.risk),
            "sig_time": s.c5_time,           # signal_time used for monthly bucket
            "month": s.c5_time.strftime("%Y-%m"),
            "f": f,
            "end": end,
        })
    return out, lo1, hi1


def sim_rr(rec, rr, lo1, hi1) -> str:
    """Return 'win' | 'loss' | 'no_fill' | 'open' for a single trade at RR."""
    f = rec["f"]
    if f < 0:
        return "no_fill"
    # SL/TP scanned from the FILL bar forward — no entry-bar lookahead beyond
    # the fact that the fill bar itself is where price first touched entry.
    plo = lo1[f:rec["end"]]
    phi = hi1[f:rec["end"]]
    if rec["dir"] == "LONG":
        tp = rec["entry"] + rr * rec["risk"]
        sl_m = plo <= rec["sl"]
        tp_m = phi >= tp
    else:
        tp = rec["entry"] - rr * rec["risk"]
        sl_m = phi >= rec["sl"]
        tp_m = plo <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else 10**9
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else 10**9
    if sl_first == 10**9 and tp_first == 10**9:
        return "open"
    # tie on the same bar -> loss (conservative: SL assumed to hit first)
    return "loss" if sl_first <= tp_first else "win"


def main():
    # 1) collect signals per asset (pooled into one list with asset tag)
    pooled = []  # list of records, with 'asset', plus per-asset lo/hi captured in closures
    per_asset_recs = {}
    for sym in SYMBOLS:
        print(f"loading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        df_tf = resample(df_1m, TF_FREQ)
        recs, lo1, hi1 = precompute(df_tf, df_1m, TF_MIN)
        per_asset_recs[sym] = (recs, lo1, hi1)
        print(f"  {sym} {TF_FREQ}: {len(recs)} signals (deduped)", flush=True)
        for r in recs:
            r2 = dict(r)
            r2["asset"] = sym
            pooled.append(r2)

    # helper: outcome of a pooled record at a given RR (uses its asset's 1m)
    def outcome(rec, rr):
        lo1, hi1 = per_asset_recs[rec["asset"]][1], per_asset_recs[rec["asset"]][2]
        return sim_rr(rec, rr, lo1, hi1)

    # 2) per-RR metrics
    n_total_closed_at = {}
    per_rr_out = []
    monthly_by_rr = {}     # rr -> {month: R}
    per_asset_R_by_rr = {}  # rr -> {asset: R}

    print("\n" + "=" * 100)
    print("RR GRID  (pooled BTC+ETH+SOL, 1h, total_R = wins*RR - losses)")
    print("=" * 100)
    header = (f"{'RR':>4} {'closed':>7} {'WR%':>6} {'total_R':>9} "
              f"{'mo_mean_R':>10} {'pct_pos%':>9} {'worst_mo':>9} {'sharpe':>8} {'n_mo':>5}")
    print(header)

    for rr in RR_GRID:
        wins = losses = 0
        month_R = {}
        asset_R = {a: 0.0 for a in SYMBOLS}
        for rec in pooled:
            o = outcome(rec, rr)
            if o == "win":
                r_val = rr
                wins += 1
            elif o == "loss":
                r_val = -1.0
                losses += 1
            else:
                continue  # no_fill / open -> dropped
            month_R[rec["month"]] = month_R.get(rec["month"], 0.0) + r_val
            asset_R[rec["asset"]] += r_val

        closed = wins + losses
        total_R = wins * rr - losses
        wr = wins / closed * 100 if closed else 0.0

        # monthly metrics (only months with >=1 closed trade are in month_R)
        m_vals = np.array(list(month_R.values()), dtype=float)
        if m_vals.size:
            mo_mean = float(m_vals.mean())
            pct_pos = float((m_vals > 0).sum() / m_vals.size * 100)
            worst = float(m_vals.min())
            std = float(m_vals.std(ddof=0))
            sharpe = float(mo_mean / std) if std > 0 else 0.0
        else:
            mo_mean = pct_pos = worst = sharpe = 0.0

        n_total_closed_at[rr] = closed
        monthly_by_rr[rr] = month_R
        per_asset_R_by_rr[rr] = asset_R
        per_rr_out.append({
            "rr": rr, "wr": round(wr, 2), "total_R": round(total_R, 2),
            "n_closed": closed, "monthly_mean_R": round(mo_mean, 4),
            "pct_pos_months": round(pct_pos, 2), "worst_month_R": round(worst, 2),
            "sharpe_monthly": round(sharpe, 4),
        })
        print(f"{rr:>4.1f} {closed:>7} {wr:>6.1f} {total_R:>+9.1f} "
              f"{mo_mean:>+10.3f} {pct_pos:>9.1f} {worst:>+9.1f} {sharpe:>8.3f} "
              f"{m_vals.size:>5}")

    # 3) best RR by sharpe / total_R
    best_rr_sharpe = max(per_rr_out, key=lambda d: d["sharpe_monthly"])["rr"]
    best_rr_totalR = max(per_rr_out, key=lambda d: d["total_R"])["rr"]
    print(f"\nbest_rr_sharpe = {best_rr_sharpe}   best_rr_totalR = {best_rr_totalR}")

    # 4) monthly_series + per_asset_totalR at best_rr_sharpe
    ms = monthly_by_rr[best_rr_sharpe]
    monthly_series = [{"month": m, "R": round(ms[m], 4)} for m in sorted(ms)]
    pa = per_asset_R_by_rr[best_rr_sharpe]
    per_asset_totalR = [{"asset": a, "total_R": round(pa[a], 2)} for a in SYMBOLS]

    n_total_closed = n_total_closed_at[best_rr_sharpe]

    print(f"\nmonthly_series @RR={best_rr_sharpe}: {len(monthly_series)} months")
    print(f"per_asset_totalR @RR={best_rr_sharpe}: "
          + ", ".join(f"{d['asset']}={d['total_R']:+.1f}" for d in per_asset_totalR))
    print(f"n_total_closed @best_rr_sharpe = {n_total_closed}")

    # emit a compact machine-readable block for the harness to read back
    import json
    print("\n===JSON_BEGIN===")
    print(json.dumps({
        "n_total_closed": n_total_closed,
        "per_rr": per_rr_out,
        "best_rr_sharpe": best_rr_sharpe,
        "best_rr_totalR": best_rr_totalR,
        "monthly_series": monthly_series,
        "per_asset_totalR": per_asset_totalR,
    }))
    print("===JSON_END===")


if __name__ == "__main__":
    main()
