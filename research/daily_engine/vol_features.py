"""vol_features — переиспользуемые HAR-RV дневные фичи (волна 1, etap_243, KEEP).

Лифт валидирован: range R² +0.013 (null p=0.000), big_day AUC +0.008; адверс-проверка
пройдена (лукахеда нет, лифт оба года, все 3 монеты). Высшие моменты (jump/semivar/skew)
слабые, но оставлены — CatBoost регуляризует, дублей feat_cols это не создаёт.

Все фичи as-of t-1 (HAR-окна кончаются на d-1) — НЕТ подглядывания.
Кэш realized-мер (etap_243_rv_measures.csv) инкрементально дополняется свежими
днями из 1m-хвоста, чтобы не читать весь 1m-файл при каждом вызове.

API:
  har_features(sym) -> DataFrame[date] с колонками VOL_FEATS (as-of t-1)
  augment(f, sym)   -> добавляет VOL_FEATS в фича-df f (по индексу-дате); при
                       любой ошибке возвращает f БЕЗ изменений (симметрично для
                       train и predict → feat_cols не рассинхронизируется).
"""
from __future__ import annotations
import time
from pathlib import Path
import numpy as np, pandas as pd
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = HERE / "output" / "etap_243_rv_measures.csv"
MIN_COVER = 1380
VOL_FEATS = ["har_rv_d", "har_rv_w", "har_rv_m", "rv_volvol",
             "jump_d", "jump_w", "rsasym_d", "rsasym_w", "rskew_d", "rkurt_d"]
_HAR_CACHE: dict[str, pd.DataFrame] = {}

# DVOL (Deribit forward-IV, волна 2 etap_247, KEEP): range R² +0.021, big_day AUC +0.014.
# Только BTC/ETH (SOL DVOL не существует). Оговорка: R²-лифт концентрирован в 2025,
# 2026 пока плоско — не переоценивать вес, мониторить.
DVOL_FEATS = ["dvol_lvl", "dvol_z30", "dvol_chg5"]
DVOL_CUR = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
_DVOL_CACHE: dict[str, pd.DataFrame] = {}


def _fetch_recent_1m(sym: str, since: pd.Timestamp) -> pd.DataFrame:
    """Дофетч свежих ЗАКРЫТЫХ 1m-баров с Binance (только разрыв since..вчера).

    Системный прокси по умолчанию (pitfall socks-proxy-блокирует-binance-rest:
    NO_PROXY не трогаем). Сеть упала → пусто (graceful, HAR на сегодня = нули)."""
    end = int(pd.Timestamp.now(tz="UTC").normalize().timestamp() * 1000)  # до начала сегодня
    cur = int(since.timestamp() * 1000)
    rows = []
    try:
        while cur < end:
            r = requests.get("https://api.binance.com/api/v3/klines",
                             params=dict(symbol=sym, interval="1m", startTime=cur, limit=1000), timeout=15)
            d = r.json()
            if not isinstance(d, list) or not d:
                break
            rows += d
            cur = d[-1][0] + 60_000
            if len(d) < 1000:
                break
    except Exception:
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "close", "v", "ct", "qv", "n", "tb", "tq", "ig"])
    df["open_time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df["close"] = pd.to_numeric(df["close"])
    return df.set_index("open_time")[["close"]]


def _measures_from_1m(sym: str, since: pd.Timestamp | None = None) -> pd.DataFrame:
    """Дневные realized-меры из 1m (на дату дня, БЕЗ лагов). since → только дни >= since."""
    p = ROOT / "data" / f"{sym}_1m.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, usecols=["open_time", "close"], parse_dates=["open_time"])
    if df["open_time"].dt.tz is None:
        df["open_time"] = df["open_time"].dt.tz_localize("UTC")
    df = df.set_index("open_time").sort_index()
    if since is not None:
        df = df[df.index >= since - pd.Timedelta(days=1)]
    # дофетч свежих баров, если локальный CSV отстал от вчера (для живого HAR)
    local_last = df.index.max() if len(df) else (since or pd.Timestamp("2020-01-01", tz="UTC"))
    yest = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)
    if local_last < yest:
        extra = _fetch_recent_1m(sym, local_last + pd.Timedelta(minutes=1))
        if len(extra):
            df = pd.concat([df, extra[extra.index > local_last]])
    r = np.log(df["close"]).diff()
    g = pd.DataFrame({"r": r}).dropna()
    g["day"] = g.index.normalize()
    rows = []
    for day, x in g.groupby("day"):
        rr = x["r"].values; n = len(rr)
        if n < MIN_COVER:
            continue
        rv = float(np.sum(rr**2))
        if rv <= 0:
            continue
        bv = (np.pi / 2.0) * float(np.sum(np.abs(rr[1:]) * np.abs(rr[:-1])))
        rs_plus = float(np.sum(rr[rr > 0] ** 2)); rs_minus = float(np.sum(rr[rr < 0] ** 2))
        rows.append(dict(day=day, asset=sym, rv=rv, jump_frac=max(rv - bv, 0.0) / rv,
                         rs_asym=(rs_minus - rs_plus) / rv,
                         rskew=float(np.sqrt(n) * np.sum(rr**3) / (rv ** 1.5)),
                         rkurt=float(n * np.sum(rr**4) / (rv ** 2))))
    return pd.DataFrame(rows)


def _load_measures(sym: str) -> pd.DataFrame:
    """Кэш + инкрементальное дополнение свежих дней из 1m-хвоста."""
    cached = pd.DataFrame()
    if CACHE.exists():
        c = pd.read_csv(CACHE, parse_dates=["day"])
        if c["day"].dt.tz is None:
            c["day"] = c["day"].dt.tz_localize("UTC")
        cached = c[c["asset"] == sym].copy()
    today = pd.Timestamp.now(tz="UTC").normalize()
    last = cached["day"].max() if len(cached) else None
    if last is None or last < today - pd.Timedelta(days=1):
        fresh = _measures_from_1m(sym, since=(last + pd.Timedelta(days=1)) if last is not None else None)
        if len(fresh):
            cached = pd.concat([cached, fresh], ignore_index=True)
            cached = cached.drop_duplicates(subset=["day", "asset"], keep="last").sort_values("day")
            # перезаписываем общий кэш (все активы): читаем существующий, заменяем срез sym
            try:
                allc = pd.read_csv(CACHE, parse_dates=["day"]) if CACHE.exists() else pd.DataFrame()
                if len(allc):
                    if allc["day"].dt.tz is None:
                        allc["day"] = allc["day"].dt.tz_localize("UTC")
                    allc = allc[allc["asset"] != sym]
                out = pd.concat([allc, cached], ignore_index=True).sort_values(["asset", "day"])
                CACHE.parent.mkdir(exist_ok=True)
                out.to_csv(CACHE, index=False)
            except Exception:
                pass
    return cached.sort_values("day")


def har_features(sym: str) -> pd.DataFrame:
    """HAR-лаги (день/неделя/месяц + jump/semivar/skew), все as-of t-1. Индекс = date (UTC)."""
    if sym in _HAR_CACHE:
        return _HAR_CACHE[sym]
    x = _load_measures(sym)
    if len(x) < 25:
        _HAR_CACHE[sym] = pd.DataFrame()
        return _HAR_CACHE[sym]
    x = x.sort_values("day").drop_duplicates("day").set_index("day")
    # продлеваем индекс до СЕГОДНЯ непрерывным днём: shift(1) положит вчерашнюю
    # меру на сегодняшнюю строку прогноза (иначе для today HAR был бы NaN).
    today = pd.Timestamp.now(tz="UTC").normalize()
    full = pd.date_range(x.index.min(), max(x.index.max(), today), freq="D", tz="UTC")
    x = x.reindex(full)
    lrv = np.log(x["rv"].clip(lower=1e-12))
    x["har_rv_d"] = lrv.shift(1)
    x["har_rv_w"] = lrv.rolling(5).mean().shift(1)
    x["har_rv_m"] = lrv.rolling(22).mean().shift(1)
    x["rv_volvol"] = lrv.rolling(10).std().shift(1)
    x["jump_d"] = x["jump_frac"].shift(1)
    x["jump_w"] = x["jump_frac"].rolling(5).mean().shift(1)
    x["rsasym_d"] = x["rs_asym"].shift(1)
    x["rsasym_w"] = x["rs_asym"].rolling(5).mean().shift(1)
    x["rskew_d"] = x["rskew"].shift(1)
    x["rkurt_d"] = x["rkurt"].shift(1)
    out = x[VOL_FEATS]
    _HAR_CACHE[sym] = out
    return out


# квинтильные границы eff_ratio (etap_245 OOS): Q1<=0.011 rough 60% .. Q5>=0.062 rough 11%
EFF_Q = [0.011, 0.024, 0.039, 0.062]


def morning_eff_ratio(sym: str) -> float | None:
    """Kaufman efficiency ratio утра (часы 0..min(now,12)) по СЕГОДНЯШНИМ 1m.

    Низкий ER (<~0.02) = рваное утро → день чаще рваный (etap_245, AUC 0.735).
    Фетчит только сегодняшние 1m (<=720 баров). Сеть упала → None."""
    try:
        day0 = pd.Timestamp.now(tz="UTC").normalize()
        end = int((day0 + pd.Timedelta(hours=12)).timestamp() * 1000)
        cur = int(day0.timestamp() * 1000)
        rows = []
        while cur < end:
            r_ = requests.get("https://api.binance.com/api/v3/klines",
                              params=dict(symbol=sym, interval="1m", startTime=cur, limit=1000), timeout=15)
            dd = r_.json()
            if not isinstance(dd, list) or not dd:
                break
            rows += dd; cur = dd[-1][0] + 60_000
            if len(dd) < 1000:
                break
        if len(rows) < 60:
            return None
        closes = pd.to_numeric(pd.DataFrame(rows)[4])
        r = np.log(closes).diff().dropna().values
        path = float(np.sum(np.abs(r)))
        return float(abs(np.sum(r)) / path) if path > 0 else None
    except Exception:
        return None


def eff_bucket(eff: float) -> str:
    """Категория рваности по квинтилям etap_245."""
    if eff <= EFF_Q[0]:
        return "очень рваное"
    if eff <= EFF_Q[1]:
        return "рваное"
    if eff <= EFF_Q[2]:
        return "среднее"
    if eff <= EFF_Q[3]:
        return "гладкое"
    return "очень гладкое"


def augment(f: pd.DataFrame, sym: str) -> pd.DataFrame:
    """Добавить VOL_FEATS в f (индекс f = даты, UTC). Ошибка → f без изменений.

    Симметрично вызывается в train и predict → feat_cols не рассинхронизируется:
    либо обе стороны получают HAR, либо ни одна."""
    try:
        h = har_features(sym)
        if h.empty:
            return f
        idx = f.index
        if getattr(idx, "tz", None) is None:
            idx = pd.DatetimeIndex(idx).tz_localize("UTC")
        add = h.reindex(idx)
        for col in VOL_FEATS:
            f[col] = add[col].values
        return f
    except Exception:
        return f


# ---------------------------------------------------------------------------
# DVOL (Deribit forward-IV)
# ---------------------------------------------------------------------------
def _fetch_dvol(cur: str, since_ms: int) -> list:
    """Дневной DVOL OHLC с Deribit, пагинация ВПЕРЁД окнами <1000 баров.

    pitfall: широкое окно → Deribit отдаёт только ПОСЛЕДНИЕ 1000. Системный прокси."""
    end = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    win = 900 * 86400 * 1000
    rows, seen, cur_ts = [], set(), since_ms
    try:
        while cur_ts < end:
            j = requests.get("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                             params=dict(currency=cur, start_timestamp=cur_ts,
                                         end_timestamp=min(cur_ts + win, end), resolution=86400),
                             timeout=20).json()
            data = [d for d in j.get("result", {}).get("data", []) if d[0] not in seen]
            if not data:
                cur_ts += win; continue
            rows += data; seen.update(d[0] for d in data)
            cur_ts = max(d[0] for d in data) + 86400 * 1000
    except Exception:
        return rows
    return rows


def dvol_daily(cur: str) -> pd.DataFrame:
    """DVOL-фичи (dvol_lvl/z30/chg5), all as-of t-1. Индекс продлён до сегодня.

    Кэш общий с etap_247; инкрементально дофетчит свежие дни."""
    if cur in _DVOL_CACHE:
        return _DVOL_CACHE[cur]
    cache = HERE / "output" / f"etap_247_dvol_{cur}.csv"
    df = pd.DataFrame()
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        if df["date"].dt.tz is None:
            df["date"] = df["date"].dt.tz_localize("UTC")
    today = pd.Timestamp.now(tz="UTC").normalize()
    last = df["date"].max() if len(df) else None
    if last is None or last < today:
        since = int(((last + pd.Timedelta(days=1)) if last is not None
                     else pd.Timestamp("2021-03-24", tz="UTC")).timestamp() * 1000)
        rows = _fetch_dvol(cur, since)
        if rows:
            fresh = pd.DataFrame(rows, columns=["t", "o", "h", "l", "dvol"])
            fresh["date"] = pd.to_datetime(fresh["t"], unit="ms", utc=True)
            df = pd.concat([df, fresh[["date", "dvol"]]], ignore_index=True)
            df = df.drop_duplicates("date").sort_values("date")
            try:
                cache.parent.mkdir(exist_ok=True); df.to_csv(cache, index=False)
            except Exception:
                pass
    if len(df) < 35:
        _DVOL_CACHE[cur] = pd.DataFrame(); return _DVOL_CACHE[cur]
    s = df.set_index("date")["dvol"].sort_index()
    full = pd.date_range(s.index.min(), max(s.index.max(), today), freq="D", tz="UTC")
    s = s.reindex(full)
    out = pd.DataFrame(index=full)
    out["dvol_lvl"] = s.shift(1)
    out["dvol_z30"] = ((s - s.rolling(30).mean()) / s.rolling(30).std()).shift(1)
    out["dvol_chg5"] = s.pct_change(5).shift(1)
    _DVOL_CACHE[cur] = out[DVOL_FEATS]
    return _DVOL_CACHE[cur]


def augment_dvol(f: pd.DataFrame, sym: str) -> pd.DataFrame:
    """Добавить DVOL_FEATS в f. ВСЕГДА добавляет 3 колонки (real для BTC/ETH, NaN иначе/ошибка)
    → feat_cols симметричен train/predict; SOL и сбои не ломают (CatBoost обрабатывает NaN)."""
    try:
        cur = DVOL_CUR.get(sym)
        if cur is not None:
            dv = dvol_daily(cur)
            if not dv.empty:
                idx = f.index
                if getattr(idx, "tz", None) is None:
                    idx = pd.DatetimeIndex(idx).tz_localize("UTC")
                add = dv.reindex(idx)
                for col in DVOL_FEATS:
                    f[col] = add[col].values
                return f
    except Exception:
        pass
    for col in DVOL_FEATS:          # SOL / нет данных / ошибка → NaN-колонки (симметрия)
        if col not in f.columns:
            f[col] = np.nan
    return f
