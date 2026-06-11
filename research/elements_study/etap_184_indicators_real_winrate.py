"""etap_184: ПРАВИЛЬНЫЙ winrate стратегий с ИНДИКАТОРАМИ (4-indicator score + фильтры).

ИСПРАВЛЕНИЕ ошибки: раньше (etap_179/183) считал WR на ГОЛЫХ зонах без индикаторов →
заниженный WR (1.1.1 = 35% вместо реальных 51.6%). Теперь добавляю к каждому сигналу
4-индикаторный momentum score (Hull + Money Hands + RSI + ASVK) на момент входа и
фильтрую по нему — как в реальной стратегии с floating TP.

Реальные WR из vault: 1.1.1 = 51.6% (BTC), 1.1.4+EMA = 67.3%, Vadim = 53.6%.

Что делаю:
1. Беру готовый датасет сигналов (etap182_graded_2017, с реальным исходом TP/SL).
2. Для каждого сигнала считаю 4-indicator score на 1h на момент signal_time.
3. Фильтрую: сигнал ПО направлению score (LONG при score>0, SHORT при score<0) —
   это и есть индикаторное подтверждение, дающее +6-10pp WR.
4. Пересчитываю WR/R по годам ДЛЯ КАЖДОЙ стратегии С фильтром и БЕЗ.
5. Сравниваю с нейросетью.

Индикаторы: smc-lib/indicators/ (trend_line_asvk, money_hands_asvk, rsi_asvk).

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/etap_184_indicators_real_winrate.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
_sys.path.insert(0, str(_ROOT / "smc-lib"))

import numpy as np
import pandas as pd

from data_manager import load_df
from indicators.trend_line_asvk import trend_line_asvk
from indicators.money_hands_asvk import money_hands
from indicators.rsi_asvk import adjusted_rsi, rsi_wilder

OUT_DIR = _ROOT / "research" / "elements_study" / "output"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
SNAME = {0: "1.1.1", 1: "1.1.2", 2: "1.1.3", 3: "FRACTAL", 4: "1.1.4"}


def compute_score_series(sym):
    """4-indicator momentum score на 1h для всей истории актива.

    score = mean(s_hull, s_mh, s_rsi, s_asvk) ∈ [-1,1] (формула из vault).
    Возвращает Series score, индексированный по 1h open_time.
    """
    df = load_df(sym, "1h").sort_index()
    closes = df["close"].tolist()
    n = len(df)

    # Hull (length=49, mult=1.6 → 78)
    hull = trend_line_asvk(closes, length=49, length_mult=1.6, mode="Hma")
    s_hull = np.array([1.0 if c == "up" else (-1.0 if c == "down" else 0.0) for c in hull["color"]])

    # Money Hands bw2
    bars = list(zip(df["open"], df["high"], df["low"], df["close"], df["volume"]))
    mh = money_hands(bars)
    mh_map = {"green": 1.0, "white_weak_bull": 0.5, "neutral": 0.0, "white_weak_bear": -0.5, "red": -1.0}
    s_mh = np.array([mh_map.get(c, 0.0) for c in mh["color"]])

    # RSI Wilder (None в разогреве → 50 нейтраль)
    rsi = np.array([float(x) if x is not None else 50.0 for x in rsi_wilder(closes, 14)])
    s_rsi = np.clip((rsi - 50) / 50, -1, 1)

    # ASVK custom RSI zone (None → нейтраль)
    asvk = adjusted_rsi(closes, 14)
    def _arr(lst): return np.array([float(x) if x is not None else np.nan for x in lst])
    ema3 = _arr(asvk["ema_3"]); above = _arr(asvk["above"]); below = _arr(asvk["below"])
    # zone: red (ema3>above)=+1 continuation, green (ema3<below)=-1 reversal; nan→0
    s_asvk = np.where(np.isnan(ema3) | np.isnan(above) | np.isnan(below), 0.0,
                      np.where(ema3 > above, 1.0, np.where(ema3 < below, -1.0, 0.0)))

    # выровнять длины (некоторые индикаторы возвращают со сдвигом/nan в начале)
    L = min(len(s_hull), len(s_mh), len(s_rsi), len(s_asvk), n)
    score = (s_hull[:L] + s_mh[:L] + s_rsi[:L] + s_asvk[:L]) / 4.0
    return pd.Series(score, index=df.index[:L])


def main():
    print("[etap_184] правильный WR с 4-индикаторным score", flush=True)

    # score-серии по активам
    print("[score] считаю 4-indicator score по 1h для BTC/ETH/SOL...", flush=True)
    score_by_sym = {}
    for sym in SYMBOLS:
        score_by_sym[sym] = compute_score_series(sym)
        print(f"  {sym}: score готов ({len(score_by_sym[sym])} баров)", flush=True)

    # датасет сигналов с реальным исходом
    ds = pd.read_csv(OUT_DIR / "etap182_graded_2017.csv", index_col="signal_time", parse_dates=["signal_time"])
    ds["год"] = ds.index.year

    # для каждого сигнала: score на момент signal_time (последний закрытый 1h)
    print("[match] сопоставляю score каждому сигналу...", flush=True)
    scores = []
    for ts, row in ds.iterrows():
        sym = SYMBOLS[int(row["sig_asset_id"])]
        ss = score_by_sym[sym]
        # последний 1h бар <= signal_time
        pos = ss.index.searchsorted(ts, side="right") - 1
        scores.append(ss.iloc[pos] if pos >= 0 else 0.0)
    ds["score"] = scores
    ds["long"] = ds["sig_direction_long"] == 1
    # индикаторное подтверждение: score согласен с направлением сигнала
    ds["ind_confirm"] = np.where(ds["long"], ds["score"] > 0, ds["score"] < 0)
    ds["ind_strong"] = np.where(ds["long"], ds["score"] >= 0.25, ds["score"] <= -0.25)

    def trade_R(g, ar):
        if g >= 4: return 2.2
        if g == 1: return -1.0
        return min(ar, 2.0) if ar > 0 else -1.0
    ds["R"] = [trade_R(g, ar) for g, ar in zip(ds["реальный_grade" if "реальный_grade" in ds else "grade"], ds["achieved_r"])]
    grade_col = "реальный_grade" if "реальный_grade" in ds.columns else "grade"

    def stats(sub):
        if len(sub) == 0: return "—"
        wr = (sub[grade_col] >= 4).mean() * 100
        return f"{sub['R'].sum():+.0f}R/{wr:.0f}%/{len(sub)}"

    print("\n========== WR СТРАТЕГИЙ: голые зоны vs + индикаторный фильтр ==========", flush=True)
    print(f"{'стратегия':<12}{'БЕЗ индикаторов':<24}{'+ score-подтверждение':<26}{'+ сильный score(±0.25)'}", flush=True)
    for sid in [0, 1, 2, 3, 4]:
        s = SNAME[sid]
        sub = ds[ds["sig_strategy_id"] == sid]
        conf = sub[sub["ind_confirm"]]
        strong = sub[sub["ind_strong"]]
        print(f"  {s:<10}{stats(sub):<24}{stats(conf):<26}{stats(strong)}", flush=True)
    allc = ds[ds["ind_confirm"]]; alls = ds[ds["ind_strong"]]
    print(f"  {'ВСЕ':<10}{stats(ds):<24}{stats(allc):<26}{stats(alls)}", flush=True)

    print("\n========== ПО ГОДАМ: + индикаторное подтверждение (score-direction) ==========", flush=True)
    print(f"{'год':<7}{'все(без инд)':<18}{'+score conf':<18}{'WR без→с инд'}", flush=True)
    for y in sorted(ds["год"].unique()):
        yd = ds[ds["год"] == y]
        if len(yd) < 10: continue
        conf = yd[yd["ind_confirm"]]
        awr = (yd[grade_col] >= 4).mean() * 100
        cwr = (conf[grade_col] >= 4).mean() * 100 if len(conf) else 0
        print(f"{y:<7}{stats(yd):<18}{stats(conf):<18}{awr:.0f}% → {cwr:.0f}%", flush=True)

    # сравнение с нейросетью (из витрины etap_183, если score там есть — переджойним)
    show = pd.read_csv(OUT_DIR / "etap183_signal_showcase.csv")
    show["время"] = pd.to_datetime(show["время"])
    print("\n========== СВОДКА: что лучше фильтрует ==========", flush=True)
    base_wr = (ds[grade_col] >= 4).mean() * 100
    ind_wr = (allc[grade_col] >= 4).mean() * 100
    strong_wr = (alls[grade_col] >= 4).mean() * 100
    print(f"  Без фильтра:           WR {base_wr:.0f}% ({len(ds)} сделок, {ds['R'].sum():+.0f}R)", flush=True)
    print(f"  4-indicator score>0:   WR {ind_wr:.0f}% ({len(allc)} сделок, {allc['R'].sum():+.0f}R)", flush=True)
    print(f"  4-indicator score±0.25: WR {strong_wr:.0f}% ({len(alls)} сделок, {alls['R'].sum():+.0f}R)", flush=True)
    nn = show[show["NN_оценка"] >= 4]
    nn_wr = (nn["реальный_grade"] >= 4).mean() * 100
    print(f"  Нейросеть >=4:         WR {nn_wr:.0f}% ({len(nn)} сделок)", flush=True)

    ds.to_csv(OUT_DIR / "etap184_signals_with_score.csv")
    print(f"\n[saved] сигналы со score → etap184_signals_with_score.csv", flush=True)


if __name__ == "__main__":
    main()
