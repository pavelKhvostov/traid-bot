"""ВАЛИДАЦИЯ балла-симбиоза как ФИЛЬТРА на входах 1.1.1 (считаемые компоненты: RSI/VWAP/ViC/наклон).

Балл на момент входа сделки 1.1.1 (на 4h): direction (-6..+6) + exhaustion (0..6). Проверяем:
  (1) сделка ПО ТРЕНДУ балла бьёт «против»? (confluence-направление как фильтр)
  (2) вход при НИЗКОМ исчерпании бьёт высокое? (не входить в перегрев)
Критерий ptt (RR=2.2) + cross-asset. MoneyHands/TechRatings нет истории -> исключены.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/confluence_filter_validate.py
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
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "research" / "ta_laws"))
from data_manager import load_df, compose_from_base  # noqa: E402
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals  # noqa: E402
from vol_gate_111_lowtf import dedup, sim_vec  # noqa: E402  (sim_vec -> (signal_time, fill_time, dir, win))

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAYS_BACK = 2400
RR = 2.2
SCORE_TF = "4h"


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    ru = pd.Series(up).ewm(alpha=1 / n, adjust=False).mean().values
    rd = pd.Series(dn).ewm(alpha=1 / n, adjust=False).mean().values
    rs = ru / (rd + 1e-9)
    return 100 - 100 / (1 + rs)


def confluence_series(df):
    """Возвращает (ts_ns, dir_score[], exh[], dir_sign[]) по барам 4h."""
    C = df["close"].values.astype(float); H = df["high"].values.astype(float)
    L = df["low"].values.astype(float); V = df["volume"].values.astype(float)
    tp = (H + L + C) / 3
    R = rsi(C, 14)
    vwap = (pd.Series(tp * V).rolling(42, min_periods=10).sum() /
            (pd.Series(V).rolling(42, min_periods=10).sum() + 1e-9)).values
    vstd = pd.Series(C).rolling(42, min_periods=10).std().values + 1e-9
    vz = (C - vwap) / vstd
    slope = np.zeros(len(C)); slope[20:] = (C[20:] - C[:-20]) / C[:-20] * 100 / 20
    # ViC POC rolling 30
    vic = np.full(len(C), np.nan)
    for i in range(30, len(C)):
        st, sv = tp[i - 30:i], V[i - 30:i]
        lo, hi = st.min(), st.max()
        if hi > lo:
            b = np.clip(((st - lo) / (hi - lo) * 23).astype(int), 0, 23)
            agg = np.zeros(24); np.add.at(agg, b, sv)
            vic[i] = lo + (agg.argmax() + 0.5) / 24 * (hi - lo)
        else:
            vic[i] = C[i]
    hh10 = pd.Series(C).rolling(10, min_periods=3).max().values
    ll10 = pd.Series(C).rolling(10, min_periods=3).min().values
    n = len(C); dirs = np.zeros(n); exh = np.zeros(n)
    for i in range(n):
        if not np.isfinite(vwap[i]) or not np.isfinite(vic[i]):
            dirs[i] = np.nan; exh[i] = np.nan; continue
        d = float(np.clip(slope[i] / 0.3, -2, 2))
        d += (1.5 if C[i] > vwap[i] else -1.5) + (0.5 if vz[i] > 1.5 else (-0.5 if vz[i] < -1.5 else 0))
        d += 1.2 if C[i] > vic[i] else -1.2
        d += (1.0 if R[i] > 50 else -1.0) + (0.7 if R[i] > 60 else (-0.7 if R[i] < 40 else 0))
        dirs[i] = d
        e = 3.0 if (R[i] >= 70 or R[i] <= 30) else (1.5 if (R[i] >= 64 or R[i] <= 36) else 0)
        e += 2.0 if abs(vz[i]) > 2 else (1.0 if abs(vz[i]) > 1.5 else 0)
        if (C[i] <= ll10[i] and R[i] > 38) or (C[i] >= hh10[i] and R[i] < 62):
            e += 1.5
        exh[i] = e
    ts = df.index.values.astype("datetime64[ns]").astype(np.int64)
    ct = ts + np.int64(int(pd.Timedelta(SCORE_TF).total_seconds() * 1e9))  # close time
    return ct, dirs, exh


def main():
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    rows = []; persym = {}
    for sym in SYMBOLS:
        print(f"[{sym}] detect+score...", flush=True)
        d1d = load_df(sym, "1d"); d12 = load_df(sym, "12h"); d4 = load_df(sym, "4h")
        d1h = load_df(sym, "1h"); d6 = compose_from_base(d1h, "6h"); d2 = compose_from_base(d1h, "2h")
        d15 = load_df(sym, "15m"); d1m = load_df(sym, "1m"); d20 = compose_from_base(d1m, "20m")
        sigs = dedup(detect_strategy_1_1_1_signals(d1d[d1d.index >= cutoff], d12[d12.index >= cutoff],
                                                   d4, d6, d1h, d2, d15, d20, verbose=False))
        tt = sim_vec(sigs, d1m, RR)
        ct, dirs, exh = confluence_series(d4)
        rr = []
        for (st, ft, d, win) in tt:
            a = np.datetime64(pd.Timestamp(ft).to_datetime64(), "ns").astype(np.int64)
            pos = int(np.searchsorted(ct, a, side="right")) - 1
            if not (0 <= pos < len(dirs)) or not np.isfinite(dirs[pos]):
                continue
            tdir = 1 if d == "LONG" else -1
            aligned = int(np.sign(dirs[pos]) == tdir)
            rr.append((aligned, exh[pos], 1 if win else 0))
        persym[sym] = rr; rows += rr
        print(f"  closed+score={len(rr)}", flush=True)

    al = np.array([r[0] for r in rows]); ex = np.array([r[1] for r in rows]); win = np.array([r[2] for r in rows])
    n = len(rows); allptt = (win.sum() * RR - (n - win.sum())) / n
    out = []; A = out.append
    A(f"ВАЛИДАЦИЯ confluence-балла как ФИЛЬТРА 1.1.1 (считаемые компоненты, RR={RR}, {n} сделок BTC+ETH+SOL)")
    A(f"Все сделки ptt {allptt:+.3f}.\n")

    def b(mask, lbl):
        k = int(mask.sum())
        if k == 0:
            return f"  {lbl:30} n=0"
        w = int(win[mask].sum())
        return f"  {lbl:30} n={k:4d}  WR={w/k*100:5.1f}%  ptt={(w*RR-(k-w))/k:+.3f}"

    A("=== (1) ФИЛЬТР НАПРАВЛЕНИЯ: сделка по тренду балла vs против ===")
    A(b(al == 1, "по тренду балла"))
    A(b(al == 0, "против тренда балла"))
    A("=== (2) ФИЛЬТР ИСЧЕРПАНИЯ: вход при низком vs высоком исчерпании ===")
    exmed = np.nanmedian(ex)
    A(b(ex <= 2, "низкое исчерпание (<=2)"))
    A(b((ex > 2) & (ex < 4), "среднее"))
    A(b(ex >= 4, "высокое исчерпание (>=4)"))
    A("=== (3) КОМБО: по тренду + низкое исчерпание ===")
    A(b((al == 1) & (ex <= 2), "по тренду & низк.исчерп."))
    A(b((al == 0) | (ex >= 4), "против ИЛИ высок.исчерп."))

    A("\n=== cross-asset (ptt по тренду / против) ===")
    cons = 0
    for s in SYMBOLS:
        aa = np.array([r[0] for r in persym[s]]); ww = np.array([r[2] for r in persym[s]])
        if len(aa) < 20:
            A(f"  {s}: мало"); continue
        pa = (ww[aa == 1].sum() * RR - ((aa == 1).sum() - ww[aa == 1].sum())) / max(1, (aa == 1).sum())
        pg = (ww[aa == 0].sum() * RR - ((aa == 0).sum() - ww[aa == 0].sum())) / max(1, (aa == 0).sum())
        cons += int(pa > pg)
        A(f"  {s}: по тренду {pa:+.3f} / против {pg:+.3f}")

    pa = (win[al == 1].sum() * RR - ((al == 1).sum() - win[al == 1].sum())) / max(1, (al == 1).sum())
    pg = (win[al == 0].sum() * RR - ((al == 0).sum() - win[al == 0].sum())) / max(1, (al == 0).sum())
    plo = (win[ex <= 2].sum() * RR - ((ex <= 2).sum() - win[ex <= 2].sum())) / max(1, (ex <= 2).sum())
    phi = (win[ex >= 4].sum() * RR - ((ex >= 4).sum() - win[ex >= 4].sum())) / max(1, (ex >= 4).sum())
    A("\n=== ВЕРДИКТ ===")
    A(f"  направление-фильтр: по тренду {pa:+.3f} vs против {pg:+.3f} (cross {cons}/3) -> "
      f"{'ПОМОГАЕТ' if pa > pg + 0.05 and cons >= 2 else 'нейтрально (как и ожидалось — confluence направление=монетка)'}")
    A(f"  исчерпание-фильтр: низк {plo:+.3f} vs высок {phi:+.3f} -> "
      f"{'НИЗКОЕ ЛУЧШЕ (не входить в перегрев)' if plo > phi + 0.05 else ('ВЫСОКОЕ лучше (вход в перегрев=по тренду сильному)' if phi > plo + 0.05 else 'нейтрально')}")

    rep = Path(__file__).resolve().parent / "confluence_filter_validate_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
