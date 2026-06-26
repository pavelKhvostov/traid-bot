"""МОДУЛЬ АНАЛИТИКИ — единое ядро (наш контекст + zone-движок Вадима + его descriptive-законы).

Принцип «один движок — два потребителя»: и живой бот-отчёт, и бэктест-harness читают ОДНУ функцию
analyze_at() → каждый вывод автоматически бэктест-валидируем, без дрейфа.

Слои (см. vault [[vadim-integration-living-market-laws]]):
  контекст (наш mtf/режим/ATR/позиция) + зона-ландшафт (Вадим канон, КАУЗАЛЬНО) +
  ЗАКОНЫ Вадима как scored-функции:
    • magnet/clear-path  — зоны = МАГНИТЫ (его «untraded=магнит»): драг против сделки; чистый путь = good
                           (эмпирически: mtf+clear-path = +0.309R vs mtf-alone +0.182R)
    • realistic-TP       — ближайший значимый магнит ПО направлению, ≤ масштаб-закон (наш extent 0.49×/ATR)
    • taxonomy-роли      — liquidity ⛽ / inefficiency 🧲 / block 🎯
    • mitigation         — зоны уже сжаты/съедены движком Вадима
    • fresh-look         — уровень инвалидации; слом → «план аннулирован»
  fusion: направление(mtf) × качество(clear-path) × цель(realistic) → setup-score + вердикт.

Descriptive-законы идут в отчёт сразу; predictive (force-model) — отдельно, через harness.
API:
    pc = precompute(df_1m)                     # один раз (зоны+resample+mtf)
    st = analyze_at(pc, ts)                    # каузальный снимок аналитики на ts
    st = analyze_live("BTCUSDT")               # удобный live-вход (CSV/fetch)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "ta_laws"))
import geometry as G  # noqa: E402
import curves as C    # noqa: E402
from research.smc_adapter import (  # noqa: E402
    precompute_zone_events, snapshot_from_events, zone_confluence, ROLE, TF_W, ZTYPES_FAST)

ZONE_TFS = ("4h", "12h", "1d")
ARC_TFS = ("1h", "4h")
SL_ATR = 1.5
RR = 2.0
MAX_EXT_ATR = 3.0           # потолок realistic-TP по нашему extent-закону
CLEAR_PATH_THR = 20.0       # порог magnet_against: ниже = чистый путь (из zone_confluence-теста)


# ───────────────────────── dataclasses ─────────────────────────
@dataclass
class ZoneLite:
    tf: str
    type: str
    role: str            # liquidity | inefficiency | block
    side: str            # above | below | inside
    lo: float
    hi: float
    level: float | None
    dist_pct: float
    age: int
    mitigation: str


@dataclass
class SetupRead:
    kind: str            # ROUNDING_TOP | ROUNDING_BOTTOM
    direction: str       # LONG | SHORT (= fade конца дуги)
    mtf_aligned: bool
    magnet_against: float
    clear_path: bool
    entry: float
    stop: float
    target: float
    rr: float
    invalidation: float  # fresh-look: слом → план аннулирован
    verdict: str


@dataclass
class AnalyticsState:
    symbol: str
    ts: pd.Timestamp
    price: float
    ctx: dict
    zones: list = field(default_factory=list)     # ZoneLite, near-price
    setups: list = field(default_factory=list)    # SetupRead
    summary: str = ""
    magnet_long: float = 0.0      # драг зон-магнитов против LONG (снизу)
    magnet_short: float = 0.0     # против SHORT (сверху)
    clear_side: str = ""          # LONG | SHORT — где путь чище (меньше магнит)
    tp_up: float = 0.0            # realistic-TP вверх (ближайший магнит ≤ extent)
    tp_down: float = 0.0          # realistic-TP вниз


# ───────────────────────── helpers ─────────────────────────
def _rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def _trend(series, ts, td):
    a = series.asof(ts); b = series.asof(ts - td)
    return "UP" if (pd.notna(a) and pd.notna(b) and a > b) else "DOWN"


def magnet_against(zones, price, trade_dir: str, max_dist=4.0) -> float:
    """Драг зон-магнитов ПРОТИВ сделки (его закон untraded=магнит).
    LONG (ждём вверх) — магниты СНИЗУ тянут вниз; SHORT — магниты СВЕРХУ. Переиспользует zone_confluence."""
    fade = "UP" if trade_dir == "LONG" else "DOWN"          # zone_confluence(fade UP) скорит зоны снизу
    return zone_confluence(zones, price, fade, max_dist)["score"]


def realistic_tp(zones, price, trade_dir: str, atr: float) -> float:
    """Ближайший значимый магнит ПО направлению сделки, ≤ масштаб-закон (price ± MAX_EXT_ATR·ATR).
    Fallback при отсутствии зоны = RR-цель price ± 1.5·ATR (наш extent)."""
    d = 1 if trade_dir == "LONG" else -1
    cap = price + d * MAX_EXT_ATR * atr
    want = "above" if trade_dir == "LONG" else "below"
    cands = []
    for z in zones:
        if z.side != want or getattr(z, "distance_pct", getattr(z, "dist_pct", 0)) < 0.3:
            continue
        lvl = z.level if z.level is not None else (z.lo if trade_dir == "LONG" else z.hi)
        if (trade_dir == "LONG" and lvl > price) or (trade_dir == "SHORT" and lvl < price):
            cands.append(lvl)
    if cands:
        tp = min(cands) if trade_dir == "LONG" else max(cands)
        tp = min(tp, cap) if trade_dir == "LONG" else max(tp, cap)   # не дальше масштаб-потолка
        return float(tp)
    return float(price + d * SL_ATR * RR * atr)                       # extent-fallback


# ───────────────────────── precompute ─────────────────────────
@dataclass
class Precomp:
    symbol: str
    df_1m: pd.DataFrame
    ev: dict
    resampled: dict
    mtf: dict             # tf -> (close series, td)
    arc: dict             # arc_tf -> dict(df, o,h,l,c, atr, n)
    btc_1d: pd.Series     # для режима (передаётся отдельно)


def precompute(df_1m: pd.DataFrame, symbol="BTCUSDT", btc_1d: pd.Series | None = None,
               zone_tfs=ZONE_TFS, arc_tfs=ARC_TFS) -> Precomp:
    ev, resampled = precompute_zone_events(df_1m, tfs=zone_tfs, types=ZTYPES_FAST)
    mtf = {"1h": (_rs(df_1m, "1h")["close"], pd.Timedelta(hours=10)),
           "4h": (_rs(df_1m, "4h")["close"], pd.Timedelta(hours=40)),
           "1d": (_rs(df_1m, "1d")["close"], pd.Timedelta(days=10))}
    arc = {}
    for tf in arc_tfs:
        df = _rs(df_1m, tf)
        arc[tf] = {"df": df, "o": df["open"].values, "h": df["high"].values,
                   "l": df["low"].values, "c": df["close"].values,
                   "atr": G.compute_atr(df), "n": len(df)}
    if btc_1d is None:
        btc_1d = mtf["1d"][0]
    return Precomp(symbol, df_1m, ev, resampled, mtf, arc, btc_1d)


# ───────────────────────── analyze ─────────────────────────
def _context(pc: Precomp, ts, price, atr_pct, range_pos):
    t1 = _trend(pc.mtf["1h"][0], ts, pc.mtf["1h"][1])
    t4 = _trend(pc.mtf["4h"][0], ts, pc.mtf["4h"][1])
    td = _trend(pc.mtf["1d"][0], ts, pc.mtf["1d"][1])
    up = sum(t == "UP" for t in (t1, t4, td))
    word = {3: "сильно ВВЕРХ", 0: "сильно ВНИЗ"}.get(up, "ВВЕРХ" if up >= 2 else "ВНИЗ")
    a = pc.btc_1d.asof(ts); b = pc.btc_1d.asof(ts - pd.Timedelta(days=30))
    regime = (1 if a > b else -1) if (pd.notna(a) and pd.notna(b) and b > 0) else 0
    return dict(t1=t1, t4=t4, td=td, mtf_up=up, word=word, regime=regime,
                atr_pct=round(atr_pct, 2), range_pos=round(range_pos, 1))


def _zones_near(zones, price, max_dist=5.0):
    out = []
    for z in zones:
        if z.distance_pct > max_dist:
            continue
        out.append(ZoneLite(z.tf, z.type, ROLE.get(z.type, "block"), z.side,
                            round(z.lo, 1), round(z.hi, 1),
                            None if z.level is None else round(z.level, 1),
                            round(z.distance_pct, 2), int(z.age_bars), z.mitigation_model))
    return sorted(out, key=lambda z: z.dist_pct)


def _recent_arc_setup(pc: Precomp, ts, price, zones, ctx, recency_bars=30):
    """Свежая завершённая арка на arc_tf (каузально ≤ ts) → SetupRead по законам."""
    best = None
    for tf in pc.arc:
        a = pc.arc[tf]; df = a["df"]; n = a["n"]
        # последний закрытый бар ≤ ts
        idx = df.index.searchsorted(ts, side="right") - 1
        if idx < 30:
            continue
        arcs = C.find_arcs(df.iloc[:idx + 1], atr=a["atr"][:idx + 1])
        arcs = [ar for ar in arcs if ar.i1 >= idx - recency_bars and ar.i1 < idx]
        for ar in arcs:
            L = ar.i1 - ar.i0; aa, bb, _ = ar.coeffs
            end_dir = "UP" if (2 * aa * L + bb) > 0 else "DOWN"
            apex = (ar.apex_i - ar.i0) / max(L, 1)
            if not (ar.sagitta_atr >= 2.5 and apex >= 0.4):
                continue
            trade_dir = "LONG" if end_dir == "DOWN" else "SHORT"   # fade конца дуги
            atr_a = a["atr"][ar.i1]
            best = (ar, tf, trade_dir, atr_a)
    if best is None:
        return None
    ar, tf, trade_dir, atr_a = best
    fade = "UP" if trade_dir == "LONG" else "DOWN"
    mtf_aligned = sum(int(_trend(s, ts, td) == fade) for _t, (s, td) in pc.mtf.items()) >= 2
    mag = magnet_against(zones, price, trade_dir)
    clear = mag < CLEAR_PATH_THR
    d = 1 if trade_dir == "LONG" else -1
    entry = price
    stop = entry - SL_ATR * atr_a * d
    target = realistic_tp(zones, price, trade_dir, atr_a)
    rr = abs(target - entry) / max(abs(entry - stop), 1e-9)
    if mtf_aligned and clear:
        verdict = "✅ ТОРГУЕМЫЙ: тренд за + путь чист (валидир. +0.309R-класс)"
    elif mtf_aligned and not clear:
        verdict = "⚠️ магнит против цели → ждать/пропуск (зоны тянут назад)"
    else:
        verdict = "⛔ против контекста → не торговать (fade-зона −R)"
    return SetupRead(ar.kind, trade_dir, mtf_aligned, round(mag, 1), clear,
                     round(entry, 1), round(stop, 1), round(target, 1), round(rr, 2),
                     round(stop, 1), verdict)


def analyze_at(pc: Precomp, ts: pd.Timestamp | None = None) -> AnalyticsState:
    if ts is None:
        ts = pc.df_1m.index[-1] + pd.Timedelta(minutes=1)
    cut = pc.df_1m.loc[pc.df_1m.index < ts]
    price = float(cut["close"].iloc[-1])
    # ATR% и позиция в диапазоне по 1h
    h1 = pc.mtf["1h"][0]
    df1 = pc.arc.get("1h", {}).get("df")
    if df1 is not None:
        i = df1.index.searchsorted(ts, side="right") - 1
        atr1 = pc.arc["1h"]["atr"]; a_pct = atr1[i] / price * 100 if i >= 0 else 0.3
        lo = pc.arc["1h"]["l"][max(0, i - 50):i + 1].min()
        hi = pc.arc["1h"]["h"][max(0, i - 50):i + 1].max()
        rng = (price - lo) / (hi - lo) * 100 if hi > lo else 50
    else:
        a_pct, rng = 0.3, 50.0
    atr_now = float(atr1[i]) if (df1 is not None and i >= 0 and atr1[i] > 0) else price * 0.003
    zraw = snapshot_from_events(pc.ev, pc.resampled, pc.df_1m, ts)
    zones = _zones_near(zraw, price)
    ctx = _context(pc, ts, price, a_pct, rng)
    setup = _recent_arc_setup(pc, ts, price, zraw, ctx)
    setups = [setup] if setup else []
    # ФИЛЬТР (магнит/clear-path) + ЦЕЛЬ (realistic-TP) — всегда, даже без сетапа
    mag_long = zone_confluence(zraw, price, "UP")["score"]
    mag_short = zone_confluence(zraw, price, "DOWN")["score"]
    clear_side = "LONG" if mag_long < mag_short else "SHORT"
    tp_up = realistic_tp(zraw, price, "LONG", atr_now)
    tp_down = realistic_tp(zraw, price, "SHORT", atr_now)
    # summary
    nb = sum(1 for z in zones if z.role == "block")
    summ = (f"Контекст {ctx['word']} ({ctx['mtf_up']}/3) · ATR {ctx['atr_pct']}% · "
            f"в диапазоне {ctx['range_pos']:.0f}% · зон у цены {len(zones)} (block {nb}). ")
    if setups:
        summ += setups[0].verdict
    else:
        summ += "Свежего arc-сетапа нет — ждать pullback в сторону тренда."
    return AnalyticsState(pc.symbol, ts, round(price, 1), ctx, zones, setups, summ,
                          round(mag_long, 1), round(mag_short, 1), clear_side,
                          round(tp_up, 1), round(tp_down, 1))


# ───────────────────────── live convenience ─────────────────────────
def _load_1m_csv(symbol):
    df = pd.read_csv(ROOT / "data" / f"{symbol}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def analyze_live(symbol="BTCUSDT", lookback_days=140, df_1m=None) -> AnalyticsState:
    """Удобный вход: берёт хвост 1m (CSV или переданный df), precompute на окне, снимок на now."""
    if df_1m is None:
        df_1m = _load_1m_csv(symbol)
    df_1m = df_1m.loc[df_1m.index >= df_1m.index[-1] - pd.Timedelta(days=lookback_days)]
    pc = precompute(df_1m, symbol=symbol)
    return analyze_at(pc, None)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    st = analyze_live("BTCUSDT")
    print(f"\n=== {st.symbol} @ {st.ts:%Y-%m-%d %H:%M} UTC  ${st.price:,.0f} ===")
    print(st.summary)
    print(f"\nЗоны у цены ({len(st.zones)}):")
    for z in st.zones[:8]:
        print(f"  {z.tf:>3} {z.type:<9} {z.role:<12} {z.side:<6} dist {z.dist_pct:5.2f}% age {z.age:>4} mit {z.mitigation}")
    for s in st.setups:
        print(f"\nСЕТАП {s.kind} {s.direction}: вход {s.entry:,.0f} стоп {s.stop:,.0f} цель {s.target:,.0f} "
              f"(RR {s.rr}) | mtf_aligned={s.mtf_aligned} magnet_against={s.magnet_against} clear={s.clear_path}")
        print(f"  {s.verdict}")
        print(f"  fresh-look инвалидация: слом {s.invalidation:,.0f} → план аннулирован")
