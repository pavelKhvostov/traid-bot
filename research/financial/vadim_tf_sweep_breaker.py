"""TF-SWEEP breaker-flip (C1) — несёт ли сетап инфу на КАКОМ-ЛИБО ТФ (bracket-independent).

Детектор TF-агностичен -> сметаем по {1h,2h,4h,6h,8h,12h,1d}. На каждом ТФ батарея на барах ТФ:
  signed-return в ATR (k=3/6/12 баров ТФ) + null(shuffle dir) + triple-barrier ±1ATR + сетка SL×RR нетто.
Если хоть на одном ТФ signed бьёт null И есть плюс-ячейка сетки -> инфа есть (LTF был костами/шумом).
Если пусто на всех -> финал по всем ТФ.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_tf_sweep_breaker.py
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

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = ["1h", "2h", "4h", "6h", "8h", "12h", "1d"]
WIN_RT, LOSS_RT = 0.0005, 0.0010
SL_GRID = [0.5, 1.0, 1.5, 2.0, 3.0]
RR_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
GRID_CAP = 1500
RNG = np.random.default_rng(7)


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


def find_breakers(df, atr):
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = df.index.view("int64") // 1_000_000
    cnd = [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i])) for i in range(len(df))]
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
        entry = 0.5 * (z_lo + z_hi); d = -1 if br.direction == "bullish" else 1
        out.append({"d": d, "entry": float(entry), "arm": arm, "atr": float(atr[arm])})
    return out


def battery_tf(tf, rep):
    # собрать сетапы + fill на барах ТФ по всем активам
    rows = []  # (d, entry, atr, hi[],lo[],cl[], f)
    nsig = 0
    for s in SYMBOLS:
        d1 = load_1m(s); dtf = rs(d1, tf); a = atr_tf(dtf)
        hi = dtf.high.values; lo = dtf.low.values; cl = dtf.close.values
        sigs = find_breakers(dtf, a); nsig += len(sigs)
        for x in sigs:
            ai = x["arm"]; end = min(ai + 1 + 60, len(cl))
            # fill = первый бар ТФ после arm, касающийся entry
            seg = range(ai + 1, len(cl))
            f = None
            for j in seg:
                if lo[j] <= x["entry"] <= hi[j]:
                    f = j; break
                if j - ai > 80:
                    break
            if f is None or f + 1 >= len(cl):
                continue
            rows.append((x["d"], x["entry"], x["atr"], hi, lo, cl, f))
    if len(rows) < 50:
        rep.append(f"  {tf:>4}: setups {nsig}, filled {len(rows)} — мало, пропуск"); return None

    # signed-return ATR k=3/6/12 баров
    sr = {3: [], 6: [], 12: []}
    for (d, e, a, hi, lo, cl, f) in rows:
        for k in sr:
            if f + k < len(cl):
                sr[k].append(d * (cl[f + k] - e) / a)
    real6 = float(np.mean(sr[6]))
    # null shuffle dir
    unsigned = np.array([s / d for s, (d, *_ ) in zip(sr[6], rows[:len(sr[6])])])  # = (cl-e)/a unsigned
    nulls = [float(np.mean(RNG.choice([-1, 1], len(unsigned)) * unsigned)) for _ in range(300)]
    null_p = float((np.array(nulls) >= real6).mean())

    # triple-barrier ±1 ATR
    favs = []
    for (d, e, a, hi, lo, cl, f) in rows:
        end = min(f + 1 + 60, len(cl)); up = e + a; dn = e - a
        uh = np.nonzero(hi[f + 1:end] >= up)[0]; dh = np.nonzero(lo[f + 1:end] <= dn)[0]
        iu = uh[0] if uh.size else 10**9; idd = dh[0] if dh.size else 10**9
        if iu == 10**9 and idd == 10**9:
            continue
        favs.append((iu < idd) if d == 1 else (idd < iu))
    pfav = float(np.mean(favs)) if favs else np.nan

    # сетка SL×RR на барах ТФ (subsample для скорости)
    gr = rows if len(rows) <= GRID_CAP else [rows[i] for i in RNG.choice(len(rows), GRID_CAP, replace=False)]
    best = (-9, None); anypos = False
    for sg in SL_GRID:
        for rr in RR_GRID:
            w = l = 0
            for (d, e, a, hi, lo, cl, f) in gr:
                end = min(f + 1 + 60, len(cl))
                if d == 1:
                    slp = e - sg * a; tp = e + sg * a * rr
                    sh = np.nonzero(lo[f + 1:end] <= slp)[0]; th = np.nonzero(hi[f + 1:end] >= tp)[0]
                else:
                    slp = e + sg * a; tp = e - sg * a * rr
                    sh = np.nonzero(hi[f + 1:end] >= slp)[0]; th = np.nonzero(lo[f + 1:end] <= tp)[0]
                si = sh[0] if sh.size else 10**9; ti = th[0] if th.size else 10**9
                if si == 10**9 and ti == 10**9:
                    continue
                w += int(ti < si); l += int(si <= ti)
            nn = w + l
            if nn < 30:
                continue
            risk_pct = sg * np.median([r[2] for r in gr]) / np.median([r[1] for r in gr]) * 100
            cost = (WIN_RT * w + LOSS_RT * l) / nn / (risk_pct / 100)
            ptt = (w * rr - l) / nn - cost
            if ptt > best[0]:
                best = (ptt, (sg, rr))
            anypos = anypos or ptt > 0.05
    info = (null_p < 0.10 and best[0] > 0.05) or (pfav > 0.54 and best[0] > 0.05)
    rep.append(f"  {tf:>4}: filled {len(rows):>5} | signed@6={real6:+.3f}ATR null_p={null_p:.2f} | "
               f"P_fav={pfav*100:.0f}% | сетка best {best[0]:+.3f}@SL{best[1][0]}/RR{best[1][1]} plus={'Y' if anypos else 'N'} | "
               f"{'ИНФА?' if info else 'пусто'}")
    return info


def main():
    rep = ["TF-SWEEP breaker-flip (C1) — bracket-independent инфо по всем ТФ",
           "signed@6 = forward 6 баров ТФ в ATR; null_p = vs shuffle-dir; P_fav = triple-barrier ±1ATR; сетка = нетто per-trade.\n"]
    any_info = False
    for tf in TFS:
        print(f"[{tf}] ...", flush=True)
        r = battery_tf(tf, rep)
        any_info = any_info or bool(r)
    rep.append("\n=== ВЕРДИКТ ===")
    rep.append("  Хоть на одном ТФ есть инфа/плюс-зона? " + ("ДА — смотри выше" if any_info else "НЕТ — breaker-флип пуст на ВСЕХ ТФ (1h..1d)"))
    out = "\n".join(rep)
    (Path(__file__).resolve().parent / "vadim_tf_sweep_breaker_report.txt").write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
