"""neural_signals_live.py — прод-инференс: свежие сигналы → оценка нейросетью 1-5 → бот.

Связывает обученную модель (etap_179) с Telegram-ботом (neural_bot.py).
Раз в INTERVAL: генерит свежие сигналы всех стратегий за последние LOOKBACK_DAYS,
оценивает класс качества 1-5 нейросетью, шлёт новые (class>=MIN_GRADE) в бота.

Дедуп: бот сам дедупит по ключу; плюс свой кэш отправленных.

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u neural_signals_live.py
Требует обученную модель в research/elements_study/output/etap179_model/.
"""
from __future__ import annotations

import sys as _sys
import time
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import importlib.util as _ilu
import numpy as np
import pandas as pd

INTERVAL_SEC = 1800          # как часто проверять новые сигналы (30 мин)
LOOKBACK_DAYS = 30           # окно поиска свежих сигналов
MIN_GRADE = 4                # слать class>=4 (взял TP). Фильтр etap_179 слабый
                             # (ρ~0.06), но class>=4 = лучшая часть; на топе lift ~×1.2
MODEL_DIR = _ROOT / "research" / "elements_study" / "output" / "etap179_model"
SENT_CACHE = _ROOT / "state" / "neural_bot" / "live_sent.json"

# загрузим генератор сигналов и инфраструктуру модели
_s179 = _ilu.spec_from_file_location("e179", _ROOT / "research/elements_study/etap_179_signal_grade_3assets_mda.py")
_e179 = _ilu.module_from_spec(_s179); _s179.loader.exec_module(_e179)
_e178 = _e179._e178
_e177 = _e179._e177

import neural_bot as nb

SNAME = {0: "1.1.1", 1: "1.1.2", 2: "1.1.3", 3: "FRACTAL", 4: "1.1.4"}


def load_model(device):
    import torch
    meta = json.loads((MODEL_DIR / "meta.json").read_text(encoding="utf-8"))
    feats = meta["feats"]; n_folds = meta["n_folds"]
    nets, scalers = [], []
    for fi in range(n_folds):
        net = _e178.build_ordinal_net(len(feats)).to(device)
        net.load_state_dict(torch.load(MODEL_DIR / f"net_fold{fi}.pt", map_location=device))
        net.eval()
        nets.append(net)
        z = np.load(MODEL_DIR / f"scaler_fold{fi}.npz")
        scalers.append((z["mean"], z["scale"]))
    return nets, scalers, feats, meta


def score_signals(ds_feat, feats, nets, scalers, device):
    """Ансамблевый ординальный score (1-5) для каждого сигнала."""
    X = ds_feat[feats].values.astype(float)
    preds = []
    for net, (mean, scale) in zip(nets, scalers):
        Xs = (X - mean) / scale
        preds.append(_e178.ordinal_predict_score(net, Xs, device))
    return np.mean(preds, axis=0)


def gen_recent_signals():
    """Свежие сигналы всех стратегий за LOOKBACK_DAYS по 3 активам с фичами."""
    cutoff = pd.Timestamp.utcnow().tz_localize("UTC") if pd.Timestamp.utcnow().tz is None else pd.Timestamp.utcnow()
    cutoff = cutoff - pd.Timedelta(days=LOOKBACK_DAYS)
    parts = []
    for aid, sym in enumerate(_e179.SYMBOLS):
        g = _e179.gen_signals_for_symbol(sym, aid)
        if g is None or g.empty:
            continue
        fdf, feats = _e179.attach_features(g, sym, aid)
        fdf = fdf[fdf.index >= cutoff]
        if not fdf.empty:
            parts.append(fdf)
    if not parts:
        return pd.DataFrame(), []
    ds = pd.concat(parts).sort_index()
    feats = [f for f in _e177.make_feature_list(list(_e177.BULK_ALL.keys())) if f in ds.columns] \
            + ["sig_strategy_id", "sig_direction_long", "sig_risk_pct", "sig_asset_id"]
    feats = [f for f in feats if f in ds.columns]
    ds = ds[ds[feats].notna().all(axis=1)]
    return ds, feats


def _load_sent() -> set:
    if SENT_CACHE.exists():
        try:
            return set(json.loads(SENT_CACHE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_sent(s: set):
    SENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SENT_CACHE.write_text(json.dumps(list(s)[-5000:], ensure_ascii=False), encoding="utf-8")


def run_once(nets, scalers, model_feats, device):
    ds, feats = gen_recent_signals()
    if ds.empty:
        print(f"[{pd.Timestamp.utcnow()}] нет свежих сигналов", flush=True)
        return 0
    # выровнять фичи под модель
    use = [f for f in model_feats if f in ds.columns]
    if len(use) != len(model_feats):
        print(f"[warn] фич не хватает: {len(use)}/{len(model_feats)}", flush=True)
    scores = score_signals(ds, model_feats, nets, scalers, device)
    ds = ds.copy(); ds["score"] = scores
    ds["pred_grade"] = np.clip(np.round(scores), 1, 5).astype(int)

    sent = _load_sent()
    n_sent = 0
    for ts, row in ds.iterrows():
        grade = int(row["pred_grade"])
        if grade < MIN_GRADE:
            continue
        sid = int(row["sig_strategy_id"])
        direction = "LONG" if row["sig_direction_long"] == 1 else "SHORT"
        # ключ дедупа
        key = f"{SNAME.get(sid)}|{int(row.get('sig_asset_id',0))}|{direction}|{ts.isoformat()}"
        if key in sent:
            continue
        risk_pct = row["sig_risk_pct"]
        sig = {
            "strategy": SNAME.get(sid, str(sid)),
            "symbol": _e179.SYMBOLS[int(row.get("sig_asset_id", 0))],
            "direction": direction,
            "grade": grade, "score": float(row["score"]),
            "risk_pct": round(float(risk_pct), 2),
            "time": ts.strftime("%Y-%m-%d %H:%M"),
        }
        nb.broadcast_neural_signal(sig)
        sent.add(key); n_sent += 1
    _save_sent(sent)
    print(f"[{pd.Timestamp.utcnow()}] оценено {len(ds)}, отправлено {n_sent} (class>={MIN_GRADE})", flush=True)
    return n_sent


def run():
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    if not (MODEL_DIR / "meta.json").exists():
        print(f"[ERR] нет модели в {MODEL_DIR}. Сначала обучи etap_179."); return
    nets, scalers, model_feats, meta = load_model(device)
    print(f"[live] модель загружена: {meta['n_folds']} фолдов, {len(model_feats)} фич, "
          f"CV ρ={meta.get('cv_rho'):.3f}, device={device}", flush=True)
    print(f"[live] цикл каждые {INTERVAL_SEC}s, шлю class>={MIN_GRADE}", flush=True)
    # уведомить подписчиков, что нейро-инференс запущен (видно что живой)
    try:
        for u in nb.active_users():
            nb.send_message(u["chat_id"],
                f"🧠 Нейро-инференс запущен.\nМодель: {meta['n_folds']} фолдов, "
                f"{len(model_feats)} фич. Шлю сигналы класса ≥{MIN_GRADE} по BTC/ETH/SOL "
                f"(5 стратегий + фракталы Андрея). Проверка каждые {INTERVAL_SEC//60} мин.")
    except Exception as e:
        print(f"[live] startup notify failed: {e!r}", flush=True)
    while True:
        try:
            run_once(nets, scalers, model_feats, device)
        except Exception as e:
            print(f"[live] ошибка цикла: {e!r}", flush=True)
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    run()
