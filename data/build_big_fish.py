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
    yw_last = now.isocalendar()[0] * 100 + now.isocalendar()[1]
    en_cours = collections.defaultdict(set)                      # site -> maladies declarees encore en cours (dernieres 4 semaines)
    for x in (d.get('bw_weekly') or {}).get('site_dis', []):
        if x[4] >= yw_last - 4: en_cours[str(x[0])].add(x[2])
    s2 = math.log(1 + CV * CV)
    def part_t(w_live, lo, hi=None):                              # part du TONNAGE (vide) entre lo et hi kg vides
        if not w_live: return 0.0
        mu = math.log(w_live) - s2 / 2
        F = lambda g: 0.5 * (1 + math.erf(((mu + s2 - math.log(g / GUT)) / math.sqrt(s2)) / math.sqrt(2)))
        return F(lo) - (F(hi) if hi else 0)
    sites = []
    for site, s in st['sites'].items():
        po = R['site_po'].get(site)
        if not po or not commercial(site): continue
        j = debut(s, last)
        if j is None: continue
        age = (now - weeks[j]).days / 30.44 + DECALAGE.get(site, 0.0)
        f = rythme.get((po, R['site_org'].get(site)), 1.0)
        age_eq = age * f                                   # age equivalent dans la zone, au rythme de cet eleveur
        mal = en_cours.get(site, set())
        # ILA : vidage force plus tot (cycles -1,1 mois), poissons au poids de la zone sans bonus de rythme ;
        # PD : croissance ralentie et cycles plus longs (+1,1 mois). Ecarts mesures sur les cycles depuis 2023.
        age_h = age_eq + (1.1 if 'ILA' in mal else 0) - (1.1 if 'PD' in mal else 0)
        age_w = (age if 'ILA' in mal else age_eq) - (1.1 if 'PD' in mal else 0)
        w1, w2 = poids(po, age_w + f), poids(po, age_w + 2 * f)
        big = max(p_big(w1), p_big(w2))
        s5 = max(p_big(w1, 5) - p_big(w1), p_big(w2, 5) - p_big(w2))
        score = (R['site_cap'].get(site) or 0) * pv(age_h) * big
        score56 = (R['site_cap'].get(site) or 0) * pv(age_h) * s5
        wm = (w1 + w2) / 2 if w1 and w2 else (w1 or w2)
        sites.append({'id': site, 'name': R['site_name'].get(site), 'co': R['site_org'].get(site), 'po': po, 'cap': R['site_cap'].get(site) or 0,
                      'stocked': weeks[j].isoformat(), 'age': round(age, 1), 'g2': round(w2 * GUT, 2) if w2 else None,
                      'pace': round(f, 2), 'p_harvest': round(pv(age_h), 3), 'note': SITES_LARGE.get(site, ''), 'disease': sorted(mal),
                      'q56': part_t(wm, 5, 6), 'q6': part_t(wm, 6), 'p6': round(big, 3), 'p56': round(s5, 3), 'score': score, 'score56': score56})
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
    # ---- classement des eleveurs : tonnes de 5-6 kg et 6 kg+ attendues sur les deux mois qui suivent le registre ----
    mois_r = sorted({c['year'] * 100 + c['month'] for c in C}); dern = mois_r[-1]
    nxt = lambda k: k + 1 if k % 100 < 12 else (k // 100 + 1) * 100 + 1
    cibles = [nxt(dern), nxt(nxt(dern))]
    def recolte(ym, ratio=None, vol=None):
        z = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        for c in C:
            if c['year'] * 100 + c['month'] != ym or not c['po'] or not c['harv_stk'] or not c['harv_kg']: continue
            w = c['harv_kg'] / c['harv_stk'] * ((ratio or {}).get(c['po'], 1.0)); t = c['harv_stk'] * w * GUT / 1000 * ((vol or {}).get(c['po'], 1.0))
            x = z[c['po']]; x[0] += t; x[1] += t * part_t(w, 5, 6); x[2] += t * part_t(w, 6)
        return z
    def ytd(y):
        h, k = collections.defaultdict(float), collections.defaultdict(float)
        for c in C:
            if c['year'] == y and c['month'] <= dern % 100 and c['harv_stk']: h[c['po']] += c['harv_stk']; k[c['po']] += c['harv_kg']
        return {po: k[po] / h[po] for po in h if h[po]}
    def bio(ym):
        b = collections.defaultdict(float)
        for c in C:
            if c['year'] * 100 + c['month'] == ym and c['stock'] and c['weight_kg']: b[c['po']] += c['stock'] * c['weight_kg']
        return b
    y1, y0 = ytd(dern // 100), ytd(dern // 100 - 1); ratio = {po: y1[po] / y0[po] for po in y1 if y0.get(po)}
    b1, b0 = bio(dern), bio(dern - 100); vol = {po: b1[po] / b0[po] for po in b1 if b0.get(po)}
    def parts(z, po=None):
        v = [sum(x[i] for p_, x in z.items() if po is None or p_ == po) for i in range(3)]
        return (100 * v[1] / v[0], 100 * v[2] / v[0]) if v[0] > 0 else None
    def methode_G(o, t, po=None):
        # moitie : le dernier mois publie tel quel ; moitie : le dernier mois + la variation saisonniere de l'an dernier (meme ecart de mois)
        L, LT, LO = parts(recolte(o), po), parts(recolte(t - 100), po), parts(recolte(o - 100), po)
        if L is None: return LT
        if LT is None or LO is None: return L
        return tuple(min(95.0, max(0.0, L[i] + (LT[i] - LO[i]) / 2)) for i in range(2))
    prev = {}
    for ym in cibles:
        ly = recolte(ym - 100)
        V = {po: v[0] * vol.get(po, 1.0) for po, v in ly.items()}                # volume de la zone : l'an dernier x biomasse en mer
        Z = {po: methode_G(dern, ym, po) for po in V}
        Z = {po: z for po, z in Z.items() if z}
        N = methode_G(dern, ym)                                                  # part nationale (la mieux testee)
        tv = sum(V[po] for po in Z)
        k = [N[i] * tv / sum(V[po] * Z[po][i] for po in Z) if sum(V[po] * Z[po][i] for po in Z) else 1 for i in range(2)]
        prev[ym] = {po: [V[po], V[po] * min(95, Z[po][0] * k[0]) / 100, V[po] * min(95, Z[po][1] * k[1]) / 100] for po in Z}
    # ---- test des methodes de calibres sur les 24 derniers mois (1 et 2 mois d'avance) ----
    def wr(o):
        ms = [o // 100 * 100 + m for m in range(1, o % 100 + 1)]
        h = collections.defaultdict(float); kk = collections.defaultdict(float); h0 = collections.defaultdict(float); k0 = collections.defaultdict(float)
        for c in C:
            ym = c['year'] * 100 + c['month']
            if not c['po'] or not c['harv_stk']: continue
            if ym in ms: h[c['po']] += c['harv_stk']; kk[c['po']] += c['harv_kg']
            if ym + 100 in ms: h0[c['po']] += c['harv_stk']; k0[c['po']] += c['harv_kg']
        return {po: (kk[po] / h[po]) / (k0[po] / h0[po]) for po in h if h0.get(po) and h[po] and k0[po]}
    bt = {m: {'nat6': [], 'nat56': [], 'z6': [], 'z56': []} for m in ('A', 'D', 'G')}
    for o in [m for m in mois_r if m >= mois_r[-1] - 200 and nxt(nxt(m)) <= dern][-24:]:
        rat = wr(o)
        for t in (nxt(o), nxt(nxt(o))):
            act = recolte(t)
            if not parts(act): continue
            for m in ('A', 'D', 'G'):
                f = (lambda po=None: parts(recolte(t - 100, rat), po)) if m == 'A' else (lambda po=None: parts(recolte(o), po)) if m == 'D' else (lambda po=None: methode_G(o, t, po))
                p_, a_ = f(), parts(act)
                if p_: bt[m]['nat56'].append(p_[0] - a_[0]); bt[m]['nat6'].append(p_[1] - a_[1])
                for po in act:
                    if act[po][0] < 2000: continue
                    pz, az = f(po), parts(act, po)
                    if pz and az: bt[m]['z56'].append(pz[0] - az[0]); bt[m]['z6'].append(pz[1] - az[1])
    mae = lambda L: round(sum(abs(x) for x in L) / len(L), 1) if L else None
    test_calibres = {m: {k2: mae(v) for k2, v in r.items()} | {'bias6': round(sum(r['nat6']) / len(r['nat6']), 1) if r['nat6'] else None} for m, r in bt.items()}
    zt = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    for ym in cibles:
        for po, v in prev[ym].items():
            for i in range(3): zt[po][i] += v[i]
    ori = [i for i in range(last - 9 - 4 * 25, last - 9 + 1, 4) if i > 0]
    sp_tot, sa_tot = collections.defaultdict(float), collections.defaultdict(float)
    err_m, err_n, top_m, top_n, nz = [], [], 0, 0, 0
    for i in ori:
        P, A, Nn = collections.defaultdict(float), collections.defaultdict(float), collections.defaultdict(float)
        for site, s_ in st['sites'].items():
            po = R['site_po'].get(site)
            if not po or not commercial(site): continue
            j = debut(s_, i)
            if j is None: continue
            co = R['site_org'].get(site); cap = R['site_cap'].get(site) or 0
            age = ((weeks[i] - weeks[j]).days / 30.44 + DECALAGE.get(site, 0.0)) * rythme.get((po, co), 1.0)
            P[(po, co)] += cap * pv(age); Nn[(po, co)] += cap
            if vide(s_, i, 9): A[(po, co)] += cap
        for po in {k[0] for k in P}:
            ks = [k for k in set(P) | set(A) if k[0] == po]
            tp, ta, tn = sum(P[k] for k in ks), sum(A[k] for k in ks), sum(Nn[k] for k in ks)
            if ta < 3000 or not tp: continue
            nz += 1
            for k in ks:
                sp_tot[k[1]] += P[k] / tp * ta; sa_tot[k[1]] += A[k]
                a_, p_, n_ = 100 * A[k] / ta, 100 * P[k] / tp, 100 * Nn[k] / tn
                if a_ >= 5 or p_ >= 5: err_m.append(abs(p_ - a_)); err_n.append(abs(n_ - a_))
            best = max(ks, key=lambda k: A[k]); top_m += max(ks, key=lambda k: P[k]) == best; top_n += max(ks, key=lambda k: Nn[k]) == best
    # correction : capacite vraiment videe / capacite prevue, sur 2 ans, bornee entre 0,6 et 1,6 (au moins 20 000 t prevues au total)
    corr = {co: max(0.6, min(1.6, sa_tot[co] / v)) for co, v in sp_tot.items() if v >= 20000}
    test_eleveurs = {'origins': len(ori), 'zone_months': nz, 'mae_model': round(statistics.mean(err_m), 1) if err_m else None,
                     'mae_capacity': round(statistics.mean(err_n), 1) if err_n else None,
                     'top_model': round(100 * top_m / nz) if nz else None, 'top_capacity': round(100 * top_n / nz) if nz else None,
                     'corrections': {co: round(v, 2) for co, v in sorted(corr.items(), key=lambda kv: -sp_tot[kv[0]])[:15]}}
    fermes = collections.defaultdict(lambda: {'t': 0.0, 't56': 0.0, 't6': 0.0, 'zones': collections.defaultdict(lambda: {'t': 0.0, 't56': 0.0, 't6': 0.0, 'sites': 0, 'pd': 0, 'ila': 0}), 'pd': 0, 'ila': 0, 'sites': 0})
    for po, (T, T56, T6) in zt.items():
        L = [x for x in sites if x['po'] == po and x['p_harvest'] > 0]
        cf = lambda x: corr.get(x['co'], 1.0)
        wt = sum(x['cap'] * x['p_harvest'] * cf(x) for x in L); w56 = sum(x['cap'] * x['p_harvest'] * cf(x) * x['q56'] for x in L); w6 = sum(x['cap'] * x['p_harvest'] * cf(x) * x['q6'] for x in L)
        if not wt: continue
        # recolte de chaque site = part de la recolte de la zone ; dans cette recolte, part de 5-6 et 6+ selon le poids estime du site,
        # recalee pour que la zone retrouve son total (k), et plafonnee : un site ne peut pas recolter plus de gros que de poissons
        k56 = (T56 / T) / (w56 / wt) if w56 else 0; k6 = (T6 / T) / (w6 / wt) if w6 else 0
        for x in L:
            a = x['cap'] * x['p_harvest'] * cf(x); h = T * a / wt
            f56, f6 = x['q56'] * k56, x['q6'] * k6
            if f56 + f6 > 0.97: r = 0.97 / (f56 + f6); f56, f6 = f56 * r, f6 * r
            parts = (h, h * f56, h * f6)
            F = fermes[x['co']]; Zf = F['zones'][po]
            for k, v in zip(('t', 't56', 't6'), parts): F[k] += v; Zf[k] += v
            if parts[0] >= 50:
                F['sites'] += 1; Zf['sites'] += 1
                if 'PD' in x['disease']: F['pd'] += 1; Zf['pd'] += 1
                if 'ILA' in x['disease']: F['ila'] += 1; Zf['ila'] += 1
    classement = sorted([{'co': co, 'harvest_t': round(F['t']), 't56': round(F['t56']), 't6': round(F['t6']),
                          'share56': round(100 * F['t56'] / F['t'], 1) if F['t'] else 0, 'share6': round(100 * F['t6'] / F['t'], 1) if F['t'] else 0,
                          'sites': F['sites'], 'pd_sites': F['pd'], 'ila_sites': F['ila'], 'pace': next((c['pace'] for c in cyc if c['co'] == co and c['po'] == 0 and c['pace']), 1.0),
                          'zones': sorted([{'po': po, 'harvest_t': round(v['t']), 't56': round(v['t56']), 't6': round(v['t6']),
                                            'share56': round(100 * v['t56'] / v['t'], 1) if v['t'] else 0, 'share6': round(100 * v['t6'] / v['t'], 1) if v['t'] else 0,
                                            'sites': v['sites'], 'pd_sites': v['pd'], 'ila_sites': v['ila']} for po, v in F['zones'].items() if v['t'] >= 20],
                                          key=lambda z: -(z['t56'] + z['t6']))}
                         for co, F in fermes.items() if F['t56'] + F['t6'] >= 20], key=lambda c: -(c['t56'] + c['t6']))
    def tots(z): return [sum(v[i] for v in z.values()) for i in range(3)]
    resume = []
    for ym in cibles:
        P, A = tots(prev[ym]), tots(recolte(ym - 100))
        resume.append({'month': ym, 'harvest_t': round(P[0]), 't56': round(P[1]), 't6': round(P[2]), 'share56': round(100 * P[1] / P[0], 1), 'share6': round(100 * P[2] / P[0], 1),
                       'ly_share56': round(100 * A[1] / A[0], 1), 'ly_share6': round(100 * A[2] / A[0], 1), 'ly_t56': round(A[1]), 'ly_t6': round(A[2]), 'ly_harvest_t': round(A[0])})
    Y = [tots(recolte(dern // 100 * 100 + m)) for m in range(1, dern % 100 + 1)]; S = [sum(x[i] for x in Y) for i in range(3)]
    d12 = set(mois_r[-12:])
    tout = sum(c['harv_kg'] or 0 for c in C if c['year'] * 100 + c['month'] in d12)
    zon = sum(c['harv_kg'] or 0 for c in C if c['po'] and c['year'] * 100 + c['month'] in d12)
    part_zones = round(zon / tout, 4) if tout else 1.0
    # archive des previsions et controle quand les mois prevus sont publies
    ARCH = os.path.join(ROOT, 'data', 'big_fish_archive.json')
    arch = json.load(io.open(ARCH, encoding='utf-8')) if os.path.exists(ARCH) else {}
    arch.setdefault(str(dern), {'made': now.isoformat(), 'norway': resume,
                                'top': [{'co': c['co'], 't56': c['t56'], 't6': c['t6'], 'harvest_t': c['harvest_t']} for c in classement[:15]]})
    io.open(ARCH, 'w', encoding='utf-8').write(json.dumps(arch, ensure_ascii=False, separators=(',', ':')))
    controles = []
    for orig, a in sorted(arch.items()):
        for x in a['norway']:
            if x['month'] in mois_r:
                A = tots(recolte(x['month']))
                controles.append({'made_from': int(orig), 'month': x['month'], 'forecast_share56': x['share56'], 'forecast_share6': x['share6'],
                                  'actual_share56': round(100 * A[1] / A[0], 1), 'actual_share6': round(100 * A[2] / A[0], 1),
                                  'forecast_harvest_t': x['harvest_t'], 'actual_harvest_t': round(A[0])})
    ytd_share = {'share56': round(100 * S[1] / S[0], 1), 'share6': round(100 * S[2] / S[0], 1), 'from': dern // 100 * 100 + 1, 'to': dern}
    tot_all = sum(z['score6'] for z in zones) or 1
    for z in zones: z['zone_share6'] = round(100 * z['score6'] / tot_all, 1)
    zones.sort(key=lambda z: -z['score6'])
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'week': now.isoformat(),
                    'active_sites': len(sites), 'offshore': [{'id': k, 'name': R['site_name'].get(k), 'what': v, 'po': R['site_po'].get(k),
                    'cap': R['site_cap'].get(k), 'status_last_12_weeks': st['sites'].get(k, '')[-12:]} for k, v in SITES_LARGE.items()], 'backtest': {str(b): round(100 * v, 1) for b, v in sorted(p_vide.items())},
                    'method': 'site age from fallow history (BarentsWatch) x zone growth curve (biomass register) x measured harvest chance by age'},
           'zones': zones,
           'ranking': {'months': cibles, 'register_month': dern, 'farmers': classement, 'norway': resume, 'ytd': ytd_share,
                       'zone_share': part_zones, 'gut': GUT, 'checks': controles, 'test_sizes': test_calibres, 'test_farmers': test_eleveurs,
                       'method': 'size mix: half the last reported month, half the last month plus last year\'s seasonal change (tested best); '
                                 'shared between farmers by site capacity x harvest chance x size mix at the estimated weight; ILA and PD adjust timing and weight'},
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
