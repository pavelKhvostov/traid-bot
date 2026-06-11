"""etap_178: Оценка сигналов стратегий 1-5 + ординальная нейросеть (ветка pavel).

ИДЕЯ (пользователь): взять ВСЕ стратегии с хорошим winrate/R (1.1.1, 1.1.2,
1.1.3, C2), для каждого их сигнала посчитать R-исход ПО ПРАВИЛАМ САМОЙ
СТРАТЕГИИ (entry/SL/TP как у неё), присвоить класс качества 1-5, и обучить
нейросеть (ординальную) предсказывать класс на момент сигнала. 6 лет.

=== ОЦЕНКА 1-5 (по достигнутому R, гонка по 1m как в backtest стратегий) ===
  Каждый сигнал = сделка: entry=mid зоны, SL=за зону, risk=|entry-SL| (правила
  стратегии). Достигнутый R = MFE/risk до того как сняли SL.
    1 = SL раньше TP (убыток)         -> "плохой, не использовать"
    2 = 0..1R  (дошёл, но слабо)
    3 = 1..2R
    4 = 2..3R
    5 = 3R+    (идеал)
  Исход через simulate_outcome (research/1_1_1/backtest) по 1m — НЕ instant-fill.

=== СТРАТЕГИИ-ИСТОЧНИКИ (entry/sl/RR из vault, см. отчёт) ===
  1.1.1: mid FVG-15m/20m, SL=15%*OB-top depth, исходный RR=2.2
  1.1.2: mid FVG-15m/20m, SL=15%*OB-top, RR=2.2
  1.1.3: mid FVG-1h/2h,  SL=15%*OB-top, RR=2.2
  (C2/i-RDRB можно добавить — нужны их детекторы; здесь ядро 1.1.x.)
  Для оценки 1-5 RR НЕ фиксируем — считаем достигнутый R = MFE/risk
  (сколько риск-кратностей взял сигнал до снятия SL).

=== ФИЧИ (на момент сигнала, <= signal close) ===
  Переиспользуем арсенал etap_177 (sweep/DOL, зоны, Bulkowski, SADF, frac_diff,
  entropy, база) + признаки самого сигнала (strategy_id, direction, risk%,
  зона-тип/ширина). Фичи строго <= момента сигнала.

=== НЕЙРОСЕТЬ: ОРДИНАЛЬНАЯ (CORAL/cumulative-logits) ===
  Классы 1-5 упорядочены (5>4>3>2>1). Ординальная регрессия через K-1
  кумулятивных бинарных задач P(y>k). Сеть = арсенал-MLP с 4 выходами.
  Стандарты López de Prado: Purged K-Fold + embargo + uniqueness weights.

=== ЗАЩИТА ОТ LOOKAHEAD (known-pitfalls) ===
  - simulate_outcome ждёт касания entry по 1m (limit-fill, НЕ instant) —
    [etap-42-instant-fill]. Сам симулятор стратегий это гарантирует.
  - dedupe_signals по (signal_time,direction,entry) — [multi-shot-2.3x].
  - фичи <= момента сигнала; исход в будущем (supervised, OK).
  - sanity shuffle-тест ординального score.

Запуск: .venv-pivot/bin/python research/elements_study/etap_178_signal_grade_1to5_ordinal_nn.py
Требует 1m-данные BTC (для simulate_outcome 1.1.x).
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

from data_manager import load_df, compose_from_base
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals

# переиспользуем арсенал-фичи и нейро-инфраструктуру из etap_177
_spec177 = _ilu.spec_from_file_location("e177", _ROOT / "research/elements_study/etap_177_neural_full_arsenal_pavel.py")
_e177 = _ilu.module_from_spec(_spec177); _spec177.loader.exec_module(_e177)

# simulate_outcome из эталонного backtest
_specbt = _ilu.spec_from_file_location("bt111", _ROOT / "research/1_1_1/backtest/backtest_strategy_1_1_1.py")
_bt = _ilu.module_from_spec(_specbt)
# backtest-модуль при импорте может пытаться выполнить main — обернём
try:
    _specbt.loader.exec_module(_bt)
except SystemExit:
    pass

SYMBOL = "BTCUSDT"
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
EMBARGO_BARS = 3
KFOLD = 5
EMBARGO_KF = 14
SEED = 42
OUT_DIR = _ROOT / "research" / "elements_study" / "output"

TARGET_RR = 2.2          # целевой RR стратегий 1.1.x (рабочий TP)
MAX_HOLD_DAYS = 30       # макс горизонт удержания


def r_to_grade(achieved_r, hit_sl_first):
    """Класс вокруг целевого TP=2.2R (RR стратегий 1.1.x).

    1 = SL раньше TP (убыток, не использовать)
    2 = не дошёл даже до 1R (слабый)
    3 = 1..2R (близко к TP, но не взял)
    4 = взял TP 2..2.2R+ (ЦЕЛЬ достигнута — хороший сигнал)
    5 = пробил >> 2.2R (≥3R, идеал — можно было держать дальше)
    achieved_r тут = МАКС R до снятия SL (MFE/risk).
    """
    if hit_sl_first:
        return 1
    if achieved_r < 1.0:
        return 2
    if achieved_r < 2.0:
        return 3
    if achieved_r < 3.0:        # 2..3R = TP=2.2 взят
        return 4
    return 5                    # 3R+ идеал


def achieved_r_outcome(sig, df_1m):
    """Гонка TP(2.2R) vs SL по 1m + макс достигнутый R. Класс 1-5 вокруг TP=2.2R.

    Своя компактная fill+гонка логика (единая для всех стратегий).
    [pitfall: lookahead-15min-vs-tf_duration] fill-scan стартует ПОСЛЕ закрытия
    entry-свечи: signal_time(open c2) + длительность fvg_tf.
    [pitfall: instant-fill] идём по реальным 1m high/low бар за баром.

    Ключевое: класс по РЕАЛЬНОЙ гонке — что тронулось раньше, TP=2.2R или SL.
    Если SL раньше → grade 1. Если TP взят → grade по тому, как далеко MFE.
    Возврат: grade, achieved_r (MFE/risk), hit_tp (взят ли 2.2R), hit_sl.
    """
    risk = sig["risk"]; entry = sig["entry"]; direction = sig["direction"]
    sl = sig["sl"]
    if risk <= 0:
        return None
    tp = entry + risk * TARGET_RR if direction == "LONG" else entry - risk * TARGET_RR
    fvg_tf = sig.get("fvg_tf", "15m")
    tf_min = {"15m": 15, "20m": 20, "1h": 60, "2h": 120, "12h": 720}.get(fvg_tf, 15)
    t0 = pd.Timestamp(sig["signal_time"]) + pd.Timedelta(minutes=tf_min)  # close c2
    t_end = t0 + pd.Timedelta(days=MAX_HOLD_DAYS)
    fwd = df_1m[(df_1m.index >= t0) & (df_1m.index < t_end)]
    if fwd.empty:
        return None
    H = fwd["high"].values; L = fwd["low"].values

    # 1) fill: ждём касания entry (limit)
    fill_i = None
    for k in range(len(fwd)):
        if (direction == "LONG" and L[k] <= entry) or (direction == "SHORT" and H[k] >= entry):
            fill_i = k; break
    if fill_i is None:
        return None  # not filled

    # 2) гонка: что тронулось раньше — SL или TP(2.2R). Параллельно копим MFE.
    mfe = 0.0; hit_sl = False; hit_tp = False
    for k in range(fill_i, len(fwd)):
        if direction == "LONG":
            mfe = max(mfe, H[k] - entry)
            sl_hit = L[k] <= sl; tp_hit = H[k] >= tp
        else:
            mfe = max(mfe, entry - L[k])
            sl_hit = H[k] >= sl; tp_hit = L[k] <= tp
        # tie в одном баре → консервативно SL раньше (anti-optimism)
        if sl_hit:
            hit_sl = True; break
        if tp_hit:
            hit_tp = True; break
    # после выхода MFE может расти дальше только до конца окна — для grade 5
    # дотягиваем MFE по оставшимся барам (потенциал «держать дальше»)
    if hit_tp:
        for k in range(k, len(fwd)):
            if direction == "LONG":
                mfe = max(mfe, H[k] - entry)
                if L[k] <= sl: break
            else:
                mfe = max(mfe, entry - L[k])
                if H[k] >= sl: break
    achieved_r = mfe / risk if risk > 0 else 0.0
    if hit_sl and not hit_tp:
        return {"grade": 1, "achieved_r": achieved_r, "hit_tp": False, "hit_sl": True}
    return {"grade": r_to_grade(achieved_r, False), "achieved_r": achieved_r,
            "hit_tp": hit_tp, "hit_sl": hit_sl}


def gen_signals_and_grades():
    print("[load] TF...", flush=True)
    df_1d = load_df(SYMBOL, "1d"); df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h"); df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m"); df_1m = load_df(SYMBOL, "1m")
    if df_1m.empty:
        raise RuntimeError("нет 1m данных — нужны для simulate_outcome")
    df_20m = compose_from_base(df_1m, "20m")
    print(f"[load] 1m={len(df_1m)} 15m={len(df_15m)} ...", flush=True)

    all_sigs = []
    print("[detect] 1.1.1 ...", flush=True)
    s111 = detect_strategy_1_1_1_signals(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    for s in s111: s["strategy_id"] = 0
    print(f"  1.1.1: {len(s111)}", flush=True)
    print("[detect] 1.1.2 ...", flush=True)
    s112 = detect_strategy_1_1_2_signals(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    for s in s112: s["strategy_id"] = 1
    print(f"  1.1.2: {len(s112)}", flush=True)
    print("[detect] 1.1.3 ...", flush=True)
    s113 = detect_strategy_1_1_3_signals(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h)
    for s in s113: s["strategy_id"] = 2
    print(f"  1.1.3: {len(s113)}", flush=True)
    all_sigs = s111 + s112 + s113

    # дедуп по (signal_time, direction, entry) — pitfall multi-shot
    seen = set(); uniq = []
    for s in all_sigs:
        key = (s["strategy_id"], str(s["signal_time"]), s["direction"], round(s["entry"], 2))
        if key in seen:
            continue
        seen.add(key); uniq.append(s)
    print(f"[dedup] {len(all_sigs)} -> {len(uniq)}", flush=True)

    # оценка 1-5 каждого сигнала
    rows = []
    for s in uniq:
        out = achieved_r_outcome(s, df_1m)
        if out is None:
            continue
        rows.append({
            "signal_time": pd.Timestamp(s["signal_time"]),
            "strategy_id": s["strategy_id"],
            "direction_long": 1 if s["direction"] == "LONG" else 0,
            "entry": s["entry"], "sl": s["sl"], "risk": s["risk"],
            "risk_pct": abs(s["entry"] - s["sl"]) / s["entry"] * 100,
            "grade": out["grade"], "achieved_r": out["achieved_r"],
            "hit_tp": int(out["hit_tp"]), "hit_sl": int(out["hit_sl"]),
        })
    g = pd.DataFrame(rows)
    print(f"[graded] {len(g)} сигналов с исходом", flush=True)
    return g, (df_12h, df_1d, df_4h, df_1h)


# ---------- фичи на момент сигнала (арсенал etap_177, asof signal_time) ----------
def build_features_for_signals(graded, dfs):
    """Берём арсенал-датасет etap_177 (BTC) и джойним к сигналам по asof времени.

    Каждый сигнал происходит в signal_time (entry-FVG close). Берём фичи
    последней 12h-свечи, ЗАКРЫТОЙ к signal_time (<= signal_time) — без lookahead.
    """
    # построим арсенал-фичи для BTC (как в etap_177)
    feat_df = _e177.build_symbol(SYMBOL, 0)  # индекс = 12h open_time
    feat_cols = _e177.make_feature_list(list(_e177.BULK_ALL.keys()))
    feat_cols = [c for c in feat_cols if c in feat_df.columns]
    # close_time каждой 12h свечи
    feat_df = feat_df.sort_index()
    feat_close_time = feat_df.index + pd.Timedelta("12h")

    rows = []
    fc_idx = feat_close_time.values
    for _, sig in graded.iterrows():
        st = np.datetime64(sig["signal_time"].tz_convert("UTC").tz_localize(None))
        # последняя 12h свеча, закрытая к signal_time
        pos = np.searchsorted(fc_idx, st, side="right") - 1
        if pos < 0:
            continue
        frow = feat_df.iloc[pos]
        d = {c: frow[c] for c in feat_cols}
        d["sig_strategy_id"] = sig["strategy_id"]
        d["sig_direction_long"] = sig["direction_long"]
        d["sig_risk_pct"] = sig["risk_pct"]
        d["grade"] = int(sig["grade"])
        d["achieved_r"] = float(sig["achieved_r"])
        d["hit_tp"] = int(sig["hit_tp"])
        d["signal_time"] = sig["signal_time"]
        rows.append(d)
    out = pd.DataFrame(rows).set_index("signal_time").sort_index()
    feat_all = feat_cols + ["sig_strategy_id", "sig_direction_long", "sig_risk_pct"]
    return out, feat_all


# ---------- ординальная нейросеть (CORAL-style cumulative logits) ----------
def build_ordinal_net(in_dim, n_classes=5):
    import torch.nn as nn

    class ResBlock(nn.Module):
        def __init__(self, dim, p):
            super().__init__()
            self.fc = nn.Linear(dim, dim); self.bn = nn.BatchNorm1d(dim)
            self.act = nn.GELU(); self.drop = nn.Dropout(p)
        def forward(self, x): return x + self.drop(self.act(self.bn(self.fc(x))))

    class OrdinalNet(nn.Module):
        def __init__(self, in_dim, hidden=128, p=0.3, K=5):
            super().__init__()
            self.inp = nn.Sequential(nn.Linear(in_dim, hidden), nn.BatchNorm1d(hidden), nn.GELU(), nn.Dropout(p))
            self.b1 = ResBlock(hidden, p); self.b2 = ResBlock(hidden, p)
            self.shared = nn.Linear(hidden, 1, bias=False)   # CORAL: один вес
            self.bias = nn.Parameter(__import__("torch").zeros(K - 1))  # K-1 порогов
        def forward(self, x):
            x = self.inp(x); x = self.b1(x); x = self.b2(x)
            logit = self.shared(x)              # (N,1)
            return logit + self.bias            # (N, K-1): P(y>k)

    return OrdinalNet(in_dim, K=n_classes)


def coral_loss(logits, grades, weights):
    """CORAL loss: grades в {1..5} -> бинарные таргеты y>k для k=1..4."""
    import torch
    import torch.nn.functional as F
    # levels: для grade g, таргет_k = 1 если g>k+1 (k=0..3 → пороги между 1|2,2|3,3|4,4|5)
    K1 = logits.shape[1]
    g = grades.unsqueeze(1)  # (N,1)
    thresholds = torch.arange(1, K1 + 1, device=logits.device).unsqueeze(0)  # (1,K1) = 1..4
    targets = (g > thresholds).float()  # (N,K1)
    loss = F.binary_cross_entropy_with_logits(logits, targets, reduction="none").mean(1)
    return (loss * weights).mean()


def ordinal_predict_score(net, X, device):
    """Ожидаемый класс = 1 + sum P(y>k)."""
    import torch
    net.eval()
    with torch.no_grad():
        logits = net(torch.tensor(X, dtype=torch.float32, device=device))
        probs = torch.sigmoid(logits).cpu().numpy()  # (N,K-1) = P(y>k)
    return 1.0 + probs.sum(axis=1)  # непрерывный score 1..5


def train_ordinal(Xtr, gtr, wtr, Xval, gval, in_dim, epochs=150, device="cpu"):
    import torch
    from torch.utils.data import TensorDataset, DataLoader
    from scipy.stats import spearmanr
    torch.manual_seed(SEED)
    net = build_ordinal_net(in_dim).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-2)
    ds = TensorDataset(torch.tensor(Xtr, dtype=torch.float32),
                       torch.tensor(gtr, dtype=torch.float32),
                       torch.tensor(wtr, dtype=torch.float32))
    dl = DataLoader(ds, batch_size=128, shuffle=True, drop_last=True)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, epochs=epochs, steps_per_epoch=max(1, len(dl)))
    Xval_t = torch.tensor(Xval, dtype=torch.float32, device=device)
    best, best_state, bad, patience = -1, None, 0, 25
    for ep in range(epochs):
        net.train()
        for xb, gb, wb in dl:
            xb, gb, wb = xb.to(device), gb.to(device), wb.to(device)
            opt.zero_grad(); loss = coral_loss(net(xb), gb, wb); loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0); opt.step(); sched.step()
        sc = ordinal_predict_score(net, Xval, device)
        rho = spearmanr(gval, sc).correlation if len(np.unique(gval)) > 1 else 0
        if rho is not None and rho > best:
            best, best_state, bad = rho, {k: v.cpu().clone() for k, v in net.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= patience: break
    if best_state: net.load_state_dict(best_state)
    return net, best


def main():
    import torch
    from sklearn.preprocessing import StandardScaler
    from scipy.stats import spearmanr
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_178] device={device} | оценка сигналов 1-5 + ординальная NN", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    graded, dfs = gen_signals_and_grades()
    if len(graded) < 200:
        print(f"[ERR] мало сигналов: {len(graded)}"); return
    print("\n[grade distribution]", flush=True)
    print(graded["grade"].value_counts().sort_index().to_string(), flush=True)
    print(f"  WR по TP=2.2R (grade>=4, ВЗЯЛ TP): {(graded['grade']>=4).mean()*100:.1f}%", flush=True)
    print(f"  WR дошёл хоть куда (grade>=2): {(graded['grade']>=2).mean()*100:.1f}%", flush=True)
    print(f"  mean achieved_R (MFE/risk): {graded['achieved_r'].mean():.2f}", flush=True)

    ds, feats = build_features_for_signals(graded, dfs)
    ds = ds[ds[feats].notna().all(axis=1)]
    ds.to_csv(OUT_DIR / "etap178_graded_signals.csv")
    print(f"[data] {len(ds)} сигналов с фичами, фич={len(feats)}", flush=True)

    tr = ds[ds.index < TRAIN_END]; emb = TRAIN_END + pd.Timedelta("12h") * EMBARGO_BARS
    te = ds[ds.index >= emb]
    if len(tr) < 150 or len(te) < 30:
        print(f"[ERR] split: tr={len(tr)} te={len(te)}"); return
    gtr = tr["grade"].values.astype(float); gte = te["grade"].values.astype(float)
    print(f"\n[split] train={len(tr)} test={len(te)}", flush=True)

    w = _e177.uniqueness_weights(tr.index, 7)
    Xte_raw = te[feats].values
    preds, rhos = [], []
    for fi, (tri, vai) in enumerate(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7)):
        sc = StandardScaler().fit(tr[feats].values[tri])
        net, vr = train_ordinal(sc.transform(tr[feats].values[tri]), gtr[tri], w[tri],
                                sc.transform(tr[feats].values[vai]), gtr[vai], len(feats), device=device)
        rhos.append(vr); preds.append(ordinal_predict_score(net, sc.transform(Xte_raw), device))
        print(f"    fold {fi}: val Spearman ρ={vr:.4f}", flush=True)
    score = np.mean(preds, axis=0)

    rho_te = spearmanr(gte, score).correlation
    print(f"\n[ORDINAL NN] CV ρ={np.mean(rhos):.4f} | TEST Spearman ρ={rho_te:.4f}", flush=True)

    # практическая проверка: средний реальный grade по предсказанным бакетам score
    te2 = te.copy(); te2["score"] = score
    te2["pred_grade"] = np.clip(np.round(score), 1, 5).astype(int)
    print("\n[реальный grade по предсказанному классу] (хотим монотонный рост):", flush=True)
    for pg in [1, 2, 3, 4, 5]:
        sub = te2[te2["pred_grade"] == pg]
        if len(sub) >= 3:
            print(f"  pred={pg}: n={len(sub):4d}  real_grade_mean={sub['grade'].mean():.2f}  "
                  f"WR_TP(grade>=4)={ (sub['grade']>=4).mean()*100:.0f}%  "
                  f"mean_R={sub['achieved_r'].mean():.2f}", flush=True)

    # топ-бакет: сигналы где сеть говорит 4-5 — реальный winrate по TP=2.2R
    top = te2[te2["score"] >= 3.5]
    base_tp = (te2["grade"] >= 4).mean()
    if len(top) >= 5:
        wr_top = (top["grade"] >= 4).mean()
        print(f"\n[TOP сигналы score>=3.5] n={len(top)}  WR_TP={wr_top*100:.0f}% "
              f"(baseline {base_tp*100:.0f}%, lift ×{wr_top/base_tp:.2f})  "
              f"mean_R={top['achieved_r'].mean():.2f}", flush=True)

    # SANITY: shuffle grade
    rng = np.random.RandomState(0); gsh = gtr.copy(); rng.shuffle(gsh)
    tri, vai = next(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7))
    sc = StandardScaler().fit(tr[feats].values[tri])
    net_sh, _ = train_ordinal(sc.transform(tr[feats].values[tri]), gsh[tri], w[tri],
                              sc.transform(tr[feats].values[vai]), gsh[vai], len(feats), epochs=60, device=device)
    sh_score = ordinal_predict_score(net_sh, sc.transform(Xte_raw), device)
    sh_rho = spearmanr(gte, sh_score).correlation
    print(f"\n[SANITY] shuffle-grade TEST ρ={sh_rho:.4f} (должен быть ~0)", flush=True)


if __name__ == "__main__":
    main()
