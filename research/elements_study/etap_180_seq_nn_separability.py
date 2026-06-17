"""etap_180: ЧЕСТНЫЙ тест разделимости good/bad нейросетью (MLP на сырых окнах).

Задача нейро-модуля (формулировка пользователя): разделить сигналы на удачные/
неудачные, обучить сеть искать закономерности, отсеять неудачные — оставить удачные.

Что было (175-178): GBM на 28 рукодельных фичах. Итог: TRAIN resub AUC 0.99,
TRAIN 5-fold CV 0.573, TEST(OOS) 0.517 — переобучение без переносимого сигнала.

Что НЕ пробовали и пробуем здесь — три исправления, чтобы дать сети честный шанс:
  1. Сеть видит СЫРОЕ окно свечей (форму), а не рукодельные агрегаты.
     Фичи на бар окна: (o,h,l,c - entry)/ATR + log(vol/vol_mean20).  K=8 баров 12h.
     Опционально + те же 28 контекст-фич (combo).
  2. Лейбл GEOMETRY-NEUTRAL: симметричный first-touch ±TARGET%.
     удачный(1) = цена прошла +TARGET% в сторону сигнала РАНЬШЕ, чем -TARGET% против.
     Base rate ~50% → честный вопрос «разделимы ли классы», без geometry-bias.
     timeout → сэмпл выбрасывается (неопределён), не засоряет.
  3. PURGED + EMBARGO CV: горизонт лейбла перекрывает соседей → обычный KFold течёт
     (AFML гл.7). Чистим train-сэмплы, чьё окно исхода пересекает val-блок + embargo.

Модель = MLPClassifier (нейросеть, есть в sklearn; torch/TCN — эскалация, если
здесь мелькнёт OOS-сигнал). Per-asset И pooled. Сравнение фич: raw / context / combo.

ВЕРДИКТ-критерий: если purged-CV AUC ≈ OOS AUC ≈ 0.5 во всех режимах — классы
неразделимы предобученными фичами, вопрос закрыт. Если OOS AUC заметно > 0.55 —
есть на чём строить, эскалируем в TCN.

Output: output/etap_180_separability.csv
"""
from __future__ import annotations
import sys
import time
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score

from data_manager import load_df, compose_from_base
from etap_172_bulkowski_patterns import DETECTORS, LOOKBACK, SWING_N
from etap_175_metalabel_dataset import wilder_atr, build_features

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OUT = _ROOT / 'research' / 'elements_study' / 'output'

WIN_K = 8                 # длина окна свечей (12h) на вход сети
TARGET_PCT = 5.0          # симметричный first-touch ±5%
TIMEOUT_12H = 60          # 30 дней; не достиг ни +5% ни -5% → выброс
HORIZON_BARS = TIMEOUT_12H  # для purge (в 12h-барах)
EMBARGO = 5               # embargo-зазор (12h-баров) вокруг val-блока

CTX_FEATS = ['close_pos_in_range', 'body_pct', 'upper_wick_pct', 'lower_wick_pct',
             'range_vs_atr', 'atr_pct', 'vol_z20', 'ema200_dist_pct', 'ema50_slope_pct',
             'pre_3d_ret_pct', 'pre_7d_ret_pct', 'usdtd_1d_ret_pct', 'hour_utc', 'dow']


def label_symmetric(side, entry, h1, l1, start, end):
    """1 = +TARGET% в сторону сигнала раньше -TARGET% против. None = timeout."""
    if side == 'long':
        tp = entry * (1 + TARGET_PCT / 100); sl = entry * (1 - TARGET_PCT / 100)
    else:
        tp = entry * (1 - TARGET_PCT / 100); sl = entry * (1 + TARGET_PCT / 100)
    for k in range(start, end):
        hi = h1[k]; lo = l1[k]
        if side == 'long':
            hit_tp = hi >= tp; hit_sl = lo <= sl
        else:
            hit_tp = lo <= tp; hit_sl = hi >= sl
        if hit_sl and hit_tp:
            return 0          # оба в одной свече → против (консерв.)
        if hit_sl:
            return 0
        if hit_tp:
            return 1
    return None               # timeout → неопределён, выброс


def collect(sym, usdtd):
    df1 = load_df(sym, "1h")
    df1 = df1[(df1.index >= START_DATE) & (df1.index <= END_DATE)].copy()
    df12 = compose_from_base(df1, "12h")
    df12 = df12[(df12.index >= START_DATE) & (df12.index <= END_DATE)].copy().reset_index()
    if 'time' not in df12.columns:
        df12 = df12.rename(columns={df12.columns[0]: 'time'})
    o, h, l, c, atr, F, n = build_features(df12, usdtd)
    v = df12['volume'].values.astype(float)
    vmean = pd.Series(v).rolling(20).mean().values
    times = df12['time']
    h1 = df1['high'].values.astype(float); l1 = df1['low'].values.astype(float)
    c1 = df1['close'].values.astype(float)
    t1_ns = df1.index.values.astype('datetime64[ns]').astype(np.int64)

    rows = []
    for i in range(max(LOOKBACK + SWING_N + 2, WIN_K), n - SWING_N):
        if atr[i] <= 0:
            continue
        sides = set()
        for det in DETECTORS:
            sig = det(df12, i)
            if sig is not None:
                sides.add(sig['side'])
        if not sides:
            continue
        # сырое окно [i-K+1 .. i], нормировано к entry=c[i] и atr[i]
        a = atr[i]; e = c[i]
        sl_ = slice(i - WIN_K + 1, i + 1)
        win = np.concatenate([
            (o[sl_] - e) / a, (h[sl_] - e) / a, (l[sl_] - e) / a, (c[sl_] - e) / a,
            np.log(np.maximum(v[sl_], 1e-9) / np.maximum(vmean[sl_], 1e-9)),
        ])
        ctx = np.array([F[k][i] for k in CTX_FEATS], dtype=float)
        t_close_ns = (times.iloc[i] + pd.Timedelta(hours=12)).value
        start = int(np.searchsorted(t1_ns, t_close_ns, side='left'))
        if start >= len(c1):
            continue
        end = min(start + TIMEOUT_12H * 12, len(c1))
        for side in sides:
            y = label_symmetric(side, e, h1, l1, start, end)
            if y is None:
                continue
            s = 1.0 if side == 'long' else -1.0
            rows.append({'symbol': sym, 'time': times.iloc[i], 'bar': i, 'side_long': s,
                         'y': y, 'win': win * s, 'ctx': np.append(ctx, s)})
    return rows


def purged_cv_auc(X, y, bar, n_splits=5):
    """Blocked time-CV с purge+embargo по горизонту лейбла. Возвращает mean OOF AUC."""
    order = np.argsort(bar)
    folds = np.array_split(order, n_splits)
    aucs = []
    for f in folds:
        vb_lo, vb_hi = bar[f].min(), bar[f].max()
        # purge: убрать train, чьё окно исхода [bar, bar+H] пересекает val-блок ± embargo
        keep = np.ones(len(y), bool); keep[f] = False
        overlap = (bar + HORIZON_BARS >= vb_lo - EMBARGO) & (bar <= vb_hi + EMBARGO)
        keep &= ~overlap
        if keep.sum() < 100 or y[f].sum() < 3 or (1 - y[f]).sum() < 3:
            continue
        clf = make_pipeline(StandardScaler(),
            MLPClassifier(hidden_layer_sizes=(64, 32), alpha=3e-3, max_iter=300,
                          early_stopping=True, n_iter_no_change=15, random_state=0))
        clf.fit(X[keep], y[keep])
        p = clf.predict_proba(X[f])[:, 1]
        aucs.append(roc_auc_score(y[f], p))
    return (np.mean(aucs), np.std(aucs), len(aucs)) if aucs else (np.nan, np.nan, 0)


def eval_block(name, df, feat_key):
    X = np.vstack(df[feat_key].values)
    y = df['y'].values.astype(int)
    bar = df['bar'].values
    is_tr = (df['time'] < TRAIN_END).values
    Xtr, ytr, btr = X[is_tr], y[is_tr], bar[is_tr]
    Xte, yte = X[~is_tr], y[~is_tr]
    cv_m, cv_s, k = purged_cv_auc(Xtr, ytr, btr)
    # финальная модель на всём train → строгий OOS
    oos = np.nan; resub = np.nan
    if len(np.unique(ytr)) == 2 and len(np.unique(yte)) == 2:
        clf = make_pipeline(StandardScaler(),
            MLPClassifier(hidden_layer_sizes=(64, 32), alpha=3e-3, max_iter=400,
                          early_stopping=True, n_iter_no_change=15, random_state=42))
        clf.fit(Xtr, ytr)
        resub = roc_auc_score(ytr, clf.predict_proba(Xtr)[:, 1])
        oos = roc_auc_score(yte, clf.predict_proba(Xte)[:, 1])
    return {'scope': name, 'feat': feat_key, 'n_train': len(Xtr), 'n_test': len(Xte),
            'base_tr': round(ytr.mean(), 3), 'base_te': round(yte.mean(), 3) if len(yte) else np.nan,
            'resub_AUC': round(resub, 3), 'purgedCV_AUC': round(cv_m, 3),
            'cv_std': round(cv_s, 3), 'cv_folds': k, 'OOS_AUC': round(oos, 3)}


def main():
    t0 = time.time()
    print("=" * 80)
    print("etap_180: разделимость good/bad нейросетью (MLP) · raw-окна · purged-CV + OOS")
    print("=" * 80)
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    ud_ret = ud['close'].pct_change().fillna(0) * 100
    udby = {pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], ud_ret.values)}

    allrows = []
    for sym in SYMBOLS:
        r = collect(sym, udby)
        allrows.extend(r)
        sub = pd.DataFrame(r)
        print(f"  [{sym}] сэмплов (не-timeout): {len(r)}  base success%={sub['y'].mean()*100:.1f}")
    df = pd.DataFrame(allrows).sort_values('time').reset_index(drop=True)
    df['win_ctx'] = [np.concatenate([w, c]) for w, c in zip(df['win'], df['ctx'])]

    print(f"\nВСЕГО сэмплов: {len(df)}  base success%={df['y'].mean()*100:.1f}  "
          f"(timeout-сэмплы выброшены)")
    print("\nAUC: 0.5 = монетка. Сигнал есть, только если purgedCV И OOS > ~0.55.")
    print(f"{'scope':>8} {'feat':>8}  {'ntr':>5}{'nte':>5}  {'b_tr':>5}{'b_te':>5}  "
          f"{'resub':>6}{'pCV':>7}{'±':>6}{'fld':>4}  {'OOS':>6}")

    results = []
    blocks = [('pooled', df)] + [(s, df[df.symbol == s]) for s in SYMBOLS]
    for name, d in blocks:
        for fk in ['win', 'ctx', 'win_ctx']:
            if len(d) < 200:
                continue
            r = eval_block(name, d, fk)
            results.append(r)
            print(f"{r['scope']:>8} {r['feat']:>8}  {r['n_train']:>5}{r['n_test']:>5}  "
                  f"{r['base_tr']:>5.2f}{r['base_te']:>5.2f}  {r['resub_AUC']:>6.3f}"
                  f"{r['purgedCV_AUC']:>7.3f}{r['cv_std']:>6.3f}{r['cv_folds']:>4}  "
                  f"{r['OOS_AUC']:>6.3f}")
    pd.DataFrame(results).to_csv(OUT / 'etap_180_separability.csv', index=False)

    best = max((r for r in results if not np.isnan(r['OOS_AUC'])),
               key=lambda r: r['OOS_AUC'], default=None)
    print("\n" + "=" * 80)
    if best and best['OOS_AUC'] > 0.55 and best['purgedCV_AUC'] > 0.55:
        print(f"СИГНАЛ: {best['scope']}/{best['feat']} OOS_AUC={best['OOS_AUC']} "
              f"pCV={best['purgedCV_AUC']} → стоит эскалировать в TCN (torch).")
    else:
        bo = best['OOS_AUC'] if best else float('nan')
        print(f"ВЕРДИКТ: лучший OOS_AUC={bo} — классы НЕ разделяются "
              f"ни сырыми окнами, ни контекстом, ни их комбо, на честном OOS.")
        print("  → потолок не в модели/фичах. Сигнал good/bad на этом пуле кандидатов")
        print("    не извлекаем (PnL = режимная бета, etap_179). Редирект Stage A.")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
