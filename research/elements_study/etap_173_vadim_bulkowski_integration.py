"""etap_173: интеграция Vadim 12h-fractal-predictor + Bulkowski на базе etap_171.

Расширяет 270 фичей etap_171 (VSA + Nison + Lopez + zone strength + USDT.D)
за счёт independent сигналов из работы Вадима по 12h-фрактал-prediction
и наших Bulkowski-детекторов (etap_172).

=== ДОБАВЛЯЕТСЯ ===

  GROUP A: Vadim zone-sweep[i] features (8 фич)
    Из research/vic_vadim/predict_fractal_zones.py.
    sweep[i] = wick + close назад. Для каждой комбинации:
      class ∈ {OB, FH/FL} × tf ∈ {12h, 1d} × dir ∈ {LONG, SHORT}.
    Mitigation: только первый sweep после ready_time зоны.
    Эмпирический edge Vadim'a 6y BTC: precision 52-65%.

  GROUP B: Vadim maxV(i-1) C2 features (4 фичи)
    Из research/vic_vadim/predict_fractal_maxv_pine.py (LTF=8m Pine-exact).
    maxV(i-1) = close LTF-бара с max volume в предыдущей 12h свече.
    Sweep[i] относительно maxV(i-1) — самый сильный single filter Vadim'a.

  GROUP D: Vadim composite Sniper flags (2 фичи)
    HH Sniper: sweep_FH[i] AND sweep_OB_SHORT[i] AND maxV_sweep_HH[i]
    LL Sniper: симметрично. Эмпирически 93% precision у Vadim'a (~5/yr).

  GROUP E: Bulkowski top-5 patterns (10 фич)
    Из etap_172. Top-5 по edge: big_w, db_eve_eve, v_bottom, hs_bottom, big_m.
    Per pattern: fired_<name> (binary), bars_since_<name> (decay 0..60).

=== БАЗА (НЕ ТРОГАЕТСЯ) ===

  etap_171 build_dataset -> 270 фич:
    индикаторы 12h, HTF Hull (HONEST), zones LONG/SHORT split,
    zone strength (age/width/touches), USDT.D, sweep history,
    block_orders proximity, time-of-day, micro-структура Lopez,
    fractional differentiation, SADF, VSA cluster, Nison candles, doji family,
    confluence_score, phase_state.

  Honest методология сохранена: HTF asof на ts_close,
  Purged K-Fold CV с embargo=14, sample weights = uniqueness × |return|.

Output:
  research/elements_study/output/etap_173_run.log
  research/elements_study/output/etap_173_summary.csv  # AUC + сравнение с etap_171
  research/elements_study/output/etap_173_pred_*.csv   # predictions per target
  research/elements_study/output/etap_173_feature_importance.csv
"""
from __future__ import annotations
import sys as _sys
import time
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from data_manager import load_df, compose_from_base

# Импортируем готовый build_dataset из etap_171 — наша 270-fic base
import importlib.util
_etap171_path = _ROOT / 'research' / 'elements_study' / 'etap_171_vsa_candlesticks.py'
_spec = importlib.util.spec_from_file_location("etap_171", _etap171_path)
_etap171 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_etap171)
build_dataset_base = _etap171.build_dataset

# Импортируем 13 Bulkowski-детекторов из etap_172
_etap172_path = _ROOT / 'research' / 'elements_study' / 'etap_172_bulkowski_patterns.py'
_spec172 = importlib.util.spec_from_file_location("etap_172", _etap172_path)
_etap172 = importlib.util.module_from_spec(_spec172)
_spec172.loader.exec_module(_etap172)

SYMBOL = "BTCUSDT"
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
TEST_END = pd.Timestamp("2026-05-31", tz="UTC")
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
TARGETS = [3.0, 4.0, 5.0]

# Top-5 паттернов Bulkowski (по результатам etap_172 на BTC 12h)
BULKOWSKI_TOP5 = ['big_w', 'db_eve_eve', 'v_bottom', 'hs_bottom', 'big_m']
BULKOWSKI_DETECTORS = {
    'big_w': _etap172.detect_big_w,
    'db_eve_eve': _etap172.detect_db_eve_eve,
    'v_bottom': _etap172.detect_v_bottom,
    'hs_bottom': _etap172.detect_hs_bottom,
    'big_m': _etap172.detect_big_m,
}
BARS_SINCE_CAP = 60


# ============================================================
# GROUP A: Vadim zone-sweep[i] (port из predict_fractal_zones.py)
# ============================================================

def _find_ob_zones(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    """Canon OB на одном ТФ. ready_time = close cur-свечи (+tf_dur от open(cur))."""
    out = []
    o = df_tf['open'].values; h = df_tf['high'].values
    l = df_tf['low'].values; c = df_tf['close'].values
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta('12h')
    for k in range(len(df_tf) - 1):
        prev_bear = c[k] < o[k]
        prev_bull = c[k] > o[k]
        cur_bull = c[k+1] > o[k+1]
        cur_bear = c[k+1] < o[k+1]
        # LONG OB
        if prev_bear and cur_bull and c[k+1] > o[k]:
            zb = float(min(l[k], l[k+1]))
            zt = float(o[k])
            if zt > zb:
                out.append({'dir':'LONG','kind':'OB','tf':tf_label,
                            'zb':zb,'zt':zt,'ready_ts':idx[k+1] + tf_dur})
        # SHORT OB
        if prev_bull and cur_bear and c[k+1] < o[k]:
            zb = float(o[k])
            zt = float(max(h[k], h[k+1]))
            if zt > zb:
                out.append({'dir':'SHORT','kind':'OB','tf':tf_label,
                            'zb':zb,'zt':zt,'ready_ts':idx[k+1] + tf_dur})
    return out


def _find_fractals(df_tf: pd.DataFrame, tf_label: str) -> list[dict]:
    """Williams FH/FL (n=2). FH ready на close i+2. Только confirmed."""
    out = []
    h = df_tf['high'].values; l = df_tf['low'].values
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta('12h')
    for i in range(2, len(df_tf) - 2):
        # FH
        if h[i] > h[i-2] and h[i] > h[i-1] and h[i] > h[i+1] and h[i] > h[i+2]:
            out.append({'dir':'SHORT','kind':'FH','tf':tf_label,
                        'zb':float(h[i]),'zt':float(h[i]),
                        'ready_ts':idx[i+2] + tf_dur})
        # FL
        if l[i] < l[i-2] and l[i] < l[i-1] and l[i] < l[i+1] and l[i] < l[i+2]:
            out.append({'dir':'LONG','kind':'FL','tf':tf_label,
                        'zb':float(l[i]),'zt':float(l[i]),
                        'ready_ts':idx[i+2] + tf_dur})
    return out


def _sweep_features_at_bar(zones_by_kind_dir_tf: dict, df_12h: pd.DataFrame, i: int,
                            first_swept_ts: dict) -> dict:
    """Vadim sweep[i] для каждой комбинации (class, tf, dir).

    sweep_OB_SHORT[i] = high[i] > zone.zt AND close[i] < zone.zt (HH->SHORT)
    sweep_OB_LONG[i]  = low[i] < zone.zb  AND close[i] > zone.zb  (LL->LONG)
    sweep_FH[i] = high[i] > FH.zt AND close[i] < FH.zt
    sweep_FL[i] = low[i]  < FL.zb AND close[i] > FL.zb

    Mitigation: first_swept_ts[(kind, tf, idx)] = ts_close первого sweep'a.
    Если sweep[i] происходит на ранее не свёпнутой зоне И ready_ts ≤ ts_close(i)
    -> это «первый sweep» (mitigation-1).
    """
    ts_close = df_12h.index[i] + pd.Timedelta(hours=12)
    cur_high = df_12h['high'].iloc[i]
    cur_low = df_12h['low'].iloc[i]
    cur_close = df_12h['close'].iloc[i]

    out = {}
    for (kind, tf, dir_), zlist in zones_by_kind_dir_tf.items():
        # Только зоны готовые ≤ ts_close (никакого lookahead)
        # И только зоны не свёпнутые ранее
        any_first_sweep = 0
        nearest_dist_pct = 20.0
        for zi, z in enumerate(zlist):
            if z['ready_ts'] > ts_close:
                continue
            zkey = (kind, tf, zi)
            if first_swept_ts.get(zkey) is not None and first_swept_ts[zkey] < ts_close:
                continue  # already swept ранее
            # Проверка sweep на текущем баре
            if dir_ == 'SHORT':  # HH-направление
                # FH: zb==zt==level
                level_top = z['zt']
                if cur_high > level_top and cur_close < level_top:
                    any_first_sweep = 1
                    first_swept_ts[zkey] = ts_close
                # дистанция до zone.top
                d = max(0.0, (level_top - cur_close) / cur_close * 100)
                if d < nearest_dist_pct:
                    nearest_dist_pct = d
            else:  # LONG
                level_bot = z['zb']
                if cur_low < level_bot and cur_close > level_bot:
                    any_first_sweep = 1
                    first_swept_ts[zkey] = ts_close
                d = max(0.0, (cur_close - level_bot) / cur_close * 100)
                if d < nearest_dist_pct:
                    nearest_dist_pct = d

        out[f'vad_sweep_{kind}_{tf}_{dir_}'] = any_first_sweep
        out[f'vad_dist_unswept_{kind}_{tf}_{dir_}_pct'] = min(nearest_dist_pct, 20.0)

    return out


def _precompute_vadim_zones(df_1h: pd.DataFrame) -> dict:
    """Собираем все Vadim zone-классы по HTF. Используются 12h и 1d."""
    print('  precomputing Vadim zone catalog (OB + FH/FL on 12h, 1d)...')
    df_12h_zones = compose_from_base(df_1h, '12h')
    df_1d_zones = compose_from_base(df_1h, '1d')

    z = {}
    for tf_label, df_tf in [('12h', df_12h_zones), ('1d', df_1d_zones)]:
        for zone in _find_ob_zones(df_tf, tf_label):
            key = (zone['kind'], tf_label, zone['dir'])
            z.setdefault(key, []).append(zone)
        for zone in _find_fractals(df_tf, tf_label):
            key = (zone['kind'], tf_label, zone['dir'])
            z.setdefault(key, []).append(zone)
    # Дайте каждому списку стабильный порядок
    for key in z:
        z[key].sort(key=lambda x: x['ready_ts'])
    n_total = sum(len(v) for v in z.values())
    print(f'    zone classes: {len(z)}, zones total: {n_total}')
    return z


# ============================================================
# GROUP B: Vadim maxV(i-1) C2 (port из predict_fractal_maxv_pine.py)
# ============================================================

def _calculate_maxv_pine(df_1m: pd.DataFrame, bar_open: pd.Timestamp,
                          ltf_minutes: int = 8) -> float | None:
    """Pine ASVK ViC maxV: LTF=8m epoch-aligned, max bullish OR bearish volume."""
    end = bar_open + pd.Timedelta(hours=12)
    mask = (df_1m.index >= bar_open) & (df_1m.index < end)
    sub = df_1m.loc[mask]
    if sub.empty:
        return None
    s = sub.resample(f'{ltf_minutes}min', origin='epoch', label='left', closed='left').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum',
    }).dropna(subset=['close'])
    if s.empty:
        return None
    bull = s[s['close'] > s['open']]
    bear = s[s['close'] < s['open']]
    mb = bull['volume'].max() if not bull.empty else 0
    mr = bear['volume'].max() if not bear.empty else 0
    if mb == 0 and mr == 0:
        return None
    if mb > mr:
        return float(bull.loc[bull['volume'].idxmax(), 'close'])
    return float(bear.loc[bear['volume'].idxmax(), 'close'])


def _precompute_maxv_series(df_12h: pd.DataFrame, df_1m: pd.DataFrame) -> pd.Series:
    """Считаем maxV для каждой 12h-свечи. Дальше .shift(1) даёт maxV(i-1)."""
    print('  precomputing maxV per 12h bar (LTF=8m Pine-exact)...')
    t0 = time.time()
    maxvs = []
    for ts in df_12h.index:
        mv = _calculate_maxv_pine(df_1m, ts, ltf_minutes=8)
        maxvs.append(mv)
    s = pd.Series(maxvs, index=df_12h.index, name='maxV')
    valid = s.notna().sum()
    print(f'    maxV computed: {valid}/{len(s)}  ({time.time()-t0:.1f}s)')
    return s


# ============================================================
# GROUP C: Bulkowski top-5 fires + bars_since
# ============================================================

def _precompute_bulkowski_fires(df_12h: pd.DataFrame) -> dict:
    """Для каждого из top-5 паттернов: бинарный массив fired[i] + bars_since[i]."""
    print('  precomputing Bulkowski top-5 fires...')
    # df_12h в etap_172 ожидает колонку 'time'. У нас индекс = time.
    df_for_det = df_12h.reset_index()
    if 'time' not in df_for_det.columns:
        df_for_det = df_for_det.rename(columns={df_for_det.columns[0]: 'time'})

    out = {}
    for name, detector in BULKOWSKI_DETECTORS.items():
        fired = np.zeros(len(df_12h), dtype=int)
        for i in range(_etap172.LOOKBACK + _etap172.SWING_N + 2, len(df_12h)):
            sig = detector(df_for_det, i)
            if sig is not None:
                fired[i] = 1
        # bars_since: декрементивный отсчёт от последнего fire'a, кэп BARS_SINCE_CAP
        bars_since = np.full(len(df_12h), BARS_SINCE_CAP, dtype=int)
        last_fire = -10000
        for i in range(len(df_12h)):
            if fired[i]:
                last_fire = i
            bs = min(i - last_fire, BARS_SINCE_CAP) if last_fire >= 0 else BARS_SINCE_CAP
            bars_since[i] = bs
        out[name] = {'fired': fired, 'bars_since': bars_since}
        print(f'    {name}: {fired.sum()} fires')
    return out


# ============================================================
# Главный augmenter
# ============================================================

def augment_dataset(ds_base: pd.DataFrame, df_12h: pd.DataFrame, df_1m: pd.DataFrame) -> pd.DataFrame:
    """Добавляем Vadim + Bulkowski колонки к etap_171 base."""
    # === GROUP A: zone-sweep ===
    print('Building GROUP A (Vadim zone-sweep features)...')
    df_1h = load_df(SYMBOL, '1h')
    df_1h = df_1h[(df_1h.index >= START_DATE) & (df_1h.index <= TEST_END)].copy()
    zones_by_kind = _precompute_vadim_zones(df_1h)
    first_swept = {}  # state: (kind, tf, idx) -> ts_first_swept
    # Группируем по (kind, tf, dir)
    zones_grouped = {}
    for (kind, tf, dir_), zlist in zones_by_kind.items():
        zones_grouped[(kind, tf, dir_)] = zlist

    # iterate по каждому 12h бару, генерим A-фичи
    a_rows = []
    df_12h_idx_list = df_12h.index.tolist()
    for i in range(len(df_12h)):
        feats = _sweep_features_at_bar(zones_grouped, df_12h, i, first_swept)
        feats['time'] = df_12h_idx_list[i]
        a_rows.append(feats)
    a_df = pd.DataFrame(a_rows)
    a_df['time'] = pd.to_datetime(a_df['time'], utc=True)
    print(f'  GROUP A: {a_df.shape[1]-1} features')

    # === GROUP B: maxV C2 ===
    print('Building GROUP B (Vadim maxV C2)...')
    maxv_s = _precompute_maxv_series(df_12h, df_1m)
    maxv_prev = maxv_s.shift(1)  # maxV(i-1)
    b_rows = []
    for i in range(len(df_12h)):
        ts = df_12h.index[i]
        mv_prev = maxv_prev.iloc[i] if not np.isnan(maxv_prev.iloc[i]) else None
        cur_high = df_12h['high'].iloc[i]; cur_low = df_12h['low'].iloc[i]
        cur_close = df_12h['close'].iloc[i]
        if mv_prev is None or np.isnan(mv_prev):
            sweep_hh = 0; sweep_ll = 0; dist_pct = 20.0; align = 0
        else:
            sweep_hh = int((cur_high > mv_prev) and (cur_close < mv_prev))
            sweep_ll = int((cur_low < mv_prev) and (cur_close > mv_prev))
            dist_pct = abs(cur_close - mv_prev) / cur_close * 100
            dist_pct = min(dist_pct, 20.0)
            # alignment: maxV выше close -> потенциально SHORT-side; ниже -> LONG
            align = 1 if mv_prev > cur_close else (-1 if mv_prev < cur_close else 0)
        b_rows.append({
            'time': ts,
            'vad_maxV_sweep_HH': sweep_hh,
            'vad_maxV_sweep_LL': sweep_ll,
            'vad_dist_maxV_prev_pct': dist_pct,
            'vad_maxV_align': align,
        })
    b_df = pd.DataFrame(b_rows)
    b_df['time'] = pd.to_datetime(b_df['time'], utc=True)
    print(f'  GROUP B: 4 features')

    # === GROUP D: composite Sniper flags ===
    print('Building GROUP D (Vadim Sniper composite flags)...')
    # HH Sniper: vad_sweep_FH_<any>_SHORT[i] AND vad_sweep_OB_<any>_SHORT[i] AND maxV_sweep_HH[i]
    # LL Sniper: симметрично
    ab_df = a_df.merge(b_df, on='time', how='left')
    fh_cols = [c for c in ab_df.columns if c.startswith('vad_sweep_FH_') and c.endswith('_SHORT')]
    ob_short_cols = [c for c in ab_df.columns if c.startswith('vad_sweep_OB_') and c.endswith('_SHORT')]
    fl_cols = [c for c in ab_df.columns if c.startswith('vad_sweep_FL_') and c.endswith('_LONG')]
    ob_long_cols = [c for c in ab_df.columns if c.startswith('vad_sweep_OB_') and c.endswith('_LONG')]

    sweep_fh_any = ab_df[fh_cols].any(axis=1).astype(int) if fh_cols else 0
    sweep_ob_short_any = ab_df[ob_short_cols].any(axis=1).astype(int) if ob_short_cols else 0
    sweep_fl_any = ab_df[fl_cols].any(axis=1).astype(int) if fl_cols else 0
    sweep_ob_long_any = ab_df[ob_long_cols].any(axis=1).astype(int) if ob_long_cols else 0

    ab_df['vad_sniper_HH'] = ((sweep_fh_any & sweep_ob_short_any & ab_df['vad_maxV_sweep_HH']).astype(int)
                              if isinstance(sweep_fh_any, pd.Series) else 0)
    ab_df['vad_sniper_LL'] = ((sweep_fl_any & sweep_ob_long_any & ab_df['vad_maxV_sweep_LL']).astype(int)
                              if isinstance(sweep_fl_any, pd.Series) else 0)
    # Core (мягче): любой sweep HTF zone AND maxV sweep
    ab_df['vad_core_HH'] = (((sweep_fh_any | sweep_ob_short_any) & ab_df['vad_maxV_sweep_HH']).astype(int)
                            if isinstance(sweep_fh_any, pd.Series) else 0)
    ab_df['vad_core_LL'] = (((sweep_fl_any | sweep_ob_long_any) & ab_df['vad_maxV_sweep_LL']).astype(int)
                            if isinstance(sweep_fl_any, pd.Series) else 0)
    print(f'  GROUP D: 4 features (sniper_HH, sniper_LL, core_HH, core_LL)')

    # === GROUP E: Bulkowski top-5 ===
    print('Building GROUP E (Bulkowski top-5 fires)...')
    bulk = _precompute_bulkowski_fires(df_12h)
    e_rows = []
    for i in range(len(df_12h)):
        rec = {'time': df_12h.index[i]}
        for name in BULKOWSKI_TOP5:
            rec[f'bulk_fired_{name}'] = int(bulk[name]['fired'][i])
            rec[f'bulk_bars_since_{name}'] = int(bulk[name]['bars_since'][i])
        e_rows.append(rec)
    e_df = pd.DataFrame(e_rows)
    e_df['time'] = pd.to_datetime(e_df['time'], utc=True)
    print(f'  GROUP E: 10 features (5 fires + 5 bars_since)')

    # === merge ===
    ds_base['time'] = pd.to_datetime(ds_base['time'], utc=True)
    ds_full = ds_base.merge(ab_df, on='time', how='left')
    ds_full = ds_full.merge(e_df, on='time', how='left')
    print(f'Augmented dataset: {ds_full.shape[1]} cols × {len(ds_full)} rows')
    return ds_full


# ============================================================
# MAIN
# ============================================================

def main():
    print('=' * 70)
    print('etap_173: Vadim 12h-fractal-predictor + Bulkowski integration')
    print('Base: etap_171 (270 features). +Vadim sweeps (8+4+4) + Bulkowski (10) = ~296')
    print('=' * 70)
    print()

    t0 = time.time()
    print('Loading data...')
    df_1h = load_df(SYMBOL, '1h')
    df_1d = load_df(SYMBOL, '1d')
    df_12h = compose_from_base(df_1h, '12h')
    df_4h = compose_from_base(df_1h, '4h')
    df_2h = compose_from_base(df_1h, '2h')
    cl, ch = START_DATE, TEST_END
    df_1h_w = df_1h[(df_1h.index >= cl) & (df_1h.index <= ch)].copy()
    df_1d_w = df_1d[(df_1d.index >= cl) & (df_1d.index <= ch)].copy()
    df_12h_w = df_12h[(df_12h.index >= cl) & (df_12h.index <= ch)].copy()
    df_4h_w = df_4h[(df_4h.index >= cl) & (df_4h.index <= ch)].copy()
    df_2h_w = df_2h[(df_2h.index >= cl) & (df_2h.index <= ch)].copy()
    print(f'  12h: {df_12h_w.index[0]} -> {df_12h_w.index[-1]}  ({len(df_12h_w)} bars)')

    # USDT.D 1d
    df_usdtd_1d = None
    usdtd_path = _ROOT / 'data' / 'USDT_D_1d.csv'
    if usdtd_path.exists():
        df_usdtd_1d = pd.read_csv(usdtd_path, index_col=0, parse_dates=True)
        if df_usdtd_1d.index.tz is None:
            df_usdtd_1d.index = df_usdtd_1d.index.tz_localize('UTC')
        df_usdtd_1d = df_usdtd_1d[(df_usdtd_1d.index >= cl) & (df_usdtd_1d.index <= ch)]
        print(f'  USDT.D 1d: {len(df_usdtd_1d)} bars')

    # 1m для maxV
    print('  loading 1m for maxV C2...')
    df_1m = pd.read_csv(_ROOT / 'data' / 'BTCUSDT_1m.csv',
                        parse_dates=['open_time'], index_col='open_time')
    if df_1m.index.tz is None:
        df_1m.index = df_1m.index.tz_localize('UTC')
    df_1m = df_1m[(df_1m.index >= cl) & (df_1m.index <= ch)].sort_index()
    print(f'  1m: {len(df_1m)} bars  ({time.time()-t0:.1f}s)')
    print()

    # === Base 270 фич ===
    print('Building etap_171 base dataset (270 features)...')
    t1 = time.time()
    ds_base = build_dataset_base(df_12h_w, df_1d_w, df_4h_w, df_2h_w, df_1h_w, df_usdtd_1d)
    ds_base['time'] = pd.to_datetime(ds_base['time'], utc=True)
    print(f'  built {len(ds_base)} samples × {ds_base.shape[1]} cols in {time.time()-t1:.1f}s')
    print()

    # === Augment ===
    ds = augment_dataset(ds_base, df_12h_w, df_1m)
    print()

    # === Split ===
    train_df = ds[ds['time'] < TRAIN_END].copy()
    test_df = ds[ds['time'] >= TRAIN_END].copy()
    print(f'TRAIN: {len(train_df)}  ({train_df["time"].min()} -> {train_df["time"].max()})')
    print(f'TEST:  {len(test_df)}   ({test_df["time"].min()} -> {test_df["time"].max()})')
    print()

    # === Feature set ===
    drop = ['time','close','high','low','is_low_fractal','is_high_fractal',
            'move_after_low_pct','move_after_high_pct'] + \
           [f'y_low_strong_{int(t)}' for t in TARGETS] + \
           [f'y_high_strong_{int(t)}' for t in TARGETS]
    feat_cols = [c for c in ds.columns if c not in drop]
    n_new_vadim = sum(1 for c in feat_cols if c.startswith('vad_'))
    n_new_bulk = sum(1 for c in feat_cols if c.startswith('bulk_'))
    print(f'Features: {len(feat_cols)}  '
          f'(base ≈ {len(feat_cols)-n_new_vadim-n_new_bulk}, Vadim {n_new_vadim}, Bulkowski {n_new_bulk})')
    print()

    X_train = train_df[feat_cols].fillna(0).values
    X_test = test_df[feat_cols].fillna(0).values

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score
    from sklearn.model_selection import KFold

    out_dir = _ROOT / 'research' / 'elements_study' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)

    # === Sample weights = uniqueness × |return| (Lopez Ch 4) ===
    log_close = np.log(df_12h_w['close'])
    future_ret = (log_close.shift(-14) - log_close).abs().fillna(0)
    sample_w_df = pd.DataFrame({'time': df_12h_w.index, 'w': future_ret.values})
    sample_w_df['time'] = pd.to_datetime(sample_w_df['time'], utc=True)
    train_df_with_w = train_df.merge(sample_w_df, on='time', how='left')
    sample_weights = train_df_with_w['w'].fillna(0).values
    sample_weights = sample_weights / max(sample_weights.mean(), 1e-9)

    # === Purged K-Fold CV (embargo=14) ===
    def purged_kfold_cv(X, y, sample_w, n_splits=5, embargo=14):
        kf = KFold(n_splits=n_splits, shuffle=False)
        aucs = []
        for fold, (train_idx, val_idx) in enumerate(kf.split(X)):
            # Embargo: вырезать ±embargo вокруг val из train
            val_start, val_end = val_idx[0], val_idx[-1]
            tr_keep = [i for i in train_idx
                       if i < val_start - embargo or i > val_end + embargo]
            tr_keep = np.array(tr_keep, dtype=int)
            if len(tr_keep) < 100:
                continue
            clf = GradientBoostingClassifier(n_estimators=200, max_depth=3,
                                              learning_rate=0.05, random_state=42)
            clf.fit(X[tr_keep], y[tr_keep], sample_weight=sample_w[tr_keep])
            y_val = y[val_idx]
            if len(np.unique(y_val)) < 2:
                continue
            p_val = clf.predict_proba(X[val_idx])[:, 1]
            aucs.append(roc_auc_score(y_val, p_val))
        return np.array(aucs)

    summary_rows = []
    fi_rows = []
    print('Training per target (Purged K-Fold + Hold-out)...')
    for target in [f'y_low_strong_{int(t)}' for t in TARGETS] + \
                  [f'y_high_strong_{int(t)}' for t in TARGETS]:
        y_train = train_df[target].values
        y_test = test_df[target].values
        baseline = y_train.mean() * 100

        # Purged CV
        cv_aucs = purged_kfold_cv(X_train, y_train, sample_weights, n_splits=5, embargo=14)
        cv_mean = float(cv_aucs.mean()) if len(cv_aucs) else float('nan')
        cv_std = float(cv_aucs.std()) if len(cv_aucs) else float('nan')

        # Hold-out
        clf = GradientBoostingClassifier(n_estimators=200, max_depth=3,
                                          learning_rate=0.05, random_state=42)
        clf.fit(X_train, y_train, sample_weight=sample_weights)
        p_test = clf.predict_proba(X_test)[:, 1]
        if len(np.unique(y_test)) >= 2:
            ho_auc = roc_auc_score(y_test, p_test)
            ho_brier = brier_score_loss(y_test, p_test)
            ho_ap = average_precision_score(y_test, p_test)
        else:
            ho_auc = ho_brier = ho_ap = float('nan')

        summary_rows.append({
            'target': target,
            'train_n': len(train_df), 'test_n': len(test_df),
            'baseline_pos_pct': baseline,
            'purged_cv_auc_mean': cv_mean,
            'purged_cv_auc_std': cv_std,
            'holdout_auc': ho_auc,
            'brier': ho_brier,
            'ap': ho_ap,
        })

        # Save predictions
        pred = test_df[['time','close','high','low',target]].copy()
        pred['p_hit'] = p_test
        pred.to_csv(out_dir / f'etap_173_pred_{target}.csv', index=False)

        # Feature importance per target
        imp = pd.Series(clf.feature_importances_, index=feat_cols).sort_values(ascending=False)
        for rank, (fname, val) in enumerate(imp.head(30).items(), 1):
            fi_rows.append({'target': target, 'rank': rank, 'feature': fname, 'importance': float(val)})

        print(f'  {target}: CV {cv_mean:.4f}±{cv_std:.4f}  HO {ho_auc:.4f}  '
              f'Brier {ho_brier:.4f}  AP {ho_ap:.4f}  '
              f'(baseline {baseline:.2f}%)')

    # Save
    pd.DataFrame(summary_rows).to_csv(out_dir / 'etap_173_summary.csv', index=False)
    pd.DataFrame(fi_rows).to_csv(out_dir / 'etap_173_feature_importance.csv', index=False)

    print()
    print('=' * 70)
    print('SUMMARY vs etap_171:')
    print('=' * 70)
    # Загружаем etap_171 summary для сравнения
    e171_path = out_dir / 'etap_171_summary.csv'
    if e171_path.exists():
        e171 = pd.read_csv(e171_path)
        e173 = pd.DataFrame(summary_rows)
        merged = e171.merge(e173, on='target', suffixes=('_171', '_173'))
        print(f"{'target':<20} {'AUC_171':>8} {'AUC_173':>8} {'Δ':>8}   {'CV_171':>10} {'CV_173':>10}")
        print('-' * 80)
        for _, r in merged.iterrows():
            d = r['holdout_auc_173'] - r['holdout_auc_171']
            print(f"{r['target']:<20} {r['holdout_auc_171']:>8.4f} {r['holdout_auc_173']:>8.4f} "
                  f"{d:>+8.4f}   {r['purged_cv_auc_mean_171']:>6.4f}±{r['purged_cv_auc_std_171']:.3f} "
                  f"{r['purged_cv_auc_mean_173']:>6.4f}±{r['purged_cv_auc_std_173']:.3f}")
    print()
    print(f'Done in {time.time()-t0:.1f}s')
    print('=' * 70)


if __name__ == '__main__':
    main()
