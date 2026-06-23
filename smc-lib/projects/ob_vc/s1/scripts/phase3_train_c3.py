"""ob_vc s1 Phase 3 v2 — Full C3-style training:
  • Main head (BCE for hit_rr1)
  • Critic head (predicts own |pred - true|, self-critique)
  • Aux head: predict r_result (regression)
  • Adaptive loss с diagnose-adjust между раундами
  • Round-based iterative, continuous

Goal: WR > 70% precision after filter @ ≥ ~80 trades/year
"""
import sys, time, math, json, pathlib
import pandas as pd, numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

S1 = pathlib.Path.home() / "smc-lib/projects/ob_vc/s1"
FEAT = S1 / "data/features_2h.parquet"
ROUNDS_DIR = S1 / "rounds"; ROUNDS_DIR.mkdir(exist_ok=True, parents=True)
HISTORY = S1 / "history.json"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.manual_seed(42); np.random.seed(42)

print(f"Device: {DEVICE}", flush=True)
print(f"Loading features ...", flush=True)
df = pd.read_parquet(FEAT)
df = df.sort_values('ts').reset_index(drop=True)
print(f"  rows: {len(df):,}  cols: {df.shape[1]}", flush=True)

EXCLUDE = {'ts','direction','hit_rr1','r_result','entry'}
feat_cols = [c for c in df.columns if c not in EXCLUDE]
df['dir_long'] = (df['direction'] == 'long').astype(int)
feat_cols = feat_cols + ['dir_long']
X = df[feat_cols].values.astype('float32')
y = df['hit_rr1'].values.astype('float32')
r_res = df['r_result'].values.astype('float32')
ts = df['ts'].values
N_FEAT = len(feat_cols)
print(f"  features: {N_FEAT}", flush=True)

from datetime import datetime, timezone
def ts_at(yr, m, d):
    return int(datetime(yr, m, d, tzinfo=timezone.utc).timestamp() * 1000)

t_train_end = ts_at(2025, 1, 1)
t_val_end   = ts_at(2025, 7, 1)
mask_tr  = ts < t_train_end
mask_val = (ts >= t_train_end) & (ts < t_val_end)
mask_te  = ts >= t_val_end
print(f"\nSplits: train={mask_tr.sum()}  val={mask_val.sum()}  test={mask_te.sum()}", flush=True)
print(f"  pos rate: train={y[mask_tr].mean()*100:.1f}%  val={y[mask_val].mean()*100:.1f}%  test={y[mask_te].mean()*100:.1f}%")

mu = X[mask_tr].mean(axis=0); sd = X[mask_tr].std(axis=0) + 1e-6
Xn = (X - mu) / sd

def to_dev(arr): return torch.from_numpy(arr).to(DEVICE)
X_tr, y_tr, r_tr   = to_dev(Xn[mask_tr]),  to_dev(y[mask_tr]),  to_dev(r_res[mask_tr])
X_val, y_val, r_val = to_dev(Xn[mask_val]), to_dev(y[mask_val]), to_dev(r_res[mask_val])
X_te, y_te, r_te    = to_dev(Xn[mask_te]),  to_dev(y[mask_te]),  to_dev(r_res[mask_te])


class S1Model(nn.Module):
    """3-head MLP: main (BCE), critic (self-error), aux_r (r_result regression)."""
    def __init__(self, in_dim, hidden=128):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(in_dim, hidden), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(hidden, hidden), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(hidden, hidden//2), nn.GELU(), nn.Dropout(0.1),
        )
        self.head_main = nn.Linear(hidden//2, 1)
        self.head_critic = nn.Linear(hidden//2, 1)
        self.head_aux_r = nn.Linear(hidden//2, 1)
    def forward(self, x):
        h = self.encoder(x)
        return {
            'main':   self.head_main(h).squeeze(-1),
            'critic': self.head_critic(h).squeeze(-1),
            'aux_r':  self.head_aux_r(h).squeeze(-1),
        }


def compute_loss(out, y, r_target, w):
    # Main BCE
    main_loss = F.binary_cross_entropy_with_logits(
        out['main'], y, pos_weight=torch.tensor(w['pos_weight'], device=DEVICE)
    )
    # Critic: predicts |sigmoid(main_pred) - y|
    with torch.no_grad():
        pred_proba = torch.sigmoid(out['main'])
        critic_target = (pred_proba - y).abs()
    critic_loss = F.l1_loss(F.softplus(out['critic']), critic_target)
    # Aux: regress r_result (range −1 to +RR)
    aux_loss = F.smooth_l1_loss(out['aux_r'], r_target)
    total = (w['main'] * main_loss + w['critic'] * critic_loss + w['aux_r'] * aux_loss)
    return total, main_loss.item(), critic_loss.item(), aux_loss.item()


def init_weights():
    pos_w = (1 - y[mask_tr].mean()) / y[mask_tr].mean()
    return {
        'main':       1.0,
        'critic':     0.2,
        'aux_r':      0.3,
        'pos_weight': float(pos_w),   # для BCE class balance
    }


def precision_at_threshold(y_true, proba, threshold):
    pred = proba >= threshold
    n_pos = int(pred.sum())
    if n_pos == 0: return 0.0, 0, 0
    n_tp = int(((pred==True) & (y_true==1)).sum())
    return n_tp / n_pos, n_pos, n_tp


def sweep_for_precision(y_true, proba, target_prec, min_n=10):
    """Find highest threshold с precision ≥ target_prec и N ≥ min_n; maximize N."""
    thr_grid = np.linspace(0.30, 0.99, 70)
    best = None
    for th in thr_grid:
        p, n, w = precision_at_threshold(y_true, proba, th)
        if p >= target_prec and n >= min_n:
            if best is None or n > best[2]:
                best = (th, p, n, w)
    return best


def train_round(model, opt, w, label):
    best_val_loss = float('inf'); best_state = None; bad = 0; PATIENCE = 10
    print(f"\n--- {label}  weights={ {k: round(v,3) for k,v in w.items()} } ---", flush=True)
    bs = 128
    for ep in range(1, 81):
        model.train()
        perm = torch.randperm(len(X_tr), device=DEVICE)
        agg = {'tot':0,'main':0,'cr':0,'aux':0,'nb':0}
        for i in range(0, len(perm), bs):
            idx = perm[i:i+bs]
            out = model(X_tr[idx])
            tot, ml, cl, al = compute_loss(out, y_tr[idx], r_tr[idx], w)
            opt.zero_grad(); tot.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            agg['tot']+=tot.item(); agg['main']+=ml; agg['cr']+=cl; agg['aux']+=al; agg['nb']+=1
        nb = max(agg['nb'],1)
        tr_loss = agg['tot']/nb
        # Val
        model.eval()
        with torch.no_grad():
            out_val = model(X_val)
            vt, vm, vc, va = compute_loss(out_val, y_val, r_val, w)
            val_loss = vt.item()
            val_proba = torch.sigmoid(out_val['main']).cpu().numpy()
        if val_loss < best_val_loss - 1e-5:
            best_val_loss = val_loss; best_state = {k:v.detach().clone() for k,v in model.state_dict().items()}; bad = 0
        else:
            bad += 1
        if ep % 5 == 0 or ep == 1:
            print(f"  ep{ep:>2}  train={tr_loss:.4f}  val={val_loss:.4f}  best={best_val_loss:.4f}  bad={bad}", flush=True)
        if bad >= PATIENCE: print(f"  early stop @ ep{ep}", flush=True); break
    model.load_state_dict(best_state)
    return model


def eval_split(model, name):
    model.eval()
    if name == 'val':
        Xs, ys = X_val, y_val.cpu().numpy()
    elif name == 'test':
        Xs, ys = X_te, y_te.cpu().numpy()
    else:
        Xs, ys = X_tr, y_tr.cpu().numpy()
    with torch.no_grad():
        proba = torch.sigmoid(model(Xs)['main']).cpu().numpy()
    return proba, ys


def diagnose_adjust(val_proba, val_y, w, target_prec=0.70, target_n=40):
    """Adapt weights based on val results."""
    actions = []
    best = sweep_for_precision(val_y, val_proba, target_prec, min_n=10)
    if best is None:
        # Не достигаем 0.70 precision — модель не достаточно decisive
        # Increase pos_weight чтобы быть более селективным на positives
        new_pw = min(w['pos_weight'] * 1.15, 5.0)
        actions.append(f"NO threshold @ ≥0.70 prec → pos_weight {w['pos_weight']:.2f} → {new_pw:.2f}")
        w['pos_weight'] = new_pw
        # Also boost main weight
        w['main'] = min(w['main'] * 1.05, 2.0)
    else:
        th, p, n, wins = best
        if n < target_n:
            # Reached precision но trades too few — broaden
            new_pw = max(w['pos_weight'] * 0.92, 0.5)
            actions.append(f"prec OK @ {p*100:.1f}% but N={n}<{target_n} → pos_weight {w['pos_weight']:.2f} → {new_pw:.2f}")
            w['pos_weight'] = new_pw
        else:
            actions.append(f"OK: prec {p*100:.1f}% N={n} (target met)")
    # Critic weight tune
    return actions, best


# --- Run ---
model = S1Model(N_FEAT).to(DEVICE)
opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
w = init_weights()
print(f"\nMLP params: {sum(p.numel() for p in model.parameters()):,}", flush=True)
print(f"Initial pos_weight: {w['pos_weight']:.3f}", flush=True)

MAX_ROUNDS = 20
history = []
for r in range(1, MAX_ROUNDS+1):
    label = f"ROUND {r}/{MAX_ROUNDS}"
    print(f"\n{'#'*70}\n# {label}\n{'#'*70}", flush=True)
    model = train_round(model, opt, w, label)
    val_p, val_y_arr = eval_split(model, 'val')
    test_p, test_y_arr = eval_split(model, 'test')
    # Diagnose
    actions, best_val = diagnose_adjust(val_p, val_y_arr, w)
    print(f"\n[DIAGNOSE]")
    for a in actions: print(f"  • {a}")
    # Eval test using val threshold
    if best_val:
        th, p_val, n_val, w_val = best_val
        p_te, n_te, w_te = precision_at_threshold(test_y_arr, test_p, th)
        print(f"\nROUND {r} RESULT:")
        print(f"  VAL  @ thr={th:.3f}:  precision={p_val*100:.1f}%  N={n_val}/{len(val_y_arr)}  wins={w_val}")
        print(f"  TEST @ thr={th:.3f}:  precision={p_te*100:.1f}%  N={n_te}/{len(test_y_arr)}  wins={w_te}")
        # Estimate trades/мес: based on test period months
        test_months = (df.loc[mask_te, 'ts'].max() - df.loc[mask_te, 'ts'].min()) / (30*24*3600*1000)
        if test_months > 0:
            print(f"  TEST trades/mo: {n_te/test_months:.1f}")
        history.append({'round':r, 'thr':float(th), 'val_p':float(p_val), 'val_n':int(n_val),
                         'test_p':float(p_te), 'test_n':int(n_te), 'test_w':int(w_te),
                         'pos_weight':float(w['pos_weight']),
                         'main_w':float(w['main']), 'critic_w':float(w['critic'])})
    else:
        history.append({'round':r, 'thr':None,
                         'pos_weight':float(w['pos_weight']),
                         'main_w':float(w['main']), 'critic_w':float(w['critic'])})
    # Save ckpt
    ck = ROUNDS_DIR / f"s1_round_{r:02d}.pt"
    torch.save({'model': model.state_dict(), 'weights': w, 'mu': mu, 'sd': sd,
                'feat_cols': feat_cols}, ck)
    print(f"  saved → {ck.name}", flush=True)
    HISTORY.write_text(json.dumps(history, indent=2, default=str))
print(f"\nHISTORY saved → {HISTORY}", flush=True)
