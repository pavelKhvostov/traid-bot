"""etap_181: Анти-overfit по методологии Goodfellow (гл.11+7). Лечим переобучение.

ДИАГНОЗ (Goodfellow гл.11.3, применён к etap_180):
  TRAIN ρ = 0.77, TEST ρ = 0.09 → ОГРОМНЫЙ gap → СИЛЬНЫЙ OVERFIT (не underfit!).
  Сеть запоминает шум train. По Goodfellow: НЕ увеличивать модель, а
  РЕГУЛЯРИЗОВАТЬ сильнее + меньше фич + больше данных.

ЛЕЧЕНИЕ (Goodfellow гл.7 Regularization + гл.11):
  1. МЕНЬШЕ модель: hidden 64 (было 128), 1 residual-блок (было 2-3).
  2. СИЛЬНЕЕ dropout: 0.5 (было 0.3-0.35). [гл.7.12]
  3. БОЛЬШЕ weight decay: 4e-2 (было 1e-2). [гл.7.1 L2]
  4. УРЕЗАТЬ фичи: топ-20 MDA + знаниевые why (107→~30, меньше для запоминания).
  5. NOISE INJECTION в train (dataset augmentation/noise robustness). [гл.7.4-7.5]
  6. Баланс 50/50 + early-stopping (есть).

ЦЕЛЬ: уменьшить gap train-test, поднять TEST ρ. Если не растёт → Bayes error
(исход сделки = шум после входа), честный потолок.

Источники сигналов/метка/датасет — из etap_179/180.
Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/etap_181_antioverfit_goodfellow.py
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

_s180 = _ilu.spec_from_file_location("e180", _ROOT / "research/elements_study/etap_180_signal_grade_knowledge_features.py")
_e180 = _ilu.module_from_spec(_s180); _s180.loader.exec_module(_e180)
_e179 = _e180._e179; _e178 = _e180._e178; _e177 = _e180._e177

TRAIN_END = _e179.TRAIN_END
EMBARGO_BARS = _e179.EMBARGO_BARS
KFOLD = _e179.KFOLD
EMBARGO_KF = _e179.EMBARGO_KF
OUT_DIR = _e179.OUT_DIR
SEED = 42

# анти-overfit гиперпараметры (Goodfellow)
HIDDEN = 64           # было 128
DROPOUT = 0.5         # было 0.35
WEIGHT_DECAY = 4e-2   # было 1e-2
NOISE_STD = 0.1       # noise injection в фичи (augmentation)
EPOCHS = 300
PATIENCE = 30
N_TOP_MDA = 20        # топ фич по важности

# топ-20 MDA фич (из etap179_mda.csv) + знаниевые why (дёшевы, осмысленны)
TOP_MDA = [
    "sig_direction_long", "bars_since_ll", "dist_hh30_pct", "bulk_hs_top_bars_since",
    "hull_dist_pct", "sweep_SSL_72h", "dist_ll30_pct", "n_SHORT_OB", "trend_4h",
    "is_green", "bulk_big_m_bars_since", "bulk_db_eve_eve_bars_since", "in_LONG_FVG",
    "bulk_v_top_fired", "sig_risk_pct", "bulk_barr_bottom_bars_since", "n_SHORT_FVG",
    "entropy", "lower_than_prev2", "sig_asset_id",
]


# ---- маленькая сильно-регуляризованная ординальная сеть ----
def build_small_net(in_dim, n_classes=5):
    import torch
    import torch.nn as nn

    class SmallOrdinal(nn.Module):
        def __init__(self, in_dim, hidden=HIDDEN, p=DROPOUT, K=5):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(in_dim, hidden), nn.BatchNorm1d(hidden), nn.GELU(), nn.Dropout(p),
                nn.Linear(hidden, hidden), nn.BatchNorm1d(hidden), nn.GELU(), nn.Dropout(p),
            )
            self.shared = nn.Linear(hidden, 1, bias=False)
            self.bias = nn.Parameter(torch.zeros(K - 1))

        def forward(self, x):
            h = self.net(x)
            return self.shared(h) + self.bias

    return SmallOrdinal(in_dim)


def train_regularized(Xtr, gtr, wtr, Xval, gval, in_dim, device):
    """Обучение с noise injection (augmentation) + сильная регуляризация."""
    import torch
    from torch.utils.data import TensorDataset, DataLoader
    from scipy.stats import spearmanr
    torch.manual_seed(SEED)
    net = build_small_net(in_dim).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=WEIGHT_DECAY)
    ds = TensorDataset(torch.tensor(Xtr, dtype=torch.float32),
                       torch.tensor(gtr, dtype=torch.float32),
                       torch.tensor(wtr, dtype=torch.float32))
    dl = DataLoader(ds, batch_size=256, shuffle=True, drop_last=True)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, epochs=EPOCHS, steps_per_epoch=max(1, len(dl)))
    Xval_t = torch.tensor(Xval, dtype=torch.float32, device=device)
    best, best_state, bad = -1, None, 0
    for ep in range(EPOCHS):
        net.train()
        for xb, gb, wb in dl:
            xb, gb, wb = xb.to(device), gb.to(device), wb.to(device)
            # NOISE INJECTION (Goodfellow гл.7.4-7.5 dataset augmentation)
            xb = xb + torch.randn_like(xb) * NOISE_STD
            opt.zero_grad()
            loss = _e178.coral_loss(net(xb), gb, wb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step(); sched.step()
        net.eval()
        with torch.no_grad():
            sc = _e178.ordinal_predict_score(net, Xval, device)
        rho = spearmanr(gval, sc).correlation if len(np.unique(gval)) > 1 else 0
        if rho is not None and rho > best:
            best, best_state, bad = rho, {k: v.cpu().clone() for k, v in net.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= PATIENCE:
                break
    if best_state:
        net.load_state_dict(best_state)
    return net, best


def main():
    import torch
    from sklearn.preprocessing import StandardScaler
    from scipy.stats import spearmanr
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_181] device={device} | АНТИ-OVERFIT (Goodfellow): hidden={HIDDEN} "
          f"drop={DROPOUT} wd={WEIGHT_DECAY} noise={NOISE_STD} top{N_TOP_MDA}фич", flush=True)

    cache = OUT_DIR / "etap179_graded_3assets.csv"
    if not cache.exists():
        print("[ERR] нет датасета etap179"); return
    ds = pd.read_csv(cache, index_col="signal_time", parse_dates=["signal_time"])
    ds, why_feats = _e180.add_knowledge_features(ds)

    # урезанный набор: топ-20 MDA + знаниевые why (Goodfellow: меньше фич против overfit)
    feats = [f for f in TOP_MDA if f in ds.columns] + [f for f in why_feats if f in ds.columns]
    feats = list(dict.fromkeys(feats))  # дедуп, сохраняя порядок
    ds = ds[ds[feats].notna().all(axis=1)]
    print(f"[data] {len(ds)} сигналов | фич={len(feats)} (было 107 → урезано против overfit)", flush=True)

    tr = ds[ds.index < TRAIN_END]; emb = TRAIN_END + pd.Timedelta("12h") * EMBARGO_BARS
    te = ds[ds.index >= emb]
    gtr = tr["grade"].values.astype(float); gte = te["grade"].values.astype(float)
    print(f"[split] train={len(tr)} test={len(te)}", flush=True)

    uw = _e177.uniqueness_weights(tr.index, 7)
    w = _e180.balanced_weights(gtr, uw)

    Xte_raw = te[feats].values
    preds, rhos, train_rhos, nets_scalers = [], [], [], []
    for fi, (tri, vai) in enumerate(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7)):
        sc = StandardScaler().fit(tr[feats].values[tri])
        Xtr = sc.transform(tr[feats].values[tri])
        net, vr = train_regularized(Xtr, gtr[tri], w[tri],
                                    sc.transform(tr[feats].values[vai]), gtr[vai], len(feats), device)
        # train ρ для контроля gap (overfit?)
        tr_rho = spearmanr(gtr[tri], _e178.ordinal_predict_score(net, Xtr, device)).correlation
        train_rhos.append(tr_rho)
        rhos.append(vr); preds.append(_e178.ordinal_predict_score(net, sc.transform(Xte_raw), device))
        nets_scalers.append((net, sc))
        print(f"    fold {fi}: TRAIN ρ={tr_rho:.3f} val ρ={vr:.3f} (gap={tr_rho-vr:.3f})", flush=True)
    score = np.mean(preds, axis=0)
    rho_te = spearmanr(gte, score).correlation
    mean_train = np.mean(train_rhos)
    print(f"\n[ANTI-OVERFIT NN] TRAIN ρ={mean_train:.3f} | CV ρ={np.mean(rhos):.3f} | TEST ρ={rho_te:.3f}", flush=True)
    print(f"  gap TRAIN-TEST: {mean_train-rho_te:.3f} (было etap_180: 0.77-0.09=0.68 — overfit)", flush=True)
    print(f"  было etap_180: TEST ρ 0.090", flush=True)

    te2 = te.copy(); te2["score"] = score
    te2["pred_grade"] = np.clip(np.round(score), 1, 5).astype(int)
    base_tp = (te2["grade"] >= 4).mean()
    print("\n[реальный WR_TP по предсказанному классу]:", flush=True)
    for pg in [1, 2, 3, 4, 5]:
        sub = te2[te2["pred_grade"] == pg]
        if len(sub) >= 3:
            print(f"  pred={pg}: n={len(sub):4d}  WR_TP={(sub['grade']>=4).mean()*100:.0f}%  "
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
    net_sh, _ = train_regularized(sc.transform(tr[feats].values[tri]), gsh[tri], w[tri],
                                  sc.transform(tr[feats].values[vai]), gsh[vai], len(feats), device)
    sh = spearmanr(gte, _e178.ordinal_predict_score(net_sh, sc.transform(Xte_raw), device)).correlation
    print(f"\n[SANITY] shuffle ρ={sh:.4f} (должен ~0)", flush=True)

    # сохранить если лучше etap_180 (ρ > 0.090)
    if rho_te > 0.090:
        import json as _json
        md = OUT_DIR / "etap179_model"; md.mkdir(parents=True, exist_ok=True)
        # ВНИМАНИЕ: сеть другой архитектуры (build_small_net) — live-инференс грузит
        # через _e178.build_ordinal_net. Сохраняем в ОТДЕЛЬНУЮ папку чтобы не сломать бота.
        md2 = OUT_DIR / "etap181_model"; md2.mkdir(parents=True, exist_ok=True)
        for fi, (net, sc) in enumerate(nets_scalers):
            torch.save(net.state_dict(), md2 / f"net_fold{fi}.pt")
            np.savez(md2 / f"scaler_fold{fi}.npz", mean=sc.mean_, scale=sc.scale_)
        (md2 / "meta.json").write_text(_json.dumps({
            "feats": feats, "n_folds": len(nets_scalers), "in_dim": len(feats),
            "cv_rho": float(np.mean(rhos)), "test_rho": float(rho_te),
            "trained": "etap_181_antioverfit", "arch": "small", "target_rr": 2.2,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[saved] ЛУЧШЕ etap_180 (ρ {rho_te:.3f} > 0.090) → etap181_model/ "
              f"(нужно обновить live-инференс под small-арх)", flush=True)
    else:
        print(f"[вывод] ρ {rho_te:.3f}. Если ≈0.09 — регуляризация не помогла "
              f"= упёрлись в Bayes error (исход сделки = шум). Честный потолок.", flush=True)


if __name__ == "__main__":
    main()
