"""Этап 82: качественный PDF-отчёт по стратегиям 1.1.4 и 1.1.5
+ практическое руководство по торговле.

Структура:
  1. Краткое содержание + ключевые цифры
  2. Stage 1: Что такое SMC-каскад (общая идея)
  3. Stage 2: Стратегия 1.1.4 — анкер FVG
  4. Stage 3: Стратегия 1.1.5 — анкер фрактал+sweep
  5. Stage 4: Как торговать руками (пошагово)
  6. Stage 5: Управление риском
  7. Stage 6: Аудит и известные баги
  8. Stage 7: Ограничения и FAQ
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                  TableStyle, PageBreak)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Italic", "C:/Windows/Fonts/ariali.ttf"))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic")
# Courier New поддерживает кириллицу (в отличие от built-in Courier)
pdfmetrics.registerFont(TTFont("CourierNew", "C:/Windows/Fonts/cour.ttf"))
pdfmetrics.registerFont(TTFont("CourierNew-Bold", "C:/Windows/Fonts/courbd.ttf"))
pdfmetrics.registerFontFamily("CourierNew", normal="CourierNew", bold="CourierNew-Bold")

OUTPUT_PDF = _Path("research/elements_study/output/etap82_strategies_1_1_4_and_1_1_5_full_guide.pdf")
CSV_114 = _Path("research/elements_study/output/etap74_BFJK_fixed_portfolio.csv")
CSV_115 = _Path("research/elements_study/output/etap81_1_1_5_hifreq_portfolio.csv")

COLOR_PRIMARY = HexColor("#1f4e79")
COLOR_ACCENT = HexColor("#2e7d32")
COLOR_WARN = HexColor("#c62828")
COLOR_LIGHT = HexColor("#e3f2fd")
COLOR_GREY = HexColor("#757575")
COLOR_TABLE_HEADER = HexColor("#1f4e79")
COLOR_TABLE_ALT = HexColor("#f5f5f5")
COLOR_HL = HexColor("#fff9c4")


def styles():
    s = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=s["Title"], fontName="Arial-Bold",
            fontSize=22, leading=28, textColor=COLOR_PRIMARY, alignment=TA_CENTER, spaceAfter=10),
        "subtitle": ParagraphStyle("subtitle", parent=s["Normal"], fontName="Arial-Italic",
            fontSize=12, leading=16, textColor=COLOR_GREY, alignment=TA_CENTER, spaceAfter=24),
        "h1": ParagraphStyle("h1", parent=s["Heading1"], fontName="Arial-Bold",
            fontSize=18, leading=22, textColor=COLOR_PRIMARY, spaceBefore=18, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=s["Heading2"], fontName="Arial-Bold",
            fontSize=14, leading=18, textColor=COLOR_PRIMARY, spaceBefore=14, spaceAfter=8),
        "h3": ParagraphStyle("h3", parent=s["Heading3"], fontName="Arial-Bold",
            fontSize=12, leading=15, textColor=black, spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("body", parent=s["Normal"], fontName="Arial",
            fontSize=10.5, leading=14, alignment=TA_JUSTIFY, spaceAfter=6),
        "bullet": ParagraphStyle("bullet", parent=s["Normal"], fontName="Arial",
            fontSize=10.5, leading=14, leftIndent=18, bulletIndent=8, spaceAfter=4),
        "mono": ParagraphStyle("mono", parent=s["Code"], fontName="CourierNew", fontSize=9,
            leading=12, backColor=COLOR_LIGHT, leftIndent=10, rightIndent=10, spaceBefore=6, spaceAfter=6),
        "caption": ParagraphStyle("caption", parent=s["Normal"], fontName="Arial-Italic",
            fontSize=9, leading=11, textColor=COLOR_GREY, alignment=TA_CENTER, spaceAfter=12),
        "warn": ParagraphStyle("warn", parent=s["Normal"], fontName="Arial-Bold",
            fontSize=10.5, leading=14, textColor=COLOR_WARN, spaceAfter=6),
        "ok": ParagraphStyle("ok", parent=s["Normal"], fontName="Arial-Bold",
            fontSize=10.5, leading=14, textColor=COLOR_ACCENT, spaceAfter=6),
        "step": ParagraphStyle("step", parent=s["Normal"], fontName="Arial",
            fontSize=11, leading=15, leftIndent=24, bulletIndent=0, spaceAfter=8),
    }


def table(data, col_widths=None, header=True, alt=True, hl=None, font_size=9.5):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Arial"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, grey),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER),
                   ("TEXTCOLOR", (0, 0), (-1, 0), white),
                   ("FONTNAME", (0, 0), (-1, 0), "Arial-Bold"),
                   ("ALIGN", (0, 0), (-1, 0), "CENTER")]
    if alt:
        for r in range(1, len(data)):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r), COLOR_TABLE_ALT))
    if hl:
        for r in hl:
            style.append(("BACKGROUND", (0, r), (-1, r), COLOR_HL))
            style.append(("FONTNAME", (0, r), (-1, r), "Arial-Bold"))
    t.setStyle(TableStyle(style))
    return t


def build():
    S = styles()
    story = []

    # ===== TITLE =====
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("Стратегии SMC-каскада 1.1.4 и 1.1.5", S["title"]))
    story.append(Paragraph("Полное руководство: суть, бэктест и торговля на BTCUSDT",
                            S["subtitle"]))
    story.append(Spacer(1, 0.5*cm))

    summary_data = [
        ["Метрика", "1.1.4 BFJK", "1.1.5 hi-freq", "1.1.5 hi-quality"],
        ["Анкер L1", "FVG-1d/12h", "Фрактал-12h+sweep", "Фрактал-12h+sweep"],
        ["Доп. фильтр", "—", "Hull-1h(L49) aligned", "Hull-12h(L160) aligned"],
        ["Сделок closed", "115", "242", "113"],
        ["Win Rate", "64.3%", "47.9%", "58.4%"],
        ["Total R", "+107.0", "+106.0", "+85.0"],
        ["Avg R / trade", "+0.93", "+0.44", "+0.75"],
        ["Плохих лет / 7", "1 (2025)", "0", "1"],
        ["Частота", "1 / 13 дн", "1 / 9 дн", "1 / 20 дн"],
        ["Стиль", "Снайпер", "Свинг", "Премиум"],
    ]
    story.append(table(summary_data, col_widths=[4.5*cm, 3.5*cm, 3.5*cm, 3.5*cm],
                        hl=[4, 5, 7]))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("BTCUSDT · 01.2020 — 04.2026 · 1m данные · все RR=2.0",
                            S["caption"]))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Дата отчёта: 11 мая 2026 г.", S["caption"]))
    story.append(PageBreak())

    # ===== 1. КРАТКОЕ СОДЕРЖАНИЕ =====
    story.append(Paragraph("1. Что вы получите из этого отчёта", S["h1"]))
    story.append(Paragraph(
        "Три проверенные на 6.3 годах истории BTCUSDT стратегии алгоритмической "
        "торговли криптовалютой по методологии Smart Money Concepts (SMC). Каждая — "
        "вложенный каскад зон от старшего таймфрейма к младшему, с фиксированным "
        "соотношением риск/прибыль 1 : 2.", S["body"]))
    story.append(Paragraph(
        "Стратегии прошли forensic-аудит на 10 категорий потенциальных багов, "
        "включая один найденный и исправленный lookahead bug в индикаторных "
        "фильтрах. Все цифры в отчёте — после фиксов, без inflation.", S["body"]))

    story.append(Paragraph("Чем стратегии различаются:", S["h3"]))
    diff_data = [
        ["", "1.1.4 BFJK", "1.1.5"],
        ["Что запускает сетап", "Образование FVG-d/12h", "Sweep фрактала-12h"],
        ["Сколько сделок в год", "18", "38"],
        ["WR (средний)", "64%", "48%"],
        ["Каждая сделка приносит", "≈ +0.93R", "≈ +0.44R"],
        ["Просадка по годам", "1 плохой год (2025)", "0 плохих лет"],
        ["Когда лучше", "Качество > частоты", "Стабильность > пика"],
    ]
    story.append(table(diff_data, col_widths=[5*cm, 5*cm, 5*cm]))

    # ===== 2. ОБЩАЯ ИДЕЯ КАСКАДА =====
    story.append(Paragraph("2. Общая идея SMC-каскада", S["h1"]))
    story.append(Paragraph(
        "Обе стратегии строятся по одному принципу — <b>многоступенчатый каскад</b>:",
        S["body"]))

    story.append(Paragraph("L1 → L2 → L3 → L4", S["h2"]))
    cascade_data = [
        ["Уровень", "Что это", "Назначение"],
        ["L1", "Макро-зона (старший ТФ)", "Контекст направления, зона интереса"],
        ["L2", "Промежуточная зона", "Подтверждение макро-кластером (объём, премиум/дискаунт)"],
        ["L3", "Триггер (младший ТФ)", "Свежий сигнал разворота на меньшем TF"],
        ["L4", "Точка входа (микро)", "Конкретная зона FVG-15m для ордера"],
    ]
    story.append(table(cascade_data, col_widths=[2*cm, 5*cm, 9*cm]))
    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "<b>Главная идея:</b> чем больше иерархических уровней совпадает в одной "
        "цене, тем выше вероятность реакции. Сделка открывается только когда "
        "цена дошла до точки, где сошлись 4 независимых сигнала.", S["body"]))

    story.append(Paragraph("Что общего между 1.1.4 и 1.1.5", S["h2"]))
    common = [
        "Оба используют <b>OB-4h → OB-1h → FVG-15m</b> как L2/L3/L4",
        "Оба применяют <b>direction matching</b>: все 4 уровня одного направления",
        "Оба используют <b>deep-FVG entry</b>: 0.7 × ширины FVG-15m",
        "Оба ставят <b>RR=2.0</b> и <b>min_sl=1%</b> от entry",
        "Оба позволяют <b>multiple setups на одну L1</b> зону (allow_multi)",
    ]
    for c in common:
        story.append(Paragraph("• " + c, S["bullet"]))

    story.append(Paragraph("В чём принципиальная разница", S["h2"]))
    story.append(Paragraph(
        "<b>1.1.4 = FVG как зона</b>. Зона FVG-d/12h «живёт», пока цена не пробила "
        "её границы. Внутри неё ищутся OB-4h. Это <b>зональная логика</b>.",
        S["body"]))
    story.append(Paragraph(
        "<b>1.1.5 = Фрактал как точка/событие</b>. Фрактал — это локальный "
        "экстремум (high или low за 5 свечей). Каскад начинается ТОЛЬКО когда "
        "цена сделала <b>sweep</b> этого уровня и отбилась обратно (failed breakout). "
        "Это <b>событийная логика</b>.", S["body"]))

    story.append(PageBreak())

    # ===== 3. СТРАТЕГИЯ 1.1.4 =====
    story.append(Paragraph("3. Стратегия 1.1.4 — анкер FVG", S["h1"]))
    story.append(Paragraph(
        "Эта стратегия — <b>«ждать структуру»</b>. Образовался FVG на дневном "
        "или 12-часовом таймфрейме — значит, есть имбаланс ликвидности, и цена "
        "с высокой вероятностью вернётся к нему. Внутри этого FVG ищем 4-stage "
        "подтверждение и входим в маленькую FVG-15m.", S["body"]))

    story.append(Paragraph("Логика каскада", S["h2"]))
    cascade14 = (
        "L1: FVG-1d или FVG-12h (макро-зона)<br/>"
        "  └ зона валидна пока цена не пробила top (для SHORT) или bottom (для LONG)<br/>"
        "L2: OB-4h или OB-6h обратного направления, ХОТЯ БЫ ОДНОЙ границей внутри L1-зоны<br/>"
        "  └ L2 должен ЗАКРЫТЬСЯ до инвалидации L1<br/>"
        "L3: OB-1h или OB-2h, обеими границами/перекрытием в L1 ∩ L2<br/>"
        "  └ L3 должен закрыться до инвалидации L1<br/>"
        "L4: FVG-15m или FVG-20m в синхронизации с L3<br/>"
        "  └ FVG-15m формируется ВО ВРЕМЯ 2 свечей OB-1h, перекрывает L1 И L2"
    )
    story.append(Paragraph(cascade14, S["mono"]))

    story.append(Paragraph("Четыре цепочки портфеля BFJK", S["h2"]))
    chains_data = [
        ["", "L1", "L2", "L3", "L4"],
        ["B", "FVG-12h", "OB-4h", "OB-1h", "FVG-15m"],
        ["F", "FVG-1d", "OB-6h", "OB-2h", "FVG-15m"],
        ["J", "FVG-1d", "OB-4h", "OB-1h", "FVG-20m"],
        ["K", "FVG-12h", "OB-4h", "OB-1h", "FVG-20m"],
    ]
    story.append(table(chains_data, col_widths=[1.5*cm, 3*cm, 3*cm, 3*cm, 3*cm]))
    story.append(Paragraph(
        "Сетапы всех 4 цепочек объединяются и дедуплицируются по (signal_time, "
        "direction, fvg_b, fvg_t). Один сетап может быть породжён несколькими "
        "цепочками — это <b>усиление сигнала</b>.", S["body"]))

    story.append(Paragraph("Финальные результаты 1.1.4", S["h2"]))
    if CSV_114.exists():
        df = pd.read_csv(CSV_114, encoding="utf-8-sig")
        closed = df[df["outcome"].isin(["win", "loss"])]
        years_data = [["Год", "Сделок", "WR", "Total R"]]
        for yr in sorted(closed["year"].unique()):
            yc = closed[closed["year"] == yr]
            yw = (yc["outcome"] == "win").sum()
            years_data.append([str(yr), str(len(yc)),
                                f"{yw/len(yc)*100:.1f}%",
                                f"{yc['R'].sum():+.1f}"])
        bad_idx = next((i for i, r in enumerate(years_data[1:], 1) if "+" not in r[3]), None)
        story.append(table(years_data, col_widths=[2*cm, 3*cm, 3*cm, 3*cm],
                            hl=[bad_idx] if bad_idx else None))
        story.append(Paragraph(
            "2025 — единственный проблемный год. Это структурное явление: стратегия "
            "1.1.4 хуже работает в режиме затяжного флэта/sideways, который "
            "характерен для 2025 на BTC.", S["body"]))

    story.append(PageBreak())

    # ===== 4. СТРАТЕГИЯ 1.1.5 =====
    story.append(Paragraph("4. Стратегия 1.1.5 — анкер фрактал + sweep", S["h1"]))
    story.append(Paragraph(
        "Эта стратегия — <b>«играть против ложного пробоя»</b>. Фрактал по "
        "Биллу Уильямсу — это локальный максимум/минимум за 5 свечей. Когда цена "
        "сначала пробивает фрактал, но затем закрывается обратно — это "
        "<b>liquidity grab</b>, классический SMC-паттерн. После такого sweep "
        "ищем разворотный каскад.", S["body"]))

    story.append(Paragraph("Определение фрактала", S["h2"]))
    frac_def = (
        "FH (Fractal High) на баре i:<br/>"
        "  high[i] > high[i-2], high[i-1], high[i+1], high[i+2]<br/>"
        "<br/>"
        "FL (Fractal Low) на баре i:<br/>"
        "  low[i] < low[i-2], low[i-1], low[i+1], low[i+2]<br/>"
        "<br/>"
        "Подтверждение (Bill Williams): на баре i+2"
    )
    story.append(Paragraph(frac_def, S["mono"]))

    story.append(Paragraph("Определение sweep", S["h2"]))
    story.append(Paragraph(
        "Sweep — это <b>ПЕРВАЯ</b> свеча после подтверждения фрактала, которая "
        "касается его уровня. Условия зависят от типа:", S["body"]))

    sweep_def = (
        "Для FH (свеча должна сделать failed breakout вверх):<br/>"
        "  high[j] > fractal_price  И  close[j] < fractal_price<br/>"
        "  (цена пробила фрактал вверх, но закрылась НИЖЕ него)<br/>"
        "<br/>"
        "Для FL (свеча должна сделать failed breakout вниз):<br/>"
        "  low[j] < fractal_price  И  close[j] > fractal_price<br/>"
        "  (цена пробила фрактал вниз, но закрылась ВЫШЕ него)<br/>"
        "<br/>"
        "Если первая касающаяся свеча закрылась ЗА уровнем — фрактал пропущен"
    )
    story.append(Paragraph(sweep_def, S["mono"]))

    story.append(Paragraph("Каскад после sweep", S["h2"]))
    cascade15 = (
        "После закрытия sweep-свечи начинается окно каскада (3 дня для 12h-фрактала):<br/>"
        "<br/>"
        "L2: OB-4h обратного направления, в <b>1 × ATR</b> от swept extreme<br/>"
        "L3: OB-1h обратного направления, в 1 × ATR от swept extreme<br/>"
        "L4: FVG-15m в синхронизации с L3, deep entry 0.7<br/>"
        "<br/>"
        "Допускается до <b>3 каскадов на один sweep</b> (множественные retest'ы)"
    )
    story.append(Paragraph(cascade15, S["mono"]))

    story.append(Paragraph("Доп. фильтр Hull-1h(L49)", S["h2"]))
    story.append(Paragraph(
        "На свежей выборке найден полезный фильтр: <b>Hull MA(49) на 1h должна быть "
        "согласована с направлением сделки</b>. Для LONG-сетапа: close[bar] > "
        "Hull[bar-2]. Для SHORT: close < Hull[bar-2]. Этот фильтр повышает WR с "
        "45% до 48% при сохранении частоты (≈ 1 сделка / 9 дней).", S["body"]))

    story.append(Paragraph("Финальные результаты 1.1.5 (hi-freq variant)", S["h2"]))
    if CSV_115.exists():
        df = pd.read_csv(CSV_115, encoding="utf-8-sig")
        closed = df[df["outcome"].isin(["win", "loss"])]
        years_data = [["Год", "Сделок", "WR", "Total R"]]
        for yr in sorted(closed["year"].unique()):
            yc = closed[closed["year"] == yr]
            yw = (yc["outcome"] == "win").sum()
            years_data.append([str(yr), str(len(yc)),
                                f"{yw/len(yc)*100:.1f}%",
                                f"{yc['R'].sum():+.1f}"])
        story.append(table(years_data, col_widths=[2*cm, 3*cm, 3*cm, 3*cm]))
        story.append(Paragraph(
            "<b>0 плохих лет за 7</b> — отличная стабильность. Все годы дают "
            "положительный R, даже 2025 (+9R) и частичный 2026 (+3R).", S["ok"]))

    story.append(PageBreak())

    # ===== 5. ТОРГОВЛЯ РУКАМИ =====
    story.append(Paragraph("5. Как торговать руками (пошагово)", S["h1"]))
    story.append(Paragraph(
        "Эта секция — самое важное практически. Бэктест показывает, что эти "
        "стратегии работают на исторических данных. Чтобы повторить результат, "
        "нужно следовать процессу строго.", S["body"]))

    story.append(Paragraph("5.1. Алгоритм для 1.1.4 (FVG-анкер)", S["h2"]))
    story.append(Paragraph(
        "<b>Шаг 1: найти активную FVG-d/12h.</b> На дневном и 12h графике BTCUSDT "
        "найти все Fair Value Gaps (Imbalance): тройку свечей где high[c0] < low[c2] "
        "(LONG-FVG) или low[c0] > high[c2] (SHORT-FVG). FVG валиден, пока ни одна "
        "свеча на том же TF не пробила его верхнюю (для SHORT) или нижнюю "
        "(для LONG) границу.", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 2: внутри FVG найти OB-4h.</b> Order Block — пара свечей "
        "противоположного направления: для LONG-OB первая медвежья, вторая бычья "
        "с закрытием выше high первой. Зона OB-LONG = [low_c1, high_c1]. OB-4h "
        "должен иметь хотя бы одну границу внутри FVG-d/12h.", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 3: дождаться OB-1h в общей зоне.</b> После закрытия OB-4h второй "
        "свечи начинаем смотреть 1h. Ищем OB-1h, чья зона перекрывает И FVG-d/12h, "
        "И OB-4h.", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 4: FVG-15m внутри 2 свечей OB-1h.</b> Самое тонкое: на 15-минутке "
        "ищем FVG, который сформировался ВО ВРЕМЯ 2-свечной формации OB-1h "
        "(не раньше и не позже). FVG-15m должен перекрыть и FVG-d/12h, и OB-4h.", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 5: разместить ордер.</b> Entry = fvg_bot + 0.7 × (fvg_top − fvg_bot) "
        "для LONG (глубокий вход). SL — внутри макро-кластера (пересечения FVG и OB-4h). "
        "TP = entry + 2 × |entry − sl|.", S["step"]))

    story.append(Paragraph("5.2. Алгоритм для 1.1.5 (Fractal-анкер)", S["h2"]))
    story.append(Paragraph(
        "<b>Шаг 1: ждать формирование фрактала-12h.</b> На 12h графике следим за "
        "локальными экстремумами. Когда видим high (или low) бара i, который выше "
        "(ниже) соседей i±1, i±2 — это потенциальный фрактал. Подтверждение "
        "приходит через 2 свечи (i+2).", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 2: дождаться sweep.</b> После подтверждения фрактала ждём первую "
        "свечу, которая касается его уровня. Если эта свеча закрылась за уровнем — "
        "сетап ОТМЕНЯЕТСЯ, фрактал пропущен. Если закрылась обратно (rejection) — "
        "это валидный sweep, каскад активируется.", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 3: проверить фильтр Hull-1h.</b> На 1h графике должна быть "
        "согласованность Hull MA(49) с направлением: для LONG (после FL-sweep) — "
        "close выше Hull MA(49)[bar-2]. Если контр-направление — сетап пропускаем.", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 4: найти OB-4h рядом со sweep.</b> На 4h ищем OB обратного "
        "направления (для FL: бычий OB; для FH: медвежий), midpoint в 1×ATR_12h "
        "от swept extreme. Окно поиска — 3 дня от sweep close.", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 5: OB-1h после OB-4h close.</b> На 1h ищем OB того же направления "
        "в той же proximity. После него — FVG-15m в синхронизации.", S["step"]))
    story.append(Paragraph(
        "<b>Шаг 6: вход на FVG-15m, SL за swept extreme.</b> Entry = 0.7 deep "
        "FVG-15m. SL ≈ swept_extreme ± 0.1% буфер, далее по асимметричной формуле "
        "(0.35 для LONG, 0.65 для SHORT). TP = 2 × |entry − sl|.", S["step"]))

    story.append(Paragraph("5.3. Универсальные правила для обеих стратегий", S["h2"]))
    rules = [
        "<b>Никогда не входить если SL < 1% от entry</b> — MIN_SL расширяет SL автоматически.",
        "<b>Жёсткая дисциплина TP/SL</b>: НЕ трейлить, НЕ переставлять — выставил и забыл.",
        "<b>Один сетап = одна позиция</b>. Если детектор показывает 2-3 сетапа на "
        "одной L1/sweep — выбирай ОДИН (ближайший к рынку или с меньшим risk_pct).",
        "<b>Тайминг входа</b>: ордер всегда лимитный, не маркет. Цена должна сама "
        "прийти к 0.7 × FVG-15m. Если уже ушла без касания — сетап пропущен.",
        "<b>Максимальное время удержания — 7 дней</b>. Если за неделю ни SL ни TP "
        "не сработали — закрывать ручкой.",
    ]
    for r in rules:
        story.append(Paragraph("• " + r, S["bullet"]))

    story.append(PageBreak())

    # ===== 6. УПРАВЛЕНИЕ РИСКОМ =====
    story.append(Paragraph("6. Управление риском", S["h1"]))

    story.append(Paragraph("6.1. Размер позиции", S["h2"]))
    story.append(Paragraph(
        "Стандартное правило: 1R = 1% от депозита. То есть SL должен означать "
        "потерю 1% депозита. Поскольку risk_pct сделок в среднем 1-1.5% (от "
        "цены entry), а позиция настраивается соответственно — на стандартной "
        "сделке вы рискуете 1% депозита, и в случае TP получаете 2%.", S["body"]))

    story.append(Paragraph("6.2. Ожидаемый месяц/год", S["h2"]))
    expect = [
        ["Метрика", "1.1.4 BFJK", "1.1.5 hi-freq", "1.1.5 hi-qual"],
        ["Сделок в месяц", "≈ 1.5", "≈ 3", "≈ 1.5"],
        ["Avg R в месяц (исторически)", "+1.4", "+1.4", "+1.1"],
        ["Худший год (R)", "-5 (2025)", "+3 (2026)", "-12 (2025)"],
        ["Лучший год (R)", "+41 (2024)", "+28 (2023)", "+25 (2022)"],
        ["Total R за 6.3 года", "+107", "+106", "+85"],
        ["Total % при 1R = 1%", "+107%", "+106%", "+85%"],
    ]
    story.append(table(expect, col_widths=[5*cm, 3.5*cm, 3.5*cm, 3.5*cm]))

    story.append(Paragraph("6.3. Drawdown и серии лоссов", S["h2"]))
    story.append(Paragraph(
        "При WR 48% в 1.1.5 серии из 4-5 лоссов подряд статистически нормальны. "
        "Это значит drawdown до -5R = до 5% депозита при 1R = 1%. Психологически "
        "нужно быть готовым к этому. В 1.1.4 при WR 64% серии короче, но просадки "
        "могут возникать в bad year (2025).", S["body"]))

    story.append(Paragraph(
        "<b>Не комбинировать обе стратегии полностью</b> — они частично "
        "пересекаются по сетапам (когда FVG-d/12h формируется около фрактала-12h). "
        "Если хочется диверсификации — использовать одну как основную и другую как "
        "сигнал-фильтр (например: брать 1.1.5 сетапы только если в этот период "
        "активен FVG-d 1.1.4).", S["body"]))

    story.append(PageBreak())

    # ===== 7. АУДИТ И БАГИ =====
    story.append(Paragraph("7. Forensic-аудит и найденные баги", S["h1"]))
    story.append(Paragraph(
        "Перед публикацией обе стратегии прошли проверку на 10 категорий "
        "потенциальных багов. Всё нижеперечисленное было найдено и исправлено.",
        S["body"]))

    story.append(Paragraph("Bug #1 (CRITICAL, FIXED): L3 после инвалидации L1 в 1.1.4", S["h2"]))
    story.append(Paragraph(
        "<b>Симптом:</b> 13% сетапов 1.1.4 формировались на УЖЕ мёртвой макро-FVG "
        "(пробитой). Эти сетапы имели WR 21%, total -7R.<br/>"
        "<b>Причина:</b> проверка инвалидации применялась только к L2 OB, "
        "пропускалась для L3 и L4.<br/>"
        "<b>Фикс:</b> добавлена проверка `L3_close ≤ L1_active_end` и аналогичная "
        "для L4 c2_close. Финальные цифры 1.1.4 в этом отчёте — после фикса.",
        S["body"]))

    story.append(Paragraph("Bug #2 (CRITICAL, FIXED): FORMING bar lookahead в Hull filter", S["h2"]))
    story.append(Paragraph(
        "<b>Симптом:</b> фильтр Hull-1h на 1.1.5 показывал WR 50.2% / +117R. "
        "После фикса — 47.9% / +106R (inflation ≈ 2-3pp WR, +11R).<br/>"
        "<b>Причина:</b> `searchsorted(ts, \"right\") - 1` возвращает индекс бара, "
        "на КОТОРОМ находится signal_time, — этот бар ещё формируется, его close "
        "неизвестен.<br/>"
        "<b>Фикс:</b> заменено на `searchsorted(ts, \"left\") - 1` — возвращает "
        "ПРЕДЫДУЩИЙ бар, чей close уже известен. Это тот же класс ошибки что "
        "documented в проекте как `htf-lookup-must-use-last-closed-bar-not-forming`.",
        S["body"]))

    story.append(Paragraph("Что проверено и чисто", S["h2"]))
    clean = [
        "Lookahead в симуляторе (entry/SL/TP сканирует только данные после signal_time)",
        "Все RR ровно 2.000 (без округлений и накопления ошибок)",
        "Нет SL ≥ entry для LONG, нет SL ≤ entry для SHORT",
        "MIN_SL_PCT 1% корректно применяется во всех сделках",
        "Нет degenerate зон (FVG/OB с bottom ≥ top)",
        "Все entry_time ≥ signal_time, все exit_time ≥ entry_time",
        "Sweep candle действительно делает failed breakout (high > FH И close < FH)",
        "Sweep — первая касающаяся свеча (не пропуск с прорывом раньше)",
        "ATR используется на момент confirm_time фрактала (i+2), не позже",
        "Direction matching: все 4 уровня каскада одного направления",
        "Win = +2.0R, Loss = -1.0R (нет аномалий в outcome)",
        "Дедупликация по (signal_time, direction, fvg_b, fvg_t) работает корректно",
    ]
    for c in clean:
        story.append(Paragraph("✓ " + c, S["bullet"]))

    story.append(PageBreak())

    # ===== 8. ОГРАНИЧЕНИЯ И FAQ =====
    story.append(Paragraph("8. Ограничения и FAQ", S["h1"]))

    story.append(Paragraph("Известные ограничения", S["h2"]))
    limits = [
        "<b>Только BTCUSDT, не ETH/SOL.</b> На других активах результаты могут "
        "сильно отличаться. Прошлая работа показала: C2v2 стратегия работала "
        "только на BTC, провалилась на ETH (-30R, 4/4 bad years).",
        "<b>Симулятор не учитывает spread, slippage, комиссии Binance.</b> "
        "В реальной торговле total R может быть ниже на 10-20%. Особенно "
        "критично для 1.1.5 hi-freq с большим количеством сделок.",
        "<b>2026 — частичный год</b> (январь-апрель), малая выборка, нельзя "
        "опираться на эти 9-12 сделок как на типичные.",
        "<b>Корреляция между мульти-сетапами</b> на одной L1/sweep не учтена "
        "в WR. Если открыть все 3 сетапа на одну зону — они скорее всего "
        "сработают одинаково.",
        "<b>Live forward-test не проведён</b>. Все результаты — только бэктест.",
    ]
    for l in limits:
        story.append(Paragraph("• " + l, S["bullet"]))

    story.append(Paragraph("Какую стратегию выбрать?", S["h2"]))
    story.append(Paragraph(
        "<b>1.1.4 BFJK</b> — если ценишь <b>качество сигнала</b> (+0.93R на сделку), "
        "не хочешь много торговать, и готов потерпеть один плохой год.<br/>"
        "<b>1.1.5 hi-freq</b> — если хочешь <b>стабильность</b> (0 плохих лет за 7), "
        "готов к большему количеству сделок и меньшему R на сделку.<br/>"
        "<b>1.1.5 hi-quality</b> — если хочешь редкие, но качественные сделки, и "
        "согласен на 1 плохой год.", S["body"]))

    story.append(Paragraph("Что если фрактал/FVG неоднозначный?", S["h2"]))
    story.append(Paragraph(
        "Используй <b>строгое определение</b>: для FVG требуется high[c0] < low[c2] "
        "ATOMARNO (никаких допущений). Для фрактала — high[i] СТРОГО > соседей "
        "(не равно). Если есть сомнение — лучше пропустить, чем взять. Бэктест "
        "сделан с этими же строгими правилами.", S["body"]))

    story.append(Paragraph("Сколько капитала нужно?", S["h2"]))
    story.append(Paragraph(
        "Минимум — чтобы 1% капитала был больше минимального лота биржи. На "
        "Binance Spot минимальный ордер ≈ $5-10. Значит депозит от $500-1000. "
        "Но для адекватного эмоционального управления риском (1R = 1% от депо, "
        "обычная просадка до 5%) — рекомендуется минимум $2000-5000.",
        S["body"]))

    story.append(Paragraph("Когда стратегия может перестать работать?", S["h2"]))
    story.append(Paragraph(
        "SMC-каскадные стратегии деградируют в <b>сильных трендах без откатов</b> "
        "(быстрый bull run без касания зон) и в <b>экстремальных flash crash</b> "
        "(когда цена пролетает все зоны). Также — изменения структуры рынка "
        "(деривативы доминируют, реальные ордера маленькие) могут постепенно "
        "ослабить SMC-эффекты. Раз в полгода стоит делать walk-forward проверку "
        "на свежих 3 месяцах.", S["body"]))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        "<i>Отчёт сгенерирован автоматически на основе бэктеста BTCUSDT 1m данных "
        "01.2020 — 04.2026 (более 3.3 млн свечей). Все CSV и логи — в "
        "research/elements_study/output/. Финальные стратегии — в etap_74 (1.1.4) "
        "и etap_81 (1.1.5).</i>", S["caption"]))

    # Build
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT_PDF), pagesize=A4,
                              leftMargin=2*cm, rightMargin=2*cm,
                              topMargin=2*cm, bottomMargin=2*cm,
                              title="Стратегии 1.1.4 и 1.1.5 — полное руководство",
                              author="Claude Code Research")
    doc.build(story)
    print(f"[OK] PDF saved: {OUTPUT_PDF}")
    print(f"     Size: {OUTPUT_PDF.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build()
