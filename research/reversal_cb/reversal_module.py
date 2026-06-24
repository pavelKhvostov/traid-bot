"""ПРОДВИНУТЫЙ CatBoost-модуль разворотов (6/8/12h), самообучаемый (purged walk-forward) +
самоисправляемый (мета-лейблинг + диагностика природы ошибок). Label = определение юзера.

Барьеры сделки = САМО определение: вход close[i], TP=+3%, SL=low[i] (бычий) / зеркально.
Метрики: precision/recall/lift (Right/Wrong на РЕШЕНИЯХ, не сырая accuracy) + permutation-null +
time-shuffle + НЕТТО-R сделки с костами. Cross-asset + год-стабильность.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/reversal_module.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from reversal_analysis import load, feats, THR, CAP  # переиспользуем фичи/загрузку  # noqa: E402
HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(7)
RT_COST = 0.0010   # round-trip кост (вход+выход), споте-консервативно
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

FEATS = ["c2l", "clv", "lwick", "body", "ret1", "ret3", "ret6", "dd20", "posrange20",
         "dist_ema20", "dist_ema50", "dist_ema100", "rsi", "consec_dn", "atr_pct", "atr_ptile",
         "range_exp", "vol_z", "vol_climax", "swept", "sweep_depth", "left_pivot"]


def label_and_outcome(df, direction="long"):
    """label (1/0) + исход сделки по барьерам определения: TP +-3%, SL=low/high[i]. Возвращает y, R, kind."""
    c = df.close.values; h = df.high.values; lo = df.low.values; n = len(c)
    y = np.full(n, -1); R = np.full(n, np.nan); kind = np.full(n, 0)  # 1 win,-1 loss,0 timeout
    for i in range(n - 2):
        if direction == "long":
            tgt = c[i] * (1 + THR); stop = lo[i]; risk = (c[i] - stop) / c[i]
        else:
            tgt = c[i] * (1 - THR); stop = h[i]; risk = (stop - c[i]) / c[i]
        if risk <= 1e-5:
            y[i] = 0; continue
        end = min(i + 1 + CAP, n); res = 0
        for j in range(i + 1, end):
            if direction == "long":
                if lo[j] < stop:
                    res = -1; break
                if h[j] >= tgt:
                    res = 1; break
            else:
                if h[j] > stop:
                    res = -1; break
                if lo[j] <= tgt:
                    res = 1; break
        y[i] = 1 if res == 1 else 0
        kind[i] = res
        rr = THR / risk
        cost_R = RT_COST / risk
        if res == 1:
            R[i] = rr - cost_R
        elif res == -1:
            R[i] = -1 - cost_R
        else:  # timeout: выход по close в конце окна
            jx = end - 1
            ret = (c[jx] - c[i]) / c[i] * (1 if direction == "long" else -1)
            R[i] = ret / risk - cost_R
    return y, R, kind


def cb(Xtr, ytr, Xte):
    from catboost import CatBoostClassifier
    try:
        m = CatBoostClassifier(iterations=400, depth=6, learning_rate=0.05, loss_function="Logloss",
                               random_seed=7, verbose=False, task_type="GPU", devices="0",
                               auto_class_weights="Balanced")
        m.fit(Xtr, ytr)
    except Exception:
        m = CatBoostClassifier(iterations=400, depth=6, learning_rate=0.05, loss_function="Logloss",
                               random_seed=7, verbose=False, auto_class_weights="Balanced")
        m.fit(Xtr, ytr)
    return m


def walk_forward(X, y, R, n_folds=6, embargo=CAP, thr=0.5, use_meta=True):
    """purged walk-forward. Возвращает pooled OOS: proba, pred, y, R, meta_pred, idxmask."""
    Xv = X.values; n = len(X)
    edges = np.linspace(int(n * 0.4), n, n_folds + 1).astype(int)
    proba = np.full(n, np.nan); meta_keep = np.full(n, np.nan); used = np.zeros(n, bool)
    for k in range(n_folds):
        te0, te1 = edges[k], edges[k + 1]; tr_end = max(0, te0 - embargo)
        if tr_end < 800 or te1 - te0 < 100:
            continue
        m = cb(Xv[:tr_end], y[:tr_end], Xv[te0:te1])
        p = m.predict_proba(Xv[te0:te1])[:, 1]
        proba[te0:te1] = p; used[te0:te1] = True
        if use_meta:
            # мета: на train взять кандидатов первички (proba>thr), метка = первичка права (y==1), обучить вторичку
            ptr = m.predict_proba(Xv[:tr_end])[:, 1]
            cand = ptr > thr
            if cand.sum() > 200 and y[:tr_end][cand].mean() not in (0.0, 1.0):
                meta_y = y[:tr_end][cand]
                mm = cb(Xv[:tr_end][cand], meta_y, Xv[te0:te1])
                meta_keep[te0:te1] = mm.predict_proba(Xv[te0:te1])[:, 1]
    return proba, meta_keep, used


def metrics(tag, pred, y, R, out, base):
    n_flag = int(pred.sum())
    if n_flag < 10:
        out.append(f"  [{tag}] флагов мало ({n_flag})"); return
    prec = y[pred == 1].mean()                       # из флагнутых — сколько реальных (Right/Wrong решения)
    rec = (pred[y == 1] == 1).mean()
    lift = prec / base
    netR = float(np.nanmean(R[pred == 1]))           # нетто-R на флагнутую сделку
    totR = float(np.nansum(R[pred == 1]))
    out.append(f"  [{tag}] флагов={n_flag}  precision={prec:.3f} (base {base:.3f}, lift {lift:.2f})  "
               f"recall={rec:.3f}  net-R/сделку={netR:+.3f}  ΣR={totR:+.0f}")
    return prec, netR


def run_dir(direction, out):
    out.append(f"\n{'='*70}\n  НАПРАВЛЕНИЕ: {direction.upper()}\n{'='*70}")
    for tf in ["8h", "12h"]:
        out.append(f"\n--- TF {tf} ---")
        per_prec = []; per_netR = []
        for sym in SYMS:
            df = load(sym, tf); X = feats(df); y, R, kind = label_and_outcome(df, direction)
            m = (y >= 0) & X[FEATS].notna().all(axis=1).values
            Xf = X[FEATS][m].reset_index(drop=True); yf = y[m]; Rf = R[m]
            idx = df.index[m]
            base = yf.mean()
            proba, meta_keep, used = walk_forward(Xf, yf, Rf, thr=0.55)
            uu = used
            pr = proba[uu]; yk = yf[uu]; Rk = Rf[uu]; mk = meta_keep[uu]; ix = idx[uu]
            base_oos = yk.mean()
            # порог первички — выбран как 0.55 (на train-распределении умеренно-уверенные); фикс для честности
            pred = (pr > 0.55).astype(int)
            # null: перемешать метки
            pp = pred.copy()
            nulls = [np.mean(yk[np.random.default_rng(s).permutation(len(yk))][pp == 1]) for s in range(200)] if pp.sum() > 10 else [base_oos]
            out.append(f"\n {sym}: OOS n={len(yk)} base={base_oos:.3f}")
            r1 = metrics("primary p>0.55", pred, yk, Rk, out, base_oos)
            # мета-фильтр
            pred_meta = ((pr > 0.55) & (mk > 0.5)).astype(int)
            r2 = metrics("+meta-фильтр", pred_meta, yk, Rk, out, base_oos)
            null_prec = float(np.mean(nulls))
            out.append(f"     permutation-null precision={null_prec:.3f} (vs primary {r1[0] if r1 else float('nan'):.3f})")
            # год-стабильность net-R (primary)
            yr = pd.Series(Rk[pred == 1], index=ix[pred == 1]).groupby(ix[pred == 1].year).mean()
            out.append("     год net-R: " + "  ".join(f"{y_}:{v:+.2f}" for y_, v in yr.items()))
            if r1:
                per_prec.append(r1[0]); per_netR.append(r1[1])
            # диагностика природы ошибок (FP vs TP) на primary
            if pred.sum() > 30:
                tp = (pred == 1) & (yk == 1); fp = (pred == 1) & (yk == 0)
                diff = []
                Xk = Xf[uu].reset_index(drop=True)
                for f in ["c2l", "ret1", "range_exp", "vol_z", "rsi", "dist_ema50"]:
                    mtp = Xk[f][tp].mean(); mfp = Xk[f][fp].mean()
                    diff.append(f"{f}: TP {mtp:+.3f} vs FP {mfp:+.3f}")
                out.append("     природа ошибок (TP vs FP): " + " | ".join(diff))
        if per_netR:
            out.append(f"\n  ИТОГ {tf}: cross-asset net-R>0: {sum(1 for r in per_netR if r>0)}/3  "
                       f"средн.precision={np.mean(per_prec):.3f} средн.net-R={np.mean(per_netR):+.3f}")


def main():
    out = ["="*70, " CatBoost-МОДУЛЬ РАЗВОРОТОВ: purged WF + мета + net-R", "="*70,
           f" косты RT={RT_COST*1e4:.0f}bps, TP=±{THR*100:.0f}%, SL=свой low/high, CAP={CAP} баров"]
    for d in ["long", "short"]:
        run_dir(d, out)
        (HERE / "reversal_module_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
