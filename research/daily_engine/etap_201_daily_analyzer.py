"""etap_201 — ДНЕВНОЙ АНАЛИЗАТОР (продукт). Честный синтез:

  - ГРАНИЦЫ ДНЯ   — CatBoost range-модель (OOS R² 0.50): ожидаемый диапазон → high/low дня
  - РЕЖИМ ДНЯ     — big_day классификатор (OOS AUC 0.73): трендовый/флэтовый день
  - СИЛЬНЫЕ/СЛАБЫЕ ЗОНЫ — детерминированно: VP HVN(сильная)/LVN(слабая) + ICT OB/FVG + DOL
  - НАПРАВЛЕНИЕ   — ЧЕСТНО: ML=монетка, поэтому bias из СТРУКТУРЫ (value-migration + EMA-тренд
                   + premium/discount + order-flow), низкая конвикция, явно помечено
  - ТРЕЙД ДНЯ     — на робастном: fade границы диапазона к POC (direction-agnostic
                   mean-reversion) ИЛИ реакция сильной зоны по bias
  - АРГУМЕНТАЦИЯ  — SHAP по range-call + структурные факторы по bias

Обучается на всех данных ДО анализируемого дня (walk-forward честность). Пул BTC+ETH+SOL.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_201_daily_analyzer.py [SYMBOL] [YYYY-MM-DD]
        (по умолчанию BTCUSDT, последний доступный день)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from etap_198_daily_direction_v1 import daily_from_flow, build_features, atr, vpoc_va, ema, SYMBOLS
import vol_features as VF   # HAR-RV (волна 1, etap_243): +0.013 R² range, +0.008 AUC big_day

OUT = HERE / "output"


def hvn_lvn(H, L, V, price, n_bins=50):
    lo, hi = L.min(), H.max()
    edges = np.linspace(lo, hi, n_bins+1); prof = np.zeros(n_bins)
    for h, l, v in zip(H, L, V):
        b0 = max(np.searchsorted(edges, l, "right")-1, 0)
        b1 = min(np.searchsorted(edges, h, "right")-1, n_bins-1)
        if b1 == b0: prof[b0] += v
        else: prof[b0:b1+1] += v/(b1-b0+1)
    sm = np.convolve(prof, np.ones(3)/3, mode="same")
    cen = (edges[:-1]+edges[1:])/2
    hvn = [cen[i] for i in range(1, n_bins-1) if sm[i] > sm[i-1] and sm[i] >= sm[i+1] and sm[i] > sm.mean()]
    lvn = [cen[i] for i in range(1, n_bins-1) if sm[i] < sm[i-1] and sm[i] <= sm[i+1] and sm[i] < sm.mean()*0.6]
    return hvn, lvn


def ict_zones(o, h, l, c, price, atr14):
    """ближайшие незакрытые FVG (канон c1-c3) и OB к цене."""
    n = len(c); zones = {"fvg_bull": None, "fvg_bear": None, "ob_bull": None, "ob_bear": None}
    for i in range(1, n-1):
        if h[i-1] < l[i+1]:  # bullish FVG
            top, bot = l[i+1], h[i-1]
            if not ((l[i+2:] < bot).any() if i+2 < n else False) and top <= price:
                if zones["fvg_bull"] is None or top > zones["fvg_bull"][1]: zones["fvg_bull"] = (bot, top)
        if l[i-1] > h[i+1]:  # bearish FVG
            top, bot = l[i-1], h[i+1]
            if not ((h[i+2:] > top).any() if i+2 < n else False) and bot >= price:
                if zones["fvg_bear"] is None or bot < zones["fvg_bear"][0]: zones["fvg_bear"] = (bot, top)
    for i in range(1, n):
        if c[i-1] < o[i-1] and c[i] > o[i-1]:
            top, bot = o[i-1], min(l[i-1], l[i])
            if not ((l[i+1:] < bot).any() if i+1 < n else False) and top < price:
                if zones["ob_bull"] is None or top > zones["ob_bull"][1]: zones["ob_bull"] = (bot, top)
        if c[i-1] > o[i-1] and c[i] < o[i-1]:
            top, bot = max(h[i-1], h[i]), o[i-1]
            if not ((h[i+1:] > top).any() if i+1 < n else False) and bot > price:
                if zones["ob_bear"] is None or bot < zones["ob_bear"][0]: zones["ob_bear"] = (bot, top)
    return zones


def train_models(date):
    """Обучить range-регрессор + big_day классификатор на всех данных ДО date (пул 3 актива)."""
    from catboost import CatBoostRegressor, CatBoostClassifier, Pool
    frames = []
    for sym in SYMBOLS:
        d = daily_from_flow(sym)
        f = build_features(d).shift(1)
        f["gap"] = (d["open"] - d["close"].shift(1)) / atr(d, 14)
        f = VF.augment(f, sym)         # HAR-RV (as-of t-1, симметрично с analyze)
        f = VF.augment_dvol(f, sym)    # DVOL forward-IV (BTC/ETH; SOL→NaN)
        f["asset"] = sym
        rng = (d["high"] - d["low"]) / d["close"].shift(1)
        f["log_range"] = np.log(rng.clip(lower=1e-6))
        f["big_day"] = (rng > rng.rolling(30).median()).astype(int)
        f["date"] = d.index
        f["_open"] = d["open"]; f["_high"] = d["high"]; f["_low"] = d["low"]
        f["_pc"] = d["close"].shift(1); f["_rf"] = rng
        frames.append(f.dropna())
    data = pd.concat(frames).sort_values("date")
    feat_cols = [c for c in data.columns if c not in
                 ("log_range", "big_day", "date", "_open", "_high", "_low", "_pc", "_rf")]
    cat_idx = [feat_cols.index("asset")]
    tr = data[data["date"] < date]
    reg = CatBoostRegressor(iterations=500, depth=5, learning_rate=0.03, l2_leaf_reg=6,
                            loss_function="RMSE", random_seed=42, verbose=0)
    reg.fit(Pool(tr[feat_cols], tr["log_range"], cat_features=cat_idx), verbose=0)
    clf = CatBoostClassifier(iterations=400, depth=4, learning_rate=0.03, l2_leaf_reg=8,
                             random_seed=42, verbose=0)
    clf.fit(Pool(tr[feat_cols], tr["big_day"], cat_features=cat_idx), verbose=0)
    # калибровки (Фаза 3, OOS-проверены): режимный ratio + множитель k под ~80% контейнмент
    trc = tr.copy()
    trc["pr"] = np.exp(reg.predict(trc[feat_cols]))
    trc["pb"] = clf.predict_proba(trc[feat_cols])[:, 1]
    r_big = float((trc.loc[trc["pb"] >= .5, "_rf"] / trc.loc[trc["pb"] >= .5, "pr"]).median())
    r_flat = float((trc.loc[trc["pb"] < .5, "_rf"] / trc.loc[trc["pb"] < .5, "pr"]).median())
    trc["prc"] = np.where(trc["pb"] >= .5, trc["pr"] * r_big, trc["pr"] * r_flat)
    need = (np.maximum(trc["_high"] - trc["_open"], trc["_open"] - trc["_low"]) / trc["_pc"] / trc["prc"])
    need = need.replace([np.inf, -np.inf], np.nan).dropna()
    k = float(np.quantile(need, 0.80))
    return reg, clf, feat_cols, cat_idx, {"r_big": r_big, "r_flat": r_flat, "k": k}


def analyze(symbol="BTCUSDT", date=None):
    from catboost import Pool
    d = daily_from_flow(symbol)
    if date is None:
        date = d.index[-1]          # последний доступный день
    else:
        date = pd.Timestamp(date, tz="UTC")
    di = d.index.get_loc(date)
    o, h, l, c, v = (d[x].values for x in ["open", "high", "low", "close", "volume"])
    open_t = o[di]; prev_close = c[di-1]; a14 = atr(d, 14).iloc[di-1]
    price = open_t

    reg, clf, feat_cols, cat_idx, calib = train_models(date)
    # фича-строка дня (as-of date-1) + gap
    f = build_features(d).shift(1)
    f["gap"] = (d["open"] - d["close"].shift(1)) / atr(d, 14)
    f = VF.augment(f, symbol)          # HAR-RV (симметрично с train_models)
    f = VF.augment_dvol(f, symbol)     # DVOL forward-IV (симметрично с train_models)
    f["asset"] = symbol
    row = f.loc[[date], feat_cols]
    exp_log_range = float(reg.predict(row)[0])
    p_big = float(clf.predict_proba(row)[0, 1])

    # границы дня (Фаза 3, OOS ~77% контейнмент): режимная де-калибровка + калиброванный k
    ratio = calib["r_big"] if p_big >= 0.5 else calib["r_flat"]
    exp_range = np.exp(exp_log_range) * ratio * prev_close   # corrected ожидаемый |high-low| дня в $
    half = calib["k"] * exp_range
    hi_b = open_t + half
    lo_b = open_t - half

    # зоны на окне 60 дней до date
    w = slice(max(0, di-60), di)
    hvn, lvn = hvn_lvn(h[w], l[w], v[w], price)
    vpoc, vah, val = vpoc_va(h[w], l[w], v[w])
    zz = ict_zones(o[w], h[w], l[w], c[w], price, a14)
    # DOL: ближайшие фрактальные ликвидности (N=2) сверху/снизу
    fh = [h[i] for i in range(di-60, di-2) if h[i] > max(h[i-2:i].max(), h[i+1:i+3].max())]
    fl = [l[i] for i in range(di-60, di-2) if l[i] < min(l[i-2:i].min(), l[i+1:i+3].min())]
    bsl = min([x for x in fh if x > price], default=None)
    ssl = max([x for x in fl if x < price], default=None)

    # структурный bias (честный, низкая конвикция)
    e20 = ema(d["close"], 20).iloc[di-1]; e50 = ema(d["close"], 50).iloc[di-1]
    vpoc_prev, _, _ = vpoc_va(h[max(0,di-65):di-5], l[max(0,di-65):di-5], v[max(0,di-65):di-5])
    val_migr = "вверх" if vpoc > vpoc_prev*1.002 else ("вниз" if vpoc < vpoc_prev*0.998 else "флэт")
    pos_va = (price - val) / (vah - val) if vah > val else 0.5
    delta_d = float(f.loc[date, "delta_norm"]) if "delta_norm" in f.columns else 0.0
    score = 0
    score += 1 if price > e20 else -1
    score += 1 if e20 > e50 else -1
    score += 1 if val_migr == "вверх" else (-1 if val_migr == "вниз" else 0)
    score += -1 if pos_va > 0.8 else (1 if pos_va < 0.2 else 0)   # premium fade / discount buy
    score += 1 if delta_d > 0 else -1
    bias = "LONG-уклон" if score >= 2 else ("SHORT-уклон" if score <= -2 else "НЕЙТРАЛЬНО")

    # SHAP-аргументация range-прогноза
    shap = reg.get_feature_importance(Pool(row, [exp_log_range], cat_features=cat_idx), type="ShapValues")[0]
    contrib = sorted(zip(feat_cols, shap[:-1]), key=lambda x: -abs(x[1]))[:5]

    fmt = lambda x: f"{x:,.0f}" if x is not None else "—"
    zr = lambda z: f"{z[0]:,.0f}-{z[1]:,.0f}" if z else "—"
    print("="*70)
    print(f"ДНЕВНОЙ АНАЛИЗ {symbol} · {date:%Y-%m-%d} (open {fmt(open_t)}, prev close {fmt(prev_close)})")
    print("="*70)
    print(f"\n■ РЕЖИМ ДНЯ: P(большой день)={p_big:.2f} → {'ТРЕНДОВЫЙ/широкий' if p_big>0.55 else ('ФЛЭТ/узкий' if p_big<0.45 else 'средний')}")
    print(f"  ATR14={fmt(a14)} | ожидаемый диапазон дня ≈ {fmt(exp_range)} ({exp_range/prev_close*100:.1f}%)")
    print(f"\n■ ГРАНИЦЫ ДНЯ (от open, до направления): ВЕРХ ≈ {fmt(hi_b)} | НИЗ ≈ {fmt(lo_b)}")
    print(f"\n■ СИЛЬНЫЕ ЗОНЫ (магниты/опора — HVN/POC):")
    print(f"   VPOC {fmt(vpoc)} | VAH {fmt(vah)} / VAL {fmt(val)}")
    print(f"   HVN: {', '.join(fmt(x) for x in sorted(hvn)) or '—'}")
    print(f"   ICT: OB_bull↓ {zr(zz['ob_bull'])} | OB_bear↑ {zr(zz['ob_bear'])} | FVG_bull↓ {zr(zz['fvg_bull'])} | FVG_bear↑ {zr(zz['fvg_bear'])}")
    print(f"\n■ СЛАБЫЕ ЗОНЫ (быстрый проход — LVN): {', '.join(fmt(x) for x in sorted(lvn)) or '—'}")
    print(f"\n■ DOL (ликвидность-цели): BSL↑ {fmt(bsl)} | SSL↓ {fmt(ssl)}")
    print(f"\n■ НАПРАВЛЕНИЕ (⚠️ ML=монетка; bias из СТРУКТУРЫ, низкая конвикция): {bias}  [score {score:+d}]")
    print(f"   тренд: цена {'>' if price>e20 else '<'} EMA20, EMA20{'>' if e20>e50 else '<'}EMA50 | value-migration {val_migr}")
    print(f"   локация: {pos_va*100:.0f}% VA ({'premium' if pos_va>0.5 else 'discount'}) | дневной delta {'+' if delta_d>0 else '−'}")
    # трейд дня
    print(f"\n■ ТРЕЙД ДНЯ (на робастном edge):")
    if p_big < 0.45:
        print(f"   ФЛЭТ-день ожидается → MEAN-REVERSION: продавать у ВЕРХ-границы {fmt(hi_b)} к POC {fmt(vpoc)},")
        print(f"   покупать у НИЗ-границы {fmt(lo_b)} к POC. Стоп за границу +0.2·ATR.")
    else:
        side = "LONG" if "LONG" in bias else ("SHORT" if "SHORT" in bias else "по реакции")
        anchor = zz['ob_bull'] or (sorted(hvn)[-1:] or [val])[0] if side=="LONG" else zz['ob_bear']
        print(f"   ШИРОКИЙ день → CONTINUATION по bias ({side}): вход от сильной зоны с подтверждением,")
        print(f"   цель — противоположная граница/DOL. Если bias НЕЙТРАЛЬНО — ждать реакции зоны.")
    print(f"\n■ АРГУМЕНТАЦИЯ диапазона (SHAP, топ-5 вкладов в прогноз):")
    for name, val_ in contrib:
        sign = "↑расширяет" if val_ > 0 else "↓сужает"
        print(f"   {name:14} {sign} ({val_:+.3f})")
    print("\n⚠️ Направление статистически непредсказуемо (доказано: AUC 0.50). Торгуемый edge — в")
    print("   ГРАНИЦАХ (R² 0.50) и реакции ЗОН. Bias — лишь приоритет сценария, не прогноз.")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    dt = sys.argv[2] if len(sys.argv) > 2 else None
    analyze(sym, dt)
