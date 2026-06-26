"""ТЕСТ «ВОЛНЫ»: если цена начала движение — это начало ридабельной волны (континуация) или ловушка?

Идея юзера: не угадывать направление заранее, а дать волне ПРОЯВИТЬ направление (импульс) и поехать с ней,
используя магнитуду (режим экспансии) как «будет большой ход». Проверяем на данных, отделяя:
  • геометрию (gambler's ruin, EV-нейтрально) от
  • реального МОМЕНТУМА (континуация сверх 50%/сверх random).

Сетап: на close 12h-свечи, если импульс за W баров >= TRIG% (волна вверх) или <= -TRIG% (вниз) -> вход В СТОРОНУ
импульса по close[i] (каузально). Исход: first-passage ±M% от входа по 1h-пути (строго после close).
continuation = дошли до барьера ПО НАПРАВЛЕНИЮ импульса первым. net-R: RR1, symmetric ±M, кост учтён.
Управление со СЛЕДУЮЩЕГО 1h-бара (нет entry-bar lookahead).

Ключевые проверки (наши стены):
  • continuation vs 50% (геом-нуль) и vs RANDOM-входа того же числа (фильтр обязан бить random);
  • РАСКОЛ long/short (асимметрия = бычий дрейф, не закон);
  • РАСКОЛ по вола-режиму (экспансия vs тихо) — спасает ли экспансия континуацию? (синтез магнитуда+направление);
  • cross-asset BTC/ETH/SOL.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/wave_continuation.py
"""
from __future__ import annotations
import sys, os
from pathlib import Path
import numpy as np
import pandas as pd
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DATA = ROOT / "research" / "elements_study" / "data"
W = int(os.environ.get("WV_W", 2))          # окно импульса (12h-баров) ~1 день
TRIG = float(os.environ.get("WV_TRIG", 2.0))  # порог импульса %
M = float(os.environ.get("WV_M", 4.0))      # барьер от входа % (RR1, symmetric)
HORIZON_H = 24 * 20                          # 20 дней на резолв
COST_RT = 0.0014


def load_flow(sym, tf):
    df = pd.read_csv(DATA / f"{sym}_{tf}_flow.csv")
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df.sort_values("open_time").reset_index(drop=True)


def first_passage(h1H, h1L, s, e, up, dn):
    """1 = up-барьер первым, 0 = dn-барьер первым, None = ни один."""
    uh = np.nonzero(h1H[s:e] >= up)[0]; dh = np.nonzero(h1L[s:e] <= dn)[0]
    iu = uh[0] if uh.size else 10**9; idd = dh[0] if dh.size else 10**9
    if iu == 10**9 and idd == 10**9:
        return None
    return 1 if iu < idd else 0


def build(sym):
    h = load_flow(sym, "12h"); o = load_flow(sym, "1h")
    C = h["close"].values.astype(float); Hi = h["high"].values; Lo = h["low"].values
    n = len(h)
    atr = G.compute_atr(pd.DataFrame({"high": Hi, "low": Lo, "close": C}))
    atr_pct = np.where(C > 0, atr / C * 100, np.nan)
    atr_pctile = pd.Series(atr_pct).rolling(200, min_periods=30).apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    t1 = o["open_time"].values.astype("datetime64[ns]").astype(np.int64)
    h1H = o["high"].values.astype(float); h1L = o["low"].values.astype(float)
    close_t = (h["open_time"] + pd.Timedelta(hours=12)).values.astype("datetime64[ns]").astype(np.int64)
    si = np.searchsorted(t1, close_t, side="left")
    rng = np.random.default_rng(hash(sym) % 2**32)
    rows = []
    for i in range(W + 60, n - 1):
        P = C[i]
        if not np.isfinite(P) or P <= 0 or not np.isfinite(atr_pctile[i]):
            continue
        imp = (C[i] - C[i - W]) / C[i - W] * 100
        s = int(si[i]); e = min(s + HORIZON_H, len(t1))
        if e - s < 5:
            continue
        up = P * (1 + M / 100); dn = P * (1 - M / 100)
        fp = first_passage(h1H, h1L, s, e, up, dn)
        if fp is None:
            continue
        trig = 1 if imp >= TRIG else (-1 if imp <= -TRIG else 0)
        # continuation = барьер по направлению импульса первым
        cont = None
        if trig == 1:
            cont = fp            # вверх первым = продолжил
        elif trig == -1:
            cont = 1 - fp        # вниз первым = продолжил
        rows.append({"sym": sym, "trig": trig, "cont": cont, "fp_up": fp,
                     "regime": atr_pctile[i], "imp": imp})
    return rows


def stats(d, label):
    n = len(d)
    if n < 20:
        return f"  {label:28} n={n:5d} (мало)"
    cr = d["cont"].mean()
    netR = cr * 1 - (1 - cr) * 1 - COST_RT / (M / 100)
    return f"  {label:28} n={n:5d}  continuation={cr*100:5.1f}%  net-R={netR:+.3f}"


def main():
    rows = []
    for s in SYMBOLS:
        print(f"[{s}] build...", flush=True); rows += build(s)
    df = pd.DataFrame(rows)
    trig = df[df.trig != 0].copy()          # сработавшие волны
    notr = df[df.trig == 0].copy()
    print(f"[data] всего {len(df)}, импульс-триггеров {len(trig)} ({len(trig)/len(df)*100:.0f}%)", flush=True)

    out = []; A = out.append
    A(f"ТЕСТ «ВОЛНЫ» — континуация после импульса. W={W}бар импульс>={TRIG}%, барьер ±{M}% RR1, путь по 1h, вход open[i+1]-экв.")
    A(f"Триггеров {len(trig)} из {len(df)} якорей. Геом-нуль continuation = 50% (symmetric).")
    A(f"net-R учитывает кост {COST_RT*100:.2f}%RT (~{COST_RT/(M/100):.3f}R).\n")

    A("=== ВСЕ ТРИГГЕРЫ (волна началась -> едем с ней) ===")
    A(stats(trig, "все импульс-входы"))
    A("\n=== РАСКОЛ LONG/SHORT (асимметрия = бычий дрейф, не закон) ===")
    A(stats(trig[trig.trig == 1], "LONG (импульс вверх)"))
    A(stats(trig[trig.trig == -1], "SHORT (импульс вниз)"))

    A("\n=== СИНТЕЗ: раскол по ВОЛА-РЕЖИМУ (спасает ли экспансия континуацию?) ===")
    q = trig.regime
    A(stats(trig[q >= 0.66], "ЭКСПАНСИЯ (вола top-34%)"))
    A(stats(trig[(q >= 0.33) & (q < 0.66)], "средняя вола"))
    A(stats(trig[q < 0.33], "ТИХО (вола low-34%)"))

    A("\n=== КОНТРОЛЬ: RANDOM-вход (нет триггера) — бьёт ли волна случайность? ===")
    # random: на не-триггерных барах берём случайную сторону, continuation = эта сторона первой
    rng = np.random.default_rng(1)
    side = rng.integers(0, 2, len(notr))     # 1=ставим на up, 0=на down
    rcont = np.where(side == 1, notr.fp_up.values, 1 - notr.fp_up.values)
    rcr = rcont.mean(); rnet = rcr - (1 - rcr) - COST_RT / (M / 100)
    A(f"  random-вход (случ.сторона)   n={len(notr):5d}  continuation={rcr*100:5.1f}%  net-R={rnet:+.3f}")
    # геом-нуль на самих триггерах: доля up среди всех (дрейф)
    A(f"  (для справки: доля up-first среди ВСЕХ = {df.fp_up.mean()*100:.1f}% = бычий дрейф)")

    A("\n=== CROSS-ASSET (все триггеры по активам) ===")
    for s in SYMBOLS:
        A(stats(trig[trig.sym == s], s))

    A("\n=== ВЕРДИКТ ===")
    cr_all = trig.cont.mean()
    crL = trig[trig.trig == 1].cont.mean(); crS = trig[trig.trig == -1].cont.mean()
    exp_cr = trig[q >= 0.66].cont.mean()
    drift_like = abs(crL - crS) > 0.06
    momentum = cr_all > 0.53
    exp_helps = exp_cr > cr_all + 0.03
    if momentum and not drift_like:
        A(f"  МОМЕНТУМ ЕСТЬ: континуация {cr_all*100:.0f}% > 50%, симметрично long/short. Волну можно ехать.")
    else:
        A(f"  МОМЕНТУМА НЕТ (континуация {cr_all*100:.0f}% ~ 50% геом-нуль; long {crL*100:.0f}% / short {crS*100:.0f}% "
          f"{'= асимметрия=дрейф' if drift_like else ''}). Начавшийся ход НЕ предсказывает продолжение сверх геометрии.")
    A(f"  Экспансия-режим: континуация {exp_cr*100:.0f}% -> {'ПОВЫШАЕТ (синтез работает!)' if exp_helps else 'НЕ спасает континуацию'}.")
    A("  Напоминание стены: геом-перевес (ближе к барьеру) EV-нейтрален; реальный edge = только моментум сверх 50% И сверх random.")

    rep = HERE / "wave_continuation_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
