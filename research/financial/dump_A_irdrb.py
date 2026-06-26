"""Per-trade CSV dump — STRATEGY A (i-RDRB+FVG), key=A_irdrb, FIXED RR=2.5.

Reuses the validated limit-fill sim from research/financial/fin_A_irdrb.py
(same dedup, same no-lookahead fill scan, same SL/TP resolution). For every
CLOSED trade (win/loss only — drops not_filled/open) pooled across
BTC+ETH+SOL it writes one row to research/financial/trades_A_irdrb.csv with:

  signal_time  exit_time  sym  direction  gross_R  risk_pct

  - signal_time = arm/signal time (C5 close), UTC 'YYYY-MM-DD HH:MM:SS'
  - exit_time   = UTC time of the SL/TP bar that resolved the trade
  - gross_R     = +2.5 if TP hit first else -1.0
  - risk_pct    = abs(entry - sl) / entry * 100 (stop distance as % of entry)

Run: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/dump_A_irdrb.py
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

# reuse the validated engine from fin_A_irdrb.py
from research.financial.fin_A_irdrb import (  # noqa: E402
    SYMBOLS, TF_FREQ, TF_MIN, load_1m, resample, precompute,
)

RR = 2.5
OUT_CSV = ROOT / "research" / "financial" / "trades_A_irdrb.csv"


def resolve_trade(rec, rr, lo1, hi1, idx1):
    """Return (outcome, exit_idx) for a single trade at RR.

    outcome in {'win','loss','no_fill','open'}. exit_idx is the 1m bar index
    of the SL/TP touch (or None). Mirrors sim_rr() in fin_A_irdrb.py exactly:
      - fill bar = rec['f'] (first bar at/after C5+TF that touched entry).
      - SL/TP scanned from the FILL bar forward (no entry-bar lookahead).
      - tie on the same bar -> loss (SL assumed first).
    """
    f = rec["f"]
    if f < 0:
        return "no_fill", None
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
        return "open", None
    if sl_first <= tp_first:  # tie -> loss
        return "loss", f + sl_first
    return "win", f + tp_first


def main():
    rows = []
    for sym in SYMBOLS:
        print(f"loading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        df_tf = resample(df_1m, TF_FREQ)
        recs, lo1, hi1 = precompute(df_tf, df_1m, TF_MIN)
        idx1 = df_1m.index
        print(f"  {sym} {TF_FREQ}: {len(recs)} signals (deduped)", flush=True)

        closed = 0
        for rec in recs:
            outcome, exit_idx = resolve_trade(rec, RR, lo1, hi1, idx1)
            if outcome not in ("win", "loss"):
                continue  # drop no_fill / open
            closed += 1
            gross_R = RR if outcome == "win" else -1.0
            risk_pct = abs(rec["entry"] - rec["sl"]) / rec["entry"] * 100.0
            exit_time = (idx1[exit_idx].strftime("%Y-%m-%d %H:%M:%S")
                         if exit_idx is not None else "")
            rows.append({
                "signal_time": rec["sig_time"].strftime("%Y-%m-%d %H:%M:%S"),
                "exit_time": exit_time,
                "sym": sym,
                "direction": rec["dir"],
                "gross_R": gross_R,
                "risk_pct": risk_pct,
            })
        print(f"  {sym}: {closed} closed trades", flush=True)

    cols = ["signal_time", "exit_time", "sym", "direction", "gross_R", "risk_pct"]
    df = pd.DataFrame(rows, columns=cols)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    print("\n===DUMP_SUMMARY===")
    print(f"csv_path={OUT_CSV}")
    print(f"n_trades={len(df)}")
    print(f"opt_rr={RR}")
    if len(df):
        print(f"median_risk_pct={float(df['risk_pct'].median())}")
        print(f"wins={int((df['gross_R'] > 0).sum())} "
              f"losses={int((df['gross_R'] < 0).sum())}")
    else:
        print("median_risk_pct=nan")
    print("cols=" + ",".join(cols))
    print("===DUMP_END===")


if __name__ == "__main__":
    main()
