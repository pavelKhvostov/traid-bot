"""Multi-TF cascade pipeline для шагов 1–5 из expert_opinion.md.

Usage:
    python3 expert_opinion.py                              # дефолт: каскад W,D,12h,4h,1h,15m
    python3 expert_opinion.py --tfs D                      # только D
    python3 expert_opinion.py --tfs W,D,4h --radius 0.06   # выборочно

ТФ-имена: W (Monday-anchor), D, 12h, 4h, 1h, 30m, 15m, 5m, 1m
или числа в минутах: 10080, 1440, 720, 240, 60, 30, 15.

Шаги 6-10 (cascade integration, structure, scenarios, invalidation) выполняются
ассистентом на основе output'а этого скрипта.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from candle import Candle
from elements.ob.code import detect_ob
from elements.block_orders.code import detect_block_orders
from elements.ob_liq.code import detect_ob_liq
from elements.rb.code import detect_rb
from elements.fvg.code import detect_fvg
from elements.i_fvg.code import detect_i_fvg
from elements.rdrb.code import detect_rdrb
from elements.i_rdrb.code import detect_i_rdrb
from patterns.i_rdrb_fvg.code import detect_i_rdrb_fvg
from elements.marubozu.code import detect_marubozu
from elements.fractal.code import detect_fractal

# Indicators
from indicators.atr import atr
from indicators.ema import ema
from indicators.cumulative_delta import cumulative_delta, bar_delta
from indicators.volume_profile import volume_profile
from indicators.vwap_anchored import anchored_vwap
from indicators.vwap_effectiveness import effectiveness_per_tf, composite_effectiveness
from indicators.vic_asvk import calculate_vic_bar, auto_ltf_minutes
from indicators.trend_line_asvk import trend_line_asvk
from indicators.rsi_asvk import adjusted_rsi, asvk_zone
from indicators.money_hands_asvk import money_hands

CSV_PATH = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))

# TF specs: name → (minutes, lookback_days, radius_pct)
TF_SPECS = {
    'W':   (10080, 730, 0.20),   # 2 года
    '3D':  (4320,  365, 0.15),   # 1 год
    '2D':  (2880,  240, 0.12),   # 8 мес
    'D':   (1440,  120, 0.08),   # 4 мес
    '12h': (720,    60, 0.06),   # 2 мес
    '6h':  (360,    42, 0.05),   # 6 нед
    '4h':  (240,    30, 0.05),   # 1 мес
    '2h':  (120,    21, 0.04),   # 3 нед
    '1h':  (60,     14, 0.03),   # 2 нед
    '30m': (30,      7, 0.025),
    '15m': (15,      5, 0.02),   # 5 дн
    '5m':  (5,       2, 0.015),
    '1m':  (1,       1, 0.01),
}

CLASS = {
    'ob': 'efficiency',
    'block_orders': 'efficiency',
    'ob_liq': 'efficiency+liq_marker',
    'rdrb': 'efficiency+liq',
    'i_rdrb': 'efficiency',
    'i_rdrb_fvg': 'efficiency+inefficiency',
    'fvg': 'inefficiency',
    'i_fvg': 'inefficiency',
    'marubozu': 'inefficiency',
    'rb': 'liquidity',
    'fractal': 'liquidity',
}

DEFAULT_CASCADE = ['W', '3D', '2D', 'D', '12h', '6h', '4h', '2h', '1h', '15m']


def load_1m():
    """Load 1m OHLCV. Returns list of (ts_ms, o, h, l, c, v)."""
    rows = []
    with CSV_PATH.open() as f:
        rd = csv.reader(f); next(rd)
        for r in rd:
            t = datetime.fromisoformat(r[0])
            rows.append((
                int(t.timestamp() * 1000),
                float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                float(r[5]) if len(r) > 5 else 0.0,
            ))
    return rows


def aggregate_epoch(d, tf_min):
    """Epoch-anchor aggregation. Returns list of (ts, o, h, l, c, v)."""
    bucket = tf_min * 60_000
    out = []; cb = None; o = h = l = c = 0; v_sum = 0.0
    for row in d:
        ts, oo, hh, ll, cc = row[0], row[1], row[2], row[3], row[4]
        vv = row[5] if len(row) > 5 else 0.0
        b = ts - (ts % bucket)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v_sum))
            cb = b; o, h, l, c = oo, hh, ll, cc; v_sum = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v_sum += vv
    if cb is not None: out.append((cb, o, h, l, c, v_sum))
    return out


# Monday-anchor via integer arithmetic (epoch was Thursday → Monday = epoch + 4 days)
MONDAY_OFFSET_MS = 4 * 86400 * 1000   # ms от epoch до первого Monday (Mon 1970-01-05 00:00 UTC)
WEEK_MS = 7 * 86400 * 1000


def aggregate_weekly_mon(d):
    """Weekly Mon-anchor через целочисленную арифметику (быстро). Returns (ts, o, h, l, c, v)."""
    out = []; cb = None; o = h = l = c = 0; v_sum = 0.0
    for row in d:
        ts, oo, hh, ll, cc = row[0], row[1], row[2], row[3], row[4]
        vv = row[5] if len(row) > 5 else 0.0
        b = ts - ((ts - MONDAY_OFFSET_MS) % WEEK_MS)
        if b != cb:
            if cb is not None: out.append((cb, o, h, l, c, v_sum))
            cb = b; o, h, l, c = oo, hh, ll, cc; v_sum = vv
        else:
            h = max(h, hh); l = min(l, ll); c = cc; v_sum += vv
    if cb is not None: out.append((cb, o, h, l, c, v_sum))
    return out


def aggregate(d, tf_name):
    if tf_name == 'W':
        return aggregate_weekly_mon(d)
    tf_min = TF_SPECS[tf_name][0]
    return aggregate_epoch(d, tf_min)


def to_candle(row):
    ts, o, h, l, c = row[0], row[1], row[2], row[3], row[4]
    return Candle(open=o, high=h, low=l, close=c, open_time=ts)


def fmt_short(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%m-%d')


def fmt_full(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK')


def detect_all(candles, rows, in_window):
    out = {k: [] for k in CLASS}

    for i in range(1, len(candles)):
        if not in_window(i): continue
        r = detect_ob(candles[i-1], candles[i])
        if r: out['ob'].append((rows[i][0], r.zone[0], r.zone[1], r.direction))

    seen = set()
    for end in range(2, len(candles)):
        if not in_window(end): continue
        for start in range(max(0, end - 6), end - 1):
            r = detect_block_orders(candles[start:end+1])
            if r:
                key = (rows[start+1][0], r.n_initial, r.n_counter)
                if key in seen: continue
                seen.add(key)
                out['block_orders'].append((rows[end][0], r.zone[0], r.zone[1], r.direction))

    for i in range(2, len(candles) - 2):
        if not in_window(i): continue
        r = detect_ob_liq(candles[i], candles[i+1])
        if r: out['ob_liq'].append((rows[i][0], r.zone[0], r.zone[1], r.direction))

    for i in range(1, len(candles) - 1):
        if not in_window(i): continue
        r = detect_rdrb(candles[i-1], candles[i], candles[i+1])
        if r: out['rdrb'].append((rows[i+1][0], r.poi[0], r.poi[1], r.direction))

    for i in range(1, len(candles) - 2):
        if not in_window(i+2): continue
        r = detect_i_rdrb(candles[i-1], candles[i], candles[i+1], candles[i+2])
        if r: out['i_rdrb'].append((rows[i+2][0], r.rdrb.poi[0], r.rdrb.poi[1], r.direction))

    for i in range(1, len(candles) - 3):
        if not in_window(i+3): continue
        r = detect_i_rdrb_fvg(candles[i-1], candles[i], candles[i+1], candles[i+2], candles[i+3])
        if r: out['i_rdrb_fvg'].append((rows[i+3][0], r.irdrb.rdrb.poi[0], r.irdrb.rdrb.poi[1], r.direction))

    fvg_list = []
    for i in range(1, len(candles) - 1):
        r = detect_fvg(candles[i-1], candles[i], candles[i+1])
        if r:
            fvg_list.append((i, r))
            if in_window(i+1):
                out['fvg'].append((rows[i+1][0], r.zone[0], r.zone[1], r.direction))

    for ai, a in fvg_list:
        for bi, b in fvg_list:
            if b.direction == a.direction: continue
            ac1, ac2, ac3 = ai - 2, ai - 1, ai
            bc1, bc2, bc3 = bi - 2, bi - 1, bi
            if bc1 <= ac3: continue
            if not in_window(bi): continue
            between = candles[ac3+1:bc1]
            result = detect_i_fvg(
                candles[ac1], candles[ac2], candles[ac3],
                between,
                candles[bc1], candles[bc2], candles[bc3],
            )
            if result:
                out['i_fvg'].append((rows[bi][0], result.overlap[0], result.overlap[1], result.direction))
                break

    for i in range(len(candles)):
        if not in_window(i): continue
        r = detect_marubozu(candles[i])
        if r: out['marubozu'].append((rows[i][0], r.zone[0], r.zone[1], r.direction))

    for i in range(len(candles)):
        if not in_window(i): continue
        r = detect_rb(candles[i])
        if r: out['rb'].append((rows[i][0], r.zone[0], r.zone[1], r.direction))

    for i in range(2, len(candles) - 2):
        if not in_window(i): continue
        r = detect_fractal(candles[i-2:i+3], n=2)
        if r: out['fractal'].append((rows[i][0], r.level, r.level, r.direction))

    return out


def analyze_tf(data, tf_name, radius, fractal_seq_out):
    """Анализ одного ТФ. fractal_seq_out — dict для накопления FH/FL последовательностей."""
    tf_min, lookback_days, default_radius = TF_SPECS[tf_name]
    if radius is None:
        radius = default_radius

    last_1m_ts = data[-1][0]
    # Режем 1m данные под lookback + padding на ширину окон детекторов (10 баров с запасом)
    slice_start_ms = last_1m_ts - (lookback_days + 14) * 24 * 3600 * 1000
    # Бинарный поиск начала
    lo, hi = 0, len(data)
    while lo < hi:
        m = (lo + hi) // 2
        if data[m][0] < slice_start_ms: lo = m + 1
        else: hi = m
    data_sliced = data[lo:]

    bars = aggregate(data_sliced, tf_name)
    bucket_ms = tf_min * 60_000
    forming = None
    if last_1m_ts < bars[-1][0] + bucket_ms - 60_000:
        forming = bars[-1]
        bars = bars[:-1]

    # Окно для фильтра зон
    window_start_ms = last_1m_ts - lookback_days * 24 * 3600 * 1000
    def in_window(i):
        return bars[i][0] >= window_start_ms

    idx_in = [i for i in range(len(bars)) if in_window(i)]
    if not idx_in:
        return None

    candles = [to_candle(r) for r in bars]
    last_close = data[-1][4]

    hits = detect_all(candles, bars, in_window)
    total = sum(len(v) for v in hits.values())

    # Position assessment
    flat = []
    for name, lst in hits.items():
        for ts, lo, hi, dir_ in lst:
            mid = (lo + hi) / 2
            if abs((mid - last_close) / last_close) > radius:
                continue
            pos = "INSIDE" if lo <= last_close <= hi else ("above" if lo > last_close else "below")
            flat.append((ts, name, lo, hi, dir_, pos, CLASS[name]))
    flat.sort(key=lambda x: -((x[2]+x[3])/2))

    fractal_seq_out[tf_name] = [(ts, lvl, dir_) for ts, lvl, _, dir_ in hits['fractal']]

    # ===== Indicators layer (Step 5b) =====
    indicators_out = compute_indicators(bars, candles, tf_name, last_1m_ts, data_sliced)

    return {
        'tf': tf_name,
        'bars_count': len(idx_in),
        'forming': forming,
        'last_close': last_close,
        'hits': hits,
        'total': total,
        'flat': flat,
        'radius': radius,
        'lookback_days': lookback_days,
        'indicators': indicators_out,
        'bars': bars,           # для cross-TF VWAP вычислений
    }


def compute_indicators(bars, candles, tf_name, last_1m_ts, data_sliced_1m):
    """Возвращает dict с индикаторами на текущем ТФ.

    bars: list of (ts, o, h, l, c, v)
    candles: parallel list of Candle
    data_sliced_1m: slice 1m данных (для VIC)
    """
    n = len(bars)
    if n == 0:
        return {}
    closes = [b[4] for b in bars]
    ohlcv = [(b[1], b[2], b[3], b[4], b[5]) for b in bars]

    out = {}

    # ATR(14)
    atr_series = atr(candles, 14)
    out['atr_last'] = atr_series[-1] if atr_series else None

    # EMA-200
    if n >= 200:
        ema_series = ema(closes, 200)
        out['ema200_last'] = ema_series[-1]
        out['ema200_position'] = ('above' if closes[-1] > ema_series[-1] else 'below') if ema_series[-1] else None
    else:
        out['ema200_last'] = None
        out['ema200_position'] = None

    # Cumulative Delta (last 50 bars trend)
    cd = cumulative_delta(ohlcv)
    if len(cd) >= 50:
        cd_now = cd[-1]
        cd_50 = cd[-50]
        out['cd_change_50'] = cd_now - cd_50
        out['cd_trend'] = 'rising' if cd_now > cd_50 else 'falling'
    else:
        out['cd_change_50'] = None
        out['cd_trend'] = None

    # Volume Profile (last 100 bars)
    if n >= 30:
        recent = ohlcv[-min(150, n):]
        bucket = (out['atr_last'] / 10) if out['atr_last'] else max(1.0, (max(b[1] for b in recent) - min(b[2] for b in recent)) / 50)
        vp = volume_profile(recent, bucket_size=bucket)
        if vp:
            out['vp_poc'] = vp.poc
            out['vp_val'] = vp.val
            out['vp_vah'] = vp.vah
    else:
        out['vp_poc'] = out['vp_val'] = out['vp_vah'] = None

    # VIC ASVK на последнем HTF баре (нужны 1m данные внутри последнего бара)
    tf_min = TF_SPECS[tf_name][0]
    if data_sliced_1m and bars:
        last_bar_open_ms = bars[-1][0]
        last_bar_end_ms = last_bar_open_ms + tf_min * 60_000
        ltf_min = auto_ltf_minutes(tf_min)
        ltf_bucket_ms = ltf_min * 60_000
        # Берём 1m внутри последнего HTF бара, агрегируем в LTF
        ltf_buckets: dict = {}
        for ts, o, h, l, c, v in data_sliced_1m:
            if last_bar_open_ms <= ts < last_bar_end_ms:
                b = ts - (ts % ltf_bucket_ms)
                ltf_buckets.setdefault(b, []).append((ts, o, h, l, c, v))
        ltf_bars = []
        for b in sorted(ltf_buckets):
            rs = sorted(ltf_buckets[b], key=lambda x: x[0])
            ltf_bars.append((
                b, rs[0][1],
                max(r[2] for r in rs), min(r[3] for r in rs),
                rs[-1][4], sum(r[5] for r in rs),
            ))
        vic = calculate_vic_bar(ltf_bars)
        if vic:
            out['vic_maxV'] = vic.maxV
            out['vic_delta'] = vic.delta
            out['vic_norm'] = vic.norm
            out['vic_ltf'] = f"{ltf_min}m"

    # ASVK Trend Line (Hull)
    if n >= 100:
        tl = trend_line_asvk(closes, length=49, length_mult=1.6, mode='Hma')
        out['trendline_color'] = tl['color'][-1]
        out['trendline_shull'] = tl['shull'][-1]
    else:
        out['trendline_color'] = None
        out['trendline_shull'] = None

    # ASVK RSI
    if n >= 50:
        ar = adjusted_rsi(closes, period=14)
        out['rsi_ema3'] = ar['ema_3'][-1]
        out['rsi_zone'] = asvk_zone(
            ar['ema_3'][-1], ar['above'][-1], ar['below'][-1],
            ar['nwe_upper'][-1], ar['nwe_lower'][-1],
        )
    else:
        out['rsi_ema3'] = None
        out['rsi_zone'] = None

    # Money Hands
    if n >= 100:
        mh = money_hands(ohlcv)
        out['mh_bw2'] = mh['bw2'][-1]
        out['mh_color'] = mh['color'][-1]
        out['mh_mf'] = mh['mf'][-1]
    else:
        out['mh_bw2'] = None
        out['mh_color'] = None
        out['mh_mf'] = None

    return out


def print_tf_summary(res):
    if res is None:
        print("   [empty window]\n"); return
    tf = res['tf']
    print(f"\n{'═'*78}")
    print(f"  TF {tf:<4}  (lookback {res['lookback_days']}d, radius ±{res['radius']*100:.1f}%, bars in window: {res['bars_count']})")
    print(f"{'═'*78}")

    if res['forming']:
        f = res['forming']
        bucket_end = f[0] + TF_SPECS[tf][0] * 60_000
        print(f"  Forming bar: O={f[1]:.2f} H={f[2]:.2f} L={f[3]:.2f} C={f[4]:.2f}  → closes {fmt_full(bucket_end)}")

    counts = {k: len(v) for k, v in res['hits'].items() if v}
    print(f"  Detections: " + ", ".join(f"{k}={n}" for k, n in counts.items()) + f"  ·  total {res['total']}")

    # Position
    flat = res['flat']
    inside = [x for x in flat if x[5] == "INSIDE"]
    above = [x for x in flat if x[5] == "above"]
    below = [x for x in flat if x[5] == "below"]
    print(f"\n  Zones near close {res['last_close']:.2f} (radius ±{res['radius']*100:.1f}%): {len(flat)} total")

    if inside:
        print(f"\n  ⊙ INSIDE ({len(inside)}):")
        for ts, name, lo, hi, dir_, _, klass in inside[:10]:
            pt = "level" if lo == hi else f"[{lo:.0f},{hi:.0f}]"
            print(f"     {fmt_short(ts):>5} {name:<12} {dir_:<5} {pt:<18} {klass}")
    if above:
        print(f"\n  ↑ ABOVE ({len(above)}):")
        for ts, name, lo, hi, dir_, _, klass in above[:10]:
            pt = f"{lo:.0f}" if lo == hi else f"[{lo:.0f},{hi:.0f}]"
            rel = (((lo+hi)/2 - res['last_close']) / res['last_close']) * 100
            print(f"     {fmt_short(ts):>5} {name:<12} {dir_:<5} {pt:<18} +{rel:.2f}%  {klass}")
    if below:
        print(f"\n  ↓ BELOW ({len(below)}):")
        for ts, name, lo, hi, dir_, _, klass in below[:10]:
            pt = f"{lo:.0f}" if lo == hi else f"[{lo:.0f},{hi:.0f}]"
            rel = (((lo+hi)/2 - res['last_close']) / res['last_close']) * 100
            print(f"     {fmt_short(ts):>5} {name:<12} {dir_:<5} {pt:<18} {rel:.2f}%  {klass}")

    # Magnets
    magnets_ineff = [x for x in flat if 'inefficiency' in x[6]]
    magnets_liq = [x for x in flat if 'liquidity' in x[6] or 'liq' in x[6]]
    print(f"\n  🧲 Magnets near price: inefficiency={len(magnets_ineff)}, liquidity={len(magnets_liq)}")

    # Indicators layer (Step 5b)
    ind = res.get('indicators', {})
    if ind:
        print(f"\n  📊 Indicators:")
        last_c = res['last_close']
        if ind.get('atr_last') is not None:
            print(f"     ATR(14):      {ind['atr_last']:.2f}  ({ind['atr_last']/last_c*100:.2f}% от close)")
        if ind.get('ema200_last') is not None:
            pos = ind['ema200_position']
            print(f"     EMA-200:      {ind['ema200_last']:.2f}  (price {pos})")
        if ind.get('cd_trend'):
            sign = '+' if ind['cd_change_50'] > 0 else ''
            print(f"     Cum.Delta-50: {ind['cd_trend']}  ({sign}{ind['cd_change_50']:.0f})")
        if ind.get('vp_poc') is not None:
            print(f"     VolProfile:   POC={ind['vp_poc']:.0f}  VAL={ind['vp_val']:.0f}  VAH={ind['vp_vah']:.0f}")
        if ind.get('vic_maxV') is not None:
            print(f"     VIC ASVK:     maxV={ind['vic_maxV']:.0f}  delta={ind['vic_delta']:+.0f}  norm={ind['vic_norm']:+.2f}  (LTF={ind.get('vic_ltf','?')})")
        if ind.get('trendline_color'):
            sh = ind.get('trendline_shull')
            sh_str = f"{sh:.0f}" if sh else "—"
            print(f"     ASVK Hull:    color={ind['trendline_color']}  SHULL={sh_str}")
        if ind.get('rsi_zone'):
            print(f"     ASVK RSI:     zone={ind['rsi_zone']}  ema_3={ind['rsi_ema3']:.1f}")
        if ind.get('mh_color'):
            mf = ind.get('mh_mf')
            mf_str = f"{mf:+.1f}" if mf is not None else "—"
            print(f"     MoneyHands:   color={ind['mh_color']}  bw2={ind['mh_bw2']:+.1f}  MF={mf_str}")


def print_vwap_rankings(data, results, last_close, tfs):
    """Считает VWAP от каждого D-фрактала за 1 год, эффективность через все ТФ.
    Печатает: 2 ближайших + 6 самых эффективных + 2 самых дальних."""
    print(f"\n{'═'*78}")
    print(f"  VWAPs ASVK — anchored от D-фракталов за 1 год, ranked across all TFs")
    print(f"{'═'*78}")

    # 1. Найти все D-фракталы за последний 1 год
    last_1m_ts = data[-1][0]
    year_ago_ms = last_1m_ts - 365 * 24 * 3600 * 1000

    lo, hi = 0, len(data)
    while lo < hi:
        m = (lo + hi) // 2
        if data[m][0] < year_ago_ms - 14 * 24 * 3600 * 1000: lo = m + 1
        else: hi = m
    data_year = data[lo:]

    d_bars = aggregate(data_year, 'D')
    d_candles = [to_candle(r) for r in d_bars]

    anchors = []   # (anchor_ts, level, direction)
    for i in range(2, len(d_candles) - 2):
        if d_bars[i][0] < year_ago_ms:
            continue
        r = detect_fractal(d_candles[i-2:i+3], n=2)
        if r:
            anchors.append((d_bars[i][0], r.level, r.direction))

    if not anchors:
        print("  (нет подтверждённых D-фракталов в окне)")
        return

    print(f"  Найдено {len(anchors)} D-фракталов. Расчёт VWAP и эффективности...\n")

    # 2. Для каждого anchor — посчитать VWAP во всех ТФ и effectiveness
    rankings = []
    for anchor_ts, level, direction in anchors:
        per_tf = []
        vwap_now_per_tf = {}
        for tf in tfs:
            tf_min = TF_SPECS[tf][0]
            # Берём bars из results (уже агрегированы)
            res = results.get(tf)
            if res is None:
                continue
            bars = res['bars']
            if not bars:
                continue
            # Найти индекс anchor бара в этом ТФ
            tf_bucket_ms = tf_min * 60_000
            anchor_bucket = anchor_ts - (anchor_ts % tf_bucket_ms) if tf != 'W' else anchor_ts - ((anchor_ts - MONDAY_OFFSET_MS) % WEEK_MS)
            anchor_idx = None
            for idx, b in enumerate(bars):
                if b[0] >= anchor_bucket:
                    anchor_idx = idx
                    break
            if anchor_idx is None:
                continue
            ohlcv = [(b[1], b[2], b[3], b[4], b[5]) for b in bars]
            vw_series = anchored_vwap(ohlcv, anchor_idx)
            # VWAP-значение на последнем баре (closed)
            vw_now = vw_series[-1]
            vwap_now_per_tf[tf] = vw_now

            # Effectiveness: bars от anchor до конца
            ohlc_pairs = [(b[1], b[2], b[3], b[4]) for b in bars[anchor_idx:]]
            vw_pairs = vw_series[anchor_idx:]
            eff = effectiveness_per_tf(tf, ohlc_pairs, vw_pairs)
            per_tf.append(eff)

        comp = composite_effectiveness(anchor_ts, per_tf)
        # VWAP_now усреднённый для определения "ближайший/дальний" к цене
        valid_now = [v for v in vwap_now_per_tf.values() if v is not None]
        vwap_avg_now = sum(valid_now) / len(valid_now) if valid_now else level
        rankings.append({
            'anchor_ts': anchor_ts,
            'anchor_level': level,
            'direction': direction,
            'vwap_now': vwap_avg_now,
            'distance': abs(vwap_avg_now - last_close),
            'composite': comp.composite,
            'total_interactions': comp.total_interactions,
            'per_tf': per_tf,
        })

    # 3. Selection: 2 closest + 6 most effective + 2 farthest (без дубликатов)
    by_distance = sorted(rankings, key=lambda r: r['distance'])
    closest_2 = by_distance[:2]
    farthest_2 = by_distance[-2:] if len(by_distance) >= 2 else []
    selected_ids = {id(r) for r in closest_2 + farthest_2}
    remaining = [r for r in rankings if id(r) not in selected_ids]
    by_effective = sorted(remaining, key=lambda r: -r['composite'])
    effective_6 = by_effective[:6]
    final = closest_2 + effective_6 + farthest_2

    def fmt_date(ms): return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MSK).strftime('%Y-%m-%d')

    print(f"  Selection (2 closest + 6 effective + 2 farthest):\n")
    headers = ('Date', 'Type', 'Level', 'VWAP_now', 'Δ%close', 'Comp.', 'Touches', 'Tag')
    print(f"  {headers[0]:<11} {headers[1]:<5} {headers[2]:>9} {headers[3]:>10} {headers[4]:>8} {headers[5]:>6} {headers[6]:>8}  {headers[7]}")
    for tag, group in [('CLOSE', closest_2), ('EFFEC', effective_6), ('FARMS', farthest_2)]:
        for r in group:
            d = fmt_date(r['anchor_ts'])
            t = 'FH' if r['direction'] == 'high' else 'FL'
            delta_pct = (r['vwap_now'] - last_close) / last_close * 100
            print(f"  {d:<11} {t:<5} {r['anchor_level']:>9.0f} {r['vwap_now']:>10.0f} {delta_pct:>+8.2f} {r['composite']:>6.3f} {r['total_interactions']:>8}  {tag}")
        print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tfs", type=str, default=",".join(DEFAULT_CASCADE),
                   help=f"comma-separated TFs (default: {','.join(DEFAULT_CASCADE)})")
    p.add_argument("--radius", type=float, default=None,
                   help="override radius (default: per-TF auto)")
    args = p.parse_args()

    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]
    for tf in tfs:
        if tf not in TF_SPECS:
            print(f"Unknown TF '{tf}'. Valid: {list(TF_SPECS.keys())}")
            return

    print(f"\n╔{'═'*76}╗")
    print(f"║  EXPERT OPINION — MULTI-TF CASCADE  ({' → '.join(tfs)})".ljust(77) + "║")
    print(f"╚{'═'*76}╝")

    print("\nStep 1. Loading 1m data...")
    data = load_1m()
    last_1m_ts = data[-1][0]
    last_close = data[-1][4]
    print(f"  Last 1m: {fmt_full(last_1m_ts)}  ·  close = {last_close:.2f}")

    # Сохраняем fractal sequences per TF для cascade analysis
    fractal_seq = {}
    results = {}
    for tf in tfs:
        res = analyze_tf(data, tf, args.radius, fractal_seq)
        results[tf] = res
        print_tf_summary(res)

    # VWAPs ranking — anchor на D-фракталах за последний 1 год,
    # эффективность через все ТФ каскада.
    print_vwap_rankings(data, results, last_close, tfs)

    # Cascade integration summary (Step 7) — fractal-based trend per TF
    print(f"\n{'═'*78}")
    print(f"  CASCADE INTEGRATION (Step 7) — trend per TF из fractal sequence")
    print(f"{'═'*78}")
    for tf in tfs:
        fseq = fractal_seq.get(tf, [])
        if not fseq:
            print(f"  {tf:<4}: no fractals detected"); continue
        fseq_sorted = sorted(fseq, key=lambda x: x[0])
        fh = [(ts, lvl) for ts, lvl, d in fseq_sorted if d == 'high']
        fl = [(ts, lvl) for ts, lvl, d in fseq_sorted if d == 'low']
        last_fh = fh[-3:] if fh else []
        last_fl = fl[-3:] if fl else []
        fh_str = " → ".join(f"{lvl:.0f}" for _, lvl in last_fh) if last_fh else "—"
        fl_str = " → ".join(f"{lvl:.0f}" for _, lvl in last_fl) if last_fl else "—"
        fh_trend = "HH" if len(fh) >= 2 and fh[-1][1] > fh[-2][1] else ("LH" if len(fh) >= 2 else "?")
        fl_trend = "HL" if len(fl) >= 2 and fl[-1][1] > fl[-2][1] else ("LL" if len(fl) >= 2 else "?")
        regime = ""
        if fh_trend == "HH" and fl_trend == "HL": regime = "UPTREND"
        elif fh_trend == "LH" and fl_trend == "LL": regime = "DOWNTREND"
        elif fh_trend == "LH" and fl_trend == "HL": regime = "CONTRACTION"
        elif fh_trend == "HH" and fl_trend == "LL": regime = "EXPANSION"
        print(f"  {tf:<4}: FH {fh_str:<25} ({fh_trend})   FL {fl_str:<25} ({fl_trend})   → {regime}")

    print(f"\n--- cascade output ready for Steps 7b-10 (confluence, scenarios, invalidation) ---\n")


if __name__ == "__main__":
    main()
