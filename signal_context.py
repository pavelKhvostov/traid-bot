"""Авто-комментарий к сигналу 1.1.1: тип дня + confluence + зоны + цели + магниты.

При срабатывании 1.1.1 формируем человеческий блок «контекст рынка», опираясь на
day-type модель (Dalton Initial Balance, etap_217) и объёмный профиль. Ключевая
находка (etap_232, 228 сделок OOS, floating TP):

  1.1.1 — это ВОЗВРАТ в HTF-зону. Лучшие входы — когда внутридневной тренд
  гонит цену ПРОТИВ направления сделки В зону:
    • SHORT в растущий день (фейд в supply)  → 70.5% WR / +36.3R (n=61)
    • LONG  в падающий день (фейд в demand)   → 77.8% WR / +23.6R (n=27)
  Вход ПО тренду дня (continuation) — слабейший случай (30% WR, n=10).

Поэтому модуль НЕ фильтрует сигнал, а ОЦЕНИВАЕТ контекст и подсказывает размер.

Всё считается из тех же live-CSV (data/<SYM>_<TF>.csv). Модель типа дня обучается
один раз на BTC 1h < 2023 и кэшируется. Блок не должен ломать сигнал — любая
ошибка внутри → пустая строка (см. build_context).

Источник логики типа дня: research/daily_engine/etap_217_daytype_layer.py.
Источник цифр ячеек: research/daily_engine/etap_232_*.py.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df

try:
    import reversal as _RV
except Exception:
    _RV = None

ROOT = Path(__file__).resolve().parent
ORDERFLOW = ROOT / "data" / "BTCUSDT_1h_orderflow.csv"

# --- day-type параметры (1:1 с etap_217) ---
IB = 3
EXT = 0.10
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")
FEATS = ["ret_k", "pos_rng", "ext_up", "ext_dn", "above_ib", "below_ib",
         "dist_ib", "open_drive", "ib_formed"]

# исторические цифры ячеек (etap_239: ДЕДУП 115 уникальных сделок 1.1.1 floating,
# строгий протокол «только закрытые бары», BTC OOS 2023+). Адверсариальный ревью
# нашёл дубли каскада в run_symbol_backtest (228 строк = 115 уникальных) —
# прежние n=61/27 были раздуты. Ячейки прошли годовую проверку на дедупе:
# CT выше прочего по WR во всех 4 годах, обе топ-ячейки в плюсе каждый год.
# Значения SHRUNK (beta-binomial, alpha=10, prior=pooled 50.4%) — ml-8.
# Ячейки валидированы ТОЛЬКО для 1.1.1; малые ячейки (n<=3) не печатаем.
CELL_STATS = {
    ("SHORT", "TREND_UP"):   "~67% WR, n=38, сглаж.",
    ("LONG", "TREND_DOWN"):  "~60% WR, n=20, сглаж.",
}

_MODEL: dict | None = None
_HOLD: dict | None = None


def shrunk_rate(hits: int, n: int, prior: float, alpha: float = 10.0) -> float:
    """Beta-binomial shrinkage: эмпирическая частота, стянутая к prior.

    Защищает ячейки с малым n от шумных крайних значений (etap_234, ml-7)."""
    return (hits + prior * alpha) / (n + alpha)


# ----------------------------------------------------------------------------
# day-type движок (инлайн копия etap_217 — production не зависит от research/)
# ----------------------------------------------------------------------------
def _classify(row) -> str:
    if not row["ib_formed"]:
        return "FORMING"
    if row["above_ib"] and row["ext_up"] >= EXT:
        return "TREND_UP"
    if row["below_ib"] and row["ext_dn"] >= EXT:
        return "TREND_DOWN"
    return "ROTATION"


def _build_rows(g: pd.DataFrame, green: int | None = None) -> pd.DataFrame:
    """Фичи по часам одного дня g (отсортирован по времени)."""
    o = g["open"].iloc[0]
    c = g["close"].values; H = g["high"].values; Lo = g["low"].values
    hi = np.maximum.accumulate(H); lo = np.minimum.accumulate(Lo)
    ib_h, ib_l = H[:IB].max(), Lo[:IB].min()
    ib_r = max(ib_h - ib_l, 1e-9); ib_mid = (ib_h + ib_l) / 2
    od = (c[0] - o) / ib_r
    rows = []
    for k in range(len(g)):
        f = k >= IB; rng = hi[k] - lo[k]
        rec = dict(k=k, ret_k=c[k] / o - 1,
                   pos_rng=(c[k] - lo[k]) / rng if rng > 0 else 0.5,
                   ext_up=max(0, hi[k] - ib_h) / ib_r if f else 0.0,
                   ext_dn=max(0, ib_l - lo[k]) / ib_r if f else 0.0,
                   above_ib=int(c[k] > ib_h) if f else 0,
                   below_ib=int(c[k] < ib_l) if f else 0,
                   dist_ib=(c[k] - ib_mid) / ib_r if f else 0.0,
                   open_drive=od, ib_formed=int(f))
        if green is not None:
            rec["green"] = green
        rows.append(rec)
    return pd.DataFrame(rows)


def _get_model() -> dict | None:
    """Per-hour логистика на BTC 1h < 2023. Обучается один раз, кэш."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from sklearn.linear_model import LogisticRegression
        df = pd.read_csv(ORDERFLOW, index_col=0, parse_dates=True)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df = df[df.index < CUTOFF]
        parts = []
        for _, g in df.groupby(df.index.normalize()):
            if len(g) < IB + 2:
                continue
            green = int(g["close"].iloc[-1] > g["open"].iloc[0])
            parts.append(_build_rows(g, green))
        R = pd.concat(parts, ignore_index=True).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        M = {}
        for k in range(24):
            s = R[R.k == k]
            if len(s) >= 50 and s.green.nunique() == 2:
                M[k] = LogisticRegression(max_iter=400).fit(s[FEATS], s.green)
        _MODEL = M
    except Exception:
        _MODEL = {}
    return _MODEL


def _get_hold_table() -> dict:
    """P(состояние часа k доживёт до конца дня | state, k) — таблица с shrinkage.

    Train BTC < 2023, OOS-калибровка проверена в etap_234 (Brier 0.207,
    pred≈факт во всех ячейках). Это персистентность НАБЛЮДАЕМОГО состояния,
    не прогноз направления."""
    global _HOLD
    if _HOLD is not None:
        return _HOLD
    try:
        df = pd.read_csv(ORDERFLOW, index_col=0, parse_dates=True)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df = df[df.index < CUTOFF]
        recs = []  # (state_k, k, final_state)
        for _, g in df.groupby(df.index.normalize()):
            if len(g) < IB + 2:
                continue
            rows = _build_rows(g).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            states = [_classify(r) for _, r in rows.iterrows()]
            final = states[-1]
            for k, st in enumerate(states):
                if k >= IB:
                    recs.append((st, k, final))
        tbl = {}
        for st in ("TREND_UP", "TREND_DOWN", "ROTATION"):
            sub = [(k, f) for s, k, f in recs if s == st]
            prior = (sum(1 for _, f in sub if f == st) / len(sub)) if sub else 0.5
            for k in range(IB, 24):
                cell = [f for kk, f in sub if kk == k]
                tbl[(st, k)] = shrunk_rate(sum(1 for f in cell if f == st),
                                           len(cell), prior)
        _HOLD = tbl
    except Exception:
        _HOLD = {}
    return _HOLD


def trend_hold_p(state: str, k: int) -> float | None:
    """P(текущее состояние доживёт до конца дня) или None (FORMING/нет данных)."""
    tbl = _get_hold_table()
    return tbl.get((state, min(max(k, IB), 23)))


def day_state(symbol: str, at: pd.Timestamp) -> tuple[str, float, int]:
    """Тип дня символа на момент `at` по барам дня ТОЛЬКО до этого часа.

    Возврат: (state, P_green, k). state ∈ FORMING/ROTATION/TREND_UP/TREND_DOWN.
    """
    df = load_df(symbol, "1h")
    if df.empty:
        return "FORMING", 0.5, 0
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    if at.tz is None:
        at = at.tz_localize("UTC")
    day = at.normalize()
    bars = df[(df.index.normalize() == day) & (df.index <= at)]
    if len(bars) < IB + 2:
        return "FORMING", 0.5, len(bars)
    rows = _build_rows(bars).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    last = rows.iloc[-1]
    state = _classify(last)
    M = _get_model()
    p = 0.5
    if M and int(last["k"]) in M:
        p = float(M[int(last["k"])].predict_proba(last[FEATS].to_frame().T)[0, 1])
    return state, p, int(last["k"])


# ----------------------------------------------------------------------------
# объёмный профиль + магниты
# ----------------------------------------------------------------------------
def volume_profile(df: pd.DataFrame, bins: int = 80, va_frac: float = 0.70):
    """POC / VAH / VAL по hlc3-объёму. Возврат (poc, vah, val) или None."""
    if df is None or df.empty or "volume" not in df:
        return None
    price = (df["high"] + df["low"] + df["close"]) / 3
    lo, hi = price.min(), price.max()
    if not np.isfinite(lo) or hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    idx = np.clip(np.digitize(price, edges) - 1, 0, bins - 1)
    vol = np.zeros(bins)
    for i, v in zip(idx, df["volume"].values):
        vol[i] += v
    if vol.sum() <= 0:
        return None
    centers = (edges[:-1] + edges[1:]) / 2
    poc_i = int(vol.argmax()); poc = centers[poc_i]
    order = np.argsort(vol)[::-1]
    target = vol.sum() * va_frac
    acc, sel = 0.0, []
    for i in order:
        acc += vol[i]; sel.append(i)
        if acc >= target:
            break
    va = centers[sel]
    return float(poc), float(va.max()), float(va.min())


def swing_levels(df: pd.DataFrame, n: int = 2, lookback: int = 120):
    """Фрактальные swing-high (BSL) и swing-low (SSL). Возврат (highs, lows)."""
    if df is None or len(df) < 2 * n + 1:
        return [], []
    g = df.tail(lookback)
    H = g["high"].values; L = g["low"].values
    highs, lows = [], []
    for i in range(n, len(g) - n):
        if H[i] == max(H[i - n:i + n + 1]):
            highs.append(float(H[i]))
        if L[i] == min(L[i - n:i + n + 1]):
            lows.append(float(L[i]))
    return highs, lows


# ----------------------------------------------------------------------------
# формат
# ----------------------------------------------------------------------------
def _f(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") if x >= 100 else f"{x:,.2f}"


def _pct(a: float, b: float) -> str:
    return f"{(a / b - 1) * 100:+.1f}%"


STATE_RU = {"TREND_UP": "🟢 растущий", "TREND_DOWN": "🔴 падающий",
            "ROTATION": "⚪ боковик", "FORMING": "⚫ день не определился"}


def verdict(direction: str, state: str, include_stats: bool = True,
            validated: bool | None = None) -> tuple[str, str]:
    """(строка-вердикт, подсказка размера) по ячейке направление × тип дня.

    validated=True — полный вердикт с WR-цифрами и «сильнейший/слабейший»
    (валидировано ТОЛЬКО на 1.1.1 BTC: etap_232/249). validated=False — нейтральное
    описание связи день↔направление БЕЗ цифр и суперлативов (ETH/SOL — перенос НЕ
    подтверждён, etap_250; и стратегии 1.1.2/3/6). По умолчанию = include_stats
    (обратная совместимость).
    """
    if validated is None:
        validated = include_stats
    counter = (direction == "SHORT" and state == "TREND_UP") or \
              (direction == "LONG" and state == "TREND_DOWN")
    cont = (direction == "LONG" and state == "TREND_UP") or \
           (direction == "SHORT" and state == "TREND_DOWN")
    if counter:
        zone = "сопротивление" if direction == "SHORT" else "опору"
        push = "растущий день гонит цену в твоё" if direction == "SHORT" \
            else "падающий день льёт цену в твою"
        if validated:
            stat = CELL_STATS.get((direction, state), "")
            suff = f" (ист.: {stat})" if stat else ""
            return (f"🔥 CONFLUENCE: {push} {zone} — фейд в зону, сильнейший вход{suff}.",
                    "размер ↑ повышенный")
        return (f"↩️ встречный день: {push} {zone} — фейд в зону.", "размер обычный")
    if cont:
        if validated:
            return ("⚠️ вход ПО тренду дня — слабейший случай для 1.1.1.",
                    "размер ↓ минимальный / пропуск")
        return ("↪️ вход по направлению тренда дня.", "размер обычный")
    if state == "ROTATION":
        return ("◽ боковик — рядовой возврат в зону.", "размер обычный")
    return ("◽ день ещё формируется (IB не закрыт) — контекста по тренду пока нет.",
            "размер обычный")


# Композитный грейд качества 1.1.1-сетапа (etap_249, BTC 190 дедуп-сделок, fixed RR=2.2).
# net = сильные − слабые маркеры; порог net≥0 год-стабилен 7/7: хор ~60% WR / слаб ~30%.
# Границы risk_pct — терцили из etap_249. Валидировано ТОЛЬКО для 1.1.1.
RISK_P33, RISK_P67 = 0.341, 0.641

# Правило размера по грейду (etap_257, TIERED): net≥1→×1.0, net=0→×0.75, net=-1→×0.5,
# net≤-2→пропуск/мин. Денежный смысл = просадка падает 13.6R→3.0R (in-sample upper),
# плюс 7/7 лет, не «больше R». GRADE_SKIP_WORST: True→net≤-2 = пропуск (×0.0),
# False→мин. размер (×0.25). По умолчанию мягкий режим (не теряем сигнал полностью).
GRADE_SKIP_WORST = False


def signal_grade(direction: str, state: str, risk_pct: float | None,
                 fvg_tf: str | None, hour: int | None, gauge: float | None) -> dict:
    """Грейд качества сетапа по надёжно-стабильным классам etap_249.

    Возврат: dict(net, label, wr, strong[], weak[], size). net≥0 → ист. ~60% WR
    (+0.93R/сделку), net<0 → ~30% (≈безубыток при RR2.2). Стабилен по всем 7 годам."""
    weak: list[str] = []
    strong: list[str] = []
    if risk_pct is not None:
        if risk_pct >= RISK_P67:
            weak.append("широкий стоп")
        elif risk_pct <= RISK_P33:
            strong.append("узкий стоп")
    if gauge is not None and gauge >= 1.0:
        weak.append("вход вдогонку (дн. ход выбран)")
    if fvg_tf == "20m":
        weak.append("вход по 20m-FVG")
    if hour is not None:
        if hour < 7:
            strong.append("Asia-сессия")
        elif hour < 21:
            weak.append("London/NY-сессия")
    if state == "ROTATION":
        weak.append("боковик-день")
    if (direction == "SHORT" and state == "TREND_UP") or (direction == "LONG" and state == "TREND_DOWN"):
        strong.append("фейд в зону (день против)")
    net = len(strong) - len(weak)
    if net >= 1:
        label, wr, mult = "ВЫСОКОЕ", "~60-65%", 1.0
        size = "полный размер (×1.0)"
    elif net == 0:
        label, wr, mult = "ХОРОШЕЕ", "~56%", 0.75
        size = "размер ×0.75"
    elif net == -1:
        label, wr, mult = "НИЖЕ СРЕДНЕГО", "~31%", 0.5
        size = "половина размера (×0.5)"
    else:
        mult = 0.0 if GRADE_SKIP_WORST else 0.25
        label, wr = "НИЗКОЕ", "~25%"
        size = "ПРОПУСК (≈безубыток)" if GRADE_SKIP_WORST else "мин. размер (×0.25)"
    return dict(net=net, label=label, wr=wr, strong=strong, weak=weak,
                size=size, size_mult=mult)


def build_context(symbol: str, sig: dict, rr: float = 2.2,
                  include_stats: bool = True) -> str:
    """Главная функция: human-блок контекста к сигналу. Ошибка → ''."""
    try:
        direction = sig["direction"]
        entry = float(sig["entry"]); sl = float(sig["sl"])
        risk = abs(entry - sl)
        tp = entry + risk * rr if direction == "LONG" else entry - risk * rr
        sig_t = pd.Timestamp(sig["signal_time"])
        if sig_t.tz is None:
            sig_t = sig_t.tz_localize("UTC")

        state, p_up, k = day_state(symbol, sig_t)
        # цифры ячеек и грейд валидированы ТОЛЬКО на 1.1.1 BTC (etap_232/249/250).
        # Для ETH/SOL и стратегий 1.1.2/3/6 — нейтральный вердикт без WR-claims.
        validated = include_stats and str(symbol).upper().replace("USDT", "") == "BTC"
        vline, size = verdict(direction, state, validated=validated)

        L: list[str] = ["", "📊 <b>Контекст рынка</b> (авто)"]
        L.append(f"Тип дня: {STATE_RU.get(state, state)} · шанс роста {p_up:.0%} · час {k}")
        # устойчивость состояния (etap_234: калибровка OOS pred≈факт)
        hp = trend_hold_p(state, k)
        if hp is not None:
            if state == "ROTATION":
                L.append(f"Устойчивость: боковик доживает до конца дня в {hp:.0%} случаев "
                         f"(в {1 - hp:.0%} — перейдёт в тренд)")
            else:
                L.append(f"Устойчивость: такой тренд к этому часу доживает до конца дня в {hp:.0%} случаев")
        L.append(vline)
        L.append(f"→ {size}")

        # данные 1h (для gauge и магнитов)
        df1h = load_df(symbol, "1h")
        if not df1h.empty and df1h.index.tz is None:
            df1h.index = df1h.index.tz_localize("UTC")

        # разворотная структура дня/недели (etap_255) — ОПИСАТЕЛЬНО (не прогноз направления)
        if _RV is not None and not df1h.empty:
            try:
                day_b = df1h[(df1h.index.normalize() == sig_t.normalize()) & (df1h.index <= sig_t)]
                dr = _RV.classify_day(day_b, developing=True)
                txt = _RV.describe_intraday(dr)
                if txt:
                    L.append(txt)
                d1 = df1h[df1h.index <= sig_t].resample("1D").agg(
                    {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
                wtxt = _RV.describe_weekly(_RV.weekly_structure(d1))
                if wtxt:
                    L.append(wtxt)
            except Exception:
                pass

        # gauge: сколько обычного дневного хода уже пройдено к входу (для грейда)
        gauge = None
        if not df1h.empty:
            day_b = df1h[(df1h.index.normalize() == sig_t.normalize()) & (df1h.index <= sig_t)]
            if len(day_b):
                daily = df1h.resample("1D").agg({"open": "first", "high": "max", "low": "min"})
                exp = ((daily.high - daily.low) / daily.open).rolling(20).median().shift(1) \
                    .reindex([sig_t.normalize()]).iloc[0]
                rng_sf = (day_b["high"].max() - day_b["low"].min()) / day_b["open"].iloc[0]
                if exp and exp > 0:
                    gauge = float(rng_sf / exp)

        # ГРЕЙД КАЧЕСТВА СЕТАПА (etap_249) — только 1.1.1 BTC (перенос на ETH/SOL
        # НЕ подтверждён, etap_250: разрыв 3пп / работает 3-4 года из 7).
        if validated:
            gr = signal_grade(direction, state, risk / entry * 100,
                              sig.get("fvg_tf"), sig_t.hour, gauge)
            L.append(f"🎚 Качество сетапа: <b>{gr['label']}</b> (балл {gr['net']:+d}) · ист. {gr['wr']} WR")
            if gr["strong"]:
                L.append("   ✅ в плюс: " + " · ".join(gr["strong"]))
            if gr["weak"]:
                L.append("   ⛔ в минус: " + " · ".join(gr["weak"]))
            L.append(f"   → размер по грейду: <b>{gr['size']}</b>")

        # зоны из сигнала
        poi = sig.get("intersection_zone")
        if poi:
            L.append(f"Зона входа (POI): {_f(min(poi))} – {_f(max(poi))}")
        L.append(f"Вход {_f(entry)} · стоп {_f(sl)} · цель {_f(tp)} "
                 f"(риск {risk / entry * 100:.2f}%, RR {rr})")

        # магниты
        if not df1h.empty:
            recent = df1h[df1h.index >= sig_t - pd.Timedelta(days=45)]
            mags: list[str] = []
            vp = volume_profile(recent)
            if vp:
                poc, vah, val = vp
                mags.append(f"POC {_f(poc)} ({_pct(poc, entry)})")
                near_va = vah if direction == "LONG" else val
                lab = "VAH" if direction == "LONG" else "VAL"
                mags.append(f"{lab} {_f(near_va)} ({_pct(near_va, entry)})")
            df4h = load_df(symbol, "4h")
            if not df4h.empty:
                highs, lows = swing_levels(df4h)
                above = sorted(h for h in highs if h > entry)
                below = sorted((l for l in lows if l < entry), reverse=True)
                if direction == "LONG" and above:
                    mags.append(f"ликвидность сверху (BSL) {_f(above[0])} ({_pct(above[0], entry)})")
                if direction == "SHORT" and below:
                    mags.append(f"ликвидность снизу (SSL) {_f(below[0])} ({_pct(below[0], entry)})")
            # IB сегодня
            day_bars = df1h[df1h.index.normalize() == sig_t.normalize()]
            if len(day_bars) >= IB:
                ibh = day_bars["high"].iloc[:IB].max(); ibl = day_bars["low"].iloc[:IB].min()
                mags.append(f"утр. коридор (IB) {_f(ibl)}–{_f(ibh)}")
            if mags:
                L.append("🧲 Магниты: " + " · ".join(mags))

        return "\n".join(L)
    except Exception:
        return ""
