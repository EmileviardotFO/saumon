#!/usr/bin/env python3
"""
Ecosse : tableau de bord hebdomadaire par site, a partir des fichiers officiels deja collectes.

  farming/donnees_gb/ms_sea_lice_current.csv + _archive.csv   comptages hebdo de poux (femelles adultes par poisson) par site,
                                                              avec le motif quand il n'y a pas de comptage (retrait avant abattage,
                                                              site vide, site tout juste empoissonne...)   [Scottish Government]
  farming/donnees_gb/se_monthly_reports.csv                   biomasse, mortalite (kg), aliment par site et par mois   [SEPA]
  data/scotland_mortality.json                                mortalite mensuelle par ferme et cycles termines   [Salmon Scotland]

    python3 scripts/build_scotland_weekly.py        -> data/scotland_weekly.json
"""
import collections, csv, datetime as dt, difflib, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GB = os.path.join(ROOT, 'farming', 'donnees_gb')


def co(n):
    n = (n or '').lower()
    for k, v in (('mowi', 'Mowi'), ('scottish sea farms', 'Scottish Sea Farms'), ('grieg', 'Scottish Sea Farms'), ('cooke', 'Cooke'), ('bakkafrost', 'Bakkafrost Scotland'),
                 ('scottish salmon company', 'Bakkafrost Scotland'), ('loch duart', 'Loch Duart'), ('organic sea harvest', 'Organic Sea Harvest'), ('kames', 'Kames'), ('wester ross', 'Mowi')):
        if k in n:
            return v
    return 'Other'


def norm(s):
    return re.sub(r'[^a-z]', '', re.sub(r'\(.*?\)', '', (s or '').lower()))


def fl(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def reason(r):
    r = (r or '').lower()
    return 'wd' if 'withdrawal' in r else 'stocked' if 'stocked' in r else 'fallow' if 'fallow' in r else 'vet' if 'veterinary' in r else 'other' if r else ''


def main():
    rows = []
    for f in ('ms_sea_lice_current.csv', 'ms_sea_lice_archive.csv'):
        p = os.path.join(GB, f)
        if os.path.exists(p):
            rows += list(csv.DictReader(open(p, encoding='utf-8-sig')))
    seen, L = set(), []
    for r in rows:
        k = (r['Site No'], r['Week Beginning'])
        if k in seen or not r['Week Beginning']:
            continue
        seen.add(k)
        rs = reason(r['Reason For No Count'])
        L.append({'site': r['Site No'], 'name': r['Site Name'].strip(), 'co': co(r['Business Name']), 'd': r['Week Beginning'], 'af': fl(r['Weekly Average AF']) if not rs else None, 'r': rs})
    if not L:
        print('scotland weekly : pas de comptages de poux')
        return
    weeks = sorted({x['d'] for x in L})
    last = weeks[-1]
    byw = collections.defaultdict(list)
    for x in L:
        byw[x['d']].append(x)

    def wk(d):
        X = byw[d]
        c = [x['af'] for x in X if x['af'] is not None]
        return {'d': d, 'n': len(c), 'af': round(sum(c) / len(c), 2) if c else None, 'o05': sum(v > 0.5 for v in c), 'o1': sum(v > 1 for v in c), 'o2': sum(v >= 2 for v in c),
                'wd': sum(x['r'] == 'wd' for x in X), 'stocked': sum(x['r'] == 'stocked' for x in X), 'fallow': sum(x['r'] == 'fallow' for x in X), 'vet': sum(x['r'] == 'vet' for x in X)}
    W = [wk(d) for d in weeks]
    # par mois : moyenne des comptages, part au-dessus de 0,5, sites-semaines en retrait avant abattage
    bm = collections.defaultdict(lambda: {'c': [], 'wd': 0, 'wds': set(), 'st': set()})
    for x in L:
        k = x['d'][:4] + x['d'][5:7]
        if x['af'] is not None:
            bm[k]['c'].append(x['af'])
        if x['r'] == 'wd':
            bm[k]['wd'] += 1
            bm[k]['wds'].add(x['site'])
        if x['r'] == 'stocked':
            bm[k]['st'].add(x['site'])
    months = [{'k': k, 'af': round(sum(v['c']) / len(v['c']), 2) if v['c'] else None, 'o05': round(100 * sum(z > 0.5 for z in v['c']) / len(v['c']), 1) if v['c'] else None,
               'wd': v['wd'], 'wd_sites': len(v['wds']), 'stocked': len(v['st'])} for k, v in sorted(bm.items())]
    # sites cette semaine, avec l'historique recent et la duree du retrait
    bys = collections.defaultdict(list)
    for x in sorted(L, key=lambda z: z['d']):
        bys[x['site']].append(x)
    M = json.load(open(os.path.join(ROOT, 'data', 'scotland_mortality.json'))) if os.path.exists(os.path.join(ROOT, 'data', 'scotland_mortality.json')) else None
    mort = {}
    if M:
        lm = M['latest']
        hist = collections.defaultdict(list)
        for k in sorted(M['months']):
            for x in M['months'][k]['farms']:
                hist[(x['co'], norm(x['farm']))].append((k, x))
        for key, h in hist.items():
            if h[-1][0] != lm:
                continue
            x = h[-1][1]
            # mois consecutifs en mer avant le dernier (jusqu'a la mise a l'eau ou au debut de la serie)
            run = []
            for k, y in reversed(h):
                if y['m'] is None:
                    break
                run.append(y['m'])
                if y['st'] == 'stocked':
                    break
            surv = 1.0
            for v in run:
                surv *= 1 - v / 100
            mort[key] = {'m': x['m'], 'st': x['st'], 'cause': x['cause'], 'cum': x['cum'], 'run': len(run), 'lost': round(100 * (1 - surv), 1) if run else None, 'farm': x['farm']}
    # SEPA : biomasse par mois et par eleveur, plafond par site
    sepa, sb, smax = [], {}, {}
    p = os.path.join(GB, 'se_monthly_reports.csv')
    if os.path.exists(p):
        agg = collections.defaultdict(lambda: collections.defaultdict(float))
        mk = collections.defaultdict(float)
        for r in csv.DictReader(open(p, encoding='utf-8-sig')):
            try:
                d = dt.datetime.strptime(r['Year'], '%d-%b-%Y')
            except ValueError:
                continue
            if d.year < 2021 or (r.get('Water Type') or '').lower() != 'seawater':
                continue
            k = f'{d.year}{d.month:02d}'
            b = fl(r['Actual Biomass on Site (tonnes)']) or 0
            c = co(r['Operator'])
            agg[k][c] += b
            mk[k] += (fl(r['Mortalities Kilograms']) or 0) / 1000
            sb[(k, c, norm(r['Site Name']))] = b
            smax[(c, norm(r['Site Name']))] = fl(r['Maximum Biomass Allowed (tonnes)'])
        for k in sorted(agg):
            t = sum(agg[k].values())
            sepa.append({'k': k, 't': round(t / 1000, 1), 'mort_t': round(mk[k]), 'mort_pct': round(100 * mk[k] / t, 2) if t else None, 'co': {c: round(v / 1000, 1) for c, v in agg[k].items() if v > 500}})
    sl = sepa[-1]['k'] if sepa else None

    def match(table, c, n):
        if (c, n) in table:
            return table[(c, n)]
        cand = [k[1] for k in table if k[0] == c]
        m = difflib.get_close_matches(n, cand, n=1, cutoff=0.78)
        if not m:
            m = [k for k in cand if len(n) >= 5 and (k.startswith(n) or n.startswith(k))][:1]
        return table[(c, m[0])] if m else None
    sbl = {(c, n): v for (k, c, n), v in sb.items() if k == sl}
    now, matched = [], 0
    for s, h in bys.items():
        x = h[-1]
        if x['d'] != last:
            continue
        rec = [y['af'] for y in h[-9:-1] if y['af'] is not None]
        wdw = 0
        for y in reversed(h):
            if y['r'] != 'wd':
                break
            wdw += 1
        n = norm(x['name'])
        mm = match(mort, x['co'], n) or {}
        matched += bool(mm)
        now.append({'site': s, 'name': x['name'], 'co': x['co'], 'af': x['af'], 'r': x['r'], 'max8': max(rec) if rec else None, 'wdw': wdw,
                    'm': mm.get('m'), 'cause': mm.get('cause'), 'lost': mm.get('lost'), 'run': mm.get('run'), 'bio': match(sbl, x['co'], n), 'cap': match(smax, x['co'], n)})
    cos = []
    for c in sorted({x['co'] for x in now}, key=lambda c: -sum(x['co'] == c for x in now)):
        X = [x for x in now if x['co'] == c]
        v = [x['af'] for x in X if x['af'] is not None]
        if len(X) < 3:
            continue
        cos.append({'co': c, 'sites': len(X), 'n': len(v), 'af': round(sum(v) / len(v), 2) if v else None, 'o05': sum(z > 0.5 for z in v), 'wd': sum(x['r'] == 'wd' for x in X),
                    'stocked': sum(x['r'] == 'stocked' for x in X), 'fallow': sum(x['r'] == 'fallow' for x in X)})
    out = {'meta': {'last_week': last, 'sepa_last': sl, 'mort_last': M['latest'] if M else None, 'sites': len(now), 'matched_mort': matched,
                    'sources': 'Scottish Government (weekly sea lice counts by site) · SEPA (monthly biomass by site) · Salmon Scotland (monthly mortality by farm)'},
           'weeks': W[-30:], 'months': months[-40:], 'now': sorted(now, key=lambda x: -(x['af'] or 0)), 'companies': cos, 'sepa': sepa[-40:]}
    if M:
        ind = M['industry']
        cyc = collections.defaultdict(lambda: collections.defaultdict(list))
        lmm = int(M['latest'][4:])
        for c in M['cycles']:
            if int(c['m'][4:]) <= lmm:
                cyc[c['co']][c['m'][:4]].append(c['cum'])
                cyc['All'][c['m'][:4]].append(c['cum'])
        out['mort'] = {'industry': ind, 'latest': M['latest'], 'companies': M['months'][M['latest']]['companies'], 'causes': M['months'][M['latest']]['causes'],
                       'stats': {k: M['months'][M['latest']][k] for k in ('n', 'active', 'over5', 'over10', 'emptied', 'stocked')},
                       'by_month': {k: {'over5': v['over5'], 'over10': v['over10'], 'active': v['active'], 'co': {c['co']: c['mean'] for c in v['companies']}} for k, v in M['months'].items()},
                       'cycles': {c: {y: {'n': len(v), 'mean': round(sum(v) / len(v), 1), 'max': max(v)} for y, v in d.items()} for c, d in cyc.items()},
                       'cycles_span': f'Jan–{dt.date(2000, lmm, 1):%b}', 'recent': sorted(M['cycles'], key=lambda c: c['m'])[-14:][::-1],
                       'worst': sorted((x for x in M['months'][M['latest']]['farms'] if x['m'] is not None), key=lambda x: -x['m'])[:15]}
    json.dump(out, open(os.path.join(ROOT, 'data', 'scotland_weekly.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    w = W[-1]
    print(f"scotland_weekly.json : semaine {last}, {len(now)} sites, {w['n']} comptes, moyenne {w['af']}, {w['o05']} > 0,5, {w['wd']} en retrait ; mortalite rattachee a {matched} sites ; SEPA {sl}")


if __name__ == '__main__':
    main()
