"""ПОЛНАЯ ТА-аналитика BTC сейчас -> чарт + структурный разбор -> лично админу в бот.

Сводит весь модуль: (1) мульти-ТФ КОНТЕКСТ/режим (несущий слой — определяет направление),
(2) ФИГУРЫ по таксономии (направление=контекст, цель=масштаб), (3) АРКИ/кривые (parabola-fit),
(4) КОНФЛЮЭНС-ВЕРДИКТ: есть ли СЕЙЧАС торгуемый trend-continuation pullback (валидир. +0.164R сетап:
форма + контекст СОВПАДАЕТ). Эмпирика категорий тянется из pattern_taxonomy.csv.

Канал: DASHBOARD_BOT_TOKEN (аналитический), получатель ADMIN=901107007. НЕ продакшн-сигнальный, НЕ рассылка.
Флаги: --dry (без отправки), --photo-only.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/send_full_btc_report.py
"""
from __future__ import annotations

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
import curves as C    # noqa: E402

ADMIN = 901107007
TB_ATR = 1.5
REVERSAL = {"DOUBLE_TOP", "DOUBLE_BOTTOM", "TRIPLE_TOP", "TRIPLE_BOTTOM", "HEAD_SHOULDERS", "INV_HEAD_SHOULDERS"}
CONTINUATION = {"ASC_TRIANGLE", "DESC_TRIANGLE", "SYM_TRIANGLE"}
RU_KIND = {
    "DOUBLE_TOP": "Двойная вершина", "DOUBLE_BOTTOM": "Двойное дно",
    "TRIPLE_TOP": "Тройная вершина", "TRIPLE_BOTTOM": "Тройное дно",
    "HEAD_SHOULDERS": "Голова-плечи", "INV_HEAD_SHOULDERS": "Перевёрнутые Г-П",
    "ASC_TRIANGLE": "Восх. треуг.", "DESC_TRIANGLE": "Нисх. треуг.",
    "SYM_TRIANGLE": "Симм. треуг.", "RECTANGLE": "Прямоугольник",
}


def load_env():
    env = {}
    for ln in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def fetch(sym, interval, limit):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": sym, "interval": interval, "limit": limit}, timeout=20)
    r.raise_for_status()
    d = r.json()
    df = pd.DataFrame(d, columns=["t", "open", "high", "low", "close", "v", "ct", "qv", "n", "tb", "tq", "ig"])
    df["open_time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df.set_index("open_time")[["open", "high", "low", "close", "v"]].rename(columns={"v": "volume"}).astype(float)


def trend(series, ts, td):
    a = series.asof(ts); b = series.asof(ts - td)
    return "UP" if (pd.notna(a) and pd.notna(b) and a > b) else "DOWN"


def cat_stats():
    csv = HERE / "pattern_taxonomy.csv"
    if not csv.exists():
        return None
    df = pd.read_csv(csv)
    df["scale"] = pd.cut(df.height_atr, [-1, 3, 6, 1e9], labels=["мелк", "сред", "крупн"]).astype(str)
    df["trel"] = df.trend_with.map({1: "ПО", 0: "ПРОТИВ"})
    df["nat"] = df.kind.map(lambda k: "REVERS" if k in REVERSAL else ("CONTIN" if k in CONTINUATION else "RANGE"))
    return df


def lookup(df, nat, scale):
    g = df[(df.nat == nat) & (df.scale == scale)]
    if len(g) < 40:
        g = df[df.scale == scale]
    gd = g[g.dirR != 0]; gb = g[g.broke == 1].dropna(subset=["ext_h"])
    return {"pdir": (gd.dirR > 0).mean() * 100 if len(gd) else 50.0,
            "ext": gb.ext_h.median() if len(gb) else 0.49, "n": len(g)}


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
    if not token and "--dry" not in sys.argv:
        print("[!] DASHBOARD_BOT_TOKEN нет в .env — отмена."); return

    df = fetch("BTCUSDT", "1h", 1000)
    c4 = fetch("BTCUSDT", "4h", 300)["close"]
    c1d = fetch("BTCUSDT", "1d", 120)["close"]
    c1h = df["close"]
    now = df.index[-1]; price = float(c1h.iloc[-1]); n = len(df)
    atr = G.compute_atr(df)
    atr_roll = pd.Series(atr).rolling(100, min_periods=20).mean().values
    arrow = lambda t: "🟢▲" if t == "UP" else "🔴▼"

    # ---- (1) КОНТЕКСТ / РЕЖИМ ----
    t1 = trend(c1h, now, pd.Timedelta(hours=10))
    t4 = trend(c4, now, pd.Timedelta(hours=40))
    td = trend(c1d, now, pd.Timedelta(days=10))
    mtf_up = sum(t == "UP" for t in (t1, t4, td))
    ctx_word = {3: "сильно ВВЕРХ", 0: "сильно ВНИЗ"}.get(mtf_up, "ВВЕРХ" if mtf_up >= 2 else "ВНИЗ")
    atr_pct = atr[-1] / price * 100
    vol_state = atr[-1] / atr_roll[-1] if atr_roll[-1] > 0 else 1.0
    vol_word = "расширение" if vol_state > 1.1 else ("сжатие" if vol_state < 0.9 else "норма")
    lo50, hi50 = df["low"].values[-50:].min(), df["high"].values[-50:].max()
    rng_pos = (price - lo50) / (hi50 - lo50) * 100 if hi50 > lo50 else 50
    d7 = trend(c1d, now, pd.Timedelta(days=7))

    stats = cat_stats()

    # ---- (2) ФИГУРЫ (таксономия) ----
    figs = F.find_figures(df)
    figs = [f for f in figs if 1 < f.comp_conf_i < n - 1 and f.comp_conf_i >= n - 200]
    figs = sorted(figs, key=lambda f: f.comp_conf_i)[-2:]
    fig_reads = []
    for f in figs:
        arm = f.comp_conf_i; a_atr = atr[arm]
        nat = "REVERS" if f.kind in REVERSAL else ("CONTIN" if f.kind in CONTINUATION else "RANGE")
        height_atr = f.height / a_atr if a_atr > 0 else 0
        scale = "мелк" if height_atr < 3 else ("сред" if height_atr < 6 else "крупн")
        mtf = sum(int(trend(s, df.index[arm], pdt) == f.expected_dir) for s, pdt in
                  [(c1h, pd.Timedelta(hours=10)), (c4, pd.Timedelta(hours=40)), (c1d, pd.Timedelta(days=10))])
        st = lookup(stats, nat, scale) if stats is not None else {"pdir": 50, "ext": 0.49, "n": 0}
        is_fade = mtf <= 1
        act_dir = f.expected_dir if not is_fade else ("UP" if f.expected_dir == "DOWN" else "DOWN")
        tgt = f.neckline + st["ext"] * f.height if f.expected_dir == "UP" else f.neckline - st["ext"] * f.height
        fig_reads.append(dict(f=f, arm=arm, nat=nat, scale=scale, mtf=mtf, st=st, is_fade=is_fade,
                              act_dir=act_dir, tgt=tgt, neck=f.neckline, height_atr=height_atr))

    # ---- (3) АРКИ ----
    arcs = C.find_arcs(df, atr=atr)
    arcs = [a for a in arcs if a.i1 >= n - 160 and a.i1 < n - 1]
    arcs = sorted(arcs, key=lambda a: a.i1)[-3:]
    arc_reads = []
    for a in arcs:
        i1 = a.i1; L = a.i1 - a.i0
        aa, bb, _ = a.coeffs
        end_dir = "UP" if (2 * aa * L + bb) > 0 else "DOWN"
        fade_dir = "UP" if end_dir == "DOWN" else "DOWN"
        apex_pos = (a.apex_i - a.i0) / max(L, 1)
        mtf_f = sum(int(trend(s, df.index[i1], pdt) == fade_dir) for s, pdt in
                    [(c1h, pd.Timedelta(hours=10)), (c4, pd.Timedelta(hours=40)), (c1d, pd.Timedelta(days=10))])
        aligned = mtf_f >= 2                       # fade разворачивается ОБРАТНО в мульти-ТФ тренд
        well_formed = a.sagitta_atr >= 2.5 and apex_pos >= 0.4
        tradeable = well_formed and aligned and (i1 >= n - 30)   # свежая + условия
        arc_reads.append(dict(a=a, i1=i1, kind=a.kind, end_dir=end_dir, fade_dir=fade_dir,
                              apex=apex_pos, sag=a.sagitta_atr, mtf_f=mtf_f, aligned=aligned,
                              well_formed=well_formed, tradeable=tradeable, atr=atr[i1]))

    # ---- (4) КОНФЛЮЭНС-ВЕРДИКТ (есть ли торгуемый сетап СЕЙЧАС) ----
    setup = None
    fresh_aligned = [r for r in arc_reads if r["tradeable"]]
    if fresh_aligned:
        r = fresh_aligned[-1]; a = r["a"]
        d = 1 if r["fade_dir"] == "UP" else -1
        entry = price
        stop = entry - 1.5 * r["atr"] * d
        target = entry + 2 * (1.5 * r["atr"]) * d
        setup = dict(dir=r["fade_dir"], entry=entry, stop=stop, target=target,
                     kind=r["kind"], sag=r["sag"], reason="форма+контекст СОВПАДАЕТ (trend-continuation pullback)")

    # ================= ЧАРТ =================
    fig, ax = plt.subplots(figsize=(18, 9))
    fig.patch.set_facecolor("#0e1116"); ax.set_facecolor("#0e1116")
    start = max(n - 240, 0)
    candles(ax, df.iloc[start:], start)
    ca = lambda t: "▲" if t == "UP" else "▼"   # без эмодзи для шрифта чарта
    leg = [f"КОНТЕКСТ 1h{ca(t1)} 4h{ca(t4)} 1d{ca(td)} = {ctx_word}",
           f"ATR {atr_pct:.1f}% ({vol_word}) · в диапазоне {rng_pos:.0f}%"]
    mi = 0
    for r in arc_reads:
        a = r["a"]; mi += 1
        aa, bb, cc = a.coeffs
        xs = np.arange(0, a.i1 - a.i0 + 1); ys = aa * xs * xs + bb * xs + cc
        col = "#06d6a0" if r["kind"] == "ROUNDING_BOTTOM" else "#ffd166"
        ax.plot(np.arange(a.i0, a.i1 + 1), ys, color=col, lw=2.4, zorder=6)
        ax.text(a.i0, a.p0, f" A{mi}", color=col, fontsize=9, fontweight="bold", zorder=8)
        kindru = "купол" if r["kind"] == "ROUNDING_TOP" else "чаша"
        verdict = "✅ ТОРГ. (pullback по тренду)" if r["tradeable"] else (
            "конфлюэнс есть" if r["aligned"] and r["well_formed"] else "слабая/против контекста")
        leg.append(f"A{mi} {kindru} sag{r['sag']:.1f} fade→{('ВВЕРХ' if r['fade_dir']=='UP' else 'ВНИЗ')} [{verdict}]")
    fi = 0
    for r in fig_reads:
        f = r["f"]; fi += 1
        col = "#d73027" if r["is_fade"] else "#1db954"
        ax.hlines(f.neckline, f.pivots[0].i, min(f.comp_conf_i + 20, n + 14), color="#9aa", lw=1.0, ls="--", zorder=4)
        ax.text(f.pivots[0].i, f.neckline, f" F{fi}", color=col, fontsize=9, fontweight="bold", zorder=8)
        leg.append(f"F{fi} {RU_KIND.get(f.kind, f.kind)} [{r['scale']}, mtf {r['mtf']}/3] цель {r['tgt']:,.0f}")
    if setup:
        d = 1 if setup["dir"] == "UP" else -1
        for lvl, cc, nm in [(setup["entry"], "#42a5f5", "ВХОД"), (setup["stop"], "#ef5350", "СТОП"),
                            (setup["target"], "#1db954", "ЦЕЛЬ")]:
            ax.hlines(lvl, n - 12, n + 16, color=cc, lw=1.6, zorder=7)
            ax.text(n + 16, lvl, f" {nm} {lvl:,.0f}", color=cc, fontsize=8, va="center", zorder=8)
    ax.text(0.012, 0.985, "\n".join(leg), transform=ax.transAxes, fontsize=8.5, color="#eee",
            va="top", ha="left", zorder=9, family="monospace",
            bbox=dict(boxstyle="round,pad=0.6", fc="#161b22", ec="#30363d"))
    ax.set_title(f"BTC · ПОЛНАЯ ТА-аналитика · {now:%Y-%m-%d %H:%M} UTC · ${price:,.0f}", fontsize=12, color="#eee")
    ax.set_xlim(start - 2, n + 24); ax.grid(alpha=0.12, color="#888"); ax.tick_params(colors="#aaa", labelsize=7)
    xt = list(range(start, n, max((n - start) // 10, 1)))
    ax.set_xticks(xt); ax.set_xticklabels([df.index[t].strftime("%m-%d\n%H:%M") for t in xt])
    for sp in ax.spines.values():
        sp.set_color("#444")
    fig.tight_layout()
    out = HERE / "btc_full_report.png"
    fig.savefig(out, dpi=120, facecolor=fig.get_facecolor()); print(f"saved {out}")

    # ================= ТЕКСТ =================
    L = [f"📊 <b>ПОЛНАЯ ТА-АНАЛИТИКА BTC</b>",
         f"🕒 {now:%Y-%m-%d %H:%M} UTC · цена <b>${price:,.0f}</b>", ""]
    L.append("<b>1) КОНТЕКСТ / РЕЖИМ</b> (несущий слой — задаёт направление):")
    L.append(f"   1h {arrow(t1)} · 4h {arrow(t4)} · 1d {arrow(td)} → <b>{ctx_word}</b> ({mtf_up}/3 ТФ вверх)")
    L.append(f"   Волатильность ATR {atr_pct:.1f}% — <b>{vol_word}</b> · позиция в 50-бар диапазоне <b>{rng_pos:.0f}%</b> · неделя {arrow(d7)}")
    L.append("")
    L.append("<b>2) ФИГУРЫ</b> (направление=контекст, цель=масштаб обратно):")
    if not fig_reads:
        L.append("   — свежих завершённых фигур нет.")
    for i, r in enumerate(fig_reads, 1):
        f = r["f"]
        tb_dir = "ВВЕРХ" if f.expected_dir == "UP" else "ВНИЗ"
        act_dir = "ВВЕРХ" if r["act_dir"] == "UP" else "ВНИЗ"
        head = f"   F{i}. {RU_KIND.get(f.kind, f.kind)} [{r['nat']}/{r['scale']} {r['height_atr']:.1f}ATR, mtf {r['mtf']}/3]"
        if r["is_fade"]:
            L.append(f"{head} → учебный пробой <b>{tb_dir}</b> к <code>{r['tgt']:,.0f}</code> "
                     f"ПРОТИВ контекста ⚠️ маловероятен → байес <b>{act_dir}</b> (fade)")
        else:
            cut = " (крупная — режь цель)" if r["scale"] == "крупн" else ""
            L.append(f"{head} → <b>{act_dir}</b>, уровень <code>{r['neck']:,.0f}</code>, "
                     f"цель <code>{r['tgt']:,.0f}</code>{cut}")
    L.append("")
    L.append("<b>3) АРКИ / КРИВЫЕ</b> (parabola-fit; edge только форма+контекст):")
    if not arc_reads:
        L.append("   — арок в окне нет.")
    for i, r in enumerate(arc_reads, 1):
        kindru = "купол ∩" if r["kind"] == "ROUNDING_TOP" else "чаша U"
        fd = "ВВЕРХ" if r["fade_dir"] == "UP" else "ВНИЗ"
        verdict = ("✅ ТОРГУЕМЫЙ (pullback по тренду)" if r["tradeable"] else
                   ("конфлюэнс есть, но не свежая" if r["aligned"] and r["well_formed"] else
                    "слабая или против контекста → пропуск"))
        L.append(f"   A{i}. {kindru} sag {r['sag']:.1f}ATR, apex {r['apex']:.2f} → разворот {fd} "
                 f"(контекст за fade {r['mtf_f']}/3) · {verdict}")
    L.append("")
    L.append("<b>4) КОНФЛЮЭНС-ВЕРДИКТ</b> (валидир. сетап = форма + контекст СОВПАДАЕТ, нетто +0.164R):")
    if setup:
        rr = abs(setup["target"] - setup["entry"]) / abs(setup["entry"] - setup["stop"])
        L.append(f"   ✅ <b>ЕСТЬ сетап: {('ЛОНГ' if setup['dir']=='UP' else 'ШОРТ')}</b> ({setup['reason']})")
        L.append(f"      Вход <code>{setup['entry']:,.0f}</code> · Стоп <code>{setup['stop']:,.0f}</code> "
                 f"· Цель <code>{setup['target']:,.0f}</code> (RR {rr:.1f})")
    else:
        L.append("   ⏸ <b>Чистого торгуемого сетапа сейчас НЕТ</b> — нет свежей формы, совпадающей с контекстом. "
                 "Ждать pullback-арки/фигуры В СТОРОНУ доминирующего тренда.")
    L.append("")
    L.append("📜 <b>Законы:</b> направление=контекст(mtf), не форма · цель=масштаб обратно (мелк ~0.8× / крупн ~0.25×) · "
             "голая форма=монетка, edge=форма+контекст (pullback по тренду) · континуация флага=фольклор.")
    L.append("<i>Аналитика, не сигнал. Не рассылка — лично вам.</i>")
    msg = "\n".join(L)

    if "--dry" in sys.argv:
        print(msg); print("\n[dry] не отправлено."); return

    base = f"https://api.telegram.org/bot{token}"
    chk = requests.get(f"{base}/getChat", params={"chat_id": ADMIN}, timeout=20).json()
    if not chk.get("ok"):
        print(f"[!] бот не видит чат {ADMIN}: {chk.get('description')} — нужно /start у бота. Отмена."); return
    cap = (f"📊 <b>Полная ТА-аналитика BTC</b> · {now:%H:%M} UTC · ${price:,.0f}\n"
           f"Контекст {ctx_word} · разбор (контекст/фигуры/арки/вердикт) ниже.")
    with open(out, "rb") as ph:
        rp = requests.post(f"{base}/sendPhoto", data={"chat_id": ADMIN, "caption": cap, "parse_mode": "HTML"},
                           files={"photo": ph}, timeout=60).json()
    print("sendPhoto ok" if rp.get("ok") else f"sendPhoto FAIL: {rp.get('description')}")
    if "--photo-only" not in sys.argv:
        rm = requests.post(f"{base}/sendMessage",
                           data={"chat_id": ADMIN, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
                           timeout=30).json()
        print("sendMessage ok" if rm.get("ok") else f"sendMessage FAIL: {rm.get('description')}")


if __name__ == "__main__":
    main()
