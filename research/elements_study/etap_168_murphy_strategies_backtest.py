"""etap_168: Честный бэктест ВСЕХ ключевых стратегий и постулатов из книги
Джона Мерфи "Технический анализ фьючерсных рынков".

Каждая стратегия:
  - дает сигнал LONG/SHORT/None на close 12h-свечи (без lookahead)
  - вход на open следующей свечи (1 бар lag — реалистично для live)
  - SL = entry - 1.0 * ATR(14)  (для LONG; зеркально для SHORT)
  - TP = entry + 2.0 * ATR(14)  (RR=2.0)
  - Max hold = 14 баров 12h (7 дней)
  - Exit: SL hit / TP hit / max hold / opposite signal

Метрики: n_trades, win%, total_R, R/trade, max_DD_R, profit_factor.

Период тестирования: 2020-01-01 → 2026-05-30 (BTCUSDT 12h).
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
from dataclasses import dataclass

from data_manager import load_df, compose_from_base

SYMBOL = "BTCUSDT"
START = pd.Timestamp("2020-01-01", tz="UTC")
END = pd.Timestamp("2026-05-31", tz="UTC")
RR = 2.0
SL_ATR_MULT = 1.0
TP_ATR_MULT = SL_ATR_MULT * RR
MAX_HOLD_BARS = 14
ATR_LEN = 14


# ============================================================
# ИНДИКАТОРЫ
# ============================================================

def rsi(s, n=14):
    d = s.diff(); g = d.clip(lower=0); l = (-d).clip(lower=0)
    ag = g.ewm(alpha=1/n, adjust=False).mean(); al = l.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + ag/al.replace(0, np.nan))

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()

def atr(df, n=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def macd(s, fast=12, slow=26, sig=9):
    e1 = ema(s, fast); e2 = ema(s, slow)
    line = e1 - e2
    signal = ema(line, sig)
    hist = line - signal
    return line, signal, hist

def stochastic(df, k=14, d=3):
    h, l, c = df['high'], df['low'], df['close']
    hh = h.rolling(k).max(); ll = l.rolling(k).min()
    K = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    D = K.rolling(d).mean()
    return K, D

def momentum(s, n=10): return s - s.shift(n)


# ============================================================
# СТРАТЕГИИ — каждая возвращает Series сигналов (1=LONG, -1=SHORT, 0=none)
# ============================================================

def strat_01_sr_breakout(df, lookback=20, pct=3.0):
    """Прорыв S/R с подтверждением: close > HH(20) на +3% + 2 свечи подряд."""
    hh = df['high'].rolling(lookback).max().shift(1)  # без текущей
    ll = df['low'].rolling(lookback).min().shift(1)
    long_brk = (df['close'] > hh * (1 + pct/100))
    short_brk = (df['close'] < ll * (1 - pct/100))
    long_conf = long_brk & long_brk.shift(1)
    short_conf = short_brk & short_brk.shift(1)
    sig = pd.Series(0, index=df.index)
    sig[long_conf] = 1; sig[short_conf] = -1
    return sig

def strat_02_fib_retrace_50(df, lookback=30, tol=2.0):
    """Вход на 50% откате от impulse в направлении тренда (Hull20)."""
    h_max = df['high'].rolling(lookback).max().shift(1)
    l_min = df['low'].rolling(lookback).min().shift(1)
    mid50 = (h_max + l_min) / 2
    trend = ema(df['close'], 50)
    trend_up = df['close'] > trend
    close_near_50 = (df['close'] - mid50).abs() / df['close'] * 100 < tol
    # LONG: тренд вверх + откат к 50% + low касается mid50
    long_sig = trend_up & close_near_50 & (df['close'] > df['close'].shift(1))
    short_sig = ~trend_up & close_near_50 & (df['close'] < df['close'].shift(1))
    sig = pd.Series(0, index=df.index)
    sig[long_sig] = 1; sig[short_sig] = -1
    return sig

def strat_03_double_top_bottom(df, lookback=40, tol_pct=0.5):
    """Double top: 2 пика на ±0.5% близости, с минимум 20 барами между."""
    sig = pd.Series(0, index=df.index)
    highs = df['high'].values; lows = df['low'].values
    for i in range(lookback, len(df)):
        win = df.iloc[i-lookback:i+1]
        # Найти 2 макс точки с интервалом ≥ 20
        h_sorted = win['high'].sort_values(ascending=False).head(5).sort_index()
        if len(h_sorted) >= 2:
            t1, t2 = h_sorted.index[0], h_sorted.index[-1]
            if (t2 - t1).total_seconds()/3600 >= 240:  # 20 баров 12h
                p1, p2 = h_sorted.iloc[0], h_sorted.iloc[-1]
                if abs(p1 - p2) / p1 * 100 < tol_pct and df['close'].iloc[i] < min(p1, p2) * 0.99:
                    sig.iloc[i] = -1
        l_sorted = win['low'].sort_values(ascending=True).head(5).sort_index()
        if len(l_sorted) >= 2:
            t1, t2 = l_sorted.index[0], l_sorted.index[-1]
            if (t2 - t1).total_seconds()/3600 >= 240:
                p1, p2 = l_sorted.iloc[0], l_sorted.iloc[-1]
                if abs(p1 - p2) / p1 * 100 < tol_pct and df['close'].iloc[i] > max(p1, p2) * 1.01:
                    sig.iloc[i] = 1
    return sig

def strat_04_vshape_key_reversal(df, vol_z_thr=2.0):
    """V-shape key reversal: outside-day + close против тренда + vol z > 2."""
    rng = df['high'] - df['low']
    body = (df['close'] - df['open']).abs()
    is_outside = (df['high'] > df['high'].shift(1)) & (df['low'] < df['low'].shift(1))
    vol_z = (df['volume'] - df['volume'].rolling(20).mean()) / df['volume'].rolling(20).std()
    body_pct = body / rng
    # LONG: outside down → close > open + vol_z > thr (после падения)
    prior_down = df['close'].shift(3) > df['close'].shift(1)
    long_sig = is_outside & (df['close'] > df['open']) & (vol_z > vol_z_thr) & prior_down & (body_pct > 0.5)
    prior_up = df['close'].shift(3) < df['close'].shift(1)
    short_sig = is_outside & (df['close'] < df['open']) & (vol_z > vol_z_thr) & prior_up & (body_pct > 0.5)
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_05_rsi_mean_reversion(df, n=14, oversold=30, overbought=70):
    """RSI mean reversion: LONG при RSI<30 → close, SHORT при RSI>70."""
    r = rsi(df['close'], n)
    # сигнал на cross обратно из зоны (более чистый чем "пока в зоне")
    long_sig = (r.shift(1) < oversold) & (r >= oversold)
    short_sig = (r.shift(1) > overbought) & (r <= overbought)
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_06_rsi_with_trend(df, n=14, oversold=30, overbought=70, ema_len=200):
    """RSI mean reversion в направлении тренда (EMA-200 фильтр)."""
    r = rsi(df['close'], n)
    trend_up = df['close'] > ema(df['close'], ema_len)
    long_sig = (r.shift(1) < oversold) & (r >= oversold) & trend_up
    short_sig = (r.shift(1) > overbought) & (r <= overbought) & ~trend_up
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_07_rsi_divergence(df, n=14, lookback=10, zone_th=70):
    """RSI divergence — главный сигнал Мерфи.
    Bearish: цена HH, RSI LH, оба RSI≥70 → SHORT
    Bullish: цена LL, RSI HL, оба RSI≤30 → LONG
    """
    r = rsi(df['close'], n)
    sig = pd.Series(0, index=df.index)
    for i in range(lookback*2, len(df)):
        # окно: последние 2*lookback баров
        cur_idx = i; prev_idx = i - lookback
        if cur_idx >= len(df) or prev_idx < 0: continue
        p_cur = df['high'].iloc[cur_idx]; p_prev = df['high'].iloc[cur_idx-lookback:cur_idx].max()
        r_cur = r.iloc[cur_idx]; r_prev = r.iloc[cur_idx-lookback:cur_idx].max()
        # bearish: HH цены, LH RSI, оба >=zone_th
        if (p_cur > p_prev) and (r_cur < r_prev) and (r_cur >= zone_th) and (r_prev >= zone_th):
            sig.iloc[i] = -1
            continue
        # bullish: LL цены, HL RSI
        pl_cur = df['low'].iloc[cur_idx]; pl_prev = df['low'].iloc[cur_idx-lookback:cur_idx].min()
        rl_cur = r.iloc[cur_idx]; rl_prev = r.iloc[cur_idx-lookback:cur_idx].min()
        if (pl_cur < pl_prev) and (rl_cur > rl_prev) and (rl_cur <= (100-zone_th)) and (rl_prev <= (100-zone_th)):
            sig.iloc[i] = 1
    return sig

def strat_08_macd_cross(df):
    """MACD пересечение сигнальной линии."""
    line, signal, _ = macd(df['close'])
    long_sig = (line.shift(1) < signal.shift(1)) & (line >= signal)
    short_sig = (line.shift(1) > signal.shift(1)) & (line <= signal)
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_09_stoch_extreme_cross(df, k=14, d=3, low=20, high=80):
    """Stochastic %K пересекает %D в экстремуме."""
    K, D = stochastic(df, k, d)
    # right-side cross в зоне: %D уже развернулся, %K догнал
    long_sig = (K.shift(1) < D.shift(1)) & (K >= D) & (D.shift(1) < low)
    short_sig = (K.shift(1) > D.shift(1)) & (K <= D) & (D.shift(1) > high)
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_10_momentum_zero_cross(df, n=10):
    """Momentum (10) пересекает 0."""
    m = momentum(df['close'], n)
    long_sig = (m.shift(1) <= 0) & (m > 0)
    short_sig = (m.shift(1) >= 0) & (m < 0)
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_11_golden_death_cross(df, fast=50, slow=200):
    """Golden Cross / Death Cross (50/200 MA)."""
    f = sma(df['close'], fast); s = sma(df['close'], slow)
    long_sig = (f.shift(1) <= s.shift(1)) & (f > s)
    short_sig = (f.shift(1) >= s.shift(1)) & (f < s)
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_12_donchian_breakout(df, n=20):
    """Дончиан 20-bar breakout (4-week rule, упомянут в гл.14)."""
    hh = df['high'].rolling(n).max().shift(1)
    ll = df['low'].rolling(n).min().shift(1)
    long_sig = df['close'] > hh
    short_sig = df['close'] < ll
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_13_triple_ma_alignment(df):
    """Allen 4/9/18 — alignment based entry."""
    m4 = sma(df['close'], 4); m9 = sma(df['close'], 9); m18 = sma(df['close'], 18)
    # bullish alignment formed
    bull = (m4 > m9) & (m9 > m18)
    bear = (m4 < m9) & (m9 < m18)
    # сигнал на формирование (не каждый бар)
    long_sig = bull & ~bull.shift(1).fillna(False)
    short_sig = bear & ~bear.shift(1).fillna(False)
    sig = pd.Series(0, index=df.index)
    sig[long_sig] = 1; sig[short_sig] = -1
    return sig

def strat_14_fibonacci_ma_cross(df):
    """Fibonacci 13/34 cross (Murphy упомянул как сильное)."""
    f = ema(df['close'], 13); s = ema(df['close'], 34)
    long_sig = (f.shift(1) <= s.shift(1)) & (f > s)
    short_sig = (f.shift(1) >= s.shift(1)) & (f < s)
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig

def strat_15_volume_climax(df, vol_z_thr=2.5, ret_thr=0.03):
    """Volume blowoff/climax: vol_z>2.5 + |return| > 3% → contra-trend pivot."""
    vol_z = (df['volume'] - df['volume'].rolling(20).mean()) / df['volume'].rolling(20).std()
    ret = df['close'].pct_change()
    # SHORT: бычий blowoff (рост на огромном объёме)
    short_sig = (vol_z > vol_z_thr) & (ret > ret_thr)
    # LONG: медвежий climax (падение на огромном объёме)
    long_sig = (vol_z > vol_z_thr) & (ret < -ret_thr)
    sig = pd.Series(0, index=df.index)
    sig[long_sig.fillna(False)] = 1; sig[short_sig.fillna(False)] = -1
    return sig


# ============================================================
# BACKTEST RUNNER
# ============================================================

def backtest_signals(df, sig: pd.Series, atr_series, rr=2.0, sl_mult=1.0, max_hold=14):
    """Прогон сигналов. Entry = next open. SL = entry - sl_mult*ATR. TP = entry + rr*sl_mult*ATR."""
    trades = []
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    opens = df['open'].values
    atrs = atr_series.values

    in_pos = False
    entry_i = None; entry_price = None; sl = None; tp = None; direction = None

    sig_vals = sig.values
    n = len(df)
    for i in range(20, n - max_hold - 2):
        if not in_pos and sig_vals[i] != 0 and not np.isnan(atrs[i]):
            # Открытие на next open
            entry_i = i + 1
            entry_price = float(opens[entry_i])
            sl_dist = atrs[i] * sl_mult
            if sig_vals[i] == 1:
                direction = 'LONG'
                sl = entry_price - sl_dist; tp = entry_price + rr * sl_dist
            else:
                direction = 'SHORT'
                sl = entry_price + sl_dist; tp = entry_price - rr * sl_dist
            in_pos = True
            continue

        if in_pos:
            held = i - entry_i
            # Проверка SL/TP
            hit_sl = (lows[i] <= sl) if direction == 'LONG' else (highs[i] >= sl)
            hit_tp = (highs[i] >= tp) if direction == 'LONG' else (lows[i] <= tp)
            exit_reason = None
            exit_price = None
            if hit_sl and hit_tp:
                # Если оба — assume worst (SL hit first)
                exit_reason = 'sl_first'; exit_price = sl
            elif hit_sl:
                exit_reason = 'sl_hit'; exit_price = sl
            elif hit_tp:
                exit_reason = 'tp_hit'; exit_price = tp
            elif held >= max_hold:
                exit_reason = 'timeout'; exit_price = float(closes[i])

            if exit_reason:
                R = ((exit_price - entry_price) / (entry_price - sl) if direction == 'LONG'
                     else (entry_price - exit_price) / (sl - entry_price))
                trades.append({
                    'entry_time': df.index[entry_i], 'entry_price': entry_price,
                    'exit_time': df.index[i], 'exit_price': exit_price,
                    'direction': direction, 'R': R, 'exit_reason': exit_reason,
                    'bars_held': held,
                })
                in_pos = False
    return pd.DataFrame(trades)


def stats(trades: pd.DataFrame):
    if len(trades) == 0:
        return {'n': 0, 'wr_pct': 0.0, 'total_R': 0.0, 'r_per_trade': 0.0,
                'max_dd_R': 0.0, 'profit_factor': 0.0, 'avg_hold_bars': 0.0}
    wins = (trades['R'] > 0).sum()
    losses = (trades['R'] <= 0).sum()
    win_R = trades.loc[trades['R'] > 0, 'R'].sum()
    loss_R = -trades.loc[trades['R'] <= 0, 'R'].sum()
    # max DD по equity curve
    cum = trades['R'].cumsum()
    dd = (cum - cum.cummax()).min()
    return {
        'n': len(trades),
        'wr_pct': wins / len(trades) * 100,
        'total_R': float(trades['R'].sum()),
        'r_per_trade': float(trades['R'].mean()),
        'max_dd_R': float(dd),
        'profit_factor': float(win_R / loss_R) if loss_R > 0 else float('inf'),
        'avg_hold_bars': float(trades['bars_held'].mean()),
        'longs': int((trades['direction']=='LONG').sum()),
        'shorts': int((trades['direction']=='SHORT').sum()),
        'tp_hit_pct': float((trades['exit_reason']=='tp_hit').sum()/len(trades)*100),
        'sl_hit_pct': float((trades['exit_reason']=='sl_hit').sum()/len(trades)*100),
        'timeout_pct': float((trades['exit_reason']=='timeout').sum()/len(trades)*100),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("="*80)
    print("etap_168: Бэктест стратегий Мерфи на BTC 12h (2020-2026)")
    print(f"  RR={RR}  SL=1.0*ATR(14)  TP={RR}*ATR  max_hold={MAX_HOLD_BARS} bars (7d)")
    print("="*80)
    print()

    t0 = time.time()
    df_1h = load_df(SYMBOL, '1h')
    df_12h = compose_from_base(df_1h, '12h')
    df_12h = df_12h[(df_12h.index >= START) & (df_12h.index <= END)].copy()
    atr14 = atr(df_12h, ATR_LEN)
    print(f"Data: {len(df_12h)} 12h bars, {df_12h.index[0]} → {df_12h.index[-1]}")
    print()

    strategies = [
        ('01 S/R breakout 3%+2bars', strat_01_sr_breakout(df_12h)),
        ('02 Fib 50% retracement',   strat_02_fib_retrace_50(df_12h)),
        ('03 Double top/bottom',     strat_03_double_top_bottom(df_12h)),
        ('04 V-shape key reversal',  strat_04_vshape_key_reversal(df_12h)),
        ('05 RSI mean reversion',    strat_05_rsi_mean_reversion(df_12h)),
        ('06 RSI + EMA200 trend',    strat_06_rsi_with_trend(df_12h)),
        ('07 RSI divergence ⭐',     strat_07_rsi_divergence(df_12h)),
        ('08 MACD cross',            strat_08_macd_cross(df_12h)),
        ('09 Stoch extreme cross',   strat_09_stoch_extreme_cross(df_12h)),
        ('10 Momentum zero cross',   strat_10_momentum_zero_cross(df_12h)),
        ('11 Golden/Death Cross 50/200', strat_11_golden_death_cross(df_12h)),
        ('12 Donchian 20 breakout',  strat_12_donchian_breakout(df_12h)),
        ('13 Triple MA 4/9/18',      strat_13_triple_ma_alignment(df_12h)),
        ('14 Fibonacci EMA 13/34',   strat_14_fibonacci_ma_cross(df_12h)),
        ('15 Volume climax',         strat_15_volume_climax(df_12h)),
    ]

    rows = []
    all_trades = []
    for name, sig in strategies:
        print(f'Running {name}...')
        tr = backtest_signals(df_12h, sig, atr14, rr=RR, sl_mult=SL_ATR_MULT, max_hold=MAX_HOLD_BARS)
        st = stats(tr)
        st['strategy'] = name
        rows.append(st)
        if len(tr): tr['strategy'] = name; all_trades.append(tr)
        print(f"  n={st['n']}  WR={st['wr_pct']:.1f}%  total_R={st['total_R']:+.1f}  R/tr={st['r_per_trade']:+.2f}  PF={st['profit_factor']:.2f}  DD={st['max_dd_R']:.1f}R")

    res = pd.DataFrame(rows)
    res = res[['strategy','n','wr_pct','total_R','r_per_trade','profit_factor','max_dd_R',
               'longs','shorts','tp_hit_pct','sl_hit_pct','timeout_pct','avg_hold_bars']]
    out = _ROOT / 'research' / 'elements_study' / 'output'
    out.mkdir(parents=True, exist_ok=True)
    res.to_csv(out / 'etap_168_murphy_backtest_summary.csv', index=False)

    if all_trades:
        pd.concat(all_trades).to_csv(out / 'etap_168_murphy_all_trades.csv', index=False)

    print()
    print("="*80)
    print("ИТОГОВАЯ СВОДКА")
    print("="*80)
    print(res.sort_values('total_R', ascending=False).to_string(index=False))
    print()
    print(f"Total time: {time.time()-t0:.1f}s")
    print(f"Output: {out}/etap_168_*.csv")


if __name__ == '__main__':
    main()
