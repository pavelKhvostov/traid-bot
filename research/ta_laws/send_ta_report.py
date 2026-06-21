"""ТА-АНАЛИТИКА «на текущий момент» -> красивый чарт + разбор -> личное сообщение в бот.

Применяет ВЫВЕДЕННЫЕ законы/таксономию к ЖИВОМУ рынку BTC 1h:
  - контекст мульти-ТФ (1h/4h/1d) — определяет НАПРАВЛЕНИЕ (по таксономии: куда = контекст, не форма);
  - последние фигуры/архетипы — категория (природа×тренд-связь×масштаб) -> цель (масштаб обратно) +
    качество + ВЕРДИКТ (учебник работает / режь цель / зона fade);
  - эмпирические числа категорий тянутся из pattern_taxonomy.csv (не хардкод).
Рисует аннотированный чарт + шлёт sendPhoto(caption) + sendMessage(полный разбор) ЛИЧНО админу.

Канал: DASHBOARD_BOT_TOKEN (аналитический бот), получатель = ADMIN (901107007).
НЕ трогает продакшн-сигнальный токен, НЕ делает рассылку подписчикам.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/send_ta_report.py
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from matplotlib.patches import Rectangle

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
import figures as F   # noqa: E402

ADMIN = 901107007
TB_ATR = 1.5
REVERSAL = {"DOUBLE_TOP", "DOUBLE_BOTTOM", "TRIPLE_TOP", "TRIPLE_BOTTOM", "HEAD_SHOULDERS", "INV_HEAD_SHOULDERS"}
CONTINUATION = {"ASC_TRIANGLE", "DESC_TRIANGLE", "SYM_TRIANGLE"}
RU_KIND = {
    "DOUBLE_TOP": "Двойная вершина", "DOUBLE_BOTTOM": "Двойное дно",
    "TRIPLE_TOP": "Тройная вершина", "TRIPLE_BOTTOM": "Тройное дно",
    "HEAD_SHOULDERS": "Голова-плечи", "INV_HEAD_SHOULDERS": "Перевёрнутые Г-П",
    "ASC_TRIANGLE": "Восходящий треуг.", "DESC_TRIANGLE": "Нисходящий треуг.",
    "SYM_TRIANGLE": "Симметричный треуг.", "RECTANGLE": "Прямоугольник (рейндж)",
}


def load_env():
    env = {}
    p = ROOT / ".env"
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def fetch(symbol, interval, limit):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=20)
    r.raise_for_status()
    d = r.json()
    df = pd.DataFrame(d, columns=["t", "open", "high", "low", "close", "volume",
                                  "ct", "qv", "n", "tb", "tq", "ig"])
    df["open_time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df.set_index("open_time")[["open", "high", "low", "close", "volume"]].astype(float)


def trend(series, ts, td):
    a = series.asof(ts); b = series.asof(ts - td)
    return "UP" if (pd.notna(a) and pd.notna(b) and a > b) else "DOWN"


def cat_stats():
    """Эмпирические профили категорий из pattern_taxonomy.csv (если есть)."""
    csv = HERE / "pattern_taxonomy.csv"
    if not csv.exists():
        return None
    df = pd.read_csv(csv)
    df["scale"] = pd.cut(df.height_atr, [-1, 3, 6, 1e9], labels=["мелк", "сред", "крупн"]).astype(str)
    df["trel"] = df.trend_with.map({1: "ПО", 0: "ПРОТИВ"})
    df["nat"] = df.kind.map(lambda k: "REVERS" if k in REVERSAL else ("CONTIN" if k in CONTINUATION else "RANGE"))
    return df


def lookup(df, nat, trel, scale):
    g = df[(df.nat == nat) & (df.trel == trel) & (df.scale == scale)]
    if len(g) < 40:
        g = df[(df.nat == nat) & (df.scale == scale)]
    if len(g) < 40:
        g = df[df.scale == scale]
    gd = g[g.dirR != 0]; gb = g[g.broke == 1].dropna(subset=["ext_h"])
    return {
        "n": len(g),
        "pdir": (gd.dirR > 0).mean() * 100 if len(gd) else 50.0,
        "ext": gb.ext_h.median() if len(gb) else 0.49,
        "ft": gb.ft_ratio.median() if len(gb) else 0.74,
    }


def candles(ax, sub, x0):
    for i, (_, r) in enumerate(sub.iterrows()):
        x = x0 + i
        up = r["close"] >= r["open"]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([x, x], [r["low"], r["high"]], color=col, lw=0.7, zorder=2)
        a, b = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.32, a), 0.64, max(b - a, 1e-9), facecolor=col, edgecolor=col, zorder=3))


def main():
    env = load_env()
    token = env.get("DASHBOARD_BOT_TOKEN")
    if not token:
        print("[!] DASHBOARD_BOT_TOKEN не найден в .env — отправка отменена.")
        return
    # --- данные ---
    df = fetch("BTCUSDT", "1h", 1000)
    c1h = df["close"]
    c4 = fetch("BTCUSDT", "4h", 300)["close"]
    c1d = fetch("BTCUSDT", "1d", 90)["close"]
    now = df.index[-1]
    price = float(c1h.iloc[-1])
    atr = G.compute_atr(df)
    n = len(df)

    # --- контекст мульти-ТФ (определяет направление по таксономии) ---
    t1 = trend(c1h, now, pd.Timedelta(hours=10))
    t4 = trend(c4, now, pd.Timedelta(hours=40))
    td = trend(c1d, now, pd.Timedelta(days=10))
    ctx_up = sum(t == "UP" for t in (t1, t4, td))
    ctx_word = {3: "сильно ВВЕРХ", 0: "сильно ВНИЗ"}.get(ctx_up, "ВВЕРХ" if ctx_up >= 2 else "ВНИЗ")

    stats = cat_stats()

    # --- последние фигуры ---
    figs = F.find_figures(df)
    figs = [f for f in figs if 1 < f.comp_conf_i < n - 1 and f.comp_conf_i >= n - 300]
    figs = sorted(figs, key=lambda f: f.comp_conf_i)[-3:]

    reads = []
    for f in figs:
        arm = f.comp_conf_i
        a_atr = atr[arm]
        nat = "REVERS" if f.kind in REVERSAL else ("CONTIN" if f.kind in CONTINUATION else "RANGE")
        p0i = f.pivots[0].i
        prior = "UP" if df["close"].values[arm] > df["close"].values[max(0, p0i - 1)] else "DOWN"
        trel = "ПО" if f.expected_dir == prior else "ПРОТИВ"
        height_atr = f.height / a_atr if a_atr > 0 else 0
        scale = "мелк" if height_atr < 3 else ("сред" if height_atr < 6 else "крупн")
        mtf = sum(int(trend(s, df.index[arm], pdt) == f.expected_dir) for s, pdt in
                  [(c1h, pd.Timedelta(hours=10)), (c4, pd.Timedelta(hours=40)), (c1d, pd.Timedelta(days=10))])
        st = lookup(stats, nat, trel, scale) if stats is not None else {"pdir": 50, "ext": 0.49, "ft": 0.74, "n": 0}
        # направление по КОНТЕКСТУ (закон: куда = контекст)
        if mtf >= 3:
            dir_tier = "контекст ЗА учебную сторону (~59%)"; verdict_dir = f.expected_dir
        elif mtf <= 1:
            dir_tier = "контекст ПРОТИВ (~45%) → риск ложного пробоя / FADE"; verdict_dir = "UP" if f.expected_dir == "DOWN" else "DOWN"
        else:
            dir_tier = "контекст нейтрален (~52%)"; verdict_dir = f.expected_dir
        # цель по МАСШТАБУ (закон: докуда = масштаб обратно)
        ext_mult = st["ext"]
        tgt = f.neckline + ext_mult * f.height if f.expected_dir == "UP" else f.neckline - ext_mult * f.height
        # вердикт-карточка
        if scale == "мелк" and mtf >= 2:
            verdict = "✅ учебник работает: measured-move реалистичен, стоп узкий"
        elif scale == "крупн":
            verdict = "✂️ крупная фигура → режь цель до 0.25–0.4× высоты, монетка по направлению"
        elif mtf <= 1:
            verdict = "⚠️ против контекста → не торговать по учебнику, зона FADE"
        else:
            verdict = "◽ средний сетап: цель ~0.5× высоты, по контексту"
        # действенное направление/цель (для fade рисуем ПРОТИВ учебника, учебную цель -> «фольклор»)
        is_fade = (mtf <= 1 and verdict_dir != f.expected_dir)
        if is_fade:
            act_dir = verdict_dir
            act_tgt = f.neckline + (1.5 * a_atr if act_dir == "UP" else -1.5 * a_atr)
            folklore_tgt = tgt
        else:
            act_dir = f.expected_dir
            act_tgt = tgt
            folklore_tgt = None
        reads.append(dict(f=f, arm=arm, nat=nat, trel=trel, scale=scale, height_atr=height_atr,
                          mtf=mtf, st=st, dir_tier=dir_tier, verdict_dir=verdict_dir,
                          ext_mult=ext_mult, tgt=tgt, verdict=verdict, a_atr=a_atr,
                          is_fade=is_fade, act_dir=act_dir, act_tgt=act_tgt, folklore_tgt=folklore_tgt))

    # ---------- ЧАРТ ----------
    def vcol(r):
        if "✅" in r["verdict"]:
            return "#1db954"
        if "⚠️" in r["verdict"] or "FADE" in r["dir_tier"]:
            return "#ff4d4d"
        return "#c9a227"

    fig, ax = plt.subplots(figsize=(18, 9))
    fig.patch.set_facecolor("#0e1116"); ax.set_facecolor("#0e1116")
    start = max(n - 220, 0)
    sub = df.iloc[start:]
    candles(ax, sub, start)
    for i, r in enumerate(reads, 1):
        f = r["f"]; arm = r["arm"]; col = vcol(r)
        ax.hlines(f.neckline, f.pivots[0].i, min(arm + 26, n + 22), color="#9aa", lw=1.0, ls="--", zorder=4)
        # фольклорная (учебная) цель — серым пунктиром, перечёркнуто, для fade
        if r["folklore_tgt"] is not None:
            ax.annotate("", xy=(arm + 20, r["folklore_tgt"]), xytext=(arm + 2, f.neckline),
                        arrowprops=dict(arrowstyle="-|>", color="#666", lw=1.3, ls=(0, (4, 3)),
                                        connectionstyle="arc3,rad=-0.10"), zorder=3)
        # действенная цель/направление
        y0, y1 = sorted([f.neckline, r["act_tgt"]])
        ax.add_patch(Rectangle((arm + 2, y0), 22, y1 - y0, facecolor=col, alpha=0.10, edgecolor="none", zorder=1))
        ax.annotate("", xy=(arm + 22, r["act_tgt"]), xytext=(arm + 2, f.neckline),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=2.4, connectionstyle="arc3,rad=0.10"), zorder=6)
        ax.text(arm + 2, f.neckline, f" {i} ", fontsize=10, color="#0e1116", fontweight="bold",
                ha="center", va="center", zorder=8,
                bbox=dict(boxstyle="circle,pad=0.25", fc=col, ec="none"))

    # легенда-панель со списком сетапов (читаемо, без наложений)
    if reads:
        leg = ["СЕТАПЫ (цвет = вердикт):"]
        for i, r in enumerate(reads, 1):
            d = "ВНИЗ" if r["act_dir"] == "DOWN" else "ВВЕРХ"
            tag = "FADE↗долой учебник" if r["is_fade"] else ("учебник" if "✅" in r["verdict"] else ("режь цель" if "✂️" in r["verdict"] else "по контексту"))
            extra = f" · учеб.цель(фольклор) {r['folklore_tgt']:,.0f}" if r["folklore_tgt"] is not None else ""
            leg.append(f"{i}. {RU_KIND.get(r['f'].kind, r['f'].kind)} "
                       f"[{r['scale']}/{r['trel']}, mtf {r['mtf']}/3] → {d}, цель {r['act_tgt']:,.0f} [{tag}]{extra}")
        ax.text(0.012, 0.30, "\n".join(leg), transform=ax.transAxes, fontsize=9, color="#eee",
                va="top", ha="left", zorder=9, family="monospace",
                bbox=dict(boxstyle="round,pad=0.6", fc="#161b22", ec="#30363d"))

    ax.set_title(f"BTC 1h · ТА-аналитика по законам таксономии · {now:%Y-%m-%d %H:%M} UTC · ${price:,.0f}\n"
                 f"контекст 1h/4h/1d = {ctx_word}   ·   цвет: зелёный=учебник работает · жёлтый=режь цель · красный=зона fade",
                 fontsize=11, color="#eee")
    ax.set_xlim(start - 2, n + 30)
    ax.grid(alpha=0.12, color="#888")
    ax.tick_params(colors="#aaa", labelsize=7)
    xt = list(range(start, n, max((n - start) // 10, 1)))
    ax.set_xticks(xt); ax.set_xticklabels([df.index[t].strftime("%m-%d\n%H:%M") for t in xt])
    for sp in ax.spines.values():
        sp.set_color("#444")
    fig.tight_layout()
    out = HERE / "btc_ta_report.png"
    fig.savefig(out, dpi=120, facecolor=fig.get_facecolor())
    print(f"saved {out}")

    # ---------- ТЕКСТ ----------
    arrow = lambda t: "🟢▲" if t == "UP" else "🔴▼"
    cap = (f"📊 <b>ТА-аналитика BTC · 1h</b>\n"
           f"🕒 {now:%Y-%m-%d %H:%M} UTC · цена <b>${price:,.0f}</b>\n"
           f"🧭 Контекст: 1h {arrow(t1)} · 4h {arrow(t4)} · 1d {arrow(td)} → <b>{ctx_word}</b>\n"
           f"Найдено сетапов: <b>{len(reads)}</b> (разбор ниже)")

    lines = [f"📊 <b>ТА-АНАЛИЗ BTC 1h</b> · {now:%Y-%m-%d %H:%M} UTC · <b>${price:,.0f}</b>",
             f"🧭 <b>Контекст</b> (определяет НАПРАВЛЕНИЕ): 1h {arrow(t1)} · 4h {arrow(t4)} · 1d {arrow(td)} → <b>{ctx_word}</b>",
             ""]
    if not reads:
        lines.append("Свежих завершённых фигур на 1h сейчас нет — рынок без чёткой геометрии.")
    for i, r in enumerate(reads, 1):
        f = r["f"]
        dword = "ВВЕРХ" if r["act_dir"] == "UP" else "ВНИЗ"
        lines.append(f"<b>{i}. {RU_KIND.get(f.kind, f.kind)}</b>  "
                     f"<i>[{r['nat']}/{r['trel']}-тренда/{r['scale']} {r['height_atr']:.1f}ATR]</i>")
        lines.append(f"   ↳ Действ. направление: <b>{dword}</b> · {r['dir_tier']}")
        if r["is_fade"]:
            lines.append(f"   ↳ Уровень: <code>{f.neckline:,.0f}</code> · fade-цель ≈ <code>{r['act_tgt']:,.0f}</code> "
                         f"(±1.5ATR) · учеб.цель(фольклор) <code>{r['folklore_tgt']:,.0f}</code> — маловероятна")
        else:
            lines.append(f"   ↳ Уровень пробоя: <code>{f.neckline:,.0f}</code> · "
                         f"цель ≈ <code>{r['act_tgt']:,.0f}</code> ({r['ext_mult']:.2f}× высоты)")
        lines.append(f"   ↳ Истор. профиль категории: P(сторона) {r['st']['pdir']:.0f}% · "
                     f"чистота {r['st']['ft']:.2f} (n={r['st']['n']})")
        lines.append(f"   ↳ <b>{r['verdict']}</b>")
        lines.append("")
    lines.append("📜 <b>Законы (на чём построено):</b>")
    lines.append("• <b>Куда</b> раскроется = КОНТЕКСТ (мульти-ТФ), не форма: mtf 3/3→~59% / 0-1→~45%.")
    lines.append("• <b>Докуда</b> = МАСШТАБ обратно: мелкая ≈0.77× / крупная ≈0.24× высоты.")
    lines.append("• Учебный measured-move (1×) реалистичен ТОЛЬКО для мелких фигур.")
    lines.append("• Против контекста → склонность к ложному пробою (зона fade-закона).")
    lines.append("")
    lines.append("<i>Это аналитика, не торговый сигнал. Не рассылка — отчёт лично вам.</i>")
    msg = "\n".join(lines)

    # ---------- ОТПРАВКА (только админу, аналитический бот) ----------
    if "--dry" in sys.argv:
        print("[dry] чарт сохранён, отправка пропущена.")
        return
    base = f"https://api.telegram.org/bot{token}"
    # проба доступа к чату (без спама)
    chk = requests.get(f"{base}/getChat", params={"chat_id": ADMIN}, timeout=20).json()
    if not chk.get("ok"):
        print(f"[!] dashboard-бот не видит чат {ADMIN}: {chk.get('description')}. "
              f"Нужно один раз нажать /start у этого бота. Отправка отменена.")
        return
    photo_only = "--photo-only" in sys.argv
    if photo_only:
        cap = (f"🔄 <b>Чарт в читаемом виде</b> · BTC 1h · {now:%H:%M} UTC · ${price:,.0f}\n"
               f"Нумерация ①②③ = сетапы из разбора выше.")
    with open(out, "rb") as ph:
        rp = requests.post(f"{base}/sendPhoto",
                           data={"chat_id": ADMIN, "caption": cap, "parse_mode": "HTML"},
                           files={"photo": ph}, timeout=60).json()
    print("sendPhoto ok" if rp.get("ok") else f"sendPhoto FAIL: {rp.get('description')}")
    if not photo_only:
        rm = requests.post(f"{base}/sendMessage",
                           data={"chat_id": ADMIN, "text": msg, "parse_mode": "HTML",
                                 "disable_web_page_preview": True}, timeout=30).json()
        print("sendMessage ok" if rm.get("ok") else f"sendMessage FAIL: {rm.get('description')}")


if __name__ == "__main__":
    main()
