"""etap_251 — CatBoost-сегментация 1.1.1 SWEPT (BTC+ETH+SOL): улучшить net-грейд etap_249.

Идея: вместо РУЧНЫХ классов — пусть CatBoost учит P(win) по богатому набору фич
(структура сигнала + модуль аналитики v2), затем бакетим OOS-предсказания в ~10 групп
(децили) → WR каждой. Это калибровочный взгляд: монотонна ли P(win) OOS?

ВАЖНО (стена learned-meta, etap_179-188): обучаемый фильтр поверх сделок почти всегда
дохнет OOS. Поэтому ЖЁСТКИЙ протокол:
  - train < 2024, test 2024-26 (true OOS), пул 3 монет (asset = категория) + per-symbol
  - permutation-null (shuffle меток win, 20 ретрейнов) — AUC реальной vs null
  - бар: OOS AUC > 0.55 И > null. Иначе = переобучение, ручной грейд лучше.
  - сравнение: CatBoost top-половина vs ручной net-грейд (etap_249) на тех же OOS.

Фичи: direction, top_tf, macro_tf, htf_tf, fvg_tf, session, state (катег.);
risk_pct, hour, eff, gauge, p_green, trend_hold, dow (числ.).

Запуск: venv/Scripts/python.exe research/daily_engine/etap_251_catboost_segmentation.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1_floating import detect_signals_111, check_swept, build_entry_sl, simulate_floating, build_score_series
import etap_217_daytype_layer as L
from etap_249_swept_segmentation import session, eff_ratio
sys.path.insert(0, str(ROOT))
import signal_context as SC

RR = 2.2
OUT = HERE / "output"
CACHE = OUT / "etap_251_dataset.csv"
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CUTOFF = pd.Timestamp("2024-01-01", tz="UTC")   # train < 2024, test >=

CAT = ["asset", "direction", "top_tf", "macro_tf", "htf_tf", "fvg_tf", "session", "state"]
NUM = ["risk_pct", "hour", "eff", "gauge", "p_green", "trend_hold", "dow"]
FEATS = CAT + NUM


def collect(sym, M):
    df_1d = load_df(sym, "1d"); df_4h = load_df(sym, "4h"); df_1h = load_df(sym, "1h")
    df_12h = compose_from_base(df_1h, "12h"); df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(sym, "15m"); df_1m = load_df(sym, "1m"); df_20m = compose_from_base(df_1m, "20m")
    for d in (df_1h, df_1m):
        if d.index.tz is None: d.index = d.index.tz_localize("UTC")
    signals = detect_signals_111(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    swept = [s for s in signals if check_swept(s, df_1h, df_2h)]
    seen, dedup = set(), []
    for s in swept:
        k = (pd.Timestamp(s["signal_time"]).isoformat(), s["direction"], tuple(s["fvg_zone"]))
        if k not in seen:
            seen.add(k); dedup.append(s)
    sl_, ss_ = build_score_series(df_1h)
    daily = df_1h.resample("1D").agg({"open": "first", "high": "max", "low": "min"})
    dmed = ((daily.high - daily.low) / daily.open).rolling(20).median().shift(1)
    rows = []
    for s in dedup:
        res = simulate_floating(s, df_1m, df_1h, sl_, ss_, R_cap=RR, threshold=-1e9, confirm=10**6, max_hold_days=3650)
        if res is None or res.outcome not in ("win", "loss", "flat"):
            continue
        t = pd.Timestamp(s["signal_time"]); t = t.tz_localize("UTC") if t.tz is None else t
        day = t.normalize(); es = build_entry_sl(s) or (np.nan, np.nan)
        entry, sl = es; risk_pct = abs(entry - sl) / entry * 100 if entry else np.nan
        bars = df_1h[(df_1h.index.normalize() == day) & (df_1h.index <= t)]
        state, p_green, kk = "FORMING", 0.5, len(bars)
        if len(bars) >= L.IB + 2:
            dec, _ = L.daytype_nowcast(bars, M)
            kk, state, p_green = dec[-1][0], dec[-1][1], dec[-1][2]
        th = SC.trend_hold_p(state, kk); th = th if th is not None else 0.5
        m = df_1m[(df_1m.index.normalize() == day) & (df_1m.index <= t)]["close"].values
        eff = eff_ratio(m) if len(m) >= 60 else np.nan
        rng_sf = (bars["high"].max() - bars["low"].min()) / bars["open"].iloc[0] if len(bars) else np.nan
        exp = dmed.reindex([day]).iloc[0] if day in dmed.index else np.nan
        gauge = rng_sf / exp if (exp and exp > 0) else np.nan
        rows.append(dict(signal_time=t, year=t.year, asset=sym, win=int(res.outcome == "win"),
                         direction=s["direction"], top_tf=s.get("top_tf"), macro_tf=s.get("fvg_macro_tf"),
                         htf_tf=s.get("ob_htf_tf"), fvg_tf=s.get("fvg_tf"), risk_pct=risk_pct,
                         state=state, hour=t.hour, session=session(t.hour), eff=eff, gauge=gauge,
                         p_green=p_green, trend_hold=th, dow=t.dayofweek))
    return pd.DataFrame(rows)


def build_dataset():
    if CACHE.exists():
        d = pd.read_csv(CACHE, parse_dates=["signal_time"])
        print(f"[cache] {len(d)} сделок из {CACHE.name}")
        return d
    bt = load_df("BTCUSDT", "1h")
    if bt.index.tz is None: bt.index = bt.index.tz_localize("UTC")
    M = L.fit_per_hour(L.build(bt).replace([np.inf, -np.inf], np.nan).fillna(0.0).query("day < @L.CUTOFF"))
    parts = []
    for s in SYMS:
        print(f"[collect] {s}...")
        parts.append(collect(s, M))
    d = pd.concat(parts, ignore_index=True)
    for c in CAT: d[c] = d[c].astype(str)
    d = d.replace([np.inf, -np.inf], np.nan)
    d.to_csv(CACHE, index=False)
    print(f"[saved] {CACHE.name}: {len(d)}")
    return d


def hand_net_grade(d):
    """Ручной net-грейд etap_249 (per-symbol терцили) — baseline для сравнения."""
    out = []
    for sym, g in d.groupby("asset"):
        p33, p67 = g.risk_pct.quantile(0.33), g.risk_pct.quantile(0.67)
        weak = ((g.risk_pct >= p67).astype(int) + (g.gauge >= 1.0).astype(int) + (g.fvg_tf == "20m").astype(int)
                + g.session.isin(["London (7-13)", "NY (13-21)"]).astype(int) + (g.state == "ROTATION").astype(int))
        ct = (((g.direction == "SHORT") & (g.state == "TREND_UP")) | ((g.direction == "LONG") & (g.state == "TREND_DOWN"))).astype(int)
        strong = (g.risk_pct <= p33).astype(int) + (g.hour < 7).astype(int) + ct
        out.append(pd.Series(strong - weak, index=g.index))
    return pd.concat(out).reindex(d.index)


def main():
    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import roc_auc_score
    d = build_dataset()
    d = d.dropna(subset=["win"]).reset_index(drop=True)
    for c in NUM: d[c] = pd.to_numeric(d[c], errors="coerce")
    d[NUM] = d[NUM].fillna(d[NUM].median())
    for c in CAT: d[c] = d[c].astype(str)
    print(f"\nвсего сделок: {len(d)} | по монетам: {dict(d.asset.value_counts())}")
    print(f"база WR: {d.win.mean()*100:.1f}% | train<2024 n={ (d.signal_time<CUTOFF).sum() } test n={ (d.signal_time>=CUTOFF).sum() }")

    tr = d[d.signal_time < CUTOFF]; te = d[d.signal_time >= CUTOFF]
    ci = [FEATS.index(c) for c in CAT]
    def fit(tr_):
        m = CatBoostClassifier(iterations=300, depth=4, learning_rate=0.03, l2_leaf_reg=8,
                               random_seed=42, verbose=0)
        m.fit(Pool(tr_[FEATS], tr_.win, cat_features=ci)); return m
    m = fit(tr)
    p_te = m.predict_proba(Pool(te[FEATS], cat_features=ci))[:, 1]
    auc_oos = roc_auc_score(te.win, p_te)
    auc_in = roc_auc_score(tr.win, m.predict_proba(Pool(tr[FEATS], cat_features=ci))[:, 1])

    print("\n" + "=" * 80)
    print(f"CatBoost P(win) — пул 3 монет. AUC in-sample={auc_in:.3f}  OOS(2024-26)={auc_oos:.3f}")
    print("=" * 80)

    # permutation-null (shuffle меток в train)
    rng = np.random.RandomState(0); nulls = []
    for i in range(20):
        t2 = tr.copy(); t2["win"] = rng.permutation(t2.win.values)
        mn = fit(t2); nulls.append(roc_auc_score(te.win, mn.predict_proba(Pool(te[FEATS], cat_features=ci))[:, 1]))
    nulls = np.array(nulls)
    pval = (nulls >= auc_oos).mean()
    print(f"  permutation-null OOS AUC: среднее {nulls.mean():.3f} (макс {nulls.max():.3f}), p={pval:.3f}")
    bar = "ПРОШЁЛ" if (auc_oos > 0.55 and pval < 0.1) else "НЕ ПРОШЁЛ"
    print(f"  бар (OOS AUC>0.55 И p<0.1): {bar}")

    # бакеты по P(win) на OOS → ~10 групп (квинтили если мало)
    te = te.copy(); te["p"] = p_te
    nb = 10 if len(te) >= 120 else (5 if len(te) >= 50 else 3)
    te["bucket"] = pd.qcut(te.p.rank(method="first"), nb, labels=False)
    print(f"\n■ Калибровка OOS: {nb} групп по P(win) (CatBoost):")
    for b, g in te.groupby("bucket"):
        print(f"   дециль {int(b)+1:>2}: pred P={g.p.mean():.2f}  факт WR={g.win.mean()*100:>5.1f}%  n={len(g)}")

    # SHAP-важность
    imp = dict(zip(FEATS, m.get_feature_importance(Pool(tr[FEATS], tr.win, cat_features=ci))))
    print("\n■ Важность фич (CatBoost):")
    for f in sorted(FEATS, key=lambda x: -imp.get(x, 0))[:10]:
        print(f"   {f:<12} {imp.get(f,0):.1f}")

    # сравнение с ручным net-грейдом на ТЕХ ЖЕ OOS
    d["net"] = hand_net_grade(d)
    teh = d[d.signal_time >= CUTOFF]
    hi = teh[teh.net >= 0]; lo = teh[teh.net < 0]
    cb_hi = te[te.p >= te.p.median()]; cb_lo = te[te.p < te.p.median()]
    print("\n■ OOS 2024-26: CatBoost (top-половина P) vs ручной net-грейд (net≥0):")
    print(f"   CatBoost top:  WR {cb_hi.win.mean()*100:.1f}% (n={len(cb_hi)}) | bottom {cb_lo.win.mean()*100:.1f}% (n={len(cb_lo)})  спред {(cb_hi.win.mean()-cb_lo.win.mean())*100:+.1f}пп")
    print(f"   net-грейд≥0:   WR {hi.win.mean()*100:.1f}% (n={len(hi)}) | net<0 {lo.win.mean()*100:.1f}% (n={len(lo)})  спред {(hi.win.mean()-lo.win.mean())*100:+.1f}пп")

    # per-symbol OOS AUC
    print("\n■ Per-symbol OOS AUC (модель пула применена к каждой монете):")
    for sym, g in te.groupby("asset"):
        if g.win.nunique() > 1 and len(g) >= 15:
            print(f"   {sym}: AUC={roc_auc_score(g.win, g.p):.3f} n={len(g)} WR={g.win.mean()*100:.0f}%")
    te.to_csv(OUT / "etap_251_oos_buckets.csv", index=False)
    print(f"\nSaved: {OUT/'etap_251_oos_buckets.csv'}")


if __name__ == "__main__":
    main()
