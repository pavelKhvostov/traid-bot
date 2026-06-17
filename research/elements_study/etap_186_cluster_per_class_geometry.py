"""etap_186: кластеризация сигналов → СВОЯ геометрия (SL/TP) каждому классу.

Идея пользователя: не предсказывать исход (он непредсказуем — etap 178-185), а
поделить сигналы на КЛАССЫ и подобрать каждому классу правильный стоп/тейк/вход.
Нейронка «плавает в сигналах как рыба» = ориентируется в пространстве сигналов.

Это методология [[López de Prado]] §3-4: distance metrics → optimal clustering
(unsupervised) → per-class решение. Грид геометрии (etap_179) уже доказал: геометрия =
огромный рычаг (−80R…+74R), разным условиям нужна разная оснастка.

Пул = Bulkowski-паттерны (etap_172), BTC+ETH+SOL, 12h. Фичи кластеризации = ТОЛЬКО
пред-входной контекст (как etap_178) + identity/height/side. Без исхода.

Процедура (честно, без подглядывания в OOS):
  1. StandardScaler + KMeans на TRAIN-фичах. K выбираем по silhouette на TRAIN.
  2. Для каждого кластера на TRAIN перебираем SL×TP-грид (etap_179) → лучшая по
     net_R геометрия класса. ЗАМОРАЖИВАЕМ.
  3. На TEST: присваиваем кластер (scaler+kmeans с TRAIN), применяем геометрию класса,
     суммируем net_R.
  Сравнение: per-class геометрия vs ЛУЧШАЯ ЕДИНАЯ глобальная (выбрана на TRAIN) —
  бьёт ли «каждому классу своё» одну-на-всех на OOS, и стабильно ли по годам.

Вход = breakout (канон); per-class entry — следующий шаг.
Multiple testing: K×28 геометрий — per-class выбор имеет свободу, поэтому baseline =
ТОЖЕ train-optimal (глобальный), и требуем OOS-улучшение + year-стабильность.

Output: output/etap_186_clusters.csv
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
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from data_manager import load_df, compose_from_base
from etap_172_bulkowski_patterns import DETECTORS, LOOKBACK, SWING_N
from etap_175_metalabel_dataset import wilder_atr, build_features, detect_failed_sweep, confirmed_swings_last
from etap_179_geometry_grid import sl_price, tp_price, simulate, SL_RULES, TP_RULES, TIMEOUT_12H

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
OUT = _ROOT / 'research' / 'elements_study' / 'output'

PAT_ID = {p: i for i, p in enumerate(sorted(
    ['big_w', 'big_m', 'db_eve_eve', 'hs_top', 'hs_bottom', 'triple_top', 'v_bottom',
     'v_top', 'rounding_bottom', 'cup_handle', 'barr_top', 'barr_bottom', 'diamond_top']))}

FEAT_KEYS = ['close_pos_in_range', 'body_pct', 'upper_wick_pct', 'lower_wick_pct',
             'range_vs_atr', 'atr_pct', 'vol_z20', 'ema200_dist_pct', 'ema50_slope_pct',
             'pre_3d_ret_pct', 'pre_7d_ret_pct', 'usdtd_1d_ret_pct', 'hour_utc', 'dow']


def collect(sym, usdtd, store):
    df1 = load_df(sym, "1h")
    df1 = df1[(df1.index >= START_DATE) & (df1.index <= END_DATE)].copy()
    df12 = compose_from_base(df1, "12h")
    df12 = df12[(df12.index >= START_DATE) & (df12.index <= END_DATE)].copy().reset_index()
    if 'time' not in df12.columns:
        df12 = df12.rename(columns={df12.columns[0]: 'time'})
    o, h, l, c, atr, F, n = build_features(df12, usdtd)
    times = df12['time']
    h1 = df1['high'].values.astype(float); l1 = df1['low'].values.astype(float)
    c1 = df1['close'].values.astype(float)
    t1_ns = df1.index.values.astype('datetime64[ns]').astype(np.int64)
    store[sym] = (h1, l1, c1)

    rows = []
    for i in range(LOOKBACK + SWING_N + 2, n - SWING_N):
        if atr[i] <= 0:
            continue
        fired = [det(df12, i) for det in DETECTORS]
        fired = [s for s in fired if s is not None]
        if not fired:
            continue
        fs_l, fs_s, fsf = detect_failed_sweep(h, l, c, i)
        sh, sl_sw = confirmed_swings_last(h, l, i, LOOKBACK, SWING_N)
        dist_hi = (sh[1] - c[i]) / c[i] * 100 if sh else 0.0
        dist_lo = (c[i] - sl_sw[1]) / c[i] * 100 if sl_sw else 0.0
        t_close_ns = (times.iloc[i] + pd.Timedelta(hours=12)).value
        start = int(np.searchsorted(t1_ns, t_close_ns, side='left'))
        if start >= len(c1):
            continue
        end = min(start + TIMEOUT_12H * 12, len(c1))
        feat_base = [F[k][i] for k in FEAT_KEYS] + [dist_hi, dist_lo,
                     fsf.get('swept_ssl', 0), fsf.get('swept_bsl', 0),
                     fsf.get('failed_ssl', 0), fsf.get('failed_bsl', 0)]
        for sig in fired:
            side = sig['side']
            rows.append({
                'symbol': sym, 'time': times.iloc[i], 'side': side,
                'entry': sig['breakout_price'], 'breakout': sig['breakout_price'],
                'struct': sig['low_price'] if side == 'long' else sig['high_price'],
                'height_pct': sig['height_pct'], 'atr': atr[i],
                'pattern': sig['pattern'], '_start': start, '_end': end,
                'period': 'test' if times.iloc[i] >= TRAIN_END else 'train',
                'feat': feat_base + [sig['height_pct'], sig.get('duration_bars', 0),
                                     1.0 if side == 'long' else 0.0, PAT_ID[sig['pattern']]],
            })
    return rows


def net_for_geometry(cand, sl_rule, tp_rule, store):
    side = cand['side']; entry = cand['entry']
    sl = sl_price(sl_rule, side, entry, cand['struct'], cand['atr'])
    tp = tp_price(tp_rule, side, entry, sl, cand['breakout'], cand['height_pct'])
    h1, l1, c1 = store[cand['symbol']]
    r = simulate(side, entry, sl, tp, h1, l1, c1, cand['_start'], cand['_end'])
    return r['net_R'] if r else None


def best_geometry(cands, store):
    """Лучшая (sl,tp) по сумме net_R на наборе cands."""
    best = None; best_sum = -1e9
    for slr in SL_RULES:
        for tpr in TP_RULES:
            s = 0.0; cnt = 0
            for cd in cands:
                v = net_for_geometry(cd, slr, tpr, store)
                if v is not None:
                    s += v; cnt += 1
            if cnt and s > best_sum:
                best_sum = s; best = (slr, tpr)
    return best, best_sum


def main():
    t0 = time.time()
    print("=" * 82)
    print("etap_186: кластеры сигналов → своя SL/TP геометрия классу · Bulkowski · 4y/2y")
    print("=" * 82)
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    ud_ret = ud['close'].pct_change().fillna(0) * 100
    udby = {pd.Timestamp(d).normalize(): r for d, r in zip(ud['datetime'], ud_ret.values)}

    store = {}
    cands = []
    for sym in SYMBOLS:
        r = collect(sym, udby, store)
        cands.extend(r)
        print(f"  [{sym}] сигналов: {len(r)}")
    print(f"  ВСЕГО: {len(cands)}")

    X = np.array([cd['feat'] for cd in cands], dtype=float)
    X = np.nan_to_num(X)
    is_tr = np.array([cd['period'] == 'train' for cd in cands])
    tr_idx = np.where(is_tr)[0]; te_idx = np.where(~is_tr)[0]

    scaler = StandardScaler().fit(X[tr_idx])
    Xs = scaler.transform(X)

    # 1) выбор K по silhouette на TRAIN
    print("\n1) выбор K по silhouette (TRAIN):")
    bestK, bestSil = None, -1
    for K in [3, 4, 5, 6]:
        km = KMeans(n_clusters=K, n_init=10, random_state=0).fit(Xs[tr_idx])
        sil = silhouette_score(Xs[tr_idx], km.labels_)
        print(f"   K={K}: silhouette={sil:.3f}")
        if sil > bestSil:
            bestSil = sil; bestK = K
    print(f"   → выбран K={bestK}")

    km = KMeans(n_clusters=bestK, n_init=10, random_state=0).fit(Xs[tr_idx])
    lab_all = km.predict(Xs)
    for cd, lb in zip(cands, lab_all):
        cd['cluster'] = int(lb)

    tr_c = [cands[i] for i in tr_idx]; te_c = [cands[i] for i in te_idx]

    # baseline: ЛУЧШАЯ ЕДИНАЯ глобальная геометрия на TRAIN, применённая к TEST
    g_glob, _ = best_geometry(tr_c, store)
    glob_test = sum(v for cd in te_c if (v := net_for_geometry(cd, g_glob[0], g_glob[1], store)) is not None)
    print(f"\n2) BASELINE (одна геометрия на всех, train-optimal={g_glob}):")
    print(f"   TEST ΣnetR = {glob_test:+.1f}  (n={len(te_c)})")

    # per-class: лучшая геометрия класса на TRAIN → применяем к TEST
    print(f"\n3) PER-CLASS геометрия (train-optimal на класс) → OOS:")
    print(f"   {'cl':>3} {'n_tr':>5}{'n_te':>5}  {'geom(SL×TP)':>16}  {'trΣR':>7}  {'teΣR':>7}  {'te_base':>7}")
    per_class_test = 0.0; rows_out = []
    for cl in range(bestK):
        ctr = [cd for cd in tr_c if cd['cluster'] == cl]
        cte = [cd for cd in te_c if cd['cluster'] == cl]
        if len(ctr) < 20:
            # слишком мал класс — на нём же используем глобальную геометрию
            g = g_glob
        else:
            g, _ = best_geometry(ctr, store)
        tr_sum = sum(v for cd in ctr if (v := net_for_geometry(cd, g[0], g[1], store)) is not None)
        te_sum = sum(v for cd in cte if (v := net_for_geometry(cd, g[0], g[1], store)) is not None)
        te_base = sum(v for cd in cte if (v := net_for_geometry(cd, g_glob[0], g_glob[1], store)) is not None)
        per_class_test += te_sum
        # доминирующие паттерны класса
        from collections import Counter
        toppat = ', '.join(f"{p}:{n}" for p, n in Counter(cd['pattern'] for cd in ctr).most_common(3))
        print(f"   {cl:>3} {len(ctr):>5}{len(cte):>5}  {g[0]+'×'+g[1]:>16}  {tr_sum:>+7.1f}  {te_sum:>+7.1f}  {te_base:>+7.1f}")
        rows_out.append({'cluster': cl, 'n_tr': len(ctr), 'n_te': len(cte),
                         'geom': f"{g[0]}x{g[1]}", 'tr_sumR': round(tr_sum, 1),
                         'te_sumR': round(te_sum, 1), 'te_base_sumR': round(te_base, 1),
                         'top_patterns': toppat})
    pd.DataFrame(rows_out).to_csv(OUT / 'etap_186_clusters.csv', index=False)

    print(f"\n   PER-CLASS TEST ΣnetR = {per_class_test:+.1f}   vs   BASELINE {glob_test:+.1f}   "
          f"Δ={per_class_test-glob_test:+.1f}")

    # per-year (OOS): per-class vs baseline
    print("\n4) PER-YEAR (OOS): per-class vs baseline ΣnetR:")
    geom_by_cluster = {r['cluster']: tuple(r['geom'].split('x')) for r in rows_out}
    yr_pc = {}; yr_bs = {}
    for cd in te_c:
        g = geom_by_cluster[cd['cluster']]
        vpc = net_for_geometry(cd, g[0], g[1], store)
        vbs = net_for_geometry(cd, g_glob[0], g_glob[1], store)
        y = cd['time'].year
        if vpc is not None:
            yr_pc[y] = yr_pc.get(y, 0.0) + vpc
        if vbs is not None:
            yr_bs[y] = yr_bs.get(y, 0.0) + vbs
    for y in sorted(yr_pc):
        print(f"   {y}: per-class {yr_pc[y]:+6.1f}  baseline {yr_bs.get(y,0):+6.1f}  Δ={yr_pc[y]-yr_bs.get(y,0):+6.1f}")
    bad_pc = sum(1 for v in yr_pc.values() if v < 0)

    print("\n" + "=" * 82)
    if per_class_test > glob_test + 0.1 * abs(glob_test) and bad_pc == 0:
        print(f"РАБОТАЕТ: per-class геометрия бьёт единую на OOS (Δ={per_class_test-glob_test:+.1f}), 0 плохих лет.")
        print("  Кластеризация сигналов + своя оснастка классу даёт edge. Следующий шаг: per-class entry, валидация K.")
    else:
        print(f"СЛАБО: per-class Δ={per_class_test-glob_test:+.1f} над baseline, bad years {bad_pc}.")
        print("  Кластерная оснастка не бьёт единую устойчиво — train-optimal геометрия класса")
        print("  не переносится на OOS (режимная нестабильность геометрии, ср. etap_179).")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
