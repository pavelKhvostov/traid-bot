"""Визуализация maxV как зоны с peak force в level и убыванием к границам zone.

Пример: D candle 2026-02-06 BTC. max-vol 32m LTF bar.

Layout:
  Left:  D candle OHLC vertical view + maxV zone overlay (gradient)
  Right: force profile (triangle/bell) along price axis
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.collections import LineCollection

MSK = timezone(timedelta(hours=3))
MS_M = 60_000

CSV = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
D_DATE = "2026-02-06"
LTF_MIN = 32

# Load D candle data
D_start = int(datetime.fromisoformat(D_DATE).replace(tzinfo=timezone.utc).timestamp() * 1000)
D_end = D_start + 24*3600*1000
rows_1m = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        ts = int(t.timestamp() * 1000)
        if ts < D_start: continue
        if ts >= D_end: break
        rows_1m.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

# D OHLC
D_o = rows_1m[0][1]
D_h = max(r[2] for r in rows_1m)
D_l = min(r[3] for r in rows_1m)
D_c = rows_1m[-1][4]

# Aggregate to 32m LTF
ltf = []; cb = None; oo = hh = ll = cc = 0.0; vv = 0.0
for ts, o, h, l, c, v in rows_1m:
    b = ts - ((ts - D_start) % (LTF_MIN * MS_M))
    if b != cb:
        if cb is not None: ltf.append((cb, oo, hh, ll, cc, vv))
        cb = b; oo, hh, ll, cc, vv = o, h, l, c, v
    else:
        hh = max(hh, h); ll = min(ll, l); cc = c; vv += v
if cb is not None: ltf.append((cb, oo, hh, ll, cc, vv))

# Max-vol LTF bar
mb = max(ltf, key=lambda b: b[5])
mb_ts, mb_o, mb_h, mb_l, mb_c, mb_v = mb
mb_dir = "BULL" if mb_c > mb_o else "BEAR"
LEVEL = mb_c
ZONE_LO = mb_l
ZONE_HI = mb_h

mb_dt = datetime.fromtimestamp(mb_ts/1000, tz=timezone.utc).astimezone(MSK)

print(f"D {D_DATE} ({mb_dir}) — max-vol {LTF_MIN}m LTF bar:")
print(f"  Time: {mb_dt.strftime('%H:%M MSK')}  V={mb_v:.0f}")
print(f"  OHLC: O={mb_o:.0f} H={mb_h:.0f} L={mb_l:.0f} C={mb_c:.0f}")
print(f"  LEVEL (close, peak force) = {LEVEL:.0f}")
print(f"  ZONE = [{ZONE_LO:.0f} .. {ZONE_HI:.0f}] = ${ZONE_HI-ZONE_LO:.0f}")

# Build figure
fig, (ax_candle, ax_force) = plt.subplots(1, 2, figsize=(14, 8),
                                            gridspec_kw={"width_ratios": [2, 1]},
                                            sharey=True)

# --- LEFT: D candle + maxV zone overlay ---
# Y range
y_lo, y_hi = D_l * 0.99, D_h * 1.01

# Draw maxV zone as gradient (peak at LEVEL, fade to ZONE boundaries)
N_GRAD = 100
y_grad = np.linspace(ZONE_LO, ZONE_HI, N_GRAD)
# Triangular force: max at LEVEL, 0 at boundaries
force = np.zeros_like(y_grad)
for i, y in enumerate(y_grad):
    if y <= LEVEL:
        force[i] = (y - ZONE_LO) / max(LEVEL - ZONE_LO, 1)
    else:
        force[i] = (ZONE_HI - y) / max(ZONE_HI - LEVEL, 1)
force = np.clip(force, 0, 1)

# Plot as horizontal colored band
for i in range(N_GRAD - 1):
    intensity = force[i]
    color = (1.0, 0.5 - 0.3*intensity, 0.0, 0.15 + 0.55*intensity)  # orange→red
    ax_candle.axhspan(y_grad[i], y_grad[i+1], facecolor=color, edgecolor='none')

# D candle drawing
x_center = 0.5
# Wick
ax_candle.plot([x_center, x_center], [D_l, D_h], color="black", lw=1.5)
# Body
body_color = "green" if D_c > D_o else "red"
ax_candle.add_patch(Rectangle((x_center - 0.15, min(D_o, D_c)),
                                0.3, abs(D_c - D_o),
                                facecolor=body_color, edgecolor="black", alpha=0.7))

# Annotate LEVEL
ax_candle.axhline(LEVEL, color="darkred", lw=2, ls="-", alpha=0.8)
ax_candle.text(0.05, LEVEL, f" maxV LEVEL = ${LEVEL:.0f}\n  (peak force)",
                va="center", ha="left", fontsize=10, fontweight="bold", color="darkred",
                bbox=dict(facecolor="white", alpha=0.8, edgecolor="darkred"))

# Annotate ZONE boundaries
for y, lbl, off in [(ZONE_LO, f"ZONE LOW = ${ZONE_LO:.0f}", -0.005),
                     (ZONE_HI, f"ZONE HIGH = ${ZONE_HI:.0f}", 0.005)]:
    ax_candle.axhline(y, color="orange", lw=1, ls="--", alpha=0.6)
    ax_candle.text(0.95, y + (y_hi - y_lo) * off, lbl,
                    va="center", ha="right", fontsize=9, color="darkorange",
                    bbox=dict(facecolor="white", alpha=0.7, edgecolor="orange"))

# D OHLC annotations
for y, lbl in [(D_h, f" H={D_h:.0f}"), (D_l, f" L={D_l:.0f}"),
                (D_o, f" O={D_o:.0f}"), (D_c, f" C={D_c:.0f}")]:
    ax_candle.text(x_center + 0.2, y, lbl, va="center", ha="left", fontsize=9)

ax_candle.set_xlim(0, 1.5)
ax_candle.set_ylim(y_lo, y_hi)
ax_candle.set_title(f"D candle {D_DATE} (03:00 MSK) + maxV zone overlay\n"
                     f"max-vol {LTF_MIN}m LTF bar @ {mb_dt.strftime('%H:%M MSK')}, V={mb_v:.0f}",
                     fontsize=11)
ax_candle.set_ylabel("Price (USD)")
ax_candle.set_xticks([])
ax_candle.grid(True, axis="y", alpha=0.3)

# --- RIGHT: force profile (triangle along price) ---
ax_force.fill_betweenx(y_grad, 0, force, alpha=0.5, color="orange", label="maxV force intensity")
ax_force.plot(force, y_grad, color="darkred", lw=2)
ax_force.axhline(LEVEL, color="darkred", lw=2, ls="-", alpha=0.8)
ax_force.text(1.02, LEVEL, f"LEVEL={LEVEL:.0f}\npeak=1.0", va="center", ha="left", fontsize=9, color="darkred")
ax_force.axhline(ZONE_LO, color="orange", lw=1, ls="--", alpha=0.6)
ax_force.text(1.02, ZONE_LO, f"ZONE LO\nforce=0", va="center", ha="left", fontsize=8, color="darkorange")
ax_force.axhline(ZONE_HI, color="orange", lw=1, ls="--", alpha=0.6)
ax_force.text(1.02, ZONE_HI, f"ZONE HI\nforce=0", va="center", ha="left", fontsize=8, color="darkorange")
ax_force.set_xlim(0, 1.2)
ax_force.set_xlabel("Force (0..1)")
ax_force.set_title(f"maxV Force Profile (triangular)\npeak at LEVEL, fades to 0 at ZONE boundaries", fontsize=11)
ax_force.grid(True, alpha=0.3)

plt.tight_layout()
out = Path.home() / "Desktop" / f"maxV_zone_{D_DATE}.png"
plt.savefig(out, dpi=130, bbox_inches="tight")
print(f"\nSaved → {out}")
