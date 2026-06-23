"""BTC-only canon PNG: 24 types (count + WR + EV + ΣR + R%).

Data hardcoded из старого канон-скрипта (на момент 2 недели назад).
"""
import pathlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = pathlib.Path.home() / "smc-lib/projects/ob_vc/data/ob_vc_2h_24_btc_canon.png"

DATA = {
    "T1a": 272, "T1b": 107, "T2":  179,
    "T3a": 329, "T3b": 143, "T4":  259,
    "T5a": 223, "T5b": 111, "T6":  161,
    "T7a": 393, "T7b": 246, "T8":  297,
    "T9a": 276, "T9b": 99,  "T10": 183,
    "T11a":334, "T11b":158, "T12": 298,
    "T13a":211, "T13b":112, "T14": 128,
    "T15a":404, "T15b":170, "T16": 285,
}
TBM = {   # (WR%, EV, ΣR)
    "T1a": (53.3, +0.065, +17),  "T1b": (58.0, +0.160, +16),  "T2":  (58.3, +0.166, +29),
    "T3a": (52.0, +0.040, +13),  "T3b": (50.7, +0.015,  +2),  "T4":  (51.4, +0.029,  +7),
    "T5a": (57.1, +0.143, +30),  "T5b": (45.2, -0.096, -10),  "T6":  (54.5, +0.090, +14),
    "T7a": (62.0, +0.240, +87),  "T7b": (52.3, +0.046, +11),  "T8":  (58.7, +0.175, +50),
    "T9a": (56.8, +0.135, +36),  "T9b": (51.6, +0.032,  +3),  "T10": (46.9, -0.062, -11),
    "T11a":(54.7, +0.095, +30),  "T11b":(51.0, +0.020,  +3),  "T12": (51.6, +0.032,  +9),
    "T13a":(51.3, +0.025,  +5),  "T13b":(56.8, +0.135, +15),  "T14": (51.3, +0.025,  +3),
    "T15a":(52.3, +0.046, +18),  "T15b":(47.8, -0.044,  -7),  "T16": (53.4, +0.069, +19),
}
RPCT = {
    "T1a": 1.03, "T1b": 0.85, "T2":  0.98, "T3a": 0.88, "T3b": 0.65, "T4":  0.99,
    "T5a": 0.63, "T5b": 0.54, "T6":  0.54, "T7a": 0.60, "T7b": 0.49, "T8":  0.57,
    "T9a": 0.89, "T9b": 0.79, "T10": 0.88, "T11a":0.74, "T11b":0.66, "T12": 0.78,
    "T13a":0.60, "T13b":0.49, "T14": 0.69, "T15a":0.50, "T15b":0.50, "T16": 0.48,
}

# Group LONG / SHORT × swept (4 sub-groups per direction)
# T1-T4   LONG  no-swept
# T5-T8   LONG  swept
# T9-T12  SHORT no-swept
# T13-T16 SHORT swept
# Each group has 3 types: Ta/Tb (extreme=prev split) + Tcur (extreme=cur)
GROUPS = [
    ("LONG  no-swept  n=1",   ["T1a","T1b","T2"]),
    ("LONG  no-swept  n=2",   ["T3a","T3b","T4"]),
    ("LONG  swept     n=1",   ["T5a","T5b","T6"]),
    ("LONG  swept     n=2",   ["T7a","T7b","T8"]),
    ("SHORT no-swept  n=1",   ["T9a","T9b","T10"]),
    ("SHORT no-swept  n=2",   ["T11a","T11b","T12"]),
    ("SHORT swept     n=1",   ["T13a","T13b","T14"]),
    ("SHORT swept     n=2",   ["T15a","T15b","T16"]),
]

def color_wr(wr):
    if wr >= 60: return "#27ae60"
    if wr >= 55: return "#7cb342"
    if wr >= 50: return "#f1c40f"
    if wr >= 45: return "#e67e22"
    return "#c0392b"

fig, ax = plt.subplots(figsize=(22, 12))
ax.set_xlim(0, 22); ax.set_ylim(0, 12)
ax.set_aspect("auto")
ax.axis("off")

# Title
ax.text(11, 11.6, "ob_vc 2h — 24 types BTC canon (TBM TP1R, 6y)", ha='center', fontsize=18, fontweight='bold')

# Layout: 8 groups in 2 rows of 4
# Each group occupies w=5.0 h=4.8, 3 sub-cards inside
gw, gh = 5.2, 4.8
xs = [0.4, 5.8, 11.2, 16.6]
ys = [5.8, 0.4]  # row 0 = top (LONG groups), row 1 = bottom (SHORT groups)

for i, (title, types) in enumerate(GROUPS):
    row = 0 if i < 4 else 1
    col = i % 4
    gx, gy = xs[col], ys[row]
    is_long = title.startswith("LONG")
    hdr_color = "#1976d2" if is_long else "#c62828"
    # Header box
    ax.add_patch(FancyBboxPatch((gx, gy + gh - 0.6), gw, 0.55, boxstyle="round,pad=0.02",
                                  facecolor=hdr_color, edgecolor='black', linewidth=1.0))
    ax.text(gx + gw/2, gy + gh - 0.33, title, ha='center', va='center',
             fontsize=11, fontweight='bold', color='white')
    # 3 cards per group
    cw, ch = (gw - 0.4) / 3, gh - 0.9
    for j, t in enumerate(types):
        cx = gx + 0.1 + j * (cw + 0.05)
        cy = gy + 0.1
        n = DATA[t]
        wr, ev, sumr = TBM[t]
        rpct = RPCT[t]
        # Card background
        ax.add_patch(FancyBboxPatch((cx, cy), cw, ch, boxstyle="round,pad=0.02",
                                      facecolor='#fafafa', edgecolor='#666', linewidth=1.0))
        # Type label
        ax.text(cx + cw/2, cy + ch - 0.35, t, ha='center', va='center',
                 fontsize=13, fontweight='bold', color='#222')
        # Count
        ax.text(cx + cw/2, cy + ch - 0.85, f"N={n}", ha='center', va='center',
                 fontsize=12, fontweight='bold', color='#333')
        # WR pill
        ax.add_patch(FancyBboxPatch((cx + 0.15, cy + ch - 1.75), cw - 0.3, 0.45,
                                      boxstyle="round,pad=0.02", facecolor=color_wr(wr),
                                      edgecolor='black', linewidth=0.7))
        ax.text(cx + cw/2, cy + ch - 1.52, f"WR {wr:.1f}%", ha='center', va='center',
                 fontsize=10, fontweight='bold', color='white')
        # EV
        ev_color = "#27ae60" if ev > 0 else "#c0392b"
        ax.text(cx + cw/2, cy + ch - 2.1, f"EV {ev:+.3f}", ha='center', va='center',
                 fontsize=10, color=ev_color, fontweight='bold')
        # ΣR
        sr_color = "#27ae60" if sumr > 0 else "#c0392b"
        ax.text(cx + cw/2, cy + ch - 2.5, f"ΣR {sumr:+.0f}", ha='center', va='center',
                 fontsize=11, color=sr_color, fontweight='bold')
        # R%
        ax.text(cx + cw/2, cy + 0.2, f"R% {rpct:.2f}", ha='center', va='center',
                 fontsize=9, color='#555')

# Totals
total_n = sum(DATA.values())
total_sumR = sum(t[2] for t in TBM.values())
avg_wr = sum(DATA[k] * TBM[k][0] for k in DATA) / total_n
ax.text(11, 0.05, f"TOTAL: N={total_n:,}  weighted WR={avg_wr:.1f}%  ΣR={total_sumR:+.0f}",
         ha='center', fontsize=13, fontweight='bold', color='#1a237e')

plt.tight_layout()
plt.savefig(OUT, dpi=130, bbox_inches='tight')
print(f"Saved → {OUT}")
print(f"Total: N={total_n}, avg WR={avg_wr:.2f}%, ΣR={total_sumR:+}")
