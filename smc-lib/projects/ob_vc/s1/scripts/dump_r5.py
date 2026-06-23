"""ob_vc s1 Phase 3 v2 — Dump 167 R5 TEST trades с фичами.

Loads R5 ckpt, runs forward pass on TEST, filters proba ≥ R5 threshold (0.710),
joins with features_2h.parquet (29 human-readable features),
writes parquet + summary.
"""
import sys, json, pathlib
import pandas as pd, numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

S1 = pathlib.Path.home() / "smc-lib/projects/ob_vc/s1"
NPZ = S1 / "data/features_v2.npz"
META = S1 / "data/meta_v2.parquet"
FEAT_AGG = S1 / "data/features_2h.parquet"
CKPT = S1 / "rounds_v2/s1v2_round_05.pt"
HISTORY = S1 / "history_v2.json"
OUT_PARQUET = S1 / "data/r5_test_trades.parquet"
OUT_SUMMARY = S1 / "r5_test_trades_summary.txt"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}", flush=True)

# Load R5 threshold
hist = json.load(open(HISTORY))
r5 = [r for r in hist if r['round'] == 5][0]
THR = r5['thr']
print(f"R5 threshold: {THR:.3f}  expected: VAL {r5['val_p']*100:.1f}% N={r5['val_n']}, TEST {r5['test_p']*100:.1f}% N={r5['test_n']}", flush=True)

# Load NPZ
print("Loading NPZ ...", flush=True)
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

MAX_ZONES = Z_ELEM.shape[1]
MAX_CLUSTERS = C_CLS.shape[1]
MAX_EVENTS = E_ELEM.shape[1]

# Meta + splits
meta = pd.read_parquet(META)
from datetime import datetime, timezone
def ts_at(yr, m, d): return int(datetime(yr, m, d, tzinfo=timezone.utc).timestamp() * 1000)
ts_np = meta['ts'].values
mask_te = ts_np >= ts_at(2025, 7, 1)
idx_te = np.where(mask_te)[0]
print(f"TEST: {len(idx_te)} events", flush=True)

# Model
D_MODEL = 128; N_HEADS = 4; N_LAYERS = 3
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
        return {'main': self.head_main(pooled).squeeze(-1)}


print("Loading R5 ckpt ...", flush=True)
model = S1Transformer().to(DEVICE)
ck = torch.load(CKPT, map_location=DEVICE, weights_only=False)
model.load_state_dict(ck['model'])
model.eval()

# Forward TEST
with torch.no_grad():
    idx_t = torch.from_numpy(idx_te).to(DEVICE)
    proba = torch.sigmoid(model(idx_t)['main']).cpu().numpy()

y_te = y_hit[idx_te].cpu().numpy()
# Filter
mask_sel = proba >= THR
sel_idx_in_test = np.where(mask_sel)[0]   # позиции в idx_te
sel_global = idx_te[sel_idx_in_test]      # глобальные indices в meta
print(f"Selected (proba ≥ {THR:.3f}): {len(sel_idx_in_test)}", flush=True)
print(f"Wins: {int(y_te[mask_sel].sum())}  Losses: {int((1-y_te[mask_sel]).sum())}", flush=True)
print(f"Precision: {y_te[mask_sel].mean()*100:.2f}%", flush=True)

# Build dump
type_arr = S_TYPE.cpu().numpy()[sel_global]
dir_arr  = S_DIR.cpu().numpy()[sel_global]
type_names = [TYPE_LABELS[t-1] if 1 <= t <= len(TYPE_LABELS) else 'UNK' for t in type_arr]
dir_names  = ['long' if d == 1 else ('short' if d == 2 else 'UNK') for d in dir_arr]

sel_meta = meta.iloc[sel_global].reset_index(drop=True)
trades = pd.DataFrame({
    'ts': sel_meta['ts'].values,
    'direction': dir_names,
    'type24': type_names,
    'hit_rr1': y_te[mask_sel].astype(int),
    'r_result': y_r[idx_te][mask_sel].cpu().numpy(),
    'proba': proba[mask_sel],
})
trades['ts_dt'] = pd.to_datetime(trades['ts'], unit='ms', utc=True)
trades['ts_msk'] = trades['ts_dt'].dt.tz_convert('Europe/Moscow').dt.strftime('%Y-%m-%d %H:%M')

# Join 29 aggregated features by (ts, direction)
print("Joining features_2h ...", flush=True)
agg = pd.read_parquet(FEAT_AGG)
agg = agg.rename(columns={'direction': 'direction'})
trades_full = trades.merge(agg, on=['ts','direction'], how='left', suffixes=('','_agg'))
matched = trades_full['n_LIQ_clusters'].notna().sum() if 'n_LIQ_clusters' in trades_full.columns else 0
print(f"Joined: {matched}/{len(trades_full)} matched with features_2h", flush=True)

# Save
trades_full.to_parquet(OUT_PARQUET, compression='zstd', compression_level=9)
print(f"Saved → {OUT_PARQUET}", flush=True)

# Summary
feat_cols = [c for c in agg.columns if c not in ('ts','direction','hit_rr1','r_result','entry')]
wins = trades_full[trades_full['hit_rr1'] == 1]
losses = trades_full[trades_full['hit_rr1'] == 0]
summary_lines = []
summary_lines.append(f"=== ob_vc s1 R5 dump: 167 TEST trades ===")
summary_lines.append(f"Threshold: {THR:.3f}")
summary_lines.append(f"Total: {len(trades_full)}  Wins: {len(wins)}  Losses: {len(losses)}  WR: {len(wins)/len(trades_full)*100:.1f}%")
summary_lines.append(f"Period TEST: 2025-07 → 2026-06 (~11.5 мес) → {len(trades_full)/11.5:.1f} trades/мес")
summary_lines.append("")

# Per-type
summary_lines.append("=== Per-type breakdown ===")
gt = trades_full.groupby('type24').agg(N=('hit_rr1','size'), W=('hit_rr1','sum'))
gt['WR'] = (gt['W']/gt['N']*100).round(1)
gt = gt.sort_values('WR', ascending=False)
summary_lines.append(gt.to_string())
summary_lines.append("")

# Feature mean delta wins vs losses
summary_lines.append("=== Top-15 features by |mean_win - mean_loss| ===")
stats = []
for f in feat_cols:
    if f not in trades_full.columns: continue
    mw = wins[f].mean(); ml = losses[f].mean()
    sd = trades_full[f].std() + 1e-9
    delta = (mw - ml) / sd     # standardized
    stats.append((f, mw, ml, delta))
stats.sort(key=lambda x: -abs(x[3]))
summary_lines.append(f"{'feature':<28}{'mean_win':>14}{'mean_loss':>14}{'std_delta':>12}")
for f, mw, ml, dl in stats[:15]:
    summary_lines.append(f"{f:<28}{mw:>14.3f}{ml:>14.3f}{dl:>12.3f}")
summary_lines.append("")

# Per-direction
summary_lines.append("=== Per-direction breakdown ===")
gd = trades_full.groupby('direction').agg(N=('hit_rr1','size'), W=('hit_rr1','sum'))
gd['WR'] = (gd['W']/gd['N']*100).round(1)
summary_lines.append(gd.to_string())
summary_lines.append("")

txt = "\n".join(summary_lines)
print(txt)
OUT_SUMMARY.write_text(txt)
print(f"\nSummary → {OUT_SUMMARY}", flush=True)
