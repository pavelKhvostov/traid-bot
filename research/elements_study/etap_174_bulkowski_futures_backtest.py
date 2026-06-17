"""etap_174: РЕАЛИСТИЧНЫЙ фьючерсный бэктест паттернов Bulkowski на BTC 12h.

В отличие от etap_172 (Bulkowski-style "ultimate move" / measure-rule — это
ОЦЕНКА паттерна, не торговля), здесь — симуляция фьючерсной торговли максимально
близко к реальности:

  • Вход: на ЗАКРЫТИИ 12h breakout-свечи (market/taker). Сканирование SL/TP
    начинается со СЛЕДУЮЩЕЙ 1h-свечи — никакого lookahead.
  • SL: структурная инвалидация паттерна (low паттерна для long / high для short)
    с буфером. Это «refutation stop» по Bulkowski (top-of-pattern стоп выбивается
    67-78% — не используем).
  • TP: 4 схемы — measure-rule half (height/2), full (height), и fixed RR=1 / RR=2.
  • Внутрибаровое разрешение SL-vs-TP на 1h-данных. Если в одной 1h-свече задеты
    оба — считаем SL первым (консервативно).
  • Таймаут: 60×12h = 30 дней → закрытие по рынку.
  • Издержки (Binance USDⓈ-M futures, консервативно):
        taker 0.05%/сторону + slippage 0.03%/сторону = round-trip 0.16% notional
        funding 0.01% за каждые 8h удержания (drag, против позиции).
  • Портфель: одна позиция за раз (chronological, реалистично для ритейла) +
    отдельно вариант «все сигналы». Дедуп одновременных сигналов одной стороны.
  • Sizing: фиксированный риск 1% эквити на сделку → equity-curve, max DD, по годам.

Честность: WR>60% на сотнях сделок — red flag lookahead (см. known-pitfalls).
Здесь вход на наблюдаемом close, разрешение на будущих 1h — lookahead исключён.

Output:
  output/etap_174_trades_<scheme>.csv
  output/etap_174_summary.csv
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import numpy as np
import pandas as pd

from data_manager import load_df, compose_from_base
from etap_172_bulkowski_patterns import DETECTORS, LOOKBACK, SWING_N

SYMBOL = "BTCUSDT"
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-06-04", tz="UTC")

# --- модель издержек (фьючерсы, консервативно) ---
TAKER_FEE = 0.0005        # 0.05% / сторону
SLIPPAGE = 0.0003         # 0.03% / сторону
SIDE_COST = TAKER_FEE + SLIPPAGE   # 0.08% / сторону
FUNDING_PER_8H = 0.0001   # 0.01% за 8h удержания (drag)

SL_BUFFER = 0.001         # +0.1% за структурный уровень (шум)
MAX_HOLD_BARS_12H = 60    # 30 дней
RISK_PER_TRADE = 0.01     # 1% эквити на сделку (для equity-curve)

TF_12H_HOURS = 12


def redetect_signals(df_12h):
    """Переисполняем все 13 детекторов → полные dict'ы с low_price/high_price."""
    signals = []
    # верхняя граница len-SWING_N-1: confirmed_swings подтверждает swing на j+n,
    # без этого ограничения читаем за пределами массива (и подсматриваем будущее)
    for i in range(LOOKBACK + SWING_N + 2, len(df_12h) - SWING_N):
        for det in DETECTORS:
            sig = det(df_12h, i)
            if sig is not None:
                sig['time'] = df_12h['time'].iloc[i]
                signals.append(sig)
    signals.sort(key=lambda s: (s['time'], s['pattern']))
    return signals


def simulate_trade(sig, h, l, c, times_ns, scheme, atr_at):
    """Реалистичная симуляция одной сделки на 1h-данных.

    scheme: 'half'|'full'|'rr1'|'rr2'      — SL=структурный уровень паттерна
            'atr_rr1.5'|'atr_rr2'|'atr_rr3' — SL=1.5×ATR(14,12h), TP=fixed RR
    atr_at: значение ATR(14) на breakout-баре (для atr-схем)
    Возвращает dict с outcome или None если нет данных для входа.
    """
    side = sig['side']
    entry = sig['breakout_price']
    t_break = sig['time']

    if scheme.startswith('atr_'):
        # контролируемый риск: узкий стоп по волатильности
        if atr_at is None or atr_at <= 0:
            return None
        risk = 1.5 * atr_at
        sl = entry - risk if side == 'long' else entry + risk
        rr = float(scheme.split('rr')[1])
        tp_dist = risk * rr
    else:
        # структурная инвалидация паттерна + буфер
        if side == 'long':
            sl = sig['low_price'] * (1 - SL_BUFFER)
            risk = entry - sl
        else:
            sl = sig['high_price'] * (1 + SL_BUFFER)
            risk = sl - entry
        if risk <= 0:
            return None
        height_frac = sig['height_pct'] / 100.0
        if scheme == 'half':
            tp_dist = entry * height_frac / 2
        elif scheme == 'full':
            tp_dist = entry * height_frac
        elif scheme == 'rr1':
            tp_dist = risk * 1.0
        elif scheme == 'rr2':
            tp_dist = risk * 2.0
        else:
            raise ValueError(scheme)
    risk_pct = risk / entry  # доля entry
    tp = entry + tp_dist if side == 'long' else entry - tp_dist

    # Старт сканирования — первая 1h свеча СТРОГО после close 12h-свечи.
    # t_break это open_time 12h свечи; её close = t_break + 12h.
    t_close = t_break + pd.Timedelta(hours=TF_12H_HOURS)
    start = int(np.searchsorted(times_ns, t_close.value, side='left'))
    if start >= len(c):
        return None
    end = min(start + MAX_HOLD_BARS_12H * TF_12H_HOURS, len(c))

    exit_price = None
    outcome = None
    exit_i = end - 1
    for k in range(start, end):
        hi = h[k]; lo = l[k]
        if side == 'long':
            hit_sl = lo <= sl
            hit_tp = hi >= tp
        else:
            hit_sl = hi >= sl
            hit_tp = lo <= tp
        if hit_sl and hit_tp:
            # оба в одной свече → SL первым (консервативно)
            exit_price = sl; outcome = 'sl'; exit_i = k; break
        if hit_sl:
            exit_price = sl; outcome = 'sl'; exit_i = k; break
        if hit_tp:
            exit_price = tp; outcome = 'tp'; exit_i = k; break
    if exit_price is None:
        exit_price = c[end - 1]; outcome = 'timeout'; exit_i = end - 1

    # gross R
    if side == 'long':
        gross_R = (exit_price - entry) / risk
    else:
        gross_R = (entry - exit_price) / risk

    # издержки
    hours_held = max(1, exit_i - start + TF_12H_HOURS)
    funding_pct = FUNDING_PER_8H * (hours_held / 8.0)
    cost_pct = 2 * SIDE_COST + funding_pct          # доля notional
    cost_R = cost_pct / risk_pct                    # в R
    net_R = gross_R - cost_R

    return {
        'time': t_break, 'pattern': sig['pattern'], 'side': side,
        'entry': entry, 'sl': sl, 'tp': tp,
        'risk_pct': risk_pct * 100,
        'exit_price': exit_price, 'outcome': outcome,
        'hours_held': hours_held,
        'gross_R': gross_R, 'cost_R': cost_R, 'net_R': net_R,
        'exit_time_ns': times_ns[exit_i],
        'start_i': start, 'exit_i': exit_i,
    }


def dedup_same_bar(trades):
    """Один и тот же (time, side) от нескольких паттернов → берём первый
    (наименьший risk_pct = ближайший структурный стоп = чище сигнал)."""
    best = {}
    for t in trades:
        key = (t['time'], t['side'])
        if key not in best or t['risk_pct'] < best[key]['risk_pct']:
            best[key] = t
    return sorted(best.values(), key=lambda x: x['time'])


def portfolio_single_position(trades):
    """Одна позиция за раз: идём хронологически, новый сигнал пока в позиции —
    пропускаем (реалистично для одного депозита без пирамидинга)."""
    trades = sorted(trades, key=lambda x: x['time'])
    selected = []
    busy_until_ns = -1
    for t in trades:
        if t['time'].value < busy_until_ns:
            continue
        selected.append(t)
        busy_until_ns = int(t['exit_time_ns'])
    return selected


def equity_metrics(trades_sorted, risk_frac=RISK_PER_TRADE):
    """Equity-curve с фиксированным риском risk_frac на сделку."""
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    curve = []
    for t in trades_sorted:
        eq *= (1 + risk_frac * t['net_R'])
        peak = max(peak, eq)
        dd = (eq - peak) / peak
        max_dd = min(max_dd, dd)
        curve.append(eq)
    return eq, max_dd, curve


def summarize(trades, label):
    if not trades:
        print(f"{label}: 0 trades")
        return None
    n = len(trades)
    net = np.array([t['net_R'] for t in trades])
    wins = (net > 0).sum()
    wr = wins / n * 100
    total_R = net.sum()
    avg_R = net.mean()
    gross_total = sum(t['gross_R'] for t in trades)
    ts = sorted(trades, key=lambda x: x['time'])
    fin_eq, max_dd, _ = equity_metrics(ts)
    # Sharpe по сделкам (annualize грубо: ~ сделок/год)
    span_years = (ts[-1]['time'] - ts[0]['time']).days / 365.25
    trades_per_year = n / max(span_years, 0.5)
    sharpe = (net.mean() / net.std() * np.sqrt(trades_per_year)) if net.std() > 0 else 0.0
    print(f"\n{label}")
    print(f"  trades={n}  WR={wr:.1f}%  net_ΣR={total_R:+.1f}  avg_R={avg_R:+.3f}  "
          f"gross_ΣR={gross_total:+.1f}  cost_drag={gross_total-total_R:.1f}R")
    print(f"  equity(1%/trade)×{fin_eq:.2f}  maxDD={max_dd*100:.1f}%  "
          f"Sharpe≈{sharpe:.2f}  ~{trades_per_year:.0f} trades/yr")
    return {
        'label': label, 'n': n, 'wr': round(wr, 1), 'net_R': round(total_R, 1),
        'avg_R': round(avg_R, 3), 'gross_R': round(gross_total, 1),
        'cost_drag_R': round(gross_total - total_R, 1),
        'final_eq': round(fin_eq, 3), 'max_dd_pct': round(max_dd * 100, 1),
        'sharpe': round(sharpe, 2),
    }


def by_year(trades, label):
    df = pd.DataFrame(trades)
    df['year'] = pd.to_datetime(df['time']).dt.year
    g = df.groupby('year')['net_R'].agg(['count', 'sum', 'mean'])
    print(f"\n  {label} — по годам:")
    bad = 0
    for yr, row in g.iterrows():
        flag = '  ❌' if row['sum'] < 0 else ''
        if row['sum'] < 0:
            bad += 1
        print(f"    {yr}: n={int(row['count']):>3}  ΣR={row['sum']:+6.1f}  avg={row['mean']:+.2f}{flag}")
    print(f"    bad years: {bad}/{len(g)}")


def by_pattern(trades, label):
    df = pd.DataFrame(trades)
    g = df.groupby('pattern')['net_R'].agg(['count', 'sum', 'mean'])
    g['wr'] = df.groupby('pattern')['net_R'].apply(lambda s: (s > 0).mean() * 100)
    g = g.sort_values('sum', ascending=False)
    print(f"\n  {label} — по паттернам:")
    print(f"    {'pattern':>16}  {'n':>4}  {'WR%':>5}  {'ΣR':>7}  {'avgR':>6}")
    for pat, row in g.iterrows():
        print(f"    {pat:>16}  {int(row['count']):>4}  {row['wr']:>5.1f}  "
              f"{row['sum']:>+7.1f}  {row['mean']:>+6.3f}")


def main():
    t0 = time.time()
    print("=" * 74)
    print("etap_174: РЕАЛИСТИЧНЫЙ фьючерсный бэктест паттернов Bulkowski (BTC 12h)")
    print("=" * 74)

    print("\nLoading 1h, composing 12h...")
    df_1h = load_df(SYMBOL, "1h")
    df_1h = df_1h[(df_1h.index >= START_DATE) & (df_1h.index <= END_DATE)].copy()
    df_12h = compose_from_base(df_1h, "12h")
    df_12h = df_12h[(df_12h.index >= START_DATE) & (df_12h.index <= END_DATE)].copy()
    df_12h = df_12h.reset_index()
    if 'time' not in df_12h.columns:
        df_12h = df_12h.rename(columns={df_12h.columns[0]: 'time'})
    print(f"  12h bars: {len(df_12h)}  1h bars: {len(df_1h)}  "
          f"range {df_12h['time'].iloc[0].date()} -> {df_12h['time'].iloc[-1].date()}")

    # 1h массивы для быстрой симуляции
    h = df_1h['high'].values.astype(float)
    l = df_1h['low'].values.astype(float)
    c = df_1h['close'].values.astype(float)
    times_ns = df_1h.index.values.astype('datetime64[ns]').astype(np.int64)

    # ATR(14) на 12h (Wilder) — для atr-схем стопа
    hh = df_12h['high'].values.astype(float)
    ll = df_12h['low'].values.astype(float)
    cc = df_12h['close'].values.astype(float)
    prev_c = np.concatenate([[cc[0]], cc[:-1]])
    tr = np.maximum(hh - ll, np.maximum(np.abs(hh - prev_c), np.abs(ll - prev_c)))
    atr_arr = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().values

    print("\nRe-detecting Bulkowski signals on 12h...")
    signals = redetect_signals(df_12h)
    print(f"  raw signals: {len(signals)}")

    schemes = ['half', 'full', 'rr1', 'rr2', 'atr_rr1.5', 'atr_rr2', 'atr_rr3']
    summary_rows = []

    for scheme in schemes:
        print("\n" + "=" * 74)
        print(f"СХЕМА TP = {scheme.upper()}   (SL = структурный уровень паттерна)")
        print("=" * 74)

        raw_trades = []
        for sig in signals:
            atr_at = atr_arr[sig['breakout_idx']] if sig['breakout_idx'] < len(atr_arr) else None
            tr = simulate_trade(sig, h, l, c, times_ns, scheme, atr_at)
            if tr is not None:
                raw_trades.append(tr)

        # дедуп одновременных сигналов одной стороны
        dd = dedup_same_bar(raw_trades)
        # портфель: одна позиция за раз
        port = portfolio_single_position(dd)

        s_all = summarize(dd, f"[{scheme}] ALL signals (deduped, multi-position)")
        s_port = summarize(port, f"[{scheme}] PORTFOLIO (single-position, реалистично)")
        # long/short split на портфеле
        longs = [t for t in port if t['side'] == 'long']
        shorts = [t for t in port if t['side'] == 'short']
        summarize(longs, f"[{scheme}]   └ LONG-only")
        summarize(shorts, f"[{scheme}]   └ SHORT-only")

        if s_port:
            by_year(port, f"[{scheme}] portfolio")
            by_pattern(port, f"[{scheme}] portfolio")

        if s_all:
            s_all['scheme'] = scheme; s_all['view'] = 'all'
            summary_rows.append(s_all)
        if s_port:
            s_port['scheme'] = scheme; s_port['view'] = 'portfolio'
            summary_rows.append(s_port)

        # сохраняем сделки портфеля
        out_dir = _ROOT / 'research' / 'elements_study' / 'output'
        out_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(port).to_csv(out_dir / f'etap_174_trades_{scheme}.csv', index=False)

    out_dir = _ROOT / 'research' / 'elements_study' / 'output'
    pd.DataFrame(summary_rows).to_csv(out_dir / 'etap_174_summary.csv', index=False)
    print("\n" + "=" * 74)
    print(f"Saved summary: {out_dir / 'etap_174_summary.csv'}")
    print(f"Done in {time.time() - t0:.1f}s")
    print("=" * 74)


if __name__ == '__main__':
    main()
