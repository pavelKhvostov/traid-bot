"""etap_177: МАКСИМАЛЬНАЯ нейросеть — весь арсенал фич, BTC+ETH+SOL, метка Андрея.

Ветка pavel. «Обучи всему её»: полный набор фич из всех материалов
(López de Prado + ICT/Андрей) на ВСЕХ трёх активах, метка Андрея.

=== МЕТКА (Андрей) ===
  На confirmation фрактала (i+2, N=2 Williams) предсказываем: даст ли фрактал
  движение >= X% (X in 3/4/5) в течение FUTURE_BARS баров ПОСЛЕ confirmation.
    y_low_strong_X  = is_low_fractal(i) AND (max high в [i+3..i+3+FB]/low[i]-1)*100 >= X
    y_high_strong_X = is_high_fractal(i) AND (low[i]-min low в [i+3..i+3+FB])/.. >= X
  Фичи — на close(i) (данные <= i), метка — будущее (supervised, OK).
  NB: фрактал-факт использует i±2 — это часть МЕТКИ, не фича. Фичи строго <= i.

=== ПОЛНЫЙ АРСЕНАЛ ФИЧ (на close i, без lookahead) ===
  Андрей/ICT: sweep_SSL/BSL_mag/failed (Liquidity Sweep/DOL), OB/FVG зоны-дист,
              Bulkowski ВСЕ 13 паттернов (fired+bars_since), фрактал-структура.
  López de Prado: SADF (bubble/explosiveness, Lec8), fractional diff (Lec3),
              Shannon entropy окна (Lec8), Amihud illiquidity (Lec8 microstructure).
  База: rsi/hull/ema/atr/vol_z, свечная геометрия, momentum, HTF-тренд (last-closed).

=== СТАНДАРТЫ ОБУЧЕНИЯ (López de Prado) ===
  Purged K-Fold + embargo, sample weights по uniqueness, triple-barrier-дух,
  pooled по BTC+ETH+SOL (asset_id как фича), focal loss, ансамбль фолдов,
  sanity shuffle. PyTorch/MPS.

Запуск: .venv-pivot/bin/python research/elements_study/etap_177_neural_full_arsenal_pavel.py
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

from data_manager import load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

# Bulkowski детекторы Андрея (все 13)
_spec = _ilu.spec_from_file_location("e172", _ROOT / "research/elements_study/etap_172_bulkowski_patterns.py")
_e172 = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_e172)
BULK_ALL = {d.__name__.replace("detect_", ""): d for d in _e172.DETECTORS}

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TF = "12h"
FRACTAL_N = 2
FUTURE_BARS = 14            # горизонт движения после confirmation (метка Андрея)
TARGETS = [3.0, 4.0, 5.0]
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
EMBARGO_BARS = 3
KFOLD = 5
EMBARGO_KF = 14
SEED = 42
ZONE_LOOKBACK = 60
BARS_SINCE_CAP = 60
SADF_WIN = 40              # окно для SADF
FRAC_D = 0.4              # порядок дробного дифференцирования
ENTROPY_WIN = 20
OUT_DIR = _ROOT / "research" / "elements_study" / "output"


# ---------- индикаторы ----------
def rsi_wilder(s, length=14):
    d = s.diff(); g = d.clip(lower=0); l = (-d).clip(lower=0)
    ag = g.ewm(alpha=1/length, adjust=False).mean(); al = l.ewm(alpha=1/length, adjust=False).mean()
    return 100 - 100/(1 + ag/al.replace(0, np.nan))


def _wma(v, length):
    w = np.arange(1, length+1, dtype=float); out = np.full(len(v), np.nan)
    for i in range(length-1, len(v)):
        out[i] = np.dot(v[i-length+1:i+1], w)/w.sum()
    return out


def hull_ma(s, length=78):
    half = length//2; sq = int(np.sqrt(length))
    raw = 2*_wma(s.values, half) - _wma(s.values, length)
    return pd.Series(_wma(pd.Series(raw).fillna(0).values, sq), index=s.index)


def ema(s, length=200): return s.ewm(span=length, adjust=False).mean()


def atr(df, length=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()


# ---------- López de Prado фичи ----------
def frac_diff_series(series, d=0.4, thres=1e-3):
    """Fractional differentiation (López Lec3): стационарность + память."""
    # веса
    w = [1.0]
    k = 1
    while True:
        wk = -w[-1] * (d - k + 1) / k
        if abs(wk) < thres:
            break
        w.append(wk); k += 1
    w = np.array(w[::-1])
    width = len(w)
    vals = series.values
    out = np.full(len(vals), np.nan)
    for i in range(width - 1, len(vals)):
        out[i] = np.dot(w, vals[i - width + 1:i + 1])
    return pd.Series(out, index=series.index)


def sadf_series(logp, win=40):
    """Упрощённый SADF (López Lec8): supremum ADF t-stat по расширяющимся окнам.

    На каждом конце t берём max ADF-t по началам [t-win, t-min]. Высокий = explosive
    (пузырь). Считается ТОЛЬКО по данным <= t (без lookahead).
    """
    y = logp.values
    n = len(y)
    out = np.full(n, np.nan)
    min_w = 12
    for t in range(win, n):
        best = -np.inf
        ya = y[t-win:t+1]
        # регрессия Δy_s = a + b*y_{s-1}; t-stat для b (ADF-lite) на под-окнах
        for start in range(0, len(ya) - min_w):
            seg = ya[start:]
            dy = np.diff(seg)
            ylag = seg[:-1]
            if len(dy) < min_w:
                continue
            X = np.column_stack([np.ones(len(ylag)), ylag])
            try:
                beta, *_ = np.linalg.lstsq(X, dy, rcond=None)
                resid = dy - X @ beta
                s2 = (resid @ resid) / max(1, len(dy) - 2)
                xtx_inv = np.linalg.inv(X.T @ X)
                se_b = np.sqrt(s2 * xtx_inv[1, 1])
                tval = beta[1] / se_b if se_b > 0 else 0.0
                if tval > best:
                    best = tval
            except Exception:
                continue
        out[t] = best if best > -np.inf else 0.0
    return pd.Series(out, index=logp.index)


def rolling_entropy(returns, win=20, bins=8):
    """Shannon entropy окна доходностей (López Lec8): мера предсказуемости."""
    r = returns.values
    n = len(r); out = np.full(n, np.nan)
    for i in range(win, n):
        seg = r[i-win:i]
        seg = seg[~np.isnan(seg)]
        if len(seg) < win // 2:
            continue
        hist, _ = np.histogram(seg, bins=bins)
        p = hist / hist.sum()
        p = p[p > 0]
        out[i] = -np.sum(p * np.log(p))
    return pd.Series(out, index=returns.index)


def amihud_illiq(df, win=14):
    """Amihud illiquidity (López Lec8): |return| / dollar_volume."""
    ret = df["close"].pct_change().abs()
    dv = (df["close"] * df["volume"]).replace(0, np.nan)
    raw = ret / dv
    return raw.rolling(win).mean()


# ---------- метка Андрея ----------
def labels_andrey(df, future_bars=14, n=2):
    """y_{low,high}_strong_{3,4,5}: фрактал + движение >=X% за future_bars после i+n+1."""
    H, L, C = df["high"].values, df["low"].values, df["close"].values
    N = len(df)
    out = {f"y_low_strong_{int(x)}": np.full(N, np.nan) for x in TARGETS}
    out.update({f"y_high_strong_{int(x)}": np.full(N, np.nan) for x in TARGETS})
    out["is_fl"] = np.full(N, np.nan); out["is_fh"] = np.full(N, np.nan)
    for i in range(n, N - n - 1):
        is_fl = L[i] < L[i-n:i].min() and L[i] < L[i+1:i+1+n].min()
        is_fh = H[i] > H[i-n:i].max() and H[i] > H[i+1:i+1+n].max()
        out["is_fl"][i] = 1 if is_fl else 0
        out["is_fh"][i] = 1 if is_fh else 0
        # движение считаем ПОСЛЕ confirmation (i+n+1 ... +future_bars)
        s = i + n + 1
        e = min(N, s + future_bars)
        if s >= N:
            continue
        if is_fl:
            mv = (H[s:e].max() / L[i] - 1) * 100 if e > s else 0
            for x in TARGETS:
                out[f"y_low_strong_{int(x)}"][i] = 1 if mv >= x else 0
        else:
            for x in TARGETS:
                out[f"y_low_strong_{int(x)}"][i] = 0
        if is_fh:
            mv = (L[i] - L[s:e].min()) / L[i] * 100 if e > s else 0
            for x in TARGETS:
                out[f"y_high_strong_{int(x)}"][i] = 1 if mv >= x else 0
        else:
            for x in TARGETS:
                out[f"y_high_strong_{int(x)}"][i] = 0
    return out


# ---------- sweep / зоны / bulkowski (как etap_175) ----------
def sweep_feats(df, i, H, L, close_i):
    out = {}
    for win_h, wb in [(24, 2), (72, 6), (168, 14)]:
        wd = df.iloc[max(0, i-wb):i+1]
        if len(wd) >= 2:
            prev = wd.iloc[:-1]; ph = prev["high"].max(); pl = prev["low"].min()
            bsl = int(H[i] > ph); ssl = int(L[i] < pl)
            bmag = (H[i]-ph)/ph*100 if bsl and ph > 0 else 0
            smag = (pl-L[i])/pl*100 if ssl and pl > 0 else 0
            bf = int(bsl and close_i < ph); sf = int(ssl and close_i > pl)
        else:
            bsl = ssl = bf = sf = 0; bmag = smag = 0
        out[f"sweep_BSL_{win_h}h"] = bsl; out[f"sweep_SSL_{win_h}h"] = ssl
        out[f"sweep_BSL_failed_{win_h}h"] = bf; out[f"sweep_SSL_failed_{win_h}h"] = sf
        out[f"sweep_BSL_mag_{win_h}h_pct"] = float(bmag); out[f"sweep_SSL_mag_{win_h}h_pct"] = float(smag)
    return out


def zone_dists(df, idx, price):
    out = {}; obs, fvgs = [], []
    for j in range(max(2, idx-ZONE_LOOKBACK), idx+1):
        z = detect_ob_pair(df, j); f = detect_fvg(df, j)
        if z is not None: obs.append(z)
        if f is not None: fvgs.append(f)
    for dl in ("LONG", "SHORT"):
        for typ, items in [("OB", obs), ("FVG", fvgs)]:
            best = 99.0; n = 0; inz = 0
            for z in items:
                if z.direction != dl: continue
                n += 1
                if z.bottom <= price <= z.top: inz = 1; d = 0.0
                elif price < z.bottom: d = (z.bottom-price)/price*100
                else: d = (price-z.top)/price*100
                best = min(best, d)
            out[f"dist_{dl}_{typ}_pct"] = best; out[f"n_{dl}_{typ}"] = n; out[f"in_{dl}_{typ}"] = inz
    return out


def precompute_bulk(df):
    df_det = df.reset_index()
    if "time" not in df_det.columns:
        df_det = df_det.rename(columns={df_det.columns[0]: "time"})
    out = {}; start = _e172.LOOKBACK + _e172.SWING_N + 2
    for nm, det in BULK_ALL.items():
        fired = np.zeros(len(df), dtype=int)
        for i in range(start, len(df)):
            try:
                if det(df_det, i) is not None: fired[i] = 1
            except Exception: pass
        bs = np.full(len(df), BARS_SINCE_CAP, dtype=int); last = -10000
        for i in range(len(df)):
            if fired[i]: last = i
            bs[i] = min(i-last, BARS_SINCE_CAP) if last >= 0 else BARS_SINCE_CAP
        out[nm] = {"fired": fired, "bars_since": bs}
    return out


def htf_dir(t0, hull_htf, close_htf):
    idx = close_htf.index.searchsorted(t0, side="right") - 1
    if idx < 3: return 0
    j = idx - 1
    c, h = close_htf.iloc[j], hull_htf.iloc[j]
    if np.isnan(c) or np.isnan(h): return 0
    return 1 if c > h else -1


# ---------- сборка по одному активу ----------
def build_symbol(sym, asset_id):
    df = load_df(sym, TF).sort_index()
    df_1d = load_df(sym, "1d").sort_index()
    df_4h = load_df(sym, "4h").sort_index()
    tf_ms = pd.Timedelta(TF)

    df["rsi"] = rsi_wilder(df["close"], 14)
    df["hull"] = hull_ma(df["close"], 78)
    df["ema"] = ema(df["close"], 200)
    df["atr"] = atr(df, 14)
    df["vol_z"] = (df["volume"]-df["volume"].rolling(20).mean())/df["volume"].rolling(20).std()
    # López de Prado фичи
    logp = np.log(df["close"])
    df["frac_diff"] = frac_diff_series(df["close"], FRAC_D)
    df["sadf"] = sadf_series(logp, SADF_WIN)
    df["entropy"] = rolling_entropy(df["close"].pct_change(), ENTROPY_WIN)
    df["amihud"] = amihud_illiq(df, 14)
    hull_1d = hull_ma(df_1d["close"], 78); hull_4h = hull_ma(df_4h["close"], 78)

    print(f"  [{sym}] precompute Bulkowski 13...", flush=True)
    bulk = precompute_bulk(df)
    labs = labels_andrey(df, FUTURE_BARS, FRACTAL_N)

    H, L, C, O = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    rows = []; N = len(df)
    for i in range(max(200, SADF_WIN+5), N):
        if df["atr"].iloc[i] <= 0 or np.isnan(df["atr"].iloc[i]) or C[i] <= 0: continue
        if np.isnan(df["sadf"].iloc[i]) or np.isnan(df["frac_diff"].iloc[i]): continue
        t0 = df.index[i] + tf_ms
        atr_i = df["atr"].iloc[i]; rng = H[i]-L[i]; body = abs(C[i]-O[i])
        uw = H[i]-max(C[i], O[i]); lw = min(C[i], O[i])-L[i]
        win_hi = H[max(0, i-29):i+1]; win_lo = L[max(0, i-29):i+1]
        f = {
            "time": df.index[i], "symbol": sym, "asset_id": asset_id,
            "close": C[i], "high": H[i], "low": L[i],
            "rsi": df["rsi"].iloc[i], "hull_dist_pct": (C[i]-df["hull"].iloc[i])/C[i]*100,
            "ema_dist_pct": (C[i]-df["ema"].iloc[i])/C[i]*100, "atr_pct": atr_i/C[i]*100,
            "vol_z": df["vol_z"].iloc[i],
            "frac_diff": df["frac_diff"].iloc[i], "sadf": df["sadf"].iloc[i],
            "entropy": df["entropy"].iloc[i] if not np.isnan(df["entropy"].iloc[i]) else 0,
            "amihud_z": 0.0,  # заполним позже z-score по train
            "amihud_raw": df["amihud"].iloc[i] if not np.isnan(df["amihud"].iloc[i]) else 0,
            "body_pct": body/C[i]*100, "range_atr": rng/atr_i if atr_i > 0 else 0,
            "upper_wick_pct": uw/rng*100 if rng > 0 else 0, "lower_wick_pct": lw/rng*100 if rng > 0 else 0,
            "close_in_range": (C[i]-L[i])/rng if rng > 0 else 0.5, "is_green": 1 if C[i] >= O[i] else 0,
            "ret_3": (C[i]/C[i-3]-1)*100 if i >= 3 else 0, "ret_7": (C[i]/C[i-7]-1)*100 if i >= 7 else 0,
            "ret_14": (C[i]/C[i-14]-1)*100 if i >= 14 else 0,
            "dist_hh30_pct": (win_hi.max()-C[i])/C[i]*100, "dist_ll30_pct": (C[i]-win_lo.min())/C[i]*100,
            "bars_since_hh": i-(max(0, i-29)+int(np.argmax(win_hi))),
            "bars_since_ll": i-(max(0, i-29)+int(np.argmin(win_lo))),
            "trend_1d": htf_dir(t0, hull_1d, df_1d["close"]), "trend_4h": htf_dir(t0, hull_4h, df_4h["close"]),
            "lower_than_prev2": 1 if (i >= 2 and L[i] < min(L[i-1], L[i-2])) else 0,
            "higher_than_prev2": 1 if (i >= 2 and H[i] > max(H[i-1], H[i-2])) else 0,
        }
        f.update(sweep_feats(df, i, H, L, C[i]))
        f.update(zone_dists(df, i, C[i]))
        for nm, d in bulk.items():
            f[f"bulk_{nm}_fired"] = int(d["fired"][i]); f[f"bulk_{nm}_bars_since"] = int(d["bars_since"][i])
        for tname in TARGETS:
            for side in ("low", "high"):
                key = f"y_{side}_strong_{int(tname)}"
                f[key] = labs[key][i]
        f["is_fl"] = labs["is_fl"][i]; f["is_fh"] = labs["is_fh"][i]
        rows.append(f)
    out = pd.DataFrame(rows).set_index("time")
    # amihud z-score (по этому активу — масштаб разный)
    a = out["amihud_raw"]
    out["amihud_z"] = ((a - a.mean()) / (a.std() + 1e-12)).clip(-5, 5)
    return out


# ---------- список фич ----------
def make_feature_list(bulk_names):
    base = ["rsi", "hull_dist_pct", "ema_dist_pct", "atr_pct", "vol_z",
            "frac_diff", "sadf", "entropy", "amihud_z",
            "body_pct", "range_atr", "upper_wick_pct", "lower_wick_pct",
            "close_in_range", "is_green", "ret_3", "ret_7", "ret_14",
            "dist_hh30_pct", "dist_ll30_pct", "bars_since_hh", "bars_since_ll",
            "trend_1d", "trend_4h", "lower_than_prev2", "higher_than_prev2", "asset_id"]
    sweep = []
    for s in ("BSL", "SSL"):
        for w in (24, 72, 168):
            sweep += [f"sweep_{s}_{w}h", f"sweep_{s}_failed_{w}h", f"sweep_{s}_mag_{w}h_pct"]
    zone = []
    for d in ("LONG", "SHORT"):
        for t in ("OB", "FVG"):
            zone += [f"dist_{d}_{t}_pct", f"n_{d}_{t}", f"in_{d}_{t}"]
    bulk = []
    for nm in bulk_names:
        bulk += [f"bulk_{nm}_fired", f"bulk_{nm}_bars_since"]
    return base + sweep + zone + bulk


# ---------- нейросеть (как etap_176) ----------
def build_net(in_dim):
    import torch.nn as nn

    class ResBlock(nn.Module):
        def __init__(self, dim, p):
            super().__init__()
            self.fc = nn.Linear(dim, dim); self.bn = nn.BatchNorm1d(dim)
            self.act = nn.GELU(); self.drop = nn.Dropout(p)
        def forward(self, x): return x + self.drop(self.act(self.bn(self.fc(x))))

    class Net(nn.Module):
        def __init__(self, in_dim, hidden=160, p=0.35):
            super().__init__()
            self.inp = nn.Sequential(nn.Linear(in_dim, hidden), nn.BatchNorm1d(hidden), nn.GELU(), nn.Dropout(p))
            self.b1 = ResBlock(hidden, p); self.b2 = ResBlock(hidden, p); self.b3 = ResBlock(hidden, p)
            self.head = nn.Sequential(nn.Linear(hidden, hidden//2), nn.GELU(), nn.Dropout(p), nn.Linear(hidden//2, 1))
        def forward(self, x):
            x = self.inp(x); x = self.b1(x); x = self.b2(x); x = self.b3(x)
            return self.head(x).squeeze(-1)
    return Net(in_dim)


def focal_loss(logits, targets, weights, alpha=0.75, gamma=2.0):
    import torch
    import torch.nn.functional as F
    bce = F.binary_cross_entropy_with_logits(logits, targets, reduction="none")
    p = torch.sigmoid(logits); pt = torch.where(targets == 1, p, 1-p)
    a = torch.where(targets == 1, alpha, 1-alpha)
    return ((a*(1-pt)**gamma*bce)*weights).mean()


def train_net(Xtr, ytr, wtr, Xval, yval, in_dim, epochs=140, device="cpu"):
    import torch
    from torch.utils.data import TensorDataset, DataLoader
    from sklearn.metrics import roc_auc_score
    torch.manual_seed(SEED)
    net = build_net(in_dim).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1.5e-2)
    ds = TensorDataset(torch.tensor(Xtr, dtype=torch.float32), torch.tensor(ytr, dtype=torch.float32),
                       torch.tensor(wtr, dtype=torch.float32))
    dl = DataLoader(ds, batch_size=512, shuffle=True, drop_last=True)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, epochs=epochs, steps_per_epoch=max(1, len(dl)))
    Xval_t = torch.tensor(Xval, dtype=torch.float32, device=device)
    best, best_state, bad, patience = 0.0, None, 0, 20
    for ep in range(epochs):
        net.train()
        for xb, yb, wb in dl:
            xb, yb, wb = xb.to(device), yb.to(device), wb.to(device)
            opt.zero_grad(); loss = focal_loss(net(xb), yb, wb); loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0); opt.step(); sched.step()
        net.eval()
        with torch.no_grad():
            pv = torch.sigmoid(net(Xval_t)).cpu().numpy()
        auc = roc_auc_score(yval, pv) if len(np.unique(yval)) > 1 else 0.5
        if auc > best:
            best, best_state, bad = auc, {k: v.cpu().clone() for k, v in net.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= patience: break
    if best_state: net.load_state_dict(best_state)
    return net, best


def predict_net(net, X, device="cpu"):
    import torch
    net.eval()
    with torch.no_grad():
        return torch.sigmoid(net(torch.tensor(X, dtype=torch.float32, device=device))).cpu().numpy()


def uniqueness_weights(index, horizon_days):
    t = index.values.astype("datetime64[ns]"); h = np.timedelta64(horizon_days, "D")
    end = t + h; starts = np.sort(t); ends = np.sort(end); n = len(t); w = np.zeros(n)
    for i in range(n):
        conc = max(1, np.searchsorted(starts, end[i], "right") - np.searchsorted(ends, t[i], "left"))
        w[i] = 1.0/conc
    return w/w.mean()


def purged_splits(index, n_splits, embargo, horizon_days):
    n = len(index); fb = np.linspace(0, n, n_splits+1).astype(int)
    t = index.values.astype("datetime64[ns]"); h = np.timedelta64(horizon_days, "D")
    for k in range(n_splits):
        v0, v1 = fb[k], fb[k+1]; val = np.arange(v0, v1)
        if len(val) == 0: continue
        vs, ve = t[v0], t[v1-1]+h; mask = np.ones(n, bool); mask[val] = False
        mask &= ~((t+h >= vs) & (t <= ve))
        mask[v1:min(n, v1+embargo)] = False
        tri = np.where(mask)[0]
        if len(tri) > 50 and len(val) > 10:
            yield tri, val


def eval_bins(proba, yte, base):
    from sklearn.metrics import roc_auc_score, precision_score, recall_score
    auc = roc_auc_score(yte, proba) if len(np.unique(yte)) > 1 else float("nan")
    bins = []
    for thr in [0.5, 0.6, 0.7, 0.8]:
        sel = proba >= thr
        if sel.sum() >= 5:
            p = precision_score(yte, sel, zero_division=0); r = recall_score(yte, sel, zero_division=0)
            bins.append((thr, int(sel.sum()), round(p, 3), round(r, 3), round(p/base, 2) if base > 0 else 0))
    return auc, bins


def run_target(ds, target, feats, device):
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    d = ds.dropna(subset=[target]).copy()
    d = d[d[feats].notna().all(axis=1)].sort_index()
    tr = d[d.index < TRAIN_END]; emb = TRAIN_END + pd.Timedelta(TF)*EMBARGO_BARS
    te = d[d.index >= emb]
    if len(tr) < 300 or len(te) < 50:
        print(f"  [{target}] too few tr={len(tr)} te={len(te)}"); return None
    y = tr[target].astype(int).values; base = te[target].astype(int).mean()
    print(f"\n===== {target} =====  train={len(tr)} test={len(te)} base_test={base*100:.2f}% pos_train={y.mean()*100:.1f}%", flush=True)
    w = uniqueness_weights(tr.index, int(FUTURE_BARS*0.5))  # горизонт метки ~7d на 12h
    Xte_raw = te[feats].values; yte = te[target].astype(int).values
    preds, cvs = [], []
    for fi, (tri, vai) in enumerate(purged_splits(tr.index, KFOLD, EMBARGO_KF, int(FUTURE_BARS*0.5))):
        sc = StandardScaler().fit(tr[feats].values[tri])
        net, va = train_net(sc.transform(tr[feats].values[tri]), y[tri], w[tri],
                            sc.transform(tr[feats].values[vai]), y[vai], len(feats), device=device)
        cvs.append(va); preds.append(predict_net(net, sc.transform(Xte_raw), device))
        print(f"    fold {fi}: val-AUC={va:.4f}", flush=True)
    proba = np.mean(preds, axis=0)
    auc, bins = eval_bins(proba, yte, base)
    print(f"  [NEURAL] CV-AUC={np.mean(cvs):.4f} | TEST-AUC={auc:.4f}", flush=True)
    for b in bins:
        print(f"     thr>={b[0]}: n={b[1]:4d} prec={b[2]:.3f} rec={b[3]:.3f} lift=×{b[4]}", flush=True)
    np.save(OUT_DIR / f"etap177_proba_{target}.npy", proba)
    return {"target": target, "cv": float(np.mean(cvs)), "test_auc": auc, "best_bin": bins[-1] if bins else None}


def main():
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_177] device={device} | арсенал фич + BTC/ETH/SOL + метка Андрея", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    parts = []
    for aid, sym in enumerate(SYMBOLS):
        print(f"[build] {sym}...", flush=True)
        parts.append(build_symbol(sym, aid))
    ds = pd.concat(parts).sort_index()
    ds.to_csv(OUT_DIR / "etap177_dataset.csv")
    feats = make_feature_list(list(BULK_ALL.keys()))
    feats = [f for f in feats if f in ds.columns]
    print(f"[data] {len(ds)} строк (3 актива), фич={len(feats)}", flush=True)

    results = []
    for x in TARGETS:
        for side in ("low", "high"):
            r = run_target(ds, f"y_{side}_strong_{int(x)}", feats, device)
            if r: results.append(r)

    print("\n===== СВОДКА (нейросеть, весь арсенал, 3 актива, метка Андрея) =====", flush=True)
    for r in results:
        bb = r["best_bin"]
        print(f"  {r['target']}: CV={r['cv']:.3f} TEST-AUC={r['test_auc']:.3f}"
              + (f" | best thr{bb[0]}: prec={bb[2]} (×{bb[4]}, n={bb[1]})" if bb else ""), flush=True)
    print("\n[sanity] для контроля lookahead — отдельный shuffle-прогон в etap_176 показал ~0.5.", flush=True)


if __name__ == "__main__":
    main()
