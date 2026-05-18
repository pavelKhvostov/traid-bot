"""Stage 3 CSV: RR sweep на winner entry=0.8, SL=ob_full.

RR варианты: 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 5.0

LONG:  entry = fvg.bottom + 0.8 × (fvg.top - fvg.bottom)
       sl    = ob.bottom
       tp    = entry + RR × (entry - sl)
SHORT: entry = fvg.top    - 0.8 × (fvg.top - fvg.bottom)
       sl    = ob.top
       tp    = entry - RR × (sl - entry)
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df

SYMBOL = "BTCUSDT"
BACKTEST_CSV = "signals/backtest_strategy_1_1_7.csv"
OUT_DIR = Path("research/1_1_7/forensic/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ENTRY_PCT = 0.8  # Stage 1 winner
RR_LIST = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 5.0]


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return pd.NaT
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def parse_zone(s):
    a, b = s.split("-")
    return float(a), float(b)


def main():
    df = pd.read_csv(BACKTEST_CSV)
    df["signal_time_utc"] = df["fvg_c2_time"].apply(parse_utc3)
    df["fvg_b"], df["fvg_t"] = zip(*df["fvg_zone"].apply(parse_zone))
    df["ob_b"], df["ob_t"] = zip(*df["ob_zone"].apply(parse_zone))
    df = df.dropna(subset=["signal_time_utc"]).reset_index(drop=True)
    print(f"[INFO] total setups: {len(df)}")

    df_1m = load_df(SYMBOL, "1m")
    ts_arr = df_1m.index.values
    h_arr = df_1m["high"].to_numpy(dtype=float)
    l_arr = df_1m["low"].to_numpy(dtype=float)

    def simulate(direction, entry, sl, tp, start, timeout_days=14):
        st = start.tz_localize(None) if start.tz else start
        end = st + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(ts_arr, np.datetime64(st))
        i1 = np.searchsorted(ts_arr, np.datetime64(end))
        if i1 <= i0:
            return "no_data", 0.0, pd.NaT
        h = h_arr[i0:i1]; l = l_arr[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0:
            return "invalid", 0.0, pd.NaT
        if direction == "LONG":
            am = l <= entry
            if not am.any():
                return "not_filled", 0.0, pd.NaT
            act = int(np.argmax(am))
            if (h[:act] >= tp).any() or (l[:act] <= sl).any():
                return "no_entry", 0.0, pd.Timestamp(ts_arr[i0+act])
            h2 = h[act:]; l2 = l[act:]
            sh = l2 <= sl; th = h2 >= tp
            si = int(np.argmax(sh)) if sh.any() else len(h2)
            ti = int(np.argmax(th)) if th.any() else len(h2)
            if si == len(h2) and ti == len(h2):
                return "open", 0.0, pd.Timestamp(ts_arr[i0+act])
            if si <= ti:
                return "loss", -1.0, pd.Timestamp(ts_arr[i0+act+si])
            return "win", (tp-entry)/risk, pd.Timestamp(ts_arr[i0+act+ti])
        am = h >= entry
        if not am.any():
            return "not_filled", 0.0, pd.NaT
        act = int(np.argmax(am))
        if (l[:act] <= tp).any() or (h[:act] >= sl).any():
            return "no_entry", 0.0, pd.Timestamp(ts_arr[i0+act])
        h2 = h[act:]; l2 = l[act:]
        sh = h2 >= sl; th = l2 <= tp
        si = int(np.argmax(sh)) if sh.any() else len(h2)
        ti = int(np.argmax(th)) if th.any() else len(h2)
        if si == len(h2) and ti == len(h2):
            return "open", 0.0, pd.Timestamp(ts_arr[i0+act])
        if si <= ti:
            return "loss", -1.0, pd.Timestamp(ts_arr[i0+act+si])
        return "win", (entry-tp)/risk, pd.Timestamp(ts_arr[i0+act+ti])

    rows = []
    for _, t in df.iterrows():
        d = t["direction"]
        fb, ft = t["fvg_b"], t["fvg_t"]
        ob_b, ob_t = t["ob_b"], t["ob_t"]
        if d == "LONG":
            entry = fb + ENTRY_PCT * (ft - fb)
            sl = ob_b
        else:
            entry = ft - ENTRY_PCT * (ft - fb)
            sl = ob_t

        invalid = (d == "LONG" and sl >= entry) or (d == "SHORT" and sl <= entry)

        for rr in RR_LIST:
            if invalid:
                rows.append({
                    "signal_time": t["signal_time_utc"].isoformat(),
                    "direction": d, "RR": rr,
                    "entry": round(entry, 2), "sl": round(sl, 2),
                    "tp": np.nan, "outcome": "invalid", "R": 0.0,
                    "fill_time": "",
                })
                continue
            if d == "LONG":
                tp = entry + rr * (entry - sl)
            else:
                tp = entry - rr * (sl - entry)
            out, r, ft_time = simulate(d, entry, sl, tp, t["signal_time_utc"])
            rows.append({
                "signal_time": t["signal_time_utc"].isoformat(),
                "direction": d, "RR": rr,
                "fvg_b": fb, "fvg_t": ft, "ob_b": ob_b, "ob_t": ob_t,
                "entry": round(entry, 2),
                "sl": round(sl, 2),
                "tp": round(tp, 2),
                "risk_pct": round(abs(entry - sl) / entry * 100, 3),
                "outcome": out, "R": r,
                "fill_time": ft_time.isoformat() if pd.notna(ft_time) else "",
            })

    csv_df = pd.DataFrame(rows)
    out_path = OUT_DIR / "stage3_rr_sweep.csv"
    csv_df.to_csv(out_path, index=False)
    print(f"  saved per-trade: {out_path}  ({len(csv_df)} rows)")

    # Summary per RR
    summary = []
    for rr in RR_LIST:
        sub = csv_df[csv_df["RR"] == rr]
        n_cl = sub["outcome"].isin(["win", "loss"]).sum()
        n_w = (sub["outcome"] == "win").sum()
        n_l = (sub["outcome"] == "loss").sum()
        n_ne = (sub["outcome"] == "no_entry").sum()
        n_nf = (sub["outcome"] == "not_filled").sum()
        n_op = (sub["outcome"] == "open").sum()
        wr = n_w / n_cl * 100 if n_cl else 0
        total = sub["R"].sum()
        r_tr = total / n_cl if n_cl else 0
        summary.append({
            "RR": rr,
            "n_total": len(sub),
            "n_closed": n_cl,
            "wins": n_w,
            "losses": n_l,
            "no_entry": n_ne,
            "not_filled": n_nf,
            "open": n_op,
            "WR_%": round(wr, 1),
            "total_R": round(total, 2),
            "R_per_trade": round(r_tr, 3),
        })
    sm_df = pd.DataFrame(summary)
    sm_path = OUT_DIR / "stage3_rr_summary.csv"
    sm_df.to_csv(sm_path, index=False)
    print(f"  saved summary:   {sm_path}")
    print("\n" + sm_df.to_string(index=False))


if __name__ == "__main__":
    main()
