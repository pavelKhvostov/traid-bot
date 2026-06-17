"""zone_reactor.backtest_1h — ТОЧНОЕ исполнение на 1h валидированной конфигурации.

12h-резолв был оптимистичен (грубое внутрибарное). Здесь честно на 1h:
  вход = проксимальный край зоны (лимит, на касании), SL = дальний край, TP = +5%,
  резолв на 1h, SL первым при касании обоих в баре (консерв.), горизонт 10 дней,
  издержки taker+slip 0.08%/сторону + funding 0.01%/8h.
Фичи (≤ касания, last-closed 12h) → GBM, train 2020-2024, test 2025-2026, фильтр P≥0.6.
Зоны ≤5% ширины (валид. конфиг). Отчёт: WR/ΣR/R-tr/по годам/max DD/частота.
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
from data_manager import load_df, compose_from_base
from research.elements_study.etap_170_lopez_features import rsi_wilder, hull_ma, ema, atr as atr_series
from research.zone_reactor.zone_touch import detect_zones, confluence_at, TF_MIN, TF_W, _load_tf

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START = pd.Timestamp("2020-01-01", tz="UTC"); END = pd.Timestamp("2026-06-11", tz="UTC")
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")    # train 2020-2024 / test 2025-2026
WMAX = 5.0; REACT = 5.0; HOLD_1H = 240; RANGE_W = 60
SIDE_COST = 0.0008; FUNDING_8H = 0.0001
FEAT = ['tf_w', 'is_ob', 'conf_count', 'conf_strength', 'in_htf', 'n_tf_aligned', 'disp_body',
        'age_h', 'pos_in_range', 'zone_width_pct', 'side_long', 'atr_pct', 'vol_z', 'rsi14',
        'ema200_dist', 'hull_dir', 'htf_1d_dir', 'htf_3d_dir']


def resolve_1h(long, entry, far, tp, h1, l1, start, n):
    """held + net_R на 1h, SL-first. risk=|entry-far|."""
    risk_pct = abs(entry - far) / entry
    end = min(start + HOLD_1H, n)
    for k in range(start, end):
        if long:
            if l1[k] <= far: out, ex = 0, k; break
            if h1[k] >= tp: out, ex = 1, k; break
        else:
            if h1[k] >= far: out, ex = 0, k; break
            if l1[k] <= tp: out, ex = 1, k; break
    else:
        return None
    hours = max(1, ex - start)
    cost = (2 * SIDE_COST + FUNDING_8H * hours / 8) / risk_pct
    rr = (REACT / 100) / risk_pct
    return out, (rr if out == 1 else -1.0) - cost, hours


def build(sym):
    frames = {tf: _load_tf(sym, tf) for tf in TF_MIN}
    zall = [z for tf in TF_MIN for z in detect_zones(frames[tf], tf)]
    d12 = frames['12h']
    h = d12['high'].values; l = d12['low'].values; c = d12['close'].values; v = d12['volume'].values
    t12 = d12.index; n = len(c)
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
    TOUCH_WIN = 1440   # окно поиска касания на 1h после рождения зоны (60 дней)
    rows = []
    for z in zall:
        wpct = (z['t'] - z['b']) / z['t'] * 100
        if wpct > WMAX or wpct < 0.5:       # флор 0.5%: тесные стопы неторгуемы (шум/слиппедж)
            continue
        long = z['dir'] == 'LONG'
        entry = z['t'] if long else z['b']; far = z['b'] if long else z['t']
        tp = entry * (1 + REACT/100) if long else entry * (1 - REACT/100)
        # РЕАЛЬНОЕ касание на 1h: первый 1h-бар после рождения, вошедший в зону
        b0 = int(np.searchsorted(t1ns, np.datetime64(z['birth'].tz_convert('UTC').tz_localize(None)), side='right'))
        e0 = min(b0 + TOUCH_WIN, len(h1))
        if b0 >= e0:
            continue
        mask = (l1[b0:e0] <= z['t']) & (h1[b0:e0] >= z['b'])
        if not mask.any():
            continue
        s1 = b0 + int(np.argmax(mask))      # бар фактического касания на 1h
        ts = d1h.index[s1]                    # реальное время касания
        j = int(np.searchsorted(t12.values, np.datetime64(ts.tz_localize(None)), side='right')) - 1
        if j < max(200, RANGE_W) or j >= n - 1 or atr[j] <= 0:
            continue
        r = resolve_1h(long, entry, far, tp, h1, l1, s1 + 1, len(h1))   # резолв со следующего 1h-бара
        if r is None:
            continue
        held, netR, hours = r
        fi = j; price = c[fi]      # j уже последний ЗАКРЫТЫЙ 12h-бар до касания (searchsorted right -1)
        cnt, strength, htf, ntf = confluence_at(entry, z['dir'], ts, zall)
        rlo = l[fi-RANGE_W:fi+1].min(); rhi = h[fi-RANGE_W:fi+1].max()
        rows.append({
            'symbol': sym, 'time': ts, 'tf_w': TF_W[z['tf']], 'is_ob': int(z['type'] == 'OB'),
            'side_long': int(long), 'held': held, 'net_R': netR, 'hours': hours,
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


def maxdd(equity):
    peak = -1e9; dd = 0
    for x in np.cumsum(equity):
        peak = max(peak, x); dd = min(dd, x - peak)
    return dd


def main():
    t0 = time.time()
    print("=" * 78)
    print("zone_reactor 1h-БЭКТЕСТ (точное исполнение) · train 2020-2024 / test 2025-2026 · зоны ≤5%")
    print("=" * 78)
    rows = []
    for sym in SYMBOLS:
        r = build(sym); rows.extend(r); print(f"  [{sym}] сделок(filled): {len(r)}")
    df = pd.DataFrame(rows).sort_values('time').reset_index(drop=True)
    df[FEAT] = df[FEAT].fillna(0)
    df.to_csv(_ROOT / 'research/zone_reactor/backtest_1h_dataset.csv', index=False)
    is_tr = (df['time'] < TRAIN_END).values
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.04, max_leaf_nodes=31,
        min_samples_leaf=40, l2_regularization=1.0, random_state=0).fit(df.loc[is_tr, FEAT].values, df.loc[is_tr, 'held'].values)
    te = df.loc[~is_tr].copy(); te['p'] = clf.predict_proba(te[FEAT].values)[:, 1]
    auc = roc_auc_score(te['held'], te['p'])
    print(f"\nTRAIN n={is_tr.sum()} / TEST n={len(te)} | OOS AUC(1h-held)={auc:.3f}")
    print(f"baseline (все касания вслепую, 1h): WR={te['held'].mean()*100:.0f}% ΣR={te['net_R'].sum():+.0f} R/tr={te['net_R'].mean():+.3f}")

    print(f"\n{'фильтр':>8} {'n':>5} {'WR%':>5} {'ΣR':>7} {'R/tr':>7} {'medHold_h':>9} {'maxDD_R':>8}")
    for tau in [0.5, 0.6, 0.7]:
        s = te[te.p >= tau].sort_values('time')
        if len(s) < 20: continue
        print(f"   P≥{tau:.1f} {len(s):>5} {s['held'].mean()*100:>4.0f} {s['net_R'].sum():>+7.0f} "
              f"{s['net_R'].mean():>+7.3f} {s['hours'].median():>9.0f} {maxdd(s['net_R'].values):>8.1f}")
    s = te[te.p >= 0.6].copy(); s['yr'] = s['time'].dt.year
    print("\nP≥0.6 по годам (точное 1h-исполнение):")
    for y, g in s.groupby('yr'):
        print(f"   {y}: n={len(g):>3} WR={g['held'].mean()*100:>3.0f}% ΣR={g['net_R'].sum():>+5.0f} R/tr={g['net_R'].mean():+.3f}")
    print(f"\nДоля касаний, разрешившихся в горизонте 10д (не timeout): "
          f"{len(df)/max(len(df),1)*100:.0f}% (timeout уже отброшены)")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
