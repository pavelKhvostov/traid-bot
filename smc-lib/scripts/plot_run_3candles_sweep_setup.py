"""Иллюстрация setup для run_3candles_sweep (3-candle pattern с sweep c1).

SHORT условия:
  1. c1, c2, c3 — все bear (3 подряд)
  2. c2.high > c1.high                  ← sweep c1 high (liquidity grab)
  3. c2.upper_wick ≥ 2.5 × c2.body

Setup:
  Entry = max(c2.o, c2.c) + 0.3 × upper_wick
  SL    = c2.high
  TP    = c3.low
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pathlib

OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/run_3candles_sweep_setup.png"

# Synthetic candles
candles = [
    {"label":"C1", "open":120, "high":122, "low":115, "close":116},  # bear
    {"label":"C2", "open":116, "high":128, "low":110, "close":112},  # bear, sweep c1.high, big wick
    {"label":"C3", "open":112, "high":113, "low":104, "close":105},  # bear (continuation)
]

c1 = candles[0]
c2 = candles[1]
c3 = candles[2]

c2_body_top = max(c2["open"], c2["close"])
upper_wick = c2["high"] - c2_body_top
body = abs(c2["open"] - c2["close"])
ratio = upper_wick / body
entry = c2_body_top + 0.3 * upper_wick
sl = c2["high"]
tp = c3["low"]
risk = sl - entry
reward = entry - tp
rr = reward / risk

fig, ax = plt.subplots(figsize=(13, 9))
fig.patch.set_facecolor('#0e1117')
ax.set_facecolor('#0e1117')

width = 0.5
for i, c in enumerate(candles):
    x = i + 1
    color = '#ef5350'  # bear
    body_lo, body_hi = min(c["open"], c["close"]), max(c["open"], c["close"])
    ax.plot([x, x], [c["low"], c["high"]], color=color, lw=1.5, zorder=2)
    rect = mpatches.Rectangle((x - width/2, body_lo), width, max(body_hi - body_lo, 0.1),
                              facecolor=color, edgecolor=color, lw=1, zorder=3)
    ax.add_patch(rect)
    ax.text(x, c["low"] - 1.5, c["label"], color='white', fontsize=16, ha='center', fontweight='bold')

# C1.high level — the level swept
ax.axhline(c1["high"], color='#9c27b0', lw=1.5, ls=':', alpha=0.8, zorder=4)
ax.text(0.3, c1["high"], f' C1.high\n {c1["high"]}\n (swept by C2)', color='#9c27b0',
        fontsize=10, va='center', fontweight='bold')

# Sweep zone highlight (C1.high to C2.high)
sweep_zone = mpatches.Rectangle((2 - width/2 - 0.05, c1["high"]), width + 0.1, c2["high"] - c1["high"],
                                  facecolor='#9c27b0', alpha=0.2, edgecolor='none', zorder=1)
ax.add_patch(sweep_zone)
ax.text(2.4, (c1["high"] + c2["high"]) / 2, 'sweep zone\n(C2.high > C1.high)',
        color='#ce93d8', fontsize=9, va='center')

# Wick area C2 highlight (full wick)
wick_lo = c2_body_top
wick_hi = c2["high"]
rect_wick = mpatches.Rectangle((2 - width/2 - 0.05, wick_lo), width + 0.1, wick_hi - wick_lo,
                                facecolor='#ffeb3b', alpha=0.12, edgecolor='none', zorder=1)
ax.add_patch(rect_wick)

# Setup lines
ax.axhline(entry, color='#ffeb3b', lw=1.8, ls='--', alpha=0.9, zorder=5)
ax.text(0.3, entry, f' Entry\n {entry:.1f}\n (0.3 × wick C2)', color='#ffeb3b',
        fontsize=11, va='center', fontweight='bold')
ax.axhline(sl, color='#ef5350', lw=2, ls='-', alpha=0.9, zorder=5)
ax.text(0.3, sl, f' SL\n {sl}\n (C2.high)', color='#ef5350',
        fontsize=11, va='center', fontweight='bold')
ax.axhline(tp, color='#4caf50', lw=2, ls='-', alpha=0.9, zorder=5)
ax.text(0.3, tp, f' TP\n {tp}\n (C3.low)', color='#4caf50',
        fontsize=11, va='center', fontweight='bold')

# SHORT arrow
ax.annotate('', xy=(3.6, tp + 1), xytext=(3.6, entry - 1),
            arrowprops=dict(arrowstyle='->', color='#4caf50', lw=2.5, alpha=0.9))
ax.text(3.7, (entry + tp) / 2, ' SHORT\n trade direction', color='#4caf50',
        fontsize=11, va='center', fontweight='bold')

# Stats
ax.text(0.5, 102, f'Условия:\n• 3 bear подряд ✓\n• C2.high ({c2["high"]}) > C1.high ({c1["high"]}) ✓  sweep c1\n• C2 upper_wick ({upper_wick}) ≥ 2.5 × body ({body}) → ratio {ratio:.1f}× ✓\n\nRisk = {risk:.1f}  |  Reward = {reward:.1f}  |  R:R = {rr:.2f}',
        color='white', fontsize=10, fontweight='bold', va='top',
        bbox=dict(facecolor='#1e2128', edgecolor='#444', alpha=0.9, pad=8))

ax.set_title('run_3candles_sweep (SHORT) — 3-candle liquidity grab continuation\n'
             '3 bear + sweep C1 high + C2 wick ≥ 2.5× body',
             color='white', fontsize=14, fontweight='bold', pad=20)
ax.set_xlim(0, 5)
ax.set_ylim(100, 135)
ax.set_xticks([])
ax.set_ylabel('Price', color='white')
ax.tick_params(colors='white')
for spine in ax.spines.values(): spine.set_color('#444')
ax.grid(True, color='#222', lw=0.5, alpha=0.5, axis='y')

plt.tight_layout()
OUT.parent.mkdir(exist_ok=True, parents=True)
plt.savefig(OUT, dpi=130, facecolor='#0e1117')
print(f"Saved: {OUT}")
print(f"\nLevels:")
print(f"  C1.high (swept):     {c1['high']}")
print(f"  C2.high (sweep top): {c2['high']}")
print(f"  C2 upper_wick / body: {upper_wick} / {body} = {ratio:.1f}×")
print(f"  Entry: {entry:.1f}, SL: {sl}, TP: {tp}, R:R: {rr:.2f}")
