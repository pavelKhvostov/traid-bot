"""LIVE: как разворотная модель видит BTC сейчас (reversal-likelihood, аналитика — НЕ торговый триггер).
Финальная CatBoost (no class-weights, нативная p) на всей истории + walk-forward OOS для калибровки уровня
(перцентиль + ист. hit-rate). Свежие 12h с Binance. Выдаёт скор по последним свечам + текущее чтение + JSON для отрисовки.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/reversal_live.py
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
from reversal_analysis import load, feats, THR, CAP  # noqa: E402
from reversal_module import FEATS, label_and_outcome  # noqa: E402
from ev_rescue import cb_nw, wf_raw  # noqa: E402
HERE = Path(__file__).resolve().parent
TF = "12h"
BINANCE_INT = "12h"
DIR = sys.argv[1] if len(sys.argv) > 1 else "long"   # long=бычье дно, short=медвежья вершина


def fetch_klines(sym="BTCUSDT", interval="12h", limit=1000):
    u = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
    r = json.load(urllib.request.urlopen(u, timeout=20))
    rows = [(pd.to_datetime(k[0], unit="ms", utc=True), float(k[1]), float(k[2]), float(k[3]),
             float(k[4]), float(k[5])) for k in r]
    return pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"]).set_index("open_time")


def main():
    out = ["="*60, f" LIVE reversal-likelihood BTC {TF} (аналитика, не триггер)", "="*60]
    # история + свежие бары -> объединить (корректные rolling-окна на хвосте)
    hist = load("BTCUSDT", TF)[["open", "high", "low", "close", "volume"]]
    live = fetch_klines("BTCUSDT", BINANCE_INT, 1000)
    comb = pd.concat([hist, live])
    comb = comb[~comb.index.duplicated(keep="last")].sort_index()
    # отбросить незакрытый последний бар (если open_time + TF > now): берём все, последний бар Binance — закрытый? klines даёт текущий открытый последним.
    comb = comb.iloc[:-1]  # убрать текущий незакрытый
    X = feats(comb)
    y, R, kind = label_and_outcome(comb, DIR)
    side = "бычье дно" if DIR == "long" else "медвежья вершина"
    m = (y >= 0) & X[FEATS].notna().all(axis=1).values
    Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]
    # калибровка: walk-forward OOS proba
    proba_oos, foldid = wf_raw(Xf, yf)
    uu = foldid >= 0
    p_oos = proba_oos[uu]; y_oos = yf[uu]
    base = y_oos.mean()
    # финальная модель на всей размеченной истории
    Xfull = X[FEATS][m].values
    p_recent_all = cb_nw(Xfull, yf, X[FEATS].values)  # предсказание на ВСЕХ барах (вкл. неразмеченный хвост)
    thr80 = float(np.quantile(p_oos, 0.80))           # порог флага = топ-20% уверенности
    out.append(f"размечено {len(yf)} баров, OOS-калибровка {len(y_oos)}, base={base:.3f}, "
               f"порог-флаг(p80)={thr80:.3f}")

    # последние ~45 баров: скор + флаг + геометрия
    N = 45
    tail = comb.index[-N:]
    recs = []
    Xall = X[FEATS]
    for t in tail:
        if t not in Xall.index:
            continue
        pos = Xall.index.get_loc(t)
        p = float(p_recent_all[pos])
        pct = float((p_oos <= p).mean() * 100)
        hr = float(y_oos[p_oos >= p].mean()) if (p_oos >= p).sum() >= 30 else float("nan")
        c = float(comb.loc[t, "close"])
        stop_lvl = float(comb.loc[t, "low"]) if DIR == "long" else float(comb.loc[t, "high"])
        tgt = c * (1 + THR) if DIR == "long" else c * (1 - THR)
        recs.append(dict(t=str(t), close=round(c, 1), stop=round(stop_lvl, 1), p=round(p, 3),
                         pct=round(pct, 1), hit=None if np.isnan(hr) else round(hr, 3),
                         flag=bool(p >= thr80), tgt=round(tgt, 1),
                         ts=int(t.timestamp())))
    flagged = [r for r in recs if r["flag"]]
    last = recs[-1]
    out.append(f"\nпоследний закрытый {TF} бар: {last['t']}  close={last['close']}")
    out.append(f"  reversal-likelihood ({side}) p={last['p']:.3f}  перцентиль {last['pct']:.0f}%  "
               f"ист.hit-rate={last['hit']}  {'>>> ФЛАГ' if last['flag'] else '(не флаг)'}")
    out.append(f"\nФЛАГНУТЫЕ развороты в последних {N} барах ({len(flagged)} шт, p>={thr80:.2f}):")
    for r in flagged[-12:]:
        out.append(f"  {r['t'][:16]}  close={r['close']:.0f} stop={r['stop']:.0f} p={r['p']:.3f} "
                   f"(перц {r['pct']:.0f}%, hit {r['hit']}) TP±3%={r['tgt']:.0f}")
    sfx = "" if DIR == "long" else "_short"
    (HERE / f"reversal_live_signal{sfx}.json").write_text(json.dumps(dict(tf=TF, dir=DIR, base=base, thr80=thr80,
        recent=recs, flagged=flagged, last=last), ensure_ascii=False, indent=2), encoding="utf-8")
    o = "\n".join(out); (HERE / f"reversal_live_report{sfx}.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
