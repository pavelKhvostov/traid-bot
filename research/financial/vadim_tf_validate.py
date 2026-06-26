"""ВАЛИДАЦИЯ HTF-находки: (A) breaker cross-asset+год на 6h/8h/1d; (B) TF-sweep mitigation+ob_liq.

Bracket-independent батарея (на барах ТФ): signed@6 в ATR + null(shuffle dir) + сетка SL×RR нетто.
A: раскол breaker по BTC/ETH/SOL и по годам на HTF -> реальный edge или pooled-монетка.
B: mitigation_block и ob_liq по всем ТФ -> есть ли HTF-инфа (как у breaker), упущенная на LTF.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_tf_validate.py
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
from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob  # noqa: E402
from elements.breaker_block.code import detect_breaker  # noqa: E402
from elements.mitigation_block.code import detect_mitigation_block  # noqa: E402
from elements.ob_liq.code import detect_ob_liq  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ALL_TFS = ["1h", "2h", "4h", "6h", "8h", "12h", "1d"]
HTF = ["6h", "8h", "1d"]
WIN_RT, LOSS_RT = 0.0005, 0.0010
SL_GRID = [0.5, 1.0, 1.5, 2.0, 3.0]; RR_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
GRID_CAP = 1500
RNG = np.random.default_rng(7)
_CACHE = {}


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def atr_tf(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=3).mean().values


def candles(df):
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = df.index.view("int64") // 1_000_000
    return [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i])) for i in range(len(df))]


def get_tf(sym, tf):
    key = (sym, tf)
    if key not in _CACHE:
        d1 = load_1m(sym); dtf = rs(d1, tf)
        _CACHE[key] = (dtf, atr_tf(dtf), candles(dtf))
    return _CACHE[key]


def setups_breaker(dtf, atr, cnd):
    n = len(cnd); out = []
    for i in range(1, n - 1):
        ob = detect_ob(cnd[i - 1], cnd[i])
        if ob is None:
            continue
        br = detect_breaker(ob, cnd[i + 1:])
        if br is None:
            continue
        arm = i + 1 + br.activated_at_idx
        if arm >= n or not np.isfinite(atr[arm]) or atr[arm] <= 0:
            continue
        z_lo, z_hi = br.initial_zone
        if z_hi <= z_lo:
            continue
        out.append((-1 if br.direction == "bullish" else 1, 0.5 * (z_lo + z_hi), float(atr[arm]), arm))
    return out


def setups_mitigation(dtf, atr, cnd):
    n = len(cnd); out = []
    for i in range(1, n - 1):
        ob = detect_ob(cnd[i - 1], cnd[i])
        if ob is None:
            continue
        try:
            mb = detect_mitigation_block(ob, cnd[i + 1:])
        except Exception:
            mb = None
        if mb is None:
            continue
        arm = i + 1 + mb.armed_at_idx
        if arm >= n or not np.isfinite(atr[arm]) or atr[arm] <= 0:
            continue
        z_lo, z_hi = mb.zone
        if z_hi <= z_lo:
            continue
        d = -1 if mb.direction == "bearish" else 1   # bearish->resist->SHORT
        entry = (z_lo + 0.3 * (z_hi - z_lo)) if d == 1 else (z_hi - 0.3 * (z_hi - z_lo))
        out.append((d, float(entry), float(atr[arm]), arm))
    return out


def setups_ob_liq(dtf, atr, cnd):
    n = len(cnd); out = []
    for i in range(1, n):
        try:
            ol = detect_ob_liq(cnd[i - 1], cnd[i])
        except Exception:
            ol = None
        if ol is None or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        z_lo, z_hi = ol.entry_zone
        if z_hi <= z_lo:
            continue
        d = 1 if ol.direction == "long" else -1
        entry = 0.5 * (z_lo + z_hi)
        out.append((d, float(entry), float(atr[i]), i))
    return out


CHAINS = {"breaker": setups_breaker, "mitigation": setups_mitigation, "ob_liq": setups_ob_liq}


def fill_rows(setups, dtf):
    hi = dtf.high.values; lo = dtf.low.values; cl = dtf.close.values
    ts = dtf.index; rows = []
    n = len(cl)
    for (d, e, a, arm) in setups:
        f = None
        for j in range(arm + 1, min(arm + 81, n)):
            if lo[j] <= e <= hi[j]:
                f = j; break
        if f is None or f + 1 >= n:
            continue
        rows.append((d, e, a, f, ts[f].year))
    return rows, hi, lo, cl


def battery(rows, hi, lo, cl):
    if len(rows) < 50:
        return None
    n = len(cl)
    sr = []
    for (d, e, a, f, y) in rows:
        if f + 6 < n:
            sr.append(d * (cl[f + 6] - e) / a)
    real = float(np.mean(sr))
    uns = np.array([s for s in sr])  # signed already; for null use unsigned*randsign
    base_d = np.array([r[0] for r in rows[:len(sr)]])
    unsigned = uns / base_d
    nulls = [float(np.mean(RNG.choice([-1, 1], len(unsigned)) * unsigned)) for _ in range(300)]
    null_p = float((np.array(nulls) >= real).mean())
    gr = rows if len(rows) <= GRID_CAP else [rows[i] for i in RNG.choice(len(rows), GRID_CAP, replace=False)]
    best = (-9, None)
    for sg in SL_GRID:
        for rr in RR_GRID:
            w = l = 0
            for (d, e, a, f, y) in gr:
                end = min(f + 61, n)
                if d == 1:
                    sp = e - sg * a; tp = e + sg * a * rr
                    sh = np.nonzero(lo[f + 1:end] <= sp)[0]; th = np.nonzero(hi[f + 1:end] >= tp)[0]
                else:
                    sp = e + sg * a; tp = e - sg * a * rr
                    sh = np.nonzero(hi[f + 1:end] >= sp)[0]; th = np.nonzero(lo[f + 1:end] <= tp)[0]
                si = sh[0] if sh.size else 10**9; ti = th[0] if th.size else 10**9
                if si == 10**9 and ti == 10**9:
                    continue
                w += int(ti < si); l += int(si <= ti)
            nn = w + l
            if nn < 30:
                continue
            rp = sg * np.median([r[2] for r in gr]) / np.median([r[1] for r in gr]) * 100
            ptt = (w * rr - l) / nn - (WIN_RT * w + LOSS_RT * l) / nn / (rp / 100)
            if ptt > best[0]:
                best = (ptt, (sg, rr))
    return dict(n=len(rows), signed=real, null_p=null_p, best=best[0], cell=best[1], sr=sr, rows=rows)


def main():
    rep = []
    # ===== A: breaker cross-asset + год на HTF =====
    rep.append("=== (A) BREAKER cross-asset + год на HTF (6h/8h/1d) ===")
    for tf in HTF:
        rep.append(f"  [{tf}] по активам:")
        per_year_sr = {}
        for s in SYMBOLS:
            dtf, atr, cnd = get_tf(s, tf)
            rows, hi, lo, cl = fill_rows(setups_breaker(dtf, atr, cnd), dtf)
            b = battery(rows, hi, lo, cl)
            if b is None:
                rep.append(f"    {s}: мало"); continue
            rep.append(f"    {s}: n={b['n']:>4} signed@6={b['signed']:+.3f} null_p={b['null_p']:.2f} сетка_best={b['best']:+.3f}@{b['cell']}")
            for (d, e, a, f, y) in b["rows"]:
                if f + 6 < len(cl):
                    per_year_sr.setdefault(y, []).append(d * (cl[f + 6] - e) / a)
        yl = " ".join(f"{y}:{np.mean(v):+.2f}" for y, v in sorted(per_year_sr.items()) if len(v) > 15)
        rep.append(f"    по годам signed@6: {yl}")
    # ===== B: mitigation + ob_liq TF-sweep =====
    for chain in ["mitigation", "ob_liq"]:
        rep.append(f"\n=== (B) {chain.upper()} TF-sweep (pooled BTC+ETH+SOL) ===")
        for tf in ALL_TFS:
            pooled_rows = []; HI = LO = CL = None
            # pooled battery: concat per-asset (battery uses single cl array -> run per asset, aggregate signed/grid)
            sr_all = []; bests = []; ns = 0; nullps = []
            for s in SYMBOLS:
                dtf, atr, cnd = get_tf(s, tf)
                rows, hi, lo, cl = fill_rows(CHAINS[chain](dtf, atr, cnd), dtf)
                b = battery(rows, hi, lo, cl)
                if b is None:
                    continue
                sr_all += b["sr"]; bests.append(b["best"]); ns += b["n"]; nullps.append(b["null_p"])
            if ns < 80:
                rep.append(f"  {tf:>4}: мало ({ns})"); continue
            real = float(np.mean(sr_all))
            # pooled null on concatenated signed
            uns = np.array(sr_all)
            nulls = [float(np.mean(RNG.choice([-1, 1], len(uns)) * np.abs(uns))) for _ in range(200)]
            null_p = float((np.array(nulls) >= real).mean())
            info = null_p < 0.10 and max(bests) > 0.05
            rep.append(f"  {tf:>4}: n={ns:>5} signed@6={real:+.3f} null_p={null_p:.2f} best_grid(max-asset)={max(bests):+.3f} {'ИНФА?' if info else 'пусто'}")
    out = "\n".join(rep)
    (Path(__file__).resolve().parent / "vadim_tf_validate_report.txt").write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
