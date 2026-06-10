"""etap_179: Оценка сигналов 1-5 на BTC+ETH+SOL (pooled) + MDA importance.

Усиление etap_178: те же стратегии (1.1.1/1.1.2/1.1.3) и метка 1-5 (гонка
TP=2.2R vs SL по 1m), но на ВСЕХ ТРЁХ активах сразу (pooled) + MDA feature
importance (какие фичи реально несут сигнал качества).

Логика и функции переиспользуются из etap_178 (метка, fill-гонка, ординальная
CORAL-сеть) и etap_177 (арсенал-фичи, Purged K-Fold, uniqueness).

Зачем 3 актива: в etap_177 переход BTC→BTC+ETH+SOL дал скачок AUC 0.67→0.93
(нейросети нужны данные). Здесь та же гипотеза для фильтра качества.

Запуск: .venv-pivot/bin/python research/elements_study/etap_179_signal_grade_3assets_mda.py
Требует 1m+15m для BTC/ETH/SOL.
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
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals

# переиспуем etap_178 (метка/оценка/сеть) и etap_177 (арсенал-фичи/CV)
_s178 = _ilu.spec_from_file_location("e178", _ROOT / "research/elements_study/etap_178_signal_grade_1to5_ordinal_nn.py")
_e178 = _ilu.module_from_spec(_s178); _s178.loader.exec_module(_e178)
_e177 = _e178._e177  # арсенал-фичи уже импортированы в etap_178

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TRAIN_END = _e178.TRAIN_END
EMBARGO_BARS = _e178.EMBARGO_BARS
KFOLD = _e178.KFOLD
EMBARGO_KF = _e178.EMBARGO_KF
OUT_DIR = _e178.OUT_DIR


FRACTAL_N = 2          # Williams (подтверждается через 2 бара)
FRACTAL_SL_DEPTH = 0.15  # SL чуть за экстремум: 15% диапазона свечи фрактала
TARGET_RR = 2.2        # как у стратегий 1.1.x


def gen_fractal_signals(df_12h):
    """Фрактал-развороты Андрея как 4-й источник сигналов (strategy_id=3).

    Сигнал на 12h: свеча i — подтверждённый Williams-фрактал N=2.
    [lookahead-safe] вход на close свечи i+N (момент ПОДТВЕРЖДЕНИЯ фрактала —
    раньше его нельзя знать). LL→LONG, HH→SHORT.
      entry = close[i+N]
      SL    = low[i] - depth (LONG) / high[i] + depth (SHORT), depth=15% диапазона i
      risk  = |entry - SL|;  TP = entry ± risk*2.2
    fvg_tf='12h' → fill-scan стартует через 12h (после закрытия entry-свечи i+N).
    """
    H = df_12h["high"].values; L = df_12h["low"].values; C = df_12h["close"].values
    idx = df_12h.index
    sigs = []
    N = FRACTAL_N
    for i in range(N, len(df_12h) - N):
        is_fl = L[i] < L[i-N:i].min() and L[i] < L[i+1:i+1+N].min()
        is_fh = H[i] > H[i-N:i].max() and H[i] > H[i+1:i+1+N].max()
        if not (is_fl or is_fh):
            continue
        conf = i + N                       # бар подтверждения
        entry_time = idx[conf]             # open-time свечи подтверждения
        entry = C[conf]                    # вход на её close
        rng = H[i] - L[i]
        depth = rng * FRACTAL_SL_DEPTH
        if is_fl:
            direction = "LONG"; sl = L[i] - depth
        else:
            direction = "SHORT"; sl = H[i] + depth
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        sigs.append({
            "strategy_id": 3, "direction": direction,
            "signal_time": entry_time, "entry": float(entry), "sl": float(sl),
            "risk": float(risk), "fvg_tf": "12h",   # fill-scan через 12h после open
        })
    return sigs


def gen_signals_for_symbol(sym, asset_id):
    df_1d = load_df(sym, "1d"); df_12h = load_df(sym, "12h")
    df_4h = load_df(sym, "4h"); df_1h = load_df(sym, "1h")
    df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(sym, "15m"); df_1m = load_df(sym, "1m")
    if df_1m.empty:
        print(f"  [{sym}] нет 1m — пропуск", flush=True); return None
    df_20m = compose_from_base(df_1m, "20m")

    s111 = detect_strategy_1_1_1_signals(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    for s in s111: s["strategy_id"] = 0
    s112 = detect_strategy_1_1_2_signals(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    for s in s112: s["strategy_id"] = 1
    s113 = detect_strategy_1_1_3_signals(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h)
    for s in s113: s["strategy_id"] = 2
    sfr = gen_fractal_signals(df_12h)      # ← НОВОЕ: фракталы Андрея (strategy_id=3)
    alls = s111 + s112 + s113 + sfr
    print(f"  [{sym}] 1.1.1={len(s111)} 1.1.2={len(s112)} 1.1.3={len(s113)} FRACTAL={len(sfr)}", flush=True)

    seen, uniq = set(), []
    for s in alls:
        key = (s["strategy_id"], str(s["signal_time"]), s["direction"], round(s["entry"], 2))
        if key in seen: continue
        seen.add(key); uniq.append(s)

    rows = []
    for s in uniq:
        out = _e178.achieved_r_outcome(s, df_1m)
        if out is None: continue
        rows.append({
            "signal_time": pd.Timestamp(s["signal_time"]), "asset_id": asset_id, "symbol": sym,
            "strategy_id": s["strategy_id"], "direction_long": 1 if s["direction"] == "LONG" else 0,
            "entry": s["entry"], "sl": s["sl"], "risk": s["risk"],
            "risk_pct": abs(s["entry"] - s["sl"]) / s["entry"] * 100,
            "grade": out["grade"], "achieved_r": out["achieved_r"],
            "hit_tp": int(out["hit_tp"]), "hit_sl": int(out["hit_sl"]),
        })
    g = pd.DataFrame(rows)
    print(f"  [{sym}] graded {len(g)} | WR_TP={ (g['grade']>=4).mean()*100:.1f}%", flush=True)
    return g


def attach_features(graded, sym, asset_id):
    """Джойн арсенал-фич (по активу) к сигналам по asof signal_time (<= close 12h)."""
    feat_df = _e177.build_symbol(sym, asset_id).sort_index()
    feat_cols = [c for c in _e177.make_feature_list(list(_e177.BULK_ALL.keys())) if c in feat_df.columns]
    fc = (feat_df.index + pd.Timedelta("12h")).values
    rows = []
    for _, sig in graded.iterrows():
        st = np.datetime64(sig["signal_time"].tz_convert("UTC").tz_localize(None))
        pos = np.searchsorted(fc, st, side="right") - 1
        if pos < 0: continue
        frow = feat_df.iloc[pos]
        d = {c: frow[c] for c in feat_cols}
        d["sig_strategy_id"] = sig["strategy_id"]
        d["sig_direction_long"] = sig["direction_long"]
        d["sig_risk_pct"] = sig["risk_pct"]
        d["sig_asset_id"] = asset_id
        d["grade"] = int(sig["grade"]); d["achieved_r"] = float(sig["achieved_r"])
        d["hit_tp"] = int(sig["hit_tp"]); d["signal_time"] = sig["signal_time"]
        rows.append(d)
    out = pd.DataFrame(rows).set_index("signal_time").sort_index()
    feat_all = feat_cols + ["sig_strategy_id", "sig_direction_long", "sig_risk_pct", "sig_asset_id"]
    return out, feat_all


def mda_importance(net_fn, X, g, feats, device, n_repeat=3):
    """MDA (López de Prado Lec8): падение Spearman ρ при перестановке фичи.

    net_fn(Xmat) -> score. Возвращает список (фича, средн. падение ρ).
    """
    from scipy.stats import spearmanr
    base = spearmanr(g, net_fn(X)).correlation
    rng = np.random.RandomState(0)
    drops = []
    for j, fname in enumerate(feats):
        ds = []
        for _ in range(n_repeat):
            Xp = X.copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            r = spearmanr(g, net_fn(Xp)).correlation
            ds.append(base - (r if r is not None else 0))
        drops.append((fname, float(np.mean(ds))))
    drops.sort(key=lambda x: -x[1])
    return base, drops


def main():
    import torch
    from sklearn.preprocessing import StandardScaler
    from scipy.stats import spearmanr
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_179] device={device} | 3 актива pooled + MDA", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    parts = []
    for aid, sym in enumerate(SYMBOLS):
        print(f"[gen] {sym}...", flush=True)
        g = gen_signals_for_symbol(sym, aid)
        if g is None or g.empty: continue
        fdf, feats = attach_features(g, sym, aid)
        parts.append(fdf)
    if not parts:
        print("[ERR] нет данных"); return
    ds = pd.concat(parts).sort_index()
    ds = ds[ds[feats].notna().all(axis=1)]
    ds.to_csv(OUT_DIR / "etap179_graded_3assets.csv")
    print(f"\n[data] {len(ds)} сигналов (3 актива), фич={len(feats)}", flush=True)
    print("[grade dist]\n" + ds["grade"].value_counts().sort_index().to_string(), flush=True)
    print(f"  WR по TP=2.2R (grade>=4): {(ds['grade']>=4).mean()*100:.1f}%", flush=True)

    tr = ds[ds.index < TRAIN_END]; emb = TRAIN_END + pd.Timedelta("12h") * EMBARGO_BARS
    te = ds[ds.index >= emb]
    print(f"[split] train={len(tr)} test={len(te)}", flush=True)
    if len(tr) < 200 or len(te) < 50:
        print("[ERR] мало"); return
    gtr = tr["grade"].values.astype(float); gte = te["grade"].values.astype(float)

    w = _e177.uniqueness_weights(tr.index, 7)
    Xte_raw = te[feats].values
    preds, rhos, nets_scalers = [], [], []
    for fi, (tri, vai) in enumerate(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7)):
        sc = StandardScaler().fit(tr[feats].values[tri])
        net, vr = _e178.train_ordinal(sc.transform(tr[feats].values[tri]), gtr[tri], w[tri],
                                      sc.transform(tr[feats].values[vai]), gtr[vai], len(feats), device=device)
        rhos.append(vr); preds.append(_e178.ordinal_predict_score(net, sc.transform(Xte_raw), device))
        nets_scalers.append((net, sc))
        print(f"    fold {fi}: val ρ={vr:.4f}", flush=True)
    score = np.mean(preds, axis=0)
    rho_te = spearmanr(gte, score).correlation
    print(f"\n[ORDINAL NN 3-asset] CV ρ={np.mean(rhos):.4f} | TEST ρ={rho_te:.4f}", flush=True)

    te2 = te.copy(); te2["score"] = score
    te2["pred_grade"] = np.clip(np.round(score), 1, 5).astype(int)
    base_tp = (te2["grade"] >= 4).mean()
    print("\n[реальный WR_TP по предсказанному классу]:", flush=True)
    for pg in [1, 2, 3, 4, 5]:
        sub = te2[te2["pred_grade"] == pg]
        if len(sub) >= 3:
            print(f"  pred={pg}: n={len(sub):4d}  WR_TP={ (sub['grade']>=4).mean()*100:.0f}%  "
                  f"mean_R={sub['achieved_r'].mean():.2f}", flush=True)
    for thr in [3.0, 3.5, 4.0]:
        top = te2[te2["score"] >= thr]
        if len(top) >= 5:
            wr = (top["grade"] >= 4).mean()
            print(f"  [TOP score>={thr}] n={len(top)}  WR_TP={wr*100:.0f}% "
                  f"(baseline {base_tp*100:.0f}%, lift ×{wr/base_tp:.2f})", flush=True)

    # SANITY shuffle
    rng = np.random.RandomState(0); gsh = gtr.copy(); rng.shuffle(gsh)
    tri, vai = next(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7))
    sc = StandardScaler().fit(tr[feats].values[tri])
    net_sh, _ = _e178.train_ordinal(sc.transform(tr[feats].values[tri]), gsh[tri], w[tri],
                                    sc.transform(tr[feats].values[vai]), gsh[vai], len(feats), epochs=60, device=device)
    sh = spearmanr(gte, _e178.ordinal_predict_score(net_sh, sc.transform(Xte_raw), device)).correlation
    print(f"\n[SANITY] shuffle-grade ρ={sh:.4f} (должен быть ~0)", flush=True)

    # MDA importance (на лучшем фолде по val ρ)
    print("\n[MDA] feature importance (падение ρ при перестановке)...", flush=True)
    best_fi = int(np.argmax(rhos))
    net_b, sc_b = nets_scalers[best_fi]
    Xte_sc = sc_b.transform(Xte_raw)
    net_fn = lambda Xm: _e178.ordinal_predict_score(net_b, Xm, device)
    base_rho, drops = mda_importance(net_fn, Xte_sc, gte, feats, device, n_repeat=3)
    print(f"  base test ρ (этот фолд) = {base_rho:.4f}", flush=True)
    print("  TOP-15 фич по важности (drop ρ):", flush=True)
    for fname, dd in drops[:15]:
        print(f"    {fname:32s} {dd:+.4f}", flush=True)
    pd.DataFrame(drops, columns=["feature", "mda_drop"]).to_csv(OUT_DIR / "etap179_mda.csv", index=False)


if __name__ == "__main__":
    main()
