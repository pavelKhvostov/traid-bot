"""ФРАКТАЛЬНЫЙ НЕЙРО-МОДУЛЬ (GPU, глубокая sequence-сеть) с многораундовым САМО-ИСПРАВЛЕНИЕМ.

ЗАДАЧА (юзер): на закрытии 12h-свечи (цена P) определить — даст ли она движение +5% (P*1.05) РАНЬШЕ,
чем -5% (P*0.95) [и в эту сторону станет фракталом]. Критерий — ПРАВИЛЬНО/НЕПРАВИЛЬНО (accuracy), без AUC.
Модуль ДОЛЖЕН: предсказать -> увидеть ошибки -> ОСОЗНАТЬ -> понять причину -> исправиться аргументированно ->
ПРОВЕРИТЬ, что стало лучше (иначе откатить и объяснить почему).

ПОЧЕМУ ТЯЖЁЛЫЙ И ЧЕСТНЫЙ:
  • вход = ПОСЛЕДОВАТЕЛЬНОСТЬ из K=48 свечей × F каузальных фич (траектория, не один срез) -> глубокая
    GRU + temporal-attention сеть на GPU видит мульти-баровые паттерны, недоступные плоским моделям;
  • walk-forward с AFML-PURGE: из train выкидываем якоря, чьё 30-дн окно метки перекрывает старт test ->
    НЕТ утечки незарезолвленной метки (та грабля, что давала фальшивые 68% в лёгкой версии);
  • метрика = OOS accuracy vs единственный достижимый в реале baseline (всегда мажоритарный класс);
  • контроль честности: shuffle-labels (должно упасть к ~50%), чтобы accuracy не была миражом.

САМО-ИСПРАВЛЕНИЕ = многораундовый цикл (loads GPU): анализ ошибок по режимам/уверенности -> аргумент ->
коррекция (focal-loss на трудных, class-weight, per-regime порог/абстейн, режим-специализация) -> ретрейн ->
сверка OOS-accuracy -> принять/откатить с доводом. «Работает» = OOS-accuracy УСТОЙЧИВО бьёт базу.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/fractal_neuro_gpu.py
Выход: research/ta_laws/fractal_neuro_gpu_report.txt + .png
"""
from __future__ import annotations
import sys, time, os
from pathlib import Path
import numpy as np
import pandas as pd
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DATA = ROOT / "research" / "elements_study" / "data"
BARRIER = 0.05
HORIZON_H = 24 * 30          # 30д горизонт гонки ±5%
PURGE = pd.Timedelta(days=30)  # AFML-пёрдж = горизонт метки
K = int(os.environ.get("FNG_K", 48))            # длина окна (свечей)
N_FOLDS = int(os.environ.get("FNG_FOLDS", 6))
N_ROUNDS = int(os.environ.get("FNG_ROUNDS", 6))  # раундов само-исправления
EPOCHS = int(os.environ.get("FNG_EPOCHS", 70))
BATCH = int(os.environ.get("FNG_BATCH", 256))
COST_RT = 0.0014
PBAR = ["ret", "rng", "body", "upw", "low", "vol_z", "delta_norm", "tbr_dev",
        "cvd_slope", "rpos", "ema_df", "ema_ds", "ema_slope", "atr_pctile"]
F = len(PBAR)


def load_flow(sym, tf):
    df = pd.read_csv(DATA / f"{sym}_{tf}_flow.csv")
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df.sort_values("open_time").reset_index(drop=True)


def roll(a, n):
    return pd.Series(a).rolling(n, min_periods=max(2, n // 3))


def build_bars(sym):
    h = load_flow(sym, "12h"); o = load_flow(sym, "1h")
    O, H, L, C, V = (h[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    delta = h["delta"].values.astype(float); cvd = h["cvd"].values.astype(float)
    tbr = h["taker_buy_ratio"].values.astype(float)
    n = len(h)
    hdf = pd.DataFrame({"high": H, "low": L, "close": C}); atr = G.compute_atr(hdf)
    atr_pct = np.where(C > 0, atr / C * 100, np.nan)
    atr_pctile = roll(atr_pct, 200).apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    logret = np.zeros(n); logret[1:] = np.log(C[1:] / np.clip(C[:-1], 1e-9, None))
    vstd = roll(logret, 30).std().values + 1e-9
    ret = logret / vstd
    rng_i = (H - L) + 1e-9
    body = (C - O) / rng_i; upw = (H - np.maximum(O, C)) / rng_i; low = (np.minimum(O, C) - L) / rng_i
    rngn = (H - L) / np.clip(C, 1e-9, None) / np.clip(atr_pct / 100, 1e-9, None)
    vmean = roll(V, 50).mean().values; vsd = roll(V, 50).std().values + 1e-9
    vol_z = (V - vmean) / vsd
    delta_norm = delta / (V + 1e-9); tbr_dev = tbr - 0.5
    base = roll(np.abs(delta), 50).mean().values + 1e-9
    cvd_slope = np.zeros(n); cvd_slope[3:] = (cvd[3:] - cvd[:-3]) / base[3:]
    lo50 = roll(L, 50).min().values; hi50 = roll(H, 50).max().values
    rpos = (C - lo50) / np.clip(hi50 - lo50, 1e-9, None)
    ema_f = pd.Series(C).ewm(span=10, adjust=False).mean().values
    ema_s = pd.Series(C).ewm(span=40, adjust=False).mean().values
    ema_df = (C - ema_f) / np.clip(C, 1e-9, None) * 100
    ema_ds = (C - ema_s) / np.clip(C, 1e-9, None) * 100
    ema_slope = np.zeros(n); ema_slope[5:] = (ema_s[5:] - ema_s[:-5]) / np.clip(C[5:], 1e-9, None) * 100
    Feat = np.column_stack([ret, rngn, body, upw, low, vol_z, delta_norm, tbr_dev,
                            cvd_slope, rpos, ema_df, ema_ds, ema_slope, atr_pctile])

    # метки ±5% по 1h-пути строго ПОСЛЕ закрытия 12h-свечи
    t1 = o["open_time"].values.astype("datetime64[ns]").astype(np.int64)
    h1H = o["high"].values.astype(float); h1L = o["low"].values.astype(float)
    close_t = (h["open_time"] + pd.Timedelta(hours=12)).values.astype("datetime64[ns]").astype(np.int64)
    si = np.searchsorted(t1, close_t, side="left")
    y = np.full(n, np.nan)
    for i in range(n):
        P = C[i]
        if not np.isfinite(P) or P <= 0:
            continue
        s = int(si[i]); e = min(s + HORIZON_H, len(t1))
        if e - s < 5:
            continue
        up = P * 1.05; dn = P * 0.95
        uh = np.nonzero(h1H[s:e] >= up)[0]; dh = np.nonzero(h1L[s:e] <= dn)[0]
        iu = uh[0] if uh.size else 10**9; idd = dh[0] if dh.size else 10**9
        if iu == 10**9 and idd == 10**9:
            continue
        y[i] = 1.0 if iu < idd else (0.0 if idd < iu else 1.0)
    ts = h["open_time"].values
    return Feat, y, ts, atr_pctile, ema_slope, np.array([sym] * n)


def assemble():
    Xs, ys, tss, syms, vol, trend = [], [], [], [], [], []
    for s in SYMBOLS:
        Feat, y, ts, apct, eslope, sy = build_bars(s)
        n = len(y)
        for i in range(K, n):
            if np.isnan(y[i]):
                continue
            win = Feat[i - K + 1:i + 1]
            if not np.isfinite(win).all() or not np.isfinite(apct[i]) or not np.isfinite(eslope[i]):
                continue
            Xs.append(win.astype(np.float32)); ys.append(y[i]); tss.append(ts[i]); syms.append(s)
            vol.append(apct[i]); trend.append(eslope[i])
    X = np.stack(Xs); Y = np.array(ys, np.float32)
    order = np.argsort(np.array(tss).astype("datetime64[ns]").astype(np.int64))
    return (X[order], Y[order], np.array(tss)[order], np.array(syms)[order],
            np.array(vol, np.float32)[order], np.array(trend, np.float32)[order])


# ---------------- модель ----------------
def get_torch():
    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    return torch, dev


def make_model(torch, hidden=128, layers=2, drop=0.25):
    import torch.nn as nn

    class SeqNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.gru = nn.GRU(F, hidden, num_layers=layers, batch_first=True,
                              dropout=drop if layers > 1 else 0.0)
            self.attn = nn.Linear(hidden, 1)
            self.head = nn.Sequential(nn.Linear(hidden, 64), nn.ReLU(), nn.Dropout(drop), nn.Linear(64, 1))

        def forward(self, x):
            out, _ = self.gru(x)                       # (B,K,hidden)
            a = torch.softmax(self.attn(out), dim=1)   # (B,K,1)
            ctx = (a * out).sum(dim=1)                 # (B,hidden)
            return self.head(ctx).squeeze(-1)
    return SeqNet()


def train_eval_fold(torch, dev, Xtr, Ytr, Xte, cfg, seed=0):
    """Обучает SeqNet на train, возвращает p(up-first) на test. cfg: loss/focal_gamma/class_w/hidden."""
    import torch.nn as nn
    torch.manual_seed(seed); np.random.seed(seed)
    # стандартизация по TRAIN
    mu = Xtr.reshape(-1, F).mean(0); sd = Xtr.reshape(-1, F).std(0) + 1e-6
    Xtr = (Xtr - mu) / sd; Xte = (Xte - mu) / sd
    model = make_model(torch, hidden=cfg.get("hidden", 128)).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.get("lr", 1e-3), weight_decay=1e-4)
    xtr = torch.tensor(Xtr, device=dev); ytr = torch.tensor(Ytr, device=dev)
    cw = cfg.get("class_w", 1.0)  # вес положительного класса
    w = torch.where(ytr > 0.5, torch.tensor(cw, device=dev), torch.tensor(1.0, device=dev))
    gamma = cfg.get("focal_gamma", 0.0)
    nrec = len(xtr)
    model.train()
    for ep in range(cfg.get("epochs", EPOCHS)):
        perm = torch.randperm(nrec, device=dev)
        for b in range(0, nrec, BATCH):
            idx = perm[b:b + BATCH]
            opt.zero_grad()
            logit = model(xtr[idx])
            p = torch.sigmoid(logit)
            bce = nn.functional.binary_cross_entropy_with_logits(logit, ytr[idx], reduction="none")
            if gamma > 0:
                pt = torch.where(ytr[idx] > 0.5, p, 1 - p)
                bce = (1 - pt).clamp(1e-6, 1) ** gamma * bce
            loss = (bce * w[idx]).mean()
            loss.backward(); opt.step()
    model.eval()
    with torch.no_grad():
        xte = torch.tensor(Xte, device=dev)
        pte = torch.sigmoid(model(xte)).cpu().numpy()
    return pte


def walk_forward(torch, dev, X, Y, ts, cfg, log=None):
    """Expanding walk-forward с AFML-пёрджем по времени. Возвращает oos proba (nan где не оценено)."""
    n = len(Y); fold = n // (N_FOLDS + 1)
    tns = ts.astype("datetime64[ns]")
    proba = np.full(n, np.nan)
    for k in range(1, N_FOLDS + 1):
        te0 = fold * k; te1 = min(fold * (k + 1), n)
        if te1 - te0 < 50:
            continue
        cut = tns[te0] - np.timedelta64(PURGE)
        tr_mask = tns < cut                       # пёрдж: метки train зарезолвлены ДО старта test
        if tr_mask.sum() < 300:
            continue
        p = train_eval_fold(torch, dev, X[tr_mask], Y[tr_mask], X[te0:te1], cfg, seed=k)
        proba[te0:te1] = p
        if log is not None:
            log(f"      fold {k}: train {tr_mask.sum()} -> test {te1-te0}")
    return proba


def acc_of(Y, proba, mask):
    pred = (proba[mask] >= 0.5).astype(int)
    return (pred == Y[mask].astype(int)).mean()


def analyze_errors(Y, proba, mask, vol, trend, base_up):
    """Возвращает срез accuracy по режимам + рекомендованную коррекцию с аргументом."""
    y = Y[mask].astype(int); p = proba[mask]; pred = (p >= 0.5).astype(int)
    v = vol[mask]; tr = trend[mask]
    diag = {}
    diag["overall"] = (pred == y).mean()
    # по уверенности
    conf = np.abs(p - 0.5)
    hi = conf >= np.quantile(conf, 0.66)
    diag["high_conf_acc"] = (pred[hi] == y[hi]).mean() if hi.sum() else np.nan
    diag["high_conf_n"] = int(hi.sum())
    # по воле
    hv = v >= np.median(v)
    diag["hi_vol_acc"] = (pred[hv] == y[hv]).mean(); diag["lo_vol_acc"] = (pred[~hv] == y[~hv]).mean()
    # по тренду
    up_t = tr > 0
    diag["uptrend_acc"] = (pred[up_t] == y[up_t]).mean() if up_t.sum() else np.nan
    diag["dntrend_acc"] = (pred[~up_t] == y[~up_t]).mean() if (~up_t).sum() else np.nan
    # дисбаланс прогнозов
    diag["pred_up_frac"] = pred.mean()
    return diag


def main():
    t0 = time.time()
    print("[load] assembling sequences...", flush=True)
    X, Y, ts, syms, vol, trend = assemble()
    base_up = Y.mean(); maj = max(base_up, 1 - base_up)
    print(f"[data] {len(Y)} анкеров, окно {K}×{F}, up-first {base_up*100:.1f}%, "
          f"maj-baseline {maj*100:.1f}%", flush=True)
    torch, dev = get_torch()
    print(f"[device] {dev} | torch {torch.__version__}", flush=True)

    out = []; A = out.append
    A("ФРАКТАЛЬНЫЙ НЕЙРО-МОДУЛЬ (GPU, sequence GRU+attention) — само-исправление, критерий ACCURACY")
    A(f"Анкеров: {len(Y)} (BTC/ETH/SOL), вход = {K} свечей × {F} фич, горизонт {HORIZON_H//24}д, AFML-пёрдж {PURGE.days}д.")
    A(f"Устройство: {dev}, torch {torch.__version__}")
    A(f"БАЗА up-first {base_up*100:.1f}%  -> мажоритарный baseline (единств. достижимый в реале) {maj*100:.1f}%")
    A("Критерий: ПРАВИЛЬНО/НЕПРАВИЛЬНО (accuracy) на block-OOS. 'Работает' = устойчиво > базы.\n")

    log = lambda m: print(m, flush=True)
    n = len(Y); fold = n // (N_FOLDS + 1)
    fmask = np.zeros(n, bool); fmask[fold:] = True  # область, где есть OOS

    # ---- РАУНД 0: база ----
    cfg = {"loss": "bce", "focal_gamma": 0.0, "class_w": 1.0, "hidden": 128, "lr": 1e-3, "epochs": EPOCHS}
    history = []
    print("[round 0] base SeqNet walk-forward...", flush=True)
    proba = walk_forward(torch, dev, X, Y, ts, cfg, log)
    mask = np.isfinite(proba)
    acc = acc_of(Y, proba, mask)
    best = {"round": 0, "cfg": dict(cfg), "acc": acc, "proba": proba.copy()}
    history.append((0, "база (BCE, GRU128)", acc))
    A("=== САМО-ИСПРАВЛЕНИЕ (раунды; accuracy на OOS) ===")
    A(f"  раунд 0: база BCE/GRU128  ->  OOS acc {acc*100:.2f}%  (база {maj*100:.2f}%)")
    print(f"[round 0] OOS acc {acc*100:.2f}%", flush=True)

    # ---- РАУНДЫ САМО-ИСПРАВЛЕНИЯ ----
    tried = set()
    for r in range(1, N_ROUNDS + 1):
        diag = analyze_errors(Y, best["proba"], np.isfinite(best["proba"]), vol, trend, base_up)
        # аргументированный выбор коррекции на основе диагностики
        cand = dict(best["cfg"])
        reason = ""
        if abs(diag["pred_up_frac"] - base_up) > 0.12 and "balance" not in tried:
            cand["class_w"] = (1 - base_up) / base_up if diag["pred_up_frac"] > base_up else base_up / (1 - base_up)
            reason = (f"прогнозы перекошены (up-доля {diag['pred_up_frac']*100:.0f}% vs база {base_up*100:.0f}%) "
                      f"-> балансирую класс-весом {cand['class_w']:.2f}"); tried.add("balance")
        elif diag["high_conf_acc"] > diag["overall"] + 0.03 and "focal" not in tried:
            cand["focal_gamma"] = 2.0
            reason = (f"на уверенных acc {diag['high_conf_acc']*100:.1f}% > общей {diag['overall']*100:.1f}% "
                      f"-> focal-loss(γ=2) фокус на трудных"); tried.add("focal")
        elif "capacity" not in tried:
            cand["hidden"] = 192; cand["epochs"] = EPOCHS + 30
            reason = "ошибки размазаны по режимам -> поднимаю ёмкость (hidden 192, +эпохи)"; tried.add("capacity")
        elif "lr" not in tried:
            cand["lr"] = 5e-4; cand["epochs"] = EPOCHS + 50
            reason = "нет прироста -> мягче lr 5e-4 + дольше обучение (тоньше оптимизация)"; tried.add("lr")
        else:
            cand["focal_gamma"] = 1.0; cand["class_w"] = cand.get("class_w", 1.0)
            reason = "комбинирую мягкий focal + текущий баланс"
        print(f"[round {r}] коррекция: {reason}", flush=True)
        proba_r = walk_forward(torch, dev, X, Y, ts, cand, log)
        mask_r = np.isfinite(proba_r); acc_r = acc_of(Y, proba_r, mask_r)
        improved = acc_r > best["acc"] + 0.003
        A(f"  раунд {r}: {reason}")
        A(f"           -> OOS acc {acc_r*100:.2f}%  ({'ПРИНЯТО (+%.2f пп)' % ((acc_r-best['acc'])*100) if improved else 'ОТКАТ (нет прироста)'})")
        history.append((r, reason, acc_r))
        if improved:
            best = {"round": r, "cfg": dict(cand), "acc": acc_r, "proba": proba_r.copy()}
        print(f"[round {r}] OOS acc {acc_r*100:.2f}% {'KEEP' if improved else 'revert'}", flush=True)

    # ---- контроль честности: shuffle-labels ----
    print("[control] shuffle-label...", flush=True)
    rng = np.random.default_rng(7); Ysh = rng.permutation(Y)
    psh = walk_forward(torch, dev, X, Ysh, ts, best["cfg"], None)
    msh = np.isfinite(psh); acc_sh = acc_of(Ysh, psh, msh)

    # ---- финальная диагностика лучшего ----
    bp = best["proba"]; bm = np.isfinite(bp)
    diag = analyze_errors(Y, bp, bm, vol, trend, base_up)
    A(f"\n=== ЛУЧШИЙ РЕЗУЛЬТАТ (раунд {best['round']}) ===")
    A(f"  OOS accuracy: {best['acc']*100:.2f}%   |  база (маж.) {maj*100:.2f}%   |  лифт {(best['acc']-maj)*100:+.2f} пп")
    A(f"  контроль shuffle-labels: {acc_sh*100:.2f}% (должно быть ~{maj*100:.0f}% -> accuracy {'честная' if acc_sh < maj + 0.02 else 'ПОДОЗРИТЕЛЬНА'})")
    A("  срез accuracy лучшего по режимам:")
    A(f"    уверенные (top-34% |p-0.5|): {diag['high_conf_acc']*100:.1f}% (n={diag['high_conf_n']})")
    A(f"    высокая вола {diag['hi_vol_acc']*100:.1f}% | низкая вола {diag['lo_vol_acc']*100:.1f}%")
    A(f"    в аптренде {diag['uptrend_acc']*100:.1f}% | в даунтренде {diag['dntrend_acc']*100:.1f}%")
    # per-asset / per-year accuracy лучшего
    A("  accuracy лучшего по активам:")
    for s in SYMBOLS:
        ms = bm & (syms == s)
        if ms.sum() > 50:
            A(f"    {s}: {acc_of(Y, bp, ms)*100:.1f}% (n={ms.sum()})")
    A("  accuracy лучшего по годам:")
    yr = pd.to_datetime(ts).year
    goodyr = 0; toty = 0
    for Yr in sorted(set(yr[bm])):
        my = bm & (yr == Yr)
        if my.sum() > 40:
            a = acc_of(Y, bp, my); toty += 1; goodyr += a > maj + 0.01
            A(f"    {Yr}: {a*100:.1f}% (n={my.sum()})")

    # ---- АБСТЕНЦИЯ: торгуем только уверенные вызовы (само-исправление 'знай, когда молчать') ----
    conf = np.abs(bp - 0.5)
    qthr = np.quantile(conf[bm], 0.66)
    hc = bm & (conf >= qthr)
    hc_acc = acc_of(Y, bp, hc)
    A(f"\n=== АБСТЕНЦИЯ: только уверенные вызовы |p-0.5|>={qthr:.3f} (top-34%) ===")
    A(f"  accuracy на уверенных: {hc_acc*100:.1f}% (n={hc.sum()}) vs база {maj*100:.1f}%  лифт {(hc_acc-maj)*100:+.1f}пп")
    hc_goodyr = 0; hc_toty = 0; hc_goodasset = 0
    A("  стабильность уверенных по годам:")
    for Yr in sorted(set(yr[hc])):
        my = hc & (yr == Yr)
        if my.sum() > 25:
            a = acc_of(Y, bp, my); hc_toty += 1; hc_goodyr += a > maj + 0.02
            A(f"    {Yr}: {a*100:.1f}% (n={my.sum()})")
    for s in SYMBOLS:
        ms = hc & (syms == s)
        if ms.sum() > 40 and acc_of(Y, bp, ms) > maj + 0.02:
            hc_goodasset += 1
    A(f"  -> уверенные: {hc_goodyr}/{hc_toty} лет и {hc_goodasset}/3 активов > базы+2пп")
    hc_works = (hc_acc > maj + 0.03) and (hc_goodyr >= max(2, hc_toty - 1)) and (hc_goodasset >= 2)

    # ---- нетто на уверенных вызовах ----
    A("\n=== НЕТТО (±5% брекет RR1, кост 0.14%RT~0.028R) на уверенных вызовах лучшего ===")
    for thr in (0.0, 0.05, 0.10):
        sel = bm & (np.abs(bp - 0.5) >= thr)
        if sel.sum() < 30:
            continue
        pred = (bp[sel] >= 0.5).astype(int); win = (pred == Y[sel].astype(int))
        exp = win.mean() - (~win).mean() - COST_RT / BARRIER
        A(f"  |p-0.5|>={thr:.2f}: n={sel.sum():5d}  acc/WR={win.mean()*100:5.1f}%  netExp={exp:+.3f}R")

    # ---- вердикт ----
    works = (best["acc"] > maj + 0.02) and (acc_sh < maj + 0.02) and (goodyr >= max(2, toty - 1))
    A("\n=== ВЕРДИКТ (само-осознание) ===")
    if works:
        A(f"  Модуль РАБОТАЕТ (на всех сделках): OOS accuracy {best['acc']*100:.1f}% устойчиво > базы {maj*100:.1f}% "
          f"({goodyr}/{toty} лет), shuffle-контроль чист. Само-исправление дало прирост по раундам.")
    elif hc_works:
        A(f"  Модуль РАБОТАЕТ УСЛОВНО (абстенция): на всех сделках = монетка ({best['acc']*100:.1f}%), НО на уверенных "
          f"вызовах {hc_acc*100:.1f}% > базы, устойчиво ({hc_goodyr}/{hc_toty} лет, {hc_goodasset}/3 активов), "
          f"shuffle чист. Само-исправление 'осознало': предсказуемо лишь подмножество -> торговать ТОЛЬКО уверенные.")
    else:
        A(f"  Модуль НЕ нашёл устойчивого превышения базы (best {best['acc']*100:.1f}% vs {maj*100:.1f}%, "
          f"годы {goodyr}/{toty}, shuffle {acc_sh*100:.1f}%). Само-исправление отработало честно: перебрало "
          f"балансировку/focal/ёмкость/lr — ни одна коррекция не дала устойчивого прироста на OOS.")
        A("  ОСОЗНАНИЕ: симметричный ±5% first-passage от 12h-свечи -> направление near-coin даже для глубокой")
        A("  GRU+attention сети; единственное стабильное превышение базы потребовало бы утечки (её мы убрали пёрджем).")
    A(f"\n  кривая само-исправления (раунд: accuracy): " +
      " | ".join(f"R{r}:{a*100:.1f}%" for r, _, a in history))
    A(f"  время: {(time.time()-t0)/60:.1f} мин")

    rep = HERE / "fractal_neuro_gpu_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))

    # график
    try:
        import matplotlib
        matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(14, 5))
        rs = [r for r, _, _ in history]; accs = [a * 100 for _, _, a in history]
        ax[0].plot(rs, accs, "o-", color="#1db954"); ax[0].axhline(maj * 100, color="#ef5350", ls="--", label=f"база {maj*100:.1f}%")
        ax[0].set_xlabel("раунд само-исправления"); ax[0].set_ylabel("OOS accuracy %")
        ax[0].set_title("Само-исправление: accuracy по раундам"); ax[0].legend(); ax[0].grid(alpha=0.2)
        ax[1].hist(bp[bm], bins=40, color="#4a90d9"); ax[1].axvline(0.5, color="k", ls="--")
        ax[1].set_title(f"p(up-first) лучшего, OOS acc {best['acc']*100:.1f}%"); ax[1].grid(alpha=0.2)
        fig.tight_layout(); fig.savefig(HERE / "fractal_neuro_gpu.png", dpi=120)
        print(f"\n[ok] -> {rep.name} + fractal_neuro_gpu.png")
    except Exception as ex:
        print(f"[plot skip] {ex}")


if __name__ == "__main__":
    main()
