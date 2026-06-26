"""ГРИД-ХАРНЕС из Вадим-элементов: фронтир #2 (структура-гейт + breaker) + #1 (ob_vc), с обязательными гейтами.

Единая батарея на конфиг: signed@6 ATR + null(shuffle) + сетка SL×RR нетто + cross-asset(per-asset signed) + OOS(≤23/≥24).
Гейт-выживание: signed бьёт null + cross-asset>=2/3 + OOS держится + плюс-ячейка сетки.
#2: breaker на entry-ТФ{6h,8h}, усиленный требованием same-dir CHoCH/BOS на gate-ТФ{12h,1d} в окне -> улучшает?
#1: ob_vc 1d/12h (через smc_adapter, best-effort).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_grid_harness.py
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
from elements.choch_bos.code import scan_market_structure  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
WIN_RT, LOSS_RT = 0.0005, 0.0010
SL_GRID = [0.5, 1.0]; RR_GRID = [2.0, 3.0]
TF_HOURS = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "8h": 8, "12h": 12, "1d": 24}
RNG = np.random.default_rng(7)
_C = {}


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


def cndl(df):
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = df.index.view("int64") // 1_000_000
    return [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i])) for i in range(len(df))]


def get(sym, tf):
    if (sym, tf) not in _C:
        d1 = load_1m(sym); dtf = rs(d1, tf)
        _C[(sym, tf)] = (dtf, atr_tf(dtf), cndl(dtf))
    return _C[(sym, tf)]


def breaker_arms(dtf, atr, cnd):
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
        out.append((-1 if br.direction == "bullish" else 1, 0.5 * (z_lo + z_hi), float(atr[arm]), arm, dtf.index[arm]))
    return out


def struct_events(dtf, cnd, want):
    try:
        evs = scan_market_structure(cnd)
    except Exception:
        return []
    out = []
    for ev in evs:
        if want != "any" and ev.type != want:
            continue
        if ev.break_idx is None or ev.break_idx >= len(dtf):
            continue
        out.append((1 if ev.side == "bullish" else -1, dtf.index[ev.break_idx]))
    return out


def fill_rows(arms, dtf):
    h = dtf.high.values; lo = dtf.low.values; c = dtf.close.values; n = len(c); rows = []
    for (d, e, a, arm, ats) in arms:
        f = None
        for j in range(arm + 1, min(arm + 81, n)):
            if lo[j] <= e <= h[j]:
                f = j; break
        if f is None or f + 1 >= n:
            continue
        rows.append((d, e, a, f, dtf.index[f].year))
    return rows, h, lo, c


def battery(by_sym):
    """by_sym[sym] = (rows, h, lo, c). -> dict metrics pooled + per-asset signed + OOS."""
    sr = []; per_signed = {}; oos = {"in": [], "out": []}; gr_all = []; arrays = {}
    for s, (rows, h, lo, c) in by_sym.items():
        n = len(c); ss = []
        for (d, e, a, f, y) in rows:
            if f + 6 < n:
                v = d * (c[f + 6] - e) / a; sr.append(v); ss.append(v)
                (oos["in"] if y <= 2023 else oos["out"]).append(v)
        per_signed[s] = float(np.mean(ss)) if ss else float("nan")
        gr_all += [(d, e, a, f, s) for (d, e, a, f, y) in rows]
        arrays[s] = (h, lo, c)
    if len(sr) < 60:
        return None
    real = float(np.mean(sr)); uns = np.abs(np.array(sr))
    nulls = [float(np.mean(RNG.choice([-1, 1], len(uns)) * uns)) for _ in range(250)]
    null_p = float((np.array(nulls) >= real).mean())
    cross = sum(1 for v in per_signed.values() if v > 0)
    oin = float(np.mean(oos["in"])) if oos["in"] else float("nan")
    oout = float(np.mean(oos["out"])) if len(oos["out"]) > 20 else float("nan")
    # grid (subsample)
    gr = gr_all if len(gr_all) <= 1500 else [gr_all[i] for i in RNG.choice(len(gr_all), 1500, replace=False)]
    best = -9
    for sg in SL_GRID:
        for rr in RR_GRID:
            w = l = 0
            for (d, e, a, f, s) in gr:
                h, lo, c = arrays[s]; end = min(f + 61, len(c))
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
            rp = sg * np.median([r[2] for r in gr]) / np.median([r[1] for r in gr]) * 100
            best = max(best, (w * rr - l) / nn - (WIN_RT * w + LOSS_RT * l) / nn / (rp / 100))
    return dict(n=len(sr), signed=real, null_p=null_p, cross=cross, oos_in=oin, oos_out=oout, best=best,
                per=per_signed)


def gated_rows(entry_tf, gate_tf, gateset):
    """breaker на entry_tf, оставить если same-dir структ-событие на gate_tf в окне 10 gate-баров до arm."""
    by_sym = {}
    for s in SYMBOLS:
        edtf, eatr, ecnd = get(s, entry_tf)
        arms = breaker_arms(edtf, eatr, ecnd)
        if gateset is not None:
            Kdur = pd.Timedelta(hours=TF_HOURS[gate_tf] * 10)
            gdtf, gatr, gcnd = get(s, gate_tf)
            evs = struct_events(gdtf, gcnd, gateset)
            arms = [(d, e, a, arm, ats) for (d, e, a, arm, ats) in arms
                    if any(es == d and (ats - Kdur) <= ets <= ats for (es, ets) in evs)]
        rows, h, lo, c = fill_rows(arms, edtf)
        by_sym[s] = (rows, h, lo, c)
    return battery(by_sym)


def main():
    out = []; A = out.append
    A("ГРИД-ХАРНЕС Вадим: #2 структура-гейт+breaker (улучшает выжившего?) + #1 ob_vc\n")
    A("=== #2 BREAKER ± структура-гейт (HTF) ===")
    A(f"{'конфиг':34}{'n':>6}{'signed@6':>9}{'null_p':>7}{'cross':>6}{'OOS_out':>8}{'grid':>8}{'verdict':>9}")
    configs = [("breaker-6h (baseline)", "6h", None, None),
               ("breaker-8h (baseline)", "8h", None, None),
               ("breaker-6h + CHoCH-12h", "6h", "12h", "CHoCH"),
               ("breaker-6h + BOS-12h", "6h", "12h", "BOS"),
               ("breaker-6h + any-struct-12h", "6h", "12h", "any"),
               ("breaker-8h + CHoCH-1d", "8h", "1d", "CHoCH"),
               ("breaker-8h + any-struct-1d", "8h", "1d", "any"),
               ("breaker-6h + any-struct-1d", "6h", "1d", "any")]
    base = {}
    for name, etf, gtf, gs in configs:
        m = gated_rows(etf, gtf, gs)
        if m is None:
            A(f"{name:34}{'мало':>6}"); continue
        surv = m["null_p"] < 0.10 and m["cross"] >= 2 and m["oos_out"] > 0 and m["best"] > 0.05
        A(f"{name:34}{m['n']:>6}{m['signed']:>+9.3f}{m['null_p']:>7.2f}{m['cross']:>4}/3{m['oos_out']:>+8.3f}{m['best']:>+8.3f}{'ВЫЖИЛ' if surv else 'нет':>9}")
        if gs is None:
            base[etf] = m
    A("  -> гейт ПОМОГАЕТ, если у gated signed/OOS/grid выше baseline того же entry-ТФ при cross>=2/3.")

    A("\n=== #1 ob_vc (1d/12h, best-effort через smc_adapter) ===")
    try:
        from research.smc_adapter import precompute_zone_events, snapshot_from_events  # noqa: E402
        by_sym = {}
        for s in SYMBOLS:
            d1 = load_1m(s)
            ev, resampled = precompute_zone_events(d1, tfs=("1d", "12h"), types=("ob_vc",))
            # собрать ob_vc-зоны как сетапы: пройтись по событиям
            rows = []
            d12 = rs(d1, "12h"); h = d12.high.values; lo = d12.low.values; c = d12.close.values
            cnt = 0
            for (tf, typ), evs in ev.items():
                if typ != "ob_vc":
                    continue
                cnt += len(evs)
            A(f"  {s}: ob_vc событий={cnt} (детектор отработал)")
        A("  ob_vc: детектор запущен; полная батарея ob_vc требует отдельной сборки entry_zone из событий —")
        A("  событий мало/структура сложная -> вынесено в отдельный прогон (низкий прайор).")
    except Exception as ex:
        A(f"  ob_vc best-effort не прошёл: {str(ex)[:120]} -> отдельный прогон.")

    A("\n=== ВЕРДИКТ ===")
    A("  Сравни gated-строки с baseline той же entry-ТФ: если ни одна gated не бьёт baseline по signed/OOS при cross>=2/3 —")
    A("  структура-гейт breaker НЕ усиливает (breaker самодостаточен). Если бьёт — новый усиленный конфиг.")
    o = "\n".join(out); (Path(__file__).resolve().parent / "vadim_grid_harness_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
