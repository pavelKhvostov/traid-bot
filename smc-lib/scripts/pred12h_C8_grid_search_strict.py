"""STRICT lookahead-safe grid search C8 поверх pred12h basket + Phase 4 force.

Цель: подобрать параметры C8 (force-based) → max PF Strategy 1.1.1 floating
       при frequency ≥ 6/мес. Все события вычислимы на close бара i, без lookahead.

Pipeline:
  1. Загрузить:
     - pred12h_baseline_c1c7.parquet (1272 пивота с C1-C7)
     - pred12h_C8_force_6y.parquet  (per-pivot Phase 4 metrics)
     - floating_btc_6y_trades.parquet (688 floating signals + trades)

  2. Слить baseline + Phase 4 → per-pivot полный dataset

  3. Для каждой комбинации C8 параметров:
     a. predicted_pivots = baseline ∩ (C1∪…∪C7 ∪ C8(params))
     b. Build trade windows (strict: start=pivot.close, end=next opposite predicted.close)
     c. Filter floating signals → window membership + direction match
     d. Aggregate stats: WR, RR, PF, Total R, n_trades, freq/mo

  4. Ранжировать по PF при freq ≥ 6/мес. Показать топ-15.
"""
from __future__ import annotations
import sys, itertools
from pathlib import Path
import pandas as pd
import numpy as np

# Load inputs
ROOT = Path.home() / 'Desktop'
P_BASELINE = ROOT / 'pred12h_baseline_c1c7.parquet'
P_FORCE = ROOT / 'pred12h_C8_force_6y.parquet'
P_TRADES = ROOT / 'floating_btc_6y_trades.parquet'

for p in [P_BASELINE, P_FORCE, P_TRADES]:
    if not p.exists():
        print(f"ERROR: {p} not found")
        sys.exit(1)

base = pd.read_parquet(P_BASELINE)
force = pd.read_parquet(P_FORCE)
trades = pd.read_parquet(P_TRADES)

print(f"baseline: {len(base):,}  force: {len(force):,}  trades: {len(trades):,}")

# Merge baseline + force on pivot_open_ts_ms + direction
df_p = base.merge(force[['pivot_open_ts_ms','direction','total_net','d3_net','n_wins','bias','force_match']],
                  on=['pivot_open_ts_ms','direction'], how='left')
print(f"merged pivot dataset: {len(df_p):,}")
print(f"  with Phase 4: {df_p['total_net'].notna().sum()}")

# Trades closed only
trades_closed = trades[trades['outcome'].isin(['win','loss','flat'])].copy()
trades_closed['signal_time'] = pd.to_datetime(trades_closed['signal_time'], utc=True)
trades_closed = trades_closed.sort_values('signal_time').reset_index(drop=True)
print(f"closed trades: {len(trades_closed):,}")

# Helpers
BIAS_GROUPS = {
    'U':    lambda b: isinstance(b,str) and b in ('UNANIMOUS BULLISH','UNANIMOUS BEARISH'),
    'UP':   lambda b: isinstance(b,str) and (b in ('UNANIMOUS BULLISH','UNANIMOUS BEARISH') or 'PIVOT signature' in b),
    'UPH':  lambda b: isinstance(b,str) and (b in ('UNANIMOUS BULLISH','UNANIMOUS BEARISH','HTF BULLISH bias','HTF BEARISH bias') or 'PIVOT signature' in b),
    'NOBAL':lambda b: isinstance(b,str) and b != 'BALANCED (weak bias)',
}

# Direction mapping: pred12h.direction (high/low) → floating signal.direction (SHORT/LONG)
DIR_TRADE = {'high': 'SHORT', 'low': 'LONG'}

# MAX_HOLD bars (12h × N)
MAX_HOLD_HOURS = 60  # 5 × 12h

def c8_mask(df, abs_net, d3, wins_fh, wins_fl, bias_grp):
    """C8 = bias OK + force_match + thresholds."""
    if df['total_net'].isna().all(): return pd.Series(False, index=df.index)
    bias_ok = df['bias'].apply(BIAS_GROUPS[bias_grp])
    net_ok = df['total_net'].abs() >= abs_net
    d3_ok = df['d3_net'].abs() >= d3
    fh_ok = (df['direction']=='high') & (df['n_wins']<=wins_fh)
    fl_ok = (df['direction']=='low') & (df['n_wins']>=wins_fl)
    wins_ok = fh_ok | fl_ok
    return bias_ok & df['force_match'].fillna(False) & net_ok & d3_ok & wins_ok

def build_windows(predicted_df):
    """STRICT lookahead-safe trade windows.

    Window for each predicted pivot:
      - start = pivot.pivot_close_ts (=  bar i CLOSE, когда pred12h+C8 decision computable)
      - end = min(next opposite predicted.pivot_close_ts, start + MAX_HOLD_HOURS)
      - direction = pred12h.direction → trade direction
    """
    df = predicted_df.sort_values('pivot_close_ts').reset_index(drop=True)
    df['pivot_close_ts'] = pd.to_datetime(df['pivot_close_ts'], utc=True)
    windows = []
    for i, row in df.iterrows():
        start = row['pivot_close_ts']
        my_dir = row['direction']
        # find next opposite
        future = df.iloc[i+1:]
        opp = future[future['direction'] != my_dir]
        if len(opp):
            end_opp = opp.iloc[0]['pivot_close_ts']
            end = min(end_opp, start + pd.Timedelta(hours=MAX_HOLD_HOURS))
        else:
            end = start + pd.Timedelta(hours=MAX_HOLD_HOURS)
        windows.append({
            'start': start, 'end': end,
            'trade_dir': DIR_TRADE[my_dir],
        })
    return pd.DataFrame(windows)

def filter_trades_by_windows(trades, windows):
    """Каждая trade включается, если signal_time ∈ окно с matching direction."""
    if len(windows) == 0:
        return trades.iloc[0:0]
    keep = pd.Series(False, index=trades.index)
    # Window-by-window scan
    for _, w in windows.iterrows():
        mask = (trades['signal_time'] >= w['start']) & (trades['signal_time'] < w['end']) & (trades['direction'] == w['trade_dir'])
        keep |= mask
    return trades[keep]

def compute_stats(filt_trades, years=6.09):
    n = len(filt_trades)
    if n == 0:
        return {'n':0,'wr':0,'pf':0,'rr':0,'total_R':0,'r_per':0,'freq_mo':0}
    W = (filt_trades['R']>0).sum()
    L = (filt_trades['R']<0).sum()
    wr = W/n*100
    pnl = filt_trades['R'].sum()
    avg_win = filt_trades.loc[filt_trades['R']>0, 'R'].mean() if W else 0
    avg_loss = filt_trades.loc[filt_trades['R']<0, 'R'].mean() if L else 0
    gw = filt_trades.loc[filt_trades['R']>0, 'R'].sum() if W else 0
    gl = abs(filt_trades.loc[filt_trades['R']<0, 'R'].sum()) if L else 0
    pf = gw/gl if gl > 0 else float('inf')
    rr = avg_win / abs(avg_loss) if avg_loss != 0 else float('inf')
    return {
        'n': n, 'wr': round(wr,2),
        'pf': round(pf, 3), 'rr': round(rr, 3),
        'total_R': round(pnl, 2), 'r_per': round(pnl/n, 3),
        'freq_mo': round(n/(years*12), 2),
    }

# === BASELINE 1: pure floating (no filter)
print("\n=== BASELINE: pure floating (no pivot filter) ===")
print(compute_stats(trades_closed))

# === BASELINE 2: F1∩F2∩F3 + C1-C7 (existing pred12h basket, no C8)
predicted_c1c7 = df_p[df_p['in_basket']].copy()
windows_c1c7 = build_windows(predicted_c1c7)
filt_c1c7 = filter_trades_by_windows(trades_closed, windows_c1c7)
print(f"\n=== BASELINE: pred12h basket C1-C7 (no C8) ===")
print(f"predicted pivots: {len(predicted_c1c7)}")
print(compute_stats(filt_c1c7))

# === GRID SEARCH: + C8 force-based
print("\n=== GRID SEARCH: basket ∪ C8(force_params) ===")
grid = {
    'abs_net': [0, 500, 1000, 1500, 2000],
    'd3':      [0, 200, 400, 600],
    'wins_fh': [0, 1, 2, 3],
    'wins_fl': [9, 8, 7, 6],
    'bias':    ['U','UP','UPH','NOBAL'],
}

results = []
for combo in itertools.product(*grid.values()):
    params = dict(zip(grid.keys(), combo))
    c8 = c8_mask(df_p, **{k:v for k,v in params.items() if k!='bias'},
                 bias_grp=params['bias'])
    predicted_v2 = df_p[df_p['in_basket'] | c8].copy()
    if len(predicted_v2) < 50: continue
    windows = build_windows(predicted_v2)
    filt = filter_trades_by_windows(trades_closed, windows)
    stats = compute_stats(filt)
    if stats['n'] < 20: continue
    stats['imp_recall'] = int(predicted_v2['is_imp'].sum())
    stats['n_predicted'] = len(predicted_v2)
    results.append({**params, **stats})

df_g = pd.DataFrame(results)
print(f"\nValid grid points: {len(df_g)}")

# Top-15 by PF with freq >= 6/mo
mask_freq = df_g['freq_mo'] >= 6
top_pf = df_g[mask_freq].sort_values('pf', ascending=False).head(15)
print(f"\n--- Top-15 by PF (freq ≥ 6/мес) ---")
print(top_pf.to_string(index=False))

# Top-15 by RR
print(f"\n--- Top-15 by RR (freq ≥ 6/мес) ---")
print(df_g[mask_freq].sort_values('rr', ascending=False).head(15).to_string(index=False))

# Top-15 by total R
print(f"\n--- Top-15 by Total R (freq ≥ 6/мес) ---")
print(df_g[mask_freq].sort_values('total_R', ascending=False).head(15).to_string(index=False))

# Save full results
OUT = Path.home() / 'Desktop/pred12h_C8_grid_strict_results.parquet'
df_g.to_parquet(OUT, index=False)
print(f"\n[DONE] saved {len(df_g)} grid results to {OUT}")
