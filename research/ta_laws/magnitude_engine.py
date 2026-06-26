"""МОДУЛЬ МАГНИТУДЫ — предсказываем РАЗМЕР предстоящего хода 12h-свечи (не направление).

Идея (после диалога про монетку): направление ±5% = монетка (определяющая инфа в будущем). НО магнитуда =
«сила броска/обороты» физически ОПРЕДЕЛЕНА настоящим состоянием — вола кластеризуется, сжатие→экспансия.
Здесь классы («большой ход» vs «тихо») должны иметь РАЗНЫЕ отпечатки в фичах = настоящие «кошки/собаки».

Цель: на close 12h-свечи (цена P) предсказать forward range за следующие H баров:
  fwd_range = (max(high[i+1..i+H]) - min(low[i+1..i+H])) / P * 100   (в %).
Две формы: регрессия (Spearman) + классификация «выше обычного» (Правильно/Неправильно).

ЧЕСТНОСТЬ (наши стены):
  • непересекающиеся якоря (step=H) -> нет автокорр-миража;
  • walk-forward + purge; shuffle-контроль; cross-asset; год-стабильность;
  • ГЛАВНЫЙ baseline = «просто текущий ATR» (вола-персистентность) — он достижим в реале и уже сильный.
    «Работает» = бьём не монетку (это легко), а ATR-персистентность; иначе edge = тривиальное «вола липкая»;
  • разделимость классов меряем Cohen's d (а не AUC) и сравниваем magnitude-цель vs direction-цель на ТЕХ ЖЕ фичах.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/magnitude_engine.py
Выход: research/ta_laws/magnitude_engine_report.txt + .png
"""
from __future__ import annotations
import sys, os
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
H = int(os.environ.get("MAG_H", 4))            # горизонт хода (12h-баров) = 2 дня
STEP = H                                         # непересекающиеся якоря
N_FOLDS = 6
GPU = os.environ.get("MAG_GPU", "0") == "1"     # по умолчанию CPU (GPU занят direction-прогоном)
FEATS = ["atr_pct", "atr_pctile", "rstd6", "rstd12", "rstd24", "volofvol", "park",
         "bbw", "bbw_pctile", "rangec", "nquiet", "inside3", "volz", "qvolz", "ntrz",
         "dabs", "cvdabs", "rpos", "dist_liq", "absret3", "absret6", "session", "dow"]


def load_flow(sym, tf):
    df = pd.read_csv(DATA / f"{sym}_{tf}_flow.csv")
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df.sort_values("open_time").reset_index(drop=True)


def rmean(a, n):
    return pd.Series(a).rolling(n, min_periods=max(2, n // 3)).mean().values


def rstd(a, n):
    return pd.Series(a).rolling(n, min_periods=max(2, n // 3)).std().values


def build(sym):
    h = load_flow(sym, "12h")
    O, Hi, Lo, C, V = (h[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    qv = h["quote_volume"].values.astype(float); nt = h["trades"].values.astype(float)
    delta = h["delta"].values.astype(float); cvd = h["cvd"].values.astype(float)
    n = len(h)
    atr = G.compute_atr(pd.DataFrame({"high": Hi, "low": Lo, "close": C}))
    atr_pct = np.where(C > 0, atr / C * 100, np.nan)
    atr_pctile = pd.Series(atr_pct).rolling(200, min_periods=30).apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    logret = np.zeros(n); logret[1:] = np.log(C[1:] / np.clip(C[:-1], 1e-9, None))
    rstd6 = rstd(logret, 6) * 100; rstd12 = rstd(logret, 12) * 100; rstd24 = rstd(logret, 24) * 100
    volofvol = rstd(atr_pct, 12)
    park = np.sqrt(rmean((np.log(np.clip(Hi / np.clip(Lo, 1e-9, None), 1e-9, None)) ** 2) / (4 * np.log(2)), 6)) * 100
    ma20 = rmean(C, 20); sd20 = rstd(C, 20); bbw = np.where(ma20 > 0, 4 * sd20 / ma20 * 100, np.nan)
    bbw_pctile = pd.Series(bbw).rolling(200, min_periods=30).apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    hl = Hi - Lo
    rng6 = pd.Series(Hi).rolling(6).max().values - pd.Series(Lo).rolling(6).min().values
    rng24 = pd.Series(Hi).rolling(24).max().values - pd.Series(Lo).rolling(24).min().values
    rangec = np.where(rng24 > 0, rng6 / rng24, np.nan)
    big_move = (np.abs(logret) * 100) > (1.5 * atr_pct)
    nquiet = np.zeros(n)
    cnt = 0
    for i in range(n):
        cnt = 0 if big_move[i] else cnt + 1
        nquiet[i] = cnt
    inside = np.zeros(n, bool)
    inside[1:] = (Hi[1:] <= Hi[:-1]) & (Lo[1:] >= Lo[:-1])
    inside3 = pd.Series(inside.astype(float)).rolling(3, min_periods=1).sum().values
    volz = (V - rmean(V, 50)) / (rstd(V, 50) + 1e-9)
    qvolz = (qv - rmean(qv, 50)) / (rstd(qv, 50) + 1e-9)
    ntrz = (nt - rmean(nt, 50)) / (rstd(nt, 50) + 1e-9)
    dabs = np.abs(delta) / (V + 1e-9)
    base = rmean(np.abs(delta), 50) + 1e-9
    cvdabs = np.zeros(n); cvdabs[3:] = np.abs(cvd[3:] - cvd[:-3]) / base[3:]
    lo50 = pd.Series(Lo).rolling(50).min().values; hi50 = pd.Series(Hi).rolling(50).max().values
    rpos = (C - lo50) / np.clip(hi50 - lo50, 1e-9, None)
    # дистанция до ближайшего недавнего экстремума (магнит) в %
    dist_liq = np.minimum(np.abs(hi50 - C), np.abs(C - lo50)) / np.clip(C, 1e-9, None) * 100
    absret3 = np.zeros(n); absret3[3:] = np.abs(C[3:] - C[:-3]) / C[:-3] * 100
    absret6 = np.zeros(n); absret6[6:] = np.abs(C[6:] - C[:-6]) / C[:-6] * 100
    dt = pd.to_datetime(h["open_time"])
    session = (dt.dt.hour >= 12).astype(float).values
    dow = dt.dt.dayofweek.values.astype(float)

    Feat = np.column_stack([atr_pct, atr_pctile, rstd6, rstd12, rstd24, volofvol, park,
                            bbw, bbw_pctile, rangec, nquiet, inside3, volz, qvolz, ntrz,
                            dabs, cvdabs, rpos, dist_liq, absret3, absret6, session, dow])

    rows = []
    for i in range(60, n - H - 1, STEP):
        if not np.isfinite(Feat[i]).all() or not np.isfinite(C[i]) or C[i] <= 0:
            continue
        fh = Hi[i + 1:i + 1 + H].max(); fl = Lo[i + 1:i + 1 + H].min()
        fwd_range = (fh - fl) / C[i] * 100
        up_exc = (fh - C[i]) / C[i] * 100; dn_exc = (C[i] - fl) / C[i] * 100
        fwd_dir = 1 if (C[i + H] - C[i]) > 0 else 0
        hit5 = 1 if (up_exc >= 5 or dn_exc >= 5) else 0
        rows.append({"sym": sym, "ts": h["open_time"].values[i], "fwd_range": fwd_range,
                     "fwd_dir": fwd_dir, "hit5": hit5,
                     **{f: Feat[i][j] for j, f in enumerate(FEATS)}})
    return rows


def spearman(a, b):
    ra = pd.Series(a).rank().values; rb = pd.Series(b).rank().values
    if np.std(ra) == 0 or np.std(rb) == 0:
        return np.nan
    return np.corrcoef(ra, rb)[0, 1]


def cohens_d(x, ybin):
    a = x[ybin == 1]; b = x[ybin == 0]
    if len(a) < 5 or len(b) < 5:
        return np.nan
    sp = np.sqrt(((len(a) - 1) * a.std() ** 2 + (len(b) - 1) * b.std() ** 2) / (len(a) + len(b) - 2))
    return (a.mean() - b.mean()) / (sp + 1e-12)


def cb(reg, seed):
    from catboost import CatBoostRegressor, CatBoostClassifier
    kw = dict(iterations=1200, depth=6, learning_rate=0.03, l2_leaf_reg=5,
              verbose=False, random_seed=seed)
    if GPU:
        kw["task_type"] = "GPU"; kw["devices"] = "0"
    return CatBoostRegressor(loss_function="RMSE", **kw) if reg else CatBoostClassifier(loss_function="Logloss", **kw)


VOL_FEATS = ["atr_pct", "atr_pctile", "rstd6", "rstd12", "rstd24", "park", "bbw", "bbw_pctile", "volofvol"]


def walk_forward(df, target, reg, feats=FEATS):
    d = df.sort_values("ts").reset_index(drop=True)
    X = d[feats].values; y = d[target].values
    tns = d["ts"].values.astype("datetime64[ns]")
    n = len(d); fold = n // (N_FOLDS + 1)
    pred = np.full(n, np.nan)
    purge = np.timedelta64(H * 12, "h")
    for k in range(1, N_FOLDS + 1):
        te0 = fold * k; te1 = min(fold * (k + 1), n)
        if te1 - te0 < 30:
            continue
        tr = tns < (tns[te0] - purge)
        if tr.sum() < 200:
            continue
        m = cb(reg, k); m.fit(X[tr], y[tr] if reg else y[tr].astype(int))
        pred[te0:te1] = m.predict(X[te0:te1]) if reg else m.predict_proba(X[te0:te1])[:, 1]
    return d, pred, np.isfinite(pred)


def main():
    rows = []
    for s in SYMBOLS:
        print(f"[{s}] build...", flush=True); rows += build(s)
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    df["year"] = pd.to_datetime(df.ts).dt.year
    # классы «выше обычного» по КАУЗАЛЬНОЙ расширяющейся медиане
    med = df["fwd_range"].expanding(min_periods=100).median().shift(1)
    df["y_big"] = (df["fwd_range"] > med).astype(float)
    df = df.dropna(subset=["y_big"]).reset_index(drop=True)
    base_big = df.y_big.mean()
    print(f"[data] {len(df)} непересек. якорей (H={H}=2дня), fwd_range медиана {df.fwd_range.median():.1f}%, "
          f"P(±5% за {H} баров)={df.hit5.mean()*100:.0f}%", flush=True)

    out = []; A = out.append
    A("МОДУЛЬ МАГНИТУДЫ — размер предстоящего хода 12h-свечи (НЕ направление). Критерий: accuracy + Spearman.")
    A(f"Якорей {len(df)} (BTC/ETH/SOL, непересек., H={H}=2дня). fwd_range медиана {df.fwd_range.median():.1f}%, "
      f"P(ход ±5% за 2дня)={df.hit5.mean()*100:.0f}%.")
    A(f"GPU={GPU}. Baseline-1: монетка/мажоритар. Baseline-2 (главный): текущий ATR (вола-персистентность).\n")

    # === 1. РАЗДЕЛИМОСТЬ: кошки/собаки. Cohen's d фич для magnitude vs direction ===
    A("=== 1. РАЗДЕЛИМОСТЬ КЛАССОВ (Cohen's d; |d|>0.5 = классы реально расходятся) ===")
    A(f"{'фича':12} {'d(big vs тихо)':>16} {'d(up vs down)':>16}")
    drows = []
    for f in FEATS:
        d_mag = cohens_d(df[f].values, df.y_big.values)
        d_dir = cohens_d(df[f].values, df.fwd_dir.values)
        drows.append((f, d_mag, d_dir))
    for f, dm, dd in sorted(drows, key=lambda r: -abs(r[1]))[:10]:
        A(f"{f:12} {dm:>16.2f} {dd:>16.2f}")
    sep_mag = np.nanmean([abs(r[1]) for r in drows]); sep_dir = np.nanmean([abs(r[2]) for r in drows])
    A(f"  средн|d|: магнитуда {sep_mag:.2f}  vs  направление {sep_dir:.2f}  -> "
      f"{'МАГНИТУДА разделима, направление НЕТ (кошки/собаки найдены!)' if sep_mag > sep_dir + 0.15 else 'разделимость сопоставима'}")

    # === 2. РЕГРЕССИЯ: предсказываем размер хода, бьём ли ATR ===
    A("\n=== 2. РЕГРЕССИЯ forward range (Spearman OOS, чем выше тем лучше) ===")
    d, pr, m = walk_forward(df, "fwd_range", reg=True)
    sp_model = spearman(pr[m], d["fwd_range"].values[m])
    sp_atr = spearman(d["atr_pct"].values[m], d["fwd_range"].values[m])
    A(f"  модель:            Spearman {sp_model:.3f}")
    A(f"  baseline тек.ATR:  Spearman {sp_atr:.3f}")
    A(f"  -> {'модель БЬЁТ ATR (+%.3f) = есть структура сверх воло-персистентности' % (sp_model-sp_atr) if sp_model > sp_atr + 0.02 else 'модель ~ ATR: магнитуда предсказуема, но в осн. = липкость волы (тоже реально)'}")

    # === 3. КЛАССИФИКАЦИЯ big vs тихо: ПРАВИЛЬНО/НЕПРАВИЛЬНО ===
    A("\n=== 3. КЛАССИФИКАЦИЯ «ход выше обычного» (accuracy OOS) ===")
    dc, pc, mc = walk_forward(df, "y_big", reg=False)
    yb = dc.y_big.values.astype(int)
    acc = ((pc[mc] >= 0.5).astype(int) == yb[mc]).mean()
    maj = max(base_big, 1 - base_big)
    # baseline вола-персистентность: большой ход если atr_pctile>=0.5
    atrp = dc.atr_pctile.values
    acc_atr = ((atrp[mc] >= 0.5).astype(int) == yb[mc]).mean()
    # ЧЕСТНЫЙ baseline: модель ТОЛЬКО на воло-фичах (полная воло-персистентность)
    dv, pv, mv = walk_forward(df, "y_big", reg=False, feats=VOL_FEATS)
    acc_vol = ((pv[mv] >= 0.5).astype(int) == dv.y_big.values[mv].astype(int)).mean()
    A(f"  baseline монетка/мажор:            {maj*100:.1f}%")
    A(f"  baseline тек.ATR>медианы (груб.):  {acc_atr*100:.1f}%")
    A(f"  baseline ВОЛА-модель (чест.):      {acc_vol*100:.1f}%  <- настоящая воло-персистентность")
    A(f"  МОДЕЛЬ (вся физика):               {acc*100:.1f}%  (vs монетка {(acc-maj)*100:+.1f}пп, vs ВОЛА-модель {(acc-acc_vol)*100:+.1f}пп)")

    # shuffle-контроль
    rng = np.random.default_rng(7)
    ds = df.copy(); ds["y_big"] = rng.permutation(df.y_big.values)
    _, psh, msh = walk_forward(ds, "y_big", reg=False)
    acc_sh = ((psh[msh] >= 0.5).astype(int) == ds.y_big.values[msh].astype(int)).mean()
    A(f"  shuffle-контроль:              {acc_sh*100:.1f}% (~{maj*100:.0f}% -> {'честно' if acc_sh < maj+0.03 else 'ПОДОЗРИТЕЛЬНО'})")

    # cross-asset + год (по классификации)
    A("  accuracy по активам / по годам:")
    for s in SYMBOLS:
        ms = mc & (dc.sym.values == s)
        if ms.sum() > 40:
            A(f"    {s}: модель {((pc[ms]>=0.5).astype(int)==yb[ms]).mean()*100:.1f}% | ATR {((atrp[ms]>=0.5).astype(int)==yb[ms]).mean()*100:.1f}%")
    yr = pd.to_datetime(dc.ts).dt.year.values; gy = 0; ty = 0
    for Y in sorted(set(yr[mc])):
        mm = mc & (yr == Y)
        if mm.sum() > 30:
            a = ((pc[mm] >= 0.5).astype(int) == yb[mm]).mean(); ty += 1; gy += a > maj + 0.03
            A(f"    {Y}: {a*100:.1f}% (n={mm.sum()})")

    # importance (что «выучил» как драйверы магнитуды)
    try:
        from catboost import CatBoostClassifier
        mfull = cb(False, 1); mfull.fit(df[FEATS].values, df.y_big.values.astype(int))
        imp = sorted(zip(FEATS, mfull.feature_importances_), key=lambda x: -x[1])[:8]
        A("\n=== 4. ДРАЙВЕРЫ магнитуды (importance) ===")
        for f, v in imp:
            A(f"    {f:12} {v:.1f}")
    except Exception as ex:
        A(f"[imp skip] {ex}")

    # вердикт
    works = (acc > maj + 0.05) and (acc_sh < maj + 0.03) and (gy >= max(3, ty - 1))
    beats_vol = (acc > acc_vol + 0.02) and (sp_model > sp_atr + 0.02)
    A("\n=== ВЕРДИКТ ===")
    if works and beats_vol:
        A(f"  РАБОТАЕТ И БЬЁТ ВОЛУ: магнитуда предсказуема ({acc*100:.0f}% vs монетка {maj*100:.0f}%), и модель добавляет "
          f"структуру сверх воло-персистентности (vs вола-модель {acc_vol*100:.0f}%). Настоящие 'кошки/собаки'.")
    elif works:
        A(f"  РАБОТАЕТ, но edge = ВОЛА: магнитуда предсказуема ({acc*100:.0f}% vs монетка {maj*100:.0f}%, {gy}/{ty} лет, "
          f"shuffle чист), ОДНАКО вола-модель уже даёт {acc_vol*100:.0f}% и регрессия модель {sp_model:.2f} ~ ATR {sp_atr:.2f} -> "
          f"прирост сверх липкости-волы мал. Edge РЕАЛЬНЫЙ, но это в основном кластеризация волатильности, не доп.структура.")
    else:
        A(f"  Магнитуда предсказуема слабее ожидаемого (модель {acc*100:.0f}%, вола {acc_vol*100:.0f}%, монетка {maj*100:.0f}%).")
    A(f"  ПРИМЕНЕНИЕ: магнитуда != направление. Это фильтр РЕЖИМА (экспансия vs тихо) -> когда уместен брейкаут/"
      f"стрэддл vs мин-реверсия; sizing/вход-тайминг каскадов; НЕ говорит КУДА, говорит НАСКОЛЬКО.")

    rep = HERE / "magnitude_engine_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))

    # === график: разделимость (кошки/собаки) ===
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        top = [r[0] for r in sorted(drows, key=lambda r: -abs(r[1]))[:3]]
        fig, ax = plt.subplots(2, 3, figsize=(16, 9))
        for j, f in enumerate(top):
            x = df[f].values
            lo, hi = np.nanpercentile(x, [1, 99]); bins = np.linspace(lo, hi, 40)
            # верх: magnitude (расходятся)
            ax[0, j].hist(x[df.y_big == 1], bins=bins, alpha=0.55, density=True, color="#ef5350", label="большой ход")
            ax[0, j].hist(x[df.y_big == 0], bins=bins, alpha=0.55, density=True, color="#4a90d9", label="тихо")
            ax[0, j].set_title(f"МАГНИТУДА · {f} (d={cohens_d(x, df.y_big.values):.2f})"); ax[0, j].legend(fontsize=7)
            # низ: direction (совпадают)
            ax[1, j].hist(x[df.fwd_dir == 1], bins=bins, alpha=0.55, density=True, color="#1db954", label="вверх")
            ax[1, j].hist(x[df.fwd_dir == 0], bins=bins, alpha=0.55, density=True, color="#9b59b6", label="вниз")
            ax[1, j].set_title(f"НАПРАВЛЕНИЕ · {f} (d={cohens_d(x, df.fwd_dir.values):.2f})"); ax[1, j].legend(fontsize=7)
        fig.suptitle("Кошки/собаки: магнитуда — классы РАСХОДЯТСЯ (верх), направление — СОВПАДАЮТ (низ)", fontsize=13)
        fig.tight_layout(); fig.savefig(HERE / "magnitude_engine.png", dpi=110)
        print(f"\n[ok] -> {rep.name} + magnitude_engine.png")
    except Exception as ex:
        print(f"[plot skip] {ex}")


if __name__ == "__main__":
    main()
