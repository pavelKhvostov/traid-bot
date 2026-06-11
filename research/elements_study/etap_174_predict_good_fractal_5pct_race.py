"""etap_174: Предсказать «хороший» фрактал-разворот на close свечи (5% race).

ЗАДАЧА (постановка пользователя):
  На close КАЖДОЙ 12h-свечи i (СТРОГО до того, как она стала фракталом —
  N=2 подтверждается только через 2 бара) предсказать: станет ли эта свеча
  «хорошим» фракталом-разворотом.

ОПРЕДЕЛЕНИЕ «ХОРОШЕГО» ФРАКТАЛА (гонка двух событий):
  LOW-фрактал (разворот вверх / LONG):
    ХОРОШИЙ  = high достиг close[i] * 1.05  РАНЬШЕ, чем low ушёл < low[i].
    ПЛОХОЙ   = low[i] снят (low < low[i])   РАНЬШЕ, чем достигнут +5%.
  HIGH-фрактал (разворот вниз / SHORT):
    ХОРОШИЙ  = low достиг close[i] * 0.95   РАНЬШЕ, чем high ушёл > high[i].
    ПЛОХОЙ   = high[i] снят (high > high[i]) РАНЬШЕ, чем достигнут -5%.
  Гонка считается по ВНУТРИБАРНЫМ 1h high/low (точность внутри 12h-бара),
  начиная с close_time[i] (момент, когда сигнал реально известен).
  Если ни одно событие не наступило за MAX_RACE_BARS_1H — метка = плохой
  (не дождались реакции = бесполезный сигнал).

ЗАЩИТА ОТ LOOKAHEAD (known-pitfalls.md — проговорено в чате):
  1. [htf-lookup-must-use-last-closed-bar] HTF-фичи (1d/4h тренд) берут
     ПОСЛЕДНИЙ ЗАКРЫТЫЙ HTF-бар с close_time <= close_time[i]. НЕ asof().
  2. [lookahead-anchor cur_open/cur_close] ВСЕ фичи — только по данным
     с индексом <= i (close[i] известен). Свеча i ещё НЕ фрактал на close.
  3. [lookahead от open() текущей свечи] Гонка 5%-vs-снятие стартует с
     close_time[i], скан 1h с open_time >= close_time[i]. НЕ от open[i].
  4. [instant-fill / WR>60%] Гонка по реальным 1h-high/low, не мгновенно.
     Precision >> 60% на сотнях примеров = ПЕРВЫЙ кандидат на проверку
     lookahead, а не повод радоваться.
  5. [multi-bar confirm vs trigger] Фичи на trigger (close[i]); метка по
     будущему. Никогда не смешиваются.
  6. Train/test split по ВРЕМЕНИ (TRAIN_END), не случайный — иначе утечка
     через serial correlation (Lopez: Purged K-Fold; здесь — простой
     time-split + embargo на границе).

ФИЧИ (только данные <= close[i], направление-агностичные):
  - индикаторы 12h: rsi(14), hull(78) dir, ema(200) dist, atr%, vol_z
  - свеча i: body%, range/atr, верхняя/нижняя тень %, close-in-range
  - momentum: pre-return 3/7/14 баров до close[i]
  - структура: расстояние до 30-bar HH/LL, бары с последнего HH/LL
  - HTF тренд: 1d hull dir, 4h hull dir (last CLOSED bar)
  - "почти-фрактал" признаки на close[i] (БЕЗ i+1,i+2):
      lower_than_prev2: low[i] < min(low[i-1],low[i-2])  (левая часть FL уже есть)
      higher_than_prev2: high[i] > max(high[i-1],high[i-2])

ВЫХОД: CSV с метриками (baseline, precision/recall/AUC по time-split),
       top-фичи (gain importance), и таблица «precision @ probability bins».

Запуск: .venv-pivot/bin/python research/elements_study/etap_174_predict_good_fractal_5pct_race.py
"""
from __future__ import annotations

# --- repo-root injection ---
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
# --- end repo-root injection ---

import numpy as np
import pandas as pd

from data_manager import load_df

# ============================================================
# CONFIG
# ============================================================
SYMBOL = "BTCUSDT"
TF = "12h"                       # таймфрейм фракталов
RACE_TF = "1h"                   # таймфрейм для точной гонки внутри 12h
FRACTAL_N = 2                    # Williams canon (подтверждается через 2 бара)
MOVE_PCT = 0.05                  # 5% реакция
MAX_RACE_DAYS = 30               # макс горизонт гонки (после — метка "плохой")
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
EMBARGO_BARS = FRACTAL_N + 1     # выкинуть бары на границе train/test (anti-leak)

RSI_LEN = 14
HULL_LEN = 78
EMA_LEN = 200
ATR_LEN = 14
VOL_Z_LEN = 20
HULL_HTF_1D = 78
HULL_HTF_4H = 78

OUT_DIR = _ROOT / "research" / "elements_study" / "output"


# ============================================================
# ИНДИКАТОРЫ (как в etap_161, чистые, без lookahead)
# ============================================================
def rsi_wilder(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    ag = gain.ewm(alpha=1 / length, adjust=False).mean()
    al = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _wma(values: np.ndarray, length: int) -> np.ndarray:
    weights = np.arange(1, length + 1, dtype=float)
    out = np.full(len(values), np.nan)
    for i in range(length - 1, len(values)):
        out[i] = np.dot(values[i - length + 1:i + 1], weights) / weights.sum()
    return out


def hull_ma(series: pd.Series, length: int = 78) -> pd.Series:
    half = length // 2
    sqrtl = int(np.sqrt(length))
    raw = 2 * _wma(series.values, half) - _wma(series.values, length)
    return pd.Series(_wma(pd.Series(raw).fillna(0).values, sqrtl), index=series.index)


def ema(series: pd.Series, length: int = 200) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


# ============================================================
# МЕТКА: гонка 5%-vs-снятие по 1h, старт с close_time[i]
# ============================================================
def label_good_fractal(
    direction: str,
    close_i: float,
    extreme_i: float,
    close_time_i: pd.Timestamp,
    df_1h: pd.DataFrame,
    max_race_end: pd.Timestamp,
) -> int | None:
    """Вернуть 1 (хороший), 0 (плохой), или None (нет данных для гонки).

    [pitfall: lookahead от open()] скан 1h строго с open_time >= close_time[i].
    [pitfall: instant-fill] идём бар за баром по реальным high/low.

    direction == "low": хороший если high >= close_i*1.05 РАНЬШЕ low < extreme_i.
    direction == "high": хороший если low <= close_i*0.95 РАНЬШЕ high > extreme_i.
    """
    fwd = df_1h[(df_1h.index >= close_time_i) & (df_1h.index < max_race_end)]
    if fwd.empty:
        return None

    if direction == "low":
        target = close_i * (1.0 + MOVE_PCT)        # +5% вверх
        for _, c in fwd.iterrows():
            hit_target = c["high"] >= target
            hit_stop = c["low"] < extreme_i        # сняли low фрактала
            # Консервативно при одновременном касании в одном баре:
            # считаем СТОП сработавшим раньше (худший случай, anti-optimism).
            if hit_stop:
                return 0
            if hit_target:
                return 1
        return 0  # не дождались реакции за горизонт = бесполезно = плохой
    else:  # "high"
        target = close_i * (1.0 - MOVE_PCT)        # -5% вниз
        for _, c in fwd.iterrows():
            hit_target = c["low"] <= target
            hit_stop = c["high"] > extreme_i       # сняли high фрактала
            if hit_stop:
                return 0
            if hit_target:
                return 1
        return 0


# ============================================================
# СБОР ДАТАСЕТА
# ============================================================
def htf_dir_last_closed(close_time_i: pd.Timestamp, hull_htf: pd.Series,
                        close_htf: pd.Series) -> int:
    """[pitfall: htf-lookup last closed] Тренд HTF по ПОСЛЕДНЕМУ ЗАКРЫТОМУ бару.

    close_time_i — момент, когда мы стоим (close 12h-свечи).
    Берём HTF-бар, чей индекс (=open_time) таков, что бар УЖЕ закрылся к
    close_time_i. close_time HTF-бара = open_time + tf; используем сам факт,
    что hull_htf/close_htf проиндексированы по open_time → ищем последний
    бар с close_time <= close_time_i, т.е. open_time + tf_htf <= close_time_i.
    Возвращает +1 (up), -1 (down), 0 (na).
    """
    # индекс последнего HTF-бара, который ЗАКРЫЛСЯ к моменту close_time_i
    idx = close_htf.index.searchsorted(close_time_i, side="right") - 1
    # бар idx открыт в close_htf.index[idx]; он закрыт, только если его
    # close_time (open + tf) <= close_time_i. searchsorted по open_time даёт
    # бар, который МОГ ещё формироваться — сдвигаемся на 1 назад для гарантии.
    if idx < 2:
        return 0
    # гарантия закрытости: предыдущий бар точно закрыт
    idx_closed = idx - 1
    if idx_closed < 1:
        return 0
    c = close_htf.iloc[idx_closed]
    h = hull_htf.iloc[idx_closed]
    if np.isnan(c) or np.isnan(h):
        return 0
    return 1 if c > h else -1


def build_dataset() -> pd.DataFrame:
    df = load_df(SYMBOL, TF).sort_index()
    df_1h = load_df(SYMBOL, RACE_TF).sort_index()
    df_1d = load_df(SYMBOL, "1d").sort_index()
    df_4h = load_df(SYMBOL, "4h").sort_index()

    tf_ms = pd.Timedelta(TF)
    max_race = pd.Timedelta(days=MAX_RACE_DAYS)

    # индикаторы 12h (по close, без lookahead — каждое значение зависит ≤ i)
    df["rsi"] = rsi_wilder(df["close"], RSI_LEN)
    df["hull"] = hull_ma(df["close"], HULL_LEN)
    df["ema"] = ema(df["close"], EMA_LEN)
    df["atr"] = atr(df, ATR_LEN)
    df["vol_z"] = (df["volume"] - df["volume"].rolling(VOL_Z_LEN).mean()) / \
                  df["volume"].rolling(VOL_Z_LEN).std()

    # HTF Hull (по close, last-closed применяется при выборке)
    hull_1d = hull_ma(df_1d["close"], HULL_HTF_1D)
    hull_4h = hull_ma(df_4h["close"], HULL_HTF_4H)

    rows = []
    n = len(df)
    arr_high = df["high"].values
    arr_low = df["low"].values
    arr_close = df["close"].values

    # стоп на n-1: метку для последних баров посчитать можно (гонка вперёд по 1h),
    # но фрактал-факт (i+1,i+2) для диагностики потребует i+2 — это ТОЛЬКО для
    # отчёта, НЕ для фич. Цикл до n (close[i] всегда известен).
    for i in range(max(EMA_LEN, 30), n):
        close_time_i = df.index[i] + tf_ms     # момент закрытия свечи i
        c_i = arr_close[i]
        h_i = arr_high[i]
        l_i = arr_low[i]
        if c_i <= 0 or df["atr"].iloc[i] <= 0 or np.isnan(df["atr"].iloc[i]):
            continue

        atr_i = df["atr"].iloc[i]
        rng = h_i - l_i
        body = abs(c_i - df["open"].iloc[i])
        upper_wick = h_i - max(c_i, df["open"].iloc[i])
        lower_wick = min(c_i, df["open"].iloc[i]) - l_i

        # структура: 30-bar HH/LL ДО i включительно (≤ i, без lookahead)
        win_hi = arr_high[max(0, i - 29):i + 1]
        win_lo = arr_low[max(0, i - 29):i + 1]
        hh30 = win_hi.max()
        ll30 = win_lo.min()
        bars_since_hh = i - (max(0, i - 29) + int(np.argmax(win_hi)))
        bars_since_ll = i - (max(0, i - 29) + int(np.argmin(win_lo)))

        feats = {
            "time": df.index[i],
            "close_time": close_time_i,
            "close": c_i,
            "high": h_i,
            "low": l_i,
            # индикаторы
            "rsi": df["rsi"].iloc[i],
            "hull_dist_pct": (c_i - df["hull"].iloc[i]) / c_i * 100,
            "ema_dist_pct": (c_i - df["ema"].iloc[i]) / c_i * 100,
            "atr_pct": atr_i / c_i * 100,
            "vol_z": df["vol_z"].iloc[i],
            # свеча i
            "body_pct": body / c_i * 100,
            "range_atr": rng / atr_i if atr_i > 0 else 0,
            "upper_wick_pct": upper_wick / rng * 100 if rng > 0 else 0,
            "lower_wick_pct": lower_wick / rng * 100 if rng > 0 else 0,
            "close_in_range": (c_i - l_i) / rng if rng > 0 else 0.5,
            "is_green": 1 if c_i >= df["open"].iloc[i] else 0,
            # momentum (pre-return до close i)
            "ret_3": (c_i / arr_close[i - 3] - 1) * 100 if i >= 3 else 0,
            "ret_7": (c_i / arr_close[i - 7] - 1) * 100 if i >= 7 else 0,
            "ret_14": (c_i / arr_close[i - 14] - 1) * 100 if i >= 14 else 0,
            # структура
            "dist_hh30_pct": (hh30 - c_i) / c_i * 100,
            "dist_ll30_pct": (c_i - ll30) / c_i * 100,
            "bars_since_hh": bars_since_hh,
            "bars_since_ll": bars_since_ll,
            # HTF тренд (last closed)
            "trend_1d": htf_dir_last_closed(close_time_i, hull_1d, df_1d["close"]),
            "trend_4h": htf_dir_last_closed(close_time_i, hull_4h, df_4h["close"]),
            # "почти-фрактал" признаки БЕЗ i+1,i+2 (только левая часть окна)
            "lower_than_prev2": 1 if (i >= 2 and l_i < min(arr_low[i - 1], arr_low[i - 2])) else 0,
            "higher_than_prev2": 1 if (i >= 2 and h_i > max(arr_high[i - 1], arr_high[i - 2])) else 0,
        }

        # МЕТКИ для обоих направлений (гонка по 1h)
        max_race_end = close_time_i + max_race
        y_low = label_good_fractal("low", c_i, l_i, close_time_i, df_1h, max_race_end)
        y_high = label_good_fractal("high", c_i, h_i, close_time_i, df_1h, max_race_end)
        feats["y_low_good"] = y_low
        feats["y_high_good"] = y_high

        # ДИАГНОСТИКА (НЕ фича!): была ли свеча реально фракталом (i+2 нужно)
        if i + FRACTAL_N < n:
            left_lo = arr_low[i - FRACTAL_N:i]
            right_lo = arr_low[i + 1:i + 1 + FRACTAL_N]
            left_hi = arr_high[i - FRACTAL_N:i]
            right_hi = arr_high[i + 1:i + 1 + FRACTAL_N]
            feats["is_fl"] = 1 if (l_i < left_lo.min() and l_i < right_lo.min()) else 0
            feats["is_fh"] = 1 if (h_i > left_hi.max() and h_i > right_hi.max()) else 0
        else:
            feats["is_fl"] = np.nan
            feats["is_fh"] = np.nan

        rows.append(feats)

    return pd.DataFrame(rows).set_index("time")


# ============================================================
# ОБУЧЕНИЕ + ОЦЕНКА
# ============================================================
FEATURE_COLS = [
    "rsi", "hull_dist_pct", "ema_dist_pct", "atr_pct", "vol_z",
    "body_pct", "range_atr", "upper_wick_pct", "lower_wick_pct",
    "close_in_range", "is_green", "ret_3", "ret_7", "ret_14",
    "dist_hh30_pct", "dist_ll30_pct", "bars_since_hh", "bars_since_ll",
    "trend_1d", "trend_4h", "lower_than_prev2", "higher_than_prev2",
]


def train_eval(ds: pd.DataFrame, target: str, label: str) -> dict:
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score, precision_score, recall_score

    d = ds.dropna(subset=[target]).copy()
    d = d[d[FEATURE_COLS].notna().all(axis=1)]

    train = d[d.index < TRAIN_END]
    # embargo: выкинуть EMBARGO_BARS на границе (serial-correlation leak)
    embargo_end = TRAIN_END + pd.Timedelta(TF) * EMBARGO_BARS
    test = d[d.index >= embargo_end]

    if len(train) < 100 or len(test) < 30:
        return {"target": label, "error": f"too few rows train={len(train)} test={len(test)}"}

    Xtr, ytr = train[FEATURE_COLS], train[target].astype(int)
    Xte, yte = test[FEATURE_COLS], test[target].astype(int)

    base_tr = ytr.mean()
    base_te = yte.mean()

    clf = lgb.LGBMClassifier(
        n_estimators=300, num_leaves=31, learning_rate=0.03,
        min_child_samples=40, subsample=0.8, colsample_bytree=0.8,
        reg_lambda=1.0, random_state=42, n_jobs=3, verbose=-1,
        is_unbalance=True,
    )
    clf.fit(Xtr, ytr)
    proba = clf.predict_proba(Xte)[:, 1]

    auc = roc_auc_score(yte, proba) if yte.nunique() > 1 else float("nan")

    # precision @ probability bins (главная практическая метрика)
    bins = []
    for thr in [0.5, 0.6, 0.7, 0.8]:
        sel = proba >= thr
        if sel.sum() >= 5:
            prec = precision_score(yte, sel, zero_division=0)
            rec = recall_score(yte, sel, zero_division=0)
            bins.append((thr, int(sel.sum()), round(prec, 3), round(rec, 3),
                         round(prec / base_te, 2) if base_te > 0 else 0))

    imp = sorted(zip(FEATURE_COLS, clf.feature_importances_),
                 key=lambda x: -x[1])[:10]

    return {
        "target": label,
        "n_train": len(train), "n_test": len(test),
        "base_rate_train": round(base_tr, 4), "base_rate_test": round(base_te, 4),
        "auc": round(auc, 4),
        "precision_bins": bins,   # (thr, n_selected, precision, recall, lift)
        "top_features": imp,
    }


def main() -> None:
    print(f"[etap_174] Загрузка данных {SYMBOL} {TF}/{RACE_TF}...")
    ds = build_dataset()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ds.to_csv(OUT_DIR / "etap174_fractal_dataset.csv")
    print(f"[data] {len(ds)} строк, {ds.index[0]} → {ds.index[-1]}")

    # baseline-статистика
    print("\n=== BASELINE (доля 'хороших' среди ВСЕХ свечей) ===")
    for tgt, name in [("y_low_good", "LOW→+5% (LONG)"), ("y_high_good", "HIGH→-5% (SHORT)")]:
        v = ds[tgt].dropna()
        print(f"  {name}: {v.mean()*100:.2f}% хороших из {len(v)} свечей "
              f"({int(v.sum())} good)")

    # для сверки: сколько среди РЕАЛЬНЫХ фракталов хороших
    print("\n=== СВЕРКА: среди реальных фракталов (диагностика, i+2) ===")
    fl = ds[(ds["is_fl"] == 1)]["y_low_good"].dropna()
    fh = ds[(ds["is_fh"] == 1)]["y_high_good"].dropna()
    if len(fl):
        print(f"  FL фракталов: {len(fl)}, из них хороших {fl.mean()*100:.1f}%")
    if len(fh):
        print(f"  FH фракталов: {len(fh)}, из них хороших {fh.mean()*100:.1f}%")

    print("\n=== ОБУЧЕНИЕ (time-split, train<2025-01-01, test после embargo) ===")
    results = []
    for tgt, name in [("y_low_good", "LOW→+5% (LONG)"), ("y_high_good", "HIGH→-5% (SHORT)")]:
        r = train_eval(ds, tgt, name)
        results.append(r)
        print(f"\n--- {name} ---")
        if "error" in r:
            print("  ", r["error"]); continue
        print(f"  train={r['n_train']} test={r['n_test']} "
              f"base_test={r['base_rate_test']*100:.2f}% AUC={r['auc']}")
        print(f"  precision @ prob bins (thr, n, precision, recall, lift):")
        for b in r["precision_bins"]:
            print(f"     thr>={b[0]}: n={b[1]:4d}  prec={b[2]:.3f}  "
                  f"rec={b[3]:.3f}  lift=×{b[4]}")
        print(f"  top features: {', '.join(f'{f}({v})' for f,v in r['top_features'][:6])}")

    print("\n[ВАЖНО] Любой lift/precision аномально высокий (>2× baseline, "
          "precision>0.6 на сотнях) — ПЕРВЫМ ДЕЛОМ проверить lookahead, "
          "не радоваться (known-pitfalls).")


if __name__ == "__main__":
    main()
