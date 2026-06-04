"""etap_169: Meta-Labeling по Lopez de Prado (Ch 3, 4, 7).

АРХИТЕКТУРА:
  Primary model = простое правило "failed sweep BSL → SHORT, failed sweep SSL → LONG"
                  (это уже наша главная фича в etap_167, importance ~0.3-0.4)
                  Mechanical rule, без training, без leakage, high recall, low precision.

  Secondary model (meta) = RandomForest, бинарный {0,1} "брать ли primary сигнал?"
                          Обучен на тех же 127 features etap_165 + side от primary.

  Labels = Triple-Barrier по Lopez:
    trgt = ATR(14) / close                     (volatility-adjusted threshold)
    pt = 2.0 * trgt  (TP в правильную сторону)
    sl = 1.0 * trgt  (SL против стороны)
    t1 = i + 14 баров (timeout)
    meta_label = 1 if pt hit first (in side direction) else 0

  Sample Weights:
    uniqueness × |Σ returns|  (Lopez Ch 4)

  CV:
    PurgedKFold(n_splits=5, embargo=14 баров)

OOS Test: 2025-01-01 → 2026-05-30 (как и раньше).
TRAIN: 2020-01-01 → 2024-12-31 (5-fold purged CV inside).
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

import time
import numpy as np
import pandas as pd

from data_manager import load_df, compose_from_base

SYMBOL = "BTCUSDT"
START = pd.Timestamp("2020-01-01", tz="UTC")
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
TEST_END = pd.Timestamp("2026-05-31", tz="UTC")
ATR_LEN = 14
PT_MULT = 2.0
SL_MULT = 1.0
T1_BARS = 14
EMBARGO = 14
SWEEP_LOOKBACK = 2   # 24h = 2 12h-баров


# ============================================================
# Helpers
# ============================================================

def atr(df, n=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


# ============================================================
# 1. Primary signal: failed sweep BSL/SSL
# ============================================================

def primary_failed_sweep(df_12h, lookback=2):
    """Failed sweep 24h primary signal.

    - sweep BSL (failed): свеча i пробила prev N-bar HIGH, но close < prev HIGH → false breakout up → SHORT
    - sweep SSL (failed): свеча i пробила prev N-bar LOW, но close > prev LOW → false breakdown → LONG
    - Если оба → 0 (ambivalent)
    - Если ни одного → 0 (no signal)

    Returns: pd.Series side ∈ {-1, 0, +1}
    """
    highs = df_12h['high'].values
    lows = df_12h['low'].values
    closes = df_12h['close'].values
    n = len(df_12h)
    side = np.zeros(n, dtype=int)

    for i in range(lookback + 2, n):
        prev_hi = max(highs[i-lookback:i])
        prev_lo = min(lows[i-lookback:i])
        bsl_swept = highs[i] > prev_hi
        ssl_swept = lows[i] < prev_lo
        bsl_failed = bsl_swept and (closes[i] < prev_hi)  # close обратно вернулся
        ssl_failed = ssl_swept and (closes[i] > prev_lo)
        if bsl_failed and ssl_failed:
            side[i] = 0  # both = ambivalent
        elif bsl_failed:
            side[i] = -1  # SHORT
        elif ssl_failed:
            side[i] = +1  # LONG
    return pd.Series(side, index=df_12h.index, name='primary_side')


# ============================================================
# 2. Triple-Barrier labeling
# ============================================================

def triple_barrier_labels(df_12h, side, atr_series, pt_mult=2.0, sl_mult=1.0, t1_bars=14):
    """Triple-Barrier по Lopez.

    Для каждой свечи где side != 0:
      entry = close(i)
      sl_dist = sl_mult * atr(i)
      pt_dist = pt_mult * atr(i)
      Если side=+1 (LONG): TP = entry + pt_dist; SL = entry - sl_dist
      Если side=-1 (SHORT): TP = entry - pt_dist; SL = entry + sl_dist
      Сканировать бары [i+1 ... i+t1_bars]:
        - Если intra-bar high/low касается TP → label=+1 (hit)
        - Если касается SL → label=-1
        - Если оба за одну свечу → label=-1 (worst case)
        - Если ни одного к t1 → label=0 (timeout, exit at close)

    Returns: DataFrame с колонками:
      entry_idx, side, entry_price, sl, pt, exit_idx, exit_price, exit_reason, bin_label, ret_pct
      meta_label = 1 if bin_label > 0 else 0
    """
    rows = []
    closes = df_12h['close'].values
    highs = df_12h['high'].values
    lows = df_12h['low'].values
    atrs = atr_series.values

    for i in range(len(df_12h)):
        s = side.iloc[i] if hasattr(side, 'iloc') else side[i]
        if s == 0 or i + t1_bars >= len(df_12h):
            continue
        if np.isnan(atrs[i]) or atrs[i] == 0:
            continue
        entry = float(closes[i])
        sl_d = sl_mult * atrs[i]
        pt_d = pt_mult * atrs[i]
        if s == 1:
            tp = entry + pt_d; sl = entry - sl_d
        else:
            tp = entry - pt_d; sl = entry + sl_d

        # Сканировать вперёд
        exit_idx = i + t1_bars  # default = timeout
        exit_price = closes[exit_idx]
        exit_reason = 'timeout'
        bin_label = 0

        for j in range(i+1, i+1+t1_bars):
            if j >= len(df_12h): break
            hit_tp = (highs[j] >= tp) if s == 1 else (lows[j] <= tp)
            hit_sl = (lows[j] <= sl) if s == 1 else (highs[j] >= sl)
            if hit_tp and hit_sl:
                # worst case: SL first
                exit_idx = j; exit_price = sl; exit_reason = 'sl_first'; bin_label = -1
                break
            elif hit_tp:
                exit_idx = j; exit_price = tp; exit_reason = 'tp_hit'; bin_label = 1
                break
            elif hit_sl:
                exit_idx = j; exit_price = sl; exit_reason = 'sl_hit'; bin_label = -1
                break

        if exit_reason == 'timeout':
            # Знак возврата
            ret = (exit_price - entry) / entry * (1 if s == 1 else -1)
            bin_label = 1 if ret > 0 else (0 if ret == 0 else -1)

        ret_pct = (exit_price - entry) / entry * (1 if s == 1 else -1) * 100
        meta_label = 1 if bin_label > 0 else 0

        rows.append({
            'entry_idx': i,
            'entry_time': df_12h.index[i],
            'exit_idx': exit_idx,
            'exit_time': df_12h.index[exit_idx],
            'side': int(s),
            'entry_price': entry,
            'sl': sl, 'tp': tp,
            'exit_price': float(exit_price),
            'exit_reason': exit_reason,
            'bin_label': bin_label,
            'meta_label': meta_label,
            'ret_pct': ret_pct,
            'atr_at_i': float(atrs[i]),
            'bars_held': exit_idx - i,
        })
    return pd.DataFrame(rows)


# ============================================================
# 3. Sample Weights (Lopez Ch 4)
# ============================================================

def sample_weights(events: pd.DataFrame, df_12h, returns: pd.Series):
    """uniqueness × |Σ returns| weights.

    events: DF с entry_idx, exit_idx (label horizon = [entry, exit])
    returns: pd.Series of bar returns (log)
    """
    # 1. Concurrency c_t = сколько label intervals "живых" в момент t
    n = len(df_12h)
    c_t = np.zeros(n)
    for _, r in events.iterrows():
        c_t[r['entry_idx']:r['exit_idx']+1] += 1
    c_t = np.where(c_t == 0, 1, c_t)  # avoid div by 0

    # 2. Uniqueness for each label
    uni = []
    for _, r in events.iterrows():
        seg = c_t[r['entry_idx']:r['exit_idx']+1]
        if len(seg) > 0:
            uni.append(np.mean(1 / seg))
        else:
            uni.append(0.0)

    # 3. Return attribution: w_i ∝ |Σ ret_t / c_t|
    ret_attr = []
    ret_arr = returns.values
    for _, r in events.iterrows():
        s = 0.0
        for t in range(r['entry_idx'], r['exit_idx']+1):
            if t < len(ret_arr) and not np.isnan(ret_arr[t]):
                s += ret_arr[t] / c_t[t]
        ret_attr.append(abs(s))

    # Combine: weight = uniqueness * return_attr_norm
    uni = np.array(uni)
    ret_attr = np.array(ret_attr)
    if ret_attr.sum() > 0:
        ret_attr = ret_attr / ret_attr.sum() * len(events)
    else:
        ret_attr = np.ones(len(events))
    if uni.sum() > 0:
        uni = uni / uni.sum() * len(events)
    else:
        uni = np.ones(len(events))
    w = uni * ret_attr
    if w.sum() > 0:
        w = w / w.sum() * len(events)
    return w


# ============================================================
# 4. Purged K-Fold CV (Lopez Ch 7)
# ============================================================

class PurgedKFold:
    """Purged K-Fold с embargo.

    Удаляет из train все samples где label interval [entry_idx, exit_idx]
    пересекается с test fold + embargo period после.
    """
    def __init__(self, n_splits=5, embargo=14):
        self.n_splits = n_splits
        self.embargo = embargo

    def split(self, events: pd.DataFrame):
        """events sorted by entry_idx."""
        n = len(events)
        indices = np.arange(n)
        fold_size = n // self.n_splits
        for k in range(self.n_splits):
            test_start = k * fold_size
            test_end = (k+1) * fold_size if k < self.n_splits - 1 else n
            test_idx = indices[test_start:test_end]

            test_entry_min = events.iloc[test_start]['entry_idx']
            test_exit_max = events.iloc[test_end-1]['exit_idx']

            # Purge: убрать из train любой sample чей label-интервал пересекает test
            train_mask = np.ones(n, dtype=bool)
            train_mask[test_start:test_end] = False
            for j in range(n):
                if test_start <= j < test_end: continue
                e_i = events.iloc[j]['entry_idx']
                e_o = events.iloc[j]['exit_idx']
                # Перекрытие?
                if not (e_o < test_entry_min or e_i > test_exit_max + self.embargo):
                    train_mask[j] = False
            train_idx = indices[train_mask]
            yield train_idx, test_idx


# ============================================================
# 5. Main
# ============================================================

def main():
    print("="*80)
    print("etap_169: META-LABELING (Lopez de Prado)")
    print("  Primary: failed sweep BSL/SSL rule (mechanical, no leakage)")
    print("  Secondary: RandomForest with triple-barrier labels + sample weights + Purged K-Fold")
    print("="*80)
    print()

    t0 = time.time()
    df_1h = load_df(SYMBOL, '1h')
    df_12h = compose_from_base(df_1h, '12h')
    df_12h = df_12h[(df_12h.index >= START) & (df_12h.index <= TEST_END)].copy()
    atr14 = atr(df_12h, ATR_LEN)
    print(f"Data: {len(df_12h)} 12h bars, {df_12h.index[0]} → {df_12h.index[-1]}")

    # 1. Primary signal
    side = primary_failed_sweep(df_12h, SWEEP_LOOKBACK)
    n_sigs = (side != 0).sum()
    print(f"\n1. Primary signals (failed sweep): {n_sigs} ({n_sigs/len(df_12h)*100:.1f}% of bars)")
    print(f"   LONG: {(side==1).sum()}  SHORT: {(side==-1).sum()}")

    # 2. Triple-Barrier labels
    events = triple_barrier_labels(df_12h, side, atr14, PT_MULT, SL_MULT, T1_BARS)
    print(f"\n2. Triple-barrier events: {len(events)}")
    print(f"   meta_label=1 (TP hit): {events['meta_label'].sum()} ({events['meta_label'].mean()*100:.1f}%)")
    print(f"   exit_reason breakdown:")
    print(events['exit_reason'].value_counts().to_string())
    print(f"   Avg ret_pct on hit: {events.loc[events['meta_label']==1, 'ret_pct'].mean():.2f}%")
    print(f"   Avg ret_pct on miss: {events.loc[events['meta_label']==0, 'ret_pct'].mean():.2f}%")

    # 3. Sample weights
    returns_log = np.log(df_12h['close'] / df_12h['close'].shift(1)).fillna(0)
    weights = sample_weights(events, df_12h, returns_log)
    print(f"\n3. Sample weights: mean={weights.mean():.3f}, min={weights.min():.3f}, max={weights.max():.3f}")

    # 4. Загрузим фичи из etap_165 (он строит датасет с 127 features)
    # Импорт build_dataset из etap_165
    print("\n4. Building features from etap_165...")
    from research.elements_study.etap_165_predict_pivot_enhanced import build_dataset
    df_1d = load_df(SYMBOL, '1d')
    df_4h = compose_from_base(df_1h, '4h')
    df_2h = compose_from_base(df_1h, '2h')
    df_1h_used = df_1h[(df_1h.index >= START) & (df_1h.index <= TEST_END)].copy()
    df_1d = df_1d[(df_1d.index >= START) & (df_1d.index <= TEST_END)].copy()
    df_4h = df_4h[(df_4h.index >= START) & (df_4h.index <= TEST_END)].copy()
    df_2h = df_2h[(df_2h.index >= START) & (df_2h.index <= TEST_END)].copy()
    df_usdtd = pd.read_csv('data/USDT_D_1d.csv', index_col=0, parse_dates=True)
    if df_usdtd.index.tz is None: df_usdtd.index = df_usdtd.index.tz_localize('UTC')

    ds = build_dataset(df_12h, df_1d, df_4h, df_2h, df_1h_used, df_usdtd)
    ds['time'] = pd.to_datetime(ds['time'], utc=True)
    ds = ds.set_index('time')
    print(f"   features dataset: {len(ds)} rows × {ds.shape[1]} cols")

    # Объединяем events с features
    events = events.merge(ds, left_on='entry_time', right_index=True, how='inner', suffixes=('', '_ds'))
    print(f"   events with features: {len(events)}")

    # Features for meta-model
    drop_cols = list(set(['entry_idx','entry_time','exit_idx','exit_time','side',
                           'entry_price','sl','tp','exit_price','exit_reason',
                           'bin_label','meta_label','ret_pct','atr_at_i','bars_held',
                           'close','high','low','is_low_fractal','is_high_fractal',
                           'move_after_low_pct','move_after_high_pct'] +
                           [c for c in events.columns if c.startswith('y_')]))
    feat_cols = [c for c in events.columns if c not in drop_cols and events[c].dtype in (np.float64, np.int64, np.float32, np.int32)]
    # Добавим side как фичу (это primary signal)
    if 'side' in events.columns:
        feat_cols = feat_cols + ['side']
    # dedup
    feat_cols = list(dict.fromkeys(feat_cols))
    print(f"   meta-model features: {len(feat_cols)}")

    # 5. Split: train events до 2025-01-01, test после
    events['is_test'] = events['entry_time'] >= TRAIN_END
    train_ev = events[~events['is_test']].sort_values('entry_idx').reset_index(drop=True)
    test_ev = events[events['is_test']].sort_values('entry_idx').reset_index(drop=True)
    weights_train = weights[~events['is_test'].values]
    print(f"\n5. TRAIN events: {len(train_ev)}  (meta+ rate {train_ev['meta_label'].mean()*100:.1f}%)")
    print(f"   TEST events:  {len(test_ev)}   (meta+ rate {test_ev['meta_label'].mean()*100:.1f}%)")

    X_train = train_ev[feat_cols].fillna(0).values
    y_train = train_ev['meta_label'].values
    X_test = test_ev[feat_cols].fillna(0).values
    y_test = test_ev['meta_label'].values

    # 6. Purged K-Fold CV for AUC estimation
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score

    print(f"\n6. Purged K-Fold CV on TRAIN (5-fold, embargo={EMBARGO} bars)...")
    pkf = PurgedKFold(n_splits=5, embargo=EMBARGO)
    fold_aucs = []
    for k, (tr_idx, te_idx) in enumerate(pkf.split(train_ev)):
        if len(te_idx) < 10 or len(tr_idx) < 50:
            print(f"   fold {k}: too few samples (tr={len(tr_idx)}, te={len(te_idx)}), skip")
            continue
        clf = RandomForestClassifier(
            n_estimators=500, max_features='sqrt',
            min_weight_fraction_leaf=0.05,
            class_weight='balanced_subsample',
            criterion='entropy', n_jobs=-1, random_state=42,
        )
        clf.fit(X_train[tr_idx], y_train[tr_idx], sample_weight=weights_train[tr_idx])
        p = clf.predict_proba(X_train[te_idx])[:, 1]
        try:
            auc = roc_auc_score(y_train[te_idx], p)
        except Exception:
            auc = float('nan')
        fold_aucs.append(auc)
        print(f"   fold {k}: train_n={len(tr_idx)}, test_n={len(te_idx)}, AUC={auc:.3f}")
    print(f"   CV AUC mean: {np.nanmean(fold_aucs):.3f}  std: {np.nanstd(fold_aucs):.3f}")

    # 7. Final fit на всём train, predict на TEST
    print(f"\n7. Final fit on full TRAIN, predict on TEST hold-out...")
    clf = RandomForestClassifier(
        n_estimators=1000, max_features='sqrt',
        min_weight_fraction_leaf=0.05,
        class_weight='balanced_subsample',
        criterion='entropy', n_jobs=-1, random_state=42,
    )
    clf.fit(X_train, y_train, sample_weight=weights_train)
    p_test = clf.predict_proba(X_test)[:, 1]
    auc_test = roc_auc_score(y_test, p_test)
    brier_test = brier_score_loss(y_test, p_test)
    ap_test = average_precision_score(y_test, p_test)
    print(f"   OOS AUC: {auc_test:.3f}  Brier: {brier_test:.3f}  AP: {ap_test:.3f}")

    # 8. Threshold sweep на TEST
    baseline = y_test.mean() * 100
    print(f"\n8. Threshold sweep on TEST (baseline meta+ rate = {baseline:.1f}%):")
    print(f"   {'thr':>5}  {'n_kept':>6}  {'kept%':>6}  {'precision%':>10}  {'lift':>5}  {'avg_ret%':>9}")
    for thr in [0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80]:
        keep = p_test >= thr
        n = keep.sum()
        if n == 0: continue
        tp = y_test[keep].sum()
        prec = tp / n * 100
        avg_ret = test_ev.loc[keep, 'ret_pct'].mean()
        lift = prec / baseline if baseline else 0
        print(f"   P≥{thr:<4} {n:>6}  {n/len(y_test)*100:>5.1f}%  {prec:>9.1f}%  {lift:>4.2f}x  {avg_ret:>+8.2f}%")

    # 9. Feature importance
    fi = sorted(zip(feat_cols, clf.feature_importances_), key=lambda x: -x[1])
    print(f"\n9. TOP-15 features:")
    for n, imp in fi[:15]:
        print(f"   {imp:.4f}  {n}")

    # 10. Save predictions
    out_dir = _ROOT / 'research' / 'elements_study' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)
    test_ev['p_meta'] = p_test
    test_ev[['entry_time','side','entry_price','sl','tp','exit_price','exit_reason',
             'meta_label','ret_pct','p_meta','bars_held']].to_csv(
        out_dir / 'etap_169_test_predictions.csv', index=False)
    print(f"\n10. Saved: {out_dir}/etap_169_test_predictions.csv")
    print(f"\nTotal time: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
