"""etap_198 — Daily Direction Engine, ФАЗА 1: дисциплинированный baseline + null-test.

Цель проекта (daily_engine): каждый день на ОТКРЫТИИ предсказать направление дня
(+ позже границы/зоны/трейд + аргументация SHAP + self-critique). Перед продуктом —
доказать, есть ли вообще сигнал, по законам проекта (project_neuro_metalabel_no_edge):
purged-CV + embargo, permutation NULL-тест, по годам, leak-аудит, ΣR не только WR.

НОВЫЕ рычаги vs провалившихся попыток (etap_180/189):
  - signed order-flow (Harris): daily delta / CVD slope / taker_buy_ratio / divergence
  - дневной горизонт (не 12h-pivot / не trade-outcome)
  - LdP-режим: explosiveness/entropy/Amihud
  - Dalton volume-profile фичи

Данные: research/elements_study/data/{SYM}_1h_flow.csv (OHLCV+taker_buy) → ресемпл в 1d.
Пул BTC+ETH+SOL (больше данных против overfit, Goodfellow). asset как категориальная фича.
Train 2020..2024, Test 2025..2026.

LEAK-SAFETY: все фичи считаются из O/H/L/C/V/flow, затем СДВИГАЮТСЯ на 1 день
(строка дня t = снимок на конец t-1) + добавляется gap (open_t vs close_{t-1}, известен на t-open).
Label = sign(close_t - open_t) НЕ сдвигается. Так фичи дня t не видят H/L/C дня t.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_198_daily_direction_v1.py
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
FLOW = ROOT / "research" / "elements_study" / "data"
OUT = Path(__file__).resolve().parent / "output"
OUT.mkdir(parents=True, exist_ok=True)
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TRAIN_END = "2025-01-01"   # train < этой даты, test >=


# ---------------- данные: 1h flow -> daily ----------------
def daily_from_flow(sym: str) -> pd.DataFrame:
    df = pd.read_csv(FLOW / f"{sym}_1h_flow.csv", parse_dates=["open_time"]).set_index("open_time")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last",
           "volume": "sum", "quote_volume": "sum", "trades": "sum",
           "taker_buy_base": "sum"}
    d = df.resample("1D", origin="epoch", label="left", closed="left").agg(agg).dropna(subset=["open"])
    d["delta"] = 2 * d["taker_buy_base"] - d["volume"]          # Harris signed flow (день)
    d["tbr"] = (d["taker_buy_base"] / d["volume"]).where(d["volume"] > 0)
    d["cvd"] = d["delta"].cumsum()
    return d


# ---------------- индикаторы ----------------
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, adjust=False).mean() / dn.ewm(alpha=1/n, adjust=False).mean().replace(0, np.nan)
    return (100 - 100/(1+rs)).fillna(50)

def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def shannon_entropy(x, bins=8):
    if len(x) < bins or np.allclose(x, x[0]): return 0.0
    h, _ = np.histogram(x, bins=bins); p = h[h > 0] / h.sum()
    return float(-(p*np.log(p)).sum())


# ---------------- volume profile (Dalton), на дневных барах окна ----------------
def vpoc_va(highs, lows, vols, n_bins=40, frac=0.7):
    lo, hi = lows.min(), highs.max()
    if hi <= lo: return np.nan, np.nan, np.nan
    edges = np.linspace(lo, hi, n_bins+1); prof = np.zeros(n_bins)
    for h, l, v in zip(highs, lows, vols):
        b0 = max(np.searchsorted(edges, l, "right")-1, 0)
        b1 = min(np.searchsorted(edges, h, "right")-1, n_bins-1)
        if b1 == b0: prof[b0] += v
        else: prof[b0:b1+1] += v/(b1-b0+1)
    poc = int(prof.argmax()); cen = lambda i: (edges[i]+edges[i+1])/2
    tot = prof.sum(); loi = hii = poc; cum = prof[poc]
    while cum < frac*tot:
        up = prof[hii+1:hii+3].sum() if hii+1 < n_bins else -1
        dn = prof[loi-2:loi].sum() if loi-1 >= 0 else -1
        if up < 0 and dn < 0: break
        if up >= dn: hii = min(hii+2, n_bins-1); cum += max(up, 0)
        else: loi = max(loi-2, 0); cum += max(dn, 0)
    return cen(poc), cen(hii), cen(loi)  # VPOC, VAH, VAL


# ---------------- сборка фич для одного актива ----------------
def build_features(d: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = d["open"], d["high"], d["low"], d["close"], d["volume"]
    f = pd.DataFrame(index=d.index)
    ret = c.pct_change()
    a = atr(d, 14); atrp = (a / c)
    # --- momentum / vol (Grimes тренд) ---
    f["ret1"] = ret; f["ret3"] = c.pct_change(3); f["ret5"] = c.pct_change(5); f["ret10"] = c.pct_change(10)
    f["atr_pct"] = atrp
    f["rv10"] = ret.rolling(10).std(); f["rv20"] = ret.rolling(20).std()
    e20, e50 = ema(c, 20), ema(c, 50)
    f["ema20_dist"] = (c - e20) / a
    f["ema50_dist"] = (c - e50) / a
    f["ema20_slope"] = e20.pct_change(5)
    f["ema_stack"] = (e20 - e50) / a
    f["rsi14"] = rsi(c, 14)
    f["body_pct"] = (c - o).abs() / (h - l).replace(0, np.nan)
    f["close_pos"] = (c - l) / (h - l).replace(0, np.nan)         # где закрылись в дне
    f["up_wick"] = (h - np.maximum(o, c)) / (h - l).replace(0, np.nan)
    f["dn_wick"] = (np.minimum(o, c) - l) / (h - l).replace(0, np.nan)
    f["range_atr"] = (h - l) / a                                  # расширение диапазона (momentum-leg)
    # --- структура / premium-discount (ICT) ---
    hh20 = h.rolling(20).max(); ll20 = l.rolling(20).min()
    f["pos_in_range20"] = (c - ll20) / (hh20 - ll20).replace(0, np.nan)  # premium>0.5 / discount<0.5
    f["dist_hh20"] = (hh20 - c) / a
    f["dist_ll20"] = (c - ll20) / a
    f["dow"] = d.index.dayofweek                                  # day-of-week (ICT недельный профиль)
    # --- Harris order-flow (НОВОЕ) ---
    f["tbr"] = d["tbr"]
    f["delta_norm"] = d["delta"] / v.replace(0, np.nan)           # дневной дисбаланс
    f["cvd_slope5"] = (d["cvd"] - d["cvd"].shift(5)) / a.rolling(5).mean()
    f["cvd_slope10"] = (d["cvd"] - d["cvd"].shift(10)) / a.rolling(10).mean()
    f["ofi3"] = d["delta"].rolling(3).sum() / v.rolling(3).sum().replace(0, np.nan)
    f["tbr_z"] = (d["tbr"] - d["tbr"].rolling(20).mean()) / d["tbr"].rolling(20).std()
    # CVD-дивергенция: цена ниже 5д назад, CVD выше (бычья) / зеркально
    pl = c < c.shift(5); cu = d["cvd"] > d["cvd"].shift(5)
    f["cvd_div_bull"] = (pl & cu).astype(int)
    f["cvd_div_bear"] = ((c > c.shift(5)) & (d["cvd"] < d["cvd"].shift(5))).astype(int)
    # --- LdP режим/микроструктура ---
    f["amihud"] = (ret.abs() / d["quote_volume"].replace(0, np.nan)) * 1e9   # illiquidity
    f["entropy20"] = ret.rolling(20).apply(lambda x: shannon_entropy(x.values), raw=False)
    f["var_ratio"] = ret.rolling(5).std() / ret.rolling(20).std()           # explosiveness proxy
    f["ret20_abs"] = c.pct_change(20).abs()                                 # пузырь/тренд сила
    # --- Dalton volume profile (rolling 30d), считаем по прошлым барам ---
    vpoc = pd.Series(index=d.index, dtype=float); vah = vpoc.copy(); val = vpoc.copy()
    H, L, V = h.values, l.values, v.values
    for i in range(30, len(d)):
        p, ah, al = vpoc_va(H[i-30:i], L[i-30:i], V[i-30:i])
        vpoc.iloc[i], vah.iloc[i], val.iloc[i] = p, ah, al
    f["dist_vpoc"] = (c - vpoc) / a
    f["pos_in_va"] = (c - val) / (vah - val).replace(0, np.nan)
    f["va_width_atr"] = (vah - val) / a
    f["vpoc_migr5"] = (vpoc - vpoc.shift(5)) / a
    # --- gap (известен на open дня t) — добавим ПОСЛЕ сдвига ---
    return f


def make_dataset():
    frames = []
    for sym in SYMBOLS:
        d = daily_from_flow(sym)
        f = build_features(d)
        f = f.shift(1)                       # СДВИГ: строка дня t = снимок конца t-1 (leak-guard)
        # gap известен на открытии дня t (open_t vs close_{t-1})
        f["gap"] = (d["open"] - d["close"].shift(1)) / atr(d, 14)
        f["asset"] = sym
        # label = направление дня t: sign(close - open)
        y = (d["close"] > d["open"]).astype(int)
        f["y"] = y
        f["date"] = d.index
        frames.append(f.dropna())
    data = pd.concat(frames).sort_values("date").reset_index(drop=True)
    return data


# ---------------- purged K-fold + embargo (López de Prado) ----------------
def purged_folds(dates: pd.Series, n_splits=5, embargo_days=3):
    idx = np.arange(len(dates)); folds = np.array_split(idx, n_splits)
    for k in range(n_splits):
        test = folds[k]
        t0, t1 = dates.iloc[test[0]], dates.iloc[test[-1]]
        emb = pd.Timedelta(days=embargo_days)
        train = np.array([i for i in idx if i not in set(test)
                          and not (t0 - emb <= dates.iloc[i] <= t1 + emb)])
        yield train, test


def main():
    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score
    data = make_dataset()
    feat_cols = [c for c in data.columns if c not in ("y", "date", "asset")] + ["asset"]
    cat_idx = [feat_cols.index("asset")]
    print(f"[data] {len(data)} строк-дней, {len(feat_cols)} фич, "
          f"{data['date'].min().date()}..{data['date'].max().date()}, "
          f"base rate up-day = {data['y'].mean():.3f}")

    tr = data[data["date"] < TRAIN_END].reset_index(drop=True)
    te = data[data["date"] >= TRAIN_END].reset_index(drop=True)
    print(f"[split] train {len(tr)} ({tr['date'].min().date()}..{tr['date'].max().date()}) | "
          f"test {len(te)} ({te['date'].min().date()}..{te['date'].max().date()})")

    def fit(Xtr, ytr, Xva=None, yva=None):
        m = CatBoostClassifier(iterations=400, depth=4, learning_rate=0.03,
                               l2_leaf_reg=8, loss_function="Logloss", eval_metric="AUC",
                               random_seed=42, verbose=0, early_stopping_rounds=40,
                               task_type="CPU")
        ev = Pool(Xva, yva, cat_features=cat_idx) if Xva is not None else None
        m.fit(Pool(Xtr, ytr, cat_features=cat_idx), eval_set=ev, verbose=0)
        return m

    # --- purged CV на train ---
    cv_aucs = []
    for trii, teii in purged_folds(tr["date"], 5, 3):
        m = fit(tr.loc[trii, feat_cols], tr.loc[trii, "y"])
        p = m.predict_proba(tr.loc[teii, feat_cols])[:, 1]
        cv_aucs.append(roc_auc_score(tr.loc[teii, "y"], p))
    cv_auc = float(np.mean(cv_aucs))
    print(f"\n[purged-CV] AUC = {cv_auc:.4f}  (folds: {[round(a,3) for a in cv_aucs]})")

    # --- permutation NULL (перемешать y, та же CV) ---
    rng = np.random.default_rng(0); null = []
    M = 40
    for j in range(M):
        yp = rng.permutation(tr["y"].values)
        a = []
        for trii, teii in purged_folds(tr["date"], 5, 3):
            m = fit(tr.loc[trii, feat_cols], yp[trii])
            p = m.predict_proba(tr.loc[teii, feat_cols])[:, 1]
            a.append(roc_auc_score(yp[teii], p))
        null.append(np.mean(a))
    null = np.array(null)
    pval = float((null >= cv_auc).mean())
    print(f"[NULL] M={M}: mean={null.mean():.4f} std={null.std():.4f} max={null.max():.4f} "
          f"| p-value(CV>=null) = {pval:.3f}")

    # --- финальная модель + OOS test + по годам ---
    final = fit(tr[feat_cols], tr["y"])
    pte = final.predict_proba(te[feat_cols])[:, 1]
    oos_auc = roc_auc_score(te["y"], pte)
    print(f"\n[OOS 2025-26] AUC = {oos_auc:.4f}  (n={len(te)}, base up={te['y'].mean():.3f})")
    te = te.copy(); te["p"] = pte; te["year"] = te["date"].dt.year
    for yr, g in te.groupby("year"):
        if len(g) > 20:
            print(f"   {yr}: AUC {roc_auc_score(g['y'], g['p']):.3f} (n={len(g)})")

    # --- importance (CatBoost) ---
    imp = final.get_feature_importance(Pool(tr[feat_cols], tr["y"], cat_features=cat_idx))
    top = sorted(zip(feat_cols, imp), key=lambda x: -x[1])[:15]
    print("\n[top-15 importance]")
    for name, val in top:
        print(f"   {name:16} {val:5.2f}")

    data.to_csv(OUT / "etap198_dataset.csv", index=False)
    print(f"\n[saved] {OUT/'etap198_dataset.csv'}")
    print("\nВЕРДИКТ:")
    print(f"  CV {cv_auc:.3f} / null {null.mean():.3f} (p={pval:.3f}) / OOS {oos_auc:.3f}")
    if pval < 0.05 and oos_auc > 0.55:
        print("  → сигнал ЕСТЬ и значим vs null → строить продукт-слой (границы/зоны/трейд/SHAP/critique)")
    else:
        print("  → сигнал слабый/незначим (как и прежние попытки). Нужна новая фича-гипотеза,")
        print("    НЕ вариация модели. Кандидаты: intraday order-flow (1h), VIC maxV, exogenous.")


if __name__ == "__main__":
    main()
