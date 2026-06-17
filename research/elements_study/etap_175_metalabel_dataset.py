"""etap_175: кросс-актив датасет для META-СЕЛЕКТОРА (фундамент нейро-модуля).

Архитектура (выбор пользователя 2026-06-09): ГИБРИД пивот → PnL-фильтр,
старт LightGBM, данные BTC+ETH+SOL.

Этот этап = ФУНДАМЕНТ (Stage A + лейблы). Дальше:
  etap_176 = LightGBM-селектор на этих лейблах + ворота etap_174.
  etap_177 = TCN-эмбеддинг (если упрёмся в потолок).

ЧТО ДЕЛАЕТ:
  Stage A (кандидаты-пивоты, без обучения, computable на любом активе):
    • failed-sweep rule (доминантная фича etap_167, importance ~0.36):
        LONG  = свеча сняла недавний SSL (low) и закрылась обратно ВЫШЕ него.
        SHORT = сняла BSL (high) и закрылась обратно НИЖЕ.
    • Bulkowski reversal-детекторы (etap_172): long+short.
  Union → точки-кандидаты (time, side, sources).

  Лейблы = triple-barrier с РЕАЛЬНЫМИ издержками (движок etap_174):
    вход на close 12h breakout-свечи (market), SL=1.5×ATR(14,12h),
    TP=RR×SL, timeout 14×12h=7д, разрешение SL-vs-TP на 1h (SL первым).
    Издержки: taker 0.05%+slip 0.03%/сторону + funding 0.01%/8h.
    Пишем net_R при policy RR=2 + флаги hit_rr1/2/3 + MFE/MAE в R.

  Фичи = компактный снимок (~28 топ-importance из etap_173): sweep, структура
    свечи, ATR/vol-режим, EMA-тренд, pre-returns, дистанция до swing, USDT.D,
    time-of-day, сила primary-сигнала. Всё ≤ i — без lookahead.

Output: output/etap_175_labeled.csv  (одна строка = кандидат)
        + печать baseline (unfiltered) win% / mean net_R — планка для селектора.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from data_manager import load_df, compose_from_base
from etap_172_bulkowski_patterns import DETECTORS, LOOKBACK, SWING_N

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")   # общий потолок (ETH/SOL до 04-30)
TEST_START = pd.Timestamp("2025-01-01", tz="UTC")

# --- издержки (как etap_174) ---
SIDE_COST = 0.0005 + 0.0003       # taker + slippage / сторону
FUNDING_PER_8H = 0.0001

# --- execution policy для лейбла ---
ATR_LEN = 14
SL_ATR_MULT = 1.5
LABEL_RR = 2.0                    # основной net_R считаем при RR=2
MAX_HOLD_12H = 14                # 7 дней
SWEEP_W = 10                     # окно поиска ликвидности (5 дней)


def wilder_atr(h, l, c, n=ATR_LEN):
    prev = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().values


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def confirmed_swings_last(highs, lows, i, lookback, n=2):
    """Последние confirmed swing high/low до бара i (исключая незакрытые справа)."""
    lo = max(0, i - lookback)
    last_sh = last_sl = None
    for j in range(lo + n, i - n + 1):
        hh = highs[j]
        if all(hh > highs[j - k] for k in range(1, n + 1)) and \
           all(hh > highs[j + k] for k in range(1, n + 1)):
            last_sh = (j, hh)
        ll = lows[j]
        if all(ll < lows[j - k] for k in range(1, n + 1)) and \
           all(ll < lows[j + k] for k in range(1, n + 1)):
            last_sl = (j, ll)
    return last_sh, last_sl


def build_features(df12, usdtd_ret_by_date):
    """Предрасчёт всех колонок-фич на 12h df. Возвращает dict массивов."""
    o = df12['open'].values.astype(float)
    h = df12['high'].values.astype(float)
    l = df12['low'].values.astype(float)
    c = df12['close'].values.astype(float)
    v = df12['volume'].values.astype(float)
    t = df12['time'].values
    n = len(c)

    atr = wilder_atr(h, l, c)
    ema200 = ema(c, 200)
    ema50 = ema(c, 50)
    rng = np.maximum(h - l, 1e-9)
    vol_mean20 = pd.Series(v).rolling(20).mean().values
    vol_std20 = pd.Series(v).rolling(20).std().values

    F = {
        'close_pos_in_range': (c - l) / rng,
        'body_pct': np.abs(c - o) / rng,
        'upper_wick_pct': (h - np.maximum(o, c)) / rng,
        'lower_wick_pct': (np.minimum(o, c) - l) / rng,
        'range_vs_atr': rng / np.maximum(atr, 1e-9),
        'atr_pct': atr / c * 100,
        'vol_z20': (v - vol_mean20) / np.maximum(vol_std20, 1e-9),
        'ema200_dist_pct': (c - ema200) / ema200 * 100,
        'ema50_slope_pct': np.concatenate([np.zeros(3), (ema50[3:] - ema50[:-3]) / ema50[:-3] * 100]),
        'pre_3d_ret_pct': np.concatenate([np.zeros(6), (c[6:] - c[:-6]) / c[:-6] * 100]),
        'pre_7d_ret_pct': np.concatenate([np.zeros(14), (c[14:] - c[:-14]) / c[:-14] * 100]),
    }
    # USDT.D дневной возврат, выровнено по дате бара
    dates = pd.to_datetime(t).normalize()
    F['usdtd_1d_ret_pct'] = np.array([usdtd_ret_by_date.get(d, 0.0) for d in dates])
    # time-of-day
    F['hour_utc'] = pd.to_datetime(t).hour.values.astype(float)
    F['dow'] = pd.to_datetime(t).dayofweek.values.astype(float)
    return o, h, l, c, atr, F, n


def detect_failed_sweep(h, l, c, i, w=SWEEP_W):
    """Возвращает (long_sig, short_sig, feats) для бара i."""
    lo = max(0, i - w)
    if lo >= i:
        return False, False, {}
    prior_low = l[lo:i].min()
    prior_high = h[lo:i].max()
    swept_ssl = l[i] < prior_low
    swept_bsl = h[i] > prior_high
    failed_ssl = swept_ssl and c[i] > prior_low       # reclaim → LONG
    failed_bsl = swept_bsl and c[i] < prior_high       # reclaim → SHORT
    sweep_ssl_mag = (prior_low - l[i]) / c[i] * 100 if swept_ssl else 0.0
    sweep_bsl_mag = (h[i] - prior_high) / c[i] * 100 if swept_bsl else 0.0
    feats = {
        'swept_ssl': int(swept_ssl), 'swept_bsl': int(swept_bsl),
        'failed_ssl': int(failed_ssl), 'failed_bsl': int(failed_bsl),
        'sweep_ssl_mag_pct': sweep_ssl_mag, 'sweep_bsl_mag_pct': sweep_bsl_mag,
    }
    return failed_ssl, failed_bsl, feats


def simulate_label(side, entry, atr_at, h1, l1, c1, t1_ns, t_close_ns):
    """Triple-barrier с издержками на 1h. SL=1.5ATR, считаем исходы для RR1/2/3
    + net_R при RR=LABEL_RR + MFE/MAE."""
    if atr_at <= 0:
        return None
    risk = SL_ATR_MULT * atr_at
    risk_pct = risk / entry
    sl = entry - risk if side == 'long' else entry + risk
    start = int(np.searchsorted(t1_ns, t_close_ns, side='left'))
    if start >= len(c1):
        return None
    end = min(start + MAX_HOLD_12H * 12, len(c1))

    tps = {rr: (entry + risk * rr if side == 'long' else entry - risk * rr)
           for rr in (1.0, 2.0, 3.0)}
    hit = {1.0: None, 2.0: None, 3.0: None}
    sl_i = None
    mfe = 0.0; mae = 0.0
    for k in range(start, end):
        hi = h1[k]; lo = l1[k]
        if side == 'long':
            mfe = max(mfe, (hi - entry) / risk)
            mae = min(mae, (lo - entry) / risk)
            sl_now = lo <= sl
        else:
            mfe = max(mfe, (entry - lo) / risk)
            mae = min(mae, (entry - hi) / risk)
            sl_now = hi >= sl
        for rr, tp in tps.items():
            if hit[rr] is None:
                tp_now = (hi >= tp) if side == 'long' else (lo <= tp)
                if tp_now:
                    hit[rr] = k
        if sl_now and sl_i is None:
            sl_i = k
        # стоп закрывает все недостигнутые TP
        if sl_i is not None:
            break
    # исход для policy RR=LABEL_RR (SL первым при равенстве бара)
    tp_i = hit[LABEL_RR]
    if sl_i is not None and (tp_i is None or sl_i <= tp_i):
        gross_R = -1.0; outcome = 'sl'; exit_i = sl_i
    elif tp_i is not None:
        gross_R = LABEL_RR; outcome = 'tp'; exit_i = tp_i
    else:
        exit_i = end - 1
        px = c1[exit_i]
        gross_R = ((px - entry) if side == 'long' else (entry - px)) / risk
        outcome = 'timeout'
    hours = max(1, exit_i - start + 12)
    cost_pct = 2 * SIDE_COST + FUNDING_PER_8H * (hours / 8.0)
    net_R = gross_R - cost_pct / risk_pct
    return {
        'risk_pct': risk_pct * 100, 'outcome': outcome,
        'gross_R': gross_R, 'net_R': net_R, 'bars_held_1h': exit_i - start,
        'win': int(net_R > 0),
        'hit_rr1': int(hit[1.0] is not None and (sl_i is None or hit[1.0] <= sl_i)),
        'hit_rr2': int(hit[2.0] is not None and (sl_i is None or hit[2.0] <= sl_i)),
        'hit_rr3': int(hit[3.0] is not None and (sl_i is None or hit[3.0] <= sl_i)),
        'mfe_R': mfe, 'mae_R': mae,
    }


def process_symbol(sym, usdtd_ret_by_date):
    df1 = load_df(sym, "1h")
    df1 = df1[(df1.index >= START_DATE) & (df1.index <= END_DATE)].copy()
    df12 = compose_from_base(df1, "12h")
    df12 = df12[(df12.index >= START_DATE) & (df12.index <= END_DATE)].copy().reset_index()
    if 'time' not in df12.columns:
        df12 = df12.rename(columns={df12.columns[0]: 'time'})

    o, h, l, c, atr, F, n = build_features(df12, usdtd_ret_by_date)
    times = df12['time']

    # 1h массивы для симуляции
    h1 = df1['high'].values.astype(float)
    l1 = df1['low'].values.astype(float)
    c1 = df1['close'].values.astype(float)
    t1_ns = df1.index.values.astype('datetime64[ns]').astype(np.int64)

    rows = []
    for i in range(LOOKBACK + SWING_N + 2, n - SWING_N):
        # Bulkowski
        bull = []; bear = []
        for det in DETECTORS:
            sig = det(df12, i)
            if sig is not None:
                (bull if sig['side'] == 'long' else bear).append(sig['pattern'])
        # failed-sweep
        fs_long, fs_short, fs_feats = detect_failed_sweep(h, l, c, i)

        cand_long = fs_long or len(bull) > 0
        cand_short = fs_short or len(bear) > 0
        if not (cand_long or cand_short):
            continue

        # последние swings для дистанции
        sh, sl_sw = confirmed_swings_last(h, l, i, LOOKBACK, SWING_N)
        dist_hi = (sh[1] - c[i]) / c[i] * 100 if sh else 0.0
        dist_lo = (c[i] - sl_sw[1]) / c[i] * 100 if sl_sw else 0.0

        base = {
            'symbol': sym, 'time': times.iloc[i], 'entry': c[i],
            'close_pos_in_range': F['close_pos_in_range'][i],
            'body_pct': F['body_pct'][i],
            'upper_wick_pct': F['upper_wick_pct'][i],
            'lower_wick_pct': F['lower_wick_pct'][i],
            'range_vs_atr': F['range_vs_atr'][i], 'atr_pct': F['atr_pct'][i],
            'vol_z20': F['vol_z20'][i],
            'ema200_dist_pct': F['ema200_dist_pct'][i],
            'ema50_slope_pct': F['ema50_slope_pct'][i],
            'pre_3d_ret_pct': F['pre_3d_ret_pct'][i],
            'pre_7d_ret_pct': F['pre_7d_ret_pct'][i],
            'usdtd_1d_ret_pct': F['usdtd_1d_ret_pct'][i],
            'hour_utc': F['hour_utc'][i], 'dow': F['dow'][i],
            'dist_swing_hi_pct': dist_hi, 'dist_swing_lo_pct': dist_lo,
            **fs_feats,
        }
        t_close_ns = (times.iloc[i] + pd.Timedelta(hours=12)).value

        for side, is_cand, n_bulk, from_fs in (
            ('long', cand_long, len(bull), fs_long),
            ('short', cand_short, len(bear), fs_short)):
            if not is_cand:
                continue
            lab = simulate_label(side, c[i], atr[i], h1, l1, c1, t1_ns, t_close_ns)
            if lab is None:
                continue
            rec = dict(base)
            rec['side_long'] = 1 if side == 'long' else 0
            rec['n_bulkowski'] = n_bulk
            rec['from_failed_sweep'] = int(bool(from_fs))
            rec['period'] = 'test' if times.iloc[i] >= TEST_START else 'train'
            rec.update(lab)
            rows.append(rec)
    return rows


def main():
    t0 = time.time()
    print("=" * 74)
    print("etap_175: кросс-актив meta-label датасет (Stage A + triple-barrier+costs)")
    print("=" * 74)

    # USDT.D дневной возврат (CSV имеет колонку 'datetime', не 'open_time')
    ud = pd.read_csv(_ROOT / 'data' / 'USDT_D_1d.csv', parse_dates=['datetime'])
    ud_ret = ud['close'].pct_change().fillna(0) * 100
    usdtd_ret_by_date = {pd.Timestamp(d).normalize(): r
                         for d, r in zip(ud['datetime'], ud_ret.values)}

    all_rows = []
    for sym in SYMBOLS:
        print(f"\n[{sym}] ...")
        rows = process_symbol(sym, usdtd_ret_by_date)
        print(f"  кандидатов: {len(rows)}")
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    out = _ROOT / 'research' / 'elements_study' / 'output' / 'etap_175_labeled.csv'
    df.to_csv(out, index=False)

    print("\n" + "=" * 74)
    print("BASELINE (unfiltered) — планка, которую должен побить селектор")
    print("=" * 74)
    for split in ['train', 'test']:
        sub = df[df['period'] == split]
        print(f"\n{split}: n={len(sub)}")
        for grp, gd in [('ALL', sub), ('LONG', sub[sub.side_long == 1]),
                        ('SHORT', sub[sub.side_long == 0])]:
            if len(gd) == 0:
                continue
            print(f"  {grp:>6}: n={len(gd):>4}  win%={gd['win'].mean()*100:>5.1f}  "
                  f"mean net_R={gd['net_R'].mean():+.3f}  ΣR={gd['net_R'].sum():+.1f}")
    print(f"\n  по активам (test):")
    for sym in SYMBOLS:
        s = df[(df.symbol == sym) & (df.period == 'test')]
        if len(s):
            print(f"    {sym}: n={len(s):>4}  win%={s['win'].mean()*100:>5.1f}  "
                  f"meanR={s['net_R'].mean():+.3f}")
    print(f"\nSaved: {out}")
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == '__main__':
    main()
