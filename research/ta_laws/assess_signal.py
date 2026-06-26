"""Оценка живого сигнала ВСЕМ стеком аналитики (контекст + ТА + зоны/законы Вадима) на ТЕКУЩИХ данных.

Сигнал S112: BTC SHORT, вход/стоп/цель заданы. Тянет live 1m (пагинация Binance), прогоняет analytics_engine
на «сейчас», + геометрия брекета (gambler's ruin), + контекст-выравнивание шорта, + магнит/clear-path к цели,
+ realistic-TP. Вердикт: благоприятен ли инстанс для шорта (edge S112 = follow-through вниз).
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/assess_signal.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import requests
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research import analytics_engine as AE  # noqa: E402
from research.smc_adapter import zone_confluence  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- сигнал ---
SYM = "BTCUSDT"; SIDE = "SHORT"
ENTRY = 64171.80; STOP = 64290.21; TARGET = 63911.30


def fetch_1m(symbol, days=55):
    end = int(time.time() * 1000); start = end - days * 24 * 60 * 60 * 1000
    rows = []; cur = start
    while cur < end:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": symbol, "interval": "1m", "startTime": cur, "limit": 1000}, timeout=20)
        r.raise_for_status(); d = r.json()
        if not d:
            break
        rows += d; cur = d[-1][0] + 60_000
        if len(d) < 1000:
            break
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "v", "ct", "qv", "n", "tb", "tq", "ig"])
    df = df.drop_duplicates("t")
    df["open_time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df.set_index("open_time")[["open", "high", "low", "close", "v"]].rename(columns={"v": "volume"}).astype(float)


def main():
    print("fetch live 1m...", flush=True)
    df = fetch_1m(SYM, days=55)
    print(f"1m баров {len(df)}; последний {df.index[-1]}", flush=True)
    pc = AE.precompute(df, symbol=SYM)
    st = AE.analyze_at(pc, None)
    price = st.price

    # геометрия брекета
    risk = STOP - ENTRY; reward = ENTRY - TARGET; rr = reward / risk
    p_target = risk / (risk + reward)        # driftless P(цель раньше стопа)
    be_wr = 1 / (1 + rr)

    out = []
    out.append("ОЦЕНКА СИГНАЛА S112 BTC SHORT — весь стек аналитики, live данные.\n")
    out.append(f"Текущая цена движка: ${price:,.0f} (сигнал-вход ${ENTRY:,.0f}; расхождение {(price-ENTRY)/ENTRY*100:+.2f}%)")
    out.append(f"Время среза: {st.ts:%Y-%m-%d %H:%M} UTC\n")

    out.append("=== 1) ГЕОМЕТРИЯ БРЕКЕТА (gambler's ruin) ===")
    out.append(f"  риск {risk:.1f} / профит {reward:.1f} → RR {rr:.2f}")
    out.append(f"  P(цель раньше стопа) по геометрии ≈ {p_target*100:.0f}%  |  безубыток RR2.2 = {be_wr*100:.0f}%")
    out.append(f"  → сама геометрия ≈ {'НОЛЬ (туго-стоп съедает RR)' if abs(p_target-be_wr)<0.03 else 'смещена'}; "
               f"плюс только за счёт edge S112 (ист. WR 44% > {p_target*100:.0f}% need).")

    out.append("\n=== 2) КОНТЕКСТ (направление) ===")
    c = st.ctx
    aligned = (SIDE == "SHORT" and c['mtf_up'] <= 1) or (SIDE == "LONG" and c['mtf_up'] >= 2)
    out.append(f"  1h/4h/1d: {'/'.join([c['t1'],c['t4'],c['td']])} → {c['word']} ({c['mtf_up']}/3 вверх) · "
               f"ATR {c['atr_pct']}% · в диапазоне {c['range_pos']:.0f}%")
    out.append(f"  SHORT {'СОГЛАСОВАН с контекстом (вниз/слабый верх) ✅' if aligned else 'ПРОТИВ контекста (тренд вверх) ⚠️ — fade-риск'}")

    out.append("\n=== 3) ЗОНЫ ВАДИМА (магнит/путь/цель) ===")
    # магнит против шорта (зоны сверху) и к цели (зоны снизу)
    mag_short = st.magnet_short    # магниты сверху (против шорта = сопротивление, защищает стоп)
    mag_long = st.magnet_long      # магниты снизу (к цели = тянут вниз = помощь шорту)
    out.append(f"  магнит сверху (против шорта/защита стопа): {mag_short:.0f}")
    out.append(f"  магнит снизу (к цели вниз/помощь шорту):   {mag_long:.0f}")
    out.append(f"  чистота пути (модуль): чище {st.clear_side}")
    out.append(f"  realistic-TP вниз (ближайший магнит): {st.tp_down:,.0f}  (цель сигнала {TARGET:,.0f})")
    # зоны вокруг entry/target
    near_e = [z for z in st.zones if z.lo <= ENTRY <= z.hi or abs((z.lo+z.hi)/2-ENTRY)/ENTRY < 0.004]
    near_t = [z for z in st.zones if z.lo <= TARGET <= z.hi or abs((z.lo+z.hi)/2-TARGET)/TARGET < 0.004]
    out.append(f"  зон у входа {ENTRY:,.0f}: {[(z.tf,z.type,z.role) for z in near_e][:4] or 'нет'}")
    out.append(f"  зон у цели {TARGET:,.0f}: {[(z.tf,z.type,z.role) for z in near_t][:4] or 'нет'}")
    # есть ли поддержка-блок МЕЖДУ входом и целью (мешает шорту)
    block_between = [z for z in st.zones if TARGET < (z.lo+z.hi)/2 < ENTRY and z.role == "block"]
    out.append(f"  блок-поддержка МЕЖДУ входом и целью (мешает шорту): "
               f"{len(block_between)} {[(z.tf,round((z.lo+z.hi)/2)) for z in block_between][:3]}")

    out.append("\n=== 4) ТА-сетап движка (для справки) ===")
    out.append(f"  {st.setups[0].verdict if st.setups else 'свежего arc-сетапа нет'}")

    out.append("\n=== ВЕРДИКТ ===")
    score = 0
    score += 1 if aligned else -1
    score += 1 if mag_long > mag_short else -1   # магнит тянет вниз (к цели) сильнее, чем вверх
    score += 1 if len(block_between) == 0 else -1
    if TARGET >= st.tp_down - 1:                  # цель не дальше realistic-магнита
        score += 1
    grade = "БЛАГОПРИЯТНЫЙ" if score >= 2 else ("НЕЙТРАЛЬНЫЙ" if score >= 0 else "НЕБЛАГОПРИЯТНЫЙ")
    out.append(f"  Аналитика-оценка инстанса: {grade} (score {score:+d}/4)")
    out.append(f"  Контекст {'за' if aligned else 'ПРОТИВ'} · путь к цели {'чистый' if not block_between else 'с поддержкой-блоком'} · "
               f"магнит {'тянет вниз' if mag_long>mag_short else 'тянет вверх (против)'} · цель {'достижима (у магнита)' if TARGET>=st.tp_down-1 else 'за ближайшим магнитом'}")
    out.append("  Помни: направление=монетка; аналитика — ФИЛЬТР качества, а edge несёт сам S112 (follow-through). "
               "Геометрия брекета на нуле — туго-стоп требует чистого хода вниз.")

    rep = HERE = Path(__file__).resolve().parent
    (rep / "assess_signal_report.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
