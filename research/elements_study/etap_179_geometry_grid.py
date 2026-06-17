"""etap_179: grid-скан ГЕОМЕТРИИ таргета/стопа на Bulkowski-кандидатах (БЕЗ ML).

Контекст (2026-06-10): нейро-селектор (etap_175/176/177/178) дал отрицательный
OOS net_R во всех трёх вариантах лейбла, permutation importance ≈ 0. Диагноз:
проблема не в модели, а в ГЕОМЕТРИИ лейбла — fixed +5% TP при структурном стопе
даёт rr_at_target<1, а отбор по EV тянет к узким стопам, которые выбивает.

Прежде чем что-либо обучать, надо разделить ДВА вопроса:
  (1) есть ли на этом пуле кандидатов хоть одна (TP,SL)-геометрия с
      положительным net_R БЕЗ всякого отбора?  ← этот этап
  (2) если есть — может ли селектор её усилить?  ← следующий этап, только если (1) да.

Если ни одна ячейка геометрии не плюсует unfiltered → кандидаты плохие,
редирект на Stage A (а не докрутка модели). Это López de Prado: плохой
результат чинит процесс, а не стратегию.

Stage A = ТОЛЬКО Bulkowski-детекторы (etap_172): у них есть height_pct →
доступен measured-move таргет (breakout ± height) — НАТИВНЫЙ таргет Bulkowski,
которого не было ни в одном лейбле 175-178. Кросс-актив BTC+ETH+SOL.

Сетка:
  SL-правила: struct (low/high паттерна) | atr1.5 | atr3 | cap3 (клип риска
              в [0.5, 3]·ATR — ограничивает далёкие структурные стопы снизу/сверху)
  TP-правила: measured (full measure) | half (half measure) | rr1 | rr2 | rr3 |
              pct5 | pct8
Резолв на 1h (SL первым в одной свече — консерв.), таймаут 60 дней.
Издержки: taker+slip 0.08%/сторону + funding 0.01%/8h (как etap_175).

ВАЖНО (multiple testing): печатаем число протестированных ячеек. Плюсовую
ячейку трактуем как ГИПОТЕЗУ — нужно согласие TRAIN+TEST и стабильность по
годам, не cherry-pick по итоговой ΣR. Перед DL — Deflated Sharpe / CPCV.

Output: output/etap_179_geometry_grid.csv (одна строка = ячейка sl×tp)
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
from etap_175_metalabel_dataset import wilder_atr, SIDE_COST, FUNDING_PER_8H

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START_DATE = pd.Timestamp("2020-01-01", tz="UTC")
END_DATE = pd.Timestamp("2026-05-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")   # 4y train / ~2.3y test
OUT = _ROOT / 'research' / 'elements_study' / 'output'

TIMEOUT_12H = 120          # 60 дней — даём measured-move дойти, но не бесконечно
ATR_FLOOR = 0.5            # cap3: стоп не ближе 0.5·ATR (анти-шум)
ATR_CAP = 3.0             # cap3: стоп не дальше 3·ATR (анти-RR<1)

SL_RULES = ['struct', 'atr1.5', 'atr3', 'cap3']
TP_RULES = ['measured', 'half', 'rr1', 'rr2', 'rr3', 'pct5', 'pct8']


def sl_price(rule, side, entry, struct, atr):
    """Цена стопа по правилу. struct = low_price(long)/high_price(short)."""
    if rule == 'struct':
        return struct
    if rule == 'atr1.5':
        d = 1.5 * atr
    elif rule == 'atr3':
        d = 3.0 * atr
    elif rule == 'cap3':
        struct_d = abs(entry - struct)
        d = min(max(struct_d, ATR_FLOOR * atr), ATR_CAP * atr)
    else:
        raise ValueError(rule)
    return entry - d if side == 'long' else entry + d


def tp_price(rule, side, entry, sl, breakout, height_pct):
    """Цена тейка. measured/half — нативный Bulkowski; rr* — кратность риска."""
    risk = abs(entry - sl)
    if rule == 'measured':
        d = breakout * height_pct / 100.0
    elif rule == 'half':
        d = breakout * height_pct / 100.0 / 2.0
    elif rule.startswith('rr'):
        d = float(rule[2:]) * risk
    elif rule == 'pct5':
        d = entry * 0.05
    elif rule == 'pct8':
        d = entry * 0.08
    else:
        raise ValueError(rule)
    return entry + d if side == 'long' else entry - d


def simulate(side, entry, sl, tp, h1, l1, c1, start, end):
    """Резолв TP/SL на 1h. SL первым при касании обоих в одной свече."""
    if side == 'long':
        if sl >= entry or tp <= entry:
            return None
    else:
        if sl <= entry or tp >= entry:
            return None
    risk_pct = abs(entry - sl) / entry
    rr = abs(tp - entry) / abs(entry - sl)

    outcome = 'timeout'; exit_i = end - 1
    for k in range(start, end):
        hi = h1[k]; lo = l1[k]
        if side == 'long':
            hit_sl = lo <= sl; hit_tp = hi >= tp
        else:
            hit_sl = hi >= sl; hit_tp = lo <= tp
        if hit_sl:
            outcome = 'sl'; exit_i = k; break
        if hit_tp:
            outcome = 'tp'; exit_i = k; break

    if outcome == 'tp':
        gross_R = rr
    elif outcome == 'sl':
        gross_R = -1.0
    else:
        px = c1[exit_i]
        gross_R = ((px - entry) if side == 'long' else (entry - px)) / abs(entry - sl)
    hours = max(1, (exit_i - start) + 12)
    cost_R = (2 * SIDE_COST + FUNDING_PER_8H * hours / 8.0) / risk_pct
    return {'outcome': outcome, 'gross_R': gross_R, 'net_R': gross_R - cost_R, 'rr': rr}


def collect_candidates(sym):
    """Все сработавшие Bulkowski-сигналы с геометрией + ATR + 1h-индексами."""
    df1 = load_df(sym, "1h")
    df1 = df1[(df1.index >= START_DATE) & (df1.index <= END_DATE)].copy()
    df12 = compose_from_base(df1, "12h")
    df12 = df12[(df12.index >= START_DATE) & (df12.index <= END_DATE)].copy().reset_index()
    if 'time' not in df12.columns:
        df12 = df12.rename(columns={df12.columns[0]: 'time'})
    h = df12['high'].values.astype(float)
    l = df12['low'].values.astype(float)
    c = df12['close'].values.astype(float)
    atr = wilder_atr(h, l, c)
    times = df12['time']
    n = len(c)

    h1 = df1['high'].values.astype(float)
    l1 = df1['low'].values.astype(float)
    c1 = df1['close'].values.astype(float)
    t1_ns = df1.index.values.astype('datetime64[ns]').astype(np.int64)

    cands = []
    for i in range(LOOKBACK + SWING_N + 2, n - SWING_N):
        if atr[i] <= 0:
            continue
        for det in DETECTORS:
            sig = det(df12, i)
            if sig is None:
                continue
            t_close_ns = (times.iloc[i] + pd.Timedelta(hours=12)).value
            start = int(np.searchsorted(t1_ns, t_close_ns, side='left'))
            if start >= len(c1):
                continue
            cands.append({
                'symbol': sym, 'time': times.iloc[i], 'side': sig['side'],
                'entry': sig['breakout_price'], 'breakout': sig['breakout_price'],
                'struct': sig['low_price'] if sig['side'] == 'long' else sig['high_price'],
                'height_pct': sig['height_pct'], 'atr': atr[i], 'pattern': sig['pattern'],
                'period': 'test' if times.iloc[i] >= TRAIN_END else 'train',
                '_start': start, '_end': min(start + TIMEOUT_12H * 12, len(c1)),
            })
    return cands, h1, l1, c1


def main():
    t0 = time.time()
    print("=" * 78)
    print("etap_179: grid геометрии TP×SL на Bulkowski-кандидатах (БЕЗ ML) · 4y/2y · 3 актива")
    print("=" * 78)

    by_sym = {}
    all_cands = []
    for sym in SYMBOLS:
        cands, h1, l1, c1 = collect_candidates(sym)
        by_sym[sym] = (h1, l1, c1)
        all_cands.extend(cands)
        print(f"  [{sym}] Bulkowski-сигналов: {len(cands)}")
    print(f"  ВСЕГО кандидатов: {len(all_cands)}  |  ячеек сетки: {len(SL_RULES)*len(TP_RULES)}")

    rows = []
    for sl_rule in SL_RULES:
        for tp_rule in TP_RULES:
            recs = []
            for cd in all_cands:
                side = cd['side']; entry = cd['entry']
                sl = sl_price(sl_rule, side, entry, cd['struct'], cd['atr'])
                tp = tp_price(tp_rule, side, entry, sl, cd['breakout'], cd['height_pct'])
                h1, l1, c1 = by_sym[cd['symbol']]
                r = simulate(side, entry, sl, tp, h1, l1, c1, cd['_start'], cd['_end'])
                if r is None:
                    continue
                recs.append({'period': cd['period'], 'side': side, 'time': cd['time'],
                             'pattern': cd['pattern'], **r})
            if not recs:
                continue
            g = pd.DataFrame(recs)
            cell = {'sl': sl_rule, 'tp': tp_rule, 'n': len(g),
                    'rr_med': round(g['rr'].median(), 2)}
            for split in ['train', 'test']:
                s = g[g.period == split]
                cell[f'{split}_n'] = len(s)
                cell[f'{split}_win'] = round(s['outcome'].eq('tp').mean() * 100, 1) if len(s) else 0
                cell[f'{split}_sumR'] = round(s['net_R'].sum(), 1)
                cell[f'{split}_meanR'] = round(s['net_R'].mean(), 3) if len(s) else 0
            te = g[g.period == 'test']
            cell['test_L_sumR'] = round(te[te.side == 'long']['net_R'].sum(), 1)
            cell['test_S_sumR'] = round(te[te.side == 'short']['net_R'].sum(), 1)
            rows.append(cell)

    grid = pd.DataFrame(rows).sort_values('test_sumR', ascending=False).reset_index(drop=True)
    grid.to_csv(OUT / 'etap_179_geometry_grid.csv', index=False)

    print(f"\nСЕТКА (sorted by TEST ΣR). trials={len(grid)} — плюсовые = ГИПОТЕЗЫ, не выводы.")
    print(f"{'sl':>7} {'tp':>9} {'rr_m':>5}  {'tr_n':>5}{'tr_win':>7}{'tr_ΣR':>8}{'tr_mR':>7}  "
          f"{'te_n':>5}{'te_win':>7}{'te_ΣR':>8}{'te_mR':>7}  {'te_L':>7}{'te_S':>7}")
    for _, r in grid.iterrows():
        print(f"{r['sl']:>7} {r['tp']:>9} {r['rr_med']:>5.2f}  "
              f"{r['train_n']:>5}{r['train_win']:>6.1f}%{r['train_sumR']:>8.1f}{r['train_meanR']:>+7.3f}  "
              f"{r['test_n']:>5}{r['test_win']:>6.1f}%{r['test_sumR']:>8.1f}{r['test_meanR']:>+7.3f}  "
              f"{r['test_L_sumR']:>+7.1f}{r['test_S_sumR']:>+7.1f}")

    cand = grid[(grid.train_sumR > 0) & (grid.test_sumR > 0)]
    print(f"\nЯчейки с TRAIN>0 И TEST>0 (согласие сплитов): {len(cand)} из {len(grid)}")
    print("  (0 ожидаемо: ось стопа инвертируется train↔test — проверяем per-year)")

    # PER-YEAR + per-side для репрезентативных ячеек: понять режимную инверсию.
    probe = [('atr1.5', 'measured'), ('atr1.5', 'rr3'), ('atr1.5', 'pct5'),
             ('struct', 'measured'), ('struct', 'pct5'), ('cap3', 'rr3')]
    print("\nPER-YEAR net_ΣR (L=long-вклад / S=short-вклад в скобках):")
    for sl_rule, tp_rule in probe:
        yr = {}
        for cd in all_cands:
            side = cd['side']; entry = cd['entry']
            sl = sl_price(sl_rule, side, entry, cd['struct'], cd['atr'])
            tp = tp_price(tp_rule, side, entry, sl, cd['breakout'], cd['height_pct'])
            h1, l1, c1 = by_sym[cd['symbol']]
            r = simulate(side, entry, sl, tp, h1, l1, c1, cd['_start'], cd['_end'])
            if r is None:
                continue
            y = cd['time'].year
            a, lo_, sh_ = yr.get(y, (0.0, 0.0, 0.0))
            yr[y] = (a + r['net_R'],
                     lo_ + (r['net_R'] if side == 'long' else 0.0),
                     sh_ + (r['net_R'] if side == 'short' else 0.0))
        line = "  ".join(f"{y}:{v[0]:+.0f}({v[1]:+.0f}/{v[2]:+.0f})" for y, v in sorted(yr.items()))
        bad = sum(1 for v in yr.values() if v[0] < 0)
        print(f"  {sl_rule:>7}×{tp_rule:>9}: {line}  [bad {bad}/{len(yr)}]")

    print(f"\nSaved: {OUT/'etap_179_geometry_grid.csv'}")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
