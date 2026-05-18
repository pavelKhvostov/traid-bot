"""Stage 1 для Strategy 1.1.4 — entry_pct sweep на 6.3y BTC.

Аналог stage1 для 1.1.7. Каскад 1.1.4:
  FVG-{1d, 12h} → FVG-{4h, 6h} → OB-{1h, 2h} + FVG-{15m, 20m}

Stage 1 параметры:
  entry_pct ∈ {0.1, 0.2, ..., 0.9} в зоне entry-FVG (15m/20m)
  SL = ob_htf.bottom (LONG) / ob_htf.top (SHORT) — Stage 1 default (ob_full)
  RR = 1.0

LONG:  entry = fvg.bottom + entry_pct × (fvg.top - fvg.bottom)
SHORT: entry = fvg.top    - entry_pct × (fvg.top - fvg.bottom)
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

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_4 import detect_strategy_1_1_4_signals

SYMBOL = "BTCUSDT"
DAYS_BACK = 2310  # 6.3y
ENTRY_PCTS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
RR = 1.0

OUT_DIR = Path("research/1_1_4/optimize/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    print("=" * 72)
    print(f"  Strategy 1.1.4 — Stage 1 (entry_pct sweep)  6.3y BTC")
    print("=" * 72)

    print("\n[INFO] loading data")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    print(f"  1d={len(df_1d)} 12h={len(df_12h)} 4h={len(df_4h)} 6h={len(df_6h)} "
          f"1h={len(df_1h)} 2h={len(df_2h)} 15m={len(df_15m)} 20m={len(df_20m)} 1m={len(df_1m)}")

    # 6.3y cutoff
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]
    print(f"  after cutoff ({cutoff.date()}): 1d={len(df_1d_f)} 12h={len(df_12h_f)}")

    print("\n[INFO] detect signals")
    sigs = detect_strategy_1_1_4_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
        verbose=True,
    )
    print(f"  raw signals: {len(sigs)}")
    if not sigs:
        print("[WARN] no signals")
        return

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

    print("\n[INFO] simulating entry_pct sweep")
    rows = []
    for sig in sigs:
        d = sig["direction"]
        fb, ft = sig["fvg_zone"]
        ob_b, ob_t = sig["ob_htf_zone"]
        signal_time = sig["signal_time"]
        if not isinstance(signal_time, pd.Timestamp):
            signal_time = pd.Timestamp(signal_time)
        if signal_time.tz is None:
            signal_time = signal_time.tz_localize("UTC")

        for ep in ENTRY_PCTS:
            if d == "LONG":
                entry = fb + ep * (ft - fb)
                sl = ob_b
                invalid = sl >= entry
            else:
                entry = ft - ep * (ft - fb)
                sl = ob_t
                invalid = sl <= entry
            if invalid:
                rows.append({
                    "signal_time": signal_time.isoformat(),
                    "direction": d, "entry_pct": ep,
                    "fvg_b": fb, "fvg_t": ft, "ob_b": ob_b, "ob_t": ob_t,
                    "entry": round(entry, 2), "sl": round(sl, 2),
                    "tp": np.nan, "outcome": "invalid", "R": 0.0,
                    "fill_time": "",
                })
                continue
            if d == "LONG":
                tp = entry + RR * (entry - sl)
            else:
                tp = entry - RR * (sl - entry)
            out, r, ft_time = simulate(d, entry, sl, tp, signal_time)
            rows.append({
                "signal_time": signal_time.isoformat(),
                "direction": d, "entry_pct": ep,
                "fvg_b": fb, "fvg_t": ft, "ob_b": ob_b, "ob_t": ob_t,
                "entry": round(entry, 2),
                "sl": round(sl, 2),
                "tp": round(tp, 2),
                "outcome": out, "R": r,
                "fill_time": ft_time.isoformat() if pd.notna(ft_time) else "",
            })

    csv_df = pd.DataFrame(rows)
    out_path = OUT_DIR / "stage1_entry_pct_sweep.csv"
    csv_df.to_csv(out_path, index=False)
    print(f"  saved per-trade: {out_path}  ({len(csv_df)} rows)")

    summary = []
    for ep in ENTRY_PCTS:
        sub = csv_df[csv_df["entry_pct"] == ep]
        n_cl = sub["outcome"].isin(["win", "loss"]).sum()
        n_w = (sub["outcome"] == "win").sum()
        n_l = (sub["outcome"] == "loss").sum()
        wr = n_w / n_cl * 100 if n_cl else 0
        total = sub["R"].sum()
        r_tr = total / n_cl if n_cl else 0
        summary.append({
            "entry_pct": ep,
            "n_total": len(sub),
            "n_closed": int(n_cl),
            "wins": int(n_w),
            "losses": int(n_l),
            "no_entry": int((sub["outcome"] == "no_entry").sum()),
            "not_filled": int((sub["outcome"] == "not_filled").sum()),
            "open": int((sub["outcome"] == "open").sum()),
            "invalid": int((sub["outcome"] == "invalid").sum()),
            "WR_%": round(wr, 1),
            "total_R": round(total, 1),
            "R_per_trade": round(r_tr, 3),
        })
    sm_df = pd.DataFrame(summary)
    sm_path = OUT_DIR / "stage1_entry_pct_summary.csv"
    sm_df.to_csv(sm_path, index=False)
    print(f"  saved summary:   {sm_path}")
    print("\n" + sm_df.to_string(index=False))


if __name__ == "__main__":
    main()
