"""Brute-force anchor sweep для slot 10 VWAP.

Candidate grid: 2026-01-30 00:00 UTC → 2026-02-01 23:45 UTC, шаг 15m.
Для каждого candidate: VWAP от anchor → 2026-06-13, composite_effectiveness
по cascade 1h/2h/4h/6h/8h/12h.

Output: top 20 by composite + rank of user's actual anchor (2026-01-31 00:00 UTC).
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from indicators.vwap_effectiveness import effectiveness_per_tf, composite_effectiveness

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
UTC = timezone.utc
MS = 60_000

# Candidate grid
START = datetime(2026, 1, 30, 0, 0, tzinfo=UTC)
END = datetime(2026, 2, 1, 23, 45, tzinfo=UTC)
STEP_MIN = 15

# User's actual slot 10 anchor
USER_ANCHOR = datetime(2026, 1, 31, 0, 0, tzinfo=UTC)
USER_ANCHOR_TS = int(USER_ANCHOR.timestamp() * 1000)

# Cascade TFs
CASCADE_TFS = [('1h', 60), ('2h', 120), ('4h', 240), ('6h', 360), ('8h', 480), ('12h', 720)]

# Eval window end (today)
EVAL_END_TS = int(datetime(2026, 6, 13, 12, 0, tzinfo=UTC).timestamp() * 1000)


def load_1m():
    rows = []
    with CSV.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((int(t.timestamp()*1000), float(r[1]), float(r[2]),
                         float(r[3]), float(r[4]), float(r[5])))
    return rows


def agg(d, tf_ms, start_ts, end_ts):
    """Aggregate 1m bars в TF, only bars в [start_ts, end_ts]."""
    out=[]; cb=None; o=h=l=c=0.0; v=0.0
    for ts,oo,hh,ll,cc,vv in d:
        if ts < start_ts or ts > end_ts:
            if cb is not None and ts > end_ts:
                break
            continue
        b = ts - (ts % tf_ms)
        if b != cb:
            if cb is not None: out.append((cb,o,h,l,c,v))
            cb=b; o,h,l,c,v = oo,hh,ll,cc,vv
        else:
            h=max(h,hh); l=min(l,ll); c=cc; v += vv
    if cb is not None: out.append((cb,o,h,l,c,v))
    return out


def anchored_vwap_for_tf_bars(rows_1m, anchor_ts, tf_ms, end_ts):
    """Считает anchored VWAP (typical-price weighted) от 1m, потом aggregates по TF.

    Returns: (tf_bars, vwap_at_close_of_each_tf_bar)
    Logic:
      - VWAP cumulative from anchor over 1m
      - TF bars built from 1m within [anchor_ts, end_ts]
      - vwap_value(tf_bar) = последнее значение VWAP до конца этого TF бара
    """
    tf_bars = []
    vwap_at_bar = []   # parallel; final VWAP at close of each TF bar

    cum_pv = 0.0
    cum_v = 0.0

    cur_bucket = None
    cur_o = cur_h = cur_l = cur_c = 0.0
    cur_v = 0.0

    for ts, o, h, l, c, v in rows_1m:
        if ts < anchor_ts:
            continue
        if ts > end_ts:
            break

        tp = (h + l + c) / 3.0
        cum_pv += tp * v
        cum_v  += v
        vwap_now = cum_pv / cum_v if cum_v > 0 else None

        bucket = ts - (ts % tf_ms)
        if bucket != cur_bucket:
            if cur_bucket is not None:
                tf_bars.append((cur_o, cur_h, cur_l, cur_c))
                vwap_at_bar.append(prev_vwap_at_bar_close)
            cur_bucket = bucket
            cur_o, cur_h, cur_l, cur_c, cur_v = o, h, l, c, v
        else:
            cur_h = max(cur_h, h)
            cur_l = min(cur_l, l)
            cur_c = c
            cur_v += v
        prev_vwap_at_bar_close = vwap_now

    if cur_bucket is not None:
        tf_bars.append((cur_o, cur_h, cur_l, cur_c))
        vwap_at_bar.append(prev_vwap_at_bar_close)

    return tf_bars, vwap_at_bar


def score_anchor(rows_1m, anchor_ts):
    per_tf = []
    for tf_name, tf_min in CASCADE_TFS:
        tf_ms = tf_min * MS
        tf_bars, vw = anchored_vwap_for_tf_bars(rows_1m, anchor_ts, tf_ms, EVAL_END_TS)
        eff = effectiveness_per_tf(tf_name, tf_bars, vw)
        per_tf.append(eff)
    return composite_effectiveness(anchor_ts, per_tf)


def main():
    print("Loading 1m...")
    rows = load_1m()
    print(f"  loaded {len(rows)} 1m rows")

    # Pre-filter to relevant window (от START до EVAL_END)
    start_ts = int(START.timestamp() * 1000)
    rows_eval = [r for r in rows if r[0] >= start_ts and r[0] <= EVAL_END_TS]
    print(f"  in eval window: {len(rows_eval)} 1m rows")

    # Generate candidates
    candidates = []
    t = START
    step = timedelta(minutes=STEP_MIN)
    while t <= END:
        candidates.append(int(t.timestamp() * 1000))
        t += step
    print(f"  candidates: {len(candidates)} ({STEP_MIN}m grid от {START.date()} до {END.date()})\n")

    # Score each candidate
    results = []
    print(f"Scoring {len(candidates)} candidates на cascade {[tf for tf, _ in CASCADE_TFS]}...")
    for i, anc in enumerate(candidates):
        eff = score_anchor(rows_eval, anc)
        results.append(eff)
        if (i+1) % 50 == 0:
            print(f"  done {i+1}/{len(candidates)}")

    # Rank by composite, descending
    results_sorted = sorted(results, key=lambda x: -x.composite)

    def fmt_anchor(ts):
        d = datetime.fromtimestamp(ts/1000, MSK)
        return d.strftime('%Y-%m-%d %H:%M МСК')

    # User anchor result
    user_result = next(r for r in results if r.anchor_ts == USER_ANCHOR_TS)
    user_rank = next(i for i, r in enumerate(results_sorted) if r.anchor_ts == USER_ANCHOR_TS) + 1

    print("\n=== TOP 20 anchors by composite ===")
    print(f"{'rank':>4}  {'anchor (МСК)':<22}  {'composite':>9}  {'tot_int':>7}  per-tf scores")
    for i, r in enumerate(results_sorted[:20]):
        marker = " ←USER" if r.anchor_ts == USER_ANCHOR_TS else ""
        tf_str = ' '.join(f"{p.tf}:{p.score:.2f}/{p.interactions}" for p in r.per_tf)
        print(f"{i+1:>4}  {fmt_anchor(r.anchor_ts):<22}  {r.composite:>9.4f}  {r.total_interactions:>7}  {tf_str}{marker}")

    print(f"\n=== USER's anchor (slot 10 = {fmt_anchor(USER_ANCHOR_TS)}) ===")
    print(f"  rank: {user_rank}/{len(results_sorted)}")
    print(f"  composite: {user_result.composite:.4f}")
    print(f"  total interactions: {user_result.total_interactions}")
    print(f"  per-TF:")
    for p in user_result.per_tf:
        print(f"    {p.tf}: score={p.score:.4f}  reactions={p.reactions}/{p.interactions}  breaks={p.breaks}")

    # Best vs user
    best = results_sorted[0]
    print(f"\n=== BEST anchor ===")
    print(f"  {fmt_anchor(best.anchor_ts)}  composite={best.composite:.4f}  interactions={best.total_interactions}")
    diff = best.composite - user_result.composite
    print(f"  Δ composite vs USER: {diff:+.4f}  ({diff/user_result.composite*100:+.1f}%)")

if __name__ == "__main__":
    main()
