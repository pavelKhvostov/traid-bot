"""Глубокий факторный анализ FADE-закона: какие факторы усиливают/убивают edge.

Метрика: tb_fade_R (+1 если против импульса первым к 1.5ATR, -1 если по импульсу). Только архетипы.
1) UNIVARIATE: каждый фактор -> бакеты -> fade-R, спред (важность), монотонность, null-p лучшего бакета,
   cross-asset (символы+), год-стабильность.
2) MULTIVARIATE: HistGBM предсказывает fade-win по всем факторам -> OOS AUC + SHUFFLE-контроль + importances.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/factor_rank.py
Выход: research/ta_laws/factors_report.txt
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

HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(11)

CONT = ["depth_pct", "imp_atr_mag", "imp_bars", "corr_bars", "vol_contr", "arm_vol_z",
        "atr_pct", "run_before", "range_pos", "corr_piv", "imp_eff"]
CAT = ["against", "htf_aligned", "regime", "mtf_align", "converging"]


def null_p_ge(mean, nv, n, iters=2000):
    if len(nv) < 5 or n < 3:
        return 1.0
    m = nv[RNG.integers(0, len(nv), size=(iters, n))].mean(axis=1)
    return float((m >= mean).mean())


def main():
    df = pd.read_csv(HERE / "law_records.csv")
    a = df[(df.is_null == 0) & (df.tb != "none")].copy()
    nv = df[(df.is_null == 1) & (df.tb != "none")].tb_fade_R.values
    for col in CONT:
        a[col] = pd.to_numeric(a[col], errors="coerce")

    out = []
    out.append("ГЛУБОКИЕ ФАКТОРЫ FADE-закона — что усиливает/убивает edge.")
    out.append(f"Решённых архетипов: {len(a)} | базовый fade-R = {a.tb_fade_R.mean():+.3f} | null = {nv.mean():+.3f}\n")

    rank = []  # (factor, spread, detail, monotonic, best_mean, best_p, best_symp)

    out.append("=== UNIVARIATE: fade-R по бакетам (low/mid/high или категориям) ===")
    for f in CONT:
        s = a.dropna(subset=[f])
        if len(s) < 100:
            continue
        try:
            s = s.assign(_b=pd.qcut(s[f], 3, labels=["low", "mid", "high"], duplicates="drop"))
        except Exception:
            continue
        g = s.groupby("_b", observed=True).tb_fade_R
        means = g.mean()
        if len(means) < 2:
            continue
        spread = means.max() - means.min()
        best_b = means.idxmax()
        bb = s[s._b == best_b]
        bp = null_p_ge(means.max(), nv, len(bb))
        symp = int((bb.groupby("symbol").tb_fade_R.mean() > 0).sum())
        mono = "↑" if means.get("high", -9) > means.get("low", 9) else ("↓" if means.get("low", -9) > means.get("high", 9) else "~")
        detail = " ".join(f"{b}({int(g.count()[b])}):{means[b]:+.2f}" for b in means.index)
        rank.append((f, spread, detail, mono, means.max(), bp, symp))

    for f in CAT:
        s = a.dropna(subset=[f])
        g = s.groupby(f, observed=True).tb_fade_R
        means = g.mean()
        if len(means) < 2:
            continue
        spread = means.max() - means.min()
        best_v = means.idxmax(); bb = s[s[f] == best_v]
        bp = null_p_ge(means.max(), nv, len(bb))
        symp = int((bb.groupby("symbol").tb_fade_R.mean() > 0).sum())
        detail = " ".join(f"{v}({int(g.count()[v])}):{means[v]:+.2f}" for v in means.index)
        rank.append((f, spread, detail, "cat", means.max(), bp, symp))

    rank.sort(key=lambda x: x[1], reverse=True)
    out.append(f"\n{'фактор':14} {'спред':>6} {'монот':>6} {'лучш':>6} {'p':>6} {'sym+':>5}  бакеты")
    for f, sp, det, mono, bm, bp, symp in rank:
        out.append(f"{f:14} {sp:>6.3f} {mono:>6} {bm:>+6.2f} {bp:>6.3f} {symp:>4}/3  {det}")

    out.append("\n=== ТОП факторы-усилители (спред>0.10, лучший бакет p<0.05, sym+>=2) ===")
    strong = [r for r in rank if r[1] > 0.10 and r[5] < 0.05 and r[6] >= 2]
    for f, sp, det, mono, bm, bp, symp in strong:
        out.append(f"  {f:14} спред {sp:.2f} {mono}  -> сильнейший бакет fadeR {bm:+.2f} (p={bp:.3f}): {det}")
    if not strong:
        out.append("  нет сильных")

    # MULTIVARIATE
    out.append("\n=== MULTIVARIATE: HistGBM предсказывает fade-win по всем факторам ===")
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.metrics import roc_auc_score
        feats = CONT + ["against", "htf_aligned", "regime", "mtf_align", "converging", "hour", "dow"]
        d = a.copy()
        for col in feats:
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d.sort_values("arm")
        y = (d.tb_fade_R > 0).astype(int).values
        X = d[feats].values
        k = int(len(d) * 0.7)
        Xtr, Xte, ytr, yte = X[:k], X[k:], y[:k], y[k:]
        m = HistGradientBoostingClassifier(max_iter=200, max_depth=4, learning_rate=0.05,
                                           l2_regularization=1.0, random_state=0)
        m.fit(Xtr, ytr)
        auc = roc_auc_score(yte, m.predict_proba(Xte)[:, 1])
        # shuffle-контроль
        ysh = RNG.permutation(ytr)
        m2 = HistGradientBoostingClassifier(max_iter=200, max_depth=4, learning_rate=0.05,
                                            l2_regularization=1.0, random_state=0)
        m2.fit(Xtr, ysh)
        auc_sh = roc_auc_score(yte, m2.predict_proba(Xte)[:, 1])
        out.append(f"  OOS AUC (time-split 70/30) = {auc:.3f} | SHUFFLE-метки AUC = {auc_sh:.3f}")
        out.append(f"  -> {'модель БЬЁТ shuffle (факторы комбинируются)' if auc - auc_sh > 0.02 else 'НЕ бьёт shuffle (факторы НЕ дают робастной комбинации)'}")
        # permutation importance (грубо: по падению AUC при перемешивании фичи)
        base = auc
        imps = []
        for i, fn in enumerate(feats):
            Xp = Xte.copy(); Xp[:, i] = RNG.permutation(Xp[:, i])
            imps.append((fn, base - roc_auc_score(yte, m.predict_proba(Xp)[:, 1])))
        imps.sort(key=lambda x: x[1], reverse=True)
        out.append("  Важность (падение OOS AUC при перемешивании фичи):")
        for fn, imp in imps[:8]:
            out.append(f"    {fn:14} {imp:+.4f}")
    except Exception as ex:
        out.append(f"  sklearn недоступен/ошибка: {ex}")

    out.append("\n=== СВОД ===")
    out.append("  Базовый fade держится во всех бакетах; усилители (по спреду) — выше. "
               "Мультивариат с shuffle-контролем показывает, комбинируются ли факторы за пределами одиночного эффекта.")

    rep = HERE / "factors_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[factors] -> {rep.name}")


if __name__ == "__main__":
    main()
