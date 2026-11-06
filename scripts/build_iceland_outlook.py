#!/usr/bin/env python3
"""
Iceland: how much salmon is coming in the next months, from MAST's site-by-site monthly figures.

    python3 scripts/build_iceland_outlook.py      -> data/iceland_outlook.json   (after build_iceland_mast.py)

1. Stock structure at the last month against a year earlier: biomass and fish by weight class (site average weight with
   a lognormal spread, coefficient of variation 0.30), plus the smolts put to sea and their weight in the first month.
2. Next 3 and 6 months: biomass of fish over 4 kg (next 3 months) and over 3 kg (next 6 months) x the ratio of what was
   then harvested to that biomass, averaged over the last 12 known months. Backtested month by month.
3. The four quarters of next year: every site simulated month by month from its fish and average weight. Growth follows
   Iceland's weight-by-months-at-sea curve (median of all site cycles since 2023), each site keeping part of its own
   advance or delay (three scenarios), corrected by its sea temperature when MAST has it; harvest = share of the stock
   usually taken at that weight (higher once a site has started harvesting); mortality = Iceland's monthly average.
   Everything harvested next year is already at sea (smolts put to sea next year are harvested the year after).
   Backtested from earlier months; the error is shown with the result. MAST's harvest is in tonnes as reported.
"""
import collections
import datetime as dt
import io
import json
import math
import os
import sys
from statistics import NormalDist

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data', 'iceland_mast.json')
OUT = os.path.join(ROOT, 'data', 'iceland_outlook.json')
PHI = NormalDist().cdf
CLASSES = [(0, 1, '<1 kg'), (1, 2, '1–2 kg'), (2, 3, '2–3 kg'), (3, 4, '3–4 kg'), (4, 5, '4–5 kg'), (5, 99, '5 kg+')]


def mi(k):
    return int(k[:4]) * 12 + int(k[5:7]) - 1


def km(i):
    return f'{i // 12}-{i % 12 + 1:02d}'


def share_above(w, lo, cv=0.30):
    """share of the biomass of a site above lo kg, for an average weight w"""
    if lo <= 0:
        return 1.0
    s2 = math.log(1 + cv * cv)
    sd = math.sqrt(s2)
    mu = math.log(w) - s2 / 2
    return 1 - PHI((math.log(lo) - mu - s2) / sd)


def share_fish_above(w, lo, cv=0.30):
    if lo <= 0:
        return 1.0
    s2 = math.log(1 + cv * cv)
    sd = math.sqrt(s2)
    mu = math.log(w) - s2 / 2
    return 1 - PHI((math.log(lo) - mu) / sd)


M = json.load(io.open(SRC, encoding='utf-8'))
S = collections.defaultdict(dict)
for x in M.get('sites', []):
    S[x['site']][x['m']] = x
NAT = {n['m']: n for n in M.get('national', [])}
TEMP = collections.defaultdict(dict)
for t in M.get('temp', []):
    if t.get('t') is not None:
        TEMP[t['site']][t['m']] = t['t']


def cyc_age(ser, k):
    start = None
    for kk in sorted(x for x in ser if x <= k):
        if ser[kk]['fish'] > 0 and start is None:
            start = kk
        if ser[kk]['fish'] <= 0:
            start = None
    return mi(k) - mi(start) if start else None


def site_w(x):
    return x['bio_t'] * 1000 / x['fish'] if x.get('fish') and x.get('bio_t') else None


def structure(k):
    o = {c[2]: {'t': 0.0, 'fish': 0.0} for c in CLASSES}
    for ser in S.values():
        x = ser.get(k)
        w = site_w(x) if x else None
        if not w:
            continue
        for lo, hi, lab in CLASSES:
            o[lab]['t'] += x['bio_t'] * (share_above(w, lo) - share_above(w, hi))
            o[lab]['fish'] += x['fish'] * (share_fish_above(w, lo) - share_fish_above(w, hi))
    return o


def big(k, lo):
    return sum(ser[k]['bio_t'] * share_above(site_w(ser[k]), lo) for ser in S.values() if k in ser and site_w(ser[k]))


def tnorm(site, m, upto):
    v = [t for kk, t in TEMP.get(site, {}).items() if int(kk[5:7]) == m and kk <= upto]
    return sum(v) / len(v) if v else None


def learn(origin):
    curve, hz, mort = collections.defaultdict(list), collections.defaultdict(lambda: [0, 0]), [0, 0]
    tgc = []
    for s, ser in S.items():
        ks = sorted(ser)
        for a, b in zip(ks, ks[1:]):
            if b > origin or mi(b) - mi(a) != 1:
                continue
            x, y = ser[a], ser[b]
            w = site_w(x)
            if not w:
                continue
            age = cyc_age(ser, a)
            if age is not None:
                curve[age].append(w)
            started = 1 if (x.get('out') or 0) > 0 else 0
            h = hz[(min(14, int(w / 0.5)), started)]
            h[0] += y.get('out') or 0
            h[1] += x['fish']
            mort[0] += y.get('dead') or 0
            mort[1] += x['fish']
    C = {a: sorted(v)[len(v) // 2] for a, v in curve.items() if len(v) >= 3}
    H = {b: v[0] / v[1] for b, v in hz.items() if v[1] > 0}
    return C, H, (mort[0] / mort[1] if mort[1] else 0.01)


def simulate(origin, H=15, keep=0.7):
    C, HZ, MR = learn(origin)
    ages = sorted(C)
    if not ages:
        return {}

    def curve(a):
        a = max(ages[0], min(ages[-1], a))
        while a not in C:
            a -= 1
        return C[a]

    out = collections.Counter()
    for s, ser in S.items():
        x = ser.get(origin)
        w = site_w(x) if x else None
        if not w:
            continue
        N, age = x['fish'], cyc_age(ser, origin) or 0
        rel = w / curve(age)
        started = 1 if (x.get('out') or 0) > 0 else 0
        anom = None
        if origin in TEMP.get(s, {}) and tnorm(s, int(origin[5:7]), origin) is not None:
            anom = TEMP[s][origin] - tnorm(s, int(origin[5:7]), origin)
        for h in range(1, H + 1):
            r = 1 + (rel - 1) * keep ** h
            g = curve(age + h) / curve(age + h - 1) if age + h <= ages[-1] else 1.03
            if anom is not None:               # ~ +6 % de croissance mensuelle par degre au-dessus de la normale du site
                g = 1 + (g - 1) * max(0.5, 1 + 0.06 * anom * 0.6 ** h)
            w2 = max(w, w * g * (r / (1 + (rel - 1) * keep ** (h - 1))))
            hz = HZ.get((min(14, int(w / 0.5)), started), HZ.get((min(14, int(w / 0.5)), 0), 0))
            n_out = N * hz
            out[km(mi(origin) + h)] += n_out * (w + w2) / 2 / 1000
            if n_out > 0.02 * N:
                started = 1
            N = max(0, N - n_out - N * MR)
            w = w2
    return out


def quarters(series):
    Q = collections.Counter()
    for k, v in series.items():
        Q[f'{k[:4]}-Q{(int(k[5:7]) - 1) // 3 + 1}'] += v
    return Q


def main():
    ks = sorted(NAT)
    last = M.get('sites_last_month') or ks[-1]
    y = int(last[:4])
    ly = km(mi(last) - 12)
    out = {'meta': {'generated': dt.date.today().isoformat(), 'last': last, 'temp_months': len({m for t in TEMP.values() for m in t})}}
    out['structure'] = {'now': structure(last), 'year_before': structure(ly), 'k': last, 'k_ly': ly}
    # ---- 3 et 6 mois : biomasse des gros poissons x rapport recent
    hist = []
    for o in ks:
        i = ks.index(o)
        if o < '2023-12':
            continue
        h3 = sum(NAT[k]['harvest_t'] for k in ks[i + 1:i + 4]) if i + 3 < len(ks) else None
        h6 = sum(NAT[k]['harvest_t'] for k in ks[i + 1:i + 7]) if i + 6 < len(ks) else None
        hist.append({'k': o, 'b4': big(o, 4), 'b3': big(o, 3), 'h3': h3, 'h6': h6})
    def ratio(upto, f, b, n=12):
        v = [x[f] / x[b] for x in hist if x[f] and x[b] and mi(x['k']) + (3 if f == 'h3' else 6) <= mi(upto)][-n:]
        return sum(v) / len(v) if len(v) >= 4 else None
    bt3, bt6 = [], []
    for x in hist:
        r3, r6 = ratio(x['k'], 'h3', 'b4'), ratio(x['k'], 'h6', 'b3')
        if r3 and x['h3']:
            bt3.append(100 * (x['b4'] * r3 / x['h3'] - 1))
        if r6 and x['h6']:
            bt6.append(100 * (x['b3'] * r6 / x['h6'] - 1))
    now = next(x for x in hist if x['k'] == last)
    r3, r6 = ratio(last, 'h3', 'b4'), ratio(last, 'h6', 'b3')
    ly3 = sum(NAT[k]['harvest_t'] for k in [km(mi(ly) + j) for j in range(1, 4)] if k in NAT)
    ly6 = sum(NAT[k]['harvest_t'] for k in [km(mi(ly) + j) for j in range(1, 7)] if k in NAT)
    mae = lambda v: sum(abs(e) for e in v) / len(v) if v else None
    out['near'] = {'b4': now['b4'], 'b3': now['b3'], 'b4_ly': big(ly, 4), 'b3_ly': big(ly, 3), 'r3': r3, 'r6': r6,
                   'h3': now['b4'] * r3 if r3 else None, 'h6': now['b3'] * r6 if r6 else None, 'ly3': ly3, 'ly6': ly6,
                   'err3': mae(bt3), 'err6': mae(bt6), 'n3': len(bt3), 'n6': len(bt6),
                   'span3': f'{km(mi(last) + 1)} – {km(mi(last) + 3)}', 'span6': f'{km(mi(last) + 1)} – {km(mi(last) + 6)}',
                   'history': [{'k': x['k'], 'b4': round(x['b4']), 'b3': round(x['b3']), 'h3': x['h3'], 'h6': x['h6']} for x in hist]}
    # ---- annee suivante par trimestre (simulation), avec test sur le passe
    H = (y + 1) * 12 + 11 - mi(last)
    sc = {}
    for nm, keep in (('fades', 0.5), ('central', 0.7), ('kept', 0.9)):
        sc[nm] = {q: round(v) for q, v in quarters(simulate(last, H, keep)).items()}
    act = quarters({k: NAT[k]['harvest_t'] for k in ks})
    bts = []
    for o in [k for k in ks if '2024-09' <= k <= km(mi(last) - 3)]:
        sim = simulate(o, 12, 0.7)
        kk = [k for k in sim if k in NAT]
        if len(kk) >= 6:
            s_, a_ = sum(sim[k] for k in kk), sum(NAT[k]['harvest_t'] for k in kk)
            bts.append({'from': o, 'months': len(kk), 'sim': round(s_), 'actual': round(a_), 'err_pct': round(100 * (s_ / a_ - 1), 1)})
    out['year'] = {'year': y + 1, 'scenarios': sc, 'actual_quarters': {q: round(v) for q, v in act.items()}, 'backtest': bts,
                   'temperature_used': bool(TEMP)}
    # ---- smolts mis a l'eau et poids au premier mois
    sm = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for s, ser in S.items():
        prev = 0
        for k in sorted(ser):
            x = ser[k]
            if x.get('in') and prev == 0 and site_w(x):
                o = sm[k[:4]]
                o[0] += x['fish']
                o[1] += x['fish'] * site_w(x)
                o[2] += 1
            prev = x['fish']
    out['smolt_weight'] = {yy: {'sites': v[2], 'kg': v[1] / v[0]} for yy, v in sorted(sm.items()) if v[0]}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f"iceland outlook: {last}; next 3 months {out['near']['h3']:.0f} t (a year earlier {ly3:.0f}), next 6 {out['near']['h6']:.0f} t ({ly6:.0f}); "
          f"{y + 1}: " + ', '.join(f"{nm} {sum(v for q, v in s.items() if q.startswith(str(y + 1)))}" for nm, s in sc.items()) + f"; backtests {[b['err_pct'] for b in bts]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
