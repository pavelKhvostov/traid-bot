"""etap_220 — #5 Triple-barrier + meta-labeling (AFML / Lopez de Prado).

Доводим слой #2 до ТОРГУЕМОГО вида:
  (a) Triple-barrier: от точки решения (k=5, после IB) вход=close[k5], TP/SL = ±m·dailyATR,
      vertical = конец дня. Метка = задет ли TP по стороне сигнала раньше SL (win/loss/timeout).
      Это честный торгуемый исход вместо «цвет дня».
  (b) Meta-labeling: первичный сигнал = call слоя day-type (LONG/SHORT по p). Вторичная
      модель решает БРАТЬ/ПРОПУСТИТЬ. Гипотеза: day-type (TREND vs ROTATION) и уверенность
      = естественный мета-фильтр (TREND-дни → выше precision и R). Purged-CV.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_220_triplebarrier_meta.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_217_daytype_layer as L
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

DATA = HERE.parent.parent / "data" / "BTCUSDT_1h_orderflow.csv"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")
KDEC = 5          # час принятия решения (после IB)
MULT = 0.6        # барьеры = ±0.6 · dailyATR


def daily_atr(df, n=14):
    d = df.resample("1D").agg({"high": "max", "low": "min", "close": "last"})
    tr = pd.concat([d.high-d.low, (d.high-d.close.shift()).abs(), (d.low-d.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def main():
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    datr = daily_atr(df)

    # модель слоя day-type (как в etap_217)
    R = L.build(df).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    tr_rows = R[R.day < CUTOFF]
    M = L.fit_per_hour(tr_rows)
    R = R.assign(p=L.predict(M, R[["k"]+L.FEATS]))

    # triple-barrier от точки решения k=KDEC
    dd = df.index.normalize(); recs = []
    pmap = R[R.k == KDEC].set_index("day")
    for day, g in df.groupby(dd):
        if len(g) <= KDEC+1 or day not in pmap.index: continue
        atrv = datr.reindex([day]).iloc[0]
        if not np.isfinite(atrv) or atrv <= 0: continue
        row = pmap.loc[day]
        c = g["close"].values; H = g["high"].values; Lo = g["low"].values
        entry = c[KDEC]; up = entry+MULT*atrv; dn = entry-MULT*atrv
        tb = 0
        for j in range(KDEC+1, len(g)):
            if H[j] >= up: tb = 1; break
            if Lo[j] <= dn: tb = -1; break
        state, mode = L.classify(row)
        p = row["p"]; call = "LONG" if p > 0.6 else ("SHORT" if p < 0.4 else "SKIP")
        # исход сделки по стороне сигнала: win если tb совпал, R = +1/-1/0(timeout)
        win = (call == "LONG" and tb == 1) or (call == "SHORT" and tb == -1)
        loss = (call == "LONG" and tb == -1) or (call == "SHORT" and tb == 1)
        Rr = 1.0 if win else (-1.0 if loss else 0.0)
        recs.append(dict(day=day, year=day.year, p=p, conf=abs(p-0.5)*2, state=state, call=call,
                         tb=tb, win=int(win), loss=int(loss), R=Rr,
                         **{f: row[f] for f in L.FEATS}))
    D = pd.DataFrame(recs)
    te = D[(D.day >= CUTOFF)]
    print("="*70); print(f"#5 TRIPLE-BARRIER (±{MULT}·ATR, реш. k={KDEC}) — OOS 2023+"); print("="*70)
    print(f"  распределение метки: TP-up {np.mean(D.tb==1):.2f} | SL-dn {np.mean(D.tb==-1):.2f} | timeout {np.mean(D.tb==0):.2f}")

    print("\n■ МЕТА-ФИЛЬТР: сигналы слоя без/с фильтром (по сделкам, не SKIP)")
    tt = te[te.call != "SKIP"]
    def block(g, lab):
        n = len(g); wr = g.win.mean()*100 if n else 0; er = g.R.mean() if n else 0
        cov = n/len(tt)*100 if len(tt) else 0
        print(f"   {lab:<34} n={n:>4} ({cov:>3.0f}% сделок) WR={wr:>4.0f}% E[R]={er:>+.3f}")
    block(tt, "ВСЕ сигналы (первичные)")
    block(tt[tt.state.isin(["TREND_UP", "TREND_DOWN"])], "только TREND-дни (meta=day-type)")
    block(tt[tt.state == "ROTATION"], "только ROTATION (контроль)")
    block(tt[tt.conf >= 0.3], "только conf≥0.3 (уверенные)")
    block(tt[(tt.state.isin(["TREND_UP","TREND_DOWN"])) & (tt.conf >= 0.3)], "TREND & conf≥0.3 (оба фильтра)")

    # purged-CV мета-модель: предсказать win по фичам слоя, обучаясь только на train, OOS на test
    print("\n■ Обучаемый мета-фильтр (logistic на фичах слоя → P(win)), purged по дате")
    trd = D[(D.day < CUTOFF) & (D.call != "SKIP")]
    mm = LogisticRegression(max_iter=400).fit(trd[L.FEATS+["conf"]], trd.win)
    tt = tt.assign(pwin=mm.predict_proba(tt[L.FEATS+["conf"]])[:, 1])
    auc = roc_auc_score(tt.win, tt.pwin)
    print(f"   meta P(win) OOS AUC = {auc:.3f}")
    for thr in [0.5, 0.55, 0.6]:
        g = tt[tt.pwin >= thr]
        if len(g): print(f"   take if P(win)≥{thr}: n={len(g):>4} ({len(g)/len(tt)*100:>3.0f}%) WR={g.win.mean()*100:>4.0f}% E[R]={g.R.mean():>+.3f}")

    D.to_csv(HERE / "output" / "etap_220_triplebarrier.csv", index=False)
    print("\nSaved: output/etap_220_triplebarrier.csv")


if __name__ == "__main__":
    main()
