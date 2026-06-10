"""etap_176: Нейросеть для предсказания хорошего фрактала-разворота (ветка pavel).

Полноценная нейросеть (PyTorch, не sklearn-MLP), обученная по стандартам
López de Prado «Advances in Financial ML» + на эталонных фичах Андрея
(sweep/DOL = ICT Liquidity Sweep, зоны, Bulkowski) + фракталы.

=== СТАНДАРТЫ ИЗ КНИГ (применены) ===
López de Prado (AFML):
  - Triple-barrier labeling = наша метка 5%-race (TP +5% / SL снятие экстремума /
    timeout 30д). Lec 3.
  - Purged K-Fold + Embargo: train/test не пересекаются по времени меток,
    embargo выкидывает бары на стыке (serial correlation). Lec 4.
  - Sample weights по uniqueness: перекрывающиеся по времени метки весят меньше
    (concurrency). Lec 4. Здесь — вес ∝ 1/avg_concurrency на горизонте метки.
  - Feature importance через MDA (перестановочная) — приложение после обучения.
  - НЕ backtest до завершения research; sanity shuffle-label тест (Lec 5).

Эталон Андрея (= канон ICT из PDF, к которому он пришёл эмпирически):
  - sweep_SSL/BSL_mag/failed (ICT Liquidity Sweep / DOL — топ-importance),
  - OB/FVG зоны-дистанции, Bulkowski top-5 fires, фрактал-структура.
  (фичи берём из готового датасета etap_175.)

Нейросеть (стандарты DL для табличных фин-данных):
  - MLP с BatchNorm + Dropout + skip-connection (не голый Linear).
  - Focal loss (дисбаланс ~20% положительных) вместо BCE.
  - AdamW + weight decay (L2), OneCycle LR, early-stopping по val-AUC.
  - StandardScaler по TRAIN-статистике (нет утечки из test).
  - MPS (Mac M5 GPU) если доступен.
  - НО держим в уме: López de Prado предупреждал — на табличных фин-фичах
    NN часто хуже GBM. Поэтому честно сравниваем с LightGBM-эталоном.

ЗАЩИТА ОТ LOOKAHEAD (known-pitfalls, как в etap_174/175):
  - все фичи <= close[i] (датасет etap_175 это гарантирует),
  - метка по будущим 1h, sanity shuffle-AUC ~0.5,
  - Purged split по времени + embargo.

Запуск: .venv-pivot/bin/python research/elements_study/etap_176_neural_fractal_pavel.py
Требует: датасет etap175_dataset.csv (создаётся etap_175). Если нет — собрать etap_175.
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

import numpy as np
import pandas as pd

OUT_DIR = _ROOT / "research" / "elements_study" / "output"
DATASET = OUT_DIR / "etap175_dataset.csv"

TF = "12h"
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
EMBARGO_BARS = 3            # N+1 (Williams N=2) на стыке train/test
KFOLD = 5
EMBARGO_KF = 14            # эмбарго внутри Purged K-Fold (бары)
MAX_RACE_DAYS = 30
SEED = 42

# Фичи: эталон Андрея (sweep/DOL + зоны + Bulkowski) + база. Имена из etap_175.
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
ZONE_FEATS = []
for d in ("LONG", "SHORT"):
    for t in ("OB", "FVG"):
        ZONE_FEATS += [f"dist_{d}_{t}_pct", f"n_{d}_{t}", f"in_{d}_{t}"]
BULK_FEATS = []
for nm in ("big_w", "db_eve_eve", "v_bottom", "hs_bottom", "big_m"):
    BULK_FEATS += [f"bulk_{nm}_fired", f"bulk_{nm}_bars_since"]
ALL_FEATS = BASE_FEATS + SWEEP_FEATS + ZONE_FEATS + BULK_FEATS


# ============================================================
# Sample weights по uniqueness (López de Prado Lec 4)
# ============================================================
def uniqueness_weights(index: pd.DatetimeIndex, horizon_days: int) -> np.ndarray:
    """Вес метки ∝ 1 / средняя concurrency на её горизонте.

    Метка свечи i живёт [t_i, t_i + horizon]. Concurrency в момент t =
    число активных меток. Вес = 1/avg_concurrency по горизонту метки.
    Перекрывающиеся метки (serial correlation) весят меньше → честнее.
    """
    t = index.values.astype("datetime64[ns]")
    h = np.timedelta64(horizon_days, "D")
    n = len(t)
    end = t + h
    # concurrency через события (start +1, end -1) — O(n log n)
    starts = np.sort(t)
    ends = np.sort(end)
    # для каждой метки: усреднить число активных за её жизнь (приближённо —
    # по числу стартов в окне [t_i, end_i] минус завершившихся)
    w = np.zeros(n)
    si = 0
    ei = 0
    # быстрый вариант: для метки i concurrency ~ (#стартов <= end_i) - (#концов < t_i)
    starts_sorted = starts
    ends_sorted = ends
    for i in range(n):
        active_started = np.searchsorted(starts_sorted, end[i], side="right")
        active_ended = np.searchsorted(ends_sorted, t[i], side="left")
        conc = max(1, active_started - active_ended)
        w[i] = 1.0 / conc
    # нормируем к среднему 1
    w = w / w.mean()
    return w


# ============================================================
# Purged K-Fold (López de Prado Lec 4)
# ============================================================
def purged_kfold_splits(index: pd.DatetimeIndex, n_splits=5, embargo=14,
                        horizon_days=30):
    """Генерит (train_idx, val_idx) с purging+embargo по ВРЕМЕНИ.

    Метка живёт horizon_days. Из train выкидываем все метки, чьи горизонты
    пересекаются с val-периодом (purge), плюс embargo баров после val.
    """
    n = len(index)
    fold_bounds = np.linspace(0, n, n_splits + 1).astype(int)
    t = index.values.astype("datetime64[ns]")
    h = np.timedelta64(horizon_days, "D")
    for k in range(n_splits):
        v0, v1 = fold_bounds[k], fold_bounds[k + 1]
        val_idx = np.arange(v0, v1)
        if len(val_idx) == 0:
            continue
        val_start = t[v0]
        val_end = t[v1 - 1] + h           # val-метки живут до сюда
        emb = np.timedelta64(embargo, "D") if False else embargo
        # train = всё, чья метка НЕ пересекает [val_start, val_end] + embargo баров
        train_mask = np.ones(n, dtype=bool)
        train_mask[val_idx] = False
        label_end = t + h
        overlap = (label_end >= val_start) & (t <= val_end)
        train_mask &= ~overlap
        # embargo: выкинуть `embargo` баров сразу после val-блока
        emb_hi = min(n, v1 + embargo)
        train_mask[v1:emb_hi] = False
        train_idx = np.where(train_mask)[0]
        if len(train_idx) > 50 and len(val_idx) > 10:
            yield train_idx, val_idx


# ============================================================
# Нейросеть (PyTorch)
# ============================================================
def build_net(in_dim):
    import torch.nn as nn

    class ResBlock(nn.Module):
        def __init__(self, dim, p):
            super().__init__()
            self.fc = nn.Linear(dim, dim)
            self.bn = nn.BatchNorm1d(dim)
            self.act = nn.GELU()
            self.drop = nn.Dropout(p)

        def forward(self, x):
            return x + self.drop(self.act(self.bn(self.fc(x))))

    class Net(nn.Module):
        def __init__(self, in_dim, hidden=128, p=0.3):
            super().__init__()
            self.inp = nn.Sequential(
                nn.Linear(in_dim, hidden), nn.BatchNorm1d(hidden), nn.GELU(), nn.Dropout(p))
            self.b1 = ResBlock(hidden, p)
            self.b2 = ResBlock(hidden, p)
            self.head = nn.Sequential(
                nn.Linear(hidden, hidden // 2), nn.GELU(), nn.Dropout(p),
                nn.Linear(hidden // 2, 1))

        def forward(self, x):
            x = self.inp(x)
            x = self.b1(x)
            x = self.b2(x)
            return self.head(x).squeeze(-1)

    return Net(in_dim)


def focal_loss(logits, targets, weights, alpha=0.7, gamma=2.0):
    """Focal loss с sample-weights (дисбаланс классов + uniqueness)."""
    import torch
    import torch.nn.functional as F
    bce = F.binary_cross_entropy_with_logits(logits, targets, reduction="none")
    p = torch.sigmoid(logits)
    pt = torch.where(targets == 1, p, 1 - p)
    a = torch.where(targets == 1, alpha, 1 - alpha)
    fl = a * (1 - pt) ** gamma * bce
    return (fl * weights).mean()


def train_net(Xtr, ytr, wtr, Xval, yval, in_dim, epochs=120, device="cpu"):
    import torch
    from torch.utils.data import TensorDataset, DataLoader
    from sklearn.metrics import roc_auc_score

    torch.manual_seed(SEED)
    net = build_net(in_dim).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    ds = TensorDataset(
        torch.tensor(Xtr, dtype=torch.float32),
        torch.tensor(ytr, dtype=torch.float32),
        torch.tensor(wtr, dtype=torch.float32))
    dl = DataLoader(ds, batch_size=256, shuffle=True, drop_last=True)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=2e-3, epochs=epochs, steps_per_epoch=max(1, len(dl)))

    Xval_t = torch.tensor(Xval, dtype=torch.float32, device=device)
    best_auc, best_state, patience, bad = 0.0, None, 18, 0
    for ep in range(epochs):
        net.train()
        for xb, yb, wb in dl:
            xb, yb, wb = xb.to(device), yb.to(device), wb.to(device)
            opt.zero_grad()
            loss = focal_loss(net(xb), yb, wb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
            sched.step()
        net.eval()
        with torch.no_grad():
            pv = torch.sigmoid(net(Xval_t)).cpu().numpy()
        auc = roc_auc_score(yval, pv) if len(np.unique(yval)) > 1 else 0.5
        if auc > best_auc:
            best_auc, best_state, bad = auc, {k: v.cpu().clone() for k, v in net.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    return net, best_auc


def predict_net(net, X, device="cpu"):
    import torch
    net.eval()
    with torch.no_grad():
        return torch.sigmoid(net(torch.tensor(X, dtype=torch.float32, device=device))).cpu().numpy()


# ============================================================
# Оценка
# ============================================================
def eval_bins(proba, yte, base):
    from sklearn.metrics import roc_auc_score, precision_score, recall_score
    auc = roc_auc_score(yte, proba) if len(np.unique(yte)) > 1 else float("nan")
    bins = []
    for thr in [0.5, 0.6, 0.7, 0.8]:
        sel = proba >= thr
        if sel.sum() >= 5:
            p = precision_score(yte, sel, zero_division=0)
            r = recall_score(yte, sel, zero_division=0)
            bins.append((thr, int(sel.sum()), round(p, 3), round(r, 3),
                         round(p / base, 2) if base > 0 else 0))
    return auc, bins


def run_target(ds, target, label, device):
    import torch
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    d = ds.dropna(subset=[target]).copy()
    d = d[d[ALL_FEATS].notna().all(axis=1)].sort_index()
    tr_all = d[d.index < TRAIN_END]
    emb = TRAIN_END + pd.Timedelta(TF) * EMBARGO_BARS
    te = d[d.index >= emb]
    if len(tr_all) < 200 or len(te) < 30:
        print(f"  [{label}] too few tr={len(tr_all)} te={len(te)}"); return

    y_all = tr_all[target].astype(int).values
    base_te = te[target].astype(int).mean()
    print(f"\n========== {label} ==========")
    print(f"  train={len(tr_all)} test={len(te)} base_test={base_te*100:.2f}% feats={len(ALL_FEATS)}")

    # sample weights (uniqueness)
    w_all = uniqueness_weights(tr_all.index, MAX_RACE_DAYS)

    # --- Purged K-Fold обучение нейросети (out-of-fold предсказание на test ансамблем) ---
    test_preds_nn = []
    cv_aucs = []
    Xtest_raw = te[ALL_FEATS].values
    for fi, (tri, vai) in enumerate(purged_kfold_splits(tr_all.index, KFOLD, EMBARGO_KF, MAX_RACE_DAYS)):
        Xtr_raw = tr_all[ALL_FEATS].values[tri]
        Xval_raw = tr_all[ALL_FEATS].values[vai]
        sc = StandardScaler().fit(Xtr_raw)
        Xtr = sc.transform(Xtr_raw); Xval = sc.transform(Xval_raw)
        Xtest = sc.transform(Xtest_raw)
        ytr, yval = y_all[tri], y_all[vai]
        wtr = w_all[tri]
        net, vauc = train_net(Xtr, ytr, wtr, Xval, yval, len(ALL_FEATS),
                              device=device)
        cv_aucs.append(vauc)
        test_preds_nn.append(predict_net(net, Xtest, device))
        print(f"    fold {fi}: val-AUC={vauc:.4f} (train {len(tri)}, val {len(vai)})")
    if not test_preds_nn:
        print("  no folds"); return
    proba_nn = np.mean(test_preds_nn, axis=0)
    yte = te[target].astype(int).values
    auc_nn, bins_nn = eval_bins(proba_nn, yte, base_te)
    print(f"  [NEURAL ensemble] Purged-CV mean val-AUC={np.mean(cv_aucs):.4f} | TEST AUC={auc_nn:.4f}")
    for b in bins_nn:
        print(f"     thr>={b[0]}: n={b[1]:4d} prec={b[2]:.3f} rec={b[3]:.3f} lift=×{b[4]}")

    # NB: LightGBM-эталон считается ОТДЕЛЬНЫМ процессом (etap_175) — libomp от
    # LightGBM конфликтует с PyTorch MPS threadpool в одном процессе (зависание).
    # Сохраняем NN-вероятности на диск для последующего сравнения/ансамбля.
    np.save(OUT_DIR / f"etap176_nn_proba_{target}.npy", proba_nn)
    np.save(OUT_DIR / f"etap176_nn_ytest_{target}.npy", yte)
    auc_g = float("nan"); auc_e = float("nan")

    # --- SANITY shuffle (на NN, 1 fold) ---
    rng = np.random.RandomState(0)
    where = purged_kfold_splits(tr_all.index, KFOLD, EMBARGO_KF, MAX_RACE_DAYS)
    tri, vai = next(where)
    sc = StandardScaler().fit(tr_all[ALL_FEATS].values[tri])
    ysh = y_all[tri].copy(); rng.shuffle(ysh)
    net_sh, _ = train_net(sc.transform(tr_all[ALL_FEATS].values[tri]), ysh, w_all[tri],
                          sc.transform(tr_all[ALL_FEATS].values[vai]), y_all[vai],
                          len(ALL_FEATS), epochs=60, device=device)
    auc_sh = roc_auc_score(yte, predict_net(net_sh, sc.transform(Xtest_raw), device)) if len(np.unique(yte)) > 1 else float("nan")
    print(f"  [SANITY] shuffle-label NN test-AUC={auc_sh:.4f} (должен быть ~0.5)")

    return {"target": label, "auc_nn": auc_nn,
            "cv_auc": float(np.mean(cv_aucs)), "shuffle_auc": auc_sh}


def main():
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_176] device={device}, torch={torch.__version__}")

    if not DATASET.exists():
        print(f"[ERR] нет датасета {DATASET}. Сначала запусти etap_175 (build).")
        return
    ds = pd.read_csv(DATASET, index_col="time", parse_dates=["time"])
    miss = [f for f in ALL_FEATS if f not in ds.columns]
    if miss:
        print(f"[ERR] нет колонок: {miss[:5]}... — пересобери etap_175"); return
    print(f"[data] {len(ds)} строк, {ds.index[0]} → {ds.index[-1]}")

    results = []
    for tgt, name in [("y_low_good", "LOW→+5% (LONG)"), ("y_high_good", "HIGH→-5% (SHORT)")]:
        r = run_target(ds, tgt, name, device)
        if r:
            results.append(r)

    print("\n===== СВОДКА (нейросеть) =====")
    for r in results:
        print(f"  {r['target']}: NN test-AUC={r['auc_nn']:.3f} | "
              f"Purged-CV val-AUC={r['cv_auc']:.3f} | shuffle={r['shuffle_auc']:.3f}")
    print("\n[ВАЖНО] shuffle-AUC>0.55 ИЛИ precision>0.6 на сотнях → проверять lookahead.")
    print("[NOTE] LightGBM-эталон — в etap_175 (отдельный процесс, конфликт libomp+MPS).")
    print("[NOTE] López de Prado: на табличных фин-фичах NN часто НЕ лучше GBM.")


if __name__ == "__main__":
    main()
