"""Визуализация 5 вариантов Force function для maxV.

Example: 2026-02-06 D candle, LEVEL=61734, ZONE=[60000, 63075].
Все 5 функций нормированы к peak=1.0 на LEVEL.
"""
from __future__ import annotations
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

LEVEL = 61734.0
ZONE_LO = 60000.0
ZONE_HI = 63075.0

# Symmetric: R = max distance to zone boundary
R = max(LEVEL - ZONE_LO, ZONE_HI - LEVEL)

# 5 force variants
def f_linear(p):
    """Triangular: f = 1 - |Δ|/R, clipped to [0,1]"""
    delta = abs(p - LEVEL)
    return max(0.0, 1.0 - delta / R)

def f_quadratic(p):
    """f = max(0, 1 - (Δ/R)²) — flatter near peak, falls faster at edges"""
    delta = abs(p - LEVEL)
    return max(0.0, 1.0 - (delta / R) ** 2)

def f_gaussian(p, sigma_frac=0.5):
    """Bell: f = exp(-(Δ/σ)²) — σ = sigma_frac × R"""
    sigma = R * sigma_frac
    delta = abs(p - LEVEL)
    return math.exp(-((delta / sigma) ** 2))

def f_exp(p, tau_frac=0.5):
    """Exp decay: f = exp(-|Δ|/τ) — τ = tau_frac × R"""
    tau = R * tau_frac
    delta = abs(p - LEVEL)
    return math.exp(-delta / tau)

def f_step(p):
    """Binary: f = 1 if |Δ| < R else 0"""
    return 1.0 if abs(p - LEVEL) <= R else 0.0


# Plot range
y_lo = LEVEL - R * 1.5
y_hi = LEVEL + R * 1.5
prices = np.linspace(y_lo, y_hi, 500)

variants = [
    ("Linear (triangular)", f_linear, "tab:blue", "f = 1 − |Δ|/R"),
    ("Quadratic", f_quadratic, "tab:orange", "f = 1 − (Δ/R)²"),
    ("Gaussian σ=R/2", lambda p: f_gaussian(p, 0.5), "tab:green", "f = e^(−(Δ/σ)²)"),
    ("Gaussian σ=R/3", lambda p: f_gaussian(p, 1/3), "tab:olive", "σ=R/3 (более узкий)"),
    ("Exp decay τ=R/2", lambda p: f_exp(p, 0.5), "tab:red", "f = e^(−|Δ|/τ)"),
    ("Step (binary)", f_step, "tab:purple", "f = 1 if in zone else 0"),
]

fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(15, 9))

# LEFT: all variants overlaid (force as function of price)
for label, func, color, formula in variants:
    forces = [func(p) for p in prices]
    ax_left.plot(forces, prices, label=f"{label}: {formula}", color=color, lw=2)

ax_left.axhline(LEVEL, color="black", lw=1.5, ls="-", alpha=0.6, label=f"LEVEL={LEVEL:.0f}")
ax_left.axhline(ZONE_LO, color="gray", lw=1, ls="--", alpha=0.5, label=f"ZONE LO={ZONE_LO:.0f}")
ax_left.axhline(ZONE_HI, color="gray", lw=1, ls="--", alpha=0.5, label=f"ZONE HI={ZONE_HI:.0f}")
ax_left.set_xlabel("Force (0..1)")
ax_left.set_ylabel("Price (USD)")
ax_left.set_title(f"5 variants Force function — overlay\nLEVEL={LEVEL:.0f}, ZONE=[{ZONE_LO:.0f}, {ZONE_HI:.0f}], R={R:.0f}")
ax_left.legend(loc="upper right", fontsize=9)
ax_left.grid(alpha=0.3)
ax_left.set_ylim(y_lo, y_hi)
ax_left.set_xlim(-0.05, 1.1)

# RIGHT: small multiples (each variant separately)
ax_right.remove()
gs = fig.add_gridspec(3, 2, left=0.55, right=0.97, top=0.92, bottom=0.07, hspace=0.4, wspace=0.3)
for i, (label, func, color, formula) in enumerate(variants):
    r_, c_ = divmod(i, 2)
    ax = fig.add_subplot(gs[r_, c_])
    forces = [func(p) for p in prices]
    ax.fill_betweenx(prices, 0, forces, alpha=0.4, color=color)
    ax.plot(forces, prices, color=color, lw=2)
    ax.axhline(LEVEL, color="black", lw=1, ls="-", alpha=0.5)
    ax.axhline(ZONE_LO, color="gray", lw=0.8, ls="--", alpha=0.4)
    ax.axhline(ZONE_HI, color="gray", lw=0.8, ls="--", alpha=0.4)
    ax.set_title(f"{label}\n{formula}", fontsize=10)
    ax.set_ylim(y_lo, y_hi)
    ax.set_xlim(0, 1.1)
    ax.tick_params(labelsize=8)
    if r_ == 2: ax.set_xlabel("Force", fontsize=9)
    if c_ == 0: ax.set_ylabel("Price", fontsize=9)
    ax.grid(alpha=0.3)

plt.suptitle("maxV Force Function Variants (Q1)", fontsize=13, y=0.985)

out = Path.home() / "Desktop" / "maxv_force_variants.png"
plt.savefig(out, dpi=130, bbox_inches="tight")
print(f"Saved → {out}")

# Print key properties
print("\n=== Force values at example prices ===")
print(f"{'Price':<10} | " + " | ".join(f"{lbl[:18]:<18}" for lbl, _, _, _ in variants))
print("-" * (12 + 22 * len(variants)))
for p in [60000, 60500, 61000, 61500, LEVEL, 62500, 63075, 63500, 64000]:
    row = f"${p:<9.0f} | " + " | ".join(f"{func(p):<18.3f}" for _, func, _, _ in variants)
    print(row)
