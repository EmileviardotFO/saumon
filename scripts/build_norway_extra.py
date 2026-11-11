#!/usr/bin/env python3
"""
Norvege, trois ajouts de novembre 2026 -> data/no_extra.json
  quality   Mattilsynet, abattage de salmonides par classe de qualite (superior + ordinaire, production, rejet) : national, par trimestre
            depuis 2018 ; par zone de production quand la page correspondante a ete lue (farming/donnees_no/mattilsynet_quality_raw_*.json,
            reponses du tableau de bord interceptees par scripts/fetch_browser_sources.py).
  capacity  Fiskeridirektoratet, registre des licences (farming/donnees_no/akvakulturregisteret.csv) : plafond de biomasse (MTB) par
            societe, capacite par site ; rapproche des sites actifs de BarentsWatch et de la biomasse du registre par zone.
  weekly    Norges sjomatrad, statistique hebdomadaire (farming/donnees_no/nsc_ukestat_*.txt) : tonnes et NOK/kg par produit et par pays.

    python3 scripts/build_norway_extra.py
"""
import collections, csv, datetime as dt, glob, io, json, os, re, statistics as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO = os.path.join(ROOT, 'farming', 'donnees_no')
J = lambda f: json.load(open(os.path.join(ROOT, 'data', f), encoding='utf-8'))


def quality():
    series = {}
    for f in sorted(glob.glob(os.path.join(NO, 'mattilsynet_quality_raw_*.json'))):
        raw = open(f, encoding='utf-8').read()
        try:
            d = json.loads(raw[raw.index('{'):])
        except Exception:
            continue
        for dr in d.get('dataResponse', []):
            for ds in dr.get('dataSubset', []):
                t = (ds.get('dataset') or {}).get('tableDataset') or {}
                cols = [(c.get('stringColumn') or c.get('doubleColumn') or c.get('longColumn') or {}).get('values', []) for c in t.get('column', [])]
                if len(cols) != 2 or not cols[0] or not isinstance(cols[0][0], str):
                    continue
                lab, val = cols
                if not all(isinstance(v, (int, float)) for v in val):
                    continue
                kind = 'q' if '-K' in lab[0] else 'y'
                mx = max(val)
                # identification par l'ordre de grandeur : volume (t), part superior (> 0,7), production (0,03-0,4), rejet (< 0,02)
                key = 'vol' if mx > 1000 else 'sup' if mx > 0.7 else 'utk' if mx < 0.02 else 'prod'
                asc = lab == sorted(lab)
                name = f'{kind}_{key}' if asc or kind == 'q' else f'ytd_{key}'
                series[name] = dict(zip(lab, val))
    if 'q_vol' not in series:
        return None
    q = [{'q': k, 'vol': round(series['q_vol'][k] / 1000, 1), 'sup': round(100 * series.get('q_sup', {}).get(k, 0), 1), 'prod': round(100 * series.get('q_prod', {}).get(k, 0), 1), 'utk': round(100 * series.get('q_utk', {}).get(k, 0), 1)} for k in sorted(series['q_vol'])]
    for x in q:
        x['prod_kt'] = round(x['vol'] * x['prod'] / 100, 1)
        x['sup_kt'] = round(x['vol'] * x['sup'] / 100, 1)
    y = [{'y': int(k), 'vol': round(series['y_vol'][k] / 1000), 'sup': round(100 * series.get('y_sup', {}).get(k, 0), 1), 'prod': round(100 * series.get('y_prod', {}).get(k, 0), 1)} for k in sorted(series.get('y_vol', {}))]
    ytd = [{'y': int(k), 'vol': round(series['ytd_vol'][k] / 1000), 'sup': round(100 * series.get('ytd_sup', {}).get(k, 0), 1), 'prod': round(100 * series.get('ytd_prod', {}).get(k, 0), 1)} for k in sorted(series.get('ytd_vol', {}))]
    for x in ytd:
        x['sup_kt'] = round(x['vol'] * x['sup'] / 100)
        x['prod_kt'] = round(x['vol'] * x['prod'] / 100)
    return {'quarters': q, 'years': y, 'ytd': ytd, 'fillets': fillets(q), 'ytd_span': f"Q1–Q{q[-1]['q'][-1]}", 'source': 'Mattilsynet, Slakting av oppdrettet laksefisk (salmon and trout together, tonnes as reported by the farmers)',
            'url': 'https://mattilsynet.no/fisk-og-akvakultur/slakting-av-fisk/statistikk-om-slakting-av-oppdrettet-laksefisk'}


def corr(a, b):
    n = len(a)
    if n < 6:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** .5, 2) if va and vb else None


def fillets(Q):
    """Croise les classes de qualite avec les exportations SSB par produit (data/data.json) : la part « Production »
    se retrouve-t-elle en filets ? Et combien de mois separent la congelation de l'exportation (decalage des prix) ?"""
    try:
        D = json.load(open(os.path.join(ROOT, 'data', 'data.json'), encoding='utf-8'))['ssb_exports']['rows']
    except Exception:
        return None
    kg, nk = collections.defaultdict(lambda: [0.0] * 4), collections.defaultdict(lambda: [0.0] * 4)
    for ym, pr, _c, k, n in D:        # 0 frais entier, 1 filet frais, 2 filet congele, 3 congele entier
        if pr < 4:
            kg[ym][pr] += k
            nk[ym][pr] += n
    yms = sorted(kg)
    qk = lambda ym: f"{ym // 100}-K{(ym % 100 - 1) // 3 + 1}"
    qs, cnt = collections.defaultdict(lambda: [0.0] * 4), collections.Counter()
    for ym in yms:
        cnt[qk(ym)] += 1
        for i in range(4):
            qs[qk(ym)][i] += kg[ym][i] / 1e6
    WFE = 1.6                         # kg de poisson entier par kg de filet (ordre de grandeur, pour la part seulement)
    byq = {x['q']: x for x in Q}
    for x in Q:
        if cnt[x['q']] == 3:
            w, ff, zf, zw = qs[x['q']]
            x.update(x_whole=round(w + zw, 1), x_ff=round(ff, 1), x_zf=round(zf, 1), x_fshare=round(100 * (ff + zf) * WFE / ((ff + zf) * WFE + w + zw), 1))
    def prev(k):
        return f"{int(k[:4]) - 1}{k[4:]}"
    ks = [x['q'] for x in Q if 'x_ff' in x and prev(x['q']) in byq and 'x_ff' in byq[prev(x['q'])]]
    d = lambda key: [byq[k][key] - byq[prev(k)][key] for k in ks]
    cor = {'n': len(ks), 'from': ks[0] if ks else None, 'fshare': corr(d('prod'), d('x_fshare')), 'fresh_fillet': corr(d('prod'), d('x_ff')), 'frozen_fillet': corr(d('prod'), d('x_zf')), 'whole': corr(d('prod'), d('x_whole'))}
    # decalage des prix : la valeur unitaire du filet congele suit le prix du frais entier de L mois plus tot
    px = lambda i: [nk[ym][i] / kg[ym][i] if kg[ym][i] else None for ym in yms]
    yoy = lambda a: [a[i] / a[i - 12] - 1 for i in range(12, len(a))]
    fw, ff, zf = yoy(px(0)), yoy(px(1)), yoy(px(2))
    lag = {'frozen': [corr(zf[L:], fw[:len(fw) - L]) for L in range(10)], 'fresh': [corr(ff[L:], fw[:len(fw) - L]) for L in range(10)]}
    lag['best_frozen'] = max(range(10), key=lambda L: lag['frozen'][L] or -1)
    # saisonnalite : part de l'annee exportee chaque mois, moyenne des 5 dernieres annees completes
    yrs = [y for y in sorted({ym // 100 for ym in yms}) if all(y * 100 + m in kg for m in range(1, 13))][-5:]
    sea = {}
    for nm, i in (('whole', 0), ('fresh_fillet', 1), ('frozen_fillet', 2)):
        sea[nm] = [round(sum(100 * kg[y * 100 + m][i] / sum(kg[y * 100 + mm][i] for mm in range(1, 13)) for y in yrs) / len(yrs), 1) for m in range(1, 13)]
    months = [{'m': ym, 'zf_t': round(kg[ym][2] / 1e3), 'zf_p': round(nk[ym][2] / kg[ym][2], 1), 'ff_t': round(kg[ym][1] / 1e3), 'ff_p': round(nk[ym][1] / kg[ym][1], 1), 'w_p': round(nk[ym][0] / kg[ym][0], 1)} for ym in yms[-30:]]
    return {'corr': cor, 'lag': lag, 'season': sea, 'season_years': [yrs[0], yrs[-1]] if yrs else None, 'months': months, 'wfe': WFE}


def turnover(Q):
    """Meme biomasse, plus de recolte : rotation du stock, survie, poids, nombre de poissons (registre de biomasse, data/data.json),
    mis a cote des classes de qualite (Mattilsynet). Memes mois chaque annee (janvier -> dernier mois du registre)."""
    try:
        R = json.load(open(os.path.join(ROOT, 'data', 'data.json'), encoding='utf-8'))['records']
    except Exception:
        return None
    F = ('uttak_kg', 'uttak_stk', 'dodfisk_stk', 'behfisk_stk', 'biomasse_kg', 'smolt_stk', 'feed_kg')
    nat, zon = collections.defaultdict(lambda: collections.defaultdict(float)), collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(float)))
    for r in R:
        k = r['year'] * 100 + r['month']
        for f in F:
            if r.get(f) is not None:
                nat[k][f] += r[f]
                zon[r.get('po')][k][f] += r[f]
    last = max(nat)
    LY, LM = last // 100, last % 100
    years = [LY - 3, LY - 2, LY - 1, LY]

    def row(src, y, m=LM):
        ks = [y * 100 + i for i in range(1, m + 1)]
        if any(k not in src for k in ks):
            return None
        sm = lambda f: sum(src[k][f] for k in ks)
        bio, stk = sm('biomasse_kg') / m, sm('behfisk_stk') / m
        e = src[y * 100 + m]
        return {'y': y, 'bio_end': round(e['biomasse_kg'] / 1e6, 1), 'fish_end': round(e['behfisk_stk'] / 1e6, 1), 'smolt': round(sm('smolt_stk') / 1e6, 1), 'dead': round(sm('dodfisk_stk') / 1e6, 1),
                'dead_pct': round(100 * sm('dodfisk_stk') / stk, 1) if stk else None, 'harv_n': round(sm('uttak_stk') / 1e6, 1), 'harv': round(sm('uttak_kg') / 1e6, 1),
                'w': round(sm('uttak_kg') / sm('uttak_stk'), 2) if sm('uttak_stk') else None, 'turn': round(sm('uttak_kg') / bio, 2) if bio else None, 'w_sea': round(e['biomasse_kg'] / e['behfisk_stk'], 2) if e['behfisk_stk'] else None,
                'feed': round(sm('feed_kg') / 1e6, 1)}
    N = [x for x in (row(nat, y) for y in years) if x]
    if len(N) < 2:
        return None
    a, b = N[-1], N[-2]
    # decomposition de la hausse de recolte : nombre de poissons, puis poids
    dn = (a['harv_n'] - b['harv_n']) * b['w']
    dw = a['harv_n'] * (a['w'] - b['w'])
    # qualite sur la meme periode quand le registre s'arrete en fin de trimestre
    qy = {}
    if LM % 3 == 0:
        for y in years:
            X = [x for x in Q if x['q'][:4] == str(y) and int(x['q'][-1]) <= LM // 3]
            if len(X) == LM // 3:
                v = sum(x['vol'] for x in X)
                qy[y] = {'vol': round(v), 'sup': round(sum(x['sup_kt'] for x in X)), 'prod': round(sum(x['prod_kt'] for x in X)), 'sup_pct': round(100 * sum(x['sup_kt'] for x in X) / v, 1), 'prod_pct': round(100 * sum(x['prod_kt'] for x in X) / v, 1)}
    for x in N:
        x['q'] = qy.get(x['y'])
    # par zone : la rotation monte-t-elle la ou la mortalite baisse ?
    Z = []
    for po in sorted(k for k in zon if isinstance(k, int) and 1 <= k <= 13):
        r1, r0 = row(zon[po], LY), row(zon[po], LY - 2)
        if r1 and r0 and r0['harv'] > 20 and r0['turn'] and r1['turn']:   # les tres petites zones (PO1, PO13) donnent des ratios aberrants
            Z.append({'po': po, 'harv': r1['harv'], 'harv0': r0['harv'], 'turn': r1['turn'], 'turn0': r0['turn'], 'dead': r1['dead_pct'], 'dead0': r0['dead_pct'], 'w': r1['w'], 'w0': r0['w'], 'fish': r1['fish_end'], 'fish0': r0['fish_end'],
                      'bio': r1['bio_end'], 'bio0': r0['bio_end']})
    zc = {'n': len(Z), 'turn_dead': corr([z['turn'] / z['turn0'] - 1 for z in Z], [z['dead'] - z['dead0'] for z in Z]), 'turn_w': corr([z['turn'] / z['turn0'] - 1 for z in Z], [z['w'] / z['w0'] - 1 for z in Z]),
          'up': sum(z['turn'] > z['turn0'] for z in Z), 'dead_down': sum(z['dead'] < z['dead0'] for z in Z)} if len(Z) >= 6 else None
    # trimestre par trimestre : part « Production » contre mortalite du registre (variations sur un an)
    qd = {}
    for x in Q:
        y, k = int(x['q'][:4]), int(x['q'][-1])
        ks = [y * 100 + m for m in range(3 * k - 2, 3 * k + 1)]
        if all(m in nat for m in ks):
            stk = sum(nat[m]['behfisk_stk'] for m in ks) / 3
            qd[x['q']] = {'prod': x['prod'], 'dead': 100 * sum(nat[m]['dodfisk_stk'] for m in ks) / stk if stk else None}
    pairs = [(qd[q]['prod'] - qd[p]['prod'], qd[q]['dead'] - qd[p]['dead']) for q in sorted(qd) for p in [f"{int(q[:4]) - 1}{q[4:]}"] if p in qd and qd[q]['dead'] is not None and qd[p]['dead'] is not None]
    link = {'n': len(pairs), 'r': corr([p[0] for p in pairs], [p[1] for p in pairs]), 'q1': [{'y': int(q[:4]), 'prod': v['prod'], 'dead': round(v['dead'], 2)} for q, v in sorted(qd.items()) if q.endswith('K1')][-4:]} if len(pairs) >= 8 else None
    return {'span': f"Jan–{dt.date(2000, LM, 1):%b}", 'last': last, 'years': N, 'decomp': {'total': round(a['harv'] - b['harv'], 1), 'fish': round(dn, 1), 'weight': round(dw, 1)}, 'zones': Z, 'zone_corr': zc, 'zone_years': [LY - 2, LY], 'link': link,
            'source': 'Fiskeridirektoratet biomass register (live weight, salmon and trout, all production areas) · Mattilsynet quality classes'}


GROUPS = [('Mowi', r'MOWI|NOVA SEA'), ('SalMar', r'SALMAR|SALFJORD|NORSKOTT|REFSNES|OCEAN FARMING|ARCTIC OFFSHORE'), ('Lerøy', r'LERØY|LEROY|SJØTROLL'), ('Cermaq', r'CERMAQ'), ('Grieg', r'GRIEG'), ('Nordlaks', r'NORDLAKS'),
          ('Bremnes / Salmon Group', r'BREMNES'), ('Alsaker', r'ALSAKER'), ('Måsøval', r'MÅSØVAL'), ('Eide', r'EIDE FJORDBRUK'), ('Firda', r'FIRDA'), ('Sinkaberg-Hansen', r'SINKABERG|SINKABERGHANSEN'), ('Ellingsen', r'ELLINGSEN'),
          ('Kvarøy', r'KVARØY'), ('Blom', r'BLOM FISKEOPPDRETT'), ('Wilsgård', r'WILSGÅRD'), ('Emilsen', r'EMILSEN'), ('Bjørøya', r'BJØRØYA'), ('Midt-Norsk Havbruk', r'MIDT-NORSK'), ('Erko', r'ERKO'), ('Osland', r'OSLAND')]


def group(n):
    for g, rx in GROUPS:
        if re.search(rx, n):
            return g
    return n.title().replace(' As', '').replace(' Asa', '')


def capacity():
    path = os.path.join(NO, 'akvakulturregisteret.csv')
    if not os.path.exists(path):
        return None
    lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    date = re.search(r'(\d\d)-(\d\d)-(\d{4})', lines[0])
    R = list(csv.DictReader(io.StringIO('\n'.join(lines[1:])), delimiter=';'))
    num = lambda x: float((x or '0').replace(',', '.') or 0)
    sea = [r for r in R if 'laks' in (r.get('ART') or '').lower() and 'MATFISK' in (r.get('PRODUKSJONSFORM') or '').upper() and r.get('TILL_ENHET') == 'TN' and r.get('LOK_PLASS') == 'SJØ']
    lic, licpo, typ = {}, collections.defaultdict(collections.Counter), {}
    site = {}
    for r in sea:
        lic[r['TILL_NR']] = (r['NAVN'], num(r['TILL_KAP']))
        typ[r['TILL_NR']] = 'commercial' if r['FORMÅL'] == 'KOMMERSIELL' else r['FORMÅL'].lower()
        if r.get('PROD_OMR'):
            licpo[r['TILL_NR']][r['PROD_OMR']] += 1
        site[r['LOK_NR']] = {'no': int(r['LOK_NR']), 'name': r['LOK_NAVN'].title(), 'cap': num(r['LOK_KAP']), 'po': int(r['PROD_OMR']) if (r.get('PROD_OMR') or '').isdigit() else None, 'owners': set()}
    for r in sea:
        site[r['LOK_NR']]['owners'].add(group(r['NAVN']))
    co = collections.defaultdict(lambda: {'mtb': 0.0, 'lic': 0, 'other': 0.0, 'sites': set(), 'site_cap': 0.0})
    for t, (n, k) in lic.items():
        g = co[group(n)]
        if typ[t] == 'commercial':
            g['mtb'] += k; g['lic'] += 1
        else:
            g['other'] += k
    for s_ in site.values():
        for o in s_['owners']:
            co[o]['sites'].add(s_['no'])
    # sites actifs (BarentsWatch) et biomasse du registre par zone
    try:
        st = J('bw_site_status.json'); SS = st['sites']; have = st['have']
        active = {int(k) for k, v in SS.items() if v and v[-1] == 'a'}
        week = have[-1]
    except Exception:
        active, week = set(), None
    for g in co.values():
        g['active'] = len(g['sites'] & active)
        g['active_cap'] = sum(site[str(n)]['cap'] for n in g['sites'] & active if str(n) in site)
    D = J('data.json'); bio = collections.defaultdict(dict)
    for r in D['records']:
        bio[r['po']][r['year'] * 100 + r['month']] = r['biomasse_kg'] / 1e6
    last = max(bio[1])
    zones = []
    for po in range(1, 14):
        ss = [s_ for s_ in site.values() if s_['po'] == po]
        ac = [s_ for s_ in ss if s_['no'] in active]
        cap_a = sum(s_['cap'] for s_ in ac) / 1000
        zones.append({'po': po, 'sites': len(ss), 'site_cap': round(sum(s_['cap'] for s_ in ss) / 1000), 'active': len(ac), 'active_cap': round(cap_a), 'biomass': round(bio[po].get(last, 0)), 'fill': round(100 * bio[po].get(last, 0) / cap_a) if cap_a else None})
    # estimation de biomasse par fermier : capacite des sites actifs x taux de remplissage de la zone (biomasse / capacite active)
    fill = {z['po']: (z['biomass'] / z['active_cap'] if z['active_cap'] else 0) for z in zones}
    comp = []
    for name, g in co.items():
        if g['mtb'] < 3000:
            continue
        est = sum(site[str(n)]['cap'] / len(site[str(n)]['owners']) * fill.get(site[str(n)]['po'], 0) for n in g['sites'] & active if str(n) in site) / 1000
        comp.append({'co': name, 'mtb': round(g['mtb'] / 1000, 1), 'other': round(g['other'] / 1000, 1), 'lic': g['lic'], 'sites': len(g['sites']), 'active': g['active'], 'active_cap': round(g['active_cap'] / 1000), 'est_bio': round(est, 1), 'use': round(100 * est / (g['mtb'] / 1000)) if g['mtb'] else None})
    comp.sort(key=lambda c: -c['mtb'])
    # licences par formal (commerciales, developpement, recherche, enseignement, exposition, stamfisk...) : tonnage et principaux titulaires
    EN = {'commercial': 'Commercial', 'utvikling': 'Development', 'forskning': 'Research', 'undervisning': 'Teaching', 'visning': 'Display (visitor centres)', 'stamfisk': 'Broodstock', 'fiskepark': 'Fish park', 'slaktemerd': 'Slaughter pens'}
    bt = collections.defaultdict(lambda: {'n': 0, 'mtb': 0.0, 'by': collections.Counter()})
    for t, (n, k) in lic.items():
        b = bt[typ[t]]
        b['n'] += 1; b['mtb'] += k; b['by'][group(n)] += k
    types = sorted(({'t': EN.get(k, k.capitalize()), 'key': k, 'n': v['n'], 'mtb': round(v['mtb'] / 1000, 1), 'top': [[h, round(x / 1000, 1)] for h, x in v['by'].most_common(4)]} for k, v in bt.items()), key=lambda z: -z['mtb'])
    tot_c = sum(k for t, (n, k) in lic.items() if typ[t] == 'commercial') / 1000
    tot_all = sum(k for n, k in lic.values()) / 1000
    nat_bio = sum(bio[po].get(last, 0) for po in bio)
    top_sites = sorted(site.values(), key=lambda s_: -s_['cap'])[:0]
    return {'date': f'{date.group(3)}-{date.group(2)}-{date.group(1)}' if date else None, 'register_month': last, 'bw_week': week, 'mtb_commercial': round(tot_c), 'mtb_all': round(tot_all), 'licences': len(lic), 'sites': len(site),
            'biomass': round(nat_bio), 'use_commercial': round(100 * nat_bio / tot_c), 'use_all': round(100 * nat_bio / tot_all), 'types': types, 'companies': comp[:30], 'zones': zones,
            'note': 'Estimated biomass per farmer = capacity of its active sites x the filling rate of the production area (register biomass / capacity of all active sites); a site shared by two farmers is split equally.',
            'source': 'Fiskeridirektoratet, Akvakulturregisteret (daily dump) · BarentsWatch site status · Biomasseregisteret'}


PROD = [('fresh_whole', r'fersk laks \('), ('frozen_whole', r'fryst laks \('), ('fresh_fillet', r'fersk laksefilet'), ('frozen_fillet', r'fryst laksefilet'), ('trout_fresh', r'fersk oppdrettet ørret')]
EN = {'U S A': 'USA', 'De Forente Arabiske Emirater': 'UAE', 'Saudi-Arabia': 'Saudi Arabia', 'Polen': 'Poland', 'Nederland': 'Netherlands', 'Frankrike': 'France', 'Spania': 'Spain', 'Kina': 'China', 'Danmark': 'Denmark', 'Italia': 'Italy', 'Storbritannia': 'United Kingdom', 'Tyskland': 'Germany', 'Litauen': 'Lithuania',
      'Sverige': 'Sweden', 'Sør-Korea': 'South Korea', 'Ukraina': 'Ukraine', 'Tyrkia': 'Turkey', 'Hongkong SAR': 'Hong Kong', 'De forente arabiske emirater': 'UAE', 'Tsjekkia': 'Czechia', 'Irland': 'Ireland', 'Hellas': 'Greece',
      'Belgia': 'Belgium', 'Estland': 'Estonia', 'Sveits': 'Switzerland', 'Marokko': 'Morocco', 'Sør-Afrika': 'South Africa', 'Filippinene': 'Philippines', 'Libanon': 'Lebanon', 'TOTALT': 'Total', 'Aserbajdsjan': 'Azerbaijan'}


def weekly():
    out = []
    n = lambda s: float(s.replace('.', '').replace(',', '.'))
    for f in sorted(glob.glob(os.path.join(NO, 'nsc_ukestat_*.txt'))):
        m = re.search(r'(\d{4})_(\d\d)\.txt', f)
        y, w = int(m.group(1)), int(m.group(2))
        cur, tabs = None, collections.defaultdict(list)
        for line in open(f, encoding='utf-8'):
            line = line.strip()
            if line.startswith('Norsk eksport av'):
                cur = next((k for k, rx in PROD if re.search(rx, line)), None)
                continue
            if not cur:
                continue
            mm = re.match(r'^(.+?)\s+([\d.]+)\s+(\d+,\d\d)\s+([\d.]+)\s+(\d+,\d\d)\s+([\d.]+)\s+(\d+,\d\d)\s+([\d.]+)\s+(\d+,\d\d)$', line)
            if mm:
                c = mm.group(1)
                tabs[cur].append({'c': EN.get(c, c), 't': n(mm.group(2)), 'p': n(mm.group(3)), 't_ly': n(mm.group(4)), 'p_ly': n(mm.group(5)), 'ytd': n(mm.group(6)), 'p_ytd': n(mm.group(7)), 'ytd_ly': n(mm.group(8)), 'p_ytd_ly': n(mm.group(9))})
        if tabs.get('fresh_whole'):
            out.append({'y': y, 'w': w, 'tables': {k: v[:28] for k, v in tabs.items()}})
    return {'weeks': out[-8:], 'source': 'Norges sjømatråd (Norwegian Seafood Council), weekly statistics; customs data via Statistics Norway. Norwegian exports only, FOB Norwegian border.'} if out else None


def main():
    out = {'meta': {'generated': dt.date.today().isoformat()}, 'quality': quality(), 'capacity': capacity(), 'weekly': weekly()}
    out['turnover'] = turnover((out['quality'] or {}).get('quarters', []))
    json.dump(out, open(os.path.join(ROOT, 'data', 'no_extra.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    q, c, w = out['quality'], out['capacity'], out['weekly']
    print('no_extra.json :', f"qualite {q['quarters'][-1]}" if q else 'qualite absente', '|', f"MTB {c['mtb_commercial']} kt, biomasse {c['biomass']} kt ({c['use_commercial']} %)" if c else 'registre absent', '|', f"{len(w['weeks'])} semaines sjomatrad" if w else 'hebdo absent')


if __name__ == '__main__':
    main()
