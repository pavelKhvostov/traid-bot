"""etap_210 — ВКЛЮЧАЕМ CatBoost в связку Bulkowski × анализатор (честный OOS).

Раньше (etap_208/209) брали только структуру + REALIZED режим (с look-ahead в метке).
Здесь подключаем НАСТОЯЩИЙ CatBoost-слой анализатора:
  - big_day классификатор (OOS AUC 0.73) обучаем на данных ДО cutoff,
  - предсказываем P_big(день) AS-OF прошлый день (без утечки),
  - связываем с Bulkowski: aligned_bias<0 (разворот против структуры) × P_big-гейт.

Вопрос: восстанавливает ли ПРЕДСКАЗАННЫЙ режим edge realized-режима (busted 47%→41%)
на чистом OOS? И помогает ли CatBoost вообще как направление? (спойлер: направление —
монетка, поэтому связь идёт через РЕЖИМ, не направление.)

Запуск: venv/Scripts/python.exe research/daily_engine/etap_210_catboost_bulkowski.py
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
import etap_201_daily_analyzer as A
import etap_209_bulkowski_interactions as I9

ROOT = HERE.parent.parent
SIG_GEOM = ROOT / "research/elements_study/output/etap_172_all_signals_geom.csv"
SIG_OUT  = ROOT / "research/elements_study/output/etap_172_signals.csv"
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")   # train CatBoost на 2020-2022, OOS 2023-2026


def row_block(tag, s):
    print(f"  {tag:<38} | n={len(s):>3} | ult {s['ult'].mean():>+6.1f}% | busted {(s['busted']==True).mean()*100:>3.0f}% "
          f"| half {(s['ult']>= s['height_pct']/2).mean()*100:>3.0f}%")


def main():
    geom = pd.read_csv(SIG_GEOM)
    out = pd.read_csv(SIG_OUT)[["time", "pattern", "side", "ult_move_pct", "busted"]]
    df = geom.merge(out, on=["time", "pattern", "side"], how="left")
    df["day"] = pd.to_datetime(df["time"], utc=True).dt.normalize()
    df["year"] = pd.to_datetime(df["time"], utc=True).dt.year

    # --- дневные серии (BTC) ---
    d = A.daily_from_flow("BTCUSDT")
    f0 = A.build_features(d).shift(1)
    atr14 = A.atr(d, 14); ema20 = A.ema(d["close"], 20); ema50 = A.ema(d["close"], 50)
    rng = (d["high"] - d["low"]) / d["close"].shift(1)
    big_series = (rng > rng.rolling(30).median()).astype(int)

    # --- CatBoost big_day, обучен на данных ДО CUTOFF (пул 3 актива, как в анализаторе) ---
    print(f"Тренирую CatBoost big_day на данных < {CUTOFF.date()} ...")
    reg, clf, feat_cols, cat_idx, calib = A.train_models(CUTOFF)

    # фичи BTC для предсказания P_big as-of прошлый день
    fb = A.build_features(d).shift(1)
    fb["gap"] = (d["open"] - d["close"].shift(1)) / A.atr(d, 14)
    fb["asset"] = "BTCUSDT"
    fb = fb.reindex(columns=feat_cols)
    valid = fb.dropna()
    p_big = pd.Series(clf.predict_proba(valid)[:, 1], index=valid.index)

    # OOS-калибровка модели (sanity): средний P_big vs realized big-rate на 2023+
    oos_days = p_big.index[p_big.index >= CUTOFF]
    realized_oos = big_series.reindex(oos_days).mean()
    print(f"  OOS 2023+: mean predicted P_big = {p_big.reindex(oos_days).mean():.3f} | realized big-rate = {realized_oos:.3f}")
    # дискриминация: realized big-rate среди предсказанных high vs low
    hi_days = oos_days[p_big.reindex(oos_days) >= 0.5]
    lo_days = oos_days[p_big.reindex(oos_days) < 0.5]
    print(f"  pred P_big>=.5 → realized big {big_series.reindex(hi_days).mean():.2f} (n={len(hi_days)}) | "
          f"pred<.5 → realized big {big_series.reindex(lo_days).mean():.2f} (n={len(lo_days)})")

    # --- связываем с сигналами ---
    rows = []
    for _, s in df.iterrows():
        if pd.isna(s["ult_move_pct"]): continue
        st = I9.read_rich(d, f0, atr14, ema20, ema50, big_series, s["day"], s["breakout_price"], s["side"])
        if st is None: continue
        day = pd.Timestamp(s["day"])
        day = (day.tz_localize("UTC") if day.tzinfo is None else day.tz_convert("UTC")).normalize()
        pb = float(p_big.reindex([day]).iloc[0]) if day in p_big.index else np.nan
        rows.append(dict(year=int(s["year"]), side=s["side"], height_pct=s["height_pct"],
                         aligned_bias=st["aligned_bias"], realized_big=st["big"], p_big=pb,
                         dol=st["dol"], ult=s["ult_move_pct"], busted=s["busted"]))
    r = pd.DataFrame(rows)
    oos = r[(r["year"] >= 2023) & r["p_big"].notna()].copy()

    print("\n" + "="*92)
    print(f"СВЯЗКА Bulkowski × CatBoost-режим — OOS 2023-2026 ({len(oos)} сигналов)")
    print("="*92)

    print("\n■ CatBoost P_big САМ — дискриминирует ли исход Bulkowski?")
    row_block("P_big >= 0.5 (предсказан широкий)", oos[oos.p_big >= 0.5])
    row_block("P_big <  0.5 (предсказан узкий)", oos[oos.p_big < 0.5])

    print("\n■ bias-инверсия (структура), OOS")
    row_block("aligned_bias < 0 (против структуры)", oos[oos.aligned_bias < 0])
    row_block("aligned_bias >= 0", oos[oos.aligned_bias >= 0])

    print("\n■ СВЯЗКА: aligned<0  ×  CatBoost-режим (предсказанный vs realized)")
    base = oos[oos.aligned_bias < 0]
    row_block("aligned<0 (база)", base)
    row_block("aligned<0 & P_big>=0.5 (ПРЕДСКАЗАН)", base[base.p_big >= 0.5])
    row_block("aligned<0 & P_big>=0.6 (ПРЕДСКАЗАН+)", base[base.p_big >= 0.6])
    row_block("aligned<0 & realized big (для сверки)", base[base.realized_big == 1])

    print("\n■ + убрать DOL-anti-конфлюэнс (etap_209): aligned<0 & P_big>=.5 & breakout НЕ у DOL")
    row_block("финальная связка", base[(base.p_big >= 0.5) & (base.dol == 0)])

    print("\n■ Контроль (что НЕ надо брать): aligned>=0 & P_big<0.5")
    row_block("anti-setup", oos[(oos.aligned_bias >= 0) & (oos.p_big < 0.5)])

    oos.to_csv(A.OUT / "etap_210_catboost_bulkowski.csv", index=False)
    print(f"\nSaved: {A.OUT / 'etap_210_catboost_bulkowski.csv'}")


if __name__ == "__main__":
    main()
