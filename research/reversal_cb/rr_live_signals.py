"""LIVE-сигналы кандидатов за последний месяц на BTC: ①8h LONG RR2.5-4, ②12h SHORT RR1.5-4.
Свежие klines Binance + история CSV; финальный селектор на размеченной истории; флаг top-30% reversal-likelihood + RR-бакет.
Исход сделки сканируется до последнего бара (WIN/LOSS/OPEN). Выдаёт JSON+печать с таймстемпами/ценами для отрисовки.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/rr_live_signals.py
"""
from __future__ import annotations
import sys, json, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from reversal_analysis import load, feats, THR  # noqa: E402
from reversal_module import FEATS  # noqa: E402
from rr_native import native  # noqa: E402
from ev_rescue import cb_nw  # noqa: E402
HERE = Path(__file__).resolve().parent
DAYS = 35


def fetch_klines(interval, limit=1000):
    u = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
    r = json.load(urllib.request.urlopen(u, timeout=20))
    rows = [(pd.to_datetime(k[0], unit="ms", utc=True), float(k[1]), float(k[2]), float(k[3]),
             float(k[4]), float(k[5])) for k in r]
    return pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"]).set_index("open_time")


def run(tf, binance_int, direction, rlo, rhi):
    hist = load("BTCUSDT", tf)[["open", "high", "low", "close", "volume"]]
    live = fetch_klines(binance_int, 1000)
    comb = pd.concat([hist, live]); comb = comb[~comb.index.duplicated(keep="last")].sort_index().iloc[:-1]
    X = feats(comb)
    y, R, risk = native(comb, direction, 0.0010, 0.0010)
    m = (y >= 0) & X[FEATS].notna().all(axis=1).values
    proba_all = cb_nw(X[FEATS][m].values, y[m], X[FEATS].values)
    thr = float(np.quantile(proba_all[m], 0.70))
    c = comb.close.values; h = comb.high.values; lo = comb.low.values; n = len(c)
    last_t = comb.index[-1]
    cutoff = last_t - pd.Timedelta(days=DAYS)
    sigs = []
    idx = comb.index
    feat_ok = X[FEATS].notna().all(axis=1).values
    for i in range(n):
        if idx[i] < cutoff or not feat_ok[i]:
            continue
        p = proba_all[i]
        if p < thr:
            continue
        rk = (c[i] - lo[i]) / c[i] if direction == "long" else (h[i] - c[i]) / c[i]
        if rk <= 1e-5:
            continue
        RR = THR / rk
        if not (rlo <= RR < rhi):
            continue
        entry = c[i]
        stop = lo[i] if direction == "long" else h[i]
        tgt = entry * (1 + THR) if direction == "long" else entry * (1 - THR)
        # исход до последнего бара
        outc = "OPEN"; exit_t = None
        for j in range(i + 1, n):
            if direction == "long":
                if lo[j] < stop:
                    outc = "LOSS"; exit_t = idx[j]; break
                if h[j] >= tgt:
                    outc = "WIN"; exit_t = idx[j]; break
            else:
                if h[j] > stop:
                    outc = "LOSS"; exit_t = idx[j]; break
                if lo[j] <= tgt:
                    outc = "WIN"; exit_t = idx[j]; break
        sigs.append(dict(tf=tf, dir=direction, t=str(idx[i]), ts=int(idx[i].timestamp()),
                         entry=round(entry, 1), stop=round(stop, 1), tgt=round(tgt, 1),
                         RR=round(RR, 2), p=round(float(p), 3), outcome=outc,
                         exit_t=str(exit_t) if exit_t is not None else None,
                         exit_ts=int(exit_t.timestamp()) if exit_t is not None else None))
    return sigs, thr, last_t


def main():
    out = ["="*64, f" LIVE-СИГНАЛЫ за {DAYS} дней — BTC (reversal-кандидаты)", "="*64]
    allsig = []
    for tf, bint, d, rlo, rhi in [("8h", "8h", "long", 2.5, 4.0), ("12h", "12h", "short", 1.5, 4.0)]:
        sigs, thr, last_t = run(tf, bint, d, rlo, rhi)
        allsig += sigs
        out.append(f"\n  {tf} {d.upper()} RR[{rlo},{rhi}) — порог-флаг p={thr:.3f}, посл.бар {last_t:%Y-%m-%d %H:%M}")
        if not sigs:
            out.append("    (нет сигналов за период)")
        for s in sigs:
            ex = f" -> {s['outcome']}" + (f" {s['exit_t'][:16]}" if s['exit_t'] else "")
            out.append(f"    {s['t'][:16]}  {s['dir']:5} вход {s['entry']:.0f} стоп {s['stop']:.0f} "
                       f"TP {s['tgt']:.0f} RR{s['RR']:.1f} p{s['p']:.2f}{ex}")
    (HERE / "rr_live_signals.json").write_text(json.dumps(allsig, ensure_ascii=False, indent=2), encoding="utf-8")
    o = "\n".join(out); (HERE / "rr_live_signals_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
