"""etap_175: Улучшенный предсказатель «хорошего» фрактала (5% race) + нейросеть.

РАЗВИТИЕ etap_174. Метка та же (5%-race, см. ниже), НО добавлены sweep-фичи
(главная находка из подхода Андрея = ICT liquidity sweep / DOL) + сравнение
LightGBM vs нейросеть (MLP).

ПОЧЕМУ SWEEP: в etap_173 (Андрей) топ-фича по importance = sweep_SSL/BSL_mag
(0.32-0.36) — снятие ликвидности. Это ровно ICT Liquidity Sweep Strategy
(Month01 Judas Swing, ICT-2022 DOL): цена снимает ликвидность под лоем →
разворот вверх. failed-sweep (пробил и вернулся) = ещё сильнее. Мой etap_174
этих фич НЕ имел → застрял на precision 33%.

МЕТКА (5%-race, как в etap_174):
  LOW (LONG):  good = high достиг close[i]*1.05 РАНЬШЕ, чем low < low[i].
  HIGH (SHORT): good = low достиг close[i]*0.95 РАНЬШЕ, чем high > high[i].
  Гонка по 1h, старт close_time[i], горизонт 30д, tie → стоп раньше.

ЗАЩИТА ОТ LOOKAHEAD (known-pitfalls, как в etap_174):
  - sweep-фичи: окно df_12h.iloc[i-win:i+1] ВКЛЮЧАЯ i, prev = всё ДО i.
    Всё <= close[i]. (определение взято из etap_165, проверено.)
  - HTF тренд по last-closed бару.
  - Гонка с close_time[i], по реальным 1h. time-split + embargo.
  - Sanity: shuffle-label AUC должен быть ~0.5.

НЕЙРОСЕТЬ: MLP (sklearn) на стандартизованных фичах. López de Prado
предупреждал: на табличных фин-фичах NN обычно ХУЖЕ GBM и легче переобучается
— проверим честно на одной выборке.

Запуск: .venv-pivot/bin/python research/elements_study/etap_175_fractal_5pct_sweep_nn.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import importlib.util as _ilu
import numpy as np
import pandas as pd

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

# Bulkowski-детекторы Андрея (etap_172) — top-5 как фичи (fired + bars_since).
# Lookahead-safe: детектор на баре i использует только close<=i (confirmed
# swings с N=2 ограничены окном [lo, i], breakout на close[i], close[i-1]<=peak).
_E172_PATH = _ROOT / "research" / "elements_study" / "etap_172_bulkowski_patterns.py"
_spec = _ilu.spec_from_file_location("e172", _E172_PATH)
_e172 = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_e172)
BULK_TOP5 = {
    "big_w": _e172.detect_big_w,
    "db_eve_eve": _e172.detect_db_eve_eve,
    "v_bottom": _e172.detect_v_bottom,
    "hs_bottom": _e172.detect_hs_bottom,
    "big_m": _e172.detect_big_m,
}
BARS_SINCE_CAP = 60

SYMBOL = "BTCUSDT"
TF = "12h"
RACE_TF = "1h"
FRACTAL_N = 2
MOVE_PCT = 0.05
MAX_RACE_DAYS = 30
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
EMBARGO_BARS = FRACTAL_N + 1

RSI_LEN, HULL_LEN, EMA_LEN, ATR_LEN, VOL_Z_LEN = 14, 78, 200, 14, 20
ZONE_LOOKBACK = 60
OUT_DIR = _ROOT / "research" / "elements_study" / "output"


# ---------- индикаторы ----------
def rsi_wilder(s, length=14):
    d = s.diff(); g = d.clip(lower=0); l = (-d).clip(lower=0)
    ag = g.ewm(alpha=1/length, adjust=False).mean()
    al = l.ewm(alpha=1/length, adjust=False).mean()
    return 100 - 100/(1 + ag/al.replace(0, np.nan))


def _wma(v, length):
    w = np.arange(1, length+1, dtype=float); out = np.full(len(v), np.nan)
    for i in range(length-1, len(v)):
        out[i] = np.dot(v[i-length+1:i+1], w)/w.sum()
    return out


def hull_ma(s, length=78):
    half = length//2; sq = int(np.sqrt(length))
    raw = 2*_wma(s.values, half) - _wma(s.values, length)
    return pd.Series(_wma(pd.Series(raw).fillna(0).values, sq), index=s.index)


def ema(s, length=200): return s.ewm(span=length, adjust=False).mean()


def atr(df, length=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()


# ---------- метка (5% race) ----------
def label_good(direction, close_i, extreme_i, t0, df_1h, t_end):
    fwd = df_1h[(df_1h.index >= t0) & (df_1h.index < t_end)]
    if fwd.empty:
        return None
    if direction == "low":
        target = close_i * (1 + MOVE_PCT)
        for _, c in fwd.iterrows():
            if c["low"] < extreme_i:   # стоп раньше (tie → стоп)
                return 0
            if c["high"] >= target:
                return 1
        return 0
    else:
        target = close_i * (1 - MOVE_PCT)
        for _, c in fwd.iterrows():
            if c["high"] > extreme_i:
                return 0
            if c["low"] <= target:
                return 1
        return 0


# ---------- HTF last-closed ----------
def htf_dir(t0, hull_htf, close_htf):
    idx = close_htf.index.searchsorted(t0, side="right") - 1
    if idx < 3:
        return 0
    j = idx - 1  # гарантированно закрытый
    c, h = close_htf.iloc[j], hull_htf.iloc[j]
    if np.isnan(c) or np.isnan(h):
        return 0
    return 1 if c > h else -1


# ---------- зоны на момент i (для дистанций) ----------
def zone_dists(df, idx, price):
    """Мин. дистанция до ближайших OB/FVG LONG/SHORT (% от цены). <=i."""
    out = {}
    obs, fvgs = [], []
    for j in range(max(2, idx - ZONE_LOOKBACK), idx + 1):
        z = detect_ob_pair(df, j)
        if z is not None:
            obs.append(z)
        f = detect_fvg(df, j)
        if f is not None:
            fvgs.append(f)
    for dir_lbl in ["LONG", "SHORT"]:
        for typ, items in [("OB", obs), ("FVG", fvgs)]:
            best = 99.0; n = 0; in_zone = 0
            for z in items:
                if z.direction != dir_lbl:
                    continue
                n += 1
                if z.bottom <= price <= z.top:
                    in_zone = 1; d = 0.0
                elif price < z.bottom:
                    d = (z.bottom - price) / price * 100
                else:
                    d = (price - z.top) / price * 100
                best = min(best, d)
            out[f"dist_{dir_lbl}_{typ}_pct"] = best
            out[f"n_{dir_lbl}_{typ}"] = n
            out[f"in_{dir_lbl}_{typ}"] = in_zone
    return out


# ---------- sweep-фичи (из etap_165, ICT liquidity sweep) ----------
def sweep_feats(df, i, highs, lows, close_i):
    out = {}
    for win_h, win_bars in [(24, 2), (72, 6), (168, 14)]:
        wl = max(0, i - win_bars)
        wd = df.iloc[wl:i+1]
        if len(wd) >= 2:
            prev = wd.iloc[:-1]
            prev_hi = prev["high"].max(); prev_lo = prev["low"].min()
            bsl = int(highs[i] > prev_hi)
            ssl = int(lows[i] < prev_lo)
            bsl_mag = (highs[i]-prev_hi)/prev_hi*100 if bsl and prev_hi > 0 else 0
            ssl_mag = (prev_lo-lows[i])/prev_lo*100 if ssl and prev_lo > 0 else 0
            bsl_failed = int(bsl and close_i < prev_hi)   # пробил high, закрылся ниже → разворот вниз
            ssl_failed = int(ssl and close_i > prev_lo)   # пробил low, закрылся выше → разворот вверх
        else:
            bsl = ssl = bsl_failed = ssl_failed = 0; bsl_mag = ssl_mag = 0
        out[f"sweep_BSL_{win_h}h"] = bsl
        out[f"sweep_SSL_{win_h}h"] = ssl
        out[f"sweep_BSL_failed_{win_h}h"] = bsl_failed
        out[f"sweep_SSL_failed_{win_h}h"] = ssl_failed
        out[f"sweep_BSL_mag_{win_h}h_pct"] = float(bsl_mag)
        out[f"sweep_SSL_mag_{win_h}h_pct"] = float(ssl_mag)
    return out


# ---------- Bulkowski top-5 fires (lookahead-safe, <=i) ----------
def precompute_bulkowski(df):
    """Для каждого паттерна: fired[i] (0/1) + bars_since[i] (cap 60).

    Детектор использует close<=i (см. коммент при импорте). df с колонкой time.
    """
    df_det = df.reset_index()
    if "time" not in df_det.columns:
        df_det = df_det.rename(columns={df_det.columns[0]: "time"})
    out = {}
    start = _e172.LOOKBACK + _e172.SWING_N + 2
    for name, det in BULK_TOP5.items():
        fired = np.zeros(len(df), dtype=int)
        for i in range(start, len(df)):
            try:
                if det(df_det, i) is not None:
                    fired[i] = 1
            except Exception:
                pass
        bars_since = np.full(len(df), BARS_SINCE_CAP, dtype=int)
        last = -10000
        for i in range(len(df)):
            if fired[i]:
                last = i
            bars_since[i] = min(i - last, BARS_SINCE_CAP) if last >= 0 else BARS_SINCE_CAP
        out[name] = {"fired": fired, "bars_since": bars_since}
    return out


# ---------- сборка ----------
def build():
    df = load_df(SYMBOL, TF).sort_index()
    df_1h = load_df(SYMBOL, RACE_TF).sort_index()
    df_1d = load_df(SYMBOL, "1d").sort_index()
    df_4h = load_df(SYMBOL, "4h").sort_index()
    tf_ms = pd.Timedelta(TF); race = pd.Timedelta(days=MAX_RACE_DAYS)

    df["rsi"] = rsi_wilder(df["close"], RSI_LEN)
    df["hull"] = hull_ma(df["close"], HULL_LEN)
    df["ema"] = ema(df["close"], EMA_LEN)
    df["atr"] = atr(df, ATR_LEN)
    df["vol_z"] = (df["volume"]-df["volume"].rolling(VOL_Z_LEN).mean())/df["volume"].rolling(VOL_Z_LEN).std()
    hull_1d = hull_ma(df_1d["close"], 78); hull_4h = hull_ma(df_4h["close"], 78)

    print("  precompute Bulkowski top-5 fires...")
    bulk = precompute_bulkowski(df)
    for nm, d in bulk.items():
        print(f"    {nm}: {int(d['fired'].sum())} fires")

    H, L, C, O = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    rows = []; n = len(df)
    for i in range(max(EMA_LEN, 30), n):
        if df["atr"].iloc[i] <= 0 or np.isnan(df["atr"].iloc[i]) or C[i] <= 0:
            continue
        t0 = df.index[i] + tf_ms
        atr_i = df["atr"].iloc[i]; rng = H[i]-L[i]; body = abs(C[i]-O[i])
        uw = H[i]-max(C[i], O[i]); lw = min(C[i], O[i])-L[i]
        win_hi = H[max(0, i-29):i+1]; win_lo = L[max(0, i-29):i+1]

        f = {
            "time": df.index[i], "close": C[i], "high": H[i], "low": L[i],
            "rsi": df["rsi"].iloc[i],
            "hull_dist_pct": (C[i]-df["hull"].iloc[i])/C[i]*100,
            "ema_dist_pct": (C[i]-df["ema"].iloc[i])/C[i]*100,
            "atr_pct": atr_i/C[i]*100, "vol_z": df["vol_z"].iloc[i],
            "body_pct": body/C[i]*100, "range_atr": rng/atr_i if atr_i > 0 else 0,
            "upper_wick_pct": uw/rng*100 if rng > 0 else 0,
            "lower_wick_pct": lw/rng*100 if rng > 0 else 0,
            "close_in_range": (C[i]-L[i])/rng if rng > 0 else 0.5,
            "is_green": 1 if C[i] >= O[i] else 0,
            "ret_3": (C[i]/C[i-3]-1)*100 if i >= 3 else 0,
            "ret_7": (C[i]/C[i-7]-1)*100 if i >= 7 else 0,
            "ret_14": (C[i]/C[i-14]-1)*100 if i >= 14 else 0,
            "dist_hh30_pct": (win_hi.max()-C[i])/C[i]*100,
            "dist_ll30_pct": (C[i]-win_lo.min())/C[i]*100,
            "bars_since_hh": i-(max(0, i-29)+int(np.argmax(win_hi))),
            "bars_since_ll": i-(max(0, i-29)+int(np.argmin(win_lo))),
            "trend_1d": htf_dir(t0, hull_1d, df_1d["close"]),
            "trend_4h": htf_dir(t0, hull_4h, df_4h["close"]),
            "lower_than_prev2": 1 if (i >= 2 and L[i] < min(L[i-1], L[i-2])) else 0,
            "higher_than_prev2": 1 if (i >= 2 and H[i] > max(H[i-1], H[i-2])) else 0,
        }
        f.update(sweep_feats(df, i, H, L, C[i]))      # ← sweep / ICT DOL
        f.update(zone_dists(df, i, C[i]))             # ← OB/FVG дистанции
        for nm, d in bulk.items():                    # ← Bulkowski top-5 fires
            f[f"bulk_{nm}_fired"] = int(d["fired"][i])
            f[f"bulk_{nm}_bars_since"] = int(d["bars_since"][i])

        t_end = t0 + race
        f["y_low_good"] = label_good("low", C[i], L[i], t0, df_1h, t_end)
        f["y_high_good"] = label_good("high", C[i], H[i], t0, df_1h, t_end)
        # диагностика фрактал-факта (не фича)
        if i+FRACTAL_N < n:
            f["is_fl"] = 1 if (L[i] < L[i-FRACTAL_N:i].min() and L[i] < L[i+1:i+1+FRACTAL_N].min()) else 0
            f["is_fh"] = 1 if (H[i] > H[i-FRACTAL_N:i].max() and H[i] > H[i+1:i+1+FRACTAL_N].max()) else 0
        else:
            f["is_fl"] = np.nan; f["is_fh"] = np.nan
        rows.append(f)
    return pd.DataFrame(rows).set_index("time")


# базовые фичи (etap_174) + новые
BASE_FEATS = [
    "rsi", "hull_dist_pct", "ema_dist_pct", "atr_pct", "vol_z", "body_pct",
    "range_atr", "upper_wick_pct", "lower_wick_pct", "close_in_range", "is_green",
    "ret_3", "ret_7", "ret_14", "dist_hh30_pct", "dist_ll30_pct",
    "bars_since_hh", "bars_since_ll", "trend_1d", "trend_4h",
    "lower_than_prev2", "higher_than_prev2",
]
SWEEP_FEATS = []
for s in ("BSL", "SSL"):
    for w in (24, 72, 168):
        SWEEP_FEATS += [f"sweep_{s}_{w}h", f"sweep_{s}_failed_{w}h", f"sweep_{s}_mag_{w}h_pct"]
ZONE_FEATS = [f"{p}_{d}_{t}{suf}" for d in ("LONG", "SHORT") for t in ("OB", "FVG")
              for p, suf in [("dist", "_pct"), ("n", ""), ("in", "")]]
# поправка имён zone (dist_LONG_OB_pct / n_LONG_OB / in_LONG_OB)
ZONE_FEATS = []
for d in ("LONG", "SHORT"):
    for t in ("OB", "FVG"):
        ZONE_FEATS += [f"dist_{d}_{t}_pct", f"n_{d}_{t}", f"in_{d}_{t}"]

BULK_FEATS = []
for nm in ("big_w", "db_eve_eve", "v_bottom", "hs_bottom", "big_m"):
    BULK_FEATS += [f"bulk_{nm}_fired", f"bulk_{nm}_bars_since"]

ALL_FEATS = BASE_FEATS + SWEEP_FEATS + ZONE_FEATS + BULK_FEATS


def split(ds, target):
    d = ds.dropna(subset=[target]).copy()
    d = d[d[ALL_FEATS].notna().all(axis=1)]
    tr = d[d.index < TRAIN_END]
    emb = TRAIN_END + pd.Timedelta(TF)*EMBARGO_BARS
    te = d[d.index >= emb]
    return tr, te


def eval_model(name, proba, yte, base):
    from sklearn.metrics import roc_auc_score, precision_score, recall_score
    auc = roc_auc_score(yte, proba) if yte.nunique() > 1 else float("nan")
    bins = []
    for thr in [0.5, 0.6, 0.7, 0.8]:
        sel = proba >= thr
        if sel.sum() >= 5:
            p = precision_score(yte, sel, zero_division=0)
            r = recall_score(yte, sel, zero_division=0)
            bins.append((thr, int(sel.sum()), round(p, 3), round(r, 3),
                         round(p/base, 2) if base > 0 else 0))
    return auc, bins


def run_target(ds, target, label):
    import lightgbm as lgb
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    tr, te = split(ds, target)
    if len(tr) < 100 or len(te) < 30:
        print(f"  [{label}] too few: tr={len(tr)} te={len(te)}"); return
    Xtr, ytr = tr[ALL_FEATS], tr[target].astype(int)
    Xte, yte = te[ALL_FEATS], te[target].astype(int)
    base = yte.mean()
    print(f"\n=== {label} ===  train={len(tr)} test={len(te)} base_test={base*100:.2f}%")

    # --- LightGBM ---
    gbm = lgb.LGBMClassifier(n_estimators=400, num_leaves=31, learning_rate=0.025,
                             min_child_samples=40, subsample=0.8, colsample_bytree=0.8,
                             reg_lambda=1.0, random_state=42, n_jobs=3, verbose=-1,
                             is_unbalance=True)
    gbm.fit(Xtr, ytr)
    pg = gbm.predict_proba(Xte)[:, 1]
    auc_g, bins_g = eval_model("GBM", pg, yte, base)
    print(f"  [LightGBM]  AUC={auc_g:.4f}")
    for b in bins_g:
        print(f"     thr>={b[0]}: n={b[1]:4d} prec={b[2]:.3f} rec={b[3]:.3f} lift=×{b[4]}")
    imp = sorted(zip(ALL_FEATS, gbm.feature_importances_), key=lambda x: -x[1])[:8]
    print(f"  top: {', '.join(f'{f}({v})' for f,v in imp)}")

    # --- Neural net (MLP) ---
    sc = StandardScaler().fit(Xtr)
    mlp = MLPClassifier(hidden_layer_sizes=(64, 32), activation="relu",
                        alpha=1e-3, learning_rate_init=1e-3, max_iter=300,
                        early_stopping=True, n_iter_no_change=15, random_state=42)
    mlp.fit(sc.transform(Xtr), ytr)
    pn = mlp.predict_proba(sc.transform(Xte))[:, 1]
    auc_n, bins_n = eval_model("NN", pn, yte, base)
    print(f"  [Neural MLP] AUC={auc_n:.4f}")
    for b in bins_n:
        print(f"     thr>={b[0]}: n={b[1]:4d} prec={b[2]:.3f} rec={b[3]:.3f} lift=×{b[4]}")

    # --- sanity shuffle (на GBM) ---
    ysh = ytr.sample(frac=1, random_state=0).values
    gbm2 = lgb.LGBMClassifier(n_estimators=400, num_leaves=31, learning_rate=0.025,
                              min_child_samples=40, random_state=42, n_jobs=3,
                              verbose=-1, is_unbalance=True)
    gbm2.fit(Xtr, ysh)
    auc_sh = roc_auc_score(yte, gbm2.predict_proba(Xte)[:, 1]) if yte.nunique() > 1 else float("nan")
    print(f"  [SANITY] shuffle-label AUC={auc_sh:.4f} (должен быть ~0.5)")


def main():
    print(f"[etap_175] build dataset {SYMBOL} {TF} (sweep + zones)...")
    ds = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ds.to_csv(OUT_DIR / "etap175_dataset.csv")
    print(f"[data] {len(ds)} rows, {ds.index[0]} → {ds.index[-1]}")
    print(f"[feats] base={len(BASE_FEATS)} sweep={len(SWEEP_FEATS)} zone={len(ZONE_FEATS)} bulk={len(BULK_FEATS)} total={len(ALL_FEATS)}")

    for tgt, name in [("y_low_good", "LOW→+5% (LONG)"), ("y_high_good", "HIGH→-5% (SHORT)")]:
        v = ds[tgt].dropna()
        print(f"  baseline {name}: {v.mean()*100:.2f}% ({int(v.sum())}/{len(v)})")

    for tgt, name in [("y_low_good", "LOW→+5% (LONG)"), ("y_high_good", "HIGH→-5% (SHORT)")]:
        run_target(ds, tgt, name)

    print("\n[ВАЖНО] precision>0.6 на сотнях + shuffle-AUC>0.55 = проверять lookahead.")


if __name__ == "__main__":
    main()
