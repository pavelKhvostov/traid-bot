"""ob_vc s1 Phase 3 v2 — Set Transformer over token sets.

Inputs (per event):
  Zones (600 max, 8 features), Clusters (20 max, 5 features),
  Events (50 max, 6 features), Self (4 categorical/scalar).

Architecture:
  Each token: elem/tf/role/dir/action/class embedding + cont_proj + token_type_emb.
  Concat zone + cluster + event + self tokens → Transformer encoder (4 layers, D=128).
  Mean-pool with mask → main BCE + critic L1 + aux_r SmoothL1.

Round-based:
  Continuous; per-round adjust pos_weight (CORRECT direction).
  Per-type tracking — find emerald types.

Walk-forward: train < 2025-01, val 2025 H1, test 2025-H2 + 2026-H1.
"""
import sys, time, math, json, pathlib
import pandas as pd, numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

S1 = pathlib.Path.home() / "smc-lib/projects/ob_vc/s1"
NPZ = S1 / "data/features_v2.npz"
META = S1 / "data/meta_v2.parquet"
ROUNDS_DIR = S1 / "rounds_v2"; ROUNDS_DIR.mkdir(exist_ok=True)
HISTORY = S1 / "history_v2.json"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.manual_seed(42); np.random.seed(42)

print(f"Device: {DEVICE}", flush=True)
print("Loading tensors ...", flush=True)
d = np.load(NPZ, allow_pickle=True)
keys = list(d.keys())
print(f"  npz keys: {keys}", flush=True)

# Move to tensors
def t(k, dt): return torch.from_numpy(d[k]).to(dt).to(DEVICE)
Z_ELEM, Z_TF, Z_ROLE, Z_DIR = t('Z_ELEM',torch.long), t('Z_TF',torch.long), t('Z_ROLE',torch.long), t('Z_DIR',torch.long)
Z_CONT, Z_MASK = t('Z_CONT',torch.float32), t('Z_MASK',torch.float32)
C_CLS = t('C_CLS',torch.long); C_CONT, C_MASK = t('C_CONT',torch.float32), t('C_MASK',torch.float32)
E_ELEM, E_TF, E_ACTION, E_ROLE = t('E_ELEM',torch.long), t('E_TF',torch.long), t('E_ACTION',torch.long), t('E_ROLE',torch.long)
E_CONT, E_MASK = t('E_CONT',torch.float32), t('E_MASK',torch.float32)
S_TYPE, S_DIR, S_NLTF = t('S_TYPE',torch.long), t('S_DIR',torch.long), t('S_NLTF',torch.long)
S_WIDTHPCT = t('S_WIDTHPCT',torch.float32)
y_hit = t('y_hit',torch.float32)
y_r   = t('y_r',torch.float32)
TYPE_LABELS = list(d['type_labels'])

N, MAX_ZONES = Z_ELEM.shape
_, MAX_CLUSTERS = C_CLS.shape
_, MAX_EVENTS = E_ELEM.shape
print(f"  N={N}  MAX_ZONES={MAX_ZONES}  MAX_CLUSTERS={MAX_CLUSTERS}  MAX_EVENTS={MAX_EVENTS}", flush=True)

# Meta for split
meta = pd.read_parquet(META)
from datetime import datetime, timezone
def ts_at(yr, m, d): return int(datetime(yr, m, d, tzinfo=timezone.utc).timestamp() * 1000)
t_train_end = ts_at(2025, 1, 1)
t_val_end   = ts_at(2025, 7, 1)
ts_np = meta['ts'].values
mask_tr  = ts_np < t_train_end
mask_val = (ts_np >= t_train_end) & (ts_np < t_val_end)
mask_te  = ts_np >= t_val_end
idx_tr  = np.where(mask_tr)[0]; idx_val = np.where(mask_val)[0]; idx_te = np.where(mask_te)[0]
print(f"\nSplits: train={len(idx_tr)} val={len(idx_val)} test={len(idx_te)}", flush=True)
print(f"  pos rate: train={y_hit[idx_tr].mean()*100:.1f}% val={y_hit[idx_val].mean()*100:.1f}% test={y_hit[idx_te].mean()*100:.1f}%", flush=True)


# ─── Model ──
D_MODEL = 128
N_HEADS = 4
N_LAYERS = 3

ELEM_VOCAB = 14   # 13 + pad
TF_VOCAB = 9
ROLE_VOCAB = 4
DIR_VOCAB = 9
ACTION_VOCAB = 10
CLS_VOCAB = 4
TYPE_VOCAB = 25   # 24 + pad
NLTF_VOCAB = 12   # 0..11

class S1Transformer(nn.Module):
    def __init__(self):
        super().__init__()
        # Embeddings (shared)
        self.elem_emb = nn.Embedding(ELEM_VOCAB, D_MODEL, padding_idx=0)
        self.tf_emb   = nn.Embedding(TF_VOCAB, D_MODEL, padding_idx=0)
        self.role_emb = nn.Embedding(ROLE_VOCAB, D_MODEL, padding_idx=0)
        self.dir_emb  = nn.Embedding(DIR_VOCAB, D_MODEL, padding_idx=0)
        self.action_emb = nn.Embedding(ACTION_VOCAB, D_MODEL, padding_idx=0)
        self.cls_emb  = nn.Embedding(CLS_VOCAB, D_MODEL, padding_idx=0)
        self.type_emb = nn.Embedding(TYPE_VOCAB, D_MODEL, padding_idx=0)
        self.nltf_emb = nn.Embedding(NLTF_VOCAB, D_MODEL, padding_idx=0)
        self.tok_type_emb = nn.Embedding(4, D_MODEL)  # 0=zone 1=cluster 2=event 3=self
        # Cont projections
        self.zone_cont   = nn.Linear(4, D_MODEL)
        self.clu_cont    = nn.Linear(4, D_MODEL)
        self.evt_cont    = nn.Linear(2, D_MODEL)
        self.self_cont   = nn.Linear(1, D_MODEL)
        # Encoder
        layer = nn.TransformerEncoderLayer(d_model=D_MODEL, nhead=N_HEADS, dim_feedforward=D_MODEL*4,
                                            dropout=0.1, batch_first=True, activation="gelu", norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, num_layers=N_LAYERS)
        self.norm = nn.LayerNorm(D_MODEL)
        # Heads
        self.head_main  = nn.Sequential(nn.Linear(D_MODEL, D_MODEL), nn.GELU(), nn.Dropout(0.1), nn.Linear(D_MODEL, 1))
        self.head_critic = nn.Sequential(nn.Linear(D_MODEL, D_MODEL), nn.GELU(), nn.Dropout(0.1), nn.Linear(D_MODEL, 1))
        self.head_aux_r  = nn.Sequential(nn.Linear(D_MODEL, D_MODEL), nn.GELU(), nn.Dropout(0.1), nn.Linear(D_MODEL, 1))

    def forward(self, idx):
        # idx: tensor of event indices into the global arrays
        # Zone tokens
        z = (self.elem_emb(Z_ELEM[idx]) + self.tf_emb(Z_TF[idx]) + self.role_emb(Z_ROLE[idx])
             + self.dir_emb(Z_DIR[idx]) + self.zone_cont(Z_CONT[idx])
             + self.tok_type_emb(torch.zeros_like(Z_ELEM[idx])))    # type=0
        zm = Z_MASK[idx]
        # Cluster tokens
        c_type = torch.ones((idx.size(0), MAX_CLUSTERS), dtype=torch.long, device=DEVICE)
        c = (self.cls_emb(C_CLS[idx]) + self.clu_cont(C_CONT[idx]) + self.tok_type_emb(c_type))
        cm = C_MASK[idx]
        # Event tokens
        e_type = torch.full((idx.size(0), MAX_EVENTS), 2, dtype=torch.long, device=DEVICE)
        ev = (self.elem_emb(E_ELEM[idx]) + self.tf_emb(E_TF[idx]) + self.action_emb(E_ACTION[idx])
              + self.role_emb(E_ROLE[idx]) + self.evt_cont(E_CONT[idx]) + self.tok_type_emb(e_type))
        em = E_MASK[idx]
        # Self tokens (4 tokens: type, dir, nltf, width)
        bs = idx.size(0)
        s_type_token = self.type_emb(S_TYPE[idx]).unsqueeze(1)
        s_dir_token  = self.dir_emb(S_DIR[idx]).unsqueeze(1)
        s_nltf_token = self.nltf_emb(S_NLTF[idx]).unsqueeze(1)
        s_width_token = self.self_cont(S_WIDTHPCT[idx].unsqueeze(-1)).unsqueeze(1)
        s_tokens = torch.cat([s_type_token, s_dir_token, s_nltf_token, s_width_token], dim=1)
        s_type3 = torch.full((bs, 4), 3, dtype=torch.long, device=DEVICE)
        s_tokens = s_tokens + self.tok_type_emb(s_type3)
        sm = torch.ones((bs, 4), device=DEVICE)
        # Concat
        x = torch.cat([z, c, ev, s_tokens], dim=1)
        mask = torch.cat([zm, cm, em, sm], dim=1)
        key_pad = (mask == 0)
        x = self.encoder(x, src_key_padding_mask=key_pad)
        x = self.norm(x)
        # Pool with mask
        m = mask.unsqueeze(-1)
        pooled = (x * m).sum(dim=1) / m.sum(dim=1).clamp(min=1)
        return {
            'main':   self.head_main(pooled).squeeze(-1),
            'critic': self.head_critic(pooled).squeeze(-1),
            'aux_r':  self.head_aux_r(pooled).squeeze(-1),
        }


model = S1Transformer().to(DEVICE)
n_params = sum(p.numel() for p in model.parameters())
print(f"\nTransformer params: {n_params/1e6:.2f}M", flush=True)
opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)


pos_rate_tr = y_hit[idx_tr].mean().item()
w = {
    'main': 1.0, 'critic': 0.2, 'aux_r': 0.3,
    'pos_weight': (1 - pos_rate_tr) / pos_rate_tr,   # initial inverse freq
}
print(f"Initial pos_weight: {w['pos_weight']:.3f}", flush=True)


def compute_loss(out, idx, w):
    yh = y_hit[idx]; yr = y_r[idx]
    main_loss = F.binary_cross_entropy_with_logits(
        out['main'], yh, pos_weight=torch.tensor(w['pos_weight'], device=DEVICE))
    with torch.no_grad():
        pp = torch.sigmoid(out['main'])
        critic_target = (pp - yh).abs()
    critic_loss = F.l1_loss(F.softplus(out['critic']), critic_target)
    aux_loss = F.smooth_l1_loss(out['aux_r'], yr)
    total = w['main']*main_loss + w['critic']*critic_loss + w['aux_r']*aux_loss
    return total, main_loss.item(), critic_loss.item(), aux_loss.item()


def precision_at_thr(y_true, proba, th):
    pred = proba >= th
    n = int(pred.sum())
    if n == 0: return 0.0, 0, 0
    w = int(((pred==True) & (y_true==1)).sum())
    return w/n, n, w


def sweep_thr(y_true, proba, target_prec=0.70, min_n=10):
    best = None
    for th in np.linspace(0.30, 0.99, 70):
        p, n, w = precision_at_thr(y_true, proba, th)
        if p >= target_prec and n >= min_n:
            if best is None or n > best[2]:
                best = (float(th), p, n, w)
    return best


def train_round(model, opt, w, label):
    bs = 64
    best_val = float('inf'); best_state = None; bad = 0
    PATIENCE = 10
    print(f"\n--- {label}  pos_w={w['pos_weight']:.2f} ---", flush=True)
    for ep in range(1, 41):
        model.train()
        perm = torch.from_numpy(np.random.permutation(idx_tr)).to(DEVICE)
        agg = {'tot':0,'nb':0}
        for i in range(0, len(perm), bs):
            sub = perm[i:i+bs]
            out = model(sub)
            tot, ml, cl, al = compute_loss(out, sub, w)
            opt.zero_grad(); tot.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            agg['tot'] += tot.item(); agg['nb'] += 1
        tr_loss = agg['tot'] / max(agg['nb'],1)
        # Val
        model.eval()
        with torch.no_grad():
            val_idx_t = torch.from_numpy(idx_val).to(DEVICE)
            out_v = model(val_idx_t)
            vt, _, _, _ = compute_loss(out_v, val_idx_t, w)
            val_loss = vt.item()
            val_proba = torch.sigmoid(out_v['main']).cpu().numpy()
        if val_loss < best_val - 1e-5:
            best_val = val_loss; best_state = {k:v.detach().clone() for k,v in model.state_dict().items()}; bad = 0
        else:
            bad += 1
        if ep % 5 == 0 or ep == 1:
            print(f"  ep{ep:>2}  train={tr_loss:.4f}  val={val_loss:.4f}  best={best_val:.4f}  bad={bad}", flush=True)
        if bad >= PATIENCE: print(f"  early stop @ ep{ep}", flush=True); break
    model.load_state_dict(best_state)
    return model


def eval_split(model, idx_arr):
    model.eval()
    with torch.no_grad():
        idx_t = torch.from_numpy(idx_arr).to(DEVICE)
        out = model(idx_t)
        proba = torch.sigmoid(out['main']).cpu().numpy()
    return proba, y_hit[idx_arr].cpu().numpy()


# --- Run rounds ---
MAX_ROUNDS = 20
history = []
for rnd in range(1, MAX_ROUNDS+1):
    label = f"ROUND {rnd}/{MAX_ROUNDS}"
    print(f"\n{'#'*70}\n# {label}\n{'#'*70}", flush=True)
    model = train_round(model, opt, w, label)
    val_p, val_y_arr = eval_split(model, idx_val)
    test_p, test_y_arr = eval_split(model, idx_te)
    best_val = sweep_thr(val_y_arr, val_p, target_prec=0.70, min_n=10)

    # Per-type breakdown on TEST (find emerald types)
    type_te = S_TYPE.cpu().numpy()[idx_te]
    type_metrics = {}
    if best_val:
        th = best_val[0]
        for t_id in range(1, TYPE_VOCAB):
            mask_t = type_te == t_id
            if mask_t.sum() < 5: continue
            p, n, w_t = precision_at_thr(test_y_arr[mask_t], test_p[mask_t], th)
            if n >= 3:
                type_metrics[TYPE_LABELS[t_id-1]] = (p, n, w_t)

    print(f"\n[DIAGNOSE]")
    if not best_val:
        new_pw = max(w['pos_weight'] * 0.85, 0.3)
        print(f"  • NO threshold @ ≥0.70 prec → pos_weight {w['pos_weight']:.2f} → {new_pw:.2f}")
        w['pos_weight'] = new_pw
    else:
        th, p_v, n_v, w_v = best_val
        p_te, n_te, w_te = precision_at_thr(test_y_arr, test_p, th)
        print(f"  • OK: VAL prec {p_v*100:.1f}% N={n_v}  →  TEST prec {p_te*100:.1f}% N={n_te}")
        if n_v < 40:
            new_pw = min(w['pos_weight'] * 1.05, 5.0)
            print(f"  • broaden (N={n_v}<40) → pos_weight {w['pos_weight']:.2f} → {new_pw:.2f}")
            w['pos_weight'] = new_pw

    # Show top-3 emerald types on TEST
    if type_metrics:
        sorted_t = sorted(type_metrics.items(), key=lambda x: -x[1][0])
        print(f"  Per-type TEST (top by precision @ thr):")
        for t, (p, n, ws) in sorted_t[:5]:
            print(f"    {t:<25} prec={p*100:>5.1f}% N={n:>3} wins={ws}")

    # Save & history
    hist_row = {'round': rnd, 'pos_weight': w['pos_weight']}
    if best_val:
        th, p_v, n_v, w_v = best_val
        p_te, n_te, w_te = precision_at_thr(test_y_arr, test_p, th)
        hist_row.update({'thr': th, 'val_p': p_v, 'val_n': n_v, 'val_w': w_v,
                          'test_p': p_te, 'test_n': n_te, 'test_w': w_te,
                          'top_types': [(t, ts[0], ts[1], ts[2]) for t, ts in sorted(type_metrics.items(), key=lambda x: -x[1][0])[:5]]})
    history.append(hist_row)
    ck = ROUNDS_DIR / f"s1v2_round_{rnd:02d}.pt"
    torch.save({'model': model.state_dict(), 'weights': w}, ck)
    HISTORY.write_text(json.dumps(history, indent=2, default=str))
print(f"\nDONE. history → {HISTORY}", flush=True)
