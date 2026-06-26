"""etap_227 — ЖИВОЙ режим: каждый час пересобирает дашборды BTC+ETH и шлёт в Telegram
АДМИНУ при СМЕНЕ режима/сигнала (без спама). Запускать по расписанию (schtasks/cron).

ТОЛЬКО бот дашбордов @new_edge_neiro_bot (DASHBOARD_BOT_TOKEN) → DASHBOARD_CHAT_ID.
НЕ продакшн-бот. Если токена/чата нет — НЕ шлёт, только генерит картинки.
"""
import os, sys, json, time
from pathlib import Path
import pandas as pd, requests
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    from dotenv import load_dotenv
    load_dotenv(HERE.parent.parent / ".env")
except Exception: pass
import etap_225_dual_dashboard as D
import etap_217_daytype_layer as L
# reversal.py лежит в корне репо (описательный детектор разворота дня/недели, etap_255)
sys.path.insert(0, str(HERE.parent.parent))
try:
    import reversal as RV
except Exception:
    RV = None

# Отдельный бот для дашбордов: @new_edge_neiro_bot (DASHBOARD_BOT_TOKEN из .env). НЕ продакшн.
# Если DASHBOARD_BOT_TOKEN не задан — скрипт НИЧЕГО не шлёт (только генерит картинки).
TOKEN = os.getenv("DASHBOARD_BOT_TOKEN", "")
NEURO_USERS = HERE.parent.parent / "state" / "neural_bot" / "users.json"
STATE = HERE.parent.parent / "state" / "live_dashboard"
STATE.mkdir(parents=True, exist_ok=True)
LAST = STATE / "last.json"
EMO = {"TREND_UP": "🟢", "TREND_DOWN": "🔴", "ROTATION": "⚪", "FORMING": "⚫"}


def expected_range(symbol, df):
    """Знаменатель gauge: Gauge 2.0 (range-модель, etap_237) c fallback на медиану.

    Возвращает (exp_pct, src): src='model' | 'median'."""
    try:
        import etap_237_gauge2 as G2
        e = G2.exp_range_pct(SRC[symbol])
        if e and e > 0:
            return float(e), "model"
    except Exception:
        pass
    daily = df.resample("1D").agg({"open": "first", "high": "max", "low": "min"})
    day = df.index.normalize().unique()[-1]
    exp = ((daily.high - daily.low) / daily.open).rolling(20).median().shift(1).reindex([pd.Timestamp(day)]).iloc[0]
    return (float(exp) if exp and exp > 0 else float("nan")), "median"


def status(symbol, df, M):
    day = df.index.normalize().unique()[-1]
    g = df[df.index.normalize() == day]
    dec, flips = L.daytype_nowcast(g, M)
    k, st, p, psm, mode, call = dec[-1]
    price = g["close"].iloc[-1]
    # сколько ожидаемого дневного хода уже выбрано (Gauge 2.0 + fallback)
    exp, exp_src = expected_range(symbol, df)
    gauge = float((g["high"].max() - g["low"].min()) / g["open"].iloc[0] / exp) if exp and exp > 0 else float("nan")
    # рваность утра: Kaufman efficiency ratio (волна 1, etap_245: AUC 0.735 vs
    # старый cross_early 0.631). Низкий ER → день чаще рваный. None → fallback на cross_early.
    praw = [d_[2] for d_ in dec]
    cross_early = sum(1 for i in range(1, min(len(praw), 12))
                      if (praw[i] - 0.5) * (praw[i - 1] - 0.5) < 0)
    try:
        import vol_features as VF
        eff = VF.morning_eff_ratio(SRC[symbol])
        eff_bucket = VF.eff_bucket(eff) if eff is not None else None
    except Exception:
        eff, eff_bucket = None, None
    # устойчивость состояния (P(trend-hold), etap_234 — таблица из signal_context)
    hold = None
    try:
        sys.path.insert(0, str(HERE.parent.parent))
        from signal_context import trend_hold_p
        if st in ("TREND_UP", "TREND_DOWN", "ROTATION"):
            hold = trend_hold_p(st, k)
    except Exception:
        pass
    # недельный контекст (product-6): позиция в диапазоне текущей недели (пн 00:00 UTC)
    wk_start = (pd.Timestamp(day) - pd.Timedelta(days=pd.Timestamp(day).dayofweek)).normalize()
    wk = df[df.index >= wk_start]
    wk_pos = float((price - wk["low"].min()) / (wk["high"].max() - wk["low"].min())) \
        if len(wk) and wk["high"].max() > wk["low"].min() else float("nan")
    pw = df[(df.index >= wk_start - pd.Timedelta(days=7)) & (df.index < wk_start)]
    pwh = float(pw["high"].max()) if len(pw) else float("nan")
    pwl = float(pw["low"].min()) if len(pw) else float("nan")
    # разворотная структура дня/недели (etap_255, описательно — без прогноза направления)
    day_rec = wk_rec = None
    if RV is not None:
        try:
            day_rec = RV.classify_day(g, developing=True)
            d1 = df.resample("1D").agg({"open": "first", "high": "max",
                                        "low": "min", "close": "last"}).dropna()
            wk_rec = RV.weekly_structure(d1)
        except Exception:
            pass
    return dict(symbol=symbol, day=str(pd.Timestamp(day).date()), state=st, p=p,
                call=call, mode=mode, flips=flips, price=price, hour=k, gauge=gauge,
                exp_pct=exp, exp_src=exp_src, cross_early=cross_early, hold=hold,
                wk_pos=wk_pos, pwh=pwh, pwl=pwl, eff=eff, eff_bucket=eff_bucket,
                day_rec=day_rec, wk_rec=wk_rec)


def _hm(p):
    return f"{p/1000:.1f}k" if p >= 10000 else f"{p:,.0f}"


def build_caption(sym, s, lines):
    st, p, price = s["state"], s["p"], s["price"]
    prices = [x for x, _ in lines]
    sup = "/".join(_hm(x) for x in sorted((x for x in prices if x < price), reverse=True)[:2]) or "опор"
    res = "/".join(_hm(x) for x in sorted(x for x in prices if x > price)[:2]) or "сопротивлений"
    DAY = {"TREND_UP": ("🟢", "трендовый день ВВЕРХ"), "TREND_DOWN": ("🔴", "трендовый день ВНИЗ"),
           "ROTATION": ("⚪", "боковик (ротация)"), "FORMING": ("⚫", "день ещё формируется")}
    emo, phrase = DAY.get(st, ("⚫", st))
    action = {
        "TREND_UP": f"торгуй ПО тренду — лонги от опор {sup} на откате, не вдогонку. Шорт сегодня против режима.",
        "TREND_DOWN": f"шорти откаты к {res}, не лови дно. Лонг сегодня против режима.",
        "ROTATION": "работай от границ к центру: продавай у верха, покупай у низа, цели мелкие. Или пропусти день.",
        "FORMING": "рано — жди, пока определится режим (первые часы дня).",
    }.get(st, "жди ясности.")
    p_ph = "склонность к зелёному" if p >= 0.65 else ("склонность к красному" if p <= 0.35 else "пока ~50/50, неопределённо")
    g = s.get("gauge", float("nan"))
    if g != g:
        g_ph = ""
    elif g >= 1.0:
        g_ph = "📈 Цена уже прошла <b>весь обычный дневной путь</b> — заходить вдогонку поздно, лучше ждать отката\n"
    elif g >= 0.5:
        g_ph = "📈 Цена прошла <b>больше половины</b> обычного дневного хода — движение в разгаре\n"
    else:
        g_ph = "📈 Цена прошла <b>лишь часть</b> обычного дневного хода — запас для движения ещё есть\n"
    stab = "сигнал устойчивый" if s["flips"] <= 1 else f"день рваный ({s['flips']} смен) — осторожно"
    # ожидаемый ход дня (Gauge 2.0): источник модель/медиана
    exp = s.get("exp_pct")
    exp_ph = (f"📏 Ожидаемый ход дня ~<b>{exp*100:.1f}%</b>"
              f"{' (прогноз-модель)' if s.get('exp_src') == 'model' else ''}\n") if exp and exp == exp else ""
    # устойчивость состояния (etap_234)
    hold = s.get("hold")
    if hold is None:
        hold_ph = ""
    elif st == "ROTATION":
        hold_ph = f"⏳ Боковик доживает до конца дня в <b>{hold:.0%}</b> случаев (в {1-hold:.0%} — уйдёт в тренд)\n"
    else:
        hold_ph = f"⏳ Такой тренд к этому часу доживает до конца дня в <b>{hold:.0%}</b> случаев\n"
    # предиктивное предупреждение о рваности (волна 1, etap_245 eff_ratio AUC 0.735):
    # низкий утренний efficiency ratio → день чаще рваный. Fallback на cross_early.
    eb = s.get("eff_bucket")
    if eb in ("очень рваное", "рваное"):
        chop_ph = (f"⚠️ Утро <b>{eb}</b> (мечется без направления) — исторически такой день "
                   f"чаще остаётся рваным (~60% при самом рваном утре). Сигналам сегодня меньше веса.\n")
    elif eb in ("очень гладкое", "гладкое"):
        chop_ph = f"✅ Утро <b>{eb}</b> (идёт направленно) — день обычно держит ход (рваным лишь ~11%).\n"
    elif eb is None and s.get("cross_early", 0) >= 2 and s["hour"] <= 14:
        chop_ph = ("⚠️ Утро рваное — исторически в ~половине таких дней сигнал ещё сменится. "
                   "Сигналам сегодня меньше веса.\n")
    else:
        chop_ph = ""
    # недельный контекст (product-6)
    wp = s.get("wk_pos")
    if wp is None or wp != wp:
        week_ph = ""
    else:
        third = "верхней трети" if wp >= 0.67 else ("нижней трети" if wp <= 0.33 else "середине")
        pwh, pwl = s.get("pwh"), s.get("pwl")
        pw_ph = f" · прошлая неделя {_hm(pwl)}–{_hm(pwh)}" if pwh and pwh == pwh else ""
        week_ph = f"📅 Неделя: цена в {third} недельного диапазона{pw_ph}\n"
    # РАЗВОРОТНАЯ СТРУКТУРА (etap_255) — описательно, направление дальше = монетка
    rev_lines = []
    if RV is not None:
        dt = RV.describe_intraday(s.get("day_rec")) if s.get("day_rec") else ""
        wt = RV.describe_weekly(s.get("wk_rec")) if s.get("wk_rec") else ""
        if dt:
            rev_lines.append(dt)
        if wt:
            rev_lines.append(wt)
    rev_ph = ("".join(x + "\n" for x in rev_lines)) if rev_lines else ""
    return (f"{emo} <b>{sym}</b> — {phrase}\n"
            f"<i>{s['day']}, {s['hour']:02d}:00 UTC · цена {price:,.0f}</i>\n\n"
            f"📊 Режим <b>{st}</b> · сигнал <b>{s['call']}</b> ({s['mode']})\n"
            f"🎯 P(день зелёный) <b>{p:.0%}</b> — {p_ph}\n"
            f"{hold_ph}"
            f"{exp_ph}"
            f"{g_ph}"
            f"{chop_ph}"
            f"{week_ph}"
            f"{rev_ph}"
            f"{s.get('accuracy_ph', '')}"
            f"🔁 Смен мнения: {s['flips']} — {stab}\n\n"
            f"<b>Что делать:</b> {action}\n\n"
            f"<i>Это состояние дня, а не прогноз будущего.</i>")


def recipients():
    """Адресаты дашбордов/алертов/брифинга (@new_edge_neiro_bot).
    1) согласованный список state/live_dashboard/users.json (приоритет,
       утверждён пользователем 2026-06-12: Андрей + Павел Хвостов; Данил
       добавится после /start), иначе
    2) явный DASHBOARD_CHAT_ID из .env, иначе
    3) /start-подписчики тестового нейро-бота. Пусто = никому."""
    approved = STATE / "users.json"
    if approved.exists():
        try:
            data = json.loads(approved.read_text(encoding="utf-8"))
            ids = [str(u["id"]) if isinstance(u, dict) else str(u) for u in data]
            if ids:
                return ids
        except Exception:
            pass
    explicit = os.getenv("DASHBOARD_CHAT_ID", "").strip()
    if explicit:
        return [explicit]
    if not NEURO_USERS.exists():
        return []
    try:
        data = json.loads(NEURO_USERS.read_text(encoding="utf-8"))
    except Exception:
        return []
    ids = []
    for u in (data if isinstance(data, list) else []):
        ids.append(u["id"] if isinstance(u, dict) else u)
    return ids


# постоянная нижняя клавиатура — цепляем к КАЖДОМУ сообщению, чтобы всегда была видна
KB = json.dumps({"keyboard": [["₿ BTC", "Ξ ETH", "◎ SOL"], ["🌐 ТОТАЛ (рынок)", "ℹ️ Справка"]],
                 "resize_keyboard": True, "is_persistent": True})


def send_photo(path, caption):
    if not TOKEN:
        print("[live] DASHBOARD_BOT_TOKEN не задан — НЕ шлю, только сохранил картинку"); return False
    rcpt = recipients()
    if not rcpt:
        print("[live] нет подписчиков @test_neyro_traid_bot (нажми /start у бота) — не шлю"); return False
    ok_any = False
    for chat in rcpt:
        with open(path, "rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                              data={"chat_id": chat, "caption": caption, "parse_mode": "HTML", "reply_markup": KB},
                              files={"photo": f}, timeout=60)
        ok = r.json().get("ok", False); ok_any = ok_any or ok
        print(f"[live] send {path.name} → {chat}: {'OK' if ok else r.text[:160]}")
    return ok_any


def send_text(text):
    if not TOKEN:
        print("[live] DASHBOARD_BOT_TOKEN не задан — текст не шлю"); return False
    ok_any = False
    for chat in recipients():
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                "reply_markup": KB}, timeout=30)
        ok = r.json().get("ok", False); ok_any = ok_any or ok
        print(f"[live] send text → {chat}: {'OK' if ok else r.text[:160]}")
    return ok_any


SYMBOLS = ["BTC", "ETH", "SOL"]
SRC = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


def fit_model():
    """Движок day-type обучается на исторических BTC (локальный CSV), применяется ко всем."""
    btc = pd.read_csv(D.BTC, index_col=0, parse_dates=True)
    if btc.index.tz is None: btc.index = btc.index.tz_localize("UTC")
    return L.fit_per_hour(L.build(btc).replace([float("inf"), float("-inf")], None).fillna(0.0))


def auto_levels(df, n=3):
    """СВЕЖИЕ зоны (пересчёт каждый прогон): объёмный профиль POC/VAH/VAL за 45д +
    ближайшие фрактальные S/R. Заменяет захардкоженные LINES (устаревали неделями)."""
    price = float(df["close"].iloc[-1])
    out = []
    try:
        sys.path.insert(0, str(HERE.parent.parent))
        from signal_context import volume_profile, swing_levels
        recent = df[df.index >= df.index[-1] - pd.Timedelta(days=45)]
        vp = volume_profile(recent)
        if vp:
            poc, vah, val = vp
            out += [(poc, "POC"), (vah, "VAH"), (val, "VAL")]
        d = df.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
        highs, lows = swing_levels(d, n=2, lookback=60)
        for h in sorted(x for x in highs if x > price * 1.002)[:1]:
            out.append((h, "сопротивление"))
        for l in sorted((x for x in lows if x < price * 0.998), reverse=True)[:1]:
            out.append((l, "опора"))
    except Exception:
        pass
    if not out:                                  # fallback — фрактальные дневные swings
        d = df.resample("1D").agg({"high": "max", "low": "min"}).dropna()
        H, Lo = d["high"].values, d["low"].values
        sh = [H[i] for i in range(n, len(d)-n) if H[i] == max(H[i-n:i+n+1])]
        sl = [Lo[i] for i in range(n, len(d)-n) if Lo[i] == min(Lo[i-n:i+n+1])]
        out = ([(x, "сопротивление") for x in sorted({round(x, 2) for x in sh if x > price})[:2]] +
               [(x, "опора") for x in sorted({round(x, 2) for x in sl if x < price}, reverse=True)[:2]])
    # дедуп близких уровней (в пределах 0.3%)
    out = sorted(out, key=lambda t: t[0])
    dedup = []
    for v, lab in out:
        if not dedup or abs(v - dedup[-1][0]) / price > 0.003:
            dedup.append((v, lab))
    return dedup or [(price, "цена")]


# Захардкоженные уровни УДАЛЕНЫ (устаревали): зоны теперь всегда свежие из auto_levels.
# MANUAL_LINES — опциональный ручной override (пусто = всегда авто).
MANUAL_LINES: dict = {}


def lines_for(sym, df):
    return MANUAL_LINES.get(sym) or auto_levels(df)


LEDGER = STATE / "ledger.csv"


def ledger_update(sym, df, s):
    """product-7: pred-vs-fact леджер. Раз в день пишем прогноз хода (exp_pct),
    на следующий день заполняем факт. Самоконтроль точности — постоянный self-critique."""
    import csv
    rows = []
    if LEDGER.exists():
        with open(LEDGER, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    today = s["day"]
    daily = df.resample("1D").agg({"high": "max", "low": "min", "close": "last"})
    changed = False
    for r in rows:  # дозаполняем факты по закрытым дням
        if r["sym"] == sym and not r.get("real_pct"):
            d0 = pd.Timestamp(r["date"], tz="UTC")
            if d0.normalize() < pd.Timestamp(today, tz="UTC"):
                try:
                    real = (daily.loc[d0, "high"] - daily.loc[d0, "low"]) / daily["close"].shift(1).loc[d0]
                    r["real_pct"] = f"{float(real):.5f}"; changed = True
                except Exception:
                    pass
    if not any(r["sym"] == sym and r["date"] == today for r in rows):
        exp = s.get("exp_pct")
        if exp and exp == exp:
            rows.append({"date": today, "sym": sym, "exp_pct": f"{exp:.5f}",
                         "exp_src": s.get("exp_src", ""), "real_pct": ""})
            changed = True
    if changed:
        with open(LEDGER, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "sym", "exp_pct", "exp_src", "real_pct"])
            w.writeheader(); w.writerows(rows)
    # точность за 30 заполненных дней → строка для caption (или "")
    filled = [r for r in rows if r["sym"] == sym and r.get("real_pct")][-30:]
    if len(filled) >= 10:
        ratios = [float(r["real_pct"]) / float(r["exp_pct"]) for r in filled if float(r["exp_pct"]) > 0]
        med = sorted(ratios)[len(ratios) // 2]
        return f"📐 Точность прогноза хода (30д): факт/прогноз ≈ {med:.2f}\n"
    return ""


def generate(sym, df, M):
    """Построить дашборд + подпись и ЗАКЭШИРОВАТЬ (для кнопок). Возврат (status, png, caption)."""
    s = status(sym, df, M)
    try:
        s["accuracy_ph"] = ledger_update(sym, df, s)
    except Exception:
        s["accuracy_ph"] = ""
    lines = lines_for(sym, df)
    path = D.dashboard(sym, df, M, lines, "{:,.0f}",
                       exp_pct=s.get("exp_pct") if s.get("exp_src") == "model" else None,
                       rev_day=s.get("day_rec"))
    cap = build_caption(sym, s, lines)
    (STATE / f"{sym}.json").write_text(json.dumps(
        {"caption": cap, "png": str(path), "hour": s["hour"], "day": s["day"],
         "state": s["state"], "call": s["call"], "p": s["p"]}, ensure_ascii=False), encoding="utf-8")
    return s, path, cap


SETUPS = STATE / "active_setups.json"


def check_setups(dfs, stats):
    """product-4: алерт смены типа дня против ОТКРЫТОГО сетапа (контекст, не команда).

    Источник позиций: state/sent_signals.json (payload сигналов S111/S112/S113/S116
    за последние 7 дней с entry/sl). Резолв на 1h: SL/TP-кросс → сетап закрыт.
    Алерт — только на ПЕРЕХОД в конфликт (LONG×TREND_DOWN / SHORT×TREND_UP)."""
    sent_p = HERE.parent.parent / "state" / "sent_signals.json"
    if not sent_p.exists():
        return
    try:
        sent = json.loads(sent_p.read_text(encoding="utf-8"))
    except Exception:
        return
    mem = json.loads(SETUPS.read_text(encoding="utf-8")) if SETUPS.exists() else {}
    now = pd.Timestamp.now(tz="UTC")
    for key, p in sent.items():
        if not isinstance(p, dict) or p.get("prefill") or "entry" not in p:
            continue
        t = pd.Timestamp(p.get("signal_time", ""))
        if t.tz is None: t = t.tz_localize("UTC")
        if now - t > pd.Timedelta(days=7):
            continue
        sym_full = p.get("symbol", ""); sym = sym_full.replace("USDT", "")
        if sym not in dfs:
            continue
        df = dfs[sym]; direction = p.get("direction")
        entry, sl = float(p["entry"]), float(p["sl"])
        risk = abs(entry - sl); rr = 2.2
        tp = entry + risk * rr if direction == "LONG" else entry - risk * rr
        fw = df[df.index > t]
        closed = False
        for _, c in fw.iterrows():
            if direction == "LONG" and (c["low"] <= sl or c["high"] >= tp): closed = True; break
            if direction == "SHORT" and (c["high"] >= sl or c["low"] <= tp): closed = True; break
        if closed:
            mem.pop(key, None); continue
        st = stats.get(sym, {}).get("state", "")
        conflict = (direction == "LONG" and st == "TREND_DOWN") or \
                   (direction == "SHORT" and st == "TREND_UP")
        was = mem.get(key)
        if conflict and was != st:
            send_text(f"⚠️ <b>{sym}</b>: у тебя активный сетап <b>{direction}</b> "
                      f"(вход {entry:,.2f}), а день перешёл в {EMO.get(st,'')} <b>{st}</b>.\n"
                      f"Это контекст, не команда: встречный день = хуже шансы дойти до цели. "
                      f"Подтяни стоп / уменьшись, если без подтверждения.")
        mem[key] = st
    SETUPS.write_text(json.dumps(mem, ensure_ascii=False), encoding="utf-8")


def main():
    M = fit_model()
    last = json.loads(LAST.read_text()) if LAST.exists() else {}
    dfs, stats = {}, {}
    for sym in SYMBOLS:
        try:
            df = D.fetch(SRC[sym])                       # все 3 монеты — живьём
            s, path, cap = generate(sym, df, M)          # всегда кэшируем (для кнопок)
            dfs[sym], stats[sym] = df, s
        except Exception as e:
            print(f"{sym}: ошибка {e!r}"); continue
        key = f"{s['state']}/{s['call']}"
        changed = last.get(sym) != key
        print(f"{sym}: {s['state']}/{s['call']} P={s['p']:.2f} (было {last.get(sym)}) → {'СМЕНА' if changed else 'без изменений'}")
        if changed: send_photo(path, cap)                # авто-пуш только при смене
        last[sym] = key
    try:
        check_setups(dfs, stats)                         # product-4: алерты по сетапам
    except Exception as e:
        print("setups: ошибка", repr(e))
    # product-5: утренний брифинг — один раз в день, в первые часы UTC
    try:
        today = pd.Timestamp.now(tz="UTC").normalize().date().isoformat()
        hr = pd.Timestamp.now(tz="UTC").hour
        if stats and hr <= 2 and last.get("brief_day") != today:
            parts = [f"🌅 <b>Утренний брифинг {today}</b> (ожидания дня, не прогноз направления)"]
            for sym, s in stats.items():
                exp = s.get("exp_pct")
                exp_t = f"~{exp*100:.1f}%" + (" (модель)" if s.get("exp_src") == "model" else "") \
                    if exp and exp == exp else "н/д"
                lv = lines_for(sym, dfs[sym])
                lv_t = " · ".join(f"{lab} {_hm(x)}" for x, lab in lv[:3])
                wp = s.get("wk_pos")
                wp_t = f", неделя {wp:.0%}" if wp and wp == wp else ""
                parts.append(f"{EMO.get(s['state'],'')} <b>{sym}</b> {s['price']:,.0f}: "
                             f"ожидаемый ход {exp_t}{wp_t}\n   уровни: {lv_t}")
            send_text("\n".join(parts))
            last["brief_day"] = today
    except Exception as e:
        print("brief: ошибка", repr(e))
    try:
        import etap_229_market as MK
        MK.generate_market(); print("MARKET: кэш обновлён")
    except Exception as e:
        print("MARKET: ошибка", repr(e))
    # TOTAL/TOTALES из TV НЕ тянем здесь (это дёргало бы график каждый час) —
    # их генерит бот кнопок по нажатию (etap_228), свежими на момент запроса.
    # Магнитуда (ADMIN-only reversal 8h/12h) — за флагом MAGNITUDE_ENABLED. Шлёт ТОЛЬКО админу,
    # мимо recipients() (там Павел). Первый запуск = prefill silent. Изолировано в magnitude_hourly.py.
    if os.getenv("MAGNITUDE_ENABLED", "").lower() in ("1", "true", "yes", "on"):
        try:
            from magnitude_hourly import magnitude_check
            magnitude_check()
        except Exception as e:
            print("magnitude: ошибка", repr(e))
    LAST.write_text(json.dumps(last, ensure_ascii=False))
    print("done.")


if __name__ == "__main__":
    main()
