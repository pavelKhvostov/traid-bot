"""etap_230 — СВЕЧНЫЕ дашборды TOTAL и TOTALES из НАСТОЯЩИХ данных TradingView
(CRYPTOCAP:TOTAL / CRYPTOCAP:TOTALES через CLI tradingview-mcp). Запасной источник —
market-cap basket из Binance (если TV недоступен). Прогоняем через day-type движок.

⚠️ TV-режим дёргает TradingView Desktop (кратко меняет символ графика и возвращает на BTC),
требует, чтобы TV был открыт. Нет TV → basket.
"""
import sys, json, time, subprocess
from pathlib import Path
import requests, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_225_dual_dashboard as D
import etap_227_live_dashboard_bot as G
import etap_229_market as MK
STATE = HERE.parent.parent / "state" / "live_dashboard"; STATE.mkdir(parents=True, exist_ok=True)
CLI = r"C:\Users\Andrew\tradingview-mcp\src\cli\index.js"
BASKET = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "LINK", "AVAX", "DOT", "SUI"]
EMO = {"TREND_UP": "🟢", "TREND_DOWN": "🔴", "ROTATION": "⚪", "FORMING": "⚫"}
DAY = {"TREND_UP": "тренд вверх", "TREND_DOWN": "тренд вниз", "ROTATION": "боковик", "FORMING": "формируется"}
ACT = {"TREND_UP": "лонги от опор на откате, не вдогонку",
       "TREND_DOWN": "шорты от сопротивлений, не лови дно",
       "ROTATION": "от границ к центру / пропуск", "FORMING": "ждать ясности"}


def T(x): return f"{x/1e12:.2f}T" if x >= 1e12 else f"{x/1e9:.0f}B"


def _cli(*a):
    return subprocess.run(["node", CLI, *a], capture_output=True, text=True, timeout=45)


def tv_fetch(tvsym, n=400):
    """Настоящие OHLCV из TV (через CLI), пересемпл в 1h. None при ошибке. Возврат графика на BTC."""
    try:
        _cli("chart", "symbol", tvsym); time.sleep(2.0)
        j = json.loads(_cli("ohlcv", "-n", str(n)).stdout)
        b = j.get("bars", [])
        if len(b) < 30:
            return None
        df = pd.DataFrame(b); df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")[["open", "high", "low", "close", "volume"]].astype(float)
        df = df.resample("1h").agg({"open": "first", "high": "max", "low": "min",
                                    "close": "last", "volume": "sum"}).dropna()
        return df if len(df) >= 30 else None
    except Exception as e:
        print("[tv_fetch]", tvsym, repr(e)[:120]); return None
    finally:
        try: _cli("chart", "symbol", "BINANCE:BTCUSDT")
        except Exception: pass


def basket_index(target):
    r = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                     params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 60, "page": 1},
                     timeout=25).json()
    mc = {c["symbol"].upper(): c["market_cap"] for c in r if c.get("market_cap")}
    w = {s: mc[s] for s in BASKET if s in mc}; tot = sum(w.values()); w = {s: v/tot for s, v in w.items()}
    dfs = {}
    for s in w:
        try: dfs[s] = D.fetch(s + "USDT")
        except Exception: pass
    common = None
    for df in dfs.values():
        common = df.index if common is None else common.intersection(df.index)
    out = pd.DataFrame(index=common)
    for col in ["open", "high", "low", "close"]:
        acc = None
        for s, df in dfs.items():
            d = df.loc[common]; term = w[s] * (d[col] / d["open"].iloc[0])
            acc = term if acc is None else acc + term
        out[col] = acc
    out["volume"] = sum(dfs[s].loc[common, "volume"] for s in dfs)
    f = target / out["close"].iloc[-1]
    for col in ["open", "high", "low", "close"]:
        out[col] *= f
    return out


def make(label, df, M, value, src):
    s = G.status(label, df, M)
    lines = [(p, T(p)) for p, _ in G.auto_levels(df)]
    path = D.dashboard(label, df, M, lines, "{:,.0f}")
    cap = (f"{EMO.get(s['state'], '⚫')} <b>{label}</b> · {DAY.get(s['state'], s['state'])} · ≈{T(value)}\n"
           f"<i>{s['day']}, {s['hour']:02d}:00 UTC · источник: {src}</i>\n\n"
           f"📊 Режим <b>{s['state']}</b> · сигнал <b>{s['call']}</b> ({s['mode']}) · P(вверх) <b>{s['p']:.0%}</b>\n"
           f"<b>Что делать:</b> {ACT.get(s['state'], '—')}\n\n"
           f"<i>состояние дня, не прогноз</i>")
    (STATE / f"{label}IDX.json").write_text(json.dumps({"caption": cap, "png": str(path)}, ensure_ascii=False), encoding="utf-8")
    return path, cap


def generate_total_totales():
    M = G.fit_model(); m = MK.fetch_market()
    res = {}
    for label, tvsym, val in [("TOTAL", "CRYPTOCAP:TOTAL", m["tot"]),
                              ("TOTALES", "CRYPTOCAP:TOTALES", m["totales"])]:
        df = tv_fetch(tvsym); src = "TradingView"
        if df is None:
            df = basket_index(val); src = "basket (TV недоступен)"
        res[label] = make(label, df, M, val, src)
    return res


if __name__ == "__main__":
    import re
    r = generate_total_totales()
    for lbl, (p, cap) in r.items():
        print("=" * 40, p.name); print(re.sub("<[^>]+>", "", cap))
