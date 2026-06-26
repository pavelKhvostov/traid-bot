"""ob_vc — полная bracket-independent батарея (последний непротестированный элемент Вадима).

Через smc_adapter.precompute_zone_events (рабочий cross-TF ob_vc-сканер) собираем события на HTF-якорях,
вход=в ob_vc-зону, батарея: signed@6 ATR + null + сетка SL×RR нетто + cross-asset + OOS(≤23/≥24), по ТФ.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_obvc_battery.py
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
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "smc-lib"))
from research.smc_adapter import precompute_zone_events  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = ("1d", "12h", "6h", "8h", "4h")
WIN_RT, LOSS_RT = 0.0005, 0.0010
SL_GRID = [0.5, 1.0, 1.5, 2.0]; RR_GRID = [2.0, 3.0]
RNG = np.random.default_rng(7)


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def atr_arr(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=3).mean().values


def dirsign(x):
    return 1 if str(x).lower() in ("long", "bullish", "buy", "up") else -1


def setups_for_tf(evs, dfx, atr):
    """evs: list dict{direction,lo,hi,born_idx,...}; dfx resampled df. -> (d,entry,atr,fill_idx,year)."""
    h = dfx.high.values; lo = dfx.low.values; c = dfx.close.values; ts = dfx.index; n = len(c)
    rows = []
    seen = set()
    for e in evs:
        bi = e.get("born_idx")
        if bi is None or bi >= n - 2 or not np.isfinite(atr[bi]) or atr[bi] <= 0:
            continue
        zlo = e.get("lo"); zhi = e.get("hi")
        if zlo is None or zhi is None or zhi <= zlo:
            continue
        d = dirsign(e.get("direction"))
        entry = 0.5 * (zlo + zhi)
        key = (bi, round(entry, 4), d)
        if key in seen:
            continue
        seen.add(key)
        f = None
        for j in range(bi + 1, min(bi + 41, n)):
            if lo[j] <= entry <= h[j]:
                f = j; break
        if f is None or f + 1 >= n:
            continue
        rows.append((d, float(entry), float(atr[bi]), f, ts[f].year))
    return rows, h, lo, c


def battery(by_sym):
    sr = []; per = {}; oos = {"in": [], "out": []}; gr = []; arr = {}
    for s, (rows, h, lo, c) in by_sym.items():
        n = len(c); ss = []
        for (d, e, a, f, y) in rows:
            if f + 6 < n:
                v = d * (c[f + 6] - e) / a; sr.append(v); ss.append(v)
                (oos["in"] if y <= 2023 else oos["out"]).append(v)
        per[s] = float(np.mean(ss)) if ss else float("nan")
        gr += [(d, e, a, f, s) for (d, e, a, f, y) in rows]; arr[s] = (h, lo, c)
    if len(sr) < 60:
        return None
    real = float(np.mean(sr)); uns = np.abs(np.array(sr))
    nulls = [float(np.mean(RNG.choice([-1, 1], len(uns)) * uns)) for _ in range(250)]
    null_p = float((np.array(nulls) >= real).mean())
    cross = sum(1 for v in per.values() if v > 0)
    oout = float(np.mean(oos["out"])) if len(oos["out"]) > 20 else float("nan")
    g = gr if len(gr) <= 1500 else [gr[i] for i in RNG.choice(len(gr), 1500, replace=False)]
    best = -9
    for sg in SL_GRID:
        for rr in RR_GRID:
            w = l = 0
            for (d, e, a, f, s) in g:
                h, lo, c = arr[s]; end = min(f + 61, len(c))
                if d == 1:
                    sp = e - sg * a; tp = e + sg * a * rr
                    sh = np.nonzero(lo[f + 1:end] <= sp)[0]; th = np.nonzero(h[f + 1:end] >= tp)[0]
                else:
                    sp = e + sg * a; tp = e - sg * a * rr
                    sh = np.nonzero(h[f + 1:end] >= sp)[0]; th = np.nonzero(lo[f + 1:end] <= tp)[0]
                si = sh[0] if sh.size else 10**9; ti = th[0] if th.size else 10**9
                if si == 10**9 and ti == 10**9:
                    continue
                w += int(ti < si); l += int(si <= ti)
            nn = w + l
            if nn < 30:
                continue
            rp = sg * np.median([r[2] for r in g]) / np.median([r[1] for r in g]) * 100
            best = max(best, (w * rr - l) / nn - (WIN_RT * w + LOSS_RT * l) / nn / (rp / 100))
    return dict(n=len(sr), signed=real, null_p=null_p, cross=cross, oos_out=oout, best=best)


def main():
    out = []; A = out.append
    A("ob_vc — полная батарея по ТФ (signed+null+сетка+cross+OOS)\n")
    A(f"{'ТФ':>5}{'n':>7}{'signed@6':>9}{'null_p':>7}{'cross':>6}{'OOS_out':>8}{'grid':>8}{'verdict':>9}")
    # precompute per sym once
    EV = {}
    for s in SYMBOLS:
        print(f"[{s}] precompute ob_vc...", flush=True)
        d1 = load_1m(s)
        ev, resampled = precompute_zone_events(d1, tfs=TFS, types=("ob_vc",))
        EV[s] = (ev, resampled)
    for tf in TFS:
        by_sym = {}
        for s in SYMBOLS:
            ev, resampled = EV[s]
            evs = ev.get((tf, "ob_vc"), [])
            if not evs or tf not in resampled:
                continue
            dfx = resampled[tf]; atr = atr_arr(dfx)
            rows, h, lo, c = setups_for_tf(evs, dfx, atr)
            if rows:
                by_sym[s] = (rows, h, lo, c)
        if len(by_sym) < 2:
            A(f"{tf:>5}{'нет событий/мало':>20}"); continue
        m = battery(by_sym)
        if m is None:
            A(f"{tf:>5}{'мало':>7}"); continue
        surv = m["null_p"] < 0.10 and m["cross"] >= 2 and (m["oos_out"] > 0) and m["best"] > 0.05
        A(f"{tf:>5}{m['n']:>7}{m['signed']:>+9.3f}{m['null_p']:>7.2f}{m['cross']:>4}/3{m['oos_out']:>+8.3f}{m['best']:>+8.3f}{'ВЫЖИЛ' if surv else 'нет':>9}")
    A("\n=== ВЕРДИКТ ob_vc ===")
    A("  Выжил если на каком-то HTF: signed бьёт null + cross>=2/3 + OOS>0 + плюс-сетка. Иначе — пуст (как остальные).")
    o = "\n".join(out); (Path(__file__).resolve().parent / "vadim_obvc_battery_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
