"""etap_237 — Gauge 2.0 (product-1 из v2.0): «сколько хода пройдено» от range-МОДЕЛИ.

Заменяет знаменатель vol-gauge: вместо rolling(20).median дневного диапазона —
прогноз пулированной CatBoost range-модели (etap_201: OOS R² 0.50, драйверы
atr_pct+dow; vol-нормировка = лучший lift v1, etap_218). Фичи as-of вчера
(shift(1) внутри train_models) — прогноз на СЕГОДНЯ без подглядывания.

Самодостаточность live: flow-CSV ({SYM}_1h_flow.csv — нужны build_features)
обновляются инкрементально с Binance (klines несут taker_buy/quote_volume).
Stale-защита: если последний ПОЛНЫЙ день в flow-CSV < вчера → None →
вызывающий код падает на rolling-медиану (старый gauge).

Запуск (тест): venv/Scripts/python.exe research/daily_engine/etap_237_gauge2.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np, pandas as pd
import requests

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
FLOW = HERE.parent / "elements_study" / "data"

_MODELS = None          # (reg, clf, feat_cols, cat_idx, calib)
_EXP_CACHE: dict = {}   # (sym, day) -> float

COLS = ["open_time", "open", "high", "low", "close", "volume", "quote_volume",
        "trades", "taker_buy_base", "taker_buy_quote", "delta", "cvd", "taker_buy_ratio"]


def refresh_flow(sym: str) -> int:
    """Инкрементально дописывает {sym}_1h_flow.csv с Binance. Возвращает n новых строк."""
    p = FLOW / f"{sym}_1h_flow.csv"
    df = pd.read_csv(p, parse_dates=["open_time"])
    last = df["open_time"].max()
    start = int((last + pd.Timedelta(hours=1)).timestamp() * 1000)
    rows = []
    cur = start
    end = int(time.time() * 1000)
    while cur < end:
        d = requests.get("https://api.binance.com/api/v3/klines",
                         params=dict(symbol=sym, interval="1h", startTime=cur, limit=1000),
                         timeout=20).json()
        if not isinstance(d, list) or not d:
            break
        rows += d
        cur = d[-1][0] + 3600_000
        if len(d) < 1000:
            break
    if not rows:
        return 0
    new = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume",
                                      "ct", "quote_volume", "trades", "taker_buy_base",
                                      "taker_buy_quote", "ig"])
    new["open_time"] = pd.to_datetime(new["t"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_base", "taker_buy_quote"]:
        new[c] = pd.to_numeric(new[c])
    new["trades"] = pd.to_numeric(new["trades"], downcast="integer")
    # только ЗАКРЫТЫЕ часы (последняя свеча может быть текущей незакрытой)
    now_floor = pd.Timestamp.now(tz="UTC").floor("h")
    new = new[new["open_time"] < now_floor]
    new = new[new["open_time"] > last]
    if new.empty:
        return 0
    new["delta"] = 2 * new["taker_buy_base"] - new["volume"]
    last_cvd = float(df["cvd"].iloc[-1]) if "cvd" in df else 0.0
    new["cvd"] = last_cvd + new["delta"].cumsum()
    new["taker_buy_ratio"] = (new["taker_buy_base"] / new["volume"]).where(new["volume"] > 0)
    out = pd.concat([df, new[COLS]], ignore_index=True)
    out.to_csv(p, index=False)
    return len(new)


def _models():
    global _MODELS
    if _MODELS is None:
        import etap_201_daily_analyzer as A
        # train на ВСЕЙ закрытой истории до сегодня; фичи внутри shift(1) → честно.
        # ВАЖНО: train_models сравнивает с tz-aware датами (как CUTOFF в etap_218).
        _MODELS = A.train_models(pd.Timestamp.now(tz="UTC").normalize())
    return _MODELS


def exp_range_pct(sym: str) -> float | None:
    """Ожидаемый (H-L)/prev_close на СЕГОДНЯ для символа. None → бери fallback."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    key = (sym, str(today.date()))
    if key in _EXP_CACHE:
        return _EXP_CACHE[key]
    try:
        import etap_201_daily_analyzer as A
        # stale-защита по ПОСЛЕДНЕМУ ЧАСУ: вчерашний день полный, только если
        # в CSV есть хотя бы один закрытый час СЕГОДНЯ (resample режет день
        # частично и по дневному индексу неполноту не видно).
        tail = pd.read_csv(FLOW / f"{sym}_1h_flow.csv", usecols=["open_time"]).iloc[-1, 0]
        if pd.Timestamp(tail).tz_localize(None) < today.tz_localize(None):
            return None
        d = A.daily_from_flow(sym)
        reg, clf, feat_cols, cat_idx, calib = _models()
        f = A.build_features(d).shift(1)
        f["gap"] = (d["open"] - d["close"].shift(1)) / A.atr(d, 14)
        import vol_features as VF
        f = VF.augment(f, sym)         # HAR-RV: должно совпадать с feat_cols из A.train_models
        f = VF.augment_dvol(f, sym)    # DVOL forward-IV (симметрично с A.train_models)
        f["asset"] = sym
        # строка на сегодня: фичи = вчерашние величины
        row = f.reindex(columns=feat_cols).iloc[[-1]]
        if row.drop(columns=["asset"]).isna().all(axis=None):
            return None
        row = row.fillna(0.0)
        pr = float(np.exp(reg.predict(row)[0]))
        pb = float(clf.predict_proba(row)[0, 1])
        ratio = calib["r_big"] if pb >= 0.5 else calib["r_flat"]
        val = pr * ratio
        _EXP_CACHE[key] = val
        return val
    except Exception:
        return None


def main():
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        n = refresh_flow(sym)
        print(f"{sym}: flow +{n} строк", end="  ")
        e = exp_range_pct(sym)
        # сравнение со старым знаменателем (rolling-медиана)
        import etap_201_daily_analyzer as A
        d = A.daily_from_flow(sym)
        old = float(((d.high - d.low) / d.open).rolling(20).median().iloc[-1])
        print(f"exp_model={e if e is None else round(e*100,2)}%  rolling20={old*100:.2f}%")


if __name__ == "__main__":
    main()
