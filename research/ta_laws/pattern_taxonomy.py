"""Расследование КАТЕГОРИЗАЦИИ паттернов ТА.

Проблема: текущий вывод модуля «у всех паттернов ~одна цель» (фигуры медиана 0.49x высоты).
Это МАРГИНАЛЬНОЕ среднее. Задача: найти ПРИЗНАКИ, которые РАСЩЕПЛЯЮТ паттерны на категории
с РАЗНЫМ поведением после раскрытия (направление + дальность + качество хода + время).

Конвейер (каузально, arm = comp_conf_i, без lookahead; BTC/ETH/SOL, 1h->D, с 2020):
  1) Богатый проход по figures.find_figures: вектор признаков-категоризаторов
     (природа/тренд-связь/мульти-ТФ/масштаб/зрелость/вола-состояние/локация/энергия пробоя)
     + движение ПОСЛЕ раскрытия (dirR направление, ext в высотах, MFE/MAE в ATR, ft_ratio,
       время до MFE, класс развязки).
  2) Дискриминантный рейтинг осей: для каждого признака — η² (доля объяснённой дисперсии)
     по каждому исходу + ПЕРЕСТАНОВОЧНЫЙ null (shuffle меток) + cross-asset знак + год.
  3) Авто-таксономия: shallow DecisionTree сам предлагает разрезы (+ SHUFFLE-контроль OOS).
  4) Именованная таксономия: профиль каждой категории + таблица «движения после раскрытия».
  5) Валидация заголовочных категорий (cross-asset + год) + график-сводка.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/pattern_taxonomy.py
Выход: research/ta_laws/taxonomy_report.txt + pattern_taxonomy.csv + taxonomy_profiles.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
import figures as F   # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = [("1h", "1h", 60), ("2h", "2h", 120), ("4h", "4h", 240),
       ("6h", "6h", 360), ("12h", "12h", 720), ("1d", "1d", 1440)]
TB_ATR = 1.5
RNG = np.random.default_rng(17)

REVERSAL = {"DOUBLE_TOP", "DOUBLE_BOTTOM", "TRIPLE_TOP", "TRIPLE_BOTTOM",
            "HEAD_SHOULDERS", "INV_HEAD_SHOULDERS"}
CONTINUATION = {"ASC_TRIANGLE", "DESC_TRIANGLE", "SYM_TRIANGLE"}
RANGEK = {"RECTANGLE"}


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def regime_at(btc_1d, ts):
    a = btc_1d.asof(ts); b = btc_1d.asof(ts - pd.Timedelta(days=30))
    return (1 if a > b else -1) if (pd.notna(a) and pd.notna(b) and b > 0) else 0


def dir_barrier(c, h, l, arm, hz, atr_a, expdir):
    """+1 если expdir-барьер 1.5ATR первым, -1 если против, 0 если ни один (не раскрылась)."""
    if atr_a <= 0:
        return 0
    base = c[arm]; up = base + TB_ATR * atr_a; dn = base - TB_ATR * atr_a
    uh = dh = None
    for x in range(arm + 1, hz + 1):
        if uh is None and h[x] >= up:
            uh = x
        if dh is None and l[x] <= dn:
            dh = x
        if uh is not None and dh is not None:
            break
    exp_hit, opp_hit = (uh, dh) if expdir == "UP" else (dh, uh)
    ei = exp_hit if exp_hit is not None else 10**9
    oi = opp_hit if opp_hit is not None else 10**9
    if ei == 10**9 and oi == 10**9:
        return 0
    return 1 if ei <= oi else -1


def movement(c, h, l, arm, hz, neck, expdir, height, atr_a):
    """Движение ПОСЛЕ раскрытия (пробой неклайна в expdir).
    Возврат: (ext_h, mfe_atr, mae_atr, ttm, ft_ratio, terminal) или None если пробоя в expdir не было.
    ext_h    — MFE в высотах фигуры (сравнимо с прежним 0.49x).
    mfe_atr  — MFE в ATR от неклайна; mae_atr — макс. ход ПРОТИВ (просадка) от пробоя до бара MFE.
    ttm      — доля горизонта до бара MFE; ft_ratio = mfe/(mfe+mae) — чистота хода.
    """
    if height <= 0 or atr_a <= 0:
        return None
    bo = None
    for x in range(arm + 1, hz + 1):
        if (expdir == "UP" and c[x] > neck) or (expdir == "DOWN" and c[x] < neck):
            bo = x; break
    if bo is None:
        return None
    ext = 0.0; mfe_bar = bo
    for y in range(bo, hz + 1):
        fav = (h[y] - neck) if expdir == "UP" else (neck - l[y])
        if fav > ext:
            ext = fav; mfe_bar = y
        if (expdir == "UP" and c[y] < neck) or (expdir == "DOWN" and c[y] > neck):
            break
    # MAE: макс. ход против направления от пробоя до бара MFE
    mae = 0.0
    for y in range(bo, mfe_bar + 1):
        adv = (neck - l[y]) if expdir == "UP" else (h[y] - neck)
        if adv > mae:
            mae = adv
    mfe_atr = ext / atr_a
    mae_atr = mae / atr_a
    ext_h = ext / height
    ttm = (mfe_bar - bo) / max(hz - bo, 1)
    ft = mfe_atr / (mfe_atr + mae_atr) if (mfe_atr + mae_atr) > 0 else 0.0
    if mfe_atr >= 2.0 and ft >= 0.66:
        term = "strong_run"
    elif mfe_atr >= 1.0:
        term = "modest_run"
    elif mae_atr > mfe_atr:
        term = "fakeout"
    else:
        term = "fizzle"
    return ext_h, mfe_atr, mae_atr, ttm, ft, term


def collect():
    btc_1d = rs(load_1m("BTCUSDT"), "1d")["close"]
    rows = []
    for sym in SYMBOLS:
        print(f"[collect] {sym}...", flush=True)
        d1 = load_1m(sym)
        sym_1d = rs(d1, "1d")["close"]
        mtf = {"1h": (rs(d1, "1h")["close"], pd.Timedelta(hours=10)),
               "4h": (rs(d1, "4h")["close"], pd.Timedelta(hours=40)),
               "1d": (sym_1d, pd.Timedelta(days=10))}
        for tlabel, freq, tf_min in TFS:
            df = rs(d1, freq)
            n = len(df)
            c = df["close"].values; h = df["high"].values; l = df["low"].values
            atr = G.compute_atr(df)
            atr_roll = pd.Series(atr).rolling(100, min_periods=20).mean().values
            cap = 30 * 24 * 60 // tf_min
            figs = F.find_figures(df)
            for f in figs:
                arm = f.comp_conf_i
                if arm < 25 or arm >= n - 2 or not (atr[arm] > 0):
                    continue
                span = max(f.comp_i - f.pivots[0].i, 10)
                hz = min(arm + min(span * 2, cap), n - 1)
                arm_ts = df.index[arm]
                # --- признаки-категоризаторы (всё <= arm) ---
                nature = "REVERSAL" if f.kind in REVERSAL else ("CONTINUATION" if f.kind in CONTINUATION else "RANGE")
                p0i = f.pivots[0].i
                prior = "UP" if c[arm] > c[max(0, p0i - 1)] else "DOWN"
                trend_with = int(f.expected_dir == prior)
                cn = sym_1d.asof(arm_ts); cp = sym_1d.asof(arm_ts - pd.Timedelta(days=10))
                htf = "UP" if (pd.notna(cn) and pd.notna(cp) and cn > cp) else "DOWN"
                htf_align = int(htf == f.expected_dir)
                mtf_align = 0
                for _t, (ser, td) in mtf.items():
                    vn = ser.asof(arm_ts); vp = ser.asof(arm_ts - td)
                    if pd.notna(vn) and pd.notna(vp):
                        mtf_align += int(("UP" if vn > vp else "DOWN") == f.expected_dir)
                reg = regime_at(btc_1d, arm_ts)
                regime_align = int(reg == (1 if f.expected_dir == "UP" else -1))
                height_atr = f.height / atr[arm]
                vol_state = atr[arm] / atr_roll[arm] if (arm < len(atr_roll) and atr_roll[arm] > 0) else np.nan
                lo50 = l[max(0, arm - 50):arm + 1].min(); hi50 = h[max(0, arm - 50):arm + 1].max()
                range_pos = (c[arm] - lo50) / (hi50 - lo50) if hi50 > lo50 else np.nan
                bar_mom = (h[arm] - l[arm]) / atr[arm]
                # --- исходы ---
                dR = dir_barrier(c, h, l, arm, hz, atr[arm], f.expected_dir)
                mv = movement(c, h, l, arm, hz, f.neckline, f.expected_dir, f.height, atr[arm])
                rows.append({
                    "symbol": sym, "tf": tlabel, "year": arm_ts.year, "kind": f.kind,
                    "expdir": f.expected_dir, "nature": nature, "trend_with": trend_with,
                    "htf_align": htf_align, "mtf_align": mtf_align, "regime_align": regime_align,
                    "height_atr": round(height_atr, 2), "span_bars": int(span),
                    "vol_state": round(vol_state, 3) if pd.notna(vol_state) else np.nan,
                    "range_pos": round(range_pos, 3) if pd.notna(range_pos) else np.nan,
                    "bar_mom": round(bar_mom, 2), "dirR": dR,
                    "broke": int(mv is not None),
                    "ext_h": round(mv[0], 3) if mv else np.nan,
                    "mfe_atr": round(mv[1], 3) if mv else np.nan,
                    "mae_atr": round(mv[2], 3) if mv else np.nan,
                    "ttm": round(mv[3], 3) if mv else np.nan,
                    "ft_ratio": round(mv[4], 3) if mv else np.nan,
                    "terminal": mv[5] if mv else "no_breakout",
                })
            print(f"   {sym} {tlabel}: figs {len(figs)}", flush=True)
    return pd.DataFrame(rows)


# ---------- дискриминантная метрика ----------
def eta2_perm(codes, y, ng, iters=400):
    """η² (доля дисперсии исхода, объяснённая разбиением) + перестановочный null p."""
    y = np.asarray(y, float)
    n = len(y)
    if n < 30:
        return 0.0, 1.0
    grand = y.mean(); ss_tot = ((y - grand) ** 2).sum()
    if ss_tot <= 0:
        return 0.0, 1.0

    def e2(cc):
        sums = np.bincount(cc, weights=y, minlength=ng)
        cnts = np.bincount(cc, minlength=ng).astype(float)
        cnts[cnts == 0] = np.nan
        means = sums / cnts
        ss_b = np.nansum(cnts * (means - grand) ** 2)
        return ss_b / ss_tot

    obs = e2(codes)
    cnt = sum(1 for _ in range(iters) if e2(RNG.permutation(codes)) >= obs)
    return float(obs), (cnt + 1) / (iters + 1)


def bucketize(s, col):
    """Вернуть (labels Series, описание бакетов) для признака."""
    x = s[col]
    if col in ("nature", "kind"):
        return x.astype(str), None
    if col in ("trend_with", "htf_align", "regime_align", "broke"):
        return x.map({0: "0", 1: "1"}).astype(str), None
    if col == "mtf_align":
        return x.map(lambda v: "0-1" if v <= 1 else ("2" if v == 2 else "3")).astype(str), None
    if col == "height_atr":
        return pd.cut(x, [-1, 3, 6, 1e9], labels=["<3", "3-6", ">=6"]).astype(str), None
    if col == "vol_state":
        return pd.cut(x, [-1, 0.9, 1.1, 1e9], labels=["сжатие", "норма", "расширение"]).astype(str), None
    if col == "range_pos":
        return pd.cut(x, [-1, 0.33, 0.66, 2], labels=["низ", "сред", "верх"]).astype(str), None
    if col == "bar_mom":
        return pd.cut(x, [-1, 1.0, 1.5, 1e9], labels=["слабый", "сред", "сильный"]).astype(str), None
    if col == "span_bars":
        q = x.quantile([0.33, 0.66]).values
        return pd.cut(x, [-1, q[0], q[1], 1e18], labels=["узкая", "сред", "широкая"]).astype(str), None
    return x.astype(str), None


def axis_report(df, axis, out):
    """Для одной оси категоризации — η² по 3 исходам + cross-asset + год."""
    res = {}
    # направление: на раскрывшихся (dirR!=0), значение = (textbook верен)
    sd = df[df.dirR != 0].copy()
    sd["_lab"], _ = bucketize(sd, axis)
    sd = sd.dropna(subset=["_lab"])
    sd = sd[sd._lab != "nan"]
    if len(sd) >= 60:
        cats = sorted(sd._lab.unique())
        codes = pd.Categorical(sd._lab, categories=cats).codes
        e2d, pd_ = eta2_perm(codes, (sd.dirR > 0).astype(float).values, len(cats))
        prof = sd.groupby("_lab").dirR.agg(["mean", "count"])
        res["dir"] = (e2d, pd_, prof)
    # дальность: на подтверждённых пробоях, ext_h
    se = df[df.broke == 1].dropna(subset=["ext_h"]).copy()
    se["_lab"], _ = bucketize(se, axis)
    se = se.dropna(subset=["_lab"]); se = se[se._lab != "nan"]
    if len(se) >= 60:
        cats = sorted(se._lab.unique())
        codes = pd.Categorical(se._lab, categories=cats).codes
        e2e, pe = eta2_perm(codes, se.ext_h.values, len(cats))
        prof = se.groupby("_lab").ext_h.agg(["median", "count"])
        res["ext"] = (e2e, pe, prof)
    # качество хода: ft_ratio
    sf = df[df.broke == 1].dropna(subset=["ft_ratio"]).copy()
    sf["_lab"], _ = bucketize(sf, axis)
    sf = sf.dropna(subset=["_lab"]); sf = sf[sf._lab != "nan"]
    if len(sf) >= 60:
        cats = sorted(sf._lab.unique())
        codes = pd.Categorical(sf._lab, categories=cats).codes
        e2f, pf = eta2_perm(codes, sf.ft_ratio.values, len(cats))
        prof = sf.groupby("_lab").ft_ratio.agg(["median", "count"])
        res["ft"] = (e2f, pf, prof)
    return res


def main():
    csv = HERE / "pattern_taxonomy.csv"
    if csv.exists() and "--reuse" in sys.argv:
        df = pd.read_csv(csv)
        print(f"[reuse] {csv.name} n={len(df)}", flush=True)
    else:
        df = collect()
        df.to_csv(csv, index=False)
        print(f"[collect] -> {csv.name} n={len(df)}", flush=True)

    out = []
    out.append("РАССЛЕДОВАНИЕ КАТЕГОРИЗАЦИИ ПАТТЕРНОВ — BTC/ETH/SOL, 1h->D, с 2020.")
    out.append(f"Всего фигур: {len(df)} | раскрылись по учебнику (broke): {df.broke.mean()*100:.0f}% | "
               f"dirR решено: {(df.dirR!=0).mean()*100:.0f}%")
    conf = df[df.broke == 1].dropna(subset=["ext_h"])
    out.append(f"МАРГИНАЛ (то, что выглядело «одной целью»): медиана ext={conf.ext_h.median():.2f}x высоты, "
               f"P(textbook dir)={(df[df.dirR!=0].dirR>0).mean()*100:.0f}%, "
               f"медиана MFE={conf.mfe_atr.median():.2f}ATR, ft_ratio={conf.ft_ratio.median():.2f}\n")

    # ---------- 1) дискриминантный рейтинг осей ----------
    AXES = ["nature", "trend_with", "htf_align", "mtf_align", "regime_align",
            "height_atr", "vol_state", "range_pos", "bar_mom", "span_bars", "kind"]
    out.append("=== 1) ПРИНЦИПЫ РАЗДЕЛЕНИЯ: какие признаки расщепляют исход (η² + перестановочный null) ===")
    out.append("η² = доля дисперсии исхода, объяснённая разбиением по оси. p — null (shuffle меток).")
    out.append(f"{'ось':14} | {'НАПРАВЛ η²/p':>16} | {'ДАЛЬНОСТЬ η²/p':>17} | {'КАЧЕСТВО η²/p':>16}")
    rank = []
    axres = {}
    for ax in AXES:
        r = axis_report(df, ax, out)
        axres[ax] = r
        d = r.get("dir"); e = r.get("ext"); ff = r.get("ft")
        ds = f"{d[0]:.4f}/{d[1]:.3f}" if d else "—"
        es = f"{e[0]:.4f}/{e[1]:.3f}" if e else "—"
        fs = f"{ff[0]:.4f}/{ff[1]:.3f}" if ff else "—"
        out.append(f"{ax:14} | {ds:>16} | {es:>17} | {fs:>16}")
        score = sum(x[0] for x in [d, e, ff] if x and x[1] < 0.05)
        rank.append((ax, score, d, e, ff))
    rank.sort(key=lambda x: x[1], reverse=True)
    out.append("\nРейтинг осей по суммарной значимой объясняющей силе (η² при p<0.05):")
    for ax, sc, *_ in rank:
        out.append(f"  {ax:14} {sc:.4f}")

    # ---------- 2) профили по топ-осям ----------
    out.append("\n=== 2) ПРОФИЛИ КАТЕГОРИЙ по топ-осям (направление / дальность / качество) ===")
    for ax, sc, d, e, ff in rank[:5]:
        out.append(f"\n-- ось «{ax}» --")
        if d:
            out.append("   НАПРАВЛЕНИЕ (dirR mean, >0 = учебная сторона чаще):")
            for lab, row in d[2].iterrows():
                out.append(f"      {str(lab):14} n={int(row['count']):>5}  dirR={row['mean']:+.3f}  "
                           f"P(textbook)={(row['mean']+1)/2*100:>4.0f}%")
        if e:
            out.append("   ДАЛЬНОСТЬ (медиана ext в высотах фигуры):")
            for lab, row in e[2].iterrows():
                out.append(f"      {str(lab):14} n={int(row['count']):>5}  ext={row['median']:.2f}x")
        if ff:
            out.append("   КАЧЕСТВО ХОДА (медиана ft_ratio, >0.5 = идёт чисто):")
            for lab, row in ff[2].iterrows():
                out.append(f"      {str(lab):14} n={int(row['count']):>5}  ft={row['median']:.2f}")

    # ---------- 3) авто-таксономия (дерево + shuffle) ----------
    out.append("\n=== 3) АВТО-ТАКСОНОМИЯ: shallow-дерево само предлагает разрезы (+ SHUFFLE-контроль OOS) ===")
    try:
        from sklearn.tree import DecisionTreeRegressor, DecisionTreeClassifier, export_text
        from sklearn.metrics import r2_score, roc_auc_score
        feats = ["nature_c", "trend_with", "htf_align", "mtf_align", "regime_align",
                 "height_atr", "vol_state", "range_pos", "bar_mom", "span_bars"]
        dd = df.copy()
        dd["nature_c"] = dd.nature.map({"REVERSAL": 0, "CONTINUATION": 1, "RANGE": 2})
        # ДАЛЬНОСТЬ: регрессор на ext_h
        se = dd[dd.broke == 1].dropna(subset=["ext_h"] + feats).sort_values(["year"])
        Xe = se[feats].values; ye = se.ext_h.values
        k = int(len(se) * 0.7)
        rgr = DecisionTreeRegressor(max_depth=3, min_samples_leaf=200, random_state=0)
        rgr.fit(Xe[:k], ye[:k])
        r2 = r2_score(ye[k:], rgr.predict(Xe[k:]))
        rgr_sh = DecisionTreeRegressor(max_depth=3, min_samples_leaf=200, random_state=0)
        rgr_sh.fit(Xe[:k], RNG.permutation(ye[:k]))
        r2_sh = r2_score(ye[k:], rgr_sh.predict(Xe[k:]))
        out.append(f"  ДАЛЬНОСТЬ ext_h: дерево OOS R²={r2:+.4f} | SHUFFLE R²={r2_sh:+.4f} -> "
                   f"{'есть структура' if r2 - r2_sh > 0.005 else 'НЕТ структуры (цель почти неразделима по этим осям)'}")
        out.append("  Разрезы дерева для ДАЛЬНОСТИ:")
        for ln in export_text(rgr, feature_names=feats).splitlines():
            out.append("    " + ln)
        # НАПРАВЛЕНИЕ: классификатор на (dirR>0) среди раскрывшихся
        sdir = dd[dd.dirR != 0].dropna(subset=feats).sort_values(["year"])
        Xd = sdir[feats].values; yd = (sdir.dirR > 0).astype(int).values
        k2 = int(len(sdir) * 0.7)
        clf = DecisionTreeClassifier(max_depth=3, min_samples_leaf=300, random_state=0)
        clf.fit(Xd[:k2], yd[:k2])
        auc = roc_auc_score(yd[k2:], clf.predict_proba(Xd[k2:])[:, 1])
        clf_sh = DecisionTreeClassifier(max_depth=3, min_samples_leaf=300, random_state=0)
        clf_sh.fit(Xd[:k2], RNG.permutation(yd[:k2]))
        auc_sh = roc_auc_score(yd[k2:], clf_sh.predict_proba(Xd[k2:])[:, 1])
        out.append(f"\n  НАПРАВЛЕНИЕ (textbook верен): дерево OOS AUC={auc:.3f} | SHUFFLE AUC={auc_sh:.3f} -> "
                   f"{'есть сигнал' if auc - auc_sh > 0.02 else 'НЕ бьёт shuffle'}")
        out.append("  Разрезы дерева для НАПРАВЛЕНИЯ:")
        for ln in export_text(clf, feature_names=feats).splitlines():
            out.append("    " + ln)
    except Exception as ex:
        out.append(f"  sklearn недоступен/ошибка: {ex}")

    # ---------- 4) именованная таксономия + движение после раскрытия ----------
    out.append("\n=== 4) ИМЕНОВАННАЯ ТАКСОНОМИЯ: природа × тренд-связь × масштаб ===")
    out.append("Для каждой категории: n, P(textbook dir), медиана ext, MFE/MAE в ATR, ft_ratio, время-до-MFE, развязка.")
    dd = df.copy()
    dd["scale"] = pd.cut(dd.height_atr, [-1, 3, 6, 1e9], labels=["мелк", "сред", "крупн"]).astype(str)
    dd["trel"] = dd.trend_with.map({1: "ПО-тренду", 0: "ПРОТИВ-тренда"})
    grp = dd.groupby(["nature", "trel", "scale"])
    out.append(f"\n{'категория':40} {'n':>5} {'Pdir%':>6} {'ext':>5} {'MFE':>5} {'MAE':>5} {'ft':>5} {'ttm':>5}  развязка")
    cat_profiles = []
    for key, g in grp:
        if len(g) < 80:
            continue
        gd = g[g.dirR != 0]; gb = g[g.broke == 1].dropna(subset=["ext_h"])
        if len(gd) < 30 or len(gb) < 30:
            continue
        pdir = (gd.dirR > 0).mean() * 100
        name = f"{key[0][:6]}/{key[1]}/{key[2]}"
        term = gb.terminal.value_counts(normalize=True)
        top_term = term.index[0] if len(term) else "-"
        out.append(f"{name:40} {len(g):>5} {pdir:>6.0f} {gb.ext_h.median():>5.2f} "
                   f"{gb.mfe_atr.median():>5.2f} {gb.mae_atr.median():>5.2f} {gb.ft_ratio.median():>5.2f} "
                   f"{gb.ttm.median():>5.2f}  {top_term}({term.iloc[0]*100:.0f}%)")
        cat_profiles.append((name, len(g), pdir, gb.ext_h.median(), gb.mfe_atr.median(),
                             gb.mae_atr.median(), gb.ft_ratio.median()))

    # ---------- 5) валидация заголовочных контрастов (cross-asset + год) ----------
    out.append("\n=== 5) ВАЛИДАЦИЯ ключевых контрастов (cross-asset знак + год-стабильность) ===")

    def contrast(metric_col, mask, split_col, hi_val, lo_val, decided_only=False):
        s = df[mask].copy()
        if decided_only:
            s = s[s.dirR != 0]
        hi = s[s[split_col] == hi_val]; lo = s[s[split_col] == lo_val]
        if len(hi) < 30 or len(lo) < 30:
            return None
        if metric_col == "Pdir":
            agg = lambda x: (x.dirR > 0).mean()
        else:
            agg = lambda x: x[metric_col].median()
        pooled = agg(hi) - agg(lo)
        syms = 0
        for sm in SYMBOLS:
            hs = hi[hi.symbol == sm]; ls = lo[lo.symbol == sm]
            if len(hs) >= 10 and len(ls) >= 10 and np.sign(agg(hs) - agg(ls)) == np.sign(pooled):
                syms += 1
        yrs = []
        for yr in sorted(s.year.unique()):
            hy = hi[hi.year == yr]; ly = lo[lo.year == yr]
            if len(hy) >= 8 and len(ly) >= 8:
                yrs.append(np.sign(agg(hy) - agg(ly)) == np.sign(pooled))
        ystab = (sum(yrs), len(yrs))
        return pooled, syms, ystab

    checks = [
        ("РЕВЕРСИВНЫЕ vs КОНТИНУАЦ — dir", "Pdir", df.dirR != 0, "nature", "REVERSAL", "CONTINUATION", True),
        ("ПО-тренду vs ПРОТИВ — dir", "Pdir", df.broke == 1, "trend_with", 1, 0, True),
        ("мульти-ТФ 3 vs 0-1 — dir", "Pdir", df.dirR != 0, "_mtf", "3", "0-1", True),
        ("мелкие vs крупные — ext", "ext_h", df.broke == 1, "_scale", "мелк", "крупн", False),
        ("сжатие vs расширение — ext", "ext_h", df.broke == 1, "_vol", "сжатие", "расширение", False),
        ("ПО-тренду vs ПРОТИВ — ft", "ft_ratio", df.broke == 1, "trend_with", 1, 0, False),
    ]
    df["_mtf"] = df.mtf_align.map(lambda v: "0-1" if v <= 1 else ("2" if v == 2 else "3"))
    df["_scale"] = pd.cut(df.height_atr, [-1, 3, 6, 1e9], labels=["мелк", "сред", "крупн"]).astype(str)
    df["_vol"] = pd.cut(df.vol_state, [-1, 0.9, 1.1, 1e9], labels=["сжатие", "норма", "расширение"]).astype(str)
    for name, metric, mask, col, hv, lv, dec in checks:
        r = contrast(metric, mask, col, hv, lv, dec)
        if r is None:
            out.append(f"  {name:40} (мало данных)"); continue
        pooled, syms, (yok, ytot) = r
        verdict = "РОБАСТНО" if syms >= 2 and ytot and yok / ytot >= 0.6 else "слабо/нестаб"
        out.append(f"  {name:40} Δ={pooled:+.3f}  cross-asset {syms}/3  год {yok}/{ytot}  -> {verdict}")

    # ---------- график-сводка ----------
    if cat_profiles:
        cat_profiles.sort(key=lambda x: x[3], reverse=True)
        names = [p[0] for p in cat_profiles]
        ext = [p[3] for p in cat_profiles]; pdir = [p[2] for p in cat_profiles]
        ft = [p[6] for p in cat_profiles]
        fig, axs = plt.subplots(1, 3, figsize=(18, max(5, len(names) * 0.45)))
        yy = np.arange(len(names))
        axs[0].barh(yy, ext, color="#2c7fb8"); axs[0].axvline(conf.ext_h.median(), color="r", ls="--", lw=1)
        axs[0].set_yticks(yy); axs[0].set_yticklabels(names, fontsize=7)
        axs[0].set_title("ДАЛЬНОСТЬ медиана ext (×высоты)\nкр.пунктир = маргинал"); axs[0].invert_yaxis()
        axs[1].barh(yy, pdir, color="#41ab5d"); axs[1].axvline(50, color="r", ls="--", lw=1)
        axs[1].set_yticks(yy); axs[1].set_yticklabels([]); axs[1].set_title("НАПРАВЛЕНИЕ P(textbook) %"); axs[1].invert_yaxis()
        axs[2].barh(yy, ft, color="#e6550d"); axs[2].axvline(0.5, color="r", ls="--", lw=1)
        axs[2].set_yticks(yy); axs[2].set_yticklabels([]); axs[2].set_title("КАЧЕСТВО ХОДА ft_ratio"); axs[2].invert_yaxis()
        fig.suptitle("Таксономия паттернов: профиль категорий (природа/тренд-связь/масштаб)", fontsize=12)
        fig.tight_layout()
        fig.savefig(HERE / "taxonomy_profiles.png", dpi=120)
        out.append(f"\n[график] taxonomy_profiles.png ({len(names)} категорий)")

    rep = HERE / "taxonomy_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[taxonomy] -> {rep.name}")


if __name__ == "__main__":
    main()
