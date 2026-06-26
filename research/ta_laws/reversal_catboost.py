"""САМООБУЧАЕМЫЙ CatBoost-GPU: учится считывать СМЕНУ ТРЕНДА на разворотных точках.

Кандидаты разворота = фрактал-пивоты (Williams k=2) на 12h. На подтверждении (i+2, close[i+2]=P):
  up-фрактал (свинг-хай) -> ждём разворот ВНИЗ;  dn-фрактал (свинг-лоу) -> разворот ВВЕРХ.
Метка (first-passage ±5% по 1h ПОСЛЕ подтверждения): label=1 если первой коснулась сторона РАЗВОРОТА
  (up-фрактал -> dn первой; dn-фрактал -> up первой), 0 = продолжение тренда.

Фичи каузальны (<= close[i+2]): исчерпание (RSI/дивергенция/перерастяжение VWAP), импульс-в-пивот
(инверсия-закон), длина забега, поток (delta/cvd/taker), вола-режим, структура (vs VWAP/ViC/канал), фитиль.

Само-обучение: CatBoost-GPU walk-forward + AFML-пёрдж; раунды само-коррекции (баланс/focal/ёмкость) с
проверкой OOS. КРИТЕРИЙ accuracy. Контроли: shuffle, cross-asset, год, РАСКОЛ сторон (up-рев/dn-рев = дрейф?).
Стена: симметричный ±5% -> направление монетка; реальный сигнал = только если бьёт base+shuffle+cross+обе стороны.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/reversal_catboost.py
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
BARRIER = 0.05
HORIZON_H = 24 * 30
PURGE = pd.Timedelta(days=30)
K = 2
N_FOLDS = 6
N_ROUNDS = 4
GPU = os.environ.get("REV_GPU", "1") == "1"
FEATS = ["frac_type", "rsi", "rsi_ext", "rsi_div", "impulse", "run_len", "atr_pct", "atr_pctile",
         "vwap_z", "dist_vic", "range_pos", "ema_slope", "delta_norm", "cvd_slope", "tbr_dev",
         "piv_wick", "body"]


def load_flow(sym, tf):
    df = pd.read_csv(DATA / f"{sym}_{tf}_flow.csv")
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df.sort_values("open_time").reset_index(drop=True)


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    ru = pd.Series(up).ewm(alpha=1 / n, adjust=False).mean().values
    rd = pd.Series(dn).ewm(alpha=1 / n, adjust=False).mean().values
    return 100 - 100 / (1 + ru / (rd + 1e-9))


def build(sym):
    h = load_flow(sym, "12h"); o = load_flow(sym, "1h")
    O, H, L, C, V = (h[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    delta = h["delta"].values.astype(float); cvd = h["cvd"].values.astype(float)
    tbr = h["taker_buy_ratio"].values.astype(float); n = len(h)
    atr = G.compute_atr(h[["high", "low", "close"]]); atr_pct = np.where(C > 0, atr / C * 100, np.nan)
    atr_pctile = pd.Series(atr_pct).rolling(200, min_periods=30).apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    R = rsi(C, 14)
    tp = (H + L + C) / 3
    vwap = (pd.Series(tp * V).rolling(28, min_periods=8).sum() / (pd.Series(V).rolling(28, min_periods=8).sum() + 1e-9)).values
    vstd = pd.Series(C).rolling(28, min_periods=8).std().values + 1e-9
    vwap_z = (C - vwap) / vstd
    ema_s = pd.Series(C).ewm(span=20, adjust=False).mean().values
    ema_slope = np.zeros(n); ema_slope[5:] = (ema_s[5:] - ema_s[:-5]) / np.clip(C[5:], 1e-9, None) * 100
    base = pd.Series(np.abs(delta)).rolling(50, min_periods=5).mean().values + 1e-9
    cvd_slope = np.zeros(n); cvd_slope[3:] = (cvd[3:] - cvd[:-3]) / base[3:]
    delta_norm = delta / (V + 1e-9); tbr_dev = tbr - 0.5
    lo50 = pd.Series(L).rolling(50, min_periods=10).min().values; hi50 = pd.Series(H).rolling(50, min_periods=10).max().values
    rpos = (C - lo50) / np.clip(hi50 - lo50, 1e-9, None)
    # ViC POC rolling 30
    vic = np.full(n, np.nan)
    for i in range(30, n):
        st, sv = tp[i - 30:i], V[i - 30:i]; lo, hi = st.min(), st.max()
        if hi > lo:
            b = np.clip(((st - lo) / (hi - lo) * 23).astype(int), 0, 23); agg = np.zeros(24); np.add.at(agg, b, sv)
            vic[i] = lo + (agg.argmax() + 0.5) / 24 * (hi - lo)
        else:
            vic[i] = C[i]
    # фракталы
    up_fr = np.zeros(n, bool); dn_fr = np.zeros(n, bool)
    for i in range(K, n - K):
        if H[i] == H[i - K:i + K + 1].max():
            up_fr[i] = True
        if L[i] == L[i - K:i + K + 1].min():
            dn_fr[i] = True
    # 1h путь
    t1 = o["open_time"].values.astype("datetime64[ns]").astype(np.int64)
    h1H = o["high"].values.astype(float); h1L = o["low"].values.astype(float)
    rows = []
    for i in range(60, n - K - 1):
        ftype = 1 if (dn_fr[i] and not up_fr[i]) else (-1 if (up_fr[i] and not dn_fr[i]) else 0)
        if ftype == 0:
            continue
        ci = i + K  # подтверждение
        if ci >= n - 1:
            continue
        P = C[ci]
        if not np.isfinite(P) or P <= 0 or not np.isfinite(atr_pctile[ci]) or not np.isfinite(vwap[ci]) or not np.isfinite(vic[ci]):
            continue
        ct = (h["open_time"].values[ci] + np.timedelta64(12, "h")).astype("datetime64[ns]").astype(np.int64)
        s = int(np.searchsorted(t1, ct, side="left")); e = min(s + HORIZON_H, len(t1))
        if e - s < 5:
            continue
        up = P * 1.05; dn = P * 0.95
        uh = np.nonzero(h1H[s:e] >= up)[0]; dh = np.nonzero(h1L[s:e] <= dn)[0]
        iu = uh[0] if uh.size else 10**9; idd = dh[0] if dh.size else 10**9
        if iu == 10**9 and idd == 10**9:
            continue
        up_first = iu < idd
        rev = (not up_first) if ftype == -1 else up_first   # реализовался ли разворот
        imp = (C[i] - C[i - 4]) / C[i - 4] * 100 / max(atr_pct[i], 1e-9) if i >= 4 else 0.0
        runl = 0
        for j in range(i, max(0, i - 12), -1):
            if (ftype == -1 and C[j] >= C[j - 1]) or (ftype == 1 and C[j] <= C[j - 1]):
                runl += 1
            else:
                break
        rng_i = (H[i] - L[i]) + 1e-9
        piv_wick = (H[i] - max(O[i], C[i])) / rng_i if ftype == -1 else (min(O[i], C[i]) - L[i]) / rng_i
        rsi_div = float((ftype == -1 and H[i] >= np.max(H[max(0, i - 10):i + 1]) and R[i] < 62) or
                        (ftype == 1 and L[i] <= np.min(L[max(0, i - 10):i + 1]) and R[i] > 38))
        feat = {"frac_type": float(ftype), "rsi": R[ci], "rsi_ext": float(R[ci] >= 68 or R[ci] <= 32),
                "rsi_div": rsi_div, "impulse": imp, "run_len": float(runl), "atr_pct": atr_pct[ci],
                "atr_pctile": atr_pctile[ci], "vwap_z": vwap_z[ci], "dist_vic": (C[ci] - vic[ci]) / C[ci] * 100,
                "range_pos": rpos[ci], "ema_slope": ema_slope[ci], "delta_norm": delta_norm[ci],
                "cvd_slope": cvd_slope[ci], "tbr_dev": tbr_dev[ci],
                "piv_wick": piv_wick, "body": (C[ci] - O[ci]) / ((H[ci] - L[ci]) + 1e-9)}
        if any(not np.isfinite(v) for v in feat.values()):
            continue
        rows.append({"sym": sym, "ts": h["open_time"].values[ci], "y": int(rev), "ftype": ftype, **feat})
    return rows


def cb(cfg, seed):
    from catboost import CatBoostClassifier
    kw = dict(iterations=cfg.get("it", 2000), depth=cfg.get("depth", 6), learning_rate=0.03,
              l2_leaf_reg=cfg.get("l2", 6), loss_function="Logloss", verbose=False, random_seed=seed)
    if cfg.get("acw"):
        kw["auto_class_weights"] = cfg["acw"]
    if cfg.get("focal"):
        kw["loss_function"] = f"Focal:focal_alpha=0.5;focal_gamma={cfg['focal']}"
    if GPU:
        kw["task_type"] = "GPU"; kw["devices"] = "0"
    return CatBoostClassifier(**kw)


def walk(df, target, cfg):
    d = df.sort_values("ts").reset_index(drop=True); X = d[FEATS].values; y = d[target].values.astype(int)
    tns = d.ts.values.astype("datetime64[ns]"); n = len(d); fold = n // (N_FOLDS + 1)
    proba = np.full(n, np.nan)
    for k in range(1, N_FOLDS + 1):
        te0 = fold * k; te1 = min(fold * (k + 1), n)
        if te1 - te0 < 30:
            continue
        tr = tns < (tns[te0] - np.timedelta64(PURGE))
        if tr.sum() < 200:
            continue
        try:
            m = cb(cfg, k); m.fit(X[tr], y[tr]); proba[te0:te1] = m.predict_proba(X[te0:te1])[:, 1]
        except Exception as ex:
            print(f"   fold {k} fail: {str(ex)[:80]}", flush=True)
    return d, proba, np.isfinite(proba)


def acc(y, p, m):
    return ((p[m] >= 0.5).astype(int) == y[m].astype(int)).mean()


def main():
    rows = []
    for s in SYMBOLS:
        print(f"[{s}] build...", flush=True); rows += build(s)
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    df["year"] = pd.to_datetime(df.ts).dt.year
    base = df.y.mean(); maj = max(base, 1 - base)
    print(f"[data] {len(df)} пивотов, разворот реализован {base*100:.1f}%, maj {maj*100:.1f}%, GPU={GPU}", flush=True)

    out = []; A = out.append
    A("САМООБУЧАЕМЫЙ CatBoost — смена тренда на фрактал-пивотах. Критерий ACCURACY (разворот vs продолжение).")
    A(f"Пивотов {len(df)} (BTC/ETH/SOL 12h). База разворота {base*100:.1f}% (up-рев {df[df.ftype==1].y.mean()*100:.0f}% / "
      f"down-рев {df[df.ftype==-1].y.mean()*100:.0f}%). Маж.baseline {maj*100:.1f}%.\n")

    cfg = {"it": 2000, "depth": 6}
    print("[round0] base...", flush=True)
    d, p, m = walk(df, "y", cfg); a = acc(df.y.values, p, m)
    best = {"r": 0, "cfg": dict(cfg), "acc": a, "p": p.copy()}; hist = [(0, "база", a)]
    A("=== САМО-КОРРЕКЦИЯ (раунды, OOS accuracy) ===")
    A(f"  раунд 0 база: {a*100:.2f}% (маж {maj*100:.2f}%)")
    tried = set()
    for r in range(1, N_ROUNDS + 1):
        pr = (best["p"] >= 0.5).astype(int); mm = np.isfinite(best["p"])
        cand = dict(best["cfg"]); reason = ""
        if abs(pr[mm].mean() - base) > 0.12 and "bal" not in tried:
            cand["acw"] = "Balanced"; tried.add("bal"); reason = "баланс классов"
        elif "focal" not in tried:
            cand["focal"] = 2.0; tried.add("focal"); reason = "focal на трудных"
        elif "cap" not in tried:
            cand["depth"] = 8; cand["it"] = 3000; tried.add("cap"); reason = "ёмкость depth8"
        else:
            cand["l2"] = 2; tried.add("l2"); reason = "слабее регуляризация"
        print(f"[round{r}] {reason}...", flush=True)
        dr, pp, mr = walk(df, "y", cand); ar = acc(df.y.values, pp, mr); imp = ar > best["acc"] + 0.003
        A(f"  раунд {r} {reason}: {ar*100:.2f}% {'ПРИНЯТО' if imp else 'откат'}"); hist.append((r, reason, ar))
        if imp:
            best = {"r": r, "cfg": dict(cand), "acc": ar, "p": pp.copy()}

    bp = best["p"]; bm = np.isfinite(bp); yv = df.y.values
    # shuffle
    rng = np.random.default_rng(7); ds = df.copy(); ds["y"] = rng.permutation(df.y.values)
    _, ps, msh = walk(ds, "y", best["cfg"]); ash = acc(ds.y.values, ps, msh)
    A(f"\n=== ЛУЧШИЙ (раунд {best['r']}) ===")
    A(f"  OOS accuracy {best['acc']*100:.2f}% | маж {maj*100:.2f}% | лифт {(best['acc']-maj)*100:+.2f}пп")
    A(f"  shuffle {ash*100:.2f}% ({'чисто' if ash < maj + 0.03 else 'ПОДОЗР'})")
    A("  по активам:")
    ga = 0
    for s in SYMBOLS:
        ms = bm & (df.sym.values == s)
        if ms.sum() > 30:
            aa = acc(yv, bp, ms); ga += aa > maj + 0.02; A(f"    {s}: {aa*100:.1f}% (n={ms.sum()})")
    A("  по годам:")
    yr = pd.to_datetime(df.ts).dt.year.values; gy = 0; ty = 0
    for Y in sorted(set(yr[bm])):
        my = bm & (yr == Y)
        if my.sum() > 25:
            aa = acc(yv, bp, my); ty += 1; gy += aa > maj + 0.02; A(f"    {Y}: {aa*100:.1f}% (n={my.sum()})")
    # раскол сторон (дрейф)
    A("  раскол сторон (дрейф-тест):")
    for ft, nm in [(1, "dn-фрактал (рев ВВЕРХ)"), (-1, "up-фрактал (рев ВНИЗ)")]:
        ms = bm & (df.ftype.values == ft)
        if ms.sum() > 30:
            b2 = max(df[df.ftype == ft].y.mean(), 1 - df[df.ftype == ft].y.mean())
            A(f"    {nm}: acc {acc(yv, bp, ms)*100:.1f}% vs side-base {b2*100:.1f}% (n={ms.sum()})")

    A("\n=== ВЕРДИКТ ===")
    works = (best["acc"] > maj + 0.03) and (ash < maj + 0.03) and (ga >= 2) and (gy >= max(3, ty - 1))
    if works:
        A(f"  РАБОТАЕТ: разворот предсказуем сверх базы ({best['acc']*100:.0f}% vs {maj*100:.0f}%), cross {ga}/3, годы {gy}/{ty}, shuffle чист.")
    else:
        A(f"  НЕ робастно: {best['acc']*100:.0f}% vs база {maj*100:.0f}% (cross {ga}/3, годы {gy}/{ty}, shuffle {ash*100:.0f}%).")
        A("  Смена тренда на симметричном ±5% -> near-coin; пивот+исчерпание не дают устойчивого предсказания разворота")
        A("  сверх базы/дрейфа. (Инверсия-закон живёт на асимметр.expR fade, не на симметр. accuracy разворота.)")
    A(f"  кривая: " + " | ".join(f"R{r}:{a*100:.1f}%" for r, _, a in hist))

    rep = HERE / "reversal_catboost_report.txt"; rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
