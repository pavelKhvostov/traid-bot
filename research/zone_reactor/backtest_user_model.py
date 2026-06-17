"""zone_reactor.backtest_user_model — модель пользователя: вход на ЗАКРЫТИИ 12h-свечи.

Критика пользователя (верная): 12h.low = min(1h.low) → если 12h-свеча не пробила
дальний край, 1h внутри неё тоже не пробила. Значит 1h не может дать больше стопов,
чем 12h при ОДНОМ входе. Разница held% в backtest_1h была от РАЗНОЙ логики, не от 1h.

Тест правильной модели:
  • касание = первый 12h-бар, вошедший в зону (после рождения зоны);
  • ВХОД = CLOSE этого 12h-бара (как говорит пользователь);
  • SL = дальний край зоны, TP = entry ± 5%;
  • резолв на 12h И на 1h (одни и те же бары) → проверяем равенство held%.
Зоны ≤5%. train 2020-2024 / test 2025-2026. Фильтр модели P≥0.6. Издержки учтены.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from data_manager import load_df
from research.elements_study.etap_170_lopez_features import rsi_wilder, hull_ma, ema, atr as atr_series
from research.zone_reactor.zone_touch import detect_zones, confluence_at, TF_MIN, TF_W, _load_tf

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START = pd.Timestamp("2020-01-01", tz="UTC"); END = pd.Timestamp("2026-06-11", tz="UTC")
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
WMAX = 5.0; REACT = 5.0; HOLD12 = 20; RANGE_W = 60; RISK_FLOOR = 0.003
SIDE_COST = 0.0008; FUNDING_8H = 0.0001
FEAT = ['tf_w', 'is_ob', 'conf_count', 'conf_strength', 'in_htf', 'n_tf_aligned', 'disp_body',
        'age_h', 'pos_in_range', 'zone_width_pct', 'side_long', 'atr_pct', 'vol_z', 'rsi14',
        'ema200_dist', 'hull_dir', 'htf_1d_dir', 'htf_3d_dir']


def resolve(long, entry, far, tp, H, L, start, n, bars12=True):
    risk_pct = max(abs(entry - far) / entry, RISK_FLOOR)
    end = min(start + n, len(H))
    for k in range(start, end):
        if long:
            if L[k] <= far: out = 0; ex = k; break
            if H[k] >= tp: out = 1; ex = k; break
        else:
            if H[k] >= far: out = 0; ex = k; break
            if L[k] <= tp: out = 1; ex = k; break
    else:
        return None
    hours = max(1, (ex - start + 1) * (12 if bars12 else 1))
    cost = (2 * SIDE_COST + FUNDING_8H * hours / 8) / risk_pct
    rr = (REACT / 100) / risk_pct
    return out, (rr if out == 1 else -1.0) - cost


def build(sym):
    frames = {tf: _load_tf(sym, tf) for tf in TF_MIN}
    zall = [z for tf in TF_MIN for z in detect_zones(frames[tf], tf)]
    d12 = frames['12h']
    o = d12['open'].values; h = d12['high'].values; l = d12['low'].values; c = d12['close'].values
    v = d12['volume'].values; t12 = d12.index; n = len(c)
    atr = atr_series(d12, 14).values; rsi = rsi_wilder(d12['close'], 14).values
    hull = hull_ma(d12['close'], 78).values; ema200 = ema(d12['close'], 200).values
    vmean = pd.Series(v).rolling(20).mean().values; vstd = pd.Series(v).rolling(20).std().values
    htf_dir = {}
    for tf in ('1d', '3d'):
        hm = hull_ma(frames[tf]['close'], 50); dd = (hm > hm.shift(3)).astype(int)*2-1
        dd.index = dd.index + pd.Timedelta(minutes=TF_MIN[tf]); htf_dir[tf] = dd
    d1h = load_df(sym, "1h"); d1h = d1h[(d1h.index >= START) & (d1h.index <= END)]
    h1 = d1h['high'].values.astype(float); l1 = d1h['low'].values.astype(float)
    t1ns = d1h.index.values.astype('datetime64[ns]')
    rows = []
    for z in zall:
        wpct = (z['t'] - z['b']) / z['t'] * 100
        if wpct > WMAX or wpct < 0.5:
            continue
        long = z['dir'] == 'LONG'
        # касание = первый 12h-бар после рождения, вошедший в зону
        b0 = int(np.searchsorted(t12.values, np.datetime64(z['birth'].tz_localize(None)), side='right'))
        touch_j = None
        for k in range(b0, n):
            if l[k] <= z['t'] and h[k] >= z['b']:
                touch_j = k; break
        if touch_j is None or touch_j < max(200, RANGE_W) or touch_j >= n - 1:
            continue
        j = touch_j
        entry = c[j]                       # ВХОД = закрытие 12h-свечи касания
        far = z['b'] if long else z['t']
        if (long and entry <= far) or (not long and entry >= far):
            continue
        tp = entry * (1 + REACT/100) if long else entry * (1 - REACT/100)
        r12 = resolve(long, entry, far, tp, h, l, j + 1, HOLD12, True)
        if r12 is None:
            continue
        # 1h-резолв с 1h-бара после закрытия этой 12h-свечи (та же точка входа)
        close_ts = t12[j] + pd.Timedelta(hours=12)
        s1 = int(np.searchsorted(t1ns, np.datetime64(close_ts.tz_localize(None)), side='left'))
        r1 = resolve(long, entry, far, tp, h1, l1, s1, HOLD12 * 12, False) if s1 < len(h1) else None
        held12, net12 = r12
        held1, net1 = (r1 if r1 else (held12, net12))
        fi = j; price = c[fi]; ts = t12[j]
        cnt, strength, htf, ntf = confluence_at(entry, z['dir'], ts, zall)
        rlo = l[fi-RANGE_W:fi+1].min(); rhi = h[fi-RANGE_W:fi+1].max()
        rows.append({
            'symbol': sym, 'time': ts, 'tf_w': TF_W[z['tf']], 'is_ob': int(z['type'] == 'OB'),
            'side_long': int(long), 'held12': held12, 'net12': net12, 'held1': held1, 'net1': net1,
            'conf_count': cnt, 'conf_strength': strength, 'in_htf': htf, 'n_tf_aligned': ntf,
            'disp_body': z['disp_body'], 'age_h': min((ts - z['birth']).total_seconds()/3600, 9999),
            'pos_in_range': (entry - rlo)/(rhi - rlo) if rhi > rlo else 0.5,
            'zone_width_pct': (z['t'] - z['b'])/price*100,
            'rsi14': rsi[fi] if not np.isnan(rsi[fi]) else 50.0,
            'ema200_dist': (price - ema200[fi])/price*100 if not np.isnan(ema200[fi]) else 0.0,
            'hull_dir': 1.0 if (not np.isnan(hull[fi]) and not np.isnan(hull[fi-3]) and hull[fi] > hull[fi-3]) else -1.0,
            'atr_pct': atr[fi]/price*100,
            'vol_z': (v[fi]-vmean[fi])/vstd[fi] if not np.isnan(vstd[fi]) and vstd[fi] else 0.0,
            'htf_1d_dir': float(htf_dir['1d'].asof(ts)) if pd.notna(htf_dir['1d'].asof(ts)) else 0.0,
            'htf_3d_dir': float(htf_dir['3d'].asof(ts)) if pd.notna(htf_dir['3d'].asof(ts)) else 0.0,
        })
    return rows


def main():
    t0 = time.time()
    print("=" * 78)
    print("МОДЕЛЬ ПОЛЬЗОВАТЕЛЯ: вход на CLOSE 12h-свечи касания зоны · train20-24/test25-26")
    print("=" * 78)
    rows = []
    for sym in SYMBOLS:
        r = build(sym); rows.extend(r); print(f"  [{sym}] сделок: {len(r)}")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True); df[FEAT] = df[FEAT].fillna(0)
    # проверка равенства 12h vs 1h резолва
    agree = (df['held12'] == df['held1']).mean() * 100
    print(f"\nПРОВЕРКА: held12 == held1 у {agree:.1f}% сделок  (если ~100% — пользователь прав: 1h≡12h)")
    print(f"  средний net12={df['net12'].mean():+.3f}  net1={df['net1'].mean():+.3f}")

    is_tr = (df['time'] < TRAIN_END).values
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(df.loc[is_tr, FEAT].values, df.loc[is_tr, 'held12'].values)
    te = df.loc[~is_tr].copy(); te['p'] = clf.predict_proba(te[FEAT].values)[:, 1]
    print(f"\nTEST n={len(te)} OOS AUC={roc_auc_score(te['held12'], te['p']):.3f}  "
          f"baseline net12 R/tr={te['net12'].mean():+.3f}")
    print(f"{'P≥':>5} {'n':>5} {'WR%':>5} {'R/tr(12h)':>10} {'R/tr(1h)':>9}")
    for tau in [0.5, 0.6, 0.7]:
        s = te[te.p >= tau]
        if len(s) < 15: continue
        print(f"{tau:>5.1f} {len(s):>5} {s['held12'].mean()*100:>4.0f} {s['net12'].mean():>+10.3f} {s['net1'].mean():>+9.3f}")
    s = te[te.p >= 0.6].copy(); s['yr'] = s['time'].dt.year
    print("\nP≥0.6 по годам (R/tr 12h):")
    for y, g in s.groupby('yr'):
        print(f"   {y}: n={len(g):>3} WR={g['held12'].mean()*100:>3.0f}% R/tr={g['net12'].mean():+.3f} ΣR={g['net12'].sum():+.0f}")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
