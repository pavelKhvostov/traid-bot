"""i-RDRB+FVG cross-asset backtest: BTC / ETH / SOL, год-разбивка, RR-сетка, clean-structure.

Решающий гейт для подключения цепочки в live: переносится ли BTC-edge (Combined-D,
+122.6R/6y) на ETH/SOL и держится ли по годам.

Методология (1:1 с smc-lib/scripts/backtest_combined_d_full.py, но на pandas-канонах):
  - паттерн: strategy_i_rdrb_fvg.detect_all_i_rdrb_fvg (canon V1, 5 свечей)
  - entry/SL: Combined-D (block edge / pattern_extreme+0.1)
  - арм с close(C5); limit-fill на 1m; SL/TP intrabar; MAX_HOLD 30d; "no_fill" если не налилось/не разрешилось
  - TP = entry ± RR·risk (RR-сетка) — заменяет фиксированный baseline-TP ради читаемого sweep

clean-structure (proxy для V2 block-orders anti-filter): same-direction OB-1h,
зона которого пересекает RDRB block setup'а в окне [C1, C5]. Есть → "dirty", нет → "clean".

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/i_rdrb_fvg/backtest_cross_asset.py
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

from strategies.strategy_1_1_1 import detect_ob_pair, zones_overlap  # noqa: E402
from strategies.strategy_i_rdrb_fvg import detect_all_i_rdrb_fvg  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = [("1h", "1h", 60), ("2h", "2h", 120)]
RR_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
MAX_HOLD_MIN = 30 * 24 * 60


def load_1m(sym: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def collect_obs_1h(df_1h: pd.DataFrame):
    """Все OB-1h: (cur_time_ns, dir, bottom, top) — для clean-structure фильтра."""
    times, dirs, bots, tops = [], [], [], []
    for i in range(1, len(df_1h)):
        ob = detect_ob_pair(df_1h, i)
        if ob is None:
            continue
        times.append(df_1h.index[i].value)
        dirs.append(ob.direction)
        bots.append(ob.bottom)
        tops.append(ob.top)
    return (np.array(times), np.array(dirs, dtype=object),
            np.array(bots), np.array(tops))


def is_dirty(sig, obs) -> bool:
    """Есть ли same-dir OB-1h, чья зона пересекает RDRB block, в окне [C1, C5]."""
    ot, od, ob_, otp = obs
    if ot.size == 0:
        return False
    t0, t1 = sig.c1_time.value, sig.c5_time.value
    bb, bt = sig.block
    m = (ot >= t0) & (ot <= t1) & (od == sig.direction) & (otp >= bb) & (ob_ <= bt)
    return bool(m.any())


def precompute(sym, df_tf, df_1m, tf_min, obs):
    """Для каждого setup'а — fill-индекс на 1m + метаданные (RR-независимо)."""
    lo1 = df_1m["low"].to_numpy()
    hi1 = df_1m["high"].to_numpy()
    idx1 = df_1m.index
    sigs = detect_all_i_rdrb_fvg(df_tf)
    out = []
    for s in sigs:
        arm = s.c5_time + pd.Timedelta(minutes=tf_min)
        sp = int(idx1.searchsorted(arm, side="left"))
        if sp >= len(idx1):
            continue
        end = min(sp + MAX_HOLD_MIN, len(lo1))
        if s.direction == "LONG":
            hit = np.where(lo1[sp:end] <= s.entry)[0]
        else:
            hit = np.where(hi1[sp:end] >= s.entry)[0]
        f = sp + int(hit[0]) if hit.size else -1
        out.append({"dir": s.direction, "entry": s.entry, "sl": s.sl, "risk": s.risk,
                    "year": int(s.c5_time.year), "clean": not is_dirty(s, obs),
                    "f": f, "end": end})
    return out, lo1, hi1


def sim_rr(rec, rr, lo1, hi1) -> str:
    f = rec["f"]
    if f < 0:
        return "no_fill"
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
    return "loss" if sl_first <= tp_first else "win"  # ничья на баре → loss (SL раньше TP)


def agg(recs, rr, lo1, hi1, mask=None):
    rows = recs if mask is None else [r for r in recs if mask(r)]
    res = [(r["dir"], sim_rr(r, rr, lo1, hi1)) for r in rows]
    w = sum(1 for _, o in res if o == "win")
    l = sum(1 for _, o in res if o == "loss")
    nf = sum(1 for _, o in res if o == "no_fill")
    op = sum(1 for _, o in res if o == "open")
    closed = w + l
    return {"n": len(rows), "w": w, "l": l, "nf": nf, "open": op,
            "closed": closed, "wr": w / closed * 100 if closed else 0.0,
            "sumR": w * rr - l, "res": res}


def main():
    all_recs = {}
    for sym in SYMBOLS:
        print(f"\nloading {sym} 1m...", flush=True)
        df_1m = load_1m(sym)
        df_1h = resample(df_1m, "1h")
        obs = collect_obs_1h(df_1h)
        for label, freq, tf_min in TFS:
            df_tf = resample(df_1m, freq)
            recs, lo1, hi1 = precompute(sym, df_tf, df_1m, tf_min, obs)
            all_recs[(sym, label)] = (recs, lo1, hi1)
            print(f"  {sym} {label}: {len(recs)} setups "
                  f"({sum(r['clean'] for r in recs)} clean)", flush=True)

    # 1) RR-сетка по символам/ТФ
    print("\n" + "=" * 92)
    print("RR-СЕТКА  (sumR = win*RR - loss)")
    print("=" * 92)
    print(f"{'sym':>7} {'TF':>3} {'RR':>4} {'closed':>6} {'WR%':>6} {'sumR':>8}  "
          f"{'L_n':>4} {'L_WR':>6} {'L_R':>7}  {'S_n':>4} {'S_WR':>6} {'S_R':>7}")
    for sym in SYMBOLS:
        for label, _, _ in TFS:
            recs, lo1, hi1 = all_recs[(sym, label)]
            for rr in RR_GRID:
                a = agg(recs, rr, lo1, hi1)
                L = [(d, o) for d, o in a["res"] if d == "LONG"]
                S = [(d, o) for d, o in a["res"] if d == "SHORT"]
                Lw = sum(1 for _, o in L if o == "win"); Ll = sum(1 for _, o in L if o == "loss")
                Sw = sum(1 for _, o in S if o == "win"); Sl = sum(1 for _, o in S if o == "loss")
                Lwr = Lw / (Lw + Ll) * 100 if (Lw + Ll) else 0
                Swr = Sw / (Sw + Sl) * 100 if (Sw + Sl) else 0
                print(f"{sym:>7} {label:>3} {rr:>4.1f} {a['closed']:>6} {a['wr']:>6.1f} "
                      f"{a['sumR']:>+8.1f}  {Lw+Ll:>4} {Lwr:>6.1f} {Lw*rr-Ll:>+7.1f}  "
                      f"{Sw+Sl:>4} {Swr:>6.1f} {Sw*rr-Sl:>+7.1f}")
            print()

    # 2) Год-разбивка (ТФ 1h, RR=1.0 как у canon Combined-D, и RR=2.0)
    for rr in (1.0, 2.0):
        print("=" * 92)
        print(f"ГОД-РАЗБИВКА  TF=1h  RR={rr}   (sumR per year)")
        print("=" * 92)
        years = list(range(2020, 2027))
        print(f"{'sym':>7}  " + "  ".join(f"{y:>7}" for y in years) + f"  {'TOTAL':>8} {'+yrs':>5}")
        for sym in SYMBOLS:
            recs, lo1, hi1 = all_recs[(sym, "1h")]
            cells, pos, tot = [], 0, 0.0
            for y in years:
                a = agg(recs, rr, lo1, hi1, mask=lambda r, y=y: r["year"] == y)
                cells.append(a["sumR"] if a["closed"] else 0.0)
                tot += a["sumR"]
                if a["closed"] and a["sumR"] > 0:
                    pos += 1
            print(f"{sym:>7}  " + "  ".join(f"{c:>+7.1f}" for c in cells)
                  + f"  {tot:>+8.1f} {pos:>4}/7")
        print()

    # 3) clean vs dirty (TF 1h, RR=1.0)
    print("=" * 92)
    print("CLEAN-STRUCTURE ANTI-FILTER  TF=1h  RR=1.0  (proxy: same-dir OB-1h ∩ block)")
    print("=" * 92)
    print(f"{'sym':>7} {'bucket':>7} {'closed':>6} {'WR%':>6} {'sumR':>8} {'R/tr':>7}")
    for sym in SYMBOLS:
        recs, lo1, hi1 = all_recs[(sym, "1h")]
        for name, mask in (("clean", lambda r: r["clean"]), ("dirty", lambda r: not r["clean"])):
            a = agg(recs, 1.0, lo1, hi1, mask=mask)
            rpt = a["sumR"] / a["closed"] if a["closed"] else 0
            print(f"{sym:>7} {name:>7} {a['closed']:>6} {a['wr']:>6.1f} {a['sumR']:>+8.1f} {rpt:>+7.3f}")
        print()


if __name__ == "__main__":
    main()
