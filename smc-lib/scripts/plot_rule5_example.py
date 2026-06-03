"""График ситуации по Правилу 5 (основная стратегия ASVK).

Top candidate (из find_rule5_asvk_examples.py):
  1h LONG OB [67360.66, 68339.37], formation 2026-03-23 02:00 MSK
  Pullback в зону: 2026-03-23 09:36
  15m LONG VC FVG [67999.99, 68281.99], formation 2026-03-23 11:00
  Continuation за 48h: +5.85%
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.ob.code import detect_ob
from elements.fvg.code import detect_fvg
from vc.code import has_vc

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
OUT = pathlib.Path.home() / "Desktop/i-rdrb-charts/rule5_asvk_example.png"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
MS_H = 60*MS_M

# Параметры события
OB_TF_MS = 1*MS_H
OB_FORMATION_TS = int(datetime(2026,3,23,2,0,tzinfo=MSK).timestamp()*1000)  # close of cur+ 1h
PULLBACK_TS = int(datetime(2026,3,23,9,36,tzinfo=MSK).timestamp()*1000)
VC_FORMATION_TS = int(datetime(2026,3,23,11,0,tzinfo=MSK).timestamp()*1000)
OB_ZONE = (67360.66, 68339.37)
VC_FVG_ZONE = (67999.99, 68281.99)

# Окно chart: от 6h до OB до 30h после VC
T_LO = OB_FORMATION_TS - 8*MS_H
T_HI = VC_FORMATION_TS + 36*MS_H

print("Loading 1m...")
rows=[]
with CSV.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        t=datetime.fromisoformat(r[0])
        ts = int(t.timestamp()*1000)
        if ts < T_LO - MS_H or ts > T_HI + MS_H: continue
        rows.append((ts,float(r[1]),float(r[2]),float(r[3]),float(r[4])))

print(f"  bars in window: {len(rows)}")

# Aggregate to 15m for clearer chart
def agg(d, tfms, anchor=0):
    out=[]; cb=None; o=h=l=c=0.0
    for ts,oo,hh,ll,cc in d:
        b = ts - ((ts - anchor) % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c))
            cb=b; o,h,l,c=oo,hh,ll,cc
        else:
            h=max(h,hh); l=min(l,ll); c=cc
    if cb is not None: out.append((cb,o,h,l,c))
    return out

bars15 = agg(rows, 15*MS_M)
bars15 = [b for b in bars15 if T_LO <= b[0] <= T_HI]
print(f"  15m candles: {len(bars15)}")

# Найти OB на 1h: ищем prev (bear) + cur (bull, close > prev.open), close cur ≈ OB_FORMATION_TS - 1h
bars1h = agg(rows, 1*MS_H)
ob_cur_open_ts = OB_FORMATION_TS - 1*MS_H
ob_cur = next((b for b in bars1h if b[0] == ob_cur_open_ts), None)
ob_prev = next((b for b in bars1h if b[0] == ob_cur_open_ts - 1*MS_H), None)
print(f"  OB cur: {datetime.fromtimestamp(ob_cur[0]/1000,MSK)} OHLC=({ob_cur[1]:.2f},{ob_cur[2]:.2f},{ob_cur[3]:.2f},{ob_cur[4]:.2f})")
print(f"  OB prev: {datetime.fromtimestamp(ob_prev[0]/1000,MSK)} OHLC=({ob_prev[1]:.2f},{ob_prev[2]:.2f},{ob_prev[3]:.2f},{ob_prev[4]:.2f})")

# Найти конкретную VC FVG на 15m
bars15_full = bars15
vc_c1_ts = VC_FORMATION_TS - 3*15*MS_M  # c1 это 3 свечи назад от formation
vc_c1_idx = next((i for i,b in enumerate(bars15_full) if b[0] == vc_c1_ts), None)
if vc_c1_idx is not None:
    c1 = Candle(open=bars15_full[vc_c1_idx][1], high=bars15_full[vc_c1_idx][2], low=bars15_full[vc_c1_idx][3], close=bars15_full[vc_c1_idx][4], open_time=bars15_full[vc_c1_idx][0])
    c2 = Candle(open=bars15_full[vc_c1_idx+1][1], high=bars15_full[vc_c1_idx+1][2], low=bars15_full[vc_c1_idx+1][3], close=bars15_full[vc_c1_idx+1][4], open_time=bars15_full[vc_c1_idx+1][0])
    c3 = Candle(open=bars15_full[vc_c1_idx+2][1], high=bars15_full[vc_c1_idx+2][2], low=bars15_full[vc_c1_idx+2][3], close=bars15_full[vc_c1_idx+2][4], open_time=bars15_full[vc_c1_idx+2][0])
    fv = detect_fvg(c1,c2,c3)
    print(f"  VC FVG detect: {fv}")

# Plot
fig, ax = plt.subplots(figsize=(16, 9))
fig.patch.set_facecolor('#0e1117')
ax.set_facecolor('#0e1117')

x_vals = [datetime.fromtimestamp(b[0]/1000, MSK) for b in bars15]
width = timedelta(minutes=12)

for b, x in zip(bars15, x_vals):
    ts,o,h,l,c = b
    is_bull = c >= o
    color = '#26a69a' if is_bull else '#ef5350'
    body_lo, body_hi = min(o,c), max(o,c)
    ax.plot([x,x],[l,h], color=color, lw=0.6, zorder=2)
    rect = mpatches.Rectangle((x - width/2, body_lo), width, max(body_hi-body_lo, 1), facecolor=color, edgecolor=color, lw=0.5, zorder=3)
    ax.add_patch(rect)

# OB zone (1h)
ob_lo, ob_hi = OB_ZONE
ax.axhspan(ob_lo, ob_hi, xmin=0, xmax=1, color='#2962ff', alpha=0.12, zorder=1)
ax.axhline(ob_lo, color='#2962ff', lw=1.0, ls='--', alpha=0.6, zorder=1)
ax.axhline(ob_hi, color='#2962ff', lw=1.0, ls='--', alpha=0.6, zorder=1)

# VC FVG zone (15m)
fv_lo, fv_hi = VC_FVG_ZONE
ax.axhspan(fv_lo, fv_hi, xmin=0, xmax=1, color='#ffeb3b', alpha=0.25, zorder=1)

# Markers
ob_form_x = datetime.fromtimestamp(OB_FORMATION_TS/1000, MSK)
pb_x = datetime.fromtimestamp(PULLBACK_TS/1000, MSK)
vc_x = datetime.fromtimestamp(VC_FORMATION_TS/1000, MSK)

ax.axvline(ob_form_x, color='#2962ff', lw=1.5, alpha=0.7, ls='-')
ax.axvline(pb_x, color='#ff9800', lw=1.5, alpha=0.8, ls='-')
ax.axvline(vc_x, color='#ffeb3b', lw=1.8, alpha=0.9, ls='-')

# Labels
y_max = max(b[2] for b in bars15)
y_min = min(b[3] for b in bars15)
y_span = y_max - y_min
ax.text(ob_form_x, y_max - y_span*0.02, '  ① OB сформирована\n     (1h LONG)', color='#2962ff', fontsize=10, va='top', fontweight='bold')
ax.text(pb_x, y_max - y_span*0.10, '  ② Pullback в зону\n     (низ к OB)', color='#ff9800', fontsize=10, va='top', fontweight='bold')
ax.text(vc_x, y_max - y_span*0.18, '  ③ VC: 15m LONG FVG\n     ⊆ HTF OB.zone\n     → ENTRY LONG', color='#ffeb3b', fontsize=10, va='top', fontweight='bold')

# Continuation arrow
cont_x = vc_x + timedelta(hours=20)
cont_y = max(b[2] for b in bars15 if b[0] <= int(cont_x.timestamp()*1000))
entry_y = (ob_lo + ob_hi)/2
ax.annotate('', xy=(cont_x, cont_y), xytext=(vc_x, entry_y),
            arrowprops=dict(arrowstyle='->', color='#4caf50', lw=2.5, alpha=0.9))
ax.text(cont_x, cont_y, f'  ④ Continuation\n     +{((cont_y-entry_y)/entry_y*100):.2f}%', color='#4caf50', fontsize=11, va='center', fontweight='bold')

# Legend
ax.text(0.01, 0.99, 'Правило 5 — основная стратегия ASVK\nBTC 1h LONG OB + 15m LONG VC внутри\n2026-03-23 MSK', transform=ax.transAxes, color='white', fontsize=12, va='top', fontweight='bold', bbox=dict(facecolor='#1e2128', edgecolor='#444', alpha=0.9, pad=8))
ax.text(0.99, 0.01, f'HTF OB: [{ob_lo:.0f}, {ob_hi:.0f}]\nLTF VC FVG: [{fv_lo:.0f}, {fv_hi:.0f}]\nEntry mid: {entry_y:.0f}', transform=ax.transAxes, color='white', fontsize=10, va='bottom', ha='right', bbox=dict(facecolor='#1e2128', edgecolor='#444', alpha=0.9, pad=6))

ax.set_ylabel('BTC, USDT', color='white')
ax.tick_params(colors='white')
for spine in ax.spines.values(): spine.set_color('#444')
ax.grid(True, color='#222', lw=0.5, alpha=0.5)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M', tz=MSK))
ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
plt.setp(ax.get_xticklabels(), rotation=30, ha='right')

ax.set_xlim(x_vals[0], x_vals[-1])
ax.set_ylim(y_min - y_span*0.02, y_max + y_span*0.05)

plt.tight_layout()
OUT.parent.mkdir(exist_ok=True, parents=True)
plt.savefig(OUT, dpi=130, facecolor='#0e1117')
print(f"Saved: {OUT}")
