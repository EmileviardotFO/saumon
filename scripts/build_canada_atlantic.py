#!/usr/bin/env python3
"""
data/canada_atl.json : tout ce qui est public sur le saumon d'elevage de la cote atlantique du Canada.

Sources (toutes publiques, relues a chaque mise a jour) :
  Nouveau-Brunswick  Programme de cartographie des sites aquacoles marins (PCSAM / MASMP) - poissons, gnb.socrata.com
                     (numero de site MF-xxxx, titulaire, statut, echeance, surface, espece, plan d'eau, contour)
                     Registre aquacole public (dnr-mrn.gnb.ca/AquacultureRegistry) : conditions a declaration obligatoire
                     par zone de gestion (ABMA) et evasions
  Nouvelle-Ecosse    Baux aquacoles marins et licences a terre, data.novascotia.ca ; production par comte
  Terre-Neuve        Liste des titulaires de licences aquacoles (PDF, gov.nl.ca) avec coordonnees ;
                     poissons mis en cage par site (reponse d'acces a l'information 2024, publiee par l'ASF) ;
                     rapport annuel du code de confinement (production, sites actifs)
  Canada             Peches et Oceans : medicaments et pesticides declares par site (Reglement sur les activites
                     d'aquaculture, 2016 ->) ; ACIA : foyers d'anemie infectieuse du saumon (AIS) ;
                     Statistique Canada 32-10-0107 (production par province) et 32-10-0005 (exportations aquacoles)

    python3 scripts/build_canada_atlantic.py [--cache DOSSIER]
"""
import csv
import html
import io
import json
import math
import os
import re
import sys
import time
import zipfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'canada_atl.json')
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
CACHE = sys.argv[sys.argv.index('--cache') + 1] if '--cache' in sys.argv else None
csv.field_size_limit(10 ** 9)

DFO = 'https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/288b6dc4-16dc-43cc-80a4-2a45b1f93383/attachments/'
SRC = {
    'nb_sites': ('NB_djwg-syd8', 'https://gnb.socrata.com/api/views/djwg-syd8/rows.csv?accessType=DOWNLOAD'),
    'nb_reg': ('NB_REG', 'https://dnr-mrn.gnb.ca/AquacultureRegistry/'),
    'ns_leases': ('NS_LEASES', 'https://data.novascotia.ca/api/views/h57h-p9mm/rows.csv?accessType=DOWNLOAD'),
    'ns_land': ('NS_LAND', 'https://data.novascotia.ca/api/views/yqwg-f62a/rows.csv?accessType=DOWNLOAD'),
    'ns_prod': ('NS_PROD', 'https://data.novascotia.ca/api/views/v2ex-ev63/rows.csv?accessType=DOWNLOAD'),
    'nl_lic': ('nl_licences.pdf', None),           # URL lue sur la page des licences (le nom du PDF change a chaque edition)
    'nl_stock': ('nl_stock.pdf', 'https://asf.ca/wp-content/uploads/2024/10/ATIPP-2024-Salmon-Licenses-and-Stocking-in-NL.pdf'),
    'nl_coc': ('NL_COC24', 'https://www.gov.nl.ca/fisheries/files/Annual-Code-of-Containment-Compliance-Report-2024.pdf'),
    'isa': ('CFIA_ISA', 'https://inspection.canada.ca/en/animal-health/aquatic-animals/diseases/reportable-diseases/isa/locations-infected'),
    'sc_prod': ('STATCAN_PROD', 'https://www150.statcan.gc.ca/n1/tbl/csv/32100107-eng.zip'),
    'sc_exp': ('STATCAN_EXP', 'https://www150.statcan.gc.ca/n1/tbl/csv/32100005-eng.zip'),
}
NL_LIC_PAGE = 'https://www.gov.nl.ca/fisheries/licenses-permits-and-fees/licensing/'
NL_LIC_FALLBACK = 'https://www.gov.nl.ca/fisheries/files/Active-Aquaculture-Licences-Aug-18-2026.pdf'

# exploitants : nom du titulaire -> groupe
GROUPS = [(r'kelly cove|cooke|cold ocean|true north', 'Cooke Aquaculture'), (r'mowi|northern harvest', 'Mowi Canada East'),
          (r'cermaq|grieg', 'Cermaq Canada (ex-Grieg NL)'), (r'nova fish farms', 'Nova Fish Farms'), (r'ocean trout', 'Ocean Trout Farms'),
          (r'snow island', 'Snow Island Salmon'), (r'wfn|we.?koqma', "We'koqma'q First Nation (WFN Fish Farm)"), (r'benson', 'Benson Aquaculture'),
          (r'sustainable blue', 'Sustainable Blue'), (r'admiral', 'Admiral Fish Farms')]


def group(name):
    for rx, g in GROUPS:
        if re.search(rx, name or '', re.I):
            return g
    return re.sub(r'(?i)[,.]?\s*(ltd|inc|limited|limited partnership|corp)\.?$', '', (name or '').strip()) or '—'


def fetch(key, url=None, binary=False):
    tag, u = SRC.get(key, (key, None))
    u = url or u
    if CACHE and os.path.exists(os.path.join(CACHE, tag)):
        b = open(os.path.join(CACHE, tag), 'rb').read()
    else:
        r = requests.get(u, headers=H, timeout=180); r.raise_for_status(); b = r.content
    return b if binary else b.decode('utf-8-sig', errors='replace')


def centroid(wkt):
    nums = [float(x) for x in re.findall(r'-?\d+\.\d+', wkt or '')]
    if len(nums) < 2:
        return None, None
    lo, la = nums[0::2], nums[1::2]
    return round(sum(la) / len(la), 5), round(sum(lo) / len(lo), 5)


def dms(s):
    m = re.match(r"\s*(-?)(\d+)\D+(\d+)\D+([\d.]+)", s or '')
    if not m:
        return None
    v = int(m.group(2)) + int(m.group(3)) / 60 + float(m.group(4)) / 3600
    return round(-v if m.group(1) else v, 5)


def nb_sites():
    out = []
    for r in csv.DictReader(io.StringIO(fetch('nb_sites'))):
        la, lo = centroid(r['the_geom'])
        exp = r.get('AUTHORIZ_3') or ''
        m = re.match(r'(\d\d)/(\d\d)/(\d{4})', exp)
        out.append({'prov': 'NB', 'id': r['SITE_NUMBE'], 'name': r['WATERBODY_'], 'holder': r['AUTHORIZ_2'], 'group': group(r['AUTHORIZ_2']),
                    'species': re.sub(r'\d+:\s*', '', r['SPECIES_CO']) or None, 'status': r['AUTHORIZ_1'], 'auth': r['AUTHORIZAT'],
                    'expiry': f'{m.group(3)}-{m.group(1)}-{m.group(2)}' if m else None, 'ha': round(float(r['SIZE_HA']), 1) if r['SIZE_HA'] else None,
                    'lat': la, 'lon': lo, 'type': 'marine'})
    return out


def ns_sites():
    out = []
    fin = re.compile(r'(?i)salmon|trout|char|halibut|cod|steelhead|bass|haddock|sablefish|finfish')
    for r in csv.DictReader(io.StringIO(fetch('ns_leases'))):
        if not fin.search(r['Species'] + ' ' + r['SpeciesTyp']):
            continue
        la, lo = dms(r['Lat_DMS']), dms(r['Long_DMS'])
        if la is None:
            la, lo = centroid(r['the_geom'])
        out.append({'prov': 'NS', 'id': r['License_Le'], 'name': r['Waterbody'], 'holder': r['Ownership'], 'group': group(r['Ownership']),
                    'species': r['Species'], 'status': r['SiteStatus'], 'county': r['County'], 'ha': float(r['Hectares']) if r['Hectares'] else None,
                    'lat': la, 'lon': lo, 'type': 'marine'})
    for r in csv.DictReader(io.StringIO(fetch('ns_land'))):
        if not re.search(r'(?i)salmon|trout|char', r['Species']):
            continue
        la, lo = dms(r['Lat_DMS']), dms(r['Long_DMS'])
        out.append({'prov': 'NS', 'id': r['License_Le'], 'name': r['County'] + ' (land-based)', 'holder': r['Ownership'], 'group': group(r['Ownership']),
                    'species': r['Species'], 'status': r['SiteStatus'], 'county': r['County'], 'lat': la, 'lon': lo, 'type': 'land'})
    return out


def nl_licence_url():
    try:
        t = requests.get(NL_LIC_PAGE, headers=H, timeout=60).text
        m = re.findall(r'href="([^"]*Active-Aquaculture-Licen[^"]*\.pdf)"', t, re.I)
        if m:
            return requests.compat.urljoin(NL_LIC_PAGE, m[0])
    except Exception:
        pass
    return NL_LIC_FALLBACK


def nl_sites():
    import pdfplumber
    url = None if CACHE else nl_licence_url()
    b = fetch('nl_lic', url or NL_LIC_FALLBACK, binary=True)
    out, edition = [], ''
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        edition = (re.search(r'AS OF ([A-Z]+ \d+, \d{4})', pdf.pages[0].extract_text() or '') or [None, ''])[1].title()
        for p in pdf.pages:
            for tb in p.extract_tables():
                for r in tb:
                    c = [re.sub(r'\s+', ' ', x or '').strip() for x in r]
                    c = [x for x in c if x]
                    i = next((k for k, x in enumerate(c) if re.match(r'AQ\d\d-LIC-?\d+', x)), None)
                    if i is None or len(c) - i < 5:
                        continue
                    c = c[i:]
                    nums = [x for x in c if re.fullmatch(r"-?\d+(\.\d+)?'?", x)]
                    if len(nums) < 2:
                        continue
                    la, lo = float(nums[-2].rstrip("'")), float(nums[-1].rstrip("'"))
                    lo = -abs(lo)
                    mid = [x for x in c[2:] if x not in nums]
                    sp = c[1]
                    if not re.search(r'(?i)salmon|steelhead|trout|char', sp):
                        continue
                    holder = mid[0] if mid else ''
                    out.append({'prov': 'NL', 'id': c[0].replace('LIC1', 'LIC-1'), 'name': ' '.join(mid[1:]), 'holder': holder, 'group': group(holder),
                                'species': sp, 'status': 'Licensed', 'lat': round(la, 5), 'lon': round(lo, 5),
                                'type': 'land' if re.search(r'(?i)nurser|hatcher|marystown|stephenville|wharf', ' '.join(mid)) else 'marine'})
    return out, edition, url


def nl_stocking():
    """poissons mis en cage par site, derniere mise en cage (reponse ATIPP 2024)"""
    import pdfplumber
    out = []
    try:
        b = fetch('nl_stock', binary=True)
    except Exception as e:  # noqa: BLE001
        print('  stockage NL :', e); return out
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        for p in pdf.pages:
            for tb in p.extract_tables():
                for r in tb:
                    c = [re.sub(r'\s+', ' ', x or '').strip() for x in r]
                    if len(c) >= 4 and re.search(r'\d{1,3}(,\d{3})+', c[-1] or '') and re.match(r'[A-Z][a-z]{2}-\d\d', c[1] or ''):
                        out.append({'site': c[0], 'date': c[1], 'species': c[2], 'n': int(c[-1].replace(',', ''))})
    return out


def site_key(s):
    return re.sub(r'[^a-z]', '', html.unescape(s or '').lower().replace("'", ''))[:14]


def aar(sites):
    """medicaments et pesticides declares (kg de matiere active), par site et par an, provinces atlantiques"""
    by_site, totals = {}, {}
    names = {}
    for s in sites:
        names.setdefault((s['prov'], s['id']), s)
        if s['prov'] == 'NS':                                   # Peches et Oceans : NS-0742 = bail AQ0742
            names.setdefault(('NS', 'NS-' + s['id'][2:]), s)
        if s['prov'] == 'NL':                                   # Peches et Oceans : 155 = licence AQ15-LIC-0155
            names.setdefault(('NL', str(int(s['id'][-4:]))), s)
    for s in sites:
        names.setdefault((s['prov'], site_key(s['name'])), s)
    PROV = {'New Brunswick': 'NB', 'Nova Scotia': 'NS', 'Newfoundland And Labrador': 'NL', 'Newfoundland and Labrador': 'NL', 'British Columbia': 'BC'}
    for y in range(2016, int(time.strftime('%Y'))):
        tag = f'DFO{y}' if y < 2022 else f'DFO_Marine_Finfish_Data_{y}'
        url = f'{DFO}marine-finfish-data-{y}.csv' if y < 2022 else f'{DFO}Marine%20Finfish%20Data%20{y}.csv'
        try:
            t = fetch(tag, url)
        except Exception:
            continue
        rows = list(csv.reader(io.StringIO(t)))
        hdr = next((r for r in rows if r and r[0].startswith('Facility')), None)
        if not hdr:
            continue
        subs = [h for h in hdr[2:] if h]
        prov = None
        for r in rows[rows.index(hdr) + 1:]:
            if not r or not any(r):
                continue
            if r[0] in PROV:
                prov = PROV[r[0]]; continue
            if not prov or prov == 'BC' or (len(r) > 1 and re.search(r'(?i)total', r[1] + r[0])):
                continue
            v = {s: float(x) for s, x in zip(subs, r[2:]) if x and re.fullmatch(r'[\d.]+', x)}
            if not v:
                continue
            T = totals.setdefault(prov, {}).setdefault(str(y), {})
            for k, x in v.items():
                T[k] = round(T.get(k, 0) + x, 2)
            s = names.get((prov, r[0])) or names.get((prov, site_key(r[1]))) or next((x for (p, k), x in names.items() if p == prov and k and site_key(r[1]).startswith(k[:8])), None)
            key = s['id'] if s else f'{prov}:{r[0]}'
            e = by_site.setdefault(key, {'prov': prov, 'facility': r[0], 'name': r[1], 'years': {}})
            e['years'][str(y)] = v
    return by_site, totals


def isa_table():
    t = fetch('isa')
    tb = re.search(r'(?s)<table.*?</table>', t)
    out = []
    for r in re.findall(r'(?s)<tr.*?</tr>', tb.group(0) if tb else ''):
        c = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', x))).strip() for x in re.findall(r'(?s)<t[hd][^>]*>(.*?)</t[hd]>', r)]
        if len(c) >= 4 and re.fullmatch(r'\d{4}', c[0]):
            out.append({'year': int(c[0]), 'date': re.sub(r'\s*Table note.*$', '', c[1]), 'prov': c[2], 'species': c[3]})
    return out


def nb_registry():
    t = fetch('nb_reg')
    x = re.sub(r'(?s)<script.*?</script>|<style.*?</style>', '', t)
    x = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', x)))
    cond, esc = [], []
    i = x.find('Date of Report Nature Source Type of Report Actions Taken')
    j = x.find('ORDERS:', i)
    seg = x[i:j] if i >= 0 else ''
    for m in re.finditer(r'(\d{4}-\d\d-\d\d) (Finfish|Shellfish) Hazard (ABMA \w+|AMA \w+|[\w ]+?) (.+?)(?= \d{4}-\d\d-\d\d |$)', seg):
        rest = m.group(4)
        k = re.match(r'(Schedule\s*A\s*-\s*Part \d|Schedule 1- Part A|unknown cause of mortality|Elevated mortality)\s*(.*)', rest, re.I)
        cond.append({'date': m.group(1), 'kind': m.group(2), 'area': m.group(3), 'type': (k.group(1) if k else rest)[:80], 'action': (k.group(2) if k else '')[:200]})
    i = x.find('Final Number of Escapes/Loss Reported')
    seg = x[i:x.find('Authorized Aquaculture Sites', i)] if i >= 0 else ''
    for m in re.finditer(r'(\d{4}-\d\d-\d\d) (\w+) (Known|Suspect)\s*([\d,]*)', seg):
        esc.append({'date': m.group(1), 'area': m.group(2), 'type': m.group(3), 'fish': int(m.group(4).replace(',', '')) if m.group(4) else None})
    return cond, esc


def statcan():
    def rows(key):
        z = zipfile.ZipFile(io.BytesIO(fetch(key, binary=True)))
        n = [x for x in z.namelist() if 'Meta' not in x][0]
        return list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding='utf-8-sig')))
    prod = {}
    for r in rows('sc_prod'):
        if r['Finfish and shellfish'] not in ('Salmon', 'Trout', 'Steelhead') or not r['VALUE']:
            continue
        v = float(r['VALUE']) * (1000 if r['SCALAR_FACTOR'] == 'thousands' else 1)
        p = prod.setdefault(r['GEO'], {}).setdefault(r['Finfish and shellfish'], {}).setdefault(r['REF_DATE'], [None, None])
        p[0 if r['UOM'] == 'Tonnes' else 1] = round(v)
    exp = {}
    for r in rows('sc_exp'):
        if 'salmon' not in r['Aquacultural products'].lower() or not r['VALUE']:
            continue
        e = exp.setdefault(r['Aquacultural products'], {}).setdefault(r['Destination'], {}).setdefault(r['REF_DATE'], [None, None])
        e[0 if r['Estimates'] == 'Quantity' else 1] = round(float(r['VALUE']))
    return prod, exp


def ns_county():
    out = {}
    for r in csv.DictReader(io.StringIO(fetch('ns_prod'))):
        if r.get('KGS'):
            out.setdefault(r['Year'], {})[r['County']] = [round(float(r['KGS']) / 1000, 1), round(float(r['Total Value'] or 0))]
    return out


def nl_facts():
    import pdfplumber
    try:
        b = fetch('nl_coc', binary=True)
        with pdfplumber.open(io.BytesIO(b)) as pdf:
            t = ' '.join((p.extract_text() or '') for p in pdf.pages[:3])
    except Exception:
        return {}
    t = re.sub(r'\s+', ' ', t)
    f = {}
    m = re.search(r'consisted of (\w+) companies', t); f['companies'] = m.group(1) if m else None
    m = re.search(r'There were (\d+) sites licensed.*?(\d+) sites were in active production', t)
    if m:
        f['sites_licensed'], f['sites_active'] = int(m.group(1)), int(m.group(2))
    m = re.search(r'Production (?:increased|decreased) from ([\d,]+) metric tonnes in (\d{4}) to ([\d,]+) metric tonnes in (\d{4})', t)
    if m:
        f['production'] = {m.group(2): int(m.group(1).replace(',', '')), m.group(4): int(m.group(3).replace(',', ''))}
    f['year'] = (re.search(r'Compliance Report - (\d{4})', t) or [None, None])[1]
    return f


def main():
    old = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    out = {'meta': {'built': time.strftime('%Y-%m-%d'), 'sources': {}}}
    def step(name, fn, default):
        try:
            v = fn(); print(f'  {name} : ok'); return v
        except Exception as e:  # noqa: BLE001
            print(f'  {name} : ERREUR {e}'); return old.get(name, default)
    sites = step('nb', nb_sites, []) + step('ns', ns_sites, [])
    nl = step('nl', nl_sites, ([], '', None))
    if isinstance(nl, tuple):
        sites += nl[0]; out['meta']['nl_edition'] = nl[1]; out['meta']['nl_url'] = nl[2]
    else:
        sites += [s for s in (old.get('sites') or []) if s.get('prov') == 'NL']
    stock = step('nl_stocking', nl_stocking, [])
    for st in stock:
        k = site_key(st['site'])
        s = next((x for x in sites if x['prov'] == 'NL' and site_key(x['name']).startswith(k[:8])), None)
        if s:
            s['stocked'] = st
        st['matched'] = s['id'] if s else None
    by_site, totals = step('aar', lambda: aar(sites), ({}, {}))
    for s in sites:
        if s['id'] in by_site:
            s['aar'] = by_site[s['id']]['years']
        # site recemment en production : traitement declare les deux dernieres annees publiees ou poissons mis en cage depuis 2023
        ys = sorted(int(y) for y in (s.get('aar') or {}))
        s['recent'] = bool((ys and ys[-1] >= max([int(y) for t in totals.values() for y in t] or [0]) - 1) or (s.get('stocked') and s['stocked']['date'][-2:] >= '23'))
    out['sites'] = sites
    out['aar_unmatched'] = {k: v for k, v in by_site.items() if ':' in k}
    out['aar_totals'] = totals
    out['nl_stocking'] = stock
    out['isa'] = step('isa', isa_table, [])
    cond = step('nb_registry', nb_registry, ([], []))
    out['nb_conditions'], out['nb_escapes'] = cond if isinstance(cond, tuple) else (old.get('nb_conditions', []), old.get('nb_escapes', []))
    sc = step('statcan', statcan, ({}, {}))
    out['production'], out['exports'] = sc if isinstance(sc, tuple) else (old.get('production', {}), old.get('exports', {}))
    out['ns_county'] = step('ns_county', ns_county, {})
    out['nl_facts'] = step('nl_facts', nl_facts, {})
    out['meta']['sources'] = {
        'NB': 'Government of New Brunswick, Marine Aquaculture Site Mapping Program (finfish) and public Aquaculture Registry',
        'NS': 'Government of Nova Scotia open data: marine aquaculture leases, land-based licences, production by county',
        'NL': 'Government of Newfoundland and Labrador: aquaculture licence holders (PDF), Code of Containment compliance report; stocking by site from a 2024 access-to-information response (published by the Atlantic Salmon Federation)',
        'DFO': 'Fisheries and Oceans Canada, Aquaculture Activities Regulations public reporting: drugs and pesticides by site (kg of active ingredient)',
        'CFIA': 'Canadian Food Inspection Agency: locations infected with infectious salmon anaemia',
        'StatCan': 'Statistics Canada tables 32-10-0107 (production by province) and 32-10-0005 (aquaculture exports)'}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    from collections import Counter
    print('ecrit', OUT, f'{os.path.getsize(OUT) // 1024} ko ;', len(sites), 'sites', Counter((s['prov'], s['group']) for s in sites).most_common(12),
          '; AIS', len(out['isa']), '; NB conditions', len(out['nb_conditions']), '; AAR sites', len(by_site), 'dont non rattaches', len(out['aar_unmatched']))


if __name__ == '__main__':
    main()
