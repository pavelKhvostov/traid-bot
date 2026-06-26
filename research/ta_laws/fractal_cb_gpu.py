"""ФРАКТАЛЬНЫЙ ±5% — тяжёлый САМО-ИСПРАВЛЯЮЩИЙСЯ модуль на CatBoost-GPU (грузит RTX 4070 Ti SUPER).

Контекст: torch-CUDA в этом окружении блокирован прокси (подтверждено), рабочий GPU-путь проекта = CatBoost-GPU.
Тот же научный каркас, что у GRU-версии (fractal_neuro_gpu.py), но обучение на ВИДЕОКАРТЕ и тяжелее:
  • вход = окно K свечей × F каузальных фич, РАЗВЁРНУТОЕ в K·F лаг-признаков + режимные скаляры;
  • walk-forward с AFML-пёрджем (метки train зарезолвлены ДО старта test -> нет утечки);
  • КРИТЕРИЙ = ПРАВИЛЬНО/НЕПРАВИЛЬНО (accuracy) на block-OOS, без AUC;
  • контроль честности shuffle-labels (должно упасть к базе);
  • САМО-ИСПРАВЛЕНИЕ многораундовое: анализ ошибок -> аргумент -> коррекция (баланс классов, ёмкость depth,
    итерации, регуляризация l2, random_strength, абстенция на уверенных) -> ретрейн -> сверка OOS -> принять/откатить.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/fractal_cb_gpu.py
Выход: research/ta_laws/fractal_cb_gpu_report.txt + .png
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
from fractal_neuro_gpu import assemble, SYMBOLS, F, K, PURGE, COST_RT, BARRIER  # noqa: E402

N_FOLDS = int(os.environ.get("FCB_FOLDS", 6))
N_ROUNDS = int(os.environ.get("FCB_ROUNDS", 6))
ITERS = int(os.environ.get("FCB_ITERS", 6000))
GPU = os.environ.get("FCB_GPU", "1") == "1"


def cb_model(cfg, seed):
    from catboost import CatBoostClassifier
    depth = min(int(cfg.get("depth", 8)), 10)  # GPU-память: depth>10 на 674 фичах = OOM на 16GB
    kw = dict(iterations=cfg.get("it", ITERS), depth=depth,
              learning_rate=cfg.get("lr", 0.02), l2_leaf_reg=cfg.get("l2", 6.0),
              random_strength=cfg.get("rs", 1.0), loss_function="Logloss",
              verbose=False, random_seed=seed, border_count=128)
    if cfg.get("bagging_temperature") is not None:
        kw["bagging_temperature"] = cfg["bagging_temperature"]
    if cfg.get("acw"):
        kw["auto_class_weights"] = cfg["acw"]
    if GPU:
        kw["task_type"] = "GPU"; kw["devices"] = "0"
    return CatBoostClassifier(**kw)


def walk_forward(Xf, Y, ts, cfg, log=None):
    n = len(Y); fold = n // (N_FOLDS + 1)
    tns = ts.astype("datetime64[ns]"); proba = np.full(n, np.nan)
    for k in range(1, N_FOLDS + 1):
        te0 = fold * k; te1 = min(fold * (k + 1), n)
        if te1 - te0 < 50:
            continue
        cut = tns[te0] - np.timedelta64(PURGE)
        tr = tns < cut
        if tr.sum() < 400:
            continue
        m = cb_model(cfg, seed=k)
        m.fit(Xf[tr], Y[tr].astype(int))
        proba[te0:te1] = m.predict_proba(Xf[te0:te1])[:, 1]
        if log:
            log(f"      fold {k}: train {int(tr.sum())} -> test {te1-te0}")
    return proba


def acc_of(Y, proba, mask):
    return ((proba[mask] >= 0.5).astype(int) == Y[mask].astype(int)).mean()


def analyze(Y, proba, mask, vol, trend, base_up):
    y = Y[mask].astype(int); p = proba[mask]; pred = (p >= 0.5).astype(int)
    v = vol[mask]; tr = trend[mask]; conf = np.abs(p - 0.5)
    hi = conf >= np.quantile(conf, 0.66)
    hv = v >= np.median(v); up = tr > 0
    return {"overall": (pred == y).mean(), "pred_up": pred.mean(),
            "hc_acc": (pred[hi] == y[hi]).mean(), "hc_n": int(hi.sum()),
            "hivol": (pred[hv] == y[hv]).mean(), "lovol": (pred[~hv] == y[~hv]).mean(),
            "up": (pred[up] == y[up]).mean() if up.sum() else np.nan,
            "dn": (pred[~up] == y[~up]).mean() if (~up).sum() else np.nan}


def main():
    t0 = time.time()
    print("[load] sequences...", flush=True)
    X, Y, ts, syms, vol, trend = assemble()
    Xf = X.reshape(len(X), K * F)
    Xf = np.column_stack([Xf, vol, trend]).astype(np.float32)
    base_up = Y.mean(); maj = max(base_up, 1 - base_up)
    print(f"[data] {len(Y)} анкеров, {Xf.shape[1]} признаков (={K}×{F}+2), up-first {base_up*100:.1f}%, "
          f"GPU={GPU}", flush=True)

    out = []; A = out.append
    A("ФРАКТАЛЬНЫЙ ±5% — CatBoost-GPU, тяжёлый, само-исправление, критерий ACCURACY")
    A(f"Анкеров {len(Y)} (BTC/ETH/SOL), {Xf.shape[1]} лаг-признаков, горизонт 30д, AFML-пёрдж {PURGE.days}д, GPU={GPU}.")
    A(f"БАЗА up-first {base_up*100:.1f}% -> мажоритарный baseline {maj*100:.1f}%. 'Работает' = устойчиво > базы.\n")
    log = lambda m: print(m, flush=True)

    cfg = {"it": ITERS, "depth": 8, "lr": 0.02, "l2": 6.0, "rs": 1.0}
    print("[round 0] base CatBoost-GPU walk-forward...", flush=True)
    proba = walk_forward(Xf, Y, ts, cfg, log)
    mask = np.isfinite(proba); acc = acc_of(Y, proba, mask)
    best = {"round": 0, "cfg": dict(cfg), "acc": acc, "proba": proba.copy()}
    history = [(0, "база (depth8/it%d)" % ITERS, acc)]
    A("=== САМО-ИСПРАВЛЕНИЕ (раунды; OOS accuracy) ===")
    A(f"  раунд 0: база -> OOS acc {acc*100:.2f}% (база {maj*100:.2f}%)")
    print(f"[round 0] {acc*100:.2f}%", flush=True)

    tried = set()
    for r in range(1, N_ROUNDS + 1):
        d = analyze(Y, best["proba"], np.isfinite(best["proba"]), vol, trend, base_up)
        cand = dict(best["cfg"]); reason = ""
        if abs(d["pred_up"] - base_up) > 0.12 and "bal" not in tried:
            cand["acw"] = "Balanced"; tried.add("bal")
            reason = f"прогнозы перекошены (up {d['pred_up']*100:.0f}% vs база {base_up*100:.0f}%) -> auto_class_weights=Balanced"
        elif d["hc_acc"] > d["overall"] + 0.03 and "cap" not in tried:
            cand["depth"] = 10; cand["it"] = ITERS + 2000; tried.add("cap")
            reason = f"на уверенных {d['hc_acc']*100:.1f}% > общей {d['overall']*100:.1f}% -> ёмкость depth10 +итерации"
        elif "reg" not in tried:
            cand["l2"] = 2.0; cand["rs"] = 2.0; tried.add("reg")
            reason = "ошибки размазаны -> слабее l2(2) + random_strength(2) для тоньше границы"
        elif "lr" not in tried:
            cand["lr"] = 0.01; cand["it"] = ITERS + 4000; tried.add("lr")
            reason = "нет прироста -> мягче lr 0.01 + длиннее обучение"
        elif "deep" not in tried:
            cand["depth"] = 10; cand["bagging_temperature"] = 1.0; cand["it"] = ITERS + 3000; tried.add("deep")
            reason = "ёмкость depth10 + Байес-бэггинг + больше деревьев (GPU-память безопасно)"
        else:
            cand["acw"] = "Balanced"; cand["l2"] = 3.0
            reason = "комбинирую баланс + умеренную регуляризацию"
        print(f"[round {r}] {reason}", flush=True)
        pr = walk_forward(Xf, Y, ts, cand, log)
        mr = np.isfinite(pr); ar = acc_of(Y, pr, mr)
        imp = ar > best["acc"] + 0.003
        A(f"  раунд {r}: {reason}")
        A(f"           -> OOS acc {ar*100:.2f}% ({'ПРИНЯТО +%.2fпп' % ((ar-best['acc'])*100) if imp else 'ОТКАТ'})")
        history.append((r, reason, ar))
        if imp:
            best = {"round": r, "cfg": dict(cand), "acc": ar, "proba": pr.copy()}
        print(f"[round {r}] {ar*100:.2f}% {'KEEP' if imp else 'revert'}", flush=True)

    print("[control] shuffle-label...", flush=True)
    rng = np.random.default_rng(7); Ysh = rng.permutation(Y)
    psh = walk_forward(Xf, Ysh, ts, best["cfg"], None); msh = np.isfinite(psh)
    acc_sh = acc_of(Ysh, psh, msh)

    bp = best["proba"]; bm = np.isfinite(bp)
    d = analyze(Y, bp, bm, vol, trend, base_up)
    A(f"\n=== ЛУЧШИЙ (раунд {best['round']}) ===")
    A(f"  OOS accuracy {best['acc']*100:.2f}% | база {maj*100:.2f}% | лифт {(best['acc']-maj)*100:+.2f}пп")
    A(f"  shuffle-контроль {acc_sh*100:.2f}% (~{maj*100:.0f}% -> {'честно' if acc_sh < maj+0.02 else 'ПОДОЗРИТЕЛЬНО'})")
    A(f"  режимы: уверенные {d['hc_acc']*100:.1f}%(n={d['hc_n']}) | hi-vol {d['hivol']*100:.1f}% lo-vol {d['lovol']*100:.1f}% | "
      f"up {d['up']*100:.1f}% dn {d['dn']*100:.1f}%")
    A("  по активам:")
    for s in SYMBOLS:
        ms = bm & (syms == s)
        if ms.sum() > 50:
            A(f"    {s}: {acc_of(Y, bp, ms)*100:.1f}% (n={ms.sum()})")
    yr = pd.to_datetime(ts).year; goodyr = 0; toty = 0
    A("  по годам:")
    for Yr in sorted(set(yr[bm])):
        my = bm & (yr == Yr)
        if my.sum() > 40:
            a = acc_of(Y, bp, my); toty += 1; goodyr += a > maj + 0.01
            A(f"    {Yr}: {a*100:.1f}% (n={my.sum()})")

    # call-side дрейф-тест (наша стена: residual=drift живёт только в up-вызовах)
    predall = (bp[bm] >= 0.5).astype(int); yb = Y[bm].astype(int)
    upc = predall == 1; dnc = predall == 0
    precU = (yb[upc] == 1).mean() if upc.sum() else np.nan
    precD = (yb[dnc] == 0).mean() if dnc.sum() else np.nan
    drift_like = (precU - base_up) > (precD - (1 - base_up)) + 0.03
    A("  раскол по стороне ПРОГНОЗА (дрейф-тест):")
    A(f"    up-вызовы:   n={int(upc.sum()):5d} precision {precU*100:.1f}% (база {base_up*100:.1f}%, лифт {(precU-base_up)*100:+.1f}пп)")
    A(f"    down-вызовы: n={int(dnc.sum()):5d} precision {precD*100:.1f}% (база {(1-base_up)*100:.1f}%, лифт {(precD-(1-base_up))*100:+.1f}пп)")
    A(f"    -> {'АСИММЕТРИЯ сторон = БЫЧИЙ ДРЕЙФ (edge живёт в up-вызовах, не структура)' if drift_like else 'симметрично (обе стороны бьют свою базу) = не чистый дрейф'}")

    conf = np.abs(bp - 0.5); qthr = np.quantile(conf[bm], 0.66); hc = bm & (conf >= qthr)
    hc_acc = acc_of(Y, bp, hc); hc_gy = 0; hc_ty = 0; hc_ga = 0
    A(f"\n=== АБСТЕНЦИЯ: только уверенные |p-0.5|>={qthr:.3f} ===")
    A(f"  accuracy уверенных {hc_acc*100:.1f}% (n={hc.sum()}) vs база {maj*100:.1f}% лифт {(hc_acc-maj)*100:+.1f}пп")
    for Yr in sorted(set(yr[hc])):
        my = hc & (yr == Yr)
        if my.sum() > 25:
            a = acc_of(Y, bp, my); hc_ty += 1; hc_gy += a > maj + 0.02
            A(f"    {Yr}: {a*100:.1f}% (n={my.sum()})")
    for s in SYMBOLS:
        ms = hc & (syms == s)
        if ms.sum() > 40 and acc_of(Y, bp, ms) > maj + 0.02:
            hc_ga += 1
    A(f"  -> уверенные: {hc_gy}/{hc_ty} лет, {hc_ga}/3 активов > базы+2пп")
    hc_works = (hc_acc > maj + 0.03) and (hc_gy >= max(2, hc_ty - 1)) and (hc_ga >= 2)

    A("\n=== НЕТТО (±5% RR1, кост 0.14%RT~0.028R) ===")
    for thr in (0.0, 0.05, 0.10):
        sel = bm & (conf >= thr)
        if sel.sum() < 30:
            continue
        win = ((bp[sel] >= 0.5).astype(int) == Y[sel].astype(int))
        exp = win.mean() - (~win).mean() - COST_RT / BARRIER
        A(f"  |p-0.5|>={thr:.2f}: n={sel.sum():5d} acc/WR {win.mean()*100:5.1f}% netExp {exp:+.3f}R")

    works = (best["acc"] > maj + 0.02) and (acc_sh < maj + 0.02) and (goodyr >= max(2, toty - 1))
    A("\n=== ВЕРДИКТ (само-осознание) ===")
    if works:
        A(f"  РАБОТАЕТ: OOS acc {best['acc']*100:.1f}% устойчиво > базы {maj*100:.1f}% ({goodyr}/{toty} лет), shuffle чист.")
    elif hc_works:
        A(f"  РАБОТАЕТ УСЛОВНО (абстенция): всё = монетка ({best['acc']*100:.1f}%), но уверенные {hc_acc*100:.1f}% "
          f"устойчивы ({hc_gy}/{hc_ty} лет, {hc_ga}/3 акт.) -> торговать ТОЛЬКО уверенные.")
    else:
        A(f"  НЕ работает: best {best['acc']*100:.1f}% vs база {maj*100:.1f}% (годы {goodyr}/{toty}, shuffle {acc_sh*100:.1f}%, "
          f"уверенные {hc_gy}/{hc_ty}). Само-исправление честно перебрало баланс/ёмкость/регуляризацию/lr — без устойчивого прироста.")
        A("  ОСОЗНАНИЕ: симметричный ±5% first-passage от 12h-свечи = near-coin и для CatBoost-GPU на 672 лаг-признаках;")
        A("  совпадает с GRU-версией. Превышение базы возможно только утечкой (убрана пёрджем) или дрейфом (не структура).")
    A(f"\n  кривая само-исправления: " + " | ".join(f"R{r}:{a*100:.1f}%" for r, _, a in history))
    A(f"  время: {(time.time()-t0)/60:.1f} мин, GPU={GPU}")

    rep = HERE / "fractal_cb_gpu_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(14, 5))
        rs = [r for r, _, _ in history]; accs = [a * 100 for _, _, a in history]
        ax[0].plot(rs, accs, "o-", color="#1db954"); ax[0].axhline(maj * 100, color="#ef5350", ls="--", label=f"база {maj*100:.1f}%")
        ax[0].set_title("CatBoost-GPU: само-исправление"); ax[0].set_xlabel("раунд"); ax[0].set_ylabel("OOS acc %"); ax[0].legend(); ax[0].grid(alpha=0.2)
        ax[1].hist(bp[bm], bins=40, color="#f5a623"); ax[1].axvline(0.5, color="k", ls="--")
        ax[1].set_title(f"p(up-first), OOS acc {best['acc']*100:.1f}%"); ax[1].grid(alpha=0.2)
        fig.tight_layout(); fig.savefig(HERE / "fractal_cb_gpu.png", dpi=120)
        print(f"\n[ok] -> {rep.name} + fractal_cb_gpu.png")
    except Exception as ex:
        print(f"[plot skip] {ex}")


if __name__ == "__main__":
    main()
