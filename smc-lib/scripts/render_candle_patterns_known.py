"""Render галерею ~36 свечных паттернов которые знаю уверенно (для candle_patterns/).

Каждый паттерн — синтетический OHLC + название, по канон-палитре chart_format.md.
"""
from __future__ import annotations
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts" / "candle_patterns_known.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

BULL = '#01a648'
BEAR = '#131b1b'
DOJI = '#888'

def draw_candle(ax, x, o, h, l, c, w=0.5):
    """Нарисовать одну свечу на ax."""
    color = BULL if c > o else (BEAR if c < o else DOJI)
    ax.vlines(x, l, h, color=color, linewidth=1.2, zorder=3)
    body_h = max(abs(o - c), 0.02)
    ax.add_patch(Rectangle((x - w/2, min(o, c)), w, body_h,
                            facecolor=color, edgecolor=color, linewidth=1.2, zorder=3))

# Каждый паттерн = функция, возвращающая список (O,H,L,C) для каждой свечи
patterns = [
    # === SINGLE-CANDLE (10) ===
    ('Doji', [(5.0, 5.4, 4.6, 5.0)]),
    ('Long-Legged Doji', [(5.0, 5.8, 4.2, 5.02)]),
    ('Gravestone Doji', [(5.0, 6.0, 5.0, 5.02)]),
    ('Dragonfly Doji', [(5.0, 5.02, 4.0, 5.0)]),
    ('Hammer (bull)', [(5.4, 5.6, 4.0, 5.5)]),
    ('Hanging Man (bear)', [(5.5, 5.7, 4.1, 5.4)]),
    ('Inverted Hammer', [(4.4, 6.0, 4.3, 4.5)]),
    ('Shooting Star', [(4.5, 6.0, 4.4, 4.4)]),
    ('Spinning Top', [(4.8, 5.7, 4.3, 5.1)]),
    ('White Marubozu', [(4.0, 6.0, 4.0, 6.0)]),

    # === TWO-CANDLE (14) ===
    ('Bullish Engulfing', [(5.5, 5.6, 4.5, 4.7), (4.6, 5.9, 4.4, 5.8)]),
    ('Bearish Engulfing', [(4.5, 5.5, 4.4, 5.3), (5.4, 5.6, 4.2, 4.4)]),
    ('Bullish Harami', [(5.8, 6.0, 4.4, 4.5), (4.7, 5.3, 4.6, 5.2)]),
    ('Bearish Harami', [(4.5, 5.8, 4.3, 5.7), (5.3, 5.5, 4.8, 4.9)]),
    ('Bullish Harami Cross', [(5.8, 6.0, 4.4, 4.5), (5.0, 5.3, 4.7, 5.0)]),
    ('Bearish Harami Cross', [(4.5, 5.8, 4.3, 5.7), (5.0, 5.3, 4.7, 5.0)]),
    ('Piercing Pattern (bull)', [(5.5, 5.6, 4.4, 4.5), (4.3, 5.2, 4.2, 5.1)]),
    ('Dark-Cloud Cover (bear)', [(4.5, 5.7, 4.4, 5.6), (5.9, 6.0, 4.7, 4.8)]),
    ('Tweezer Top', [(4.5, 5.8, 4.4, 5.5), (5.5, 5.8, 4.6, 4.7)]),
    ('Tweezer Bottom', [(5.5, 5.6, 4.2, 4.5), (4.5, 5.4, 4.2, 5.3)]),
    ('Bullish Kicker', [(5.5, 5.6, 5.0, 5.0), (5.8, 6.0, 5.8, 6.0)]),
    ('Bearish Kicker', [(5.0, 5.5, 5.0, 5.5), (4.7, 4.7, 4.2, 4.2)]),
    ('Inside Bar', [(4.4, 5.8, 4.2, 5.6), (5.0, 5.4, 4.6, 5.2)]),
    ('Outside Bar', [(4.7, 5.3, 4.6, 5.2), (5.4, 5.9, 4.1, 4.3)]),

    # === THREE-CANDLE (12) ===
    ('Morning Star', [(5.6, 5.8, 4.4, 4.5), (4.4, 4.5, 4.0, 4.2), (4.5, 5.7, 4.4, 5.6)]),
    ('Evening Star', [(4.4, 5.6, 4.3, 5.5), (5.7, 6.0, 5.6, 5.8), (5.6, 5.7, 4.3, 4.4)]),
    ('Morning Doji Star', [(5.6, 5.8, 4.4, 4.5), (4.3, 4.5, 4.0, 4.31), (4.5, 5.7, 4.4, 5.6)]),
    ('Evening Doji Star', [(4.4, 5.6, 4.3, 5.5), (5.7, 6.0, 5.6, 5.71), (5.6, 5.7, 4.3, 4.4)]),
    ('Three White Soldiers', [(4.3, 5.0, 4.2, 4.9), (4.7, 5.5, 4.6, 5.4), (5.2, 5.9, 5.1, 5.8)]),
    ('Three Black Crows', [(5.7, 5.8, 5.0, 5.1), (5.2, 5.3, 4.5, 4.6), (4.7, 4.8, 4.0, 4.1)]),
    ('Three Inside Up', [(5.7, 5.8, 4.5, 4.6), (4.9, 5.3, 4.8, 5.2), (5.2, 5.9, 5.0, 5.8)]),
    ('Three Inside Down', [(4.5, 5.7, 4.4, 5.6), (5.3, 5.4, 4.9, 5.0), (4.9, 5.0, 4.1, 4.2)]),
    ('Three Outside Up', [(5.5, 5.6, 4.7, 4.8), (4.7, 5.9, 4.6, 5.8), (5.7, 6.1, 5.6, 6.0)]),
    ('Three Outside Down', [(4.5, 5.4, 4.4, 5.3), (5.4, 5.5, 4.2, 4.3), (4.3, 4.4, 3.9, 4.0)]),
    ('Abandoned Baby (bull)', [(5.7, 5.8, 4.5, 4.6), (4.2, 4.3, 4.0, 4.21), (4.7, 5.8, 4.6, 5.7)]),
    ('Abandoned Baby (bear)', [(4.5, 5.6, 4.4, 5.5), (5.9, 6.0, 5.8, 5.91), (5.4, 5.5, 4.4, 4.5)]),
]

n = len(patterns)
ncols = 6
nrows = (n + ncols - 1) // ncols   # 36/6 = 6

print(f"Rendering {n} patterns in {nrows}×{ncols} grid...")
fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 2.4, nrows * 2.6))

for idx, (name, candles) in enumerate(patterns):
    ax = axes[idx // ncols, idx % ncols]
    n_c = len(candles)
    # Расположим свечи по X в центре
    for k, (o, h, l, c) in enumerate(candles):
        x = k + 0.5
        draw_candle(ax, x, o, h, l, c, w=0.6)
    ax.set_xlim(-0.3, n_c + 0.3)
    # Y лимиты по всем свечам с padding
    all_y = [v for c_ in candles for v in c_]
    ymin, ymax = min(all_y), max(all_y)
    pad = (ymax - ymin) * 0.25 + 0.1
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(name, fontsize=10, fontweight='bold', pad=4)
    # Подписать число свечей в углу
    ax.text(0.97, 0.03, f"{n_c}", transform=ax.transAxes,
            fontsize=7, color='#888', ha='right', va='bottom')
    # Тонкая рамка
    for spine in ax.spines.values():
        spine.set_linewidth(0.5); spine.set_color('#aaa')

# Скрыть пустые ячейки если есть
for k in range(n, nrows * ncols):
    axes[k // ncols, k % ncols].axis('off')

fig.suptitle('Свечные паттерны — каталог уверенно реализуемых детекторов (~36)',
             fontsize=14, fontweight='bold', y=0.995)
plt.tight_layout(rect=[0, 0, 1, 0.985])
plt.savefig(OUT, dpi=100, facecolor='white')
print(f"Saved: {OUT}")
