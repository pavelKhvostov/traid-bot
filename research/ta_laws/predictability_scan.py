"""СКАН ПРЕДСКАЗУЕМОСТИ — какие свойства рынка персистентны (=предсказуемы), кроме магнитуды?

Принцип: направление = монетка (автокорр ~0, рынок эффективен). Предсказуемо то, что ПЕРСИСТЕНТНО.
Магнитуда (вола) — такой пример. Сканируем другие свойства: меряем персистентность (текущее окно -> следующее,
НЕпересекающиеся окна) = Spearman(v[i], v[i+1]), против shuffle. Высокая персистентность + бьёт shuffle = кандидат
в «тонкий инструмент» ортогональный направлению.

Окно W=8 12h-баров (4 дня), step=W (нет автокорр-инфляции), BTC+ETH+SOL пулом.
Свойства: direction(ret), |ret|, realized-vol, range, trendiness(efficiency ratio), volume, trades,
downside-semivol(скос), + кросс-актив корреляция (BTC-ETH/BTC-SOL/ETH-SOL).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/predictability_scan.py
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
DATA = ROOT / "research" / "elements_study" / "data"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
W = 8


def spearman(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 30:
        return np.nan
    ra = pd.Series(a[m]).rank().values; rb = pd.Series(b[m]).rank().values
    if np.std(ra) == 0 or np.std(rb) == 0:
        return np.nan
    return float(np.corrcoef(ra, rb)[0, 1])


def load(sym):
    df = pd.read_csv(DATA / f"{sym}_12h_flow.csv")
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df.sort_values("open_time").reset_index(drop=True)


def window_props(df):
    """Свойства по непересекающимся окнам W. Возвращает dict свойство->массив значений по окнам."""
    O, H, L, C, V = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    NT = df["trades"].values.astype(float)
    lr = np.zeros(len(C)); lr[1:] = np.log(C[1:] / np.clip(C[:-1], 1e-9, None))
    props = {k: [] for k in ["ret", "absret", "rvol", "range", "trend", "vol", "trades", "dnsemi"]}
    for s in range(W, len(C) - W, W):
        seg = slice(s, s + W)
        bars = lr[s + 1:s + W]
        net = (C[s + W - 1] - C[s]) / C[s]
        props["ret"].append(net)
        props["absret"].append(abs(net))
        props["rvol"].append(np.std(bars) if len(bars) else np.nan)
        props["range"].append((H[seg].max() - L[seg].min()) / C[s])
        sa = np.sum(np.abs(bars))
        props["trend"].append(abs(np.sum(bars)) / sa if sa > 0 else np.nan)   # efficiency ratio
        props["vol"].append(V[seg].mean())
        props["trades"].append(NT[seg].mean())
        neg = bars[bars < 0]
        props["dnsemi"].append((np.std(neg) if len(neg) > 1 else 0.0))
    return {k: np.array(v) for k, v in props.items()}, df["open_time"].values[W:len(C) - W:W]


def persistence(vals):
    """Spearman(v[i], v[i+1]) + shuffle."""
    v = np.asarray(vals, float)
    real = spearman(v[:-1], v[1:])
    rng = np.random.default_rng(3)
    sh = np.nanmean([spearman(v[:-1], rng.permutation(v[1:])) for _ in range(30)])
    return real, sh


def main():
    # пер-символьные свойства
    PS = {}; TS = {}
    for s in SYMBOLS:
        PS[s], TS[s] = window_props(load(s))

    out = []; A = out.append
    A(f"СКАН ПРЕДСКАЗУЕМОСТИ свойств рынка (персистентность окно->окно, W={W} 12h-баров=4дня, непересек., BTC+ETH+SOL пул)")
    A("Высокая персистентность (Spearman) >> shuffle = свойство предсказуемо (кандидат в инструмент).\n")
    A(f"{'свойство':28} {'персист.':>9} {'shuffle':>9} {'предсказуемо?':>14}")

    LABELS = [("ret", "НАПРАВЛЕНИЕ (знак хода)"), ("absret", "|ход| (направл. магнитуда)"),
              ("rvol", "realized-vol (магнитуда)"), ("range", "range (магнитуда)"),
              ("trend", "трендовость (eff.ratio)"), ("vol", "объём/активность"),
              ("trades", "число сделок"), ("dnsemi", "downside-semivol (скос)")]
    results = {}
    for key, lbl in LABELS:
        pooled = np.concatenate([PS[s][key] for s in SYMBOLS])
        # персистентность считаем ПО символу (не смешивая стыки), потом усредняем
        reals, shs = [], []
        for s in SYMBOLS:
            r, sh = persistence(PS[s][key])
            if np.isfinite(r):
                reals.append(r); shs.append(sh)
        real = np.mean(reals); sh = np.mean(shs)
        results[key] = real
        verdict = "ДА" if (real > 0.20 and real > sh + 0.10) else ("слабо" if real > 0.10 else "нет(монетка)")
        A(f"{lbl:28} {real:>+9.3f} {sh:>+9.3f} {verdict:>14}")

    # кросс-актив корреляция: режим со-движения
    A("\n=== КРОСС-АКТИВ КОРРЕЛЯЦИЯ (режим со-движения, персистентна?) ===")
    # выравниваем по времени, считаем corr доходностей в окне, затем персистентность серии corr
    closes = {}
    for s in SYMBOLS:
        d = load(s).set_index("open_time")["close"]
        closes[s] = d
    aligned = pd.DataFrame(closes).dropna()
    lr = np.log(aligned / aligned.shift(1)).dropna()
    pairs = [("BTCUSDT", "ETHUSDT"), ("BTCUSDT", "SOLUSDT"), ("ETHUSDT", "SOLUSDT")]
    corr_persist = []
    for a, b in pairs:
        cs = []
        arr_a = lr[a].values; arr_b = lr[b].values
        for s in range(0, len(arr_a) - W, W):
            ca = arr_a[s:s + W]; cb = arr_b[s:s + W]
            if np.std(ca) > 0 and np.std(cb) > 0:
                cs.append(np.corrcoef(ca, cb)[0, 1])
            else:
                cs.append(np.nan)
        cs = np.array(cs)
        r, sh = persistence(cs)
        corr_persist.append(r)
        A(f"  {a[:3]}-{b[:3]}: персист.corr {r:+.3f} (shuffle {sh:+.3f}), средн.corr {np.nanmean(cs):+.2f}")
    A(f"  -> корреляция-режим персистентен: {np.nanmean(corr_persist):+.3f}")

    # ранжирование
    A("\n=== РАНГ предсказуемости (кроме направления) ===")
    rank = sorted([(k, v) for k, v in results.items() if k != "ret"], key=lambda x: -x[1])
    for k, v in rank:
        A(f"  {dict(LABELS)[k]:28} {v:+.3f}")
    A(f"  кросс-актив корреляция (средн.)   {np.nanmean(corr_persist):+.3f}")
    A(f"\n  НАПРАВЛЕНИЕ для сравнения: {results['ret']:+.3f}  <- ~0 = монетка (стена подтверждается)")

    A("\n=== ВЫВОД: что ещё подобное магнитуде (предсказуемо + ортогонально направлению) ===")
    A("  Предсказуемы (персистентны) свойства, НЕ являющиеся стороной. Кандидаты-инструменты:")
    A("   1. МАГНИТУДА/вола (есть) — фильтр режима, сайзер каскадов.")
    A("   2. АКТИВНОСТЬ (объём/сделки) — если персистентна: фильтр ликвидности/участия, тайминг.")
    A("   3. ТРЕНДОВОСТЬ (eff.ratio) — если персистентна: ВЫБОР СТРАТЕГИИ (тренд->континуация/каскад,")
    A("      пила->фейд/мин-реверсия). Самый ценный ортогональный к направлению рычаг.")
    A("   4. КОРРЕЛЯЦИЯ-режим — тайминг диверсификации корзины (высокая corr -> риск-офф, не диверсифицирует).")
    A("   5. ВОЛА-СКОС (downside) — асимметрия риска, калибровка стопов.")
    A("  Решает не угадывание стороны, а МЕТА-СЛОЙ: размер/характер/со-движение -> какую стратегию и каким сайзом.")

    rep = Path(__file__).resolve().parent / "predictability_scan_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
