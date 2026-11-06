#!/usr/bin/env python3
"""
Generations outlook: the written state of play shown at the top of the "Generations vs last year" tab.

    python3 scripts/build_gen_outlook.py      -> data/gen_outlook.json

Rebuilt after every new month of the Biomasseregisteret (monthly workflow). It answers one question: will there be a
gap in big fish (5 kg+ gutted) when the harvest moves from one generation to the next, as there used to be every year?

1. History: 5 kg+ and 6 kg+ harvested each month (harvest weight of each zone and generation, lognormal spread,
   coefficient of variation 0.27, gutted = 0.888 x live) and the "transition gap" of each season (October to September):
   lowest 3-month average of 5 kg+ harvested between April and September / monthly average of the October-March before.
2. State of play at the last register month: the generation being harvested and the next one against the year before at
   the same stage (fish left, biomass, weight, fish 5 kg+, growth per fish, TGC, mortality, sea temperature).
3. Projection of the next 12 months by size class, relative method: the same simulation is run from the last month and
   from the same month a year earlier, and the ratio of the two is applied to what was really harvested a year earlier
   (the simulation's own errors, which are large, cancel out for the most part). Simulation, zone by zone and generation by
   generation: growth = usual TGC at that weight and calendar month x the generation's own recent advance (3 scenarios:
   advance fades out, kept at 70 %, kept in full) x expected sea temperature (normal of the last 3 years + current
   anomaly fading by 0.6 a month); harvest = usual share of the stock harvested at that weight and calendar month;
   harvest weight = stock weight x usual ratio; mortality = the generation's last 3 months. Learned on 2019-2020 and
   2023 onwards (2021-2022 left out). Tested from September 2025: April-July 2026 5 kg+ harvest forecast 206 kt,
   actual 215 kt; October-March under-forecast (224 vs 312 kt) because growth accelerated that winter.
4. Next two months: next month's harvest from whole-fish exports (SSB weekly, already complete), and what the next
   register will show if each scenario holds.
"""
import calendar
import collections
import datetime as dt
import io
import json
import math
import os
import sys
from statistics import NormalDist

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
OUT = os.path.join(ROOT, 'data', 'gen_outlook.json')
GUT = 0.888
PHI = NormalDist().cdf
LEARN = lambda k: k // 100 not in (2021, 2022)
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']


def sh(k, n):
    y, m = k // 100, k % 100 - 1 + n
    y += m // 12
    m %= 12
    return y * 100 + m + 1


def days(k):
    return calendar.monthrange(k // 100, k % 100)[1]


def ml(k):
    return f'{MON[k % 100 - 1]} {k // 100}'


def share(w, lo, cv):
    """share (in number, in kg) of fish above lo kg gutted, for a live mean weight w"""
    s2 = math.log(1 + cv * cv)
    sd = math.sqrt(s2)
    mu = math.log(w) - s2 / 2
    L = math.log(lo / GUT)
    return 1 - PHI((L - mu) / sd), 1 - PHI((L - mu - s2) / sd)


D = json.load(io.open(DATA, encoding='utf-8'))
# ---- sea temperature by zone and month (BarentsWatch weekly reports, ISO week -> month of its Thursday, weighted by sites)
_tt = collections.defaultdict(lambda: [0.0, 0])
for r in (D.get('bw_weekly') or {}).get('rows', []):
    if r.get('t') is None or not r.get('nt'):
        continue
    th = dt.date.fromisocalendar(r['y'], r['w'], 4)
    x = _tt[(r['po'], th.year * 100 + th.month)]
    x[0] += r['t'] * r['nt']
    x[1] += r['nt']
TEMP = {key: v[0] / v[1] for key, v in _tt.items() if v[1]}
TEMP_LAST = max((k for _, k in TEMP), default=None)
C = collections.defaultdict(dict)
for c in D['cohort']:
    if c['po']:
        C[(c['po'], c['cohort'])][c['year'] * 100 + c['month']] = c
MONTHS = sorted({k for ser in C.values() for k in ser})
LAST = MONTHS[-1]
ZONES = list(range(1, 14))


def month_growth(po, g, k):
    """production per fish in month k (change in biomass + harvest + dead at half weight; fish appearing or vanishing
    without being declared enter at 0.15 kg or leave at the average weight), TGC (grams), mortality %"""
    ser = C.get((po, g), {})
    a, b = ser.get(sh(k, -1)), ser.get(k)
    if not a or not b or not (a['stock'] or 0) > 2e5 or not b['stock'] or not a['weight_kg'] or not b['weight_kg']:
        return None
    d = (b.get('dead_stk') or 0) + (b.get('loss_stk') or 0)
    out = d * (a['weight_kg'] + b['weight_kg']) / 4
    gap = b['stock'] - a['stock'] + (b.get('harv_stk') or 0) + d
    out += -gap * 0.15 if gap > 0 else -gap * (a['weight_kg'] + b['weight_kg']) / 2
    prod = b['stock'] * b['weight_kg'] - a['stock'] * a['weight_kg'] + (b.get('harv_kg') or 0) + out
    g_fish = prod / ((a['stock'] + b['stock']) / 2)
    T = TEMP.get((po, k))
    w0 = a['weight_kg']
    tgc = ((w0 + g_fish) ** (1 / 3) - w0 ** (1 / 3)) * 10000 / (T * days(k)) if T and T > 1 and w0 + g_fish > 0 else None
    return dict(w0=w0, g=g_fish, T=T, tgc=tgc, mort=100 * d / a['stock'], N=a['stock'])


def agg(g, k, zones=ZONES):
    S = collections.defaultdict(float)
    W = 0
    for po in zones:
        m = month_growth(po, g, k)
        if not m or m['tgc'] is None or not (-1 < m['tgc'] < 6):
            continue
        W += m['N']
        for f in ('w0', 'g', 'T', 'tgc', 'mort'):
            S[f] += m[f] * m['N']
    return {f: v / W for f, v in S.items()} if W > 1e6 else None


def gen_state(g, k, zones=ZONES):
    o = dict(fish=0.0, bio=0.0, n5=0.0, b5=0.0, b6=0.0)
    for po in zones:
        c = C.get((po, g), {}).get(k)
        if not c or not c['stock'] or not c['weight_kg']:
            continue
        o['fish'] += c['stock']
        o['bio'] += c['stock'] * c['weight_kg']
        n5, b5 = share(c['weight_kg'], 5, 0.30)
        o['n5'] += c['stock'] * n5
        o['b5'] += c['stock'] * c['weight_kg'] * GUT * b5
        o['b6'] += c['stock'] * c['weight_kg'] * GUT * share(c['weight_kg'], 6, 0.30)[1]
    o['w'] = o['bio'] / o['fish'] if o['fish'] else None
    return o


# ---- harvest by size class, actual
HA = collections.defaultdict(lambda: collections.defaultdict(float))
ST5 = collections.defaultdict(float)
for (po, g), ser in C.items():
    for k, c in ser.items():
        if c.get('stock') and c.get('weight_kg'):
            ST5[k] += c['stock'] * c['weight_kg'] * GUT * share(c['weight_kg'], 5, 0.30)[1]
for (po, g), ser in C.items():
    for k, c in ser.items():
        if (c.get('harv_stk') or 0) > 0 and c.get('harv_kg'):
            w = c['harv_kg'] / c['harv_stk']
            t = c['harv_kg'] * GUT
            HA[k]['tot'] += t
            HA[k][5] += t * share(w, 5, 0.27)[1]
            HA[k][6] += t * share(w, 6, 0.27)[1]


def tables(origin):
    b = lambda w: min(16, int(w / 0.5))
    tg = collections.defaultdict(lambda: [0, 0])
    hz = collections.defaultdict(lambda: [0, 0])
    hzb = collections.defaultdict(lambda: [0, 0])
    rr = collections.defaultdict(lambda: [0, 0])
    for (po, g), ser in C.items():
        for k, c in ser.items():
            if k > origin or not LEARN(k):
                continue
            p = ser.get(sh(k, -1))
            if not p or not p['weight_kg'] or not (p['stock'] or 0) > 2e5:
                continue
            m = month_growth(po, g, k)
            if m and m['tgc'] is not None and -1 < m['tgc'] < 6 and m['w0'] >= 0.2:
                x = tg[(b(m['w0']), k % 100)]
                x[0] += m['tgc'] * m['N']
                x[1] += m['N']
            hs = c.get('harv_stk') or 0
            x = hz[(b(p['weight_kg']), k % 100)]
            x[0] += hs
            x[1] += p['stock']
            x = hzb[b(p['weight_kg'])]
            x[0] += hs
            x[1] += p['stock']
            if hs > 2e4 and c.get('harv_kg') and c['weight_kg']:
                x = rr[b(p['weight_kg'])]
                x[0] += c['harv_kg']
                x[1] += hs * p['weight_kg']

    def tgc(w, m):
        for d in (0, 1, -1, 2, -2, 3, -3):
            x = tg[(b(max(0.1, w + 0.5 * d)), m)]
            if x[1] > 1e6:
                return x[0] / x[1]
        return 2.5

    def lam(w, m):
        x, y = hz[(b(w), m)], hzb[b(w)]
        return x[0] / x[1] if x[1] > 5e6 else (y[0] / y[1] if y[1] else 0)

    ratio = lambda w: (lambda x: x[0] / x[1] if x[1] else 1.15)(rr[b(w)])
    return tgc, lam, ratio


def tnorm(po, m, origin):
    v = [TEMP[(po, y * 100 + m)] for y in range(2019, origin // 100 + 1)
         if (po, y * 100 + m) in TEMP and y * 100 + m <= origin and LEARN(y * 100 + m)]
    return sum(v[-3:]) / len(v[-3:]) if v else 8.0


def simulate(origin, H=12, own=0.7):
    tgc, lam, ratio = tables(origin)
    out = collections.defaultdict(lambda: collections.defaultdict(float))
    for (po, g), ser in C.items():
        c = ser.get(origin)
        if not c or not (c['stock'] or 0) > 2e5 or not c['weight_kg']:
            continue
        N, w = c['stock'], c['weight_kg']
        rs, mr = [], []
        for j in range(3):
            m = month_growth(po, g, sh(origin, -j))
            if m:
                mr.append(max(0, m['mort']) / 100)
                if m['tgc'] is not None and -1 < m['tgc'] < 6 and m['w0'] >= 0.3:
                    rs.append(m['tgc'] / tgc(m['w0'], sh(origin, -j) % 100))
        rho = max(0.75, min(1.3, (sum(rs) / len(rs)) ** own)) if rs else 1.0
        mort = sum(mr) / len(mr) if mr else 0.01
        anom = TEMP.get((po, origin), tnorm(po, origin % 100, origin)) - tnorm(po, origin % 100, origin)
        for i in range(1, H + 1):
            k = sh(origin, i)
            mm = k % 100
            T = tnorm(po, mm, origin) + anom * 0.6 ** i
            hn = N * min(0.9, lam(w, mm))
            wh = w * ratio(w)
            wr = max(0.5 * w, (N * w - hn * wh) / (N - hn)) if hn > 0 and N > hn else w
            if hn > 0:
                kg = hn * wh * GUT
                out[k]['tot'] += kg
                out[k][5] += kg * share(wh, 5, 0.27)[1]
                out[k][6] += kg * share(wh, 6, 0.27)[1]
            N = max(0, N - hn - N * mort)
            w = (wr ** (1 / 3) + tgc(wr, mm) * rho * T * 30.4 / 10000) ** 3
            out[k]['st5'] += N * w * GUT * share(w, 5, 0.30)[1]
            out[k]['n%d' % g] += N
            out[k]['b%d' % g] += N * w
    return out


def relative(origin, own):
    """projection of the 12 months after origin: actual harvest a year earlier x simulation(origin) / simulation(origin - 12)"""
    o0 = sh(origin, -12)
    a, b = simulate(o0, own=own), simulate(origin, own=own)
    rows = []
    for i in range(1, 13):
        k0, k1 = sh(o0, i), sh(origin, i)
        r = {'k': k1}
        for f in ('tot', 5, 6):
            r[f] = HA[k0][f] * b[k1][f] / a[k0][f] if a[k0][f] else None
            r['ly_%s' % f] = HA[k0][f]
        rows.append(r)
    return rows, a, b


def nowcast(last):
    """harvest (t live) of the month after the last register month, from whole-fish exports (SSB 03024)"""
    rows = (D.get('ssb_weekly') or {}).get('rows') or []
    W = collections.defaultdict(float)
    for yw, _p, w, *_ in rows:
        W[yw] += w or 0
    ex, dd = collections.defaultdict(float), collections.defaultdict(int)
    for yw, t in W.items():
        try:
            mon = dt.date.fromisocalendar(yw // 100, yw % 100, 1)
        except ValueError:
            continue
        for i in range(7):
            x = mon + dt.timedelta(days=i)
            k = x.year * 100 + x.month
            ex[k] += t / 7
            dd[k] += 1
    full = lambda k: dd.get(k, 0) >= days(k)
    H = collections.defaultdict(float)
    for r in D['records']:
        H[r['year'] * 100 + r['month']] += (r.get('uttak_kg') or 0) / 1000
    R = [H[k] / ex[k] for k in sorted(H) if k <= last and ex.get(k) and full(k)][-25:]
    nxt, nn = sh(last, 1), sh(last, 2)
    out = {}
    if full(nxt) and len(R) >= 6:
        ws = sum(0.7 ** (len(R) - 1 - i) for i in range(len(R)))
        r = sum(0.7 ** (len(R) - 1 - i) * x for i, x in enumerate(R)) / ws
        out['next'] = {'k': nxt, 't': ex[nxt] * r, 'ly': H.get(sh(nxt, -12))}
    # month after: exports so far against the same days a year earlier
    if dd.get(nn):
        n = dd[nn]
        a = sum(W[yw] for yw in W if _in_month(yw, nn, n))
        b = sum(W[yw] for yw in W if _in_month(yw, sh(nn, -12), n))
        if b:
            out['after'] = {'k': nn, 'days': n, 'yoy': 100 * (a / b - 1)}
    return out


def _in_month(yw, k, ndays):
    try:
        mon = dt.date.fromisocalendar(yw // 100, yw % 100, 1)
    except ValueError:
        return False
    th = mon + dt.timedelta(days=3)
    return th.year * 100 + th.month == k and th.day <= ndays + 3


def gap_index(series_by_k, season_end):
    """season October (y-1) -> September (y): lowest 3-month average of 5 kg+ between April and September / average of
    October-March before"""
    y = season_end // 100
    win = [series_by_k.get(y * 100 + m) for m in range(4, 10)]
    win_ok = [v for v in win if v is not None]
    pre = [series_by_k.get(k) for k in [(y - 1) * 100 + m for m in (10, 11, 12)] + [y * 100 + m for m in (1, 2, 3)]]
    if len(win_ok) < 6 or any(v is None for v in pre):
        return None
    lo = min(sum(win[i:i + 3]) / 3 for i in range(4))
    j = min(range(4), key=lambda i: sum(win[i:i + 3]))
    return {'ratio': lo / (sum(pre) / 6), 'low': lo / 1e6, 'pre': sum(pre) / 6 / 1e6, 'when': f'{MON[3 + j]}-{MON[5 + j]}'}


def gap_txt(G, now):
    a, b = round(100 * min(G)), round(100 * max(G))
    head = f"{a}–{b} % depending on the scenario" if a != b else f"about {a} % in every scenario"
    return f"Lowest point ÷ winter average in the season ahead: {head}, against {100 * now:.0f} % this year. "


def pct(a, b):
    return 100 * (a / b - 1) if a is not None and b else None


def sgn(v, d=0):
    if v is None:
        return '—'
    v = round(v, d) + 0.0
    return (f'{v:+.{d}f} %' if v else f'{0:.{d}f} %').replace('-', '−')


def main():
    k = LAST
    Y = k // 100
    m = k % 100
    old = Y - 1 if m >= 5 else Y - 2      # generation being harvested
    new = old + 1
    k1 = sh(k, -12)
    # ---- history of the transition gap
    s5 = {kk: v[5] for kk, v in HA.items()}
    hist = []
    for y in range(2018, Y + 1):
        gi = gap_index(s5, y * 100 + 9)
        if gi:
            hist.append(dict(season=f'{y - 1}-{str(y)[2:]}', **{a: round(b, 3) if isinstance(b, float) else b for a, b in gi.items()},
                             spring5=round(sum(HA[y * 100 + mm][5] for mm in range(4, 8)) / 1e6, 1),
                             spring_tot=round(sum(HA[y * 100 + mm]['tot'] for mm in range(4, 8)) / 1e6, 1),
                             st5min=round(min(ST5[y * 100 + mm] for mm in range(4, 10)) / 1e6, 1)))
    # ---- state of play
    so, so1 = gen_state(old, k), gen_state(old - 1, k1)
    sn, sn1 = gen_state(new, k), gen_state(new - 1, k1)
    g3 = lambda g, kk: [agg(g, sh(kk, -j)) for j in range(3)]
    avg3 = lambda L, f: (lambda v: sum(v) / len(v) if v else None)([x[f] for x in L if x and x.get(f) is not None])
    go, go1, gn, gn1 = g3(old, k), g3(old - 1, k1), g3(new, k), g3(new - 1, k1)
    st = dict(k=k, old=old, new=new,
              old_fish=so['fish'] / 1e6, old_fish_ly=so1['fish'] / 1e6, old_bio=so['bio'] / 1e6, old_bio_ly=so1['bio'] / 1e6,
              old_w=so['w'], old_w_ly=so1['w'], old_b5=so['b5'] / 1e6, old_b5_ly=so1['b5'] / 1e6,
              new_fish=sn['fish'] / 1e6, new_fish_ly=sn1['fish'] / 1e6, new_bio=sn['bio'] / 1e6, new_bio_ly=sn1['bio'] / 1e6,
              new_w=sn['w'], new_w_ly=sn1['w'],
              old_gr=avg3(go, 'g'), old_gr_ly=avg3(go1, 'g'), old_tgc=avg3(go, 'tgc'), old_tgc_ly=avg3(go1, 'tgc'),
              old_mort=avg3(go, 'mort'), old_mort_ly=avg3(go1, 'mort'),
              new_gr=avg3(gn, 'g'), new_gr_ly=avg3(gn1, 'g'), new_tgc=avg3(gn, 'tgc'), new_tgc_ly=avg3(gn1, 'tgc'),
              new_mort=avg3(gn, 'mort'), new_mort_ly=avg3(gn1, 'mort'),
              T=avg3(go, 'T'), T_ly=avg3(go1, 'T'),
              harv5_3=sum(HA[sh(k, -j)][5] for j in range(3)) / 1e6, harv5_3_ly=sum(HA[sh(k1, -j)][5] for j in range(3)) / 1e6,
              harv_3=sum(HA[sh(k, -j)]['tot'] for j in range(3)) / 1e6, harv_3_ly=sum(HA[sh(k1, -j)]['tot'] for j in range(3)) / 1e6)
    # temperatures already known beyond the register
    tnew = []
    kk = sh(k, 1)
    while TEMP_LAST and kk <= TEMP_LAST:
        a = [TEMP[(po, kk)] for po in ZONES if (po, kk) in TEMP]
        b = [TEMP[(po, sh(kk, -12))] for po in ZONES if (po, sh(kk, -12)) in TEMP]
        if a and b:
            tnew.append({'k': kk, 't': sum(a) / len(a), 'ly': sum(b) / len(b)})
        kk = sh(kk, 1)
    # ---- scenarios
    SC = [('fade', 0.0, 'Advance fades out'), ('central', 0.7, 'Central: advance mostly kept'), ('fast', 1.0, 'Advance kept in full')]
    scen, sims = {}, {}
    for key, own, lab in SC:
        rows, a, b = relative(k, own)
        sims[key] = (a, b)
        su = lambda f, i0, i1: sum(r[f] or 0 for r in rows[i0:i1])
        sl = lambda f, i0, i1: sum(r['ly_%s' % f] for r in rows[i0:i1])
        per = {}
        # periods: next quarter, the one after, the transition window (April-July) when it falls in the 12 months, last quarter
        months = [r['k'] for r in rows]
        win = [i for i, kk in enumerate(months) if 4 <= kk % 100 <= 7]
        spans = [('next 3 months', 0, 3), ('months 4-6', 3, 6)]
        if len(win) == 4 and win[-1] - win[0] == 3:
            spans.append((f'Apr-Jul {months[win[0]] // 100}', win[0], win[0] + 4))
        spans.append(('months 10-12', 9, 12))
        for nm, i0, i1 in spans:
            per[nm] = {'span': f'{ml(months[i0])} – {ml(months[i1 - 1])}', 'tot': pct(su('tot', i0, i1), sl('tot', i0, i1)),
                       '5': pct(su(5, i0, i1), sl(5, i0, i1)), '6': pct(su(6, i0, i1), sl(6, i0, i1)), 'kt5': su(5, i0, i1) / 1e6}
        # transition-gap index of the projected season, completed with actual months when the season has started
        ser = dict(s5)
        for r in rows:
            ser[r['k']] = r[5]
        y_end = Y + 1 if m >= 10 else Y
        gi = gap_index(ser, y_end * 100 + 9)
        # what the next register should show under this scenario
        n1 = sh(k, 1)
        exp_fish = None
        if b[n1].get('n%d' % old) and a[sh(n1, -12)].get('n%d' % (old - 1)):
            sim_r = b[n1]['n%d' % old] / a[sh(n1, -12)]['n%d' % (old - 1)]
            act_ly = gen_state(old - 1, sh(n1, -12))['fish']
            exp_fish = {'fish': act_ly * sim_r / 1e6, 'ly': act_ly / 1e6}
        scen[key] = {'label': lab, 'own': own, 'periods': per, 'gap': gi, 'next_fish': exp_fish,
                     'months': [{'k': r['k'], 'tot': r['tot'] / 1e6 if r['tot'] else None, 'kt5': r[5] / 1e6 if r[5] else None,
                                 'kt6': r[6] / 1e6 if r[6] else None, 'ly_tot': r['ly_tot'] / 1e6, 'ly5': r['ly_5'] / 1e6, 'ly6': r['ly_6'] / 1e6} for r in rows]}
    nc = nowcast(k)
    # ---- text
    P = []
    f1 = lambda v: '—' if v is None else f'{v:.1f}'
    f2 = lambda v: '—' if v is None else f'{v:.2f}'
    cur_gap = next((h for h in hist if h['season'] == f'{Y - 1}-{str(Y)[2:]}'), None) if m >= 9 else None
    past = [h for h in hist if h['season'] not in ('2020-21', '2021-22')]
    P.append(
        f"<b>State of play, end of {MONL[m - 1]} {Y}.</b> G{old} — the generation being harvested — has "
        f"{f1(st['old_fish'])} M fish left against {f1(st['old_fish_ly'])} M for G{old - 1} a year earlier ({sgn(pct(st['old_fish'], st['old_fish_ly']), 1)}), "
        f"but they weigh {f2(st['old_w'])} kg against {f2(st['old_w_ly'])} kg, so its biomass is {sgn(pct(st['old_bio'], st['old_bio_ly']), 1)} and its stock of fish over 5 kg gutted "
        f"{sgn(pct(st['old_b5'], st['old_b5_ly']), 0)} ({st['old_b5']:.0f} kt against {st['old_b5_ly']:.0f}). "
        f"Over the last three months it grew {f2(st['old_gr'])} kg per fish a month against {f2(st['old_gr_ly'])} ({sgn(pct(st['old_gr'], st['old_gr_ly']), 0)}) "
        f"in water at {f1(st['T'])} °C against {f1(st['T_ly'])} °C — temperature-corrected (TGC) {sgn(pct(st['old_tgc'], st['old_tgc_ly']), 0)} — and lost "
        f"{f2(st['old_mort'])} % of its fish a month against {f2(st['old_mort_ly'])} %. "
        f"G{new}, which takes over next year, has {f1(st['new_fish'])} M fish ({sgn(pct(st['new_fish'], st['new_fish_ly']), 1)}) at {f2(st['new_w'])} kg against {f2(st['new_w_ly'])} "
        f"(biomass {sgn(pct(st['new_bio'], st['new_bio_ly']), 0)}), growing {sgn(pct(st['new_gr'], st['new_gr_ly']), 0)} faster per fish, TGC {sgn(pct(st['new_tgc'], st['new_tgc_ly']), 0)}. "
        f"Fish over 5 kg harvested in the last three months: {st['harv5_3']:.0f} kt gutted against {st['harv5_3_ly']:.0f} ({sgn(pct(st['harv5_3'], st['harv5_3_ly']), 0)}), "
        f"out of {st['harv_3']:.0f} kt in all ({sgn(pct(st['harv_3'], st['harv_3_ly']), 0)}).")
    gh = ' · '.join(f"{h['season']} <b>{100 * h['ratio']:.0f} %</b>" + (' <span style="color:var(--muted)">(atypical)</span>' if h['season'] in ('2020-21', '2021-22') else '') for h in hist)
    P.append(
        f"<b>The gap between generations.</b> Until 2024, the big fish ran short every year while the harvest moved to the new generation: "
        f"the lowest three months of 5 kg+ harvested between April and September fell to about "
        f"{100 * min(h['ratio'] for h in past if int(h['season'][:4]) < 2024):.0f}–{100 * max(h['ratio'] for h in past if int(h['season'][:4]) < 2024):.0f} % "
        f"of the October–March monthly average, and the market was sold small fish while waiting for the 5+/6+. Lowest point ÷ winter average, season by season: {gh}. "
        + (f"The last two seasons broke the pattern: the 5 kg+ held at {100 * hist[-2]['ratio']:.0f} % and {100 * hist[-1]['ratio']:.0f} % of the winter level "
           f"(in 2024 the shortage of big fish came in the autumn instead, September–December, with only a fifth of the harvest over 5 kg), "
           f"and the stock of 5 kg+ fish at sea never fell below {hist[-2]['st5min']:.0f} and {hist[-1]['st5min']:.0f} kt, against "
           f"{min(h['st5min'] for h in past if int(h['season'][:4]) < 2023):.0f}–{max(h['st5min'] for h in past if int(h['season'][:4]) < 2023):.0f} kt in the years before: "
           f"the new generations now reach harvest weight months earlier." if len(hist) >= 2 and hist[-1]['ratio'] > 0.85 and hist[-2]['ratio'] > 0.8 else ''))
    c, f, s = scen['central'], scen['fade'], scen['fast']
    trans = next((nm for nm in c['periods'] if nm.startswith('Apr-Jul')), None)
    if trans:
        tp = lambda sc, x: sgn(sc['periods'][trans][x], 0)
        verdict = ('no gap in sight' if f['periods'][trans]['5'] is not None and f['periods'][trans]['5'] > -8
                   else 'a gap is possible' if c['periods'][trans]['5'] is not None and c['periods'][trans]['5'] > -8 else 'a gap is likely')
        P.append(
            f"<b>Next transition ({trans}): {verdict}.</b> Projected 5 kg+ harvest against the same months of {int(trans[-4:]) - 1}: "
            f"<b>{tp(c, '5')}</b> if the new generation keeps most of its advance, {tp(f, '5')} if the advance fades out, {tp(s, '5')} if it keeps all of it; "
            f"6 kg+ {tp(f, '6')} to {tp(s, '6')}; all sizes {tp(f, 'tot')} to {tp(s, 'tot')}. "
            + (gap_txt([x['gap']['ratio'] for x in (f, c, s)], hist[-1]['ratio']) if f['gap'] and s['gap'] and c['gap'] and hist else '')
            + ("The risk is rather the other way: if the advance holds, a wave of 6 kg+ in spring–early summer, more than the market took this year. "
               if s['periods'][trans]['6'] is not None and s['periods'][trans]['6'] > 25 else ''))
    nq, q2 = c['periods'].get('next 3 months'), c['periods'].get('months 4-6')
    two = []
    for i in range(2):
        mo = [sc['months'][i] for sc in (f, c, s)]
        kk = mo[0]['k']
        known = nc.get('next') if nc.get('next') and nc['next']['k'] == kk else None
        tt = (f"about {known['t'] * GUT / 1000:.0f} kt gutted ({sgn(pct(known['t'], known['ly']), 0)}, already known from exports)" if known
              else f"{mo[1]['tot']:.0f} kt gutted ({sgn(pct(mo[0]['tot'], mo[0]['ly_tot']), 0)} to {sgn(pct(mo[2]['tot'], mo[2]['ly_tot']), 0)})")
        two.append(f"{MONL[kk % 100 - 1]}: {tt}, of which 5 kg+ about {mo[1]['kt5']:.0f} kt ({sgn(pct(mo[1]['kt5'], mo[1]['ly5']), 0)} on a year earlier) and 6 kg+ {mo[1]['kt6']:.0f} kt ({sgn(pct(mo[1]['kt6'], mo[1]['ly6']), 0)})")
    P.append(
        f"<b>Two-month assumptions.</b> " + '; '.join(two) + ". "
        f"Behind them: G{old} keeps being harvested at the pace usual for its weight (so faster than G{old - 1}, being heavier), its mortality stays at the last three months' level, "
        f"and sea temperature follows the normal with today's anomaly fading. ")
    P.append(
        f"<b>Next months.</b> {nq['span']}: all sizes {sgn(f['periods']['next 3 months']['tot'], 0)} to {sgn(s['periods']['next 3 months']['tot'], 0)} on a year earlier, "
        f"5 kg+ {sgn(nq['5'], 0)} (central). {q2['span']}: all sizes {sgn(f['periods']['months 4-6']['tot'], 0)} to {sgn(s['periods']['months 4-6']['tot'], 0)}, 5 kg+ {sgn(q2['5'], 0)}. "
        + (f"{MONL[nc['after']['k'] % 100 - 1]} so far ({nc['after']['days']} days): whole-fish exports {sgn(nc['after']['yoy'], 0)}. " if nc.get('after') else '')
        + (' '.join(f"Sea temperature {MON[t['k'] % 100 - 1]} {t['k'] // 100}: {t['t']:.1f} °C against {t['ly']:.1f}." for t in tnew)))
    n1 = sh(k, 1)
    pub = f"due early {MONL[sh(n1, 2) % 100 - 1]}"
    ef = c.get('next_fish')
    P.append(
        f"<b>What the {MONL[n1 % 100 - 1]} register ({pub}) will tell.</b> "
        + (f"Fish left in G{old}: about {ef['fish']:.0f} M expected against {ef['ly']:.0f} M for G{old - 1} a year earlier ({sgn(pct(ef['fish'], ef['ly']), 0)}, from {sgn(pct(st['old_fish'], st['old_fish_ly']), 0)} now); "
           f"clearly fewer would mean the big fish are being pulled forward and the spring tail gets thinner, clearly more that harvesting is slowing down. " if ef else '')
        + f"The decisive figure is G{new}'s temperature-corrected growth: still {sgn(pct(st['new_tgc'], st['new_tgc_ly']), 0)} on G{new - 1} now; "
        f"if it stays above about +10 %, read the 'advance kept' column (more 5–6 kg+ in spring, the risk becomes too many big fish); "
        f"if it falls back to zero or below, read 'advance fades' (5 kg+ flat on this year, total volume a little down in the first half). "
        f"Mortality of G{old} and G{new} (now {f2(st['old_mort'])} % and {f2(st['new_mort'])} % a month) moves the volume, not the timing.")
    P.append(
        '<span style="color:var(--muted)">How it is worked out: the same zone-by-generation simulation (growth = usual TGC at that weight and month × the generation\'s own recent advance × expected temperature; '
        'harvest = usual share of the stock taken at that weight and month; mortality = last three months) is run from this month and from the same month a year earlier, '
        'and the ratio of the two is applied to what was really harvested a year earlier, so most of the simulation\'s own errors cancel. Tested from September 2025: '
        'April–July 2026 5 kg+ forecast 206 kt, actual 215 kt; the winter was under-forecast (224 against 312 kt) because growth accelerated. 2021–2022 are left out of what is learned. '
        'Size classes come from average weights with a lognormal spread, so they are estimates. Rebuilt after every register.</span>')
    out = {'meta': {'generated': dt.date.today().isoformat(), 'last': k, 'temp_last': TEMP_LAST},
           'state': st, 'history': hist, 'scenarios': scen, 'nowcast': nc, 'temps_since': tnew, 'paragraphs': P}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':'), default=lambda o: None))
    print(f'gen_outlook: {ml(k)}, G{old}/G{new}; ' + ' | '.join(f"{key}: " + ', '.join(f"{nm} 5+ {sgn(v['5'], 0)}" for nm, v in sc['periods'].items()) for key, sc in scen.items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
