#!/usr/bin/env python3
"""
Colombie-Britannique : permis, sites fermes, cycles et evenements par site, fichiers ouverts du ministere federal des Peches (DFO).

  farming/donnees_ca/dfo/licences.csv          permis marins valides : biomasse maximale par site, expiration, eleveur
  farming/donnees_ca/dfo/carcass.csv           par site et par mois depuis 2013 : stade (mise a l'eau, grossissement, recolte) et mortalite en % par cause
  farming/donnees_ca/dfo/lice_mitigation.csv   evenements dates de lutte contre les poux, dont les abattages
  farming/donnees_ca/dfo/health_events.csv     diagnostics veterinaires par site

Aucun fichier ne donne le nombre de poissons ni les tonnes : la mortalite d'un cycle est la composition des % mensuels.

    python3 scripts/build_canada_bc.py        -> data/canada_bc.json
"""
import collections, csv, json, os, statistics as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'farming', 'donnees_ca', 'dfo')
MON = {m: i + 1 for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'])}
CAUSES = [('Environmental (%/month)', 'Environment'), ("Fresh 'silver' (%/month)", 'Fresh, no visible cause'), ('Infectious Disease (%/month)', 'Infectious disease'), ('Handling / Transport (%/month)', 'Handling, transport'),
          ('Mature (%/month)', 'Maturation'), ('Old / Decomposed (%/month)', 'Old, decomposed'), ('Poor Performer / Cull (%/month)', 'Poor performers, culls'), ('Predator Attack (%/month)', 'Predators')]


def rd(f):
    p = os.path.join(SRC, f)
    return list(csv.DictReader(open(p, encoding='utf-8-sig', errors='replace'))) if os.path.exists(p) else []


def co(n):
    n = (n or '').lower()
    return 'Mowi' if 'mowi' in n or 'marine harvest' in n else 'Cermaq' if 'cermaq' in n or 'mainstream' in n else 'Grieg (now Cermaq)' if 'grieg' in n else 'Creative Salmon' if 'creative' in n else 'Other'


def pct(v):
    try:
        return float(str(v).replace('%', ''))
    except ValueError:
        return None


def main():
    LIC, CAR, MIT, HE = rd('licences.csv'), rd('carcass.csv'), rd('lice_mitigation.csv'), rd('health_events.csv')
    if not LIC or not CAR:
        print('canada bc : fichiers DFO absents')
        return
    ST = 'Production Information & Report Status'
    rows = []
    for r in CAR:
        if 'atlantic' not in r['Species'].lower():
            continue
        m = MON.get(r['Month'].strip().lower())
        if not m:
            continue
        rows.append({'k': int(r['Year']) * 12 + m - 1, 'f': r['Facility Reference Number'], 'co': co(r['Licence Holder']), 'name': r['Site Common Name'].strip(), 'unit': r['Aquaculture Management Unit'].strip(),
                     'st': r[ST].strip().lower(), 'tot': pct(r['Total Mortality (%/month)']), 'c': {lab: pct(r[col]) for col, lab in CAUSES}})
    last = max(r['k'] for r in rows)
    ym = lambda k: (k // 12) * 100 + k % 12 + 1
    lic = {r['Facility Reference Number']: r for r in LIC if 'atlantic' in r['Licensed Species'].lower()}
    for r in lic.values():
        r['mtb'] = pct(r['Maximum Allowable Peak Biomass']) or 0
    # ---- permis par eleveur
    hold = collections.defaultdict(lambda: {'n': 0, 'mtb': 0.0})
    units = collections.defaultdict(lambda: collections.defaultdict(lambda: {'n': 0, 'mtb': 0.0}))
    for r in lic.values():
        h = r['Licence Holder'].replace('MOWI Canada West', 'Mowi').replace('Cermaq British Columbia', 'Cermaq')
        hold[h]['n'] += 1; hold[h]['mtb'] += r['mtb']
        u = units[r['Aquaculture Management Unit'].strip()][h]
        u['n'] += 1; u['mtb'] += r['mtb']
    exp = collections.Counter(r['Licence Expiry Date'] for r in lic.values())
    # ---- sites actifs par annee, par eleveur ; sites sortis de la liste des permis
    bys = collections.defaultdict(list)
    for r in sorted(rows, key=lambda r: r['k']):
        bys[r['f']].append(r)
    years = sorted({r['k'] // 12 for r in rows})
    active = [{'y': y, 'sites': len({r['f'] for r in rows if r['k'] // 12 == y}), 'co': dict(collections.Counter(c for f, c in {(r['f'], r['co']) for r in rows if r['k'] // 12 == y}))} for y in years]
    # sites en mer par mois (pour comparer les memes mois d'une annee sur l'autre)
    stocked = collections.defaultdict(set)
    for r in rows:
        stocked[r['k']].add(r['f'])
    closed = sorted(({'f': f, 'name': v[-1]['name'], 'co': v[-1]['co'], 'unit': v[-1]['unit'], 'last': ym(v[-1]['k']), 'first': ym(v[0]['k'])} for f, v in bys.items() if f not in lic and v[-1]['k'] >= 2018 * 12),
                    key=lambda x: -x['last'])
    cu = collections.Counter(c['unit'] for c in closed)
    # ---- cycles : mois consecutifs en mer sur un site (trou de 2 mois ou plus = nouveau cycle)
    cyc = []
    for f, v in bys.items():
        cur = [v[0]]
        for a, b in zip(v, v[1:]):
            if b['k'] - a['k'] > 2:
                cyc.append(cur); cur = []
            cur.append(b)
        cyc.append(cur)
    C = []
    for c in cyc:
        surv, pre, inh, cs = 1.0, 1.0, False, collections.defaultdict(float)
        for r in c:
            inh = inh or 'harvest' in r['st']
            if r['tot'] is not None:
                surv *= 1 - r['tot'] / 100
                if not inh:
                    pre *= 1 - r['tot'] / 100
            for lab, x in r['c'].items():
                cs[lab] += x or 0
        C.append({'f': c[0]['f'], 'name': c[-1]['name'], 'co': c[-1]['co'], 'unit': c[-1]['unit'], 'start': ym(c[0]['k']), 'end': ym(c[-1]['k']), 'mo': c[-1]['k'] - c[0]['k'] + 1,
                  'loss': round(100 * (1 - pre), 1), 'loss_all': round(100 * (1 - surv), 1), 'open': c[-1]['k'] >= last - 1, 'entry': 'smolt' in c[0]['st'], 'harv': any('harvest' in r['st'] for r in c), 'last_st': c[-1]['st'],
                  'top': max(cs, key=cs.get) if cs else None, 'cs': {k: round(x, 1) for k, x in cs.items()}})
    done = [c for c in C if not c['open'] and c['entry'] and c['harv'] and c['mo'] >= 10 and c['start'] >= 201301]
    by_end = collections.defaultdict(list)
    for c in done:
        by_end[c['end'] // 100].append(c)
    cyc_year = [{'y': y, 'n': len(v), 'loss': round(S.mean(c['loss'] for c in v), 1), 'med': round(S.median(c['loss'] for c in v), 1), 'mo': round(S.median(c['mo'] for c in v)), 'worst': max(c['loss'] for c in v), 'loss_all': round(S.mean(c['loss_all'] for c in v), 1),
                 'co': {h: {'n': len(x), 'loss': round(S.mean(c['loss'] for c in x), 1)} for h in ('Mowi', 'Cermaq', 'Grieg (now Cermaq)') for x in [[c for c in v if c['co'] == h]] if x}} for y, v in sorted(by_end.items()) if len(v) >= 3]
    # causes, par annee : points de mortalite mensuelle cumules, part de chaque cause
    cause_year = []
    for y in years[-5:]:
        t = collections.defaultdict(float)
        for r in rows:
            if r['k'] // 12 == y:
                for lab, x in r['c'].items():
                    t[lab] += x or 0
        s = sum(t.values())
        cause_year.append({'y': y, 'share': {k: round(100 * v / s, 1) for k, v in t.items()} if s else {}})
    # mortalite mensuelle moyenne des sites en mer, 3 ans, et sites par stade
    months = []
    for k in range(last - 35, last + 1):
        X = [r for r in rows if r['k'] == k]
        t = [r['tot'] for r in X if r['tot'] is not None]
        months.append({'k': ym(k), 'sites': len(X), 'mort': round(S.mean(t), 2) if t else None, 'entry': sum('smolt' in r['st'] for r in X), 'grow': sum('grow' in r['st'] for r in X), 'harv': sum('harvest' in r['st'] for r in X),
                       'co': {h: round(S.mean(v), 2) for h in ('Mowi', 'Cermaq', 'Grieg (now Cermaq)') for v in [[r['tot'] for r in X if r['co'] == h and r['tot'] is not None]] if v}})
    # ---- evenements de lutte contre les poux
    mit = collections.defaultdict(collections.Counter)
    last12 = collections.defaultdict(collections.Counter)
    for r in MIT:
        d = r['Incident Date']
        if len(d) < 7:
            continue
        k = int(d[:4]) * 12 + int(d[5:7]) - 1
        for part in r['Mitigation'].split(';'):
            p = part.strip().lower()
            t = 'harvest' if 'harvest' in p else 'feed' if 'feed' in p else 'mech' if 'mechanical' in p else 'bath' if p.startswith('medicinal') else 'nonmed' if 'non-medicinal' in p else None
            if t:
                mit[int(d[:4])][t] += 1
                if k > last - 12:
                    last12[r['Facility Reference Number']][t] += 1
    mit_last = max((r['Incident Date'] for r in MIT if r['Incident Date']), default=None)
    he = collections.Counter()
    for r in HE:
        if r['Incident Date'][:4] >= str(years[-1] - 2) and 'atlantic' in r['Species'].lower():
            he[(r['Incident Date'][:4], r['Veterinary Diagnosis'].strip().capitalize().replace('Mouth rot', 'Mouthrot'))] += 1
    # ---- sites aujourd'hui
    now = []
    for c in C:
        if not c['open']:
            continue
        l = lic.get(c['f'])
        t = last12.get(c['f'], {})
        now.append({'f': c['f'], 'name': c['name'], 'co': c['co'].replace('Grieg (now Cermaq)', 'Cermaq (ex-Grieg)'), 'unit': c['unit'], 'st': 'smolt entry' if 'smolt' in c['last_st'] else 'harvesting' if 'harvest' in c['last_st'] else 'grow-out',
                    'since': c['start'], 'mo': c['mo'], 'loss': c['loss'], 'loss_all': c['loss_all'], 'top': c['top'], 'mtb': l['mtb'] if l else None, 'lic': bool(l), 'trt': sum(v for k, v in t.items() if k != 'harvest'), 'harv_ev': t.get('harvest', 0)})
    idle = sorted(({'f': f, 'name': r['Site Common Name'].strip(), 'co': co(r['Licence Holder']), 'unit': r['Aquaculture Management Unit'].strip(), 'mtb': r['mtb'],
                    'last': ym(bys[f][-1]['k']) if f in bys else None} for f, r in lic.items() if f not in {x['f'] for x in now}), key=lambda x: -(x['last'] or 0))
    out = {'meta': {'last': ym(last), 'mit_last': mit_last, 'source': 'Fisheries and Oceans Canada (DFO), Pacific aquaculture public reporting: marine finfish licences, carcass classification by facility, sea lice mitigation events, fish health events',
                    'note': 'No fish numbers or tonnes are published per site. Cycle loss = monthly mortality percentages compounded from stocking to the month before harvesting starts (once harvesting has begun the percentage applies to the few fish left, so compounding the whole cycle overstates the loss; that upper figure is kept as loss_all). Atlantic salmon only.'},
           'licences': {'n': len(lic), 'mtb': round(sum(r['mtb'] for r in lic.values())), 'holders': [{'h': h, 'n': v['n'], 'mtb': round(v['mtb'])} for h, v in sorted(hold.items(), key=lambda z: -z[1]['mtb'])],
                        'units': [{'u': u, 'n': sum(x['n'] for x in v.values()), 'mtb': round(sum(x['mtb'] for x in v.values())), 'h': {h: round(x['mtb']) for h, x in v.items()}, 'closed': cu.get(u, 0)} for u, v in sorted(units.items(), key=lambda z: -sum(x['mtb'] for x in z[1].values()))],
                        'expiry': sorted(exp.items()), 'stocked_now': sum(1 for x in now if x['lic']), 'stocked_mtb': round(sum(x['mtb'] or 0 for x in now)), 'idle': idle},
           'active': active, 'stocked_same_month': [{'y': (last - 12 * i) // 12, 'k': ym(last - 12 * i), 'sites': len(stocked.get(last - 12 * i, ()))} for i in range(8, -1, -1)],
           'closed': closed, 'closed_units': cu.most_common(), 'cycles_year': cyc_year, 'cause_year': cause_year, 'months': months,
           'mitigation': [{'y': y, **{t: mit[y].get(t, 0) for t in ('feed', 'bath', 'nonmed', 'mech', 'harvest')}} for y in sorted(mit)[-6:]],
           'health': [{'d': d, 'y': {str(y): he.get((str(y), d), 0) for y in years[-3:]}} for d, _ in collections.Counter({d: sum(v for (yy, dd), v in he.items() if dd == d) for d in {k[1] for k in he}}).most_common(8)],
           'now': sorted(now, key=lambda x: -x['mo']), 'recent': sorted(done, key=lambda c: -c['end'])[:14]}
    json.dump(out, open(os.path.join(ROOT, 'data', 'canada_bc.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f"canada_bc.json : {len(lic)} permis saumon atlantique, {out['licences']['mtb']} t ; {len(now)} sites en mer en {ym(last)} ; {len(closed)} sites sortis depuis 2018 ; {len(done)} cycles termines")


if __name__ == '__main__':
    main()
