"""etap_166: Аудит честности etap_165 (новые фичи).

Проверяем что новые фичи (USDT.D, sweep, block_orders) не имеют lookahead.
Воспроизводим расчёт фичей для одной test-свечи на full df и truncated df.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from data_manager import load_df, compose_from_base

def rsi_wilder(s, n=14):
    d = s.diff(); g = d.clip(lower=0); l = (-d).clip(lower=0)
    ag = g.ewm(alpha=1/n, adjust=False).mean(); al = l.ewm(alpha=1/n, adjust=False).mean()
    rs = ag/al.replace(0, np.nan); return 100 - 100/(1+rs)


def compute_features(df_12h, df_usdtd_1d, ts_i):
    """Расчёт критичных новых фичей на момент close 12h-свечи ts_i."""
    ts_close = ts_i + pd.Timedelta(hours=12)
    ts_lookup = ts_close

    # USDT.D 1d (HONEST: index сдвинут на close = +1d)
    if df_usdtd_1d is not None and not df_usdtd_1d.empty:
        ud_close = df_usdtd_1d['close'].copy()
        ud_close.index = ud_close.index + pd.Timedelta(days=1)
        ud_now = ud_close.asof(ts_lookup)
        ud_3d = ud_close.asof(ts_lookup - pd.Timedelta(days=3))
        usdtd_3d_ret = float((ud_now - ud_3d)/ud_3d*100) if pd.notna(ud_now) and pd.notna(ud_3d) and ud_3d else 0.0
    else:
        usdtd_3d_ret = 0.0
        ud_now = float('nan')

    # Sweep history (24h window = 2 12h bars)
    i = df_12h.index.get_loc(ts_i)
    win_bars = 2
    wl = max(0, i - win_bars)
    wd = df_12h.iloc[wl:i+1]  # включая i
    if len(wd) >= 2:
        prev = wd.iloc[:-1]
        prev_hi = float(prev['high'].max())
        prev_lo = float(prev['low'].min())
        cur_hi = float(df_12h['high'].iloc[i])
        cur_lo = float(df_12h['low'].iloc[i])
        cur_close = float(df_12h['close'].iloc[i])
        bsl_swept = int(cur_hi > prev_hi)
        bsl_mag = (cur_hi - prev_hi) / prev_hi * 100 if bsl_swept and prev_hi > 0 else 0
        bsl_failed = int(bsl_swept and cur_close < prev_hi)
    else:
        bsl_swept = bsl_mag = bsl_failed = 0
        prev_hi = prev_lo = float('nan')

    # Block orders (1d) — detect_block_orders pattern
    body_pct = (df_12h['close'] - df_12h['open']).abs() / (df_12h['high'] - df_12h['low']).replace(0, np.nan)
    vz = (df_12h['volume'] - df_12h['volume'].rolling(20).mean()) / df_12h['volume'].rolling(20).std()
    is_block_at_i = bool((body_pct.iloc[i] >= 0.7) and (vz.iloc[i] >= 2.0)) if i < len(body_pct) else False

    return {
        'ts_i': ts_i,
        'ts_close': ts_close,
        'usdtd_3d_ret': usdtd_3d_ret,
        'sweep_BSL_24h': bsl_swept,
        'sweep_BSL_mag_24h_pct': bsl_mag,
        'sweep_BSL_failed_24h': bsl_failed,
        'prev_hi_24h': prev_hi,
        'is_block_at_close': int(is_block_at_i),
        'vol_z_at_i': float(vz.iloc[i]) if i < len(vz) and pd.notna(vz.iloc[i]) else 0.0,
        'body_pct_at_i': float(body_pct.iloc[i]) if i < len(body_pct) and pd.notna(body_pct.iloc[i]) else 0.0,
    }


def main():
    print("="*70)
    print("etap_166: Honesty audit v3 — новые фичи etap_165")
    print("="*70)
    print()

    START = pd.Timestamp('2020-01-01', tz='UTC')
    END = pd.Timestamp('2026-05-31', tz='UTC')

    df_1h = load_df('BTCUSDT', '1h')
    df_1h = df_1h[(df_1h.index >= START) & (df_1h.index <= END)]
    df_12h_full = compose_from_base(df_1h, '12h')

    df_usdtd_full = pd.read_csv(_ROOT/'data'/'USDT_D_1d.csv', index_col=0, parse_dates=True)
    if df_usdtd_full.index.tz is None:
        df_usdtd_full.index = df_usdtd_full.index.tz_localize('UTC')
    df_usdtd_full = df_usdtd_full[(df_usdtd_full.index >= START) & (df_usdtd_full.index <= END)]

    points = [
        '2026-02-06 00:00',
        '2026-02-08 12:00',
        '2026-03-17 00:00',
        '2026-05-06 00:00',
        '2026-05-10 12:00',
        '2025-09-20 00:00',
    ]

    any_leak = False
    for ts_str in points:
        ts_i = pd.Timestamp(ts_str, tz='UTC')
        if ts_i not in df_12h_full.index:
            print(f'{ts_str}: not in index, skip'); continue
        ts_close = ts_i + pd.Timedelta(hours=12)

        # Truncated: 1h до close_ts_12h - 1h, потом compose 12h
        df_1h_t = df_1h[df_1h.index <= ts_close - pd.Timedelta(hours=1)]
        df_12h_t = compose_from_base(df_1h_t, '12h')
        df_12h_t = df_12h_t[df_12h_t.index <= ts_close - pd.Timedelta(hours=12)]
        df_usdtd_t = df_usdtd_full[df_usdtd_full.index <= ts_close - pd.Timedelta(days=1)]

        if ts_i not in df_12h_t.index:
            print(f'{ts_str}: not in truncated, skip'); continue

        f = compute_features(df_12h_full, df_usdtd_full, ts_i)
        t = compute_features(df_12h_t, df_usdtd_t, ts_i)
        print(f'### {ts_str}')
        for k in ['usdtd_3d_ret','sweep_BSL_24h','sweep_BSL_mag_24h_pct','sweep_BSL_failed_24h',
                  'prev_hi_24h','vol_z_at_i','body_pct_at_i','is_block_at_close']:
            fv = f[k]; tv = t[k]
            if isinstance(fv, float) and isinstance(tv, float):
                diff = abs(fv - tv)
                ok = diff < 1e-6
            else:
                ok = fv == tv
                diff = 0 if ok else 1
            mark = 'OK ✓' if ok else '⚠ LEAK'
            if not ok: any_leak = True
            print(f'  {k:<25} FULL={fv}  TRUNC={tv}  {mark}')
        print()

    print('='*70)
    if any_leak:
        print('⚠ ⚠ ⚠  LOOKAHEAD В НОВЫХ ФИЧАХ — модель etap_165 НЕ честная')
    else:
        print('✓ ✓ ✓  НОВЫЕ ФИЧИ ЧЕСТНЫЕ — etap_165 готова к live')
    print('='*70)


if __name__ == '__main__':
    main()
