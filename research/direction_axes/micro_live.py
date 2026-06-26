"""LIVE калиброванный микро-bias (15m next-bar) для аналитики — заменяет ручное «вероятное направление».
Обучает финальную CatBoost на всей истории, калибрует уверенность -> реальный hit-rate (из walk-forward OOS),
дотягивает свежие 1m с Binance, выдаёт текущее чтение BTC: P(up 15m) + перцентиль уверенности + ист.надёжность.
ВАЖНО: горизонт = СЛЕДУЮЩИЙ 15m бар. Это tape-bias, НЕ свинг и НЕ торговый сигнал (edge ≤ costs).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/direction_axes/micro_live.py
"""
from __future__ import annotations
import sys, json, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from micro_direction import build_bars, features, PRICE_ONLY, FLOW  # noqa: E402
from micro_threshold import cb_oos_proba  # noqa: E402
HERE = Path(__file__).resolve().parent
FEATS = PRICE_ONLY + FLOW


def fetch_1m(sym="BTCUSDT", need=2600):
    """последние ~need 1m свечей с Binance spot (для построения текущего 15m бара + rolling-окон)."""
    out = []; end = ""
    while len(out) < need:
        u = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1m&limit=1000"
        if end:
            u += f"&endTime={end}"
        r = json.load(urllib.request.urlopen(u, timeout=20))
        if not r:
            break
        out = r + out
        end = r[0][0] - 1
        if len(r) < 1000:
            break
    rows = [(pd.to_datetime(k[0], unit="ms", utc=True), float(k[1]), float(k[2]), float(k[3]),
             float(k[4]), float(k[5])) for k in out]
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"]).set_index("open_time")
    return df[~df.index.duplicated(keep="last")].sort_index()


def build_15m_from_1m(df):
    sgn = np.sign(df.close.values - df.open.values)
    df = df.copy()
    df["sgnvol"] = sgn * df.volume.values
    df["up"] = (df.close.values > df.open.values).astype(float)
    df["m_ret"] = df.close.pct_change(fill_method=None)
    g = df.resample("15min", origin="epoch", label="left", closed="left")
    bar = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), volume=("volume", "sum"),
                sgnvol=("sgnvol", "sum"), up_frac=("up", "mean"),
                vmax=("volume", "max"), rv=("m_ret", "std"), nmin=("close", "count")).dropna(subset=["close"])
    return bar


def main():
    from catboost import CatBoostClassifier
    out = ["="*64, " LIVE МИКРО-BIAS BTC (15m next-bar, калиброванный)", "="*64]

    # 1) история -> калибровка (walk-forward OOS) + финальная модель
    Xh = features(build_bars("15min"))
    proba_oos, y_oos, fwd_oos = cb_oos_proba(Xh, FEATS)
    pred_oos = (proba_oos > 0.5).astype(int)
    conv_h = np.abs(proba_oos - 0.5)
    correct_h = (pred_oos == y_oos).astype(float)
    dir_h = np.where(pred_oos == 1, 1, -1)
    out.append(f"калибровка на {len(y_oos)} OOS-барах (walk-forward); общий acc={correct_h.mean():.4f}")

    Xv = Xh[FEATS].values; yv = (Xh["fwd"] > 0).astype(int).values
    try:
        fm = CatBoostClassifier(iterations=400, depth=6, learning_rate=0.05, loss_function="Logloss",
                                random_seed=7, verbose=False, task_type="GPU", devices="0")
        fm.fit(Xv, yv)
    except Exception:
        fm = CatBoostClassifier(iterations=400, depth=6, learning_rate=0.05, loss_function="Logloss",
                                random_seed=7, verbose=False); fm.fit(Xv, yv)

    # 2) live-фичи: свежие 1m -> 15m -> последний ЗАКРЫТЫЙ бар
    d1 = fetch_1m()
    bar = build_15m_from_1m(d1)
    # отбросить незакрытый последний бар (nmin<15), взять последний полный
    closed = bar[bar.nmin >= 15]
    Xl = features(closed, live=True)
    last = Xl.iloc[[-1]]
    t_bar = last.index[-1]
    p_up = float(fm.predict_proba(last[FEATS].values)[0, 1])
    c = abs(p_up - 0.5)
    direction = "ВВЕРХ" if p_up > 0.5 else "ВНИЗ"

    # 3) калибровка текущей уверенности
    pct = float((conv_h <= c).mean() * 100)                 # перцентиль уверенности
    mask = conv_h >= c
    n_bucket = int(mask.sum())
    hit = float(correct_h[mask].mean()) if n_bucket >= 30 else float("nan")
    # ист. средний ход в направлении прогноза при conv>=c (gross, информационно)
    same = mask & (dir_h == (1 if p_up > 0.5 else -1))
    gross_bps = float(np.mean(dir_h[same] * fwd_oos[same]) * 1e4) if same.sum() >= 30 else float("nan")
    last_close = float(closed.close.iloc[-1])

    out.append(f"\nпоследний закрытый 15m бар: {t_bar:%Y-%m-%d %H:%M} UTC  close={last_close:.0f}")
    out.append(f"P(up next 15m) = {p_up:.3f}   ->  lean {direction}")
    out.append(f"уверенность |p-0.5| = {c:.3f}  (перцентиль {pct:.1f}% ист. распределения)")
    out.append(f"ИСТ. НАДЁЖНОСТЬ этого уровня (conv>={c:.3f}, n={n_bucket}): hit-rate = {hit:.3f}")
    out.append(f"ист. средний ход в сторону прогноза (gross, до костов): {gross_bps:+.2f} bps / 15m")
    # честная интерпретация
    if pct < 75:
        verdict = "НИЗКАЯ уверенность -> аналитике показывать как 'нет края / ~монетка'."
    elif hit >= 0.58:
        verdict = "ВЫСОКАЯ уверенность -> честный 15m micro-lean (НЕ торговый сигнал: edge ≤ costs)."
    else:
        verdict = "Умеренная уверенность -> слабый контекст, не выделять."
    out.append(f"ВЕРДИКТ: {verdict}")

    # сохранить компактный JSON для интеграции в аналитику
    sig = dict(bar_time=str(t_bar), close=last_close, p_up=round(p_up, 4), conviction=round(c, 4),
               conv_pct=round(pct, 1), hit_rate=None if np.isnan(hit) else round(hit, 4),
               n_bucket=n_bucket, gross_bps=None if np.isnan(gross_bps) else round(gross_bps, 2),
               direction=direction)
    (HERE / "micro_live_signal.json").write_text(json.dumps(sig, ensure_ascii=False, indent=2), encoding="utf-8")
    o = "\n".join(out); (HERE / "micro_live_report.txt").write_text(o, encoding="utf-8"); print(o)


if __name__ == "__main__":
    main()
