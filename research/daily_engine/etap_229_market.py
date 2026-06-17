"""etap_229 — рыночная карта TOTAL / TOTALES + классные метрики (CoinGecko + Fear&Greed).
Сдвоенная картинка (TOTAL сверху / TOTALES снизу) + метрики + «чтение». Бесплатные API, без ключа.
"""
import sys, json
from pathlib import Path
import requests
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
OUT = HERE / "output"; OUT.mkdir(exist_ok=True)
STATE = HERE.parent.parent / "state" / "live_dashboard"; STATE.mkdir(parents=True, exist_ok=True)
STABLES = ["usdt", "usdc", "dai", "fdusd", "tusd", "usde", "usds"]


def T(x): return f"{x/1e12:.2f}T" if x >= 1e12 else f"{x/1e9:.0f}B"


def fetch_market():
    g = requests.get("https://api.coingecko.com/api/v3/global", timeout=25).json()["data"]
    tot = g["total_market_cap"]["usd"]; chg = g["market_cap_change_percentage_24h_usd"]
    vol = g["total_volume"]["usd"]; mcp = g["market_cap_percentage"]
    btc_d = mcp.get("btc", 0); eth_d = mcp.get("eth", 0)
    stbl = sum(mcp.get(s, 0) for s in STABLES)
    try:
        f = requests.get("https://api.alternative.me/fng/", timeout=20).json()["data"][0]
        fng, fcls = int(f["value"]), f["value_classification"]
    except Exception:
        fng, fcls = -1, "n/a"
    return dict(tot=tot, chg=chg, vol=vol, btc_d=btc_d, eth_d=eth_d, stbl=stbl,
                totales=tot*(1-stbl/100), total2=tot*(1-btc_d/100),
                total3=tot*(1-(btc_d+eth_d)/100), fng=fng, fcls=fcls)


def read(m):
    p = []
    if m["btc_d"] >= 55: p.append("доминация BTC высокая → деньги в защите/BTC, альты под давлением")
    elif m["btc_d"] <= 48: p.append("доминация BTC низкая → альты в силе (режим альтсезона)")
    else: p.append("доминация BTC средняя → баланс BTC/альты")
    if 0 <= m["fng"] <= 25: p.append("крайний страх — часто разворотная зона (контр-настроение)")
    elif m["fng"] >= 75: p.append("жадность — осторожно с погоней за лонгами")
    elif m["fng"] >= 0: p.append("настроение нейтральное")
    return "; ".join(p) + "."


def card(m):
    fig = plt.figure(figsize=(10, 8)); fig.patch.set_facecolor("#0e1117")
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    grn, red, wht, gry = "#26a69a", "#ef5350", "#e6e6e6", "#9aa0a6"
    col = grn if m["chg"] >= 0 else red
    ax.text(0.5, 0.95, "РЫНОК КРИПТЫ  ·  TOTAL / TOTALES", color=wht, fontsize=20, weight="bold", ha="center")
    # TOTAL
    ax.add_patch(plt.Rectangle((0.05, 0.66), 0.9, 0.17, color="#1b2230"))
    ax.text(0.08, 0.785, "TOTAL", color=gry, fontsize=14, weight="bold")
    ax.text(0.08, 0.70, "вся капитализация крипты", color=gry, fontsize=11)
    ax.text(0.92, 0.775, T(m["tot"]), color=wht, fontsize=30, weight="bold", ha="right")
    ax.text(0.92, 0.70, f"24ч {m['chg']:+.2f}%", color=col, fontsize=14, weight="bold", ha="right")
    # TOTALES
    ax.add_patch(plt.Rectangle((0.05, 0.46), 0.9, 0.17, color="#1b2230"))
    ax.text(0.08, 0.585, "TOTALES", color=gry, fontsize=14, weight="bold")
    ax.text(0.08, 0.50, "без стейблкоинов = рисковая часть рынка", color=gry, fontsize=11)
    ax.text(0.92, 0.575, T(m["totales"]), color=wht, fontsize=30, weight="bold", ha="right")
    ax.text(0.92, 0.50, f"стейблы {m['stbl']:.1f}%", color=gry, fontsize=12, ha="right")
    # метрики
    yy = 0.37
    cells = [("BTC.D", f"{m['btc_d']:.1f}%"), ("ETH.D", f"{m['eth_d']:.1f}%"),
             ("TOTAL2 (без BTC)", T(m["total2"])), ("TOTAL3 (без BTC+ETH)", T(m["total3"])),
             ("Объём 24ч", T(m["vol"])), ("Fear & Greed", f"{m['fng']} · {m['fcls']}" if m['fng'] >= 0 else "n/a")]
    for i, (k, v) in enumerate(cells):
        x = 0.08 + (i % 3) * 0.30; y = yy - (i // 3) * 0.10
        ax.text(x, y, k, color=gry, fontsize=11)
        ax.text(x, y-0.04, v, color=wht, fontsize=15, weight="bold")
    # чтение
    ax.add_patch(plt.Rectangle((0.05, 0.05), 0.9, 0.10, color="#10261f"))
    ax.text(0.08, 0.115, "ЧТЕНИЕ", color=grn, fontsize=11, weight="bold")
    ax.text(0.08, 0.075, read(m), color=wht, fontsize=11.5, wrap=True)
    p = OUT / "etap_229_market.png"; fig.savefig(p, dpi=115, facecolor=fig.get_facecolor())
    plt.close(fig); return p


def caption(m):
    arr = "📈" if m["chg"] >= 0 else "📉"
    gap = m["tot"] - m["totales"]
    return (f"🌐 <b>Рынок крипты</b> — обзор\n\n"
            f"{arr} <b>TOTAL</b> (вся капа): <b>{T(m['tot'])}</b> · 24ч <b>{m['chg']:+.2f}%</b>\n"
            f"└ весь крипторынок; растёт = деньги входят\n"
            f"💠 <b>TOTALES</b> (без стейблов): <b>{T(m['totales'])}</b>\n"
            f"└ рисковая часть рынка — чистый аппетит к риску\n\n"
            f"📊 BTC.D <b>{m['btc_d']:.1f}%</b> · ETH.D <b>{m['eth_d']:.1f}%</b> · стейблы <b>{m['stbl']:.1f}%</b> (≈кэш {T(gap)})\n"
            f"🪙 Альты: TOTAL2 <b>{T(m['total2'])}</b> · TOTAL3 <b>{T(m['total3'])}</b>\n"
            f"😱 Fear &amp; Greed: <b>{m['fng']} — {m['fcls']}</b>\n\n"
            f"<b>Чтение:</b> {read(m)}\n\n"
            f"<i>Контекст рынка, а не прогноз.</i>")


def generate_market():
    m = fetch_market()
    p = card(m); cap = caption(m)
    (STATE / "MARKET.json").write_text(json.dumps({"caption": cap, "png": str(p)}, ensure_ascii=False), encoding="utf-8")
    return p, cap


if __name__ == "__main__":
    import re
    p, cap = generate_market()
    print("saved:", p.name)
    print(re.sub("<[^>]+>", "", cap))
