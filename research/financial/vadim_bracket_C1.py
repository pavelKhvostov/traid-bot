"""C1-FIXED bracket-independent info test — финален ли винрейт брейкера или чинится бракетом?

Прошлый C1 провалился из-за СЛОМАННОГО бракета (SL=край-фитиля на стороне прихода -> мгновенный стоп).
Здесь: те же точки брейкера (find_breakers), но тестируем ИНФО сетапа НЕЗАВИСИМО от бракета:
  1) signed-return в ATR на 12/24/48/96ч от fill (несёт ли флип направленную инфу);
  2) triple-barrier ±1/±2 ATR (какая сторона первой, без RR);
  3) ПОЛНАЯ сетка SL×RR (ATR-based, нетто) — есть ли ХОТЬ ОДНА плюс-ячейка;
  4) null (перетасовка направления).
Если signed≈0≤null И P_fav≈0.5 И вся сетка минус -> сетап пуст, винрейт ФИНАЛЕН. Иначе чинится.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_bracket_C1.py
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
TFS = {"1h": "1h", "2h": "2h"}
WIN_RT, LOSS_RT = 0.0005, 0.0010
SL_GRID = [0.5, 1.0, 1.5, 2.0, 3.0]   # ×ATR
RR_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
HORIZ_H = [12, 24, 48, 96]
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
        entry = 0.5 * (z_lo + z_hi)
        d = -1 if br.direction == "bullish" else 1   # bullish breaker=SHORT, bearish=LONG
        out.append({"d": d, "entry": float(entry), "arm_ts": df.index[arm], "atr": float(atr[arm])})
    return out


def main():
    # собрать сетапы + 1m путь от fill
    allsig = []
    paths = {}
    for s in SYMBOLS:
        d1 = load_1m(s); paths[s] = d1
        for tf in TFS.values():
            dtf = rs(d1, tf); a = atr_tf(dtf)
            for sg in find_breakers(dtf, a):
                sg["sym"] = s; allsig.append(sg)
    print(f"[setups] брейкер-армов: {len(allsig)}", flush=True)
    CAP = 2500
    if len(allsig) > CAP:
        allsig = [allsig[i] for i in RNG.choice(len(allsig), CAP, replace=False)]
        print(f"[subsample] -> {len(allsig)} (репрезентативно)", flush=True)

    # fill: лимит в entry после arm (limit достигается с любой стороны — берём первое касание)
    rows = []
    for s in SYMBOLS:
        d1 = paths[s]; hi = d1.high.values; lo = d1.low.values; cl = d1.close.values; idx = d1.index
        sub = [x for x in allsig if x["sym"] == s]
        for x in sub:
            sp = idx.searchsorted(x["arm_ts"], side="right")
            if sp >= len(cl):
                continue
            end = min(sp + 30 * 24 * 60, len(cl))
            # fill = первое касание entry (limit) с любой стороны
            seg_hi = hi[sp:end]; seg_lo = lo[sp:end]
            touch = np.nonzero((seg_hi >= x["entry"]) & (seg_lo <= x["entry"]))[0]
            if not touch.size:
                continue
            f = sp + int(touch[0])
            rows.append({**x, "f": f, "sym": s})
    print(f"[filled] {len(rows)}", flush=True)

    # === БАТАРЕЯ ===
    out = []; A = out.append
    A("C1-FIXED bracket-independent — финален ли винрейт брейкера или чинится?")
    A(f"Брейкер-армов {len(allsig)}, filled {len(rows)} (BTC+ETH+SOL, 1h+2h).\n")

    # signed-return в ATR
    A("=== 1. SIGNED-RETURN в ATR (несёт ли флип направленную инфу) ===")
    sr = {hh: [] for hh in HORIZ_H}
    for r in rows:
        d1 = paths[r["sym"]]; cl = d1.close.values; f = r["f"]; e = cl[f]
        for hh in HORIZ_H:
            j = f + hh * 60
            if j < len(cl):
                sr[hh].append(r["d"] * (cl[j] - e) / r["atr"])
    real20 = float(np.mean(sr[24]))
    for hh in HORIZ_H:
        A(f"  {hh:>3}ч: signed {np.mean(sr[hh]):+.3f} ATR (n={len(sr[hh])})")
    # null: перетасовать направление
    nulls = []
    arr = np.array(sr[24])
    base_d = np.array([r["d"] for r in rows[:len(arr)]])
    for _ in range(300):
        sh = RNG.choice([-1, 1], size=len(arr))
        nulls.append(np.mean(arr / base_d * sh))   # arr/base_d = unsigned move; ×random sign
    null_p = float((np.array(nulls) >= real20).mean())
    A(f"  null (shuffle dir) p={null_p:.3f}  -> {'signed бьёт null' if null_p<0.1 else 'signed НЕ бьёт null (нет инфы)'}")

    # triple-barrier ±1/±2 ATR
    A("\n=== 2. TRIPLE-BARRIER (какая сторона первой, без RR) ===")
    for k in (1.0, 2.0):
        favs = []
        for r in rows:
            d1 = paths[r["sym"]]; hi = d1.high.values; lo = d1.low.values; cl = d1.close.values
            f = r["f"]; e = cl[f]; a = r["atr"]; end = min(f + 30 * 24 * 60, len(cl))
            up = e + k * a; dn = e - k * a
            uh = np.nonzero(hi[f + 1:end] >= up)[0]; dh = np.nonzero(lo[f + 1:end] <= dn)[0]
            iu = uh[0] if uh.size else 10**9; idd = dh[0] if dh.size else 10**9
            if iu == 10**9 and idd == 10**9:
                continue
            up_first = iu < idd
            fav = up_first if r["d"] == 1 else (not up_first)
            favs.append(fav)
        A(f"  ±{k:.0f}ATR: P_fav={np.mean(favs)*100:.1f}% (n={len(favs)})  {'>50 есть перевес' if np.mean(favs)>0.52 else '~50 монетка'}")

    # SL×RR grid (ATR-based, нетто)
    A("\n=== 3. СЕТКА SL×RR (ATR-based, НЕТТО per-trade; есть ли плюс-ячейка?) ===")
    A("  SL\\RR " + "".join(f"{rr:>8.1f}" for rr in RR_GRID))
    best = (-9, None)
    anypos = False
    for sg in SL_GRID:
        line = f"  {sg:>4.1f}×"
        for rr in RR_GRID:
            wins = los = 0
            for r in rows:
                d1 = paths[r["sym"]]; hi = d1.high.values; lo = d1.low.values; cl = d1.close.values
                f = r["f"]; e = cl[f]; a = r["atr"]; end = min(f + 30 * 24 * 60, len(cl))
                if r["d"] == 1:
                    slp = e - sg * a; tp = e + sg * a * rr
                    sh = np.nonzero(lo[f + 1:end] <= slp)[0]; th = np.nonzero(hi[f + 1:end] >= tp)[0]
                else:
                    slp = e + sg * a; tp = e - sg * a * rr
                    sh = np.nonzero(hi[f + 1:end] >= slp)[0]; th = np.nonzero(lo[f + 1:end] <= tp)[0]
                si = sh[0] if sh.size else 10**9; ti = th[0] if th.size else 10**9
                if si == 10**9 and ti == 10**9:
                    continue
                wins += int(ti < si); los += int(si <= ti)
            n = wins + los
            if n < 30:
                line += f"{'--':>8}"; continue
            risk_pct = sg * np.median([r["atr"] for r in rows]) / np.median([paths[r["sym"]].close.values[r["f"]] for r in rows]) * 100
            cost = (WIN_RT * wins + LOSS_RT * los) / max(n, 1) / (risk_pct / 100)
            ptt = (wins * rr - los) / n - cost
            line += f"{ptt:>+8.3f}"
            if ptt > best[0]:
                best = (ptt, (sg, rr, n, wins / n))
            anypos = anypos or ptt > 0.05
        A(line)
    A(f"  лучшая ячейка: SL {best[1][0]}×ATR / RR {best[1][1]} -> netExp {best[0]:+.3f} (n={best[1][2]}, WR {best[1][3]*100:.0f}%)")
    A(f"  плюс-зона (>+0.05)? {'ДА' if anypos else 'НЕТ'}")

    A("\n=== ВЕРДИКТ C1 ===")
    empty = (null_p >= 0.1) and (not anypos)
    if empty:
        A(f"  ВИНРЕЙТ ФИНАЛЕН: signed не бьёт null (p={null_p:.2f}) И вся сетка SL×RR в минусе -> брейкер-флип ПУСТ.")
        A("  Сломанный бракет был не причиной — даже с нормальным ATR-SL точка не несёт инфы.")
    else:
        A(f"  ЧИНИТСЯ: есть инфа/плюс-зона (лучшая {best[0]:+.3f} @ SL{best[1][0]}/RR{best[1][1]}). Бракет имеет значение.")
    rep = Path(__file__).resolve().parent / "vadim_bracket_C1_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
