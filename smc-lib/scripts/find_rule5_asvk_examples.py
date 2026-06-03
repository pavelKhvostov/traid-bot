"""Поиск ситуаций по Правилу 5 (основная стратегия ASVK):
  1. HTF OB (1h или 2h) сформирована при HTF-движении
  2. Цена возвращается в OB.zone (pullback)
  3. Внутри OB.zone появляется LTF VC (LTF FVG того же направления, FVG ⊆ OB.zone)
  4. После VC — continuation в направлении OB

Канон VC: HTF=1h/2h, LTF=15m/20m, aligned.
"""
from __future__ import annotations
import csv, pathlib, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
from candle import Candle
from elements.ob.code import detect_ob
from elements.fvg.code import detect_fvg
from vc.code import has_vc

CSV = pathlib.Path.home() / "traid-bot/data/BTCUSDT_1m_vic_vadim.csv"
MSK = timezone(timedelta(hours=3))
MS_M = 60_000
MS_H = 60*MS_M

# Окно поиска: последние 60 дней
LOOKBACK_DAYS = 60

print("Loading 1m...")
rows=[]
with CSV.open() as f:
    rd=csv.reader(f); next(rd)
    for r in rd:
        t=datetime.fromisoformat(r[0])
        rows.append((int(t.timestamp()*1000),float(r[1]),float(r[2]),float(r[3]),float(r[4])))

last_ts = rows[-1][0]
window_start = last_ts - LOOKBACK_DAYS*24*3600*1000
print(f"  data: {len(rows)} bars, window: {datetime.fromtimestamp(window_start/1000, MSK).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(last_ts/1000, MSK).strftime('%Y-%m-%d')}")

def agg(d, tfms, anchor=0):
    out=[]; cb=None; o=h=l=c=0.0
    for ts,oo,hh,ll,cc in d:
        b = ts - ((ts - anchor) % tfms)
        if b!=cb:
            if cb is not None: out.append((cb,o,h,l,c))
            cb=b; o,h,l,c=oo,hh,ll,cc
        else:
            h=max(h,hh); l=min(l,ll); c=cc
    if cb is not None: out.append((cb,o,h,l,c))
    return out

def to_cans(bb):
    return [Candle(open=b[1],high=b[2],low=b[3],close=b[4],open_time=b[0]) for b in bb]

bars = {
    "1h":  agg(rows, 1*MS_H),
    "2h":  agg(rows, 2*MS_H),
    "15m": agg(rows, 15*MS_M),
    "20m": agg(rows, 20*MS_M),
}
cans = {tf: to_cans(bb) for tf,bb in bars.items()}
tf_ms = {"1h":1*MS_H,"2h":2*MS_H,"15m":15*MS_M,"20m":20*MS_M}

def fmt(ts): return datetime.fromtimestamp(ts/1000, MSK).strftime('%Y-%m-%d %H:%M')

# Детект всех HTF OBs в окне
htf_obs = []  # (tf, idx_pair_start, ob, formation_ts, prev_bar, cur_bar)
for htf in ("1h","2h"):
    cs = cans[htf]
    for i in range(len(cs)-1):
        if cs[i].open_time < window_start - 5*24*3600*1000:  # небольшой запас
            continue
        if cs[i].open_time > last_ts - 12*3600*1000:  # last 12h — не успеет проявиться pullback
            continue
        ob = detect_ob(cs[i], cs[i+1])
        if ob:
            formation_ts = cs[i+1].open_time + tf_ms[htf]
            htf_obs.append({
                "tf": htf, "i": i, "ob": ob,
                "formation_ts": formation_ts,
                "prev": cs[i], "cur": cs[i+1],
            })

print(f"  HTF OBs (1h+2h): {len(htf_obs)}")

# Pullback + VC поиск
ltf_fvgs_cache = {}
def fvgs_in_window(ltf, t_lo, t_hi):
    key = (ltf, t_lo, t_hi)
    if key in ltf_fvgs_cache: return ltf_fvgs_cache[key]
    cs = cans[ltf]
    out = []
    for k in range(len(cs)-2):
        c1, c2, c3 = cs[k], cs[k+1], cs[k+2]
        if c1.open_time < t_lo: continue
        if c3.open_time + tf_ms[ltf] > t_hi: break
        fv = detect_fvg(c1, c2, c3)
        if fv:
            out.append({"fvg": fv, "c1_ts": c1.open_time, "c3_ts": c3.open_time,
                        "formation_ts": c3.open_time + tf_ms[ltf]})
    ltf_fvgs_cache[key] = out
    return out

found = []
SEARCH_HORIZON_H = 72   # сколько часов после OB искать pullback+VC
CONTINUATION_H = 48     # горизонт continuation после VC
MIN_AWAY_BARS = 60      # 1m bars — минимум сколько цена должна ОТСУТСТВОВАТЬ в зоне (= 1h)
MIN_RR = 3.0            # отбрасываем R:R < 3
MAX_RR_CAP = 50         # ограничиваем R:R сверху (избегаем 750× из деления на ~0)

for rec in htf_obs:
    ob = rec["ob"]; direction = ob.direction
    zlo, zhi = ob.zone
    t0 = rec["formation_ts"]
    t_end = min(t0 + SEARCH_HORIZON_H*MS_H, last_ts)
    i0 = next((i for i,r in enumerate(rows) if r[0] >= t0), None)
    if i0 is None: continue
    # 1) Цена должна ВЫЙТИ из зоны (для LONG: low > zhi; для SHORT: high < zlo)
    away_idx = None
    for j in range(i0, len(rows)):
        ts,o,h,l,c = rows[j]
        if ts > t_end: break
        if direction == "long" and l > zhi:
            away_idx = j; break
        if direction == "short" and h < zlo:
            away_idx = j; break
    if away_idx is None: continue
    # 2) Затем достаточно долго отсутствовать (≥ MIN_AWAY_BARS подряд)
    away_count = 0; truly_away_idx = None
    for j in range(away_idx, len(rows)):
        ts,o,h,l,c = rows[j]
        if ts > t_end: break
        inside = (l <= zhi) if direction=="long" else (h >= zlo)
        if inside:
            away_count = 0
        else:
            away_count += 1
            if away_count >= MIN_AWAY_BARS:
                truly_away_idx = j; break
    if truly_away_idx is None: continue
    # 3) Найти первый возврат в зону ПОСЛЕ выхода (это и есть pullback)
    pullback_ts = None
    for j in range(truly_away_idx+1, len(rows)):
        ts,o,h,l,c = rows[j]
        if ts > t_end: break
        if direction == "long" and l <= zhi:
            pullback_ts = ts; break
        if direction == "short" and h >= zlo:
            pullback_ts = ts; break
    if pullback_ts is None: continue
    # Окно VC: ОТ pullback_ts (строго) до конца окна или до consumed
    vc_t_lo = pullback_ts
    vc_t_hi = t_end
    # Поиск VC на LTF (15m, 20m)
    vcs = []
    for ltf in ("15m","20m"):
        for f_rec in fvgs_in_window(ltf, vc_t_lo, vc_t_hi):
            fv = f_rec["fvg"]
            if fv.direction != direction: continue
            if has_vc(ob, fv):
                vcs.append({"ltf":ltf, "fvg":fv, "formation_ts":f_rec["formation_ts"]})
    if not vcs: continue
    # Берём первую (раннюю) VC
    vcs.sort(key=lambda v: v["formation_ts"])
    vc = vcs[0]
    # Continuation: после VC formation_ts, насколько цена ушла в направлении OB
    cont_end = min(vc["formation_ts"] + CONTINUATION_H*MS_H, last_ts)
    icv = next((i for i,r in enumerate(rows) if r[0] >= vc["formation_ts"]), None)
    if icv is None: continue
    seg = [r for r in rows[icv:] if r[0] <= cont_end]
    if not seg: continue
    entry_price = (zlo + zhi) / 2  # середина OB как условный entry
    if direction == "long":
        max_move = max(r[2] for r in seg) - entry_price  # high - entry
        adverse = entry_price - min(r[3] for r in seg)   # entry - low (drawdown)
    else:
        max_move = entry_price - min(r[3] for r in seg)
        adverse = max(r[2] for r in seg) - entry_price
    move_pct = max_move / entry_price * 100
    advr_pct = adverse / entry_price * 100
    rr = min(move_pct / max(advr_pct, 0.05), MAX_RR_CAP)
    if rr < MIN_RR: continue
    if move_pct < 1.0: continue  # хотя бы 1% движения
    found.append({
        "tf": rec["tf"], "dir": direction,
        "ob_zone": (zlo, zhi),
        "ob_formation_ts": t0,
        "pullback_ts": pullback_ts,
        "vc_ltf": vc["ltf"],
        "vc_fvg_zone": vc["fvg"].zone,
        "vc_formation_ts": vc["formation_ts"],
        "entry_mid": entry_price,
        "move_pct": move_pct, "advr_pct": advr_pct, "rr": rr,
        "cont_end": cont_end,
    })

print(f"  Кандидатов (HTF OB + pullback + VC + continuation): {len(found)}")
# Сортируем по R:R (continuation/drawdown), берём top 8
found.sort(key=lambda x: -x["rr"])

print()
print(f"{'#':<3} {'HTF':<4} {'dir':<6} {'OB sigma':<25} {'pullback':<18} {'VC LTF':<7} {'VC zone':<22} {'VC ts':<18} {'move%':<7} {'dd%':<6} {'R:R':<5}")
print("-"*150)
for i, f in enumerate(found[:8], 1):
    zlo,zhi = f["ob_zone"]; fvz_lo, fvz_hi = f["vc_fvg_zone"]
    print(f"{i:<3} {f['tf']:<4} {f['dir']:<6} [{zlo:.0f},{zhi:.0f}]{'':>5} {fmt(f['pullback_ts']):<18} {f['vc_ltf']:<7} [{fvz_lo:.0f},{fvz_hi:.0f}]{'':>3} {fmt(f['vc_formation_ts']):<18} {f['move_pct']:>5.2f}  {f['advr_pct']:>5.2f}  {f['rr']:>4.2f}")

print()
print("Top candidate (детально):")
if found:
    f = found[0]
    zlo,zhi = f["ob_zone"]; fvz_lo, fvz_hi = f["vc_fvg_zone"]
    print(f"  HTF: {f['tf']} OB ({f['dir']})")
    print(f"  OB zone: [{zlo:.2f}, {zhi:.2f}], formation ≈ {fmt(f['ob_formation_ts'])}")
    print(f"  Pullback в зону: {fmt(f['pullback_ts'])}")
    print(f"  LTF VC: {f['vc_ltf']} FVG, zone [{fvz_lo:.2f}, {fvz_hi:.2f}], formation {fmt(f['vc_formation_ts'])}")
    print(f"  Continuation за {CONTINUATION_H}h: move={f['move_pct']:.2f}%  drawdown={f['advr_pct']:.2f}%  R:R={f['rr']:.2f}")
