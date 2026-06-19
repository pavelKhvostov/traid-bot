"""Amplified Force visualization — Gaussian × W_position × W_age.

Show 6 example maxV's with different (position, age) combos centered at same
LEVEL — peak height = amplified force = signal strength.

Gaussian base × W_pos × W_age:
  W_pos = 1.5 if wick else 0.7
  W_age = 1 + 0.3 × ln(1 + days/30)
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# Common LEVEL for all examples (для прямого сравнения)
LEVEL = 70000.0
ZONE_LO = 69000.0
ZONE_HI = 71000.0
R = max(LEVEL - ZONE_LO, ZONE_HI - LEVEL)  # 1000
SIGMA = R / 2  # Gaussian sigma

def base_force(price):
    """Gaussian σ=R/2"""
    return math.exp(-((price - LEVEL) / SIGMA) ** 2)

def w_pos(position):
    return 1.5 if "wick" in position else 0.7

def w_age(days):
    return 1 + 0.3 * math.log(1 + days / 30)

# Examples
examples = [
    ("body_top + fresh (1d)",       "body_top",    1,   "tab:gray"),
    ("body_bottom + fresh (1d)",    "body_bottom", 1,   "tab:olive"),
    ("upper_wick + fresh (1d)",     "upper_wick",  1,   "tab:blue"),
    ("lower_wick + fresh (1d)",     "lower_wick",  1,   "tab:cyan"),
    ("upper_wick + aged (90d)",     "upper_wick",  90,  "tab:red"),
    ("lower_wick + aged (120d)",    "lower_wick",  120, "tab:purple"),
    ("upper_wick + veteran (365d)", "upper_wick",  365, "darkred"),
]

# Compute amplified force profiles
prices = np.linspace(ZONE_LO - R*0.5, ZONE_HI + R*0.5, 500)
profiles = []
for label, pos, age, color in examples:
    wp = w_pos(pos)
    wa = w_age(age)
    amp_total = wp * wa
    forces = np.array([base_force(p) * amp_total for p in prices])
    profiles.append((label, pos, age, color, forces, wp, wa, amp_total))

# Build figure
fig, (ax_main, ax_legend) = plt.subplots(1, 2, figsize=(14, 9),
                                          gridspec_kw={"width_ratios": [3, 1.5]})

# LEFT: all amplified bells overlaid
ax_main.axhline(LEVEL, color="black", lw=1.5, ls="-", alpha=0.7, label=f"LEVEL = {LEVEL:.0f}")
ax_main.axhline(ZONE_LO, color="gray", lw=1, ls="--", alpha=0.4, label=f"ZONE LO = {ZONE_LO:.0f}")
ax_main.axhline(ZONE_HI, color="gray", lw=1, ls="--", alpha=0.4, label=f"ZONE HI = {ZONE_HI:.0f}")

for label, pos, age, color, forces, wp, wa, amp in profiles:
    ax_main.fill_betweenx(prices, 0, forces, alpha=0.15, color=color)
    ax_main.plot(forces, prices, color=color, lw=2.5,
                  label=f"{label}: peak={amp:.2f}")

ax_main.set_xlabel("Amplified Force = base × W_pos × W_age", fontsize=11)
ax_main.set_ylabel("Price (USD)", fontsize=11)
ax_main.set_title("maxV Amplified Force — Gaussian σ=R/2 × W_position × W_age\n"
                   f"W_pos: wick=1.5, body=0.7   |   W_age = 1 + 0.3·ln(1 + days/30)",
                   fontsize=11)
ax_main.legend(loc="upper right", fontsize=8.5)
ax_main.grid(alpha=0.3)
ax_main.set_ylim(ZONE_LO - R*0.5, ZONE_HI + R*0.5)
ax_main.set_xlim(0, 3.0)

# RIGHT: table of weights
ax_legend.axis("off")
table_lines = ["Amplification table:\n"]
table_lines.append(f"{'Combo':<28} {'W_pos':<7} {'W_age':<7} {'Total':<8}")
table_lines.append("─" * 50)
for label, pos, age, color, forces, wp, wa, amp in profiles:
    table_lines.append(f"{label:<28} {wp:<7.2f} {wa:<7.3f} {amp:<8.3f}")

ax_legend.text(0.0, 0.9, "\n".join(table_lines), ha="left", va="top",
                family="monospace", fontsize=9.5,
                bbox=dict(facecolor="lightyellow", edgecolor="black", boxstyle="round,pad=0.5"))

# Show formula
formula_text = (
    "Formula:\n\n"
    "amplified_force(p) =\n"
    "  exp(-((p - LEVEL)/σ)²)\n"
    "  × W_pos(position)\n"
    "  × W_age(days)\n\n"
    "where:\n"
    f"  σ = R/2 = {SIGMA:.0f}\n"
    "  R = max(LEVEL-zone_lo,\n"
    "          zone_hi-LEVEL)\n\n"
    "W_pos:\n"
    "  wick:  1.5\n"
    "  body:  0.7\n\n"
    "W_age = 1 + 0.3·ln(1 + d/30)"
)
ax_legend.text(0.0, 0.35, formula_text, ha="left", va="top",
                family="monospace", fontsize=10,
                bbox=dict(facecolor="lightcyan", edgecolor="navy", boxstyle="round,pad=0.5"))

plt.tight_layout()
out = Path.home() / "Desktop" / "maxv_amplified_force.png"
plt.savefig(out, dpi=130, bbox_inches="tight")
print(f"Saved → {out}")

# Numeric table
print("\nAmplification breakdown:")
print(f"{'Combo':<32} {'W_pos':<7} {'W_age':<7} {'Total':<8}")
print("-" * 60)
for label, pos, age, color, forces, wp, wa, amp in profiles:
    print(f"{label:<32} {wp:<7.2f} {wa:<7.3f} {amp:<8.3f}")
