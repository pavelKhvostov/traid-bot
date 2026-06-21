"""Chart Feb-May 2026 — MULTI maxV (D 05/06/24/28-Feb) с Gaussian-gradient cluster.

Canon base: chart_format.md / expert/chart.py.
ViC overlay: feedback-vic-maxv-chart-style.md (blue palette, light alpha).
"""
from __future__ import annotations
import math, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator
from matplotlib.colors import LinearSegmentedColormap

MSK = timezone(timedelta(hours=3))
MS_M = 60_000
MS_H = 60 * MS_M
CSV_PATH = Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

DATE_FROM = "2024-02-24"     # окно загрузки событий (для history / age)
DATE_TO = "2026-06-04"
DISPLAY_FROM = "2025-12-04"  # окно отображения (zoom)

# maxV для ВСЕХ D-свечей в окне (None = автодетект всех)
TARGET_DATES = None
LTF_MIN = 32  # D + mlt=45 canon

# === Canon palette ===
BULL_COLOR = '#01a648'
BEAR_COLOR = '#131b1b'
DOJI_COLOR = '#888'
CURRENT_PRICE_COLOR = '#c62828'
BAR_GAP_FRACTION = 0.5
BAR_WIDTH_FRACTION = 1.0 - BAR_GAP_FRACTION
BAR_LINEWIDTH = 1.1

TF_MIN = 1440  # D
TF_MS = TF_MIN * MS_M

def y_step_for_price(price: float) -> float:
    if price >= 10000: return 1000
    if price >= 1000:  return 100
    if price >= 100:   return 10
    if price >= 10:    return 1
    return 0.1

start_ms = int(datetime.fromisoformat(DATE_FROM).replace(tzinfo=timezone.utc).timestamp() * 1000)
end_ms = int(datetime.fromisoformat(DATE_TO).replace(tzinfo=timezone.utc).timestamp() * 1000) + 24*3600*1000

rows = []
with CSV_PATH.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        ts = int(t.timestamp() * 1000)
        if ts < start_ms: continue
        if ts >= end_ms: break
        rows.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))

def agg(rs, tf_ms, anchor=0):
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in rs:
        b = ts - ((ts - anchor) % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    return out

barsD = agg(rows, TF_MS)
win_start = barsD[0][0]
win_end = barsD[-1][0] + TF_MS
last_close = rows[-1][4]
barsD_by_start = {b[0]: b for b in barsD}

# === maxV per target D (canon: absolute max-volume LTF bar) ===
def maxv_for_d(d_start_ms, ltf_min=LTF_MIN):
    d_end = d_start_ms + TF_MS
    ltf_ms = ltf_min * MS_M
    out = []; cb = None; o = h = l = c = 0.0; v = 0.0
    for ts, oo, hh, ll, cc, vv in rows:
        if ts < d_start_ms: continue
        if ts >= d_end: break
        b = ts - ((ts - d_start_ms) % ltf_ms)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v))
            cb = b; o, h, l, c, v = oo, hh, ll, cc, vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v += vv
    if cb is not None: out.append((cb, o, h, l, c, v))
    if not out: return None
    return max(out, key=lambda b: b[5])  # absolute max-volume bar

def w_pos(p): return 1.5 if "wick" in p else 0.7
def w_age(days): return 1 + 0.3 * math.log(1 + max(days, 0) / 30)

# === Mitigation decay (Вариант B) ===
# Virgin: W_v = K_V (full power)
# Mitigated: W_v = 1 + (K_V - 1) × exp(-days_since_touch / TAU)
#   t=0 (just touched): ≈ K_V (как virgin)
#   t=TAU (7d):         ≈ 1 + (K_V-1)/e ≈ 1.74 для K_V=3
#   t→∞:                → 1.0 (полностью выработана)
K_V = 3.0   # virgin boost
TAU = 7.0   # days decay constant

def w_virgin(is_mit, days_since_touch):
    if not is_mit:
        return K_V
    decay = math.exp(-max(days_since_touch, 0) / TAU)
    return 1.0 + (K_V - 1.0) * decay

# === Condition #4: Broken Defense ===
W_BROKEN = 1.8

# === Condition #5: Candle Size & Volatility ===
# W_vol = (V_norm / R_norm), clipped [0.5, 2.0]
#   V_norm = parent_V / median_V_20  (volume anomaly)
#   R_norm = parent_range / ATR_20   (range vs typical volatility)
# Логика:
#   tight bar + heavy V (consolidation absorption) → boost ×1.5-2.0
#   wide bar + average V (directional move) → penalty ×0.5-0.8
#   median bar + median V → 1.0
ATR_N = 20

def compute_atr_and_medv(bars_d, n=ATR_N):
    """Rolling ATR(n) and median(V) per D bar — strict (no lookahead, t-1)."""
    atrs = [None] * len(bars_d)
    medvs = [None] * len(bars_d)
    trs = []
    for i, b in enumerate(bars_d):
        if i == 0:
            trs.append(b[2] - b[3])
        else:
            pc = bars_d[i-1][4]
            trs.append(max(b[2]-b[3], abs(b[2]-pc), abs(b[3]-pc)))
        lo = max(0, i - n + 1)
        atrs[i] = sum(trs[lo:i+1]) / (i - lo + 1) if i > 0 else trs[0]
        vs = sorted([bars_d[j][5] for j in range(lo, i+1)])
        medvs[i] = vs[len(vs)//2] if vs else 1.0
    return atrs, medvs

atrs_d, medvs_d = compute_atr_and_medv(barsD)
d_idx_by_start = {b[0]: i for i, b in enumerate(barsD)}

def w_vol(parent_range, parent_v, atr, med_v):
    if atr <= 0 or med_v <= 0: return 1.0
    R_norm = parent_range / atr
    V_norm = parent_v / med_v
    ratio = V_norm / R_norm if R_norm > 0 else 1.0
    return max(0.5, min(2.0, ratio))

def detect_broken_defense(c1_event, c2_d_bar):
    """c1_event = event dict for C1; c2_d_bar = (ts, o, h, l, c, v) of next D."""
    if c2_d_bar is None: return False
    c1_d = barsD_by_start.get(c1_event["d_start"])
    if c1_d is None: return False
    c1_low, c1_high = c1_d[3], c1_d[2]
    c2_o, c2_h, c2_l, c2_c = c2_d_bar[1], c2_d_bar[2], c2_d_bar[3], c2_d_bar[4]
    L = c1_event["level"]
    if c1_event["position"] == "lower_wick":
        return (c2_h > L) and (c2_c < c1_low)
    if c1_event["position"] == "upper_wick":
        return (c2_l < L) and (c2_c > c1_high)
    return False

# Mitigation: maxV LEVEL was touched by any 1m bar after formation
# Returns (is_mitigated: bool, first_touch_ts: int|None)
def check_mitigation(level, formation_end_ms):
    for ts, o, h, l, c, v in rows:
        if ts < formation_end_ms: continue
        if l <= level <= h:
            return True, ts
    return False, None

events = []
target_d_starts = (
    [int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() * 1000) for d in TARGET_DATES]
    if TARGET_DATES else [b[0] for b in barsD]
)
ZONE_ALPHA = 0.30  # canon 2026-06-04: zone = 30% of parent range, clipped
for d_start in target_d_starts:
    db = barsD_by_start.get(d_start)
    if db is None: continue
    mb = maxv_for_d(d_start)
    if mb is None: continue
    mb_ts, mb_o, mb_h, mb_l, mb_c, mb_v = mb
    d_o, d_h, d_l, d_c = db[1], db[2], db[3], db[4]
    body_lo, body_hi = min(d_o, d_c), max(d_o, d_c)
    if mb_c < body_lo: pos = "lower_wick"
    elif mb_c > body_hi: pos = "upper_wick"
    elif mb_c < (body_lo + body_hi)/2: pos = "body_bottom"
    else: pos = "body_top"
    # === Zone: 30% of parent range, centered at L = mb_c, clipped to [d_l, d_h] ===
    R_parent_d = d_h - d_l
    w_zone = ZONE_ALPHA * R_parent_d
    zone_lo = max(d_l, mb_c - w_zone/2)
    zone_hi = min(d_h, mb_c + w_zone/2)
    age_days = (win_end - d_start) / (24 * 3600 * 1000)
    parent_d_end = d_start + TF_MS
    is_mit, first_touch = check_mitigation(mb_c, parent_d_end)
    days_since_touch = (win_end - first_touch) / (24 * 3600 * 1000) if is_mit else 0.0
    W_v = w_virgin(is_mit, days_since_touch)
    # Condition #5: W_vol from parent candle
    d_idx = d_idx_by_start[d_start]
    parent_range = db[2] - db[3]
    parent_v = db[5]
    atr = atrs_d[d_idx] if d_idx > 0 else (atrs_d[1] if len(atrs_d) > 1 else 1.0)
    med_v = medvs_d[d_idx] if d_idx > 0 else (medvs_d[1] if len(medvs_d) > 1 else parent_v)
    W_vol = w_vol(parent_range, parent_v, atr, med_v)
    AMP = w_pos(pos) * w_age(age_days) * W_v * W_vol
    events.append({
        "date": datetime.fromtimestamp(d_start/1000, timezone.utc).strftime("%Y-%m-%d"),
        "d_start": d_start,
        "level": mb_c,
        "zone_lo": zone_lo,
        "zone_hi": zone_hi,
        "position": pos,
        "age_days": age_days,
        "amp": AMP,
        "mitigated": is_mit,
        "first_touch": first_touch,
        "days_since_touch": days_since_touch,
        "w_v": W_v,
        "w_vol": W_vol,
        "parent_range": parent_range,
        "parent_v": parent_v,
        "atr": atr,
        "med_v": med_v,
    })

# === Apply Condition #4: Broken Defense ===
# Iterate (C1, C2) pairs by chronological order
events_sorted = sorted(events, key=lambda e: e["d_start"])
events_by_dstart = {e["d_start"]: e for e in events}
n_broken = 0
for i, e in enumerate(events_sorted):
    c2_dstart = e["d_start"] + TF_MS
    c2_d_bar = barsD_by_start.get(c2_dstart)
    if detect_broken_defense(e, c2_d_bar):
        e["broken_defense"] = True
        e["amp"] *= W_BROKEN
        e["w_broken"] = W_BROKEN
        n_broken += 1
    else:
        e["broken_defense"] = False
        e["w_broken"] = 1.0

n_virgin = sum(1 for e in events if not e["mitigated"])
n_mit = len(events) - n_virgin
print(f"Loaded {len(events)} maxV events ({n_virgin} virgin / {n_mit} mitigated)")
print(f"  W_virgin: K_V={K_V}, TAU={TAU}d")
print(f"  W_broken: {W_BROKEN} for {n_broken} broken-defense events")
print(f"  W_vol (Condition #5): V_norm/R_norm clipped [0.5, 2.0], ATR_N={ATR_N}")
print(f"    boosted (W_vol>1.2): {sum(1 for e in events if e['w_vol']>1.2)}")
print(f"    neutral  (0.8-1.2):  {sum(1 for e in events if 0.8<=e['w_vol']<=1.2)}")
print(f"    penalty  (W_vol<0.8): {sum(1 for e in events if e['w_vol']<0.8)}")
print(f"\n  Top-15 by AMP:")
for e in sorted(events, key=lambda x: -x["amp"])[:15]:
    flag = "VIRGIN" if not e["mitigated"] else f"mit({e['days_since_touch']:>3.0f}d)"
    bd = " [BROKEN]" if e["broken_defense"] else ""
    print(f"    D {e['date']}  L={e['level']:.0f}  pos={e['position']:<12}  age={e['age_days']:>3.0f}d  {flag:<10}  W_v={e['w_v']:.2f}  W_vol={e['w_vol']:.2f}  AMP={e['amp']:.2f}{bd}")

def to_dt(ms): return datetime.fromtimestamp(ms/1000, MSK)

# === Figure ===
fig, ax = plt.subplots(figsize=(24, 13))

# Display zoom window
display_start_ms = int(datetime.fromisoformat(DISPLAY_FROM).replace(tzinfo=timezone.utc).timestamp() * 1000)
barsD_visible = [b for b in barsD if b[0] >= display_start_ms]
if not barsD_visible: barsD_visible = barsD
y_min = min(b[3] for b in barsD_visible) * 0.97
y_max = max(b[2] for b in barsD_visible) * 1.02
all_zone_lo = min(e["zone_lo"] for e in events)
all_zone_hi = max(e["zone_hi"] for e in events)
y_lo_band = min(y_min, all_zone_lo * 0.99)
y_hi_band = max(y_max, all_zone_hi * 1.01)

# Blue cmap — N>>1 maxV перекрываются, поэтому per-event alpha снижен
N_events = max(1, len(events))
alpha_scale = min(1.0, 4.0 / math.sqrt(N_events))
blue_cmap = LinearSegmentedColormap.from_list(
    "force_blue",
    [(0.690, 0.847, 1.0, 0.0),
     (0.0, 0.690, 1.0, 0.25 * alpha_scale),
     (0.098, 0.463, 0.824, 0.45 * alpha_scale)]
)

# Normalization для alpha по полному AMP (включает все 4 условия)
amps = [e["amp"] for e in events]
AMP_MIN, AMP_MAX = min(amps), max(amps)
def amp_to_alpha(amp):
    """Map AMP → alpha_mult in [0.15, 1.0]. Сильней AMP = ярче."""
    if AMP_MAX <= AMP_MIN: return 1.0
    norm = (amp - AMP_MIN) / (AMP_MAX - AMP_MIN)
    return 0.15 + 0.85 * norm

# === 1) Per-maxV ViC gradient ===
n_rows = 800
n_cols = 50
prices_arr = np.linspace(y_hi_band, y_lo_band, n_rows)
x_end_dt = to_dt(win_end)
x_end_num = mdates.date2num(x_end_dt)

for e in events:
    L = e["level"]
    R = max(L - e["zone_lo"], e["zone_hi"] - L)
    if R <= 0: continue
    SIGMA = R / 2
    # Alpha по полному AMP: единый стиль (синий), яркость = сила
    alpha_mult = amp_to_alpha(e["amp"])
    force_col = np.exp(-((prices_arr - L) / SIGMA) ** 2) * alpha_mult
    force_col = np.clip(force_col, 0, 1)
    img = np.tile(force_col[:, None], (1, n_cols))
    x_start_num = mdates.date2num(to_dt(e["d_start"]))
    ax.imshow(img,
              extent=[x_start_num, x_end_num, y_lo_band, y_hi_band],
              aspect="auto", cmap=blue_cmap, vmin=0, vmax=1,
              origin="upper", interpolation="bilinear", zorder=1)
    # LEVEL marker — синий, alpha пропорциональна AMP
    lvl_alpha = 0.10 + 0.40 * alpha_mult
    ax.hlines(L, to_dt(e["d_start"]), x_end_dt,
              color="#1a3f6f", lw=0.5, alpha=lvl_alpha, zorder=4)

# === 2) D candles ===
bar_w = (TF_MIN/60)/24 * BAR_WIDTH_FRACTION

for b in barsD:
    t = to_dt(b[0] + TF_MS//2)
    o, h, l, c = b[1], b[2], b[3], b[4]
    color_b = BULL_COLOR if c > o else (BEAR_COLOR if c < o else DOJI_COLOR)
    ax.vlines(t, l, h, color=color_b, linewidth=BAR_LINEWIDTH, zorder=3)
    ax.add_patch(plt.Rectangle((mdates.date2num(t) - bar_w/2, min(o, c)),
                               bar_w, max(abs(o - c), 0.01),
                               facecolor=color_b, edgecolor=color_b,
                               linewidth=BAR_LINEWIDTH, zorder=3))

# === 3) X-axis: Mondays + today ===
today_dt = to_dt(win_end)
start_dt = to_dt(display_start_ms)
last_monday = (today_dt - timedelta(days=today_dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
week_ticks = []; d = last_monday
while d >= start_dt:
    week_ticks.append(d); d -= timedelta(days=7)
week_ticks.reverse()
if today_dt.date() != last_monday.date():
    week_ticks.append(today_dt)
ax.set_xticks(week_ticks)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%m', tz=MSK))
ax.grid(False)

# === 4) Y-axis right ===
ax.yaxis.tick_right()
ax.yaxis.set_label_position('right')
ax.yaxis.set_major_locator(MultipleLocator(y_step_for_price(last_close)))

# === 5) Current price ===
ax.axhline(y=last_close, color=CURRENT_PRICE_COLOR, linewidth=0.9, linestyle=':', alpha=1.0, zorder=2)
ax.set_xlim(start_dt, today_dt)
ax.set_ylim(y_min, y_max)
fig.canvas.draw()
existing_ticks = list(ax.get_yticks())
y_step = y_step_for_price(last_close)
filtered = [t for t in existing_ticks if abs(t - last_close) > y_step * 0.5]
all_ticks = sorted(set(filtered + [last_close]))
ax.set_yticks(all_ticks)
labels = []
for t in all_ticks:
    if abs(t - last_close) < 0.0001:
        labels.append(f' {last_close:,.0f} ')
    else:
        labels.append(f'{int(t):,}')
ax.set_yticklabels(labels)
for tl, t in zip(ax.get_yticklabels(), all_ticks):
    if abs(t - last_close) < 0.5:
        tl.set_color('white'); tl.set_weight('bold'); tl.set_fontsize(11)
        tl.set_bbox(dict(facecolor=CURRENT_PRICE_COLOR, edgecolor=CURRENT_PRICE_COLOR, pad=4))

for tl, td in zip(ax.get_xticklabels(), week_ticks):
    if td == today_dt:
        tl.set_color('white'); tl.set_weight('bold'); tl.set_fontsize(11)
        tl.set_bbox(dict(facecolor=CURRENT_PRICE_COLOR, edgecolor=CURRENT_PRICE_COLOR, pad=4))

# === 6) Title ===
n_virgin = sum(1 for e in events if not e["mitigated"])
n_mit = len(events) - n_virgin
n_wick = sum(1 for e in events if "wick" in e["position"])
fig.text(0.5, 0.97,
         f"BTC  |  D  |  {today_dt.strftime('%d-%m-%Y')}  |  {today_dt.strftime('%H:%M')} MSK   +   ViC maxV heatmap "
         f"(N={len(events)}; zone=30%×R_parent; яркость ∝ AMP = W_pos × W_age × W_v × W_broken × W_vol)",
         ha='center', va='top', fontsize=12, fontweight='bold')

plt.subplots_adjust(left=0.02, right=0.96, top=0.93, bottom=0.06)

out = Path.home() / "Desktop" / "maxv_cluster_feb.png"
plt.savefig(out, dpi=140)
print(f"\nSaved → {out}")
