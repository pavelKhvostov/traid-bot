"""etap_162: Аудит честности модели etap_161 — есть ли lookahead?

Тест: для 5 случайных OOS-свечей пересчитать ВСЕ фичи, обрезав датасет
ровно до их close. Затем сравнить с фичами из etap_161 (где df весь
исторический + будущий).

Если фичи совпадают → модель честная.
Если различаются → нашли lookahead source.

Особое внимание:
  - HTF Hull asof — берёт ли значение 1d/4h свечи, чей close ещё не известен?
  - rolling/ewm индикаторы — пересчёт в момент close дает то же?
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

START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
TEST_END = pd.Timestamp("2026-05-31", tz="UTC")

def rsi_wilder(s, n=14):
    d = s.diff(); g = d.clip(lower=0); l = (-d).clip(lower=0)
    ag = g.ewm(alpha=1/n, adjust=False).mean()
    al = l.ewm(alpha=1/n, adjust=False).mean()
    rs = ag/al.replace(0, np.nan)
    return 100 - 100/(1+rs)

def _wma(v, n):
    w = np.arange(1, n+1, dtype=float)
    o = np.full(len(v), np.nan)
    for i in range(n-1, len(v)):
        o[i] = np.dot(v[i-n+1:i+1], w) / w.sum()
    return o

def hull_ma(s, n=78):
    h = n//2; sq = int(np.sqrt(n))
    raw = 2*_wma(s.values, h) - _wma(s.values, n)
    return pd.Series(_wma(pd.Series(raw).fillna(0).values, sq), index=s.index)

def ema(s, n=200): return s.ewm(span=n, adjust=False).mean()

def atr(df, n=14):
    h,l,c = df['high'],df['low'],df['close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def main():
    print("="*70)
    print("etap_162: Honesty audit — full df vs truncated to candle close")
    print("="*70)
    print()

    df_1h = load_df('BTCUSDT', '1h')
    df_1d = load_df('BTCUSDT', '1d')
    df_12h_full = compose_from_base(df_1h, '12h')
    df_4h_full = compose_from_base(df_1h, '4h')

    df_1h = df_1h[(df_1h.index >= START_DATE) & (df_1h.index <= TEST_END)]
    df_1d = df_1d[(df_1d.index >= START_DATE) & (df_1d.index <= TEST_END)]
    df_12h_full = df_12h_full[(df_12h_full.index >= START_DATE) & (df_12h_full.index <= TEST_END)]
    df_4h_full = df_4h_full[(df_4h_full.index >= START_DATE) & (df_4h_full.index <= TEST_END)]

    # Пересчитаем индикаторы на ПОЛНОМ датасете
    rsi_full = rsi_wilder(df_12h_full['close'], 14)
    hull_12h_full = hull_ma(df_12h_full['close'], 78)
    hull_1d_full = hull_ma(df_1d['close'], 20)
    hull_4h_full = hull_ma(df_4h_full['close'], 78)
    ema_full = ema(df_12h_full['close'], 200)
    atr_full = atr(df_12h_full, 14)

    # Тест-точки: пользовательские примеры + 5 случайных свечей
    test_points = [
        '2026-02-06 00:00',
        '2026-02-08 12:00',
        '2026-03-17 00:00',
        '2026-03-29 12:00',
        '2026-05-06 00:00',
        '2025-06-15 12:00',
        '2025-09-20 00:00',
        '2026-01-15 12:00',
    ]

    print(f'{"timestamp":<22} {"feature":<25} {"FULL_df":>12} {"TRUNCATED":>12} {"diff":>10}  {"verdict"}')
    print('-'*110)

    any_leak = False

    for ts_str in test_points:
        ts = pd.Timestamp(ts_str, tz='UTC')
        if ts not in df_12h_full.index:
            print(f'{ts_str}: NOT IN INDEX, skip')
            continue

        # === FULL DF ===
        rsi_full_val = rsi_full.loc[ts]
        hull_12h_full_val = hull_12h_full.loc[ts]
        ema_full_val = ema_full.loc[ts]
        atr_full_val = atr_full.loc[ts]

        # HTF asof из полного df (как в etap_161)
        h1d_full_asof = hull_1d_full.asof(ts)
        h1d_full_prev = hull_1d_full.asof(ts - pd.Timedelta(days=3))
        htf1d_full = 1 if h1d_full_asof > h1d_full_prev else -1

        h4h_full_asof = hull_4h_full.asof(ts)
        h4h_full_prev = hull_4h_full.asof(ts - pd.Timedelta(hours=12))
        htf4h_full = 1 if h4h_full_asof > h4h_full_prev else -1

        # === TRUNCATED — только данные с close ≤ ts ===
        # Для 12h-свечи с open=ts (например 2026-02-06 00:00),
        # её close = ts + 12h. Значит мы знаем эту 12h свечу полностью.
        # Для 1h данных: знаем все 1h свечи с open_time + 1h ≤ ts + 12h, т.е. open_time ≤ ts + 11h
        # Для 1d: знаем 1d свечи с close ≤ ts+12h, т.е. open_time+1d ≤ ts+12h → open_time ≤ ts-12h
        close_ts_12h = ts + pd.Timedelta(hours=12)

        # Truncate 1h до полностью закрытых на момент close_ts_12h:
        # 1h candle [open, open+1h) закрылась если open+1h ≤ close_ts_12h
        df_1h_t = df_1h[df_1h.index <= close_ts_12h - pd.Timedelta(hours=1)]
        # Аналогично 1d (open+1d ≤ close_ts_12h)
        df_1d_t = df_1d[df_1d.index <= close_ts_12h - pd.Timedelta(days=1)]

        df_12h_t = compose_from_base(df_1h_t, '12h')
        df_4h_t = compose_from_base(df_1h_t, '4h')

        # Только полностью закрытые
        df_12h_t = df_12h_t[df_12h_t.index <= close_ts_12h - pd.Timedelta(hours=12)]
        df_4h_t = df_4h_t[df_4h_t.index <= close_ts_12h - pd.Timedelta(hours=4)]

        # Должна включать СВЕЧУ ts (она же закрылась)
        if ts not in df_12h_t.index:
            print(f'{ts_str}: candle not in truncated 12h, skip')
            continue

        rsi_t = rsi_wilder(df_12h_t['close'], 14).loc[ts]
        hull_12h_t = hull_ma(df_12h_t['close'], 78).loc[ts]
        ema_t = ema(df_12h_t['close'], 200).loc[ts]
        atr_t = atr(df_12h_t, 14).loc[ts]

        hull_1d_t = hull_ma(df_1d_t['close'], 20)
        h1d_t_asof = hull_1d_t.asof(ts)
        h1d_t_prev = hull_1d_t.asof(ts - pd.Timedelta(days=3))
        htf1d_t = 1 if (pd.notna(h1d_t_asof) and pd.notna(h1d_t_prev) and h1d_t_asof > h1d_t_prev) else -1

        hull_4h_t = hull_ma(df_4h_t['close'], 78)
        h4h_t_asof = hull_4h_t.asof(ts)
        h4h_t_prev = hull_4h_t.asof(ts - pd.Timedelta(hours=12))
        htf4h_t = 1 if (pd.notna(h4h_t_asof) and pd.notna(h4h_t_prev) and h4h_t_asof > h4h_t_prev) else -1

        # Сравнение
        checks = [
            ('rsi_14',          rsi_full_val,       rsi_t),
            ('hull_12h_78',     hull_12h_full_val,  hull_12h_t),
            ('ema_200',         ema_full_val,       ema_t),
            ('atr_14',          atr_full_val,       atr_t),
            ('hull_1d_asof',    h1d_full_asof,      h1d_t_asof),
            ('hull_4h_asof',    h4h_full_asof,      h4h_t_asof),
            ('htf_1d_dir',      htf1d_full,         htf1d_t),
            ('htf_4h_dir',      htf4h_full,         htf4h_t),
        ]
        for name, f, t in checks:
            if pd.isna(f) and pd.isna(t):
                continue
            if pd.isna(f) or pd.isna(t):
                print(f'{ts_str:<22} {name:<25} {f!s:>12} {t!s:>12}  one-NaN  ⚠ LEAK?')
                any_leak = True
                continue
            diff = abs(f - t)
            rel = diff / (abs(f) + 1e-9)
            verdict = 'OK ✓' if rel < 1e-6 else f'⚠ LEAK rel={rel:.4%}'
            if rel >= 1e-6: any_leak = True
            print(f'{ts_str:<22} {name:<25} {f:>12.4f} {t:>12.4f} {diff:>10.4f}  {verdict}')
        print()

    print('='*70)
    if any_leak:
        print('⚠ LOOKAHEAD ДЕТЕКТИРОВАН — фичи отличаются между full и truncated df')
        print('  Значит модель etap_161 НЕ ЧЕСТНАЯ — использует будущие данные.')
    else:
        print('✓ Модель ЧЕСТНАЯ — все фичи идентичны в full и truncated df')
    print('='*70)


if __name__ == '__main__':
    main()
