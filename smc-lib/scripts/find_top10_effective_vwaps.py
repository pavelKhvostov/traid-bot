"""Найти 10 самых эффективных VWAP-anchors с 2025-11-01 на BTCUSDT.

Алгоритм:
1. Детектируем D-Williams-N=2 фракталы (FH+FL) от 2025-11-01 до 2026-05-13
   (последний должен иметь ≥ 30 дней forward window).
2. Для каждого pivot строим 96 anchor-кандидатов в окне i+3 D-бара (15m grid).
3. Для каждого кандидата — Phase 1 composite_effectiveness в окне первых 30 дней
   на cascade 1h/2h/4h/6h/8h/12h.
4. Best anchor per pivot = argmax Phase 1 composite.
5. Ranking pivots по best Phase 1 score → top 10.

Output:
- Лог в stdout
- JSON с 10 anchor timestamps (ms) для подачи в TradingView indicator
"""
from __future__ import annotations
import csv, pathlib, sys, json, subprocess
from datetime import datetime, timezone, timedelta
import bisect

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.vwap_effectiveness import effectiveness_per_tf, composite_effectiveness

UTC = timezone.utc
MSK = timezone(timedelta(hours=3))
MS = 60_000
CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"

START_SCAN = datetime(2025, 11, 1, tzinfo=UTC)
START_SCAN_TS = int(START_SCAN.timestamp() * 1000)
EVAL_NOW = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
EVAL_NOW_TS = int(EVAL_NOW.timestamp() * 1000)
PHASE1_DAYS = 30
PHASE1_MS = PHASE1_DAYS * 86400 * 1000

CASCADE_TFS = [('1h', 60), ('2h', 120), ('4h', 240), ('6h', 360), ('8h', 480), ('12h', 720)]
N_FRACTAL = 2

# Fetch fresh data
FETCH = pathlib.Path.home() / "smc-lib/scripts/fetch_btc_1m_missing.py"
if FETCH.exists():
    print("Fetching 1m...")
    subprocess.run([sys.executable, str(FETCH)], capture_output=True, text=True, timeout=120)

print("Loading 1m...")
rows = []
with CSV.open() as f:
    rd = csv.reader(f); next(rd)
    for r in rd:
        t = datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]),
                     float(r[3]), float(r[4]), float(r[5])))

# pre-filter с buffer для Phase 1 horizon
# нужно от START - 5d (для fractal context) до EVAL_NOW
data_start = START_SCAN_TS - 5*86400*1000
rows = [r for r in rows if data_start <= r[0] <= EVAL_NOW_TS]
print(f"  1m rows in window: {len(rows)}")

def agg(d, tf_ms):
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in d:
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v = oo,hh,ll,cc,vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v += vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out

D = agg(rows, 1440*MS)
print(f"  D bars: {len(D)}")

# ── D-Williams-N=2 фракталы в окне ───────────────────────────────
fractals = []
for i in range(N_FRACTAL, len(D)-N_FRACTAL):
    if D[i][0] < START_SCAN_TS: continue
    # требуем ≥ 30 дней forward
    if D[i][0] + (3 + 1) * 86400*1000 + PHASE1_MS > EVAL_NOW_TS: continue
    center = D[i]
    others = D[i-N_FRACTAL:i] + D[i+1:i+1+N_FRACTAL]
    if all(center[2] > o[2] for o in others):
        fractals.append((center[0], 'FH', center[2]))
    elif all(center[3] < o[3] for o in others):
        fractals.append((center[0], 'FL', center[3]))

print(f"  D-fractals в окне (с forward ≥ 30d): {len(fractals)}")

# ── Для каждого фрактала: 96 anchor-кандидатов в i+3 D-бара ─────
def score_anchor_phase1(anchor_ts):
    """Compute Phase 1 (first 30d) composite_effectiveness for given anchor."""
    end_ts = anchor_ts + PHASE1_MS

    # построим VWAP по 1m + aggregated TF bars одним проходом
    per_tf_state = {}   # tf_name → {ts, o, h, l, c, v, prev_vwap_at_close}
    per_tf_bars_and_vw = {tf: ([], []) for tf, _ in CASCADE_TFS}
    cum_pv = 0.0; cum_v = 0.0
    last_vwap = None

    for ts, o, h, l, c, v in rows:
        if ts < anchor_ts: continue
        if ts > end_ts: break
        tp = (h + l + c) / 3.0
        cum_pv += tp * v
        cum_v  += v
        vwap_now = cum_pv / cum_v if cum_v > 0 else None

        for tf_name, tf_min in CASCADE_TFS:
            tf_ms = tf_min * MS
            bucket = ts - (ts % tf_ms)
            state = per_tf_state.get(tf_name)
            if state is None or state['bucket'] != bucket:
                # flush previous bucket
                if state is not None:
                    per_tf_bars_and_vw[tf_name][0].append(
                        (state['o'], state['h'], state['l'], state['c'])
                    )
                    per_tf_bars_and_vw[tf_name][1].append(state['vw_at_close'])
                per_tf_state[tf_name] = {
                    'bucket': bucket, 'o': o, 'h': h, 'l': l, 'c': c,
                    'vw_at_close': vwap_now,
                }
            else:
                state['h'] = max(state['h'], h)
                state['l'] = min(state['l'], l)
                state['c'] = c
                state['vw_at_close'] = vwap_now

    # flush remaining
    for tf_name, _ in CASCADE_TFS:
        state = per_tf_state.get(tf_name)
        if state is not None:
            per_tf_bars_and_vw[tf_name][0].append(
                (state['o'], state['h'], state['l'], state['c'])
            )
            per_tf_bars_and_vw[tf_name][1].append(state['vw_at_close'])

    per_tf_results = []
    for tf_name, _ in CASCADE_TFS:
        bars, vws = per_tf_bars_and_vw[tf_name]
        eff = effectiveness_per_tf(tf_name, bars, vws)
        per_tf_results.append(eff)
    comp = composite_effectiveness(anchor_ts, per_tf_results)
    return comp

print(f"\nScoring 96 anchor candidates × {len(fractals)} fractals...")
print(f"  (Phase 1 window = первые {PHASE1_DAYS} дней)\n")

results_per_pivot = []
for fi, (pivot_ts, kind, level) in enumerate(fractals):
    # i+3 D-бар = pivot_ts + 3 days, 24h окно, 15m grid → 96 кандидатов
    window_start = pivot_ts + 3*86400*1000
    best_comp = None
    best_anchor = None
    for k in range(96):
        anc = window_start + k*15*60*1000
        comp = score_anchor_phase1(anc)
        if best_comp is None or comp.composite > best_comp.composite:
            best_comp = comp
            best_anchor = anc
    pivot_dt = datetime.fromtimestamp(pivot_ts/1000, MSK)
    anchor_dt = datetime.fromtimestamp(best_anchor/1000, MSK)
    results_per_pivot.append({
        'pivot_ts': pivot_ts,
        'pivot_kind': kind,
        'pivot_level': level,
        'pivot_str': pivot_dt.strftime('%Y-%m-%d'),
        'best_anchor_ts': best_anchor,
        'best_anchor_str': anchor_dt.strftime('%Y-%m-%d %H:%M МСК'),
        'phase1_composite': best_comp.composite,
        'phase1_interactions': best_comp.total_interactions,
        'per_tf': [(p.tf, p.score, p.interactions) for p in best_comp.per_tf],
    })
    print(f"  [{fi+1}/{len(fractals)}] pivot {pivot_dt.strftime('%Y-%m-%d')} {kind}@{level:.0f}"
          f"  → anchor {anchor_dt.strftime('%m-%d %H:%M МСК')}"
          f"  Ph1 comp={best_comp.composite:.4f} int={best_comp.total_interactions}")

# ── Rank by Phase 1 composite, top 10 ────────────────────────────
results_sorted = sorted(results_per_pivot, key=lambda r: -r['phase1_composite'])
top10 = results_sorted[:10]

print(f"\n=== TOP 10 EFFECTIVE VWAP ANCHORS (Phase 1 composite, first {PHASE1_DAYS}d) ===\n")
print(f"{'rank':>4}  {'pivot':<12}  {'kind':>4}  {'level':>9}  "
      f"{'best anchor':<24}  {'Ph1_comp':>9}  {'Ph1_int':>8}")
for i, r in enumerate(top10):
    print(f"{i+1:>4}  {r['pivot_str']:<12}  {r['pivot_kind']:>4}  {r['pivot_level']:>9.0f}  "
          f"{r['best_anchor_str']:<24}  {r['phase1_composite']:>9.4f}  {r['phase1_interactions']:>8}")

# ── Output JSON ──────────────────────────────────────────────────
out_path = pathlib.Path.home() / "Desktop/i-rdrb-charts" / "top10_effective_vwap_anchors.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with out_path.open('w') as f:
    json.dump({
        'generated_at_msk': datetime.now(MSK).isoformat(),
        'scan_window': {
            'start': START_SCAN.isoformat(),
            'end_eval': EVAL_NOW.isoformat(),
        },
        'phase1_days': PHASE1_DAYS,
        'cascade': [tf for tf, _ in CASCADE_TFS],
        'top10': top10,
    }, f, indent=2, default=str)
print(f"\nSaved: {out_path}")

# Также вывести просто список timestamps для подачи в TV
print("\nAnchor timestamps (ms, for TV indicator):")
for i, r in enumerate(top10):
    print(f"  in_{i}: {r['best_anchor_ts']}  // {r['best_anchor_str']}")
