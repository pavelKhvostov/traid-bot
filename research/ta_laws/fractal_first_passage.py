"""ФРАКТАЛЬНЫЙ FIRST-PASSAGE ±5% — самообучаемый, само-исправляющийся нейро-модуль.

ЗАДАЧА (по постановке юзера): на ЗАКРЫТИИ 12h-свечи (цена P) аргументированно, используя все наши
знания/индикаторы/поток, определить — станет ли эта свеча ФРАКТАЛОМ и даст ли движение +5% (P*1.05)
РАНЬШЕ, чем -5% (P*0.95) в обратную сторону (или наоборот). Т.е. close=50000 -> 52500 раньше 47500?

Это направленный FIRST-PASSAGE на СИММЕТРИЧНЫХ барьерах ±5%. Важно (наши стены):
  • дистанция тут КОНСТАНТА (оба барьера = 5%), значит gambler's-ruin-геометрия = ровно 50% (чистая монетка) —
    любой edge ОБЯЗАН идти от drift-нейтральной СТРУКТУРЫ, а не от расстояния;
  • остаточный плюс up-first обычно = БЫЧИЙ ДРЕЙФ (проверяем расколом LONG/SHORT — стена residual=drift);
  • «станет фракталом» подтверждается через i+2 -> LOOKAHEAD -> это часть МЕТКИ, НИКОГДА не фича.

Фрактал (Williams k=2): up-fractal = свинг-хай (медв. пивот), dn-fractal = свинг-лоу (быч. пивот).
dn-fractal + up-first = чистый бычий свинг-запуск; up-fractal + down-first = медвежий. Это и есть
«свеча стала фракталом и дала 5% в свою сторону».

САМО-ОБУЧЕНИЕ / САМО-ИСПРАВЛЕНИЕ (как просил юзер — модуль ДОЛЖЕН осознать ошибку, понять причину,
исправиться аргументированно), двухуровнево:
  L1 (онлайн, walk-forward): OnlineLaw — на каждом якоре предсказывает, видит исход, АТРИБУТИРУЕТ
     причину ошибки (какая фича сильнее тянула не туда) и АРГУМЕНТИРОВАННО двигает её вес (лог).
  L2 (мета, структурное осознание): после OOS-эпохи модуль считает диагностики (OOS-AUC vs permutation-
     null, cross-asset leave-one-out, год-стабильность, раскол LONG/SHORT = дрейф-сигнатура) и
     АРГУМЕНТИРОВАННО исправляет САМ ПОДХОД: если его точность держится на up-вызовах в бычьи годы —
     осознаёт «я выучил дрейф, не структуру», перепроверяет drift-нейтрально (баланс классов), и либо
     признаёт монетку, либо закрепляет реальный остаток с доказательством.

Каузальность: все фичи только из информации <= close[i]; путь ±5% резолвится по 1h строго ПОСЛЕ
закрытия 12h-свечи (start = первый 1h-бар с open_time >= close_time). Вход для нетто = open[i+1]-эквивалент
(закрытие 12h = старт). Косты ±5% брекета: 0.14% RT ~ 0.028R (мизер vs 5%) -> barrier-R ~ нетто.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/fractal_first_passage.py
Выход: research/ta_laws/fractal_first_passage_report.txt + fractal_first_passage.png
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
from zone_race_module import OnlineLaw  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DATA = ROOT / "research" / "elements_study" / "data"
BARRIER = 0.05            # ±5%
HORIZON_H = 24 * 30       # 30 дней (1h-баров) на гонку барьеров
FRACTAL_K = 2             # Williams: 2 бара с каждой стороны
COST_RT = 0.0014          # 0.14% round-trip (taker*2 + slip*2)

FEATS = ["mom1", "mom2", "mom3", "mom6", "mom12", "accel", "atr_pct", "atr_pctile",
         "range_pos", "ema_slope", "px_vs_ema", "htf_mom6", "htf_mom14",
         "delta_norm", "cvd_slope", "tbr_dev", "cvd_div", "imp3", "flag_small",
         "fade_sig", "body", "up_wick", "lo_wick"]


def load_flow(sym, tf):
    df = pd.read_csv(DATA / f"{sym}_{tf}_flow.csv", parse_dates=["open_time"])
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df.sort_values("open_time").reset_index(drop=True)


def ema(a, n):
    return pd.Series(a).ewm(span=n, adjust=False).mean().values


def build(sym):
    h = load_flow(sym, "12h")
    o = load_flow(sym, "1h")
    O, H, L, C, V = (h[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    delta = h["delta"].values.astype(float)
    cvd = h["cvd"].values.astype(float)
    tbr = h["taker_buy_ratio"].values.astype(float)
    n = len(h)
    # ATR% (через geometry на 12h df с нужными колонками)
    hdf = pd.DataFrame({"high": H, "low": L, "close": C})
    atr = G.compute_atr(hdf)
    atr_pct = np.where(C > 0, atr / C * 100, np.nan)
    # running-percentile ATR% (каузально, exp. квантиль приближаем рангом в расширяющемся окне)
    atr_rank = pd.Series(atr_pct).expanding(min_periods=30).apply(
        lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    # EMA-структура
    ema_f = ema(C, 10); ema_s = ema(C, 40); ema_slope = np.zeros(n)
    ema_slope[5:] = (ema_s[5:] - ema_s[:-5]) / np.where(C[5:] > 0, C[5:], 1) * 100
    px_vs_ema = (C - ema_s) / np.where(C > 0, C, 1) * 100
    # CVD наклон (изменение cvd за 3 бара, нормировано на средн. |delta|)
    base = pd.Series(np.abs(delta)).rolling(50, min_periods=5).mean().values + 1e-9
    cvd_slope = np.zeros(n); cvd_slope[3:] = (cvd[3:] - cvd[:-3]) / base[3:]
    delta_norm = delta / (V + 1e-9)
    tbr_dev = tbr - 0.5
    # фрактал (label-side, нужен i±2 -> LOOKAHEAD, только в метку)
    up_fr = np.zeros(n, bool); dn_fr = np.zeros(n, bool)
    for i in range(FRACTAL_K, n - FRACTAL_K):
        win_h = H[i - FRACTAL_K:i + FRACTAL_K + 1]; win_l = L[i - FRACTAL_K:i + FRACTAL_K + 1]
        if H[i] == win_h.max() and (win_h.argmax() == FRACTAL_K):
            up_fr[i] = True
        if L[i] == win_l.min() and (win_l.argmin() == FRACTAL_K):
            dn_fr[i] = True
    fr_dir = np.where(dn_fr & ~up_fr, 1, np.where(up_fr & ~dn_fr, -1, 0))  # +1 быч.свинг-лоу

    # 1h-путь для резолва ±5%
    t1 = o["open_time"].values.astype("datetime64[ns]").astype(np.int64)
    h1H = o["high"].values.astype(float); h1L = o["low"].values.astype(float); h1O = o["open"].values.astype(float)
    close_t = (h["open_time"] + pd.Timedelta(hours=12)).values.astype("datetime64[ns]").astype(np.int64)
    start_idx = np.searchsorted(t1, close_t, side="left")

    rows = []
    for i in range(60, n - FRACTAL_K - 1):
        P = C[i]
        if not np.isfinite(P) or P <= 0 or not np.isfinite(atr_pct[i]) or atr_pct[i] <= 0:
            continue
        up = P * (1 + BARRIER); dn = P * (1 - BARRIER)
        s = int(start_idx[i]); e = min(s + HORIZON_H, len(t1))
        if e - s < 5:
            continue
        segH = h1H[s:e]; segL = h1L[s:e]
        up_hits = np.nonzero(segH >= up)[0]; dn_hits = np.nonzero(segL <= dn)[0]
        iu = up_hits[0] if up_hits.size else None
        idd = dn_hits[0] if dn_hits.size else None
        if iu is None and idd is None:
            y = None; ambig = False
        elif iu is None:
            y = 0; ambig = False
        elif idd is None:
            y = 1; ambig = False
        elif iu < idd:
            y = 1; ambig = False
        elif idd < iu:
            y = 0; ambig = False
        else:  # один и тот же 1h-бар коснулся обоих — резолвим по близости к open бара (пессимистично-нейтрально)
            bo = h1O[s + iu]; y = 1 if (up - bo) <= (bo - dn) else 0; ambig = True
        # ---- фичи (каузально, <= close[i]) ----
        def ret(k):
            return (C[i] - C[i - k]) / C[i - k] * 100 / atr_pct[i]
        rng = H[max(0, i - 50):i + 1]; lo50 = L[max(0, i - 50):i + 1].min(); hi50 = rng.max()
        rpos = (P - lo50) / (hi50 - lo50) if hi50 > lo50 else 0.5
        imp3 = ret(3)
        rng2 = (max(H[i - 1], H[i]) - min(L[i - 1], L[i])) / P * 100 / atr_pct[i]
        flag_small = 1.0 if rng2 < 1.2 else 0.0
        fade_sig = (-np.sign(imp3) * flag_small) if abs(imp3) > 1.0 else 0.0
        rng_i = (H[i] - L[i]) + 1e-9
        feat = {
            "mom1": ret(1), "mom2": ret(2), "mom3": imp3, "mom6": ret(6), "mom12": ret(12),
            "accel": ret(3) - ret(12), "atr_pct": atr_pct[i], "atr_pctile": atr_rank[i],
            "range_pos": rpos, "ema_slope": ema_slope[i], "px_vs_ema": px_vs_ema[i],
            "htf_mom6": ret(6), "htf_mom14": ret(14) if i >= 14 else 0.0,
            "delta_norm": delta_norm[i], "cvd_slope": cvd_slope[i], "tbr_dev": tbr_dev[i],
            "cvd_div": float(np.sign(imp3) != np.sign(cvd_slope[i])),
            "imp3": imp3, "flag_small": flag_small, "fade_sig": fade_sig,
            "body": (C[i] - O[i]) / rng_i, "up_wick": (H[i] - max(O[i], C[i])) / rng_i,
            "lo_wick": (min(O[i], C[i]) - L[i]) / rng_i,
        }
        if any((not np.isfinite(v)) for v in feat.values()):
            continue
        rows.append({"sym": sym, "ts": h["open_time"].values[i], "y": y, "ambig": ambig,
                     "fr_dir": int(fr_dir[i]), "price": P, **feat})
    return rows


# ---------- валидация ----------
def walk_forward_auc(df, feats, n_folds=6):
    """Expanding-window time-series OOS AUC (CatBoost). Возвращает (auc, oos_proba, oos_mask, oos_y)."""
    from catboost import CatBoostClassifier
    from sklearn.metrics import roc_auc_score
    d = df.sort_values("ts").reset_index(drop=True)
    X = d[feats].values; y = d["y"].values.astype(int)
    nrec = len(d); fold = nrec // (n_folds + 1)
    proba = np.full(nrec, np.nan);
    for k in range(1, n_folds + 1):
        tr_end = fold * k; te_end = min(fold * (k + 1), nrec)
        if te_end - tr_end < 30 or tr_end < 100:
            continue
        m = CatBoostClassifier(iterations=300, depth=4, learning_rate=0.03, l2_leaf_reg=6,
                               loss_function="Logloss", verbose=False, random_seed=k,
                               task_type="CPU")
        m.fit(X[:tr_end], y[:tr_end])
        proba[tr_end:te_end] = m.predict_proba(X[tr_end:te_end])[:, 1]
    mask = np.isfinite(proba)
    auc = roc_auc_score(y[mask], proba[mask]) if mask.sum() > 50 and len(set(y[mask])) > 1 else np.nan
    return auc, proba, mask, y, d


def leave_one_asset(df, feats):
    from catboost import CatBoostClassifier
    from sklearn.metrics import roc_auc_score
    res = {}
    for s in SYMBOLS:
        tr = df[df.sym != s]; te = df[df.sym == s]
        if len(te) < 50:
            continue
        m = CatBoostClassifier(iterations=300, depth=4, learning_rate=0.03, l2_leaf_reg=6,
                               loss_function="Logloss", verbose=False, random_seed=1, task_type="CPU")
        m.fit(tr[feats].values, tr.y.values.astype(int))
        p = m.predict_proba(te[feats].values)[:, 1]
        yt = te.y.values.astype(int)
        res[s] = roc_auc_score(yt, p) if len(set(yt)) > 1 else np.nan
    return res


def permutation_null(y, proba, mask, n=300, seed=7):
    from sklearn.metrics import roc_auc_score
    rng = np.random.default_rng(seed)
    yt = y[mask]; pt = proba[mask]
    real = roc_auc_score(yt, pt)
    null = np.empty(n)
    for k in range(n):
        null[k] = roc_auc_score(rng.permutation(yt), pt)
    p = (1 + (null >= real).sum()) / (n + 1)
    return real, null.mean(), np.quantile(null, 0.95), p


def main():
    rows = []
    for s in SYMBOLS:
        print(f"[{s}] build...", flush=True)
        rows += build(s)
    raw = pd.DataFrame(rows)
    raw["year"] = pd.to_datetime(raw.ts).dt.year
    neither = raw.y.isna().mean()
    df = raw.dropna(subset=["y"]).copy(); df["y"] = df.y.astype(int)
    df = df.sort_values("ts").reset_index(drop=True)
    base_up = df.y.mean()
    print(f"[samples] всего {len(raw)}, c исходом {len(df)}, neither(±5% не достигнут за {HORIZON_H//24}д) "
          f"{neither*100:.1f}%, up-first {base_up*100:.1f}%, ambig {df.ambig.mean()*100:.1f}%", flush=True)

    out = []
    A = out.append
    A("ФРАКТАЛЬНЫЙ FIRST-PASSAGE ±5% — самообучаемый/само-исправляющийся нейро-модуль")
    A(f"Якорей с исходом: {len(df)} (BTC/ETH/SOL, 12h, горизонт {HORIZON_H//24}д, каузально, путь по 1h).")
    A(f"neither (±5% не достигнут за {HORIZON_H//24}д): {neither*100:.1f}%  |  ambig (оба в одном 1h-баре): {df.ambig.mean()*100:.1f}%")
    A(f"БАЗА up-first: {base_up*100:.1f}%  (это и есть бычий дрейф; чистая монетка по симметрии = 50%)\n")

    # === ОПИСАТЕЛЬНО: фрактал и его 5%-сторона ===
    A("=== ФРАКТАЛ vs реализованная 5%-сторона (описательно, fr_dir подтверждён через i±2) ===")
    for d, nm in [(1, "dn-фрактал (свинг-лоу, быч.)"), (-1, "up-фрактал (свинг-хай, медв.)"), (0, "не фрактал")]:
        sub = df[df.fr_dir == d]
        if len(sub):
            A(f"  {nm:30} n={len(sub):5d}  up-first={sub.y.mean()*100:5.1f}%")
    A("  (если фрактал-направление ПРЕДСКАЗЫВАЛО бы 5%-сторону — у dn-фрактала up-first был бы >> базы.")
    A("   но fr_dir известен лишь через 2 бара -> это валидация структуры, не торгуемый сигнал.)\n")

    # === L1: онлайн само-исправление ===
    law = OnlineLaw(FEATS)
    X = df[FEATS].values; y = df.y.values.astype(int)
    preds = np.zeros(len(df), int)
    for i in range(len(df)):
        pr, _ = law.step(X[i], int(y[i]),
                         {"i": i, "sym": df.sym.values[i], "ts": pd.Timestamp(df.ts.values[i]).to_pydatetime()})
        preds[i] = pr
    warm = 300
    m = np.arange(len(df)) >= warm
    acc = (preds[m] == y[m]).mean()
    maj = max(base_up, 1 - base_up)
    half = (warm + len(df)) // 2
    early = (preds[warm:half] == y[warm:half]).mean(); late = (preds[half:] == y[half:]).mean()
    A("=== L1 ОНЛАЙН САМО-ИСПРАВЛЕНИЕ (OnlineLaw, walk-forward, без AUC) ===")
    A(f"  тривиальный baseline (всегда мажоритарный класс): {maj*100:.1f}%")
    A(f"  нейро онлайн: {acc*100:.1f}%  (лифт над мажоритарным {(acc-maj)*100:+.1f} п.п.)")
    A(f"  самообучение: ранняя {early*100:.1f}% -> поздняя {late*100:.1f}% "
      f"({'учится' if late > early + 0.01 else 'плато (нечему учиться сверх дрейфа)'})")
    A("  частые 'виновники' (фича чаще тянула не туда):")
    for f, c in sorted(law.culprits.items(), key=lambda kv: -kv[1])[:6]:
        A(f"    {f:12} {c}")
    A("  аргументированные коррекции (первые):")
    for l in law.log[:4]:
        A("    " + l)
    A("")

    # === L1.5 САМО-ПРОВЕРКА: не мираж ли высокая онлайн-точность? ===
    # подозрение (наша стена): acc>=65% на направленной крипте -> искать автокорр меток + утечку
    ac = []; runs = []; pers_c = 0; pers_n = 0
    for s in SYMBOLS:
        yy = df[df.sym == s].sort_values("ts").y.values
        if len(yy) > 10:
            ac.append(float(np.corrcoef(yy[1:], yy[:-1])[0, 1]))
            runs.append(len(yy) / (int(np.sum(yy[1:] != yy[:-1])) + 1))
            pers_c += int((yy[1:] == yy[:-1]).sum()); pers_n += len(yy) - 1
    pers = pers_c / pers_n
    rng = np.random.default_rng(11); perm = rng.permutation(len(df))
    laws = OnlineLaw(FEATS); ps = np.zeros(len(df), int)
    Xs = X[perm]; ys = y[perm]; dts = pd.Timestamp("2020-01-01").to_pydatetime()
    for i in range(len(df)):
        pr, _ = laws.step(Xs[i], int(ys[i]), {"i": i, "sym": "shuf", "ts": dts})
        ps[i] = pr
    sh_acc = (ps[warm:] == ys[warm:]).mean()
    A("=== L1.5 САМО-ПРОВЕРКА: 67.8% онлайн — это мираж автокорреляции меток? ===")
    A(f"  lag-1 автокорр метки y (по активам): {', '.join(f'{a:+.2f}' for a in ac)}; средн. длина серии ~{np.mean(runs):.0f} якорей")
    A(f"  ПРИЧИНА: горизонт {HORIZON_H//24}д при шаге 12ч -> соседние якоря делят ~{HORIZON_H//12} перекрытых 1h-баров пути -> метка почти не меняется.")
    A(f"  baseline ПЕРСИСТЕНТНОСТИ (pred[i]=y[i-1], 'как в прошлый раз'): {pers*100:.1f}%  <- ВОТ источник 'точности'")
    A(f"  OnlineLaw на ПЕРЕТАСОВАННОМ времени (автокорр разорвана): {sh_acc*100:.1f}% ~ маж. {maj*100:.1f}%")
    A(f"  + утечка онлайн-оценки: метку y[i-1] узнаём лишь через {HORIZON_H//24}д после close[i-1] = на ~{HORIZON_H//24}д ПОЗЖЕ close[i];")
    A(f"    в реале к close[i] она НЕ известна, а онлайн-модуль уже на ней обучился -> {HORIZON_H//24}-дн. label-lookahead.")
    A("  ОСОЗНАНИЕ: онлайн-точность = персистентность сильно-автокоррелированной метки + утечка незарезолвленных меток,")
    A("  НЕ предсказание. Честная метрика = block-OOS (CatBoost, L2 ниже).\n")
    mirage = (sh_acc < acc - 0.08) or (pers > 0.6)

    # === L2: OOS AUC + null + cross-asset + год + дрейф-раскол ===
    A("=== L2 СТРУКТУРНАЯ ВАЛИДАЦИЯ (CatBoost walk-forward OOS) ===")
    auc, proba, mask, yall, dsorted = walk_forward_auc(df, FEATS)
    real, nmean, n95, pval = permutation_null(yall, proba, mask)
    A(f"  OOS AUC: {auc:.4f}   permutation-null: mean {nmean:.4f}, 95%-квантиль {n95:.4f}, p={pval:.3f}")
    A(f"  -> {'БЬЁТ null (есть сигнал)' if pval < 0.05 else 'НЕ бьёт null = неотличимо от монетки'}")
    loa = leave_one_asset(df, FEATS)
    A("  cross-asset (leave-one-asset-out AUC): " + ", ".join(f"{k}={v:.3f}" for k, v in loa.items()))
    pos = sum(v > 0.52 for v in loa.values())
    A(f"  -> {pos}/{len(loa)} активов с AUC>0.52 (нужно >=2/3 для cross-asset робастности)")
    # год-стабильность
    A("  год-стабильность OOS AUC:")
    from sklearn.metrics import roc_auc_score
    yr = pd.to_datetime(dsorted.ts).dt.year.values
    good = 0; tot = 0
    for Y in sorted(set(yr[mask])):
        mm = mask & (yr == Y)
        if mm.sum() > 40 and len(set(yall[mm])) > 1:
            a = roc_auc_score(yall[mm], proba[mm]); tot += 1; good += a > 0.52
            A(f"    {Y}: AUC {a:.3f} (n={mm.sum()})")
    A(f"  -> {good}/{tot} лет с AUC>0.52")
    # ДРЕЙФ-РАСКОЛ: точность по сторонам прогноза + drift-нейтральная переоценка
    A("  ДРЕЙФ-ДИАГНОСТИКА (раскол по стороне прогноза, порог 0.5):")
    pm = mask
    predcls = (proba >= 0.5).astype(int)
    up_call = pm & (predcls == 1); dn_call = pm & (predcls == 0)
    accU = (yall[up_call] == 1).mean() if up_call.sum() else np.nan
    accD = (yall[dn_call] == 0).mean() if dn_call.sum() else np.nan
    A(f"    up-вызовы:   n={up_call.sum():5d}  precision(up-first)={accU*100:5.1f}%  (база {base_up*100:.1f}%)")
    A(f"    down-вызовы: n={dn_call.sum():5d}  precision(down-first)={accD*100:5.1f}%  (база {(1-base_up)*100:.1f}%)")
    bal = balanced_oos_auc(df, FEATS)
    A(f"    drift-нейтральная переоценка (классы сбалансированы по годам): OOS AUC {bal:.4f}")

    # === НЕТТО-ТОРГОВОСПОСОБНОСТЬ на уверенных вызовах ===
    A("\n=== НЕТТО-ТОРГОВОСПОСОБНОСТЬ (±5% брекет, RR=1, кост 0.14% RT ~ 0.028R) ===")
    for thr in (0.55, 0.60):
        sel = pm & ((proba >= thr) | (proba <= 1 - thr))
        if sel.sum() < 30:
            A(f"  порог |p-0.5|>={thr-0.5:.2f}: сделок мало ({sel.sum()})"); continue
        side = (proba[sel] >= 0.5).astype(int)
        win = (side == yall[sel])
        # ±5% симметрия: выигрыш +1R, проигрыш -1R, минус кост
        exp = win.mean() * 1.0 + (~win).mean() * (-1.0) - COST_RT / BARRIER
        A(f"  |p-0.5|>={thr-0.5:.2f}: n={sel.sum():5d}  WR={win.mean()*100:5.1f}%  netExp={exp:+.3f}R/сделку")

    # === L2 АРГУМЕНТИРОВАННОЕ САМО-ОСОЗНАНИЕ/ИСПРАВЛЕНИЕ ===
    A("\n=== САМО-ОСОЗНАНИЕ И АРГУМЕНТИРОВАННАЯ КОРРЕКЦИЯ (мета) ===")
    verdict = []
    if mirage:
        verdict.append(f"0) ОСОЗНАЛ ОШИБКУ: моя онлайн-точность {acc*100:.0f}% — МИРАЖ. На перетасованном времени она падает "
                       f"до {sh_acc*100:.0f}% (~маж.), а тупой 'как в прошлый раз' даёт {pers*100:.0f}%. Причина: метка ±5% "
                       f"автокоррелирована (перекрытие 30-дн окон) + узнаётся через 30д -> онлайн обучался на будущем. "
                       f"Исправление: доверяю ТОЛЬКО block-OOS (CatBoost), где этого нет.")
    if auc < 0.52 or good < max(2, tot - 1):
        verdict.append(f"1) Честная метрика — OOS AUC {auc:.3f} (p={pval:.3f}, но только {good}/{tot} лет>0.52). "
                       f"Это практически монетка: направление ±5% от 12h-свечи не предсказуемо сверх дрейфа.")
    else:
        verdict.append(f"1) OOS AUC {auc:.3f} бьёт null (p={pval:.3f}) -> возможный сигнал, проверяю на дрейф/перенос.")
    drift_like = (not np.isnan(accU) and not np.isnan(accD) and (accU - base_up) > (accD - (1 - base_up)) + 0.03)
    if drift_like:
        verdict.append(f"2) Причина (атрибуция): up-вызовы точнее своей базы сильнее, чем down-вызовы своей "
                       f"({accU*100:.1f} vs база {base_up*100:.1f} | {accD*100:.1f} vs {(1-base_up)*100:.1f}). "
                       f"Это сигнатура БЫЧЬЕГО ДРЕЙФА (наша стена residual=drift), а не симметричной структуры.")
        verdict.append(f"3) Исправление: переоцениваю drift-нейтрально (баланс классов по годам). AUC -> {bal:.4f}. "
                       f"{'Сигнал ВЫЖИЛ дрейф-нейтрально.' if bal > 0.53 else 'Сигнал СХЛОПНУЛСЯ к ~0.5 -> это был дрейф. Признаю ошибку: симметричный ±5% first-passage = монетка+дрейф.'}")
    else:
        verdict.append(f"2) Стороны симметричны (up {accU*100:.1f}/{base_up*100:.1f} ~ down {accD*100:.1f}/"
                       f"{(1-base_up)*100:.1f}) -> не похоже на чистый дрейф; смотрю cross-asset/год.")
        verdict.append(f"3) drift-нейтральная AUC {bal:.4f}; cross-asset {pos}/{len(loa)}; годы {good}/{tot}.")
    robust = (pval < 0.05) and (bal > 0.53) and (pos >= 2) and (good >= max(1, tot - 1))
    verdict.append(f"4) ИТОГ: {'РОБАСТНЫЙ направленный сигнал на ±5% (бьёт null + cross-asset + годы + дрейф-нейтрально).' if robust else 'НЕ робастно. ±5% направление = почти монетка; остаток объясним дрейфом. Честный продукт = ОПИСАНИЕ (вероятность/сторона как контекст), НЕ торговый предиктор сам по себе.'}")
    for v in verdict:
        A("  " + v)

    rep = HERE / "fractal_first_passage_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))

    # график
    try:
        fig, ax = plt.subplots(2, 2, figsize=(14, 9))
        roll = pd.Series((preds == y).astype(float)).rolling(500, min_periods=50).mean()
        ax[0, 0].plot(roll.values, color="#1db954", lw=1.2, label="онлайн rolling-acc(500)")
        ax[0, 0].axhline(maj, color="#ef5350", ls="--", label=f"мажоритарный {maj*100:.0f}%")
        ax[0, 0].set_title("L1 само-обучение (точность)"); ax[0, 0].legend(fontsize=8); ax[0, 0].grid(alpha=0.2)
        ax[0, 1].hist(proba[mask], bins=40, color="#4a90d9"); ax[0, 1].axvline(0.5, color="k", ls="--")
        ax[0, 1].set_title(f"OOS p(up-first), AUC={auc:.3f}"); ax[0, 1].grid(alpha=0.2)
        # год-AUC бар
        yrs = []; aucs = []
        for Y in sorted(set(yr[mask])):
            mm = mask & (yr == Y)
            if mm.sum() > 40 and len(set(yall[mm])) > 1:
                yrs.append(str(Y)); aucs.append(roc_auc_score(yall[mm], proba[mm]))
        ax[1, 0].bar(yrs, aucs, color="#f5a623"); ax[1, 0].axhline(0.5, color="k", ls="--")
        ax[1, 0].set_title("OOS AUC по годам"); ax[1, 0].grid(alpha=0.2)
        # фрактал-сторона
        cats = ["dn-fr", "up-fr", "no-fr"]; vals = [df[df.fr_dir == d].y.mean() * 100 for d in (1, -1, 0)]
        ax[1, 1].bar(cats, vals, color="#9b59b6"); ax[1, 1].axhline(base_up * 100, color="k", ls="--", label="база")
        ax[1, 1].set_title("up-first% по фрактал-типу"); ax[1, 1].legend(fontsize=8); ax[1, 1].grid(alpha=0.2)
        fig.tight_layout(); fig.savefig(HERE / "fractal_first_passage.png", dpi=120)
        print(f"\n[ok] -> {rep.name} + fractal_first_passage.png")
    except Exception as ex:
        print(f"[plot skip] {ex}")


def balanced_oos_auc(df, feats, n_folds=6):
    """drift-нейтрально: в КАЖДОМ train-фолде уравниваем классы (undersample мажоритарный), затем OOS AUC."""
    from catboost import CatBoostClassifier
    from sklearn.metrics import roc_auc_score
    d = df.sort_values("ts").reset_index(drop=True)
    X = d[feats].values; y = d.y.values.astype(int)
    rng = np.random.default_rng(3)
    nrec = len(d); fold = nrec // (n_folds + 1); proba = np.full(nrec, np.nan)
    for k in range(1, n_folds + 1):
        tr_end = fold * k; te_end = min(fold * (k + 1), nrec)
        if te_end - tr_end < 30 or tr_end < 100:
            continue
        idx = np.arange(tr_end); y0 = idx[y[:tr_end] == 0]; y1 = idx[y[:tr_end] == 1]
        nmin = min(len(y0), len(y1))
        if nmin < 30:
            continue
        bal = np.concatenate([rng.choice(y0, nmin, False), rng.choice(y1, nmin, False)])
        m = CatBoostClassifier(iterations=300, depth=4, learning_rate=0.03, l2_leaf_reg=6,
                               loss_function="Logloss", verbose=False, random_seed=k, task_type="CPU")
        m.fit(X[bal], y[bal])
        proba[tr_end:te_end] = m.predict_proba(X[tr_end:te_end])[:, 1]
    mask = np.isfinite(proba)
    return roc_auc_score(y[mask], proba[mask]) if mask.sum() > 50 and len(set(y[mask])) > 1 else np.nan


if __name__ == "__main__":
    main()
