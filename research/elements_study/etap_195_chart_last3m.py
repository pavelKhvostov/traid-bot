"""etap_195: график BTC за последние 3 месяца с точками, подтверждёнными
in-process системой (etap_193).

Система: для каждого Bulkowski reversal-сигнала смотрим путь первых 12ч и моделью
(обученной на train <2024) оцениваем P(дойдёт +5% раньше снятия). «Подтверждён» =
P ≥ 0.6 на чекпоинте 12ч. Рисуем BTC 12h за 3 мес, отмечаем:
  • подтверждённые сигналы — крупный маркер, ✓зелёный (дошёл +5%) / ✗красный (busted);
  • отклонённые (низкий P) — мелкий серый ×.
Окно 2026-03-03 → 2026-06-03 (OOS).

Output: output/etap_195_chart_last3m.png
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sklearn.ensemble import HistGradientBoostingClassifier

from data_manager import load_df, compose_from_base
from etap_193_path_forensics import build_symbol, SYMBOLS, TRAIN_END

OUT = _ROOT / 'research' / 'elements_study' / 'output'
PATH_F = ['mae6', 'mfe6', 'r1_6', 'mae12', 'mfe12', 'r1_12', 'r2_12', 'risk_pct', 'side_long']
WIN_LO = pd.Timestamp("2026-03-03", tz="UTC")
WIN_HI = pd.Timestamp("2026-06-03", tz="UTC")
P_CONF = 0.60
DATA_END = pd.Timestamp("2026-06-03 16:00", tz="UTC")


def main():
    # 1) датасет всех активов → обучаем in-process модель на train, открытые на 12ч
    rows = []
    for sym in SYMBOLS:
        rows.extend(build_symbol(sym))
    df = pd.DataFrame(rows)
    df['time'] = pd.to_datetime(df['time'], utc=True)
    op = df[df.open_at_12 == 1].copy()
    tr = op[op.time < TRAIN_END]
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
        min_samples_leaf=20, l2_regularization=1.0, random_state=42).fit(
        tr[PATH_F].fillna(0).values, tr['success'].values)

    # цена BTC 12h (для координат маркеров и линии)
    d1h = load_df('BTCUSDT', '1h')
    d12 = compose_from_base(d1h, '12h')

    # 2) BTC сигналы в окне
    b = op[(op.symbol == 'BTCUSDT') & (op.time >= WIN_LO) & (op.time <= WIN_HI)].copy()
    b['entry'] = d12['close'].reindex(b['time']).values   # close сигнальной 12h-свечи
    b['p'] = clf.predict_proba(b[PATH_F].fillna(0).values)[:, 1]
    b['confirmed'] = b['p'] >= P_CONF
    # «pending» — сигнал, чья развязка могла не уложиться в данные (последние ~30 дней)
    b['pending'] = (b['time'] > DATA_END - pd.Timedelta(days=30)) & (b['outcome'] == 'timeout')

    conf = b[b.confirmed & ~b.pending]
    n_conf = len(conf); n_win = int(conf['success'].sum())
    wr = n_win / n_conf * 100 if n_conf else 0
    print(f"BTC окно {WIN_LO.date()}..{WIN_HI.date()}: всего сигналов {len(b)}, "
          f"подтверждено {b['confirmed'].sum()}, resolved-подтв {n_conf}, "
          f"из них дошли +5%: {n_win} (WR {wr:.0f}%)")

    # 3) цена BTC 12h в окне
    px = d12[(d12.index >= WIN_LO) & (d12.index <= WIN_HI)]

    fig, ax = plt.subplots(figsize=(15, 7))
    ax.plot(px.index, px['close'], color='#222', lw=1.0, alpha=0.8, label='BTC 12h close', zorder=1)

    def mark(sub, **kw):
        for _, r in sub.iterrows():
            up = r['side_long'] == 1
            ax.scatter(r['time'], r['entry'], marker='^' if up else 'v', zorder=5, **kw)

    # отклонённые (низкий P)
    mark(b[~b.confirmed], s=45, c='#bbb', edgecolors='none', label='_')
    # подтверждённые, дошли +5%
    mark(conf[conf.success == 1], s=170, c='#16a34a', edgecolors='k', linewidths=0.6)
    # подтверждённые, busted
    mark(conf[conf.success == 0], s=170, c='#dc2626', edgecolors='k', linewidths=0.6)
    # подтверждённые, ещё в развитии
    mark(b[b.confirmed & b.pending], s=140, c='#f59e0b', edgecolors='k', linewidths=0.6)

    from matplotlib.lines import Line2D
    legend = [
        Line2D([0], [0], marker='^', color='w', markerfacecolor='#16a34a', markeredgecolor='k', markersize=12, label='Подтверждён → дошёл +5%'),
        Line2D([0], [0], marker='v', color='w', markerfacecolor='#dc2626', markeredgecolor='k', markersize=12, label='Подтверждён → busted'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#f59e0b', markeredgecolor='k', markersize=11, label='Подтверждён → в развитии'),
        Line2D([0], [0], marker='^', color='w', markerfacecolor='#bbb', markersize=9, label='Отклонён (низкий P)'),
        Line2D([0], [0], color='#222', lw=1, label='BTC 12h close'),
    ]
    ax.legend(handles=legend, loc='upper left', fontsize=9, framealpha=0.9)
    ax.set_title(f'BTC · Bulkowski-развороты, подтверждённые in-process системой '
                 f'(P≥{P_CONF}) · {WIN_LO.date()}–{WIN_HI.date()}\n'
                 f'Подтверждённых (resolved): {n_conf} · дошли +5%: {n_win} · WR {wr:.0f}% '
                 f'(▲=LONG ▼=SHORT)', fontsize=11)
    ax.set_ylabel('Цена, USDT'); ax.grid(alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()
    fig.tight_layout()
    out = OUT / 'etap_195_chart_last3m.png'
    fig.savefig(out, dpi=110)
    print(f"Saved: {out}")

    # печать списка точек
    print("\nПодтверждённые точки (BTC, окно):")
    for _, r in b[b.confirmed].sort_values('time').iterrows():
        st = 'WIN+5%' if (r['success'] == 1 and not r['pending']) else ('PENDING' if r['pending'] else 'busted')
        print(f"  {r['time'].strftime('%Y-%m-%d %H:%M')}  {'LONG ' if r['side_long']==1 else 'SHORT'}  "
              f"{r['pattern']:>12}  entry={r['entry']:.0f}  P={r['p']:.2f}  → {st}")


if __name__ == '__main__':
    main()
