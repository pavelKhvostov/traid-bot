"""Run R5 BTC ckpt inference на ETH 2023-2026.

R5 model never saw ETH — это **out-of-distribution** test.
Применяем тот же threshold 0.71 (с BTC R5) и репортим WR.
"""
import sys, json, pathlib
import pandas as pd, numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

S1   = pathlib.Path.home() / "smc-lib/projects/ob_vc/s1"
ETH  = pathlib.Path.home() / "smc-lib/projects/ob_vc/eth"
NPZ  = ETH / "data/eth_features_v2.npz"
META = ETH / "data/eth_meta_v2.parquet"
CKPT = S1 / "rounds_v2/s1v2_round_05.pt"
HISTORY = S1 / "history_v2.json"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}", flush=True)

# R5 reference
hist = json.load(open(HISTORY))
r5 = [r for r in hist if r['round'] == 5][0]
THR = r5['thr']
print(f"R5 (BTC) threshold: {THR:.3f}", flush=True)
print(f"R5 BTC reference: VAL {r5['val_p']*100:.1f}% N={r5['val_n']}, TEST {r5['test_p']*100:.1f}% N={r5['test_n']}", flush=True)

# Load ETH NPZ
print("\nLoading ETH NPZ ...", flush=True)
d = np.load(NPZ, allow_pickle=True)
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
print(f"  N events: {N}, baseline pos rate: {y_hit.mean().item()*100:.1f}%", flush=True)

# Model (same arch as training)
D_MODEL=128; N_HEADS=4; N_LAYERS=3
ELEM_VOCAB,TF_VOCAB,ROLE_VOCAB,DIR_VOCAB,ACTION_VOCAB,CLS_VOCAB,TYPE_VOCAB,NLTF_VOCAB = 14,9,4,9,10,4,25,12

class S1Transformer(nn.Module):
    def __init__(self):
        super().__init__()
        self.elem_emb = nn.Embedding(ELEM_VOCAB, D_MODEL, padding_idx=0)
        self.tf_emb   = nn.Embedding(TF_VOCAB, D_MODEL, padding_idx=0)
        self.role_emb = nn.Embedding(ROLE_VOCAB, D_MODEL, padding_idx=0)
        self.dir_emb  = nn.Embedding(DIR_VOCAB, D_MODEL, padding_idx=0)
        self.action_emb = nn.Embedding(ACTION_VOCAB, D_MODEL, padding_idx=0)
        self.cls_emb  = nn.Embedding(CLS_VOCAB, D_MODEL, padding_idx=0)
        self.type_emb = nn.Embedding(TYPE_VOCAB, D_MODEL, padding_idx=0)
        self.nltf_emb = nn.Embedding(NLTF_VOCAB, D_MODEL, padding_idx=0)
        self.tok_type_emb = nn.Embedding(4, D_MODEL)
        self.zone_cont = nn.Linear(4, D_MODEL)
        self.clu_cont  = nn.Linear(4, D_MODEL)
        self.evt_cont  = nn.Linear(2, D_MODEL)
        self.self_cont = nn.Linear(1, D_MODEL)
        layer = nn.TransformerEncoderLayer(d_model=D_MODEL, nhead=N_HEADS, dim_feedforward=D_MODEL*4,
                                            dropout=0.1, batch_first=True, activation="gelu", norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, num_layers=N_LAYERS)
        self.norm = nn.LayerNorm(D_MODEL)
        self.head_main   = nn.Sequential(nn.Linear(D_MODEL, D_MODEL), nn.GELU(), nn.Dropout(0.1), nn.Linear(D_MODEL, 1))
        self.head_critic = nn.Sequential(nn.Linear(D_MODEL, D_MODEL), nn.GELU(), nn.Dropout(0.1), nn.Linear(D_MODEL, 1))
        self.head_aux_r  = nn.Sequential(nn.Linear(D_MODEL, D_MODEL), nn.GELU(), nn.Dropout(0.1), nn.Linear(D_MODEL, 1))
    def forward(self, idx):
        z = (self.elem_emb(Z_ELEM[idx]) + self.tf_emb(Z_TF[idx]) + self.role_emb(Z_ROLE[idx])
             + self.dir_emb(Z_DIR[idx]) + self.zone_cont(Z_CONT[idx])
             + self.tok_type_emb(torch.zeros_like(Z_ELEM[idx])))
        zm = Z_MASK[idx]
        c_type = torch.ones((idx.size(0), MAX_CLUSTERS), dtype=torch.long, device=DEVICE)
        c = (self.cls_emb(C_CLS[idx]) + self.clu_cont(C_CONT[idx]) + self.tok_type_emb(c_type))
        cm = C_MASK[idx]
        e_type = torch.full((idx.size(0), MAX_EVENTS), 2, dtype=torch.long, device=DEVICE)
        ev = (self.elem_emb(E_ELEM[idx]) + self.tf_emb(E_TF[idx]) + self.action_emb(E_ACTION[idx])
              + self.role_emb(E_ROLE[idx]) + self.evt_cont(E_CONT[idx]) + self.tok_type_emb(e_type))
        em = E_MASK[idx]
        bs = idx.size(0)
        s_type_token = self.type_emb(S_TYPE[idx]).unsqueeze(1)
        s_dir_token  = self.dir_emb(S_DIR[idx]).unsqueeze(1)
        s_nltf_token = self.nltf_emb(S_NLTF[idx]).unsqueeze(1)
        s_width_token = self.self_cont(S_WIDTHPCT[idx].unsqueeze(-1)).unsqueeze(1)
        s_tokens = torch.cat([s_type_token, s_dir_token, s_nltf_token, s_width_token], dim=1)
        s_type3 = torch.full((bs, 4), 3, dtype=torch.long, device=DEVICE)
        s_tokens = s_tokens + self.tok_type_emb(s_type3)
        sm = torch.ones((bs, 4), device=DEVICE)
        x = torch.cat([z, c, ev, s_tokens], dim=1)
        mask = torch.cat([zm, cm, em, sm], dim=1)
        key_pad = (mask == 0)
        x = self.encoder(x, src_key_padding_mask=key_pad)
        x = self.norm(x)
        m = mask.unsqueeze(-1)
        pooled = (x * m).sum(dim=1) / m.sum(dim=1).clamp(min=1)
        return self.head_main(pooled).squeeze(-1)

print("Loading R5 BTC ckpt ...", flush=True)
model = S1Transformer().to(DEVICE)
ck = torch.load(CKPT, map_location=DEVICE, weights_only=False)
model.load_state_dict(ck['model'])
model.eval()

# Inference на всех ETH events в батчах
BATCH = 128
proba = np.zeros(N, dtype=np.float32)
with torch.no_grad():
    for i in range(0, N, BATCH):
        idx = torch.arange(i, min(i+BATCH, N), device=DEVICE)
        proba[i:i+len(idx)] = torch.sigmoid(model(idx)).cpu().numpy()
print(f"Inference done. N events: {N}", flush=True)

y = y_hit.cpu().numpy()
r = y_r.cpu().numpy()

print(f"\n=== ETH out-of-distribution R5 inference ===")
print(f"Proba stats: min={proba.min():.3f} mean={proba.mean():.3f} max={proba.max():.3f}")
print()

# Apply BTC R5 threshold
mask_sel = proba >= THR
n_sel = mask_sel.sum()
print(f"Apply R5 BTC threshold {THR:.3f}:")
print(f"  Selected: {n_sel}  ({n_sel/N*100:.1f}% of events)")
if n_sel > 0:
    wr_sel = y[mask_sel].mean() * 100
    ev_sel = r[mask_sel].mean()
    print(f"  WR: {wr_sel:.2f}%")
    print(f"  EV/trade: {ev_sel:+.3f}R")
    print(f"  Σ R: {r[mask_sel].sum():+.0f}R")
yr_eth = 3.43  # 2023-01 → 2026-06 ≈ 3.43 years
print(f"  Trades/мес: {n_sel/(yr_eth*12):.1f}")
print()

# Sweep thresholds to find ETH-optimal
print("=== Sweep thresholds (find ETH max-WR with N≥30) ===")
print(f"{'thr':>6}  {'N':>6}  {'WR':>6}  {'EV':>8}  {'ΣR':>8}")
best_wr = 0
for th in np.linspace(0.3, 0.95, 27):
    msk = proba >= th
    n = int(msk.sum())
    if n < 30: continue
    w = y[msk].mean()*100
    e = r[msk].mean()
    sr = r[msk].sum()
    print(f"{th:>6.3f}  {n:>6}  {w:>5.1f}%  {e:>+8.3f}  {sr:>+8.0f}")
    if w > best_wr: best_wr = w

print()
print(f"=== Baseline ETH (no filter) ===")
print(f"  N={N}  WR={y.mean()*100:.1f}%  EV={r.mean():+.3f}R  Σ={r.sum():+.0f}R")
print()
print(f"=== Conclusion ===")
print(f"  Baseline WR ETH: {y.mean()*100:.1f}%")
print(f"  R5 inference @ thr={THR:.3f}: {wr_sel:.1f}% (vs BTC TEST 71.3%)")
print(f"  Max achievable WR on ETH (sweep): {best_wr:.1f}%")
