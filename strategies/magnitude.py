"""Стратегия «Магнитуда» — ML reversal-детектор для live.
① long на ЗАКРЫТЫХ 8h барах, ② short на ЗАКРЫТЫХ 12h барах. Persisted CatBoost (models/magnitude_*.cbm).
Сигнал: вход=close, стоп=свой low/high, TP=±3%, отбор = reversal-likelihood ≥ flag_thr И RR=3%/риск в RR-бакете.

Фичи (22) вендорены из канона research/reversal_cb/reversal_analysis.feats — должны совпадать (тест test_magnitude
сверяет с research-каноном, ловит дрейф). Спека: research/reversal_cb/MAGNITUDA_REPRODUCE.md.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
CONFIG_PATH = MODELS_DIR / "magnitude_config.json"

FEATS = ["c2l", "clv", "lwick", "body", "ret1", "ret3", "ret6", "dd20", "posrange20", "dist_ema20",
         "dist_ema50", "dist_ema100", "rsi", "consec_dn", "atr_pct", "atr_ptile", "range_exp",
         "vol_z", "vol_climax", "swept", "sweep_depth", "left_pivot"]

_CACHE: dict = {}


def _ema(x, span):
    return pd.Series(x).ewm(span=span, adjust=False).mean().values


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.clip(d, 0, None); dn = np.clip(-d, 0, None)
    ru = pd.Series(up).ewm(alpha=1 / n, adjust=False).mean().values
    rd = pd.Series(dn).ewm(alpha=1 / n, adjust=False).mean().values
    return 100 - 100 / (1 + ru / (rd + 1e-12))


def compute_feats(df: pd.DataFrame) -> pd.DataFrame:
    """22 фичи на закрытии бара (past-only). Вендор из reversal_analysis.feats — держать в синхроне (см. test_magnitude)."""
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    rng = (h - l).astype(float); rng[rng == 0] = np.nan
    pc = np.roll(c, 1); pc[0] = c[0]
    X = pd.DataFrame(index=df.index)
    X["clv"] = ((c - l) - (h - c)) / rng
    X["lwick"] = (np.minimum(o, c) - l) / rng
    X["body"] = np.abs(c - o) / rng
    X["c2l"] = (c - l) / c
    for k in (1, 3, 6):
        X[f"ret{k}"] = c / np.roll(c, k) - 1
    X["dd20"] = c / pd.Series(h).rolling(20).max().values - 1
    rmin = pd.Series(l).rolling(20).min().values; rmax = pd.Series(h).rolling(20).max().values
    X["posrange20"] = (c - rmin) / (rmax - rmin + 1e-12)
    X["dist_ema20"] = c / _ema(c, 20) - 1
    X["dist_ema50"] = c / _ema(c, 50) - 1
    X["dist_ema100"] = c / _ema(c, 100) - 1
    X["rsi"] = _rsi(c)
    dnc = (c < pc).astype(int)
    X["consec_dn"] = pd.Series(dnc).groupby((dnc != pd.Series(dnc).shift()).cumsum()).cumcount().values * dnc
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).rolling(14).mean().values
    X["atr_pct"] = atr / c
    X["atr_ptile"] = pd.Series(atr).rolling(100).rank(pct=True).values
    X["range_exp"] = rng / pd.Series(rng).rolling(20).mean().values
    X["vol_z"] = (v - pd.Series(v).rolling(96).mean().values) / (pd.Series(v).rolling(96).std().values + 1e-12)
    X["vol_climax"] = v / pd.Series(v).rolling(20).mean().values
    rmin5 = pd.Series(l).rolling(5).min().shift(1).values
    X["swept"] = (l < rmin5).astype(float)
    X["sweep_depth"] = np.clip((rmin5 - l) / c, 0, None)
    X["left_pivot"] = ((l <= np.roll(l, 1)) & (l <= np.roll(l, 2))).astype(float)
    return X.replace([np.inf, -np.inf], np.nan)


def _load():
    """ленивая загрузка config + моделей CatBoost (синглтон)."""
    if _CACHE:
        return _CACHE
    from catboost import CatBoostClassifier
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    models = {}
    for d, spec in cfg["directions"].items():
        m = CatBoostClassifier(); m.load_model(str(MODELS_DIR / spec["model"]))
        models[d] = m
    _CACHE.update(cfg=cfg, models=models)
    return _CACHE


def detect_magnitude_signals(df: pd.DataFrame, direction: str, n_recent: int = 3,
                             model=None, cfg=None) -> list[dict]:
    """Сигналы Магнитуды по ПОСЛЕДНИМ n_recent ЗАКРЫТЫМ барам df (TF соответствует направлению).
    df: OHLCV (open/high/low/close/volume), индекс — время (UTC), только закрытые бары.
    direction: 'long' (df=8h) или 'short' (df=12h). Возвращает list[dict]."""
    if direction not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")
    if df is None or len(df) < 110:          # нужно >=100 баров для rolling-окон
        return []
    if model is None or cfg is None:
        st = _load(); cfg = cfg or st["cfg"]; model = model or st["models"][direction]
    spec = cfg["directions"][direction]
    THR = cfg["THR"]; rlo, rhi = spec["rr"]; flag_thr = spec["flag_thr"]
    X = compute_feats(df)
    c = df["close"].values; h = df["high"].values; lo = df["low"].values
    out = []
    n = len(df)
    for i in range(max(0, n - n_recent), n):
        row = X[FEATS].iloc[i]
        if row.isna().any():
            continue
        p = float(model.predict_proba(row.values.reshape(1, -1))[0, 1])
        if p < flag_thr:
            continue
        entry = float(c[i])
        if direction == "long":
            stop = float(lo[i]); tgt = entry * (1 + THR); risk = (entry - stop) / entry
        else:
            stop = float(h[i]); tgt = entry * (1 - THR); risk = (stop - entry) / entry
        if risk <= 1e-5:
            continue
        rr = THR / risk
        if not (rlo <= rr < rhi):
            continue
        out.append({
            "signal_time": pd.Timestamp(df.index[i]),
            "direction": "LONG" if direction == "long" else "SHORT",
            "tf": spec["tf"],
            "entry": round(entry, 2),
            "sl": round(stop, 2),
            "tp": round(tgt, 2),
            "rr": round(float(rr), 2),
            "p": round(p, 3),
            "confirm_type": f"Magnitude reversal {spec['tf']} (p={p:.2f}, RR={rr:.1f})",
        })
    return out
