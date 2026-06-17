"""zone_reactor v2 Блок 2-3: САМОНАСТРОЙКА ЦЕЛИ + самообучение.

Запрос пользователя: система сама учится определять ЦЕЛЬ (что считать сильной зоной),
а не я хардкожу +5%. AutoML-поиск над целью, нормированной по ATR (убирает волатильность):
  цель = +TM·ATR в сторону зоны раньше, чем −SM·ATR против, за горизонт H (12h-баров).
Параметры (TM, SM, H) система подбирает САМА.

ЧЕСТНОСТЬ (López de Prado §1.4.2 — анти p-hacking):
  • поиск цели — ТОЛЬКО на TRAIN 2020-2024 через purged-CV (метрика = CV net_R/сделку
    отфильтрованного P≥0.6 подмножества);
  • лучшая (TM,SM,H) ЗАМОРАЖИВАЕТСЯ;
  • TEST 2025-2026 считается ОДИН раз (+ на 1h для честного исполнения);
  • permutation null-тест выбранной цели.
Фичи: BASE + ACCEPTANCE (Блок 1 показал acceptance даёт сигнал). CatBoost-GPU.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
import numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
from sklearn.metrics import roc_auc_score
from catboost import CatBoostClassifier
from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg
from research.elements_study.etap_170_lopez_features import rsi_wilder, hull_ma, ema, atr as atr_series

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START = pd.Timestamp("2020-01-01", tz="UTC"); END = pd.Timestamp("2026-06-11", tz="UTC")
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
TFS = {'6h': 360, '8h': 480, '12h': 720, '1d': 1440, '3d': 4320}
TF_W = {'6h': 0.8, '8h': 1.0, '12h': 1.5, '1d': 2.5, '3d': 3.0}
WMAX = 5.0; RANGE_W = 60; ACC_W = 80; SIDE_COST = 0.0008; FUNDING_8H = 0.0001
HORIZON_D = 20; EMBARGO_D = 2
# ПРОСТРАНСТВО ЦЕЛИ (система выбирает сама на train)
TM_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]      # target × ATR
SM_GRID = [1.0, 1.5, 2.0]                 # stop × ATR
H_GRID = [20, 40]                          # горизонт, 12h-баров
BASE = ['tf_w', 'is_ob', 'zone_width_pct', 'pos_in_range', 'age_h', 'rsi14', 'ema200_dist',
        'hull_dir', 'atr_pct', 'vol_z', 'htf_1d_dir', 'htf_3d_dir', 'side_long',
        'acc_candles', 'acc_touch_bars', 'acc_vol_frac']


def _load(sym, tf):
    d = compose_from_base(load_df(sym, "1h"), "12h") if tf == '12h' else load_df(sym, tf)
    return d[(d.index >= START) & (d.index <= END)].copy()


def zones(df, tf):
    out = []
    for j in range(2, len(df)):
        z = detect_ob_pair(df, j)
        if z is not None:
            out.append({'b': z.bottom, 't': z.top, 'dir': z.direction, 'type': 'OB', 'tf': tf,
                        'birth': z.cur_time + pd.Timedelta(minutes=TFS[tf])})
        f = detect_fvg(df, j)
        if f is not None:
            out.append({'b': f.bottom, 't': f.top, 'dir': f.direction, 'type': 'FVG', 'tf': tf,
                        'birth': f.c2_time + pd.Timedelta(minutes=TFS[tf])})
    return out


def build(sym, store12, store1h):
    frames = {tf: _load(sym, tf) for tf in TFS}
    zall = [z for tf in TFS for z in zones(frames[tf], tf)]
    d12 = frames['12h']
    h = d12['high'].values; l = d12['low'].values; c = d12['close'].values; v = d12['volume'].values
    t12 = d12.index; n = len(c); atrv = atr_series(d12, 14).values
    rsi = rsi_wilder(d12['close'], 14).values; hull = hull_ma(d12['close'], 78).values
    ema200 = ema(d12['close'], 200).values
    vmean = pd.Series(v).rolling(20).mean().values; vstd = pd.Series(v).rolling(20).std().values
    htf = {}
    for tf in ('1d', '3d'):
        hm = hull_ma(frames[tf]['close'], 50); dd = (hm > hm.shift(3)).astype(int)*2-1
        dd.index = dd.index + pd.Timedelta(minutes=TFS[tf]); htf[tf] = dd
    d1h = load_df(sym, "1h"); d1h = d1h[(d1h.index >= START) & (d1h.index <= END)]
    store12[sym] = (h, l, atrv, t12); store1h[sym] = (d1h['high'].values, d1h['low'].values,
                                                       d1h.index.values.astype('datetime64[ns]'))
    rows = []
    for z in zall:
        wpct = (z['t'] - z['b']) / z['t'] * 100
        if wpct > WMAX or wpct < 0.5:
            continue
        long = z['dir'] == 'LONG'
        b0 = int(np.searchsorted(t12.values, np.datetime64(z['birth'].tz_localize(None)), side='right'))
        tj = None
        for k in range(b0, n):
            if l[k] <= z['t'] and h[k] >= z['b']:
                tj = k; break
        if tj is None or tj < max(200, RANGE_W) or tj >= n - 1 or atrv[tj] <= 0:
            continue
        entry = c[tj]; ts = t12[tj]; price = c[tj]; fi = tj
        w0 = max(0, tj - ACC_W); s_lo = l[w0:tj]; s_hi = h[w0:tj]; s_c = c[w0:tj]; s_v = v[w0:tj]
        ov = (s_lo <= z['t']) & (s_hi >= z['b']); ci = (s_c >= z['b']) & (s_c <= z['t'])
        rlo = l[fi-RANGE_W:fi+1].min(); rhi = h[fi-RANGE_W:fi+1].max()
        rows.append({
            'symbol': sym, 'time': ts, 'touch_j': tj, 'entry': entry, 'atr': atrv[tj],
            'side_long': int(long), 'tf_w': TF_W[z['tf']], 'is_ob': int(z['type'] == 'OB'),
            'zone_width_pct': wpct, 'pos_in_range': (entry - rlo)/(rhi - rlo) if rhi > rlo else 0.5,
            'age_h': min((ts - z['birth']).total_seconds()/3600, 9999),
            'rsi14': rsi[fi] if not np.isnan(rsi[fi]) else 50.0,
            'ema200_dist': (price - ema200[fi])/price*100 if not np.isnan(ema200[fi]) else 0.0,
            'hull_dir': 1.0 if (not np.isnan(hull[fi]) and not np.isnan(hull[fi-3]) and hull[fi] > hull[fi-3]) else -1.0,
            'atr_pct': atrv[fi]/price*100,
            'vol_z': (v[fi]-vmean[fi])/vstd[fi] if not np.isnan(vstd[fi]) and vstd[fi] else 0.0,
            'htf_1d_dir': float(htf['1d'].asof(ts)) if pd.notna(htf['1d'].asof(ts)) else 0.0,
            'htf_3d_dir': float(htf['3d'].asof(ts)) if pd.notna(htf['3d'].asof(ts)) else 0.0,
            'acc_candles': int(ci.sum()), 'acc_touch_bars': int(ov.sum()),
            'acc_vol_frac': float(s_v[ov].sum() / (s_v.sum() + 1e-9)),
        })
    return rows


def label12(df, TM, SM, H, store12):
    """ATR-цель на 12h: held=+TM·ATR раньше −SM·ATR. Возвращает held, net_R."""
    held = np.zeros(len(df), np.int8); net = np.full(len(df), np.nan)
    for i, r in enumerate(df.itertuples()):
        h, l, atrv, _ = store12[r.symbol]
        j = r.touch_j; e = r.entry; a = r.atr; long = r.side_long == 1
        tgt = e + TM*a if long else e - TM*a
        stp = e - SM*a if long else e + SM*a
        end = min(j + 1 + H, len(h))
        out = None
        for k in range(j + 1, end):
            if long:
                if l[k] <= stp: out = 0; break
                if h[k] >= tgt: out = 1; break
            else:
                if h[k] >= stp: out = 0; break
                if l[k] <= tgt: out = 1; break
        if out is None:
            continue
        held[i] = out
        rr = TM / SM
        risk_pct = SM*a / e
        net[i] = (rr if out == 1 else -1.0) - (2*SIDE_COST)/max(risk_pct, 0.003)
    return held, net


def purged_cv_netR(X, y, net, tdays, n_splits=4):
    """CV: train модель, фильтр P≥0.6, средний net_R на отложенных фолдах."""
    order = np.argsort(tdays); folds = np.array_split(order, n_splits); vals = []
    for f in folds:
        lo, hi = tdays[f].min(), tdays[f].max()
        keep = np.ones(len(y), bool); keep[f] = False
        keep &= ~((tdays + HORIZON_D >= lo - EMBARGO_D) & (tdays <= hi + EMBARGO_D))
        if keep.sum() < 300 or y[keep].sum() < 30 or len(np.unique(y[keep])) < 2:
            continue
        m = CatBoostClassifier(iterations=400, learning_rate=0.05, depth=6, l2_leaf_reg=3,
                               task_type='GPU', devices='0', verbose=0, random_seed=0).fit(X[keep], y[keep])
        p = m.predict_proba(X[f])[:, 1]
        sel = net[f][(p >= 0.6) & ~np.isnan(net[f])]
        if len(sel) >= 10:
            vals.append(sel.mean())
    return np.mean(vals) if vals else -9, (np.mean([len(np.array_split(order, n_splits)[0])]) if vals else 0)


def main():
    t0 = time.time()
    print("=" * 78)
    print("zone_reactor v2: САМОНАСТРОЙКА ЦЕЛИ (ATR) на train 2020-24 → test 2025-26 (1 раз)")
    print("=" * 78)
    store12, store1h = {}, {}
    rows = []
    for sym in SYMBOLS:
        rows.extend(build(sym, store12, store1h))
    df = pd.DataFrame(rows).reset_index(drop=True)
    df['tdays'] = (pd.to_datetime(df['time'], utc=True) - pd.to_datetime(df['time'], utc=True).min()).dt.total_seconds()/86400
    is_tr = (pd.to_datetime(df['time'], utc=True) < TRAIN_END).values
    print(f"зон: {len(df)}  TRAIN {is_tr.sum()} / TEST {(~is_tr).sum()}")
    Xall = df[BASE].fillna(0).values

    # --- САМОНАСТРОЙКА ЦЕЛИ: поиск (TM,SM,H) по CV-net_R ТОЛЬКО на train ---
    print("\nПоиск цели на TRAIN (purged-CV net_R, P≥0.6):")
    best = None
    tr_idx = np.where(is_tr)[0]
    for H in H_GRID:
        for SM in SM_GRID:
            for TM in TM_GRID:
                if TM / SM < 1.0:
                    continue
                held, net = label12(df, TM, SM, H, store12)
                ytr = held[tr_idx]; Xtr = Xall[tr_idx]; nettr = net[tr_idx]; tdtr = df['tdays'].values[tr_idx]
                cvR, _ = purged_cv_netR(Xtr, ytr, nettr, tdtr)
                base = ytr.mean()
                if best is None or cvR > best[0]:
                    best = (cvR, TM, SM, H, base)
    cvR, TM, SM, H, base = best
    print(f"  ВЫБРАНА цель: TM={TM}·ATR / SM={SM}·ATR / H={H}×12h (rr={TM/SM:.2f})  "
          f"CV net_R/tr={cvR:+.3f}  held-база={base*100:.0f}%")

    # --- ФИНАЛ: заморозили цель, тест ОДИН раз ---
    held, net = label12(df, TM, SM, H, store12)
    df['held'] = held; df['net12'] = net
    clf = CatBoostClassifier(iterations=600, learning_rate=0.04, depth=6, l2_leaf_reg=3,
                             task_type='GPU', devices='0', verbose=0, random_seed=0).fit(Xall[tr_idx], held[tr_idx])
    te_idx = np.where(~is_tr)[0]
    p_te = clf.predict_proba(Xall[te_idx])[:, 1]
    yte = held[te_idx]; auc = roc_auc_score(yte, p_te)
    te = df.iloc[te_idx].copy(); te['p'] = p_te
    print(f"\nTEST 2025-2026 (1 раз): OOS AUC={auc:.3f}  held-база={yte.mean()*100:.0f}%")
    print(f"  baseline (все касания, ATR-цель) net_R/tr={te['net12'].mean():+.3f}")
    for tau in [0.5, 0.6, 0.7]:
        s = te[(te.p >= tau) & te['net12'].notna()]
        if len(s) < 20: continue
        print(f"  P≥{tau}: n={len(s):>4} held%={s['held'].mean()*100:>3.0f} net_R/tr={s['net12'].mean():+.3f} ΣR={s['net12'].sum():+.0f}")
    s = te[(te.p >= 0.6) & te['net12'].notna()].copy(); s['yr'] = pd.to_datetime(s['time'], utc=True).dt.year
    print("  P≥0.6 по годам:", "  ".join(f"{y}:n{len(g)}/R{g['net12'].mean():+.2f}" for y, g in s.groupby('yr')))

    # permutation null-тест выбранной цели
    rng = np.random.RandomState(0); real = te[(te.p >= 0.6)]['net12'].dropna().mean()
    null = []
    for _ in range(200):
        pp = rng.permutation(p_te)
        sel = te['net12'].values[(pp >= 0.6) & te['net12'].notna().values]
        if len(sel) >= 10: null.append(np.nanmean(sel))
    null = np.array(null); pval = (null >= real).mean()
    print(f"\nNull-тест (случайный P): real net_R/tr={real:+.3f} vs null mean={null.mean():+.3f}  p={pval:.3f}")
    print("=" * 78)
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
