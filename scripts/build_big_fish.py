#!/usr/bin/env python3
"""
Which farmers should have big fish to harvest in the next two months, zone by zone (Norway).

    python3 scripts/build_big_fish.py        -> data/big_fish.json  (no paid call: public data only)

Method
  1. Date of stocking of each site's current cycle: the end of its last fallow period, read from the weekly status of every
     site kept by update_barentswatch.py (data/bw_site_status.json: a = fish reported, f = fallow, - = no report).
  2. Weight of the fish on each site: the growth curve of its zone (live weight by months at sea, median of the 2019-2025
     generations of the Directorate's biomass register), at the site's age in one and two months.
  3. Chance that the site is harvested within about two months: measured on the history itself (share of sites of the same
     age that were emptied within 9 weeks, 2021 onwards), then combined with the share of fish of 6 kg gutted or more
     expected at the site's estimated weight (log-normal spread, CV 0.27, as elsewhere in the dashboard).
  4. Each company's share of a zone = its sites' capacity (MTB) x harvest chance x big-fish share, over the zone total.
  Research, broodstock, school and public licences are left out. Shares, not tonnes: the stock on each site is not public.
  5. Pace of each farmer: median length of its completed cycles in the zone since 2023 against the zone's (at least 8 cycles).
     A farmer that empties its sites sooner grows its fish faster (bigger smolts, better growth): its sites are aged accordingly.
"""
import collections
import datetime as dt
import io
import json
import math
import os
import re
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
STAT = os.path.join(ROOT, 'data', 'bw_site_status.json')
OUT = os.path.join(ROOT, 'data', 'big_fish.json')
GUT = 0.888
CV = 0.27
# Societes rattachees a leur groupe (le registre les liste a part) : Ocean Farming AS (Ocean Farm 1, a Håbranden) appartient a
# SalMar a 93,4 % ; Mariculture AS (Smart Fish Farm, site « Frøya » en mer de Norvege) est une filiale de SalMar Aker Ocean.
GROUPE = {'ocean farming as': 'SalMar', 'mariculture as': 'SalMar'}
# Sites qui recoivent des poissons deja grands, transferes d'un autre site : leur cycle commence avec des poissons de plusieurs mois.
# Havfarm 1 « Jostein Albert » (Nordlaks, site 39777 Ytre Hadseløya) recoit des saumons d'environ 2 kg -> environ 9 mois de croissance.
DECALAGE = {'39777': 9.0}
SITES_LARGE = {'39777': 'Havfarm 1 "Jostein Albert" (Nordlaks)', '33757': 'Ocean Farm 1 (SalMar, Ocean Farming AS)',
               '45196': 'Smart Fish Farm (SalMar Aker Ocean, Mariculture AS) — not stocked yet'}
PAS_COMMERCIAL = re.compile(r'fylkeskommune|akademi|\bfou\b|forskning|genetics|aquagen|stamfisk|benchmark|inkubator|universitet|skole|'
                            r'visning|havforskning|nofima|rogn|polarfeed', re.I)


def p_big(w_live, lo=6.0):
    if not w_live: return 0.0
    s2 = math.log(1 + CV * CV)
    z = (math.log(lo / GUT) - (math.log(w_live) - s2 / 2)) / math.sqrt(s2)
    return 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))


def main():
    d = json.load(io.open(DATA, encoding='utf-8'))
    st = json.load(io.open(STAT, encoding='utf-8'))
    R, C = d['bw_register'], d['cohort']
    R['site_org'] = {k: GROUPE.get((v or '').lower(), v) for k, v in R['site_org'].items()}
    y0, w0 = map(int, st['first'].split('-'))
    n = max(len(v) for v in st['sites'].values())
    weeks = [dt.date.fromisocalendar(y0, w0, 1) + dt.timedelta(weeks=i) for i in range(n)]
    last = n - 1
    while last > 0 and not any(len(v) > last and v[last] in 'af' for v in st['sites'].values()): last -= 1

    # courbes de croissance par zone (poids vif selon l'age en mois)
    cur = collections.defaultdict(lambda: collections.defaultdict(list))
    for c in C:
        if not c['po'] or c['cohort'] < 2019 or not c['weight_kg'] or (c['stock'] or 0) < 50000: continue
        a = round(c['age_months'])
        if 0 <= a <= 30: cur[c['po']][a].append(c['weight_kg'])
    curve = {po: {a: statistics.median(v) for a, v in A.items() if len(v) >= 2} for po, A in cur.items()}

    def poids(po, age):
        A = curve.get(po) or {}
        if not A: return None
        ks = sorted(A); a = age
        if a <= ks[0]: return A[ks[0]]
        if a >= ks[-1]: return A[ks[-1]]
        lo = max(k for k in ks if k <= a); hi = min(k for k in ks if k >= a)
        return A[lo] if hi == lo else A[lo] + (A[hi] - A[lo]) * (a - lo) / (hi - lo)

    def debut(s, i):
        if i >= len(s) or s[i] != 'a': return None
        j, gap, k = i, 0, i
        while k >= 0:
            if s[k] == 'a': gap, j = 0, k
            elif s[k] in 'f-':
                gap += 1
                if gap >= 3: return j
            else: return None
            k -= 1
        return None

    def vide(s, i, h):
        run = 0
        for k in range(i + 1, min(len(s), i + 1 + h)):
            run = run + 1 if s[k] in 'f-' else 0
            if run >= 3: return True
        return False

    commercial = lambda site: not PAS_COMMERCIAL.search(R['site_org'].get(site) or '')
    # probabilite d'etre vide sous 9 semaines selon l'age, mesuree sur l'historique (origines mensuelles depuis 2021)
    i0 = next(i for i, w in enumerate(weeks) if w >= dt.date(2021, 1, 1))
    hist = collections.defaultdict(lambda: [0, 0])
    for i in range(i0, last - 9, 4):
        for site, s in st['sites'].items():
            if not R['site_po'].get(site) or not commercial(site): continue
            j = debut(s, i)
            if j is None: continue
            b = min(26, int(((weeks[i] - weeks[j]).days / 30.44) // 2) * 2)
            hist[b][0] += 1; hist[b][1] += vide(s, i, 9)
    p_vide = {b: v[1] / v[0] for b, v in hist.items() if v[0] >= 30}
    pv = lambda age: p_vide.get(min(26, int(age // 2) * 2), 0.0)

    # rythme de chaque eleveur dans chaque zone : duree mediane de ses cycles termines depuis 2023 comparee a celle de la zone.
    # Des cycles plus courts sans maladie = poissons qui atteignent plus vite leur poids (gros smolts, bonne croissance) :
    # on vieillit alors leurs sites d'autant (age x rythme, borne entre 0,8 et 1,5 ; au moins 8 cycles termines).
    durees = collections.defaultdict(list)
    for site, s in st['sites'].items():
        po = R['site_po'].get(site)
        if not po or not commercial(site): continue
        for k in range(1, last + 1):
            if s[k] in 'f-' and s[k - 1] == 'a' and s[k:k + 3].count('a') == 0 and weeks[k] >= dt.date(2023, 1, 1):
                j = debut(s, k - 1)
                if j is not None and (weeks[k] - weeks[j]).days > 120: durees[(po, R['site_org'].get(site))].append((weeks[k] - weeks[j]).days / 30.44)
    zone_med = {}
    for (po, co), L in durees.items(): zone_med.setdefault(po, []).extend(L)
    zone_med = {po: statistics.median(L) for po, L in zone_med.items()}
    rythme = {k: max(0.8, min(1.5, zone_med[k[0]] / statistics.median(L))) for k, L in durees.items() if len(L) >= 8}
    now = weeks[last]
    sites = []
    for site, s in st['sites'].items():
        po = R['site_po'].get(site)
        if not po or not commercial(site): continue
        j = debut(s, last)
        if j is None: continue
        age = (now - weeks[j]).days / 30.44 + DECALAGE.get(site, 0.0)
        f = rythme.get((po, R['site_org'].get(site)), 1.0)
        age_eq = age * f                                   # age equivalent dans la zone, au rythme de cet eleveur
        w1, w2 = poids(po, age_eq + f), poids(po, age_eq + 2 * f)
        big = max(p_big(w1), p_big(w2))
        s5 = max(p_big(w1, 5) - p_big(w1), p_big(w2, 5) - p_big(w2))
        score = (R['site_cap'].get(site) or 0) * pv(age_eq) * big
        score56 = (R['site_cap'].get(site) or 0) * pv(age_eq) * s5
        sites.append({'id': site, 'name': R['site_name'].get(site), 'co': R['site_org'].get(site), 'po': po, 'cap': R['site_cap'].get(site) or 0,
                      'stocked': weeks[j].isoformat(), 'age': round(age, 1), 'g2': round(w2 * GUT, 2) if w2 else None,
                      'pace': round(f, 2), 'p_harvest': round(pv(age_eq), 3), 'note': SITES_LARGE.get(site, ''), 'p6': round(big, 3), 'p56': round(s5, 3), 'score': score, 'score56': score56})
    zones = []
    for po in sorted({x['po'] for x in sites}):
        L = [x for x in sites if x['po'] == po]
        tot, tot56 = sum(x['score'] for x in L), sum(x['score56'] for x in L)
        if not tot and not tot56: continue
        cos = collections.defaultdict(lambda: {'s6': 0.0, 's56': 0.0, 'sites': 0, 'cap': 0, 'pace': 1.0})
        for x in L:
            if x['score'] + x['score56'] <= 0: continue
            c = cos[x['co']]; c['s6'] += x['score']; c['s56'] += x['score56']; c['sites'] += 1; c['cap'] += x['cap']; c['pace'] = x['pace']
        zones.append({'po': po, 'score6': round(tot), 'score56': round(tot56),
                      'companies': sorted([{'co': k, 'share6': round(100 * v['s6'] / tot, 1) if tot else 0, 'share56': round(100 * v['s56'] / tot56, 1) if tot56 else 0,
                                            'sites': v['sites'], 'cap': v['cap'], 'pace': v['pace']} for k, v in cos.items()], key=lambda c: -c['share6'] - c['share56'] / 2)[:12],
                      'cycle_months': round(zone_med.get(po, 0), 1),
                      'sites': sorted([{k: v for k, v in x.items() if k not in ('score', 'score56', 'po')} for x in L if x['score'] + x['score56'] > 0],
                                      key=lambda x: -(x['p_harvest'] * (x['p6'] + x['p56'] / 2)))[:15]})
    # ---- durees de cycle par eleveur et par zone (cycles termines depuis 2023) ----
    maladie = collections.defaultdict(list)                     # site -> [(debut aaaass, fin aaaass, maladie)]
    for x in (d.get('bw_weekly') or {}).get('site_dis', []):
        maladie[str(x[0])].append((x[3], x[4], x[2]))
    tous = []
    yw = lambda k: weeks[k].isocalendar()[0] * 100 + weeks[k].isocalendar()[1]
    det = collections.defaultdict(lambda: {'len': [], 'len_ok': [], 'len_dis': [], 'fallow': [], 'by_year': collections.defaultdict(list), 'disease': 0})
    for site, s in st['sites'].items():
        po = R['site_po'].get(site); co = R['site_org'].get(site)
        if not po or not commercial(site): continue
        k = 1
        while k <= last:
            if s[k] in 'f-' and s[k - 1] == 'a' and s[k:k + 3].count('a') == 0:
                j = debut(s, k - 1)
                if j is not None and weeks[k] >= dt.date(2023, 1, 1) and (weeks[k] - weeks[j]).days > 120:
                    m = (weeks[k] - weeks[j]).days / 30.44
                    types = sorted({t for a, b, t in maladie.get(site, []) if a <= yw(k) and b >= yw(j)})
                    tous.append({'po': po, 'co': co, 'len': m, 'dis': types})
                    for key in ((po, co), (0, co), (po, '*')):
                        x = det[key]; x['len'].append(m); x['by_year'][weeks[k].year].append(m)
                        (x['len_dis'] if types else x['len_ok']).append(m)
                        if types: x['disease'] += 1
                    # jachere qui suit : semaines jusqu'a la prochaine mise en mer
                    e = k
                    while e <= last and s[e] != 'a': e += 1
                    if e <= last:
                        for key in ((po, co), (0, co), (po, '*')): det[key]['fallow'].append(e - k)
            k += 1
    def q(L, p):
        L = sorted(L); i = (len(L) - 1) * p; a = int(i); b = min(a + 1, len(L) - 1)
        return L[a] + (L[b] - L[a]) * (i - a)
    actifs = collections.defaultdict(list)
    for x in sites: actifs[(x['po'], x['co'])].append(x['age']); actifs[(0, x['co'])].append(x['age'])
    cyc = []
    for (po, co), x in det.items():
        if co == '*' or len(x['len']) < 3: continue
        zmed = det[(po, '*')]['len'] if po else [m for (p2, c2), y in det.items() if c2 == '*' for m in y['len']]
        cyc.append({'po': po, 'co': co, 'cycles': len(x['len']), 'median': round(statistics.median(x['len']), 1),
                    'p25': round(q(x['len'], .25), 1), 'p75': round(q(x['len'], .75), 1),
                    'pace': round(statistics.median(zmed) / statistics.median(x['len']), 2) if zmed else None,
                    'fallow_weeks': round(statistics.median(x['fallow'])) if x['fallow'] else None,
                    'by_year': {str(a): round(statistics.median(L), 1) for a, L in sorted(x['by_year'].items()) if len(L) >= 2},
                    'disease_share': round(100 * x['disease'] / len(x['len'])),
                    'median_ok': round(statistics.median(x['len_ok']), 1) if len(x['len_ok']) >= 3 else None,
                    'median_dis': round(statistics.median(x['len_dis']), 1) if len(x['len_dis']) >= 3 else None,
                    'active_sites': len(actifs.get((po, co), [])), 'active_age': round(statistics.median(actifs[(po, co)]), 1) if actifs.get((po, co)) else None})
    # rythme national d'un eleveur : moyenne de ses rythmes de zone ponderee par ses cycles (les zones du nord ont des cycles plus longs :
    # comparer a la mediane nationale penaliserait les eleveurs du nord)
    for c in cyc:
        if c['po'] == 0:
            Z = [(z['pace'], z['cycles']) for z in cyc if z['co'] == c['co'] and z['po'] and z['pace']]
            c['pace'] = round(sum(p * n for p, n in Z) / sum(n for _, n in Z), 2) if Z else None
    # impact des maladies : ecart de duree de chaque cycle touche a la mediane des cycles sains de sa zone
    sain = {po: statistics.median(det[(po, '*')]['len_ok']) for (po, co) in det if co == '*' and len(det[(po, '*')]['len_ok']) >= 5}
    impact = []
    for t in sorted({t for c in tous for t in c['dis']}):
        L = [c for c in tous if t in c['dis'] and c['po'] in sain]
        if len(L) < 3: continue
        ec = [c['len'] - sain[c['po']] for c in L]
        impact.append({'disease': t, 'cycles': len(L), 'median': round(statistics.median([c['len'] for c in L]), 1),
                       'vs_healthy': round(statistics.median(ec), 1), 'shorter_share': round(100 * sum(1 for e in ec if e < -1) / len(ec)),
                       'zones': [[po, k] for po, k in collections.Counter(c['po'] for c in L).most_common()]})
    tous_sains = [c for c in tous if not c['dis']]
    # poids moyen abattu par zone (vide), 12 derniers mois et 12 mois d'avant, depuis le registre de la biomasse
    mois = sorted({c['year'] * 100 + c['month'] for c in C})
    der = mois[-12:]; avant = mois[-24:-12]
    def pm(po, M):
        h = sum(c['harv_stk'] or 0 for c in C if c['po'] == po and c['year'] * 100 + c['month'] in M)
        k = sum(c['harv_kg'] or 0 for c in C if c['po'] == po and c['year'] * 100 + c['month'] in M)
        return (round(k / h * GUT, 2) if h else None), round(k * GUT / 1e6, 1)
    poids_zone = {}
    for po in sorted({c['po'] for c in C if c['po']}):
        (w, v), (wp, vp) = pm(po, set(der)), pm(po, set(avant))
        poids_zone[po] = {'harvest_kg': w, 'harvest_kg_prev': wp, 'harvest_kt': v, 'harvest_kt_prev': vp}
    zones_cyc = [{'po': po, 'cycles': len(x['len']), 'median': round(statistics.median(x['len']), 1),
                  'median_ok': round(statistics.median(x['len_ok']), 1) if len(x['len_ok']) >= 3 else None,
                  'median_dis': round(statistics.median(x['len_dis']), 1) if len(x['len_dis']) >= 3 else None,
                  'disease_share': round(100 * x['disease'] / len(x['len'])), 'active_sites': sum(1 for y in sites if y['po'] == po),
                  'active_age': round(statistics.median([y['age'] for y in sites if y['po'] == po]), 1) if any(y['po'] == po for y in sites) else None,
                  **poids_zone.get(po, {}),
                  'fallow_weeks': round(statistics.median(x['fallow'])) if x['fallow'] else None,
                  'by_year': {str(a): round(statistics.median(L), 1) for a, L in sorted(x['by_year'].items()) if len(L) >= 3}}
                 for (po, co), x in det.items() if co == '*']
    tot_all = sum(z['score6'] for z in zones) or 1
    for z in zones: z['zone_share6'] = round(100 * z['score6'] / tot_all, 1)
    zones.sort(key=lambda z: -z['score6'])
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'week': now.isoformat(),
                    'active_sites': len(sites), 'offshore': [{'id': k, 'name': R['site_name'].get(k), 'what': v, 'po': R['site_po'].get(k),
                    'cap': R['site_cap'].get(k), 'status_last_12_weeks': st['sites'].get(k, '')[-12:]} for k, v in SITES_LARGE.items()], 'backtest': {str(b): round(100 * v, 1) for b, v in sorted(p_vide.items())},
                    'method': 'site age from fallow history (BarentsWatch) x zone growth curve (biomass register) x measured harvest chance by age'},
           'zones': zones,
           'cycles': {'since': '2023-01-01', 'min_cycles': 3, 'farmers': sorted(cyc, key=lambda c: (c['po'], -c['cycles'])),
                      'zones': sorted(zones_cyc, key=lambda z: z['po']), 'disease_impact': impact,
                      'norway': {'cycles': len(tous), 'median': round(statistics.median([c['len'] for c in tous]), 1) if tous else None,
                                 'median_ok': round(statistics.median([c['len'] for c in tous_sains]), 1) if tous_sains else None,
                                 'disease_share': round(100 * (len(tous) - len(tous_sains)) / len(tous)) if tous else None,
                                 'harvest_months': [der[0], der[-1]]}}}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f"data/big_fish.json : {len(sites)} commercial sites with fish, week of {now}, {len(zones)} zones")


if __name__ == '__main__':
    main()
