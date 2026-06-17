"""zone_reactor.model — нейросеть силы зоны с самообучением (GPU / RTX 4070 Ti Super).

Задача (валидирована в zone_touch.py): на касании ICT-зоны предсказать held (реакция
≥5% раньше пробоя) vs broke. Baseline GBM: OOS AUC ~0.73. Сеть должна как минимум
повторить и попробовать превзойти + дать самообучение/интроспекцию.

САМООБУЧЕНИЕ (как просил пользователь — «почему здесь права, здесь нет»):
  1. Focal loss (γ=2) — авто-фокус на ТРУДНЫХ примерах (модель сама усиливает то, что
     путает), мягкая self-correction.
  2. Hard-example mining: 2-й раунд — апвейт примеров с высоким loss из 1-го раунда.
  3. ИНТРОСПЕКЦИЯ ошибок на OOS: профиль фич у FP (думала сильная — пробилась) и FN
     (думала слабая — удержалась) vs верных → «где и почему ошиблась».

GPU: device=cuda если есть (иначе cpu). Сеть маленькая (таблица 18 фич) — GPU тут не
ускоряет драматически, но задействован; ценность — в самообучении/интроспекции.

Output: output печать + research/zone_reactor/model_oos_pred.csv
"""
from __future__ import annotations
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
import numpy as np, pandas as pd
import torch, torch.nn as nn
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

OUT = _ROOT / 'research' / 'zone_reactor'
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
FEAT = ['tf_w', 'is_ob', 'conf_count', 'conf_strength', 'in_htf', 'n_tf_aligned', 'disp_body',
        'age_h', 'pos_in_range', 'zone_width_pct', 'side_long', 'atr_pct', 'vol_z', 'rsi14',
        'ema200_dist', 'hull_dir', 'htf_1d_dir', 'htf_3d_dir']
DEV = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
torch.manual_seed(0)


class Net(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d, 128), nn.BatchNorm1d(128), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(128, 64), nn.BatchNorm1d(64), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(64, 32), nn.ReLU(), nn.Dropout(0.2), nn.Linear(32, 1))

    def forward(self, x):
        return self.net(x).squeeze(-1)


def focal_loss(logits, y, w, gamma=2.0):
    p = torch.sigmoid(logits)
    pt = torch.where(y == 1, p, 1 - p)
    bce = nn.functional.binary_cross_entropy_with_logits(logits, y, reduction='none')
    return (w * (1 - pt) ** gamma * bce).mean()


def train(Xtr, ytr, Xva, yva, sw, epochs=120):
    net = Net(Xtr.shape[1]).to(DEV)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
    Xt = torch.tensor(Xtr, dtype=torch.float32, device=DEV); yt = torch.tensor(ytr, dtype=torch.float32, device=DEV)
    wt = torch.tensor(sw, dtype=torch.float32, device=DEV)
    Xv = torch.tensor(Xva, dtype=torch.float32, device=DEV)
    best_auc, best_state, bad = 0, None, 0
    for ep in range(epochs):
        net.train(); opt.zero_grad()
        loss = focal_loss(net(Xt), yt, wt); loss.backward(); opt.step()
        net.eval()
        with torch.no_grad():
            pv = torch.sigmoid(net(Xv)).cpu().numpy()
        try:
            auc = roc_auc_score(yva, pv)
        except Exception:
            auc = 0.5
        if auc > best_auc:
            best_auc, best_state, bad = auc, {k: v.clone() for k, v in net.state_dict().items()}, 0
        else:
            bad += 1
            if bad > 25:
                break
    net.load_state_dict(best_state)
    return net, best_auc


def main():
    print("=" * 78)
    print(f"zone_reactor NN (самообучение) · device={DEV} "
          f"{torch.cuda.get_device_name(0) if DEV.type=='cuda' else ''}")
    print("=" * 78)
    df = pd.read_csv(OUT / 'zone_touch_dataset.csv'); df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True)
    df[FEAT] = df[FEAT].fillna(0)
    is_tr = (df['time'] < TRAIN_END).values
    sc = StandardScaler().fit(df.loc[is_tr, FEAT].values)
    X = sc.transform(df[FEAT].values).astype(np.float32); y = df['held'].values.astype(np.float32)
    tr_idx = np.where(is_tr)[0]; te_idx = np.where(~is_tr)[0]
    cut = int(len(tr_idx) * 0.85)                  # time-ordered val для early-stop
    a, b = tr_idx[:cut], tr_idx[cut:]
    Xte, yte = X[te_idx], y[te_idx]

    # РАУНД 1
    sw = np.ones(len(a), np.float32)
    net, va = train(X[a], y[a], X[b], y[b], sw)
    with torch.no_grad():
        oos1 = roc_auc_score(yte, torch.sigmoid(net(torch.tensor(Xte, device=DEV))).cpu().numpy())
    # hard-example mining: loss на train-a
    with torch.no_grad():
        pa = torch.sigmoid(net(torch.tensor(X[a], device=DEV))).cpu().numpy()
    hard = -(y[a]*np.log(pa+1e-7) + (1-y[a])*np.log(1-pa+1e-7))   # per-sample BCE
    sw2 = 1.0 + (hard > np.quantile(hard, 0.7)).astype(np.float32) * 1.5   # апвейт трудных
    # РАУНД 2 (самообучение на трудных)
    net2, va2 = train(X[a], y[a], X[b], y[b], sw2)
    p_oos = torch.sigmoid(net2(torch.tensor(Xte, device=DEV).float())).detach().cpu().numpy() \
        if True else None
    with torch.no_grad():
        p_oos = torch.sigmoid(net2(torch.tensor(Xte, dtype=torch.float32, device=DEV))).cpu().numpy()
    oos2 = roc_auc_score(yte, p_oos)
    print(f"\nРаунд1 OOS AUC={oos1:.3f} (val {va:.3f})  |  Раунд2 (hard-mining) OOS AUC={oos2:.3f}")
    print(f"baseline GBM был ~0.728 (без width 0.679)")

    # net_R
    te = df.loc[~is_tr].copy(); te['p'] = p_oos
    risk = np.clip(te['zone_width_pct'].values/100, 0.003, None); rr = 0.05/risk
    te['net_R'] = np.where(te['held'] == 1, rr, -1.0) - (2*0.0008)/risk
    print(f"\nnet_R: baseline R/tr={te['net_R'].mean():+.3f}")
    for tau in [0.5, 0.6, 0.7]:
        s = te[te.p >= tau]
        if len(s) < 30: continue
        print(f"   P≥{tau}: n={len(s):>4} held%={s['held'].mean()*100:>4.0f} ΣR={s['net_R'].sum():>+6.0f} R/tr={s['net_R'].mean():+.3f}")
    sy = te[te.p >= 0.6].copy(); sy['yr'] = sy['time'].dt.year
    print("   P≥0.6 по годам: " + "  ".join(f"{y}:R/tr{g['net_R'].mean():+.2f}" for y, g in sy.groupby('yr')))

    # ИНТРОСПЕКЦИЯ ОШИБОК — «почему здесь права, здесь нет»
    te['pred'] = (te['p'] >= 0.5).astype(int)
    raw = df.loc[~is_tr, FEAT].reset_index(drop=True)
    te = te.reset_index(drop=True)
    fp = raw[(te.pred == 1) & (te.held == 0)]; tp = raw[(te.pred == 1) & (te.held == 1)]
    fn = raw[(te.pred == 0) & (te.held == 1)]; tn = raw[(te.pred == 0) & (te.held == 0)]
    print(f"\nИНТРОСПЕКЦИЯ (OOS): FP={len(fp)} TP={len(tp)} FN={len(fn)} TN={len(tn)}")
    print("  где сеть ОШИБЛАСЬ «думала сильная, пробилась» (FP vs TP) — топ-отличия фич:")
    diff = ((fp.mean() - tp.mean()) / (raw.std() + 1e-9)).abs().sort_values(ascending=False)
    for f in diff.index[:5]:
        print(f"    {f:>15}: FP={fp[f].mean():+.2f} vs TP={tp[f].mean():+.2f} (норм.Δ {diff[f]:.2f})")
    print("  «думала слабая, удержалась» (FN vs TN) — топ-отличия:")
    diff2 = ((fn.mean() - tn.mean()) / (raw.std() + 1e-9)).abs().sort_values(ascending=False)
    for f in diff2.index[:5]:
        print(f"    {f:>15}: FN={fn[f].mean():+.2f} vs TN={tn[f].mean():+.2f} (норм.Δ {diff2[f]:.2f})")
    te[['time', 'symbol', 'p', 'held', 'net_R']].to_csv(OUT / 'model_oos_pred.csv', index=False)
    print(f"\nSaved: {OUT/'model_oos_pred.csv'}")


if __name__ == '__main__':
    main()
