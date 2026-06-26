"""Стейтмен последнего уровня: средний edge<кост, но топ-conviction подмножество может пробить кост?
Тот же 15m walk-forward, но храним PROBA -> разбивка по уверенности (децили |p-0.5|), net-taker/maker на сделку.
Если даже топ-дециль gross < кост -> kill закалён окончательно. Если топ пробивает maker -> реальный (maker-зависимый) лид.
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
from micro_direction import build_bars, features, PRICE_ONLY, FLOW, TAKER_RT, MAKER_RT  # noqa: E402
HERE = Path(__file__).resolve().parent


def cb_oos_proba(X, feats, n_folds=6, embargo=20):
    from catboost import CatBoostClassifier
    Xv = X[feats].values; y = (X["fwd"] > 0).astype(int).values; fwd = X["fwd"].values
    n = len(X); edges = np.linspace(int(n * 0.4), n, n_folds + 1).astype(int)
    proba = np.full(n, np.nan); used = np.zeros(n, bool)
    for k in range(n_folds):
        te0, te1 = edges[k], edges[k + 1]; tr_end = max(0, te0 - embargo)
        if tr_end < 500 or te1 - te0 < 100:
            continue
        try:
            m = CatBoostClassifier(iterations=350, depth=6, learning_rate=0.05, loss_function="Logloss",
                                   random_seed=7, verbose=False, task_type="GPU", devices="0")
            m.fit(Xv[:tr_end], y[:tr_end])
        except Exception:
            m = CatBoostClassifier(iterations=350, depth=6, learning_rate=0.05, loss_function="Logloss",
                                   random_seed=7, verbose=False); m.fit(Xv[:tr_end], y[:tr_end])
        proba[te0:te1] = m.predict_proba(Xv[te0:te1])[:, 1]; used[te0:te1] = True
    return proba[used], y[used], fwd[used]


def main():
    out = ["="*70, " 15m CONVICTION-ФИЛЬТР: пробивает ли топ-уверенность кост?", "="*70]
    bar = build_bars("15min"); X = features(bar)
    p, y, fwd = cb_oos_proba(X, PRICE_ONLY + FLOW)
    conv = np.abs(p - 0.5)                      # уверенность
    pred = (p > 0.5).astype(int)
    sgn = np.where(pred == 1, 1, -1)
    pnl = sgn * fwd                             # gross per-bar signed return
    out.append(f"OOS баров={len(y)}  база gross={np.mean(pnl)*1e4:+.2f}bps  (taker {TAKER_RT*1e4:.0f} / maker {MAKER_RT*1e4:.0f}bps RT)")
    out.append(f"\n{'порог топ-%':>12}{'n':>9}{'acc':>8}{'gross_bps':>11}{'net-taker':>11}{'net-maker':>11}")
    order = np.argsort(-conv)                   # по убыв. уверенности
    for frac in [1.0, 0.5, 0.25, 0.10, 0.05, 0.02, 0.01]:
        k = int(len(order) * frac); sel = order[:k]
        acc = (pred[sel] == y[sel]).mean(); g = np.mean(pnl[sel])
        out.append(f"{frac*100:>11.0f}%{k:>9}{acc:>8.4f}{g*1e4:>+11.2f}{(g-TAKER_RT)*1e4:>+11.2f}{(g-MAKER_RT)*1e4:>+11.2f}")
    # для справки: насколько большой gross нужен — это RT в bps
    out.append(f"\nЧтобы пробить: gross должен превысить {MAKER_RT*1e4:.0f}bps (maker) / {TAKER_RT*1e4:.0f}bps (taker).")
    o = "\n".join(out); (HERE / "micro_threshold_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
