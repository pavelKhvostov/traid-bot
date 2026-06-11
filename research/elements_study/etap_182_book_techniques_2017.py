"""etap_182: Грамотное переобучение по УЧЕБНИКУ (синтез 3 DL-книг) на данных 2017+.

Применяет ЛУЧШИЕ непробованные техники из Goodfellow/Nielsen/Nikolenko против
overfit (наш train ρ 0.77 / test 0.09):
  1. LayerNorm вместо BatchNorm (Nikolenko: малые батчи → шумная BN).
  2. Feature-masking augmentation (обнулять 15% входов) + noise injection (Goodfellow 7.4-7.5).
  3. L1-penalty на входной слой = отбор шумовых фич (Nikolenko, Goodfellow 7.10).
  4. Label smoothing 0.05 (Goodfellow/Nikolenko против overconfidence).
  5. weight_decay БЕЗ bias/norm (Goodfellow 7.1, param groups).
  6. SWA/EMA усреднение весов (Goodfellow 8.7.3).
  7. СИЛЬНЫЙ BASELINE: LightGBM на тех же фичах (отдельный процесс — libomp+torch
     конфликт). Цель MLP — побить GBM. Если не бьёт — GBM лучше для табличных (книги).

ДАННЫЕ: 2017+ (BTC/ETH с 2017-08, SOL с 2020-08) — вдвое больше истории.
Метка/источники/Purged-K-Fold — из etap_178/179/180 (TP=2.2R, balanced, why-фичи).

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/etap_182_book_techniques_2017.py
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

TRAIN_END = pd.Timestamp("2024-06-01", tz="UTC")  # больше истории → сдвигаем train/test
EMBARGO_BARS = _e179.EMBARGO_BARS
KFOLD = _e179.KFOLD
EMBARGO_KF = _e179.EMBARGO_KF
OUT_DIR = _e179.OUT_DIR
SEED = 42

# гиперпараметры по учебнику (анти-overfit)
HIDDEN = 96
DROPOUT = 0.4
WEIGHT_DECAY = 3e-2
FEATURE_MASK_P = 0.15   # обнулять 15% входов (denoising augmentation)
NOISE_STD = 0.08
L1_INPUT = 1e-4         # L1 на входной слой
LABEL_SMOOTH = 0.05
EPOCHS = 350
PATIENCE = 35
SWA_START = 0.7         # SWA усреднять последние 30% эпох

DATASET_2017 = OUT_DIR / "etap182_graded_2017.csv"


# ---- сеть по учебнику: LayerNorm + L1-вход ----
def build_book_net(in_dim, n_classes=5):
    import torch
    import torch.nn as nn

    class BookOrdinal(nn.Module):
        def __init__(self, in_dim, hidden=HIDDEN, p=DROPOUT, K=5):
            super().__init__()
            self.input_layer = nn.Linear(in_dim, hidden)   # L1 будет на его weight
            self.body = nn.Sequential(
                nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(p),
                nn.Linear(hidden, hidden), nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(p),
            )
            self.shared = nn.Linear(hidden, 1, bias=False)
            self.bias = nn.Parameter(torch.zeros(K - 1))

        def forward(self, x):
            h = self.body(self.input_layer(x))
            return self.shared(h) + self.bias

    return BookOrdinal(in_dim)


def coral_loss_smooth(logits, grades, weights, smooth=LABEL_SMOOTH):
    """CORAL loss + label smoothing."""
    import torch
    import torch.nn.functional as F
    K1 = logits.shape[1]
    g = grades.unsqueeze(1)
    thr = torch.arange(1, K1 + 1, device=logits.device).unsqueeze(0)
    targets = (g > thr).float()
    # label smoothing: 1→1-s, 0→s
    targets = targets * (1 - smooth) + 0.5 * smooth
    loss = F.binary_cross_entropy_with_logits(logits, targets, reduction="none").mean(1)
    return (loss * weights).mean()


def train_book(Xtr, gtr, wtr, Xval, gval, in_dim, device):
    """Обучение со всеми техниками учебника."""
    import torch
    from torch.utils.data import TensorDataset, DataLoader
    from scipy.stats import spearmanr
    torch.manual_seed(SEED)
    net = build_book_net(in_dim).to(device)

    # weight_decay БЕЗ bias/norm (param groups, Goodfellow 7.1)
    decay, no_decay = [], []
    for name, p in net.named_parameters():
        if p.ndim == 1 or "bias" in name or "Norm" in name:
            no_decay.append(p)
        else:
            decay.append(p)
    opt = torch.optim.AdamW([
        {"params": decay, "weight_decay": WEIGHT_DECAY},
        {"params": no_decay, "weight_decay": 0.0},
    ], lr=2e-3)

    ds = TensorDataset(torch.tensor(Xtr, dtype=torch.float32),
                       torch.tensor(gtr, dtype=torch.float32),
                       torch.tensor(wtr, dtype=torch.float32))
    dl = DataLoader(ds, batch_size=256, shuffle=True, drop_last=True)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, epochs=EPOCHS, steps_per_epoch=max(1, len(dl)))
    Xval_t = torch.tensor(Xval, dtype=torch.float32, device=device)

    swa_weights, swa_n = None, 0
    best, best_state, bad = -1, None, 0
    for ep in range(EPOCHS):
        net.train()
        for xb, gb, wb in dl:
            xb, gb, wb = xb.to(device), gb.to(device), wb.to(device)
            # feature-masking augmentation (denoising) + noise injection
            mask = (torch.rand_like(xb) > FEATURE_MASK_P).float()
            xb = xb * mask + torch.randn_like(xb) * NOISE_STD
            opt.zero_grad()
            loss = coral_loss_smooth(net(xb), gb, wb)
            # L1 на входной слой (отбор фич)
            loss = loss + L1_INPUT * net.input_layer.weight.abs().sum()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step(); sched.step()
        # SWA: усреднять веса в последних эпохах
        if ep >= int(EPOCHS * SWA_START):
            sd = net.state_dict()
            if swa_weights is None:
                swa_weights = {k: v.clone().float() for k, v in sd.items()}; swa_n = 1
            else:
                for k in swa_weights:
                    swa_weights[k] = (swa_weights[k] * swa_n + sd[k].float()) / (swa_n + 1)
                swa_n += 1
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
    # выбрать SWA или best по val
    if swa_weights is not None:
        net.load_state_dict({k: v.to(device) for k, v in swa_weights.items()})
        with torch.no_grad():
            swa_rho = spearmanr(gval, _e178.ordinal_predict_score(net, Xval, device)).correlation
        if best_state is not None and (swa_rho is None or best > swa_rho):
            net.load_state_dict(best_state)
    elif best_state is not None:
        net.load_state_dict(best_state)
    return net, best


def build_dataset_2017():
    """Пересобрать датасет на расширенных данных 2017+."""
    if DATASET_2017.exists():
        print(f"[reuse] {DATASET_2017}", flush=True)
        return pd.read_csv(DATASET_2017, index_col="signal_time", parse_dates=["signal_time"])
    print("[build] датасет на 2017+ (детекция + исходы по 1m, ДОЛГО)...", flush=True)
    parts = []
    for aid, sym in enumerate(_e179.SYMBOLS):
        print(f"  [gen] {sym}...", flush=True)
        g = _e179.gen_signals_for_symbol(sym, aid)
        if g is None or g.empty:
            continue
        fdf, _ = _e179.attach_features(g, sym, aid)
        parts.append(fdf)
    ds = pd.concat(parts).sort_index()
    ds.to_csv(DATASET_2017)
    print(f"[saved] {DATASET_2017} ({len(ds)} сигналов)", flush=True)
    return ds


def main():
    import torch
    from sklearn.preprocessing import StandardScaler
    from scipy.stats import spearmanr
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_182] device={device} | техники учебника на данных 2017+", flush=True)

    ds = build_dataset_2017()
    ds, why = _e180.add_knowledge_features(ds)
    base = [c for c in _e177.make_feature_list(list(_e177.BULK_ALL.keys())) if c in ds.columns] \
           + ["sig_strategy_id", "sig_direction_long", "sig_risk_pct", "sig_asset_id"]
    feats = [f for f in base + why if f in ds.columns]
    feats = list(dict.fromkeys(feats))
    ds = ds[ds[feats].notna().all(axis=1)]
    print(f"[data] {len(ds)} сигналов (2017+) | фич={len(feats)} | период {ds.index[0]:%Y-%m} → {ds.index[-1]:%Y-%m}", flush=True)
    print(f"  было на 2022+: 5574 сигнала. Сейчас: {len(ds)} ({len(ds)/5574:.1f}×)", flush=True)

    tr = ds[ds.index < TRAIN_END]; emb = TRAIN_END + pd.Timedelta("12h") * EMBARGO_BARS
    te = ds[ds.index >= emb]
    gtr = tr["grade"].values.astype(float); gte = te["grade"].values.astype(float)
    print(f"[split] train={len(tr)} test={len(te)} (train_end={TRAIN_END:%Y-%m})", flush=True)

    uw = _e177.uniqueness_weights(tr.index, 7)
    w = _e180.balanced_weights(gtr, uw)

    Xte_raw = te[feats].values
    preds, rhos, train_rhos, nets_scalers = [], [], [], []
    for fi, (tri, vai) in enumerate(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7)):
        sc = StandardScaler().fit(tr[feats].values[tri])
        Xtr = sc.transform(tr[feats].values[tri])
        net, vr = train_book(Xtr, gtr[tri], w[tri], sc.transform(tr[feats].values[vai]), gtr[vai], len(feats), device)
        tr_rho = spearmanr(gtr[tri], _e178.ordinal_predict_score(net, Xtr, device)).correlation
        train_rhos.append(tr_rho); rhos.append(vr)
        preds.append(_e178.ordinal_predict_score(net, sc.transform(Xte_raw), device))
        nets_scalers.append((net, sc))
        print(f"    fold {fi}: TRAIN ρ={tr_rho:.3f} val ρ={vr:.3f} (gap={tr_rho-vr:.3f})", flush=True)
    score = np.mean(preds, axis=0)
    rho_te = spearmanr(gte, score).correlation
    print(f"\n[BOOK-NN 2017+] TRAIN ρ={np.mean(train_rhos):.3f} | CV ρ={np.mean(rhos):.3f} | TEST ρ={rho_te:.3f}", flush=True)
    print(f"  gap TRAIN-TEST={np.mean(train_rhos)-rho_te:.3f} (было etap_180: 0.68 overfit)", flush=True)
    print(f"  было etap_180 (2022, BN, без техник): TEST ρ 0.090", flush=True)

    te2 = te.copy(); te2["score"] = score
    base_tp = (te2["grade"] >= 4).mean()
    for thr in [3.0, 3.5, 4.0]:
        top = te2[te2["score"] >= thr]
        if len(top) >= 5:
            wr = (top["grade"] >= 4).mean()
            print(f"  [TOP score>={thr}] n={len(top)} WR_TP={wr*100:.0f}% (base {base_tp*100:.0f}%, ×{wr/base_tp:.2f})", flush=True)

    # SANITY shuffle
    rng = np.random.RandomState(0); gsh = gtr.copy(); rng.shuffle(gsh)
    tri, vai = next(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7))
    sc = StandardScaler().fit(tr[feats].values[tri])
    net_sh, _ = train_book(sc.transform(tr[feats].values[tri]), gsh[tri], w[tri],
                           sc.transform(tr[feats].values[vai]), gsh[vai], len(feats), device)
    sh = spearmanr(gte, _e178.ordinal_predict_score(net_sh, sc.transform(Xte_raw), device)).correlation
    print(f"\n[SANITY] shuffle ρ={sh:.4f}", flush=True)

    # сохранить фичи+метку для baseline GBM (отдельный процесс)
    import json as _json
    np.savez(OUT_DIR / "etap182_for_gbm.npz",
             Xtr=tr[feats].values, gtr=gtr, Xte=Xte_raw, gte=gte)
    (OUT_DIR / "etap182_feats.json").write_text(_json.dumps(feats, ensure_ascii=False), encoding="utf-8")
    print(f"[saved] данные для baseline GBM → etap182_for_gbm.npz (запустить отдельно)", flush=True)
    print(f"\n[NN итог] TEST ρ={rho_te:.3f}. Сравнить с GBM baseline (отдельный процесс).", flush=True)


if __name__ == "__main__":
    main()
