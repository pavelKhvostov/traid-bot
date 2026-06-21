"""Промотировать ли order-flow absorption в SCORED фактор? Честный null-тест.

Гипотеза: уровень, поглотивший ВСТРЕЧНЫЙ поток на прошлой реакции (support поглотил
продажи / resistance — покупки), удержится чаще. Фича absorp_signal = effort * align,
align = -delta (support) | +delta (resistance) — больше = больше встречного потока поглощено.
Метка y = удержание (REJECT=1 / BREAK=0). Дисциплина как le_validate_null:
  - naive shuffle-y (ловушка) → p
  - стратиф-shuffle ВНУТРИ бинов [dist×atr] → p (контроль конфаунда близость×волатильность)
  - инкремент AUC[y~dist+atr] vs +absorp → Δ
  - год-стабильность знака
KEEP-SCORE только если стратиф-p<0.05 И инкремент>0.005 И год-стабильно; иначе descriptive-only.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LogisticRegression

RNG = np.random.default_rng(7); N = 2000


def main():
    fp = HERE / "_val_BTCUSDT.csv"
    df = pd.read_csv(fp)
    df = df.dropna(subset=["y", "dist_rel", "atr_rel", "absorp_effort", "absorp_delta", "role"])
    df = df[df["absorp_effort"] > 0].copy()                 # только тесты с измеренным потоком
    align = np.where(df["role"] == "support", -df["absorp_delta"], df["absorp_delta"])
    df["absorp_signal"] = df["absorp_effort"].values * align
    y = df["y"].values.astype(int); x = df["absorp_signal"].values
    n = len(df)
    if n < 50 or len(set(y)) < 2:
        print(f"мало данных (n={n})"); return
    real = roc_auc_score(y, x)
    print(f"\norder-flow absorption: n={n}, base hold {y.mean():.1%}, AUC(absorp_signal)={real:.3f}")
    print(f"  (effort med {df.absorp_effort.median():.1f}, |delta| med {df.absorp_delta.abs().median():.2f})")

    naive = np.array([roc_auc_score(RNG.permutation(y), x) for _ in range(N)])
    p1 = (naive >= real).mean() if real >= 0.5 else (naive <= real).mean()
    print(f"[1] наивный shuffle-y: mean {naive.mean():.3f} -> p={p1:.3f}")

    dq = pd.qcut(df["dist_rel"].rank(method="first"), 4, labels=False)
    aq = pd.qcut(df["atr_rel"].rank(method="first"), 4, labels=False)
    strata = dq.values * 4 + aq.values
    ns = []
    for _ in range(N):
        sh = x.copy()
        for s in np.unique(strata):
            idx = np.where(strata == s)[0]
            sh[idx] = RNG.permutation(x[idx])
        ns.append(roc_auc_score(y, sh))
    ns = np.array(ns)
    p2 = (ns >= real).mean() if real >= 0.5 else (ns <= real).mean()
    print(f"[2] стратиф-shuffle (dist×atr): mean {ns.mean():.3f}, 95%до {np.quantile(ns,0.95):.3f} -> p={p2:.3f}")

    X0 = df[["dist_rel", "atr_rel"]].values
    X1 = df[["dist_rel", "atr_rel", "absorp_signal"]].values
    a0 = roc_auc_score(y, LogisticRegression(max_iter=600).fit(X0, y).predict_proba(X0)[:, 1])
    a1 = roc_auc_score(y, LogisticRegression(max_iter=600).fit(X1, y).predict_proba(X1)[:, 1])
    print(f"[3] AUC[y~dist+atr]={a0:.3f} vs +absorp={a1:.3f}  Δ={a1-a0:+.3f}")

    print("[4] по годам AUC(absorp_signal):")
    yr_ok = 0; yr_tot = 0
    for yr, g in df.groupby("year"):
        if len(g) < 30 or g.y.nunique() < 2:
            continue
        a = roc_auc_score(g.y.values, g.absorp_signal.values); yr_tot += 1; yr_ok += int(a > 0.5)
        print(f"   {yr}: n={len(g):>4} AUC={a:.3f}")
    keep = (p2 < 0.05) and (a1 - a0 > 0.005) and (yr_tot and yr_ok / yr_tot >= 0.6)
    print(f"\nВЕРДИКТ: {'SCORE IT (пережил null+инкремент+год)' if keep else 'DESCRIPTIVE-ONLY (не бьёт конфаунд) — как и всё остальное'}")


if __name__ == "__main__":
    main()
