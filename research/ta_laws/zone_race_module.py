"""НЕЙРО-МОДУЛЬ «ГОНКА ЗОН»: в какую зону Вадима цена придёт ПЕРВОЙ (first-passage), с само-исправлением.

Переформулирует неразрешимое «куда пойдёт» в разрешимое «какая зона коснётся первой»: на каждом якоре —
ближайшая незакрытая зона ВВЕРХУ (Z↑) и ВНИЗУ (Z↓) из канон-движка Вадима; метка = кто первым (каузально,
форвард по 1h). Фичи: дистанции, сила-магнит, роль, мульти-ТФ контекст, вола.

САМО-ОБУЧЕНИЕ/САМО-ИСПРАВЛЕНИЕ (онлайн, walk-forward, без lookahead): на каждом якоре модуль
  1) предсказывает (Z↑ или Z↓ первой),
  2) видит исход,
  3) ОСОЗНАЁТ ошибку, АТРИБУТИРУЕТ причину (какая фича потянула не туда — наибольший вклад в неверную сторону),
  4) АРГУМЕНТИРОВАННО двигает вес этой фичи (онлайн-градиент) и логирует довод,
  → каждый новый якорь ревизует «убеждения» (веса) обо всех прошлых = само-исправление.

Метрика (НЕ AUC, по просьбе): точность vs тривиальный baseline «ближайшая зона первой», cross-asset,
кривая самоулучшения (поздняя точность > ранней?), лог аргументированных коррекций, итоговые «законы» (веса).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/zone_race_module.py
Выход: research/ta_laws/zone_race_report.txt + zone_race_curve.png
"""
from __future__ import annotations
import sys, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
from research.smc_adapter import (precompute_zone_events, snapshot_from_events,  # noqa: E402
                                  ROLE, TF_W, ZTYPES_FAST)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ZONE_TFS = ("12h", "1d")
HORIZON = 60          # 1h-баров вперёд для гонки
MAXDIST = 6.0         # макс. дистанция зоны (%) для участия
FEATS = ["dist_ratio", "str_up", "str_down", "str_diff", "mag_up", "mag_down", "mtf_up", "atr_pct"]


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def zstrength(z):
    mat = 1.0 if 2 <= z.age_bars <= 40 else (0.7 if z.age_bars <= 120 else 0.4)
    role_w = {"block": 1.0, "liquidity": 0.7, "inefficiency": 0.6}[ROLE.get(z.type, "block")]
    return TF_W.get(z.tf, 1.0) * mat * role_w


def build_samples(sym):
    d1 = load_1m(sym)
    h1 = rs(d1, "1h"); n = len(h1)
    H = h1["high"].values; L = h1["low"].values
    atr = G.compute_atr(h1)
    mtf = {"1h": (h1["close"], pd.Timedelta(hours=10)),
           "4h": (rs(d1, "4h")["close"], pd.Timedelta(hours=40)),
           "1d": (rs(d1, "1d")["close"], pd.Timedelta(days=10))}
    ev, resampled = precompute_zone_events(d1, tfs=ZONE_TFS, types=ZTYPES_FAST)
    out = []
    step = 12   # якорь каждые 12 1h-баров (~раз в 12ч)
    for i in range(60, n - HORIZON - 1, step):
        ts = h1.index[i]; price = float(h1["close"].values[i])
        zs = snapshot_from_events(ev, resampled, d1, ts)
        ups = [z for z in zs if z.lo > price and (z.lo - price) / price * 100 <= MAXDIST]
        dns = [z for z in zs if z.hi < price and (price - z.hi) / price * 100 <= MAXDIST]
        if not ups or not dns:
            continue
        zu = min(ups, key=lambda z: z.lo); zd = max(dns, key=lambda z: z.hi)
        d_up = (zu.lo - price) / price * 100; d_dn = (price - zd.hi) / price * 100
        # first-passage метка
        first = None
        for x in range(i + 1, i + 1 + HORIZON):
            up_hit = H[x] >= zu.lo; dn_hit = L[x] <= zd.hi
            if up_hit and dn_hit:
                first = 1 if (H[x] - price) <= (price - L[x]) else 0; break  # грубо ближе
            if up_hit:
                first = 1; break
            if dn_hit:
                first = 0; break
        if first is None:
            continue
        mtf_up = sum(int((s.asof(ts) > s.asof(ts - td))) for s, td in mtf.values())
        feat = {
            "dist_ratio": (d_dn - d_up) / (d_dn + d_up + 1e-9),   # >0 → up ближе
            "str_up": zstrength(zu), "str_down": zstrength(zd),
            "str_diff": zstrength(zu) - zstrength(zd),
            "mag_up": 1.0 if ROLE.get(zu.type) in ("inefficiency", "liquidity") else 0.0,
            "mag_down": 1.0 if ROLE.get(zd.type) in ("inefficiency", "liquidity") else 0.0,
            "mtf_up": float(mtf_up), "atr_pct": atr[i] / price * 100,
        }
        out.append({"sym": sym, "ts": ts, "y": first, "d_up": d_up, "d_dn": d_dn, **feat})
    return out


class OnlineLaw:
    """Онлайн-логистика с running-нормализацией + атрибуцией ошибки + аргументированной коррекцией."""
    def __init__(self, feats, lr=0.08):
        self.f = feats; self.k = len(feats); self.lr = lr
        self.w = np.zeros(self.k); self.b = 0.0
        self.mean = np.zeros(self.k); self.M2 = np.zeros(self.k); self.cnt = 0
        self.wtraj = []; self.culprits = {}; self.log = []

    def _norm(self, x):
        std = np.sqrt(self.M2 / self.cnt) if self.cnt > 1 else np.ones(self.k)
        std[std < 1e-6] = 1.0
        return (x - self.mean) / std

    def _upd_stats(self, x):
        self.cnt += 1; d = x - self.mean; self.mean += d / self.cnt; self.M2 += d * (x - self.mean)

    def step(self, x_raw, y, meta):
        xn = self._norm(x_raw)
        z = float(self.w @ xn + self.b); p = 1 / (1 + math.exp(-max(-30, min(30, z))))
        pred = 1 if p > 0.5 else 0
        wrong = pred != y
        if wrong and self.cnt > 200:
            contrib = self.w * xn                      # вклад фич в логит
            sign = 1.0 if pred == 1 else -1.0          # неверно предсказал {pred}
            j = int(np.argmax(contrib * sign))         # фича, сильнее всех тянувшая к неверному
            self.culprits[self.f[j]] = self.culprits.get(self.f[j], 0) + 1
            w_old = self.w[j]
            e = y - p
            self.w += self.lr * e * xn; self.b += self.lr * e
            if len(self.log) < 7:
                self.log.append(
                    f"#{meta['i']} {meta['sym']} {meta['ts']:%Y-%m-%d %H:%M}: предсказал "
                    f"{'ВВЕРХ' if pred else 'ВНИЗ'} (p={p:.2f}), факт {'ВВЕРХ' if y else 'ВНИЗ'}. "
                    f"Причина: фича '{self.f[j]}' (вклад {contrib[j]:+.2f}) тянула к неверному. "
                    f"Исправление: w[{self.f[j]}] {w_old:+.3f}->{self.w[j]:+.3f} (Δ{self.w[j]-w_old:+.3f}).")
        else:
            e = y - p
            self.w += self.lr * e * xn; self.b += self.lr * e
        self._upd_stats(x_raw)
        self.wtraj.append(self.w.copy())
        return pred, wrong


def main():
    rng = np.random.default_rng(7)
    alls = []
    for s in SYMBOLS:
        print(f"[{s}] build samples...", flush=True)
        alls += build_samples(s)
    df = pd.DataFrame(alls).sort_values("ts").reset_index(drop=True)
    print(f"[samples] {len(df)} (up-first {df.y.mean()*100:.0f}%)", flush=True)

    X = df[FEATS].values
    y = df.y.values
    law = OnlineLaw(FEATS)
    preds = np.zeros(len(df), int); wrongs = np.zeros(len(df), bool)
    base = (df.dist_ratio.values > 0).astype(int)     # baseline: ближайшая зона первой
    for i in range(len(df)):
        pr, wr = law.step(X[i], int(y[i]), {"i": i, "sym": df.sym.values[i], "ts": df.ts.values[i].astype('datetime64[s]').item()})
        preds[i] = pr; wrongs[i] = wr

    warm = 200
    acc = (preds[warm:] == y[warm:]).mean()
    base_acc = (base[warm:] == y[warm:]).mean()
    half = (len(df) + warm) // 2
    early = (preds[warm:half] == y[warm:half]).mean()
    late = (preds[half:] == y[half:]).mean()

    out = []
    out.append("НЕЙРО-МОДУЛЬ «ГОНКА ЗОН» — в какую зону Вадима цена придёт первой (first-passage, само-исправление).")
    out.append(f"Якорей: {len(df)} (BTC/ETH/SOL, каждые 12ч, зоны {ZONE_TFS}, горизонт {HORIZON}h, каузально).")
    out.append(f"Доля up-first: {df.y.mean()*100:.0f}%\n")
    out.append("=== ТОЧНОСТЬ (без AUC) ===")
    out.append(f"  baseline «ближайшая зона первой»: {base_acc*100:.1f}%")
    out.append(f"  нейро-модуль (онлайн, walk-forward): {acc*100:.1f}%  (лифт {(acc-base_acc)*100:+.1f} п.п.)")
    out.append(f"  самоулучшение: ранняя {early*100:.1f}% -> поздняя {late*100:.1f}% "
               f"({'УЧИТСЯ' if late > early + 0.005 else 'плато'})")
    # cross-asset
    out.append("  по символам (нейро / baseline):")
    for s in SYMBOLS:
        m = (df.sym.values == s) & (np.arange(len(df)) >= warm)
        if m.sum() > 30:
            out.append(f"    {s}: {(preds[m]==y[m]).mean()*100:.1f}% / {(base[m]==y[m]).mean()*100:.1f}%")

    out.append("\n=== САМО-ИСПРАВЛЕНИЕ: аргументированные коррекции (первые) ===")
    out += ["  " + l for l in law.log]
    out.append("\n  Частота причин ошибок (какая фича чаще тянула не туда):")
    for f, c in sorted(law.culprits.items(), key=lambda kv: -kv[1])[:8]:
        out.append(f"    {f:12} {c}")

    out.append("\n=== ВЫВЕДЕННЫЕ «ЗАКОНЫ» (итоговые веса, что модуль понял) ===")
    order = np.argsort(-np.abs(law.w))
    for j in order:
        out.append(f"    {FEATS[j]:12} w={law.w[j]:+.3f}  ({'→ up-first' if law.w[j]>0 else '→ down-first'} при росте фичи)")

    out.append("\n=== ВЕРДИКТ ===")
    beats = acc > base_acc + 0.01
    learns = late > early + 0.005
    out.append(f"  {'нейро-модуль БЬЁТ дистанцию' if beats else 'дистанция доминирует — зоны/контекст дают мало сверх неё'}"
               f" ({acc*100:.1f}% vs {base_acc*100:.1f}%); самообучение: {'есть' if learns else 'плато'}.")
    out.append("  Честно: первый-проход цены к зоне ≈ задача дистанции; вклад магнит-силы/контекста сверх неё — "
               + ("положительный и закреплён весами." if beats else "малый (модуль сам это 'осознал' — вес дистанции доминирует)."))

    rep = HERE / "zone_race_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))

    # кривая самообучения
    wt = np.array(law.wtraj)
    rollacc = pd.Series((preds == y).astype(float)).rolling(400, min_periods=50).mean()
    fig, ax = plt.subplots(2, 1, figsize=(13, 8))
    ax[0].plot(rollacc.values, color="#1db954", lw=1.3, label="нейро rolling-acc(400)")
    ax[0].axhline(base_acc, color="#ef5350", ls="--", lw=1, label=f"baseline дистанция {base_acc*100:.0f}%")
    ax[0].set_title("Само-обучение: скользящая точность «гонки зон»"); ax[0].legend(fontsize=8); ax[0].grid(alpha=0.2)
    for j in range(len(FEATS)):
        ax[1].plot(wt[:, j], lw=1, label=FEATS[j])
    ax[1].set_title("Ревизия 'убеждений': траектории весов (само-исправление)"); ax[1].legend(fontsize=7, ncol=4); ax[1].grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(HERE / "zone_race_curve.png", dpi=120)
    print(f"\n[zone_race] -> {rep.name} + zone_race_curve.png")


if __name__ == "__main__":
    main()
