"""Превью: как level_engine ляжет в живой дашборд (НЕ трогает etap_227/225).

(а) ближайшие уровни -> линии с ярлыком 'N/10 SUP/RES' на чарте (через штатный lines);
(б) блок 'Уровни' добавляется в подпись. Печатает путь PNG + итоговую подпись.
"""
import sys
from pathlib import Path
import pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[0] / "daily_engine"))
sys.path.insert(0, str(HERE.parents[1]))
import etap_225_dual_dashboard as D
import etap_227_live_dashboard_bot as B
import le_engine as LE


def level_block(snap, n=3):
    price = snap["price"]
    sup = sorted([L for L in snap["levels"] if L["center"] < price], key=lambda L: -L["center"])[:n]
    res = sorted([L for L in snap["levels"] if L["center"] >= price], key=lambda L: L["center"])[:n]

    def tag(L):
        x = []
        if L["has_magnet"]: x.append("POC")
        if L["has_liquidity"]: x.append("LIQ")
        extra = ("," + "/".join(x)) if x else ""
        return (f"{L['center']:,.0f} — <b>{L['strength']}/10</b> "
                f"({L['n_zones']}з/{len(L['tfs'])}TF{extra}, R{L['rejects']}/B{L['breaks']})")
    out = ["", "🪜 <b>Уровни рядом</b> (сила, описательно — не прогноз):"]
    for L in res[::-1]:
        out.append(f"  ▲ сопр {tag(L)}")
    for L in sup:
        out.append(f"  ▼ опора {tag(L)}")
    return "\n".join(out)


def main():
    df = D.fetch("BTCUSDT", days=900)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    M = B.fit_model()
    snap = LE.snapshot(df, df.index[-1]); price = snap["price"]
    sup = sorted([L for L in snap["levels"] if L["center"] < price], key=lambda L: -L["center"])[:3]
    res = sorted([L for L in snap["levels"] if L["center"] >= price], key=lambda L: L["center"])[:3]
    lines = [(L["center"], f"{L['strength']}/10 {('опора' if L['side']=='support' else 'сопр')}")
             for L in sup + res]
    s = B.status("BTC", df, M)
    path = D.dashboard("BTC_lvlpreview", df, M, lines, "{:,.0f}",
                       exp_pct=s.get("exp_pct") if s.get("exp_src") == "model" else None,
                       rev_day=s.get("day_rec"))
    cap = B.build_caption("BTC", s, lines) + "\n" + level_block(snap)
    print("PNG:", path)
    print("\n===== ПОДПИСЬ (как уйдёт в Telegram) =====\n")
    print(cap.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))


if __name__ == "__main__":
    main()
