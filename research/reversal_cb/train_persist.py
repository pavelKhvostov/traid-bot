"""Обучить + ПЕРСИСТНУТЬ финальные модели Магнитуды для live: ① long-8h, ② short-12h.
Финальная модель на ВСЕЙ размеченной истории (пул BTC/ETH/SOL), без class-weights (калиброванная proba).
Сохраняет: models/magnitude_long_8h.cbm, models/magnitude_short_12h.cbm, models/magnitude_config.json
(FEATS, THR, CAP, порог-флаг per-direction = 70-й перцентиль proba финальной модели, RR-бакет).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/reversal_cb/train_persist.py
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from reversal_analysis import load, feats, THR, CAP  # noqa: E402
from reversal_module import FEATS  # noqa: E402
from rr_native import native  # noqa: E402
from catboost import CatBoostClassifier  # noqa: E402
ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
SPECS = {"long": dict(tf="8h", rr=[2.5, 4.0]), "short": dict(tf="12h", rr=[1.5, 4.0])}


def build_xy(direction, tf):
    X = []; y = []
    for s in SYMS:
        df = load(s, tf); F = feats(df); yy, R, risk = native(df, direction, 0.0010, 0.0010)
        m = (yy >= 0) & F[FEATS].notna().all(axis=1).values & np.isfinite(risk)
        X.append(F[FEATS][m]); y.append(yy[m])
    return pd.concat(X, ignore_index=True), np.concatenate(y)


def main():
    MODELS.mkdir(exist_ok=True)
    cfg = {"FEATS": FEATS, "THR": THR, "CAP": CAP, "flag_pct": 0.70, "directions": {}}
    out = ["=== TRAIN+PERSIST Магнитуда (финальные live-модели) ==="]
    for direction, spec in SPECS.items():
        tf = spec["tf"]
        Xdf, y = build_xy(direction, tf)
        model = CatBoostClassifier(iterations=300, depth=6, learning_rate=0.05, loss_function="Logloss",
                                   random_seed=7, verbose=False)
        try:
            model = CatBoostClassifier(iterations=300, depth=6, learning_rate=0.05, loss_function="Logloss",
                                       random_seed=7, verbose=False, task_type="GPU", devices="0")
            model.fit(Xdf.values, y)
        except Exception:
            model = CatBoostClassifier(iterations=300, depth=6, learning_rate=0.05, loss_function="Logloss",
                                       random_seed=7, verbose=False)
            model.fit(Xdf.values, y)
        proba = model.predict_proba(Xdf.values)[:, 1]
        thr = float(np.quantile(proba, cfg["flag_pct"]))
        fname = f"magnitude_{direction}_{tf}.cbm"
        model.save_model(str(MODELS / fname))
        cfg["directions"][direction] = {"tf": tf, "rr": spec["rr"], "flag_thr": thr,
                                        "model": fname, "n_train": int(len(y)), "base_rate": float(y.mean())}
        out.append(f"  {direction} {tf}: n={len(y)} base={y.mean():.3f} flag_thr(p70)={thr:.3f} -> {fname}")
    (MODELS / "magnitude_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    out.append(f"  config -> models/magnitude_config.json")
    print("\n".join(out))


if __name__ == "__main__":
    main()
