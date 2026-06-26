"""ОБЪЕДИНЁННЫЙ per-coin анализ в бот: наш контекст + ТА-модуль + зоны/законы Вадима (один стек).

Совокупное использование (лучшее): КОНТЕКСТ(наш mtf/режим) → ЗОНЫ(канон Вадима, роли+митигация) →
ФИЛЬТР(магнит/clear-path) → ЦЕЛЬ(realistic-TP) → ВЕРДИКТ. Направление=монетка; ценность=карта+фильтр+цель.
Один движок analytics_engine кормит и текст, и чарт. BTC/ETH/SOL. Шлёт ЛИЧНО админу (901107007) через
аналитический DASHBOARD_BOT_TOKEN (не продакшн-сигналы, не рассылка).

Флаги: --dry (без отправки), --photo-only.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/send_combined_report.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research import analytics_engine as AE  # noqa: E402

ADMIN = 901107007
COINS = [("BTCUSDT", "₿ BTC"), ("ETHUSDT", "Ξ ETH"), ("SOLUSDT", "◎ SOL")]
ROLE_COL = {"block": "#3aa0ff", "inefficiency": "#ff8c42", "liquidity": "#ffd23f"}


def load_env():
    env = {}
    for ln in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def candles(ax, sub, x0):
    for i, (_, r) in enumerate(sub.iterrows()):
        x = x0 + i; up = r["close"] >= r["open"]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([x, x], [r["low"], r["high"]], color=col, lw=0.7, zorder=3)
        a, b = sorted([r["open"], r["close"]])
        ax.add_patch(Rectangle((x - 0.32, a), 0.64, max(b - a, 1e-9), facecolor=col, edgecolor=col, zorder=4))


def render_btc(pc, st, out):
    df = pc.arc["1h"]["df"]; n = len(df); start = max(n - 200, 0); xr = n + 28
    fig, ax = plt.subplots(figsize=(18, 9)); fig.patch.set_facecolor("#0e1116"); ax.set_facecolor("#0e1116")
    candles(ax, df.iloc[start:], start)
    ax.hlines(st.price, start, xr, color="#ddd", lw=0.9, ls=":", zorder=6)
    ax.text(xr, st.price, f" ${st.price:,.0f}", color="#ddd", fontsize=8, va="center")
    for z in st.zones[:14]:
        col = ROLE_COL.get(z.role, "#3aa0ff")
        ax.add_patch(Rectangle((start, z.lo), xr - start, max(z.hi - z.lo, st.price * 1e-4),
                               facecolor=col, alpha=0.14, edgecolor=col, lw=0.7, zorder=2))
        ax.text(xr, (z.lo + z.hi) / 2, f" {z.tf}·{z.type}·{z.mitigation.split('-')[0]}",
                color=col, fontsize=6.3, va="center", zorder=7)
    if st.tp_up:
        ax.hlines(st.tp_up, n - 6, xr, color="#1db954", lw=1.3, zorder=6)
        ax.text(n - 6, st.tp_up, "TP↑ ", color="#1db954", fontsize=7, ha="right", va="center")
    if st.tp_down:
        ax.hlines(st.tp_down, n - 6, xr, color="#ef5350", lw=1.3, zorder=6)
        ax.text(n - 6, st.tp_down, "TP↓ ", color="#ef5350", fontsize=7, ha="right", va="center")
    leg = [f"BTC {st.ctx['word']}  ATR {st.ctx['atr_pct']}%  в диапазоне {st.ctx['range_pos']:.0f}%",
           f"магнит L {st.magnet_long:.0f} / S {st.magnet_short:.0f}  ->  clear-path {st.clear_side}",
           "цвет=РОЛЬ: синий блок · оранж неэфф · жёлтый ликвид   (карта+фильтр+цель, НЕ прогноз)"]
    ax.text(0.012, 0.985, "\n".join(leg), transform=ax.transAxes, fontsize=8.5, color="#eee",
            va="top", ha="left", zorder=9, family="monospace",
            bbox=dict(boxstyle="round,pad=0.6", fc="#161b22", ec="#30363d"))
    ax.set_title(f"ОБЪЕДИНЁННЫЙ АНАЛИЗ BTC — наш контекст + ТА + зоны Вадима · {st.ts:%Y-%m-%d %H:%M} UTC",
                 fontsize=11, color="#eee")
    ax.set_xlim(start - 2, xr + 6); ax.grid(alpha=0.10, color="#888"); ax.tick_params(colors="#aaa", labelsize=7)
    xt = list(range(start, n, max((n - start) // 10, 1)))
    ax.set_xticks(xt); ax.set_xticklabels([df.index[t].strftime("%m-%d\n%H:%M") for t in xt])
    for sp in ax.spines.values():
        sp.set_color("#444")
    fig.tight_layout(); fig.savefig(out, dpi=120, facecolor=fig.get_facecolor()); plt.close(fig)


def coin_block(emoji, st):
    nb = sum(1 for z in st.zones if z.role == "block")
    ni = sum(1 for z in st.zones if z.role == "inefficiency")
    nl = sum(1 for z in st.zones if z.role == "liquidity")
    L = [f"<b>{emoji} ${st.price:,.0f}</b>",
         f"  • Контекст: <b>{st.ctx['word']}</b> ({st.ctx['mtf_up']}/3) · ATR {st.ctx['atr_pct']}% · в диапазоне {st.ctx['range_pos']:.0f}%",
         f"  • Зоны у цены: {len(st.zones)} (🎯{nb} блок · 🧲{ni} неэфф · ⛽{nl} ликвид)",
         f"  • Фильтр: магнит L {st.magnet_long:.0f} / S {st.magnet_short:.0f} → <b>чище {st.clear_side}</b>",
         f"  • Цель (realistic-TP): ↑ <code>{st.tp_up:,.0f}</code> / ↓ <code>{st.tp_down:,.0f}</code>"]
    if st.setups:
        s = st.setups[0]
        L.append(f"  • Сетап ТА: {s.kind} {s.direction} · {s.verdict}")
        L.append(f"    вход {s.entry:,.0f} · стоп {s.stop:,.0f} · цель {s.target:,.0f} (инвалид. {s.invalidation:,.0f})")
    else:
        L.append("  • Сетап ТА: нет свежего — ждать pullback в сторону тренда")
    return "\n".join(L)


def main():
    photo_only = "--photo-only" in sys.argv
    dry = "--dry" in sys.argv
    states = {}; pc_btc = None
    for sym, _ in COINS:
        print(f"[{sym}] analyze...", flush=True)
        df = AE._load_1m_csv(sym)
        df = df.loc[df.index >= df.index[-1] - pd.Timedelta(days=140)]
        pc = AE.precompute(df, symbol=sym)
        st = AE.analyze_at(pc, None)
        states[sym] = st
        if sym == "BTCUSDT":
            pc_btc = pc
    out = ROOT / "research" / "ta_laws" / "combined_report.png"
    render_btc(pc_btc, states["BTCUSDT"], out)
    print(f"saved {out}")

    ts = states["BTCUSDT"].ts
    L = [f"🧩 <b>ОБЪЕДИНЁННЫЙ АНАЛИЗ ПО МОНЕТАМ</b>",
         f"🕒 {ts:%Y-%m-%d %H:%M} UTC · стек: <b>наш контекст + ТА-модуль + зоны/законы Вадима</b>", ""]
    L.append("<i>Как читать:</i> КОНТЕКСТ(mtf/режим) → ЗОНЫ(канон Вадима+роли) → ФИЛЬТР(магнит/clear-path) → "
             "ЦЕЛЬ(realistic-TP) → ВЕРДИКТ. Направление=монетка; ценность = карта+фильтр+цель+инвалидация.")
    L.append("")
    for sym, emoji in COINS:
        L.append(coin_block(emoji, states[sym])); L.append("")
    L.append("📜 <b>Роли зон:</b> 🎯блок=реакция · 🧲неэфф=магнит-заполнить · ⛽ликвид=топливо/стопы. "
             "«чище LONG/SHORT» = меньше магнитов против хода (ФИЛЬТР отбора/сайзинга, не прогноз).")
    L.append("<i>Аналитика, не сигнал. Не рассылка — лично вам, админу.</i>")
    msg = "\n".join(L)

    if dry:
        print("\n" + msg + "\n\n[dry] не отправлено.")
        return
    env = load_env(); token = env.get("DASHBOARD_BOT_TOKEN")
    if not token:
        print("[!] DASHBOARD_BOT_TOKEN нет — отмена."); return
    base = f"https://api.telegram.org/bot{token}"
    chk = requests.get(f"{base}/getChat", params={"chat_id": ADMIN}, timeout=20).json()
    if not chk.get("ok"):
        print(f"[!] бот не видит чат {ADMIN}: {chk.get('description')} — нужен /start. Отмена."); return
    cap = (f"🧩 Объединённый анализ (контекст+ТА+зоны Вадима) · {ts:%m-%d %H:%M} UTC\n"
           f"BTC {states['BTCUSDT'].ctx['word']} · разбор по BTC/ETH/SOL ниже.")
    with open(out, "rb") as ph:
        rp = requests.post(f"{base}/sendPhoto", data={"chat_id": ADMIN, "caption": cap, "parse_mode": "HTML"},
                           files={"photo": ph}, timeout=60).json()
    print("sendPhoto ok" if rp.get("ok") else f"sendPhoto FAIL: {rp.get('description')}")
    if not photo_only:
        rm = requests.post(f"{base}/sendMessage",
                           data={"chat_id": ADMIN, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
                           timeout=30).json()
        print("sendMessage ok" if rm.get("ok") else f"sendMessage FAIL: {rm.get('description')}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
