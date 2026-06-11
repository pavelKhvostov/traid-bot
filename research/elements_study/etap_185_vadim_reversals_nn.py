"""etap_185: Нейросеть-разворот на сигналах ViC Vadim (78% precision) — лучшее × лучшее.

Сходятся два сильнейших инструмента для РАЗВОРОТОВ:
- ViC Vadim Core (sweep HTF-зон ∪ OB ∩ sweep maxV): 78.98% precision (HH 83%/LL 75%)
- Нейросеть-арсенал (etap_177): AUC 0.93 на предсказании разворотных фракталов

Генерирую Core-сигналы Вадима на BTC/ETH/SOL (2017+), для каждого:
1. РЕАЛЬНЫЙ исход (стал ли разворотным фракталом + дал движение) — метка Андрея.
2. Оценка нейросетью (арсенал-фичи etap_177): согласна ли сеть, что тут разворот.
Смотрим: усиливает ли нейросеть-фильтр precision Вадима (78% → выше?).

Переиспользует функции Вадима (research/vic_vadim/predict_fractal_maxv) + арсенал etap_177.
Данные: 15m (для maxV) + 12h, с 2017.

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/etap_185_vadim_reversals_nn.py
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

from data_manager import load_df, compose_from_base

# функции Вадима
from research.vic_vadim.predict_fractal_maxv import (
    calculate_maxv_12h_bar, find_ob_zones, find_fractals,
    zone_sweep_flags, fractal_sweep_flags, HTF_LIST, compose_htf,
)
# арсенал-фичи + нейросеть (etap_177)
_s177 = _ilu.spec_from_file_location("e177", _ROOT / "research/elements_study/etap_177_neural_full_arsenal_pavel.py")
_e177 = _ilu.module_from_spec(_s177); _s177.loader.exec_module(_e177)

OUT_DIR = _ROOT / "research" / "elements_study" / "output"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
FRACTAL_N = 2
FUTURE_BARS = 14
MOVE_PCT = 5.0   # «хороший» разворот = движение >=5% (метка Андрея)


def gen_vadim_core_signals(sym):
    """Core-сигналы Вадима: (sweep_FH/FL ∪ OB_sweep) ∩ sweep_maxV[i] на 12h.

    Возвращает DataFrame: signal_time(12h open), direction(HH=SHORT/LL=LONG),
    + реальный исход (стал фракталом + движение) + close/high/low бара i.
    """
    df_15m = load_df(sym, "15m").sort_index()
    df_12h = load_df(sym, "12h").sort_index()
    if df_15m.empty or df_12h.empty:
        return None

    # maxV для каждой 12h-свечи (из 15m, LTF≈15m приближение)
    df_15m_naive = df_15m.copy(); df_15m_naive.index.name = None
    maxv = np.full(len(df_12h), np.nan)
    for k, t in enumerate(df_12h.index):
        v = calculate_maxv_12h_bar(df_15m_naive, t)
        if v is not None:
            maxv[k] = v

    H = df_12h["high"].to_numpy(); L = df_12h["low"].to_numpy(); C = df_12h["close"].to_numpy()
    # sweep maxV(i-1) на свече i
    sw_short = np.zeros(len(df_12h), bool); sw_long = np.zeros(len(df_12h), bool)
    for i in range(1, len(df_12h)):
        m = maxv[i-1]
        if np.isnan(m): continue
        if H[i] > m and C[i] < m: sw_short[i] = True   # HH
        if L[i] < m and C[i] > m: sw_long[i] = True    # LL

    # HTF-зоны sweep (fractal + OB) на 12h/1d/2d/3d/W (compose_htf Вадима)
    htf = {tf: compose_htf(df_15m, freq).sort_index() for tf, freq in HTF_LIST}
    all_ob, all_fract = [], []
    for tf, dft in htf.items():
        try:
            all_ob += find_ob_zones(dft, tf)
            all_fract += find_fractals(dft, tf)
        except Exception:
            pass
    c1_fh = fractal_sweep_flags(df_12h, all_fract, "FH")
    c1_fl = fractal_sweep_flags(df_12h, all_fract, "FL")
    c1_obs = zone_sweep_flags(df_12h, all_ob, "SHORT")
    c1_obl = zone_sweep_flags(df_12h, all_ob, "LONG")

    # Core: (sweep_FH ∪ OB_short) ∩ sweep_maxV для HH; зеркально LL
    core_hh = (np.asarray(c1_fh) | np.asarray(c1_obs)) & sw_short
    core_ll = (np.asarray(c1_fl) | np.asarray(c1_obl)) & sw_long

    rows = []
    n = len(df_12h)
    for i in range(FRACTAL_N, n - FRACTAL_N - 1):
        if not (core_hh[i] or core_ll[i]):
            continue
        direction = "SHORT" if core_hh[i] else "LONG"
        # реальный исход = стал фракталом + движение в сторону разворота
        if core_ll[i]:  # LL → LONG, ждём рост
            is_fract = L[i] < L[i-FRACTAL_N:i].min() and L[i] < L[i+1:i+1+FRACTAL_N].min()
            s = i + FRACTAL_N + 1; e = min(n, s + FUTURE_BARS)
            mv = (H[s:e].max()/L[i]-1)*100 if e > s else 0
        else:  # HH → SHORT, ждём падение
            is_fract = H[i] > H[i-FRACTAL_N:i].max() and H[i] > H[i+1:i+1+FRACTAL_N].max()
            s = i + FRACTAL_N + 1; e = min(n, s + FUTURE_BARS)
            mv = (L[i] - L[s:e].min())/L[i]*100 if e > s else 0
        good = bool(is_fract and mv >= MOVE_PCT)
        rows.append({
            "signal_time": df_12h.index[i], "symbol": sym,
            "direction": direction, "is_fractal": int(is_fract),
            "move_pct": round(mv, 2), "good_reversal": int(good),
            "close": C[i], "high": H[i], "low": L[i],
            "bar_idx": i,
        })
    return pd.DataFrame(rows)


def main():
    import torch
    from sklearn.preprocessing import StandardScaler
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_185] Vadim Core разворотов + нейросеть | device={device}", flush=True)

    # 1) генерируем Core-сигналы Вадима по 3 активам
    parts = []
    for sym in SYMBOLS:
        print(f"[vadim] {sym}: генерирую Core-сигналы (maxV из 15m)...", flush=True)
        sig = gen_vadim_core_signals(sym)
        if sig is not None and len(sig):
            parts.append(sig)
            prec = sig["good_reversal"].mean()*100
            isf = sig["is_fractal"].mean()*100
            print(f"  {sym}: {len(sig)} Core-сигналов, фракталов {isf:.0f}%, "
                  f"хороших разворотов(>=5%) {prec:.0f}%", flush=True)
    if not parts:
        print("[ERR] нет сигналов"); return
    vadim = pd.concat(parts).sort_values("signal_time").reset_index(drop=True)
    print(f"\n[Vadim Core ВСЕГО] {len(vadim)} сигналов, "
          f"is_fractal {vadim['is_fractal'].mean()*100:.0f}%, "
          f"хороших разворотов {vadim['good_reversal'].mean()*100:.0f}%", flush=True)

    # 2) арсенал-фичи etap_177 для каждого актива → джойн к сигналам Вадима
    print("\n[фичи] строю арсенал etap_177 по активам...", flush=True)
    feat_by_sym = {}
    for aid, sym in enumerate(SYMBOLS):
        fdf = _e177.build_symbol(sym, aid).sort_index()
        feat_by_sym[sym] = fdf
    feat_cols = [c for c in _e177.make_feature_list(list(_e177.BULK_ALL.keys()))
                 if c in next(iter(feat_by_sym.values())).columns]

    rows = []
    for _, sig in vadim.iterrows():
        fdf = feat_by_sym[sig["symbol"]]
        pos = fdf.index.searchsorted(sig["signal_time"], side="right") - 1
        if pos < 0: continue
        d = {c: fdf.iloc[pos][c] for c in feat_cols}
        d["good_reversal"] = sig["good_reversal"]
        d["is_fractal"] = sig["is_fractal"]
        d["direction_long"] = 1 if sig["direction"] == "LONG" else 0
        d["signal_time"] = sig["signal_time"]
        d["symbol"] = sig["symbol"]
        rows.append(d)
    ds = pd.DataFrame(rows).set_index("signal_time").sort_index()
    feats = [f for f in feat_cols if f in ds.columns]
    ds = ds[ds[feats].notna().all(axis=1)]
    print(f"[data] {len(ds)} сигналов с фичами, фич={len(feats)}", flush=True)

    # 3) нейросеть оценивает: согласна ли что тут разворот (Purged K-Fold OOF)
    from scipy.stats import spearmanr
    from sklearn.metrics import roc_auc_score
    y = ds["good_reversal"].values.astype(float)
    X = ds[feats].values
    w = _e177.uniqueness_weights(ds.index, 7)
    oof = np.full(len(ds), np.nan)
    print("\n[NN] Purged K-Fold OOF оценка...", flush=True)
    for fi, (tri, vai) in enumerate(_e177.purged_splits(ds.index, 5, 14, 7)):
        sc = StandardScaler().fit(X[tri])
        net, vr = _e177.train_net(sc.transform(X[tri]), y[tri], w[tri],
                                  sc.transform(X[vai]), y[vai], len(feats), device=device)
        oof[vai] = _e177.predict_net(net, sc.transform(X[vai]), device)
        print(f"    fold {fi}: val AUC≈{vr:.3f}", flush=True)
    miss = np.isnan(oof)
    if miss.any():
        sc = StandardScaler().fit(X[~miss])
        net, _ = _e177.train_net(sc.transform(X[~miss]), y[~miss], w[~miss],
                                 sc.transform(X[~miss][:100]), y[~miss][:100], len(feats), device=device)
        oof[miss] = _e177.predict_net(net, sc.transform(X[miss]), device)

    ds["nn_score"] = oof
    auc = roc_auc_score(y, oof) if len(np.unique(y)) > 1 else float("nan")

    # 4) результат: усиливает ли нейросеть precision Вадима?
    base = y.mean()*100
    print(f"\n========== РЕЗУЛЬТАТ: Vadim Core + нейросеть ==========", flush=True)
    print(f"  Vadim Core БЕЗ нейросети: precision хороших разворотов {base:.0f}% ({len(ds)} сигналов)", flush=True)
    print(f"  Нейросеть OOS AUC: {auc:.3f}", flush=True)
    for q in [0.5, 0.7, 0.8, 0.9]:
        thr = np.quantile(oof, q)
        top = ds[ds["nn_score"] >= thr]
        if len(top) >= 5:
            p = top["good_reversal"].mean()*100
            print(f"  + нейросеть топ-{int((1-q)*100)}% (score>={thr:.2f}): "
                  f"precision {p:.0f}% (база {base:.0f}%, lift ×{p/base:.2f}), n={len(top)}", flush=True)

    # sanity shuffle
    rng = np.random.RandomState(0); ysh = y.copy(); rng.shuffle(ysh)
    tri, vai = next(_e177.purged_splits(ds.index, 5, 14, 7))
    sc = StandardScaler().fit(X[tri])
    net_sh, _ = _e177.train_net(sc.transform(X[tri]), ysh[tri], w[tri],
                                sc.transform(X[vai]), ysh[vai], len(feats), epochs=60, device=device)
    sh = roc_auc_score(y, _e177.predict_net(net_sh, sc.transform(X), device)) if len(np.unique(y))>1 else 0.5
    print(f"\n  [SANITY] shuffle AUC={sh:.3f} (должен ~0.5)", flush=True)

    ds.to_csv(OUT_DIR / "etap185_vadim_nn.csv")
    print(f"[saved] → etap185_vadim_nn.csv", flush=True)


if __name__ == "__main__":
    main()
