"""ViC-Vadim 12h Вариант 1 — ИСПОЛНЕНИЕ: entry/SL/TP backtest (открытая задача из vault).

Предиктор уже валидирован (precision 75-93%); здесь формализуем СДЕЛКУ и честно меряем R.
Сигнал (Core, mlt=45/LTF16m): HH=(sweep_FH∪OB_short)∩maxV_short -> SHORT; LL mirror -> LONG.
  Entry = close(i) (как в спеке).
  SL    = high(i)*(1+buf) для SHORT / low(i)*(1-buf) для LONG  (high/low(i) уже = max снятых
          уровней, т.к. sweep => high(i)>level). risk = |SL-entry| = размах свип-фитиля.
  TP    = варианты: RR-cap grid {1.5,2.0,2.5,3.0} ИЛИ time-stop close(i+2).
Гонка SL/TP вперёд по 12h барам (SL первым внутри бара, консервативно), max_hold=10 (5д).

Дисциплина: per-year, HH/LL split, дедуп (1 сигнал/бар/направление уже уникален), + ETH/SOL
перенос. Честно: 6y in-sample для предиктора (mlt=45 cross-asset валидирован отдельно).

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/vic_vadim/backtest_v1_signal_rr.py BTCUSDT
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "research" / "vic_vadim"))
import optimize_mlt as OM

LTF_MIN = 16   # mlt=45
RR_GRID = [1.5, 2.0, 2.5, 3.0]
BUF = 0.001
MAX_HOLD = 10


def load(sym):
    p = ROOT / "data" / f"{sym}_1m_vic_vadim.csv"
    if not p.exists():
        p = ROOT / "data" / f"{sym}_1m.csv"          # стандартный кэш (vic_vadim не закоммичен)
    df = pd.read_csv(p, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def build_signals(sym):
    df_1m = load(sym); df_1m_naive = df_1m.copy(); df_1m_naive.index.name = None
    htf = {tf: OM.compose_htf(df_1m, freq) for tf, freq in OM.HTF_LIST}
    df = htf["12h"]
    all_ob, all_fr = [], []
    for d in htf.values():
        all_ob += OM.find_ob_zones(d); all_fr += OM.find_fractals(d)
    c1_fh = OM.fractal_sweep_flags(df, all_fr, "FH"); c1_fl = OM.fractal_sweep_flags(df, all_fr, "FL")
    c1_obs = OM.zone_sweep_flags(df, all_ob, "SHORT"); c1_obl = OM.zone_sweep_flags(df, all_ob, "LONG")
    maxv = OM.maxv_all_12h(df_1m_naive, df, LTF_MIN)
    h = df["high"].to_numpy(); l = df["low"].to_numpy(); c = df["close"].to_numpy()
    idx = df.index; n = len(df)
    sw_s = np.zeros(n, bool); sw_l = np.zeros(n, bool)
    for i in range(1, n):
        if np.isnan(maxv[i - 1]): continue
        if h[i] > maxv[i - 1] and c[i] < maxv[i - 1]: sw_s[i] = True
        if l[i] < maxv[i - 1] and c[i] > maxv[i - 1]: sw_l[i] = True
    hh = (c1_fh | c1_obs) & sw_s
    ll = (c1_fl | c1_obl) & sw_l
    sigs = []
    for i in range(2, n - 2):
        if hh[i]: sigs.append((idx[i], "SHORT", float(c[i]), float(h[i]), i))
        if ll[i]: sigs.append((idx[i], "LONG", float(c[i]), float(l[i]), i))
    return df, sigs


def sim(df, sigs, rr, timestop=False):
    H = df["high"].to_numpy(); L = df["low"].to_numpy(); C = df["close"].to_numpy(); n = len(df)
    rows = []
    for t, d, entry, ext, i in sigs:
        if d == "SHORT":
            sl = ext * (1 + BUF); risk = sl - entry
        else:
            sl = ext * (1 - BUF); risk = entry - sl
        if risk <= 0:
            continue
        if timestop:
            j = min(i + 2, n - 1)
            R = ((entry - C[j]) if d == "SHORT" else (C[j] - entry)) / risk
            rows.append(dict(t=t, year=t.year, dir=d, outcome="ts", R=float(R))); continue
        tp = entry - rr * risk if d == "SHORT" else entry + rr * risk
        out, R = "open", 0.0
        for j in range(i + 1, min(i + 1 + MAX_HOLD, n)):
            if d == "SHORT":
                if H[j] >= sl: out, R = "loss", -1.0; break
                if L[j] <= tp: out, R = "win", float(rr); break
            else:
                if L[j] <= sl: out, R = "loss", -1.0; break
                if H[j] >= tp: out, R = "win", float(rr); break
        if out == "open":
            j = min(i + MAX_HOLD, n - 1)
            R = ((entry - C[j]) if d == "SHORT" else (C[j] - entry)) / risk; out = "timeout"
        rows.append(dict(t=t, year=t.year, dir=d, outcome=out, R=float(R)))
    return pd.DataFrame(rows)


def summary(b, label):
    n = len(b); sr = b.R.sum(); rpt = sr / n if n else 0
    wr = (b.outcome == "win").mean() * 100 if "win" in set(b.outcome) else float("nan")
    eq = np.cumsum(b.sort_values("t").R.values); dd = float((np.maximum.accumulate(eq) - eq).max()) if n else 0
    print(f"  {label:<22} n={n:>4} WR={wr:>5.1f}% ΣR={sr:>+7.1f} R/сд={rpt:>+.3f} maxDD={dd:>5.1f} ΣR/DD={(sr/dd if dd>0 else float('nan')):>5.2f}")
    return sr, rpt


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    print(f"[{sym}] строю сигналы ViC-Vadim 12h Core (LTF {LTF_MIN}m)...")
    df, sigs = build_signals(sym)
    hh = sum(1 for s in sigs if s[1] == "SHORT"); lln = sum(1 for s in sigs if s[1] == "LONG")
    print(f"  сигналов: {len(sigs)} (HH/SHORT {hh}, LL/LONG {lln})  "
          f"{df.index[0].date()}..{df.index[-1].date()}")
    print("\n=== RR-cap grid (вход close(i), SL за свип-фитиль) ===")
    best = None
    for rr in RR_GRID:
        b = sim(df, sigs, rr)
        sr, rpt = summary(b, f"RR={rr}")
        if best is None or rpt > best[1]: best = (rr, rpt, b)
    print("\n=== time-stop close(i+2) ===")
    bts = sim(df, sigs, 0, timestop=True)
    summary(bts, "time-stop i+2")
    # детализация лучшего RR: по годам + HH/LL
    rr, rpt, b = best
    print(f"\n=== ДЕТАЛИ best RR={rr} ===")
    for d_ in ("SHORT", "LONG"):
        bd = b[b["dir"] == d_]; summary(bd, f"{d_} ({'HH' if d_=='SHORT' else 'LL'})")
    print("  по годам:")
    for yr, g in b.groupby("year"):
        wr = (g.outcome == "win").mean() * 100; print(f"    {yr}: n={len(g):>3} WR={wr:>5.1f}% ΣR={g.R.sum():>+6.1f}")


if __name__ == "__main__":
    main()
