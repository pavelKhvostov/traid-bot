"""zone_reactor.explain — ответ ЯЗЫКОМ ТРЕЙДЕРА: причина реакции / отсутствия реакции.

Поверх валидированной zone-touch модели (GBM, OOS AUC 0.73). Для каждой зоны:
  • per-feature атрибуция (occlusion: ΔP, если фичу заменить на медиану train) — какие
    факторы толкнули вероятность реакции ВВЕРХ (за реакцию) и ВНИЗ (против);
  • перевод факторов во фразы трейдера (ICT/моментум/премиум-дискаунт/свежесть);
  • вывод: «РЕАКЦИЯ ожидается, потому что …» / «реакции НЕТ, потому что …».
Плюс агрегат: типичные причины реакции vs отсутствия (общий ответ трейдеру).

Самокоррекция: модель уже учится на трудных примерах (focal+hard-mining в model.py);
здесь — само-ОБЪЯСНЕНИЕ + разбор ошибок (FP/FN) языком трейдера = «почему я ошиблась».
"""
from __future__ import annotations
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

OUT = _ROOT / 'research' / 'zone_reactor'
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
FEAT = ['tf_w', 'is_ob', 'conf_count', 'conf_strength', 'in_htf', 'n_tf_aligned', 'disp_body',
        'age_h', 'pos_in_range', 'zone_width_pct', 'side_long', 'atr_pct', 'vol_z', 'rsi14',
        'ema200_dist', 'hull_dir', 'htf_1d_dir', 'htf_3d_dir']


def phrase(feat, val, contrib, long):
    """Фраза трейдера для фичи по её значению и вкладу (contrib>0 = за реакцию)."""
    pos = contrib > 0
    if feat in ('conf_strength', 'conf_count', 'n_tf_aligned'):
        return ("сильное multi-TF подтверждение зоны" if pos else "слабое multi-TF подтверждение") if abs(contrib) > 0.01 else None
    if feat == 'in_htf':
        return ("зона подтверждена HTF (1d/3d)" if val > 0.5 else "нет HTF-зоны рядом") if pos else None
    if feat == 'pos_in_range':
        if long:
            return "глубокий discount (зона спроса внизу диапазона)" if val < 0.4 else ("premium — покупка дорого" if val > 0.6 else None)
        return "premium (зона предложения вверху диапазона)" if val > 0.6 else ("discount — продажа дёшево" if val < 0.4 else None)
    if feat == 'age_h':
        return "свежая, нетронутая зона" if val < 100 else "старая/многократно тронутая зона"
    if feat == 'disp_body':
        return "сильный импульс создал зону (displacement)" if val > 0.6 else "вялое тело — слабая зона"
    if feat == 'zone_width_pct':
        return "широкая зона (запас до пробоя)" if val > 2 else "узкая/тонкая зона"
    if feat == 'rsi14':
        if long:
            return "RSI перепродан — разворот вверх" if val < 35 else ("RSI перекуплен" if val > 65 else None)
        return "RSI перекуплен — разворот вниз" if val > 65 else ("RSI перепродан" if val < 35 else None)
    if feat == 'atr_pct':
        return "высокая волатильность — 5% ход вероятен" if val > 4 else "низкая волатильность — 5% далеко"
    if feat == 'ema200_dist':
        return ("растянуто от EMA200" if abs(val) > 8 else None)
    if feat in ('hull_dir', 'htf_1d_dir', 'htf_3d_dir'):
        aligned = (val > 0) == long
        return ("HTF-тренд в сторону зоны" if aligned else "против HTF-тренда") if abs(contrib) > 0.01 else None
    if feat == 'is_ob':
        return ("order block" if val > 0.5 else "FVG-зона") if abs(contrib) > 0.015 else None
    if feat == 'vol_z':
        return "всплеск объёма на касании" if val > 1 else None
    return None


def occlusion(clf, X, med):
    """ΔP по каждой фиче (значение → медиана train). Возвращает матрицу contrib [n, d]."""
    p0 = clf.predict_proba(X)[:, 1]
    contrib = np.zeros_like(X)
    for j in range(X.shape[1]):
        Xj = X.copy(); Xj[:, j] = med[j]
        contrib[:, j] = p0 - clf.predict_proba(Xj)[:, 1]
    return p0, contrib


def explain_row(feats_raw, contrib, long, top=4):
    order = np.argsort(-np.abs(contrib))
    pro, con = [], []
    for j in order:
        ph = phrase(FEAT[j], feats_raw[FEAT[j]], contrib[j], long)
        if ph is None:
            continue
        (pro if contrib[j] > 0 else con).append(ph)
        if len(pro) + len(con) >= top + 2:
            break
    return pro[:top], con[:3]


def main():
    df = pd.read_csv(OUT / 'zone_touch_dataset.csv'); df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True); df[FEAT] = df[FEAT].fillna(0)
    df = df[df.zone_width_pct <= 3.0].reset_index(drop=True)   # только РЕАЛИСТИЧНЫЕ зоны (валид. конфиг)
    print(f"[реалистичные зоны ≤3% ширины: {len(df)}]")
    is_tr = (df['time'] < TRAIN_END).values
    Xtr = df.loc[is_tr, FEAT].values; ytr = df.loc[is_tr, 'held'].values
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(Xtr, ytr)
    med = np.median(Xtr, axis=0)
    te = df.loc[~is_tr].reset_index(drop=True)
    Xte = te[FEAT].values
    p, contrib = occlusion(clf, Xte, med)
    te['p'] = p
    print(f"zone_reactor EXPLAIN · OOS AUC={roc_auc_score(te['held'], p):.3f}")

    print("\n" + "=" * 78)
    print("ПРИМЕРЫ — ответ языком трейдера (реальные зоны OOS):")
    print("=" * 78)
    # сильные (P высокий, реакция была) и слабые (P низкий, реакции не было)
    strong = te[(te.p >= 0.65)].sort_values('p', ascending=False).head(3)
    weak = te[(te.p <= 0.30)].sort_values('p').head(3)
    for _, r in pd.concat([strong, weak]).iterrows():
        i = r.name; long = r['side_long'] == 1
        pro, con = explain_row(te.loc[i, FEAT], contrib[i], long)
        verdict = "СИЛЬНАЯ → жду реакцию ≥5%" if r['p'] >= 0.5 else "СЛАБАЯ → реакции не жду"
        fact = "(факт: реакция была ✓)" if r['held'] == 1 else "(факт: пробой, реакции нет ✗)"
        print(f"\n{r['symbol']} {r['time'].strftime('%Y-%m-%d')} "
              f"{'LONG demand' if long else 'SHORT supply'}-зона · P={r['p']:.2f} → {verdict} {fact}")
        if pro:
            print(f"   ✅ ЗА реакцию: {'; '.join(pro)}")
        if con:
            print(f"   ⛔ против:    {'; '.join(con)}")

    # АГРЕГАТ: типичные причины реакции vs отсутствия (общий ответ)
    print("\n" + "=" * 78)
    print("ОБЩИЙ ОТВЕТ — что РАЗЛИЧАЕТ сильные зоны (реакция) от слабых (пробой):")
    print("=" * 78)
    held = te[te.held == 1]; broke = te[te.held == 0]
    diffs = []
    for f in FEAT:
        d = (held[f].mean() - broke[f].mean()) / (te[f].std() + 1e-9)
        diffs.append((f, d, held[f].mean(), broke[f].mean()))
    for f, d, hm, bm in sorted(diffs, key=lambda x: -abs(x[1]))[:8]:
        sign = "выше у реакции" if d > 0 else "ниже у реакции"
        print(f"   {f:>16}: реакция={hm:+.2f} / пробой={bm:+.2f}  ({sign}, норм.Δ {d:+.2f})")
    print("\nЧитается так: реакция вероятнее, когда зона ШИРЕ (запас до пробоя), at HTF-TF,")
    print("в discount, RSI в крайности, высокая волатильность; пробой — когда узкая зона,")
    print("в premium, без HTF-подтверждения. multi-TF confluence сам по себе слабо влияет.")


if __name__ == '__main__':
    main()
