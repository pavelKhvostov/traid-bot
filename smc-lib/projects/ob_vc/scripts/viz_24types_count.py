"""PNG canon: count per 24 types ob_vc."""
import pathlib
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

P = pathlib.Path.home() / "smc-lib/projects/ob_vc/data/ob_vc_24types_classified.parquet"
OUT = pathlib.Path.home() / "smc-lib/projects/ob_vc/data/ob_vc_24types_count.png"

df = pd.read_parquet(P)
print(f"Total: {len(df):,} unique OBs")

# Group counts (ordered: direction × swept × n_FVG × extreme × wick)
order = []
for direction in ['long','short']:
    for swept in [False, True]:
        for n_fvg in [1, 2]:
            for extreme in ['prev','cur']:
                if extreme == 'prev':
                    for wick in ['a','b']:
                        order.append((direction, swept, n_fvg, extreme, wick))
                else:
                    order.append((direction, swept, n_fvg, extreme, ''))

# Aggregate
g = df.groupby(['direction','swept','n_fvg_proxy','extreme','wick_suffix']).size()
labels = []; counts = []; colors = []
for key in order:
    d, sw, nf, ext, wk = key
    label = f"{d[:1].upper()}_{'sw' if sw else 'nsw'}_n{nf}_{ext}{wk}"
    labels.append(label)
    try:
        cnt = int(g.loc[(d, sw, nf, ext, wk)])
    except KeyError:
        cnt = 0
    counts.append(cnt)
    # Color: long blue family, short red family; shade by swept yes/no
    if d == 'long':
        colors.append('#1976d2' if sw else '#64b5f6')
    else:
        colors.append('#c62828' if sw else '#ef9a9a')

fig, ax = plt.subplots(figsize=(18, 8))
x = np.arange(len(labels))
bars = ax.bar(x, counts, color=colors, edgecolor='black', linewidth=0.5)
for bar, cnt in zip(bars, counts):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 20, str(cnt),
            ha='center', va='bottom', fontsize=8, fontweight='bold')

ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=60, ha='right', fontsize=9)
ax.set_ylabel("Count of unique OBs (6.5y BTC, dedup HTF×LTF)")
ax.set_title(f"ob_vc 24-types classification | n={len(df):,} unique OBs (6.5y BTC)")
ax.grid(axis='y', alpha=0.3)

# Legend by color
from matplotlib.patches import Patch
legend = [
    Patch(color='#1976d2', label='LONG swept'),
    Patch(color='#64b5f6', label='LONG no-swept'),
    Patch(color='#c62828', label='SHORT swept'),
    Patch(color='#ef9a9a', label='SHORT no-swept'),
]
ax.legend(handles=legend, loc='upper right')
plt.tight_layout()
plt.savefig(OUT, dpi=130, bbox_inches='tight')
print(f"Saved → {OUT}")
