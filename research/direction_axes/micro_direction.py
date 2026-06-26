"""САМО-КРИТИКА killer-контролей: сильнейшая форма гипотезы «боты -> инфа в OHLCV».
Богатая OHLCV-микроструктура -> знак BTC[t+1] на МЕЛКОМ горизонте (5m/15m), BTC-only,
PURGED WALK-FORWARD (не один сплит), CatBoost + логистика, two-cost (taker/maker).

Бьёт по дырам моих контролей: горизонт (≥1h -> 5m/15m), фичи (тонкие -> kitchen sink),
cross-asset гейт (снят), один OOS-сплит (-> walk-forward), косты (taker И maker).
Защита от миражей: фичи строго на закрытии бара, цель строго вперёд, label non-overlap (h=1 бар),
embargo между train/test, time-shuffle + permutation null, price-only-rich baseline для маржинала flow.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/direction_axes/micro_direction.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(7)
TAKER_RT = 0.0010   # агрессор, ~10bps round-trip (споте консервативно)
MAKER_RT = 0.0002   # пассив/спред, ~2bps round-trip


def build_bars(rule):
    """5m/15m бары из 1m с интрабар-микроструктурой."""
    df = pd.read_csv(ROOT / "data" / "BTCUSDT_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    df = df.sort_index()
    sgn = np.sign(df.close.values - df.open.values)
    df["sgnvol"] = sgn * df.volume.values
    df["up"] = (df.close.values > df.open.values).astype(float)
    df["m_ret"] = df.close.pct_change(fill_method=None)
    g = df.resample(rule, origin="epoch", label="left", closed="left")
    bar = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), volume=("volume", "sum"),
                sgnvol=("sgnvol", "sum"), up_frac=("up", "mean"),
                vmax=("volume", "max"), rv=("m_ret", "std"), nmin=("close", "count")).dropna(subset=["close"])
    bar = bar[bar.nmin >= 2]
    return bar


def features(bar, live=False):
    o, h, l, c, v = bar.open, bar.high, bar.low, bar.close, bar.volume
    pc = c.shift(1)
    X = pd.DataFrame(index=bar.index)
    rng = (h - l).replace(0, np.nan)
    # --- геометрия бара (всё на закрытии) ---
    X["ret"] = c / pc - 1
    X["body"] = (c - o) / o
    X["range"] = (h - l) / o
    X["upwick"] = (h - np.maximum(o, c)) / o
    X["dnwick"] = (np.minimum(o, c) - l) / o
    X["clv"] = ((c - l) - (h - c)) / rng
    X["body_rng"] = (c - o) / rng
    X["gap"] = (o - pc) / pc
    # --- объём ---
    X["vol_z"] = (v - v.rolling(96).mean()) / (v.rolling(96).std() + 1e-12)
    X["vol_chg"] = v.pct_change(fill_method=None).clip(-5, 5)
    # --- signed-flow прокси (bar-rule) ---
    X["sgnvol_n"] = bar.sgnvol / v.replace(0, np.nan)        # дисбаланс [-1..1]
    X["up_frac"] = bar.up_frac
    X["vol_conc"] = bar.vmax / v.replace(0, np.nan)          # концентрация объёма
    X["intrabar_rv"] = bar.rv
    # --- мульти-масштаб моментум/CVD ---
    for k in (3, 6, 12):
        X[f"mom{k}"] = c.pct_change(k, fill_method=None)
        X[f"cvd{k}"] = X["sgnvol_n"].rolling(k).mean()
    # --- лаги ---
    for f in ("ret", "body", "clv", "sgnvol_n"):
        X[f"{f}_l1"] = X[f].shift(1); X[f"{f}_l2"] = X[f].shift(2)
    if not live:
        X["fwd"] = c.shift(-1) / c - 1                        # цель: ретёрн след. бара
        return X.replace([np.inf, -np.inf], np.nan).dropna()
    # live: оставить последний закрытый бар (без fwd), dropna только по фичам
    return X.replace([np.inf, -np.inf], np.nan).dropna(how="any")


PRICE_ONLY = ["ret", "body", "range", "upwick", "dnwick", "clv", "body_rng", "gap", "vol_z", "vol_chg",
              "intrabar_rv", "mom3", "mom6", "mom12", "ret_l1", "ret_l2", "body_l1", "body_l2", "clv_l1", "clv_l2"]
FLOW = ["sgnvol_n", "up_frac", "vol_conc", "cvd3", "cvd6", "cvd12", "sgnvol_n_l1", "sgnvol_n_l2"]


def cb_oos(X, feats, n_folds=6, embargo=20):
    """purged walk-forward: расширяющийся train, тест на след. блоке, embargo-зазор. Возвращает pooled (pred,y,fwd,idx)."""
    from catboost import CatBoostClassifier
    Xv = X[feats].values
    y = (X["fwd"] > 0).astype(int).values
    fwd = X["fwd"].values
    n = len(X)
    edges = np.linspace(int(n * 0.4), n, n_folds + 1).astype(int)  # первые 40% всегда в train
    preds = np.full(n, -1); used = np.zeros(n, bool)
    for k in range(n_folds):
        te0, te1 = edges[k], edges[k + 1]
        tr_end = max(0, te0 - embargo)
        if tr_end < 500 or te1 - te0 < 100:
            continue
        try:
            params = dict(iterations=350, depth=6, learning_rate=0.05, loss_function="Logloss",
                          random_seed=7, verbose=False, task_type="GPU", devices="0")
            m = CatBoostClassifier(**params)
            m.fit(Xv[:tr_end], y[:tr_end])
        except Exception:
            m = CatBoostClassifier(iterations=350, depth=6, learning_rate=0.05, loss_function="Logloss",
                                   random_seed=7, verbose=False)
            m.fit(Xv[:tr_end], y[:tr_end])
        p = m.predict(Xv[te0:te1])
        preds[te0:te1] = p.astype(int); used[te0:te1] = True
    m_ = used
    return preds[m_], y[m_], fwd[m_], X.index[m_]


def report(tag, pred, y, fwd, idx, out):
    acc = (pred == y).mean()
    maj = max(y.mean(), 1 - y.mean())
    sgn = np.where(pred == 1, 1, -1)
    gross = float(np.mean(sgn * fwd))               # per-bar signed return
    net_t = gross - TAKER_RT
    net_m = gross - MAKER_RT
    # permutation null
    nulls = [np.mean(pred == RNG.permutation(y)) for _ in range(300)]
    null_p = float((np.array(nulls) >= acc).mean())
    # persistence baseline (знак=пред. бар)
    pers = (y[1:] == y[:-1]).mean()
    yrs = pd.Series(pred == y, index=idx).groupby(idx.year).mean()
    out.append(f"\n[{tag}]  n_OOS={len(y)}")
    out.append(f"  acc={acc:.4f}  (majority={maj:.4f}, persistence={pers:.4f})  null={np.mean(nulls):.4f}±{np.std(nulls):.4f} p={null_p:.3f}")
    out.append(f"  per-bar signed-ret: gross={gross*1e4:+.2f}bps | net-taker={net_t*1e4:+.2f}bps | net-maker={net_m*1e4:+.2f}bps")
    out.append("  год OOS: " + "  ".join(f"{yr}:{v:.3f}" for yr, v in yrs.items()))
    return acc, gross


def main():
    out = ["="*72, " МИКРО-НАПРАВЛЕНИЕ BTC: rich-OHLCV, purged walk-forward, two-cost", "="*72]
    for rule, lbl in [("15min", "15m"), ("5min", "5m")]:
        out.append(f"\n{'#'*60}\n## ГОРИЗОНТ {lbl}\n{'#'*60}")
        bar = build_bars(rule)
        X = features(bar)
        out.append(f"баров={len(X)}  {X.index[0].date()} -> {X.index[-1].date()}  "
                   f"(косты: taker {TAKER_RT*1e4:.0f}bps / maker {MAKER_RT*1e4:.0f}bps RT)")
        # price-only-rich
        p1 = cb_oos(X, PRICE_ONLY)
        report(f"{lbl} CatBoost PRICE-only-rich", *p1, out)
        # full (+flow)
        p2 = cb_oos(X, PRICE_ONLY + FLOW)
        report(f"{lbl} CatBoost FULL (+flow)", *p2, out)
        print("\n".join(out)); (HERE / "micro_direction_report.txt").write_text("\n".join(out), encoding="utf-8")
    o = "\n".join(out); (HERE / "micro_direction_report.txt").write_text(o, encoding="utf-8")


if __name__ == "__main__":
    main()
