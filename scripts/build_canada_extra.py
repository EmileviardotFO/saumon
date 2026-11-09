#!/usr/bin/env python3
"""
Construit data/canada_extra.json : ce qui complete l'onglet Canada pour le rapprocher de l'onglet Islande.

Sources (toutes publiques) :
  - US Census, importations par poste-frontiere (endpoint porths, SH 030214 saumon atlantique frais entier)
    + quantites par pays (endpoint hs) : Blaine (WA) = Colombie-Britannique, Calais / Houlton (Maine) = cote Atlantique.
    Les postes routiers ne declarent pas de poids : les tonnes par cote = tonnes du Canada x part de la valeur du poste.
  - DFO Pacifique, classification des carcasses par ferme et par mois (2013 ->) : statut de production
    (mise a l'eau de smolts / croissance / recolte) et mortalite mensuelle en % par cause.
  - NOAA OISST v2.1 (ERDDAP) : temperature de surface de la mer, moyenne mensuelle par zone d'elevage.

    python3 scripts/build_canada_extra.py              # telecharge puis calcule
    python3 scripts/build_canada_extra.py --cache DIR  # relit / ecrit les donnees brutes dans DIR (mise au point)
"""
import argparse
import csv
import datetime as dt
import io
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'canada_extra.json')
UA = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; data refresh)'}
CARC = ('https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/0a8c5505-ecb3-4d8b-8120-462bd7def6bb/attachments/'
        'carc-cat-fac-inst-2013-ongoing-rpt-pac-dfo-mpo-aquaculture-eng.csv')
PORTHS = 'https://api.census.gov/data/timeseries/intltrade/imports/porths'
HS = 'https://api.census.gov/data/timeseries/intltrade/imports/hs'
FIRST_YEAR = 2018
MOIS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                    'september', 'october', 'november', 'december'], 1)}
SOCIETE = {'Marine Harvest Canada': 'MOWI Canada West', 'Mainstream Canada': 'Cermaq Canada',
           'Cermaq British Columbia': 'Cermaq Canada'}
# zones de temperature (point en mer proche des fermes)
SST_ZONES = [
    ('bc_broughton', 'BC · Broughton / Queen Charlotte Strait', 'BC', 50.70, -126.55),
    ('bc_north_island', 'BC · Quatsino / Port Hardy', 'BC', 50.45, -127.80),
    ('bc_nootka', 'BC · Nootka / Esperanza', 'BC', 49.75, -126.75),
    ('bc_clayoquot', 'BC · Clayoquot Sound', 'BC', 49.20, -126.05),
    ('nb_fundy', 'New Brunswick · Bay of Fundy', 'ATL', 44.95, -66.90),
    ('ns_south', 'Nova Scotia · South Shore', 'ATL', 43.95, -64.60),
    ('nl_south', 'Newfoundland · South Coast (Fortune Bay)', 'ATL', 47.45, -55.60),
]


def http(url, tries=3, timeout=120):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (204, 404): return e.code, b''
            last = e
        except Exception as e:
            last = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f'{url[:120]} : {last}')


def ym(k):
    return int(k[:4]) * 100 + int(k[5:7])


def mback(k, n):
    y, m = divmod(k, 100); t = y * 12 + m - 1 - n
    return (t // 12) * 100 + t % 12 + 1


def mdiff(a, b):
    """mois de b a a"""
    return (a // 100 - b // 100) * 12 + a % 100 - b % 100


# ----------------------------------------------------------------------------- telechargements
def fetch_ports(key):
    """{yyyymm: {port: [nom, valeur USD]}} pour le Canada, SH 030214 ; et {yyyymm: kg} au niveau pays."""
    ports, qty = {}, {}
    this = dt.date.today().year
    for y in range(FIRST_YEAR, this + 1):
        q = {'get': 'PORT,PORT_NAME,CTY_CODE,GEN_VAL_MO', 'I_COMMODITY': '030214', 'time': f'from {y}-01 to {y}-12'}
        if key: q['key'] = key
        st, raw = http(PORTHS + '?' + urllib.parse.urlencode(q, safe=',:'))
        if st == 204 or not raw: continue
        if not raw.lstrip().startswith(b'['):
            raise RuntimeError('Census porths : reponse inattendue (cle d\'API manquante ?) ' + raw[:120].decode('utf-8', 'replace'))
        t = json.loads(raw); h = t[0]
        for r in t[1:]:
            d = dict(zip(h, r))
            if d['CTY_CODE'] != '1220' or d['PORT'] == '-': continue
            v = float(d['GEN_VAL_MO'] or 0)
            if v <= 0: continue
            ports.setdefault(str(ym(d['time'])), {})[d['PORT']] = [d['PORT_NAME'], v]
        q = {'get': 'CTY_CODE,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1', 'COMM_LVL': 'HS6', 'I_COMMODITY': '030214', 'time': f'from {y}-01 to {y}-12'}
        if key: q['key'] = key
        st, raw = http(HS + '?' + urllib.parse.urlencode(q, safe=',:'))
        if st == 204 or not raw: continue
        t = json.loads(raw); h = t[0]
        for r in t[1:]:
            d = dict(zip(h, r))
            if d['CTY_CODE'] != '1220': continue
            qty[str(ym(d['time']))] = [float(d['GEN_QY1_MO'] or 0), float(d['GEN_VAL_MO'] or 0), d.get('UNIT_QY1')]
        print(f'  Census {y} : {sum(1 for k in ports if k.startswith(str(y)))} mois par poste, {sum(1 for k in qty if k.startswith(str(y)))} au niveau pays')
    return {'ports': ports, 'qty': qty}


def fetch_carcass():
    st, raw = http(CARC)
    if st != 200: raise RuntimeError(f'DFO carcasses : {st}')
    return raw.decode('utf-8-sig', 'replace')


def fetch_sst():
    """Moyennes mensuelles de temperature de surface : NOAA OISST v2.1 (libre de droits, via ERDDAP), maille de mer la plus proche
    (memes fonctions que scripts/build_sea_temp.py). Open-Meteo, utilise d'abord, n'autorise que l'usage non commercial."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_sea_temp as BST
    out = {}
    for zid, lab, coast, la, lo in SST_ZONES:
        got = {}
        cell = BST.maille(la, lo)
        if cell:
            m = defaultdict(list)
            for d, v in BST.oisst(cell[0], cell[1], '2016-01-01', None).items():
                m[d[:7]].append(v)
            got = {str(ym(k)): round(sum(v) / len(v), 2) for k, v in m.items() if len(v) >= 20}
        out[zid] = got
        print(f'  SST {zid} : {len(out[zid])} mois (maille {cell})')
    return out


# ----------------------------------------------------------------------------- calculs
def pct(s):
    s = (s or '').strip().replace('%', '')
    try: return float(s)
    except ValueError: return None


def port_group(code):
    d = code[:2]
    if d in ('30', '31', '29', '32', '25', '27', '28'): return 'pac'     # Washington, Alaska, Oregon, Hawaii, Californie
    if d in ('01', '04', '05', '10', '11', '13', '14', '15', '16', '18', '52'): return 'atl'   # Maine, Boston, cote Est
    return 'mid'                                                         # Grands Lacs, New York interieur, Dakota...


def us_tonnes():
    """Tonnes de saumon atlantique frais entier importees du Canada (US Census HTS10, deja lu par
    update_national_trade.py dans data/us_imports.json, forme 0) : {yyyymm: [kg, USD, unite]}."""
    p = os.path.join(ROOT, 'data', 'us_imports.json')
    if not os.path.exists(p): return {}
    d = json.load(open(p))
    return {str(r[0]): [r[3] * 1000, r[4] * 1000, 'kg'] for r in d.get('rows', []) if r[1] == 'CA' and r[2] == 0}


def build_ports(P):
    ports, qty = P['ports'], us_tonnes() or P['qty']
    months = sorted(set(ports) | set(qty), key=int)
    rows, names, by_port = [], {}, defaultdict(float)
    for k in months:
        g = {'pac': 0.0, 'atl': 0.0, 'mid': 0.0}
        for code, (nm, v) in (ports.get(k) or {}).items():
            g[port_group(code)] += v; names[code] = nm; by_port[code] += v
        tv = sum(g.values())
        kg, val, unit = (qty.get(k) or [None, None, None])
        if not tv and not kg: continue
        t = (kg or 0) / 1000
        r = {'m': int(k), 'usd': round(tv or (val or 0)), 't': round(t, 1) if kg else None}
        for c in g:
            r[c + '_usd'] = round(g[c])
            r[c + '_t'] = round(t * g[c] / tv, 1) if tv and kg else None
        r['usd_kg'] = round(val / kg, 2) if kg and val else None
        rows.append(r)
    top = sorted(by_port.items(), key=lambda x: -x[1])[:12]
    tot = sum(by_port.values()) or 1
    return {'rows': rows, 'ports': [{'code': c, 'name': names[c], 'group': port_group(c), 'share': round(100 * v / tot, 1)} for c, v in top]}


def build_carcass(text):
    rd = csv.DictReader(io.StringIO(text))
    recs = []
    causes = None
    for r in rd:
        if causes is None:
            causes = [c for c in rd.fieldnames if c.endswith('(%/month)') and not c.startswith('Total')]
        try: k = int(r['Year']) * 100 + MOIS[r['Month'].strip().lower()]
        except (KeyError, ValueError): continue
        sp = (r.get('Species') or '').lower()
        st = (r.get('Production Information & Report Status') or '').strip().lower()
        st = 'smolt' if st.startswith('smolt') else 'harvest' if st.startswith('harv') else 'grow' if st.startswith('grow') else st or 'na'
        co = r['Licence Holder'].strip(); co = SOCIETE.get(co, co)
        recs.append({'k': k, 'id': r['Facility Reference Number'].strip(), 'n': r['Site Common Name'].strip(), 'co': co,
                     'amu': r['Aquaculture Management Unit'].strip(), 'lat': r.get('Latitude'), 'lon': r.get('Longitude'),
                     'atl': 'atlantic' in sp, 'st': st, 'tot': pct(r.get('Total Mortality (%/month)')),
                     'c': {c.replace(' (%/month)', ''): pct(r.get(c)) for c in causes}})
    atl = [r for r in recs if r['atl']]
    months = sorted({r['k'] for r in atl})
    cause_names = [c.replace(' (%/month)', '') for c in causes]
    # par mois
    mon = []
    for k in months:
        rr = [r for r in atl if r['k'] == k]
        tots = [r['tot'] for r in rr if r['tot'] is not None]
        row = {'m': k, 'sites': len(rr), 'smolt': sum(r['st'] == 'smolt' for r in rr), 'harvest': sum(r['st'] == 'harvest' for r in rr),
               'grow': sum(r['st'] == 'grow' for r in rr), 'mort': round(statistics.mean(tots), 3) if tots else None,
               'mort_med': round(statistics.median(tots), 3) if tots else None}
        row['cause'] = {c: round(statistics.mean([r['c'][c] for r in rr if r['c'][c] is not None] or [0]), 3) for c in cause_names}
        mon.append(row)
    # par entreprise et par mois : [fermes, smolt, recolte, mortalite moyenne]
    byco = defaultdict(dict)
    for co in sorted({r['co'] for r in atl}):
        for k in months:
            rr = [r for r in atl if r['k'] == k and r['co'] == co]
            if not rr: continue
            t = [r['tot'] for r in rr if r['tot'] is not None]
            byco[co][str(k)] = [len(rr), sum(r['st'] == 'smolt' for r in rr), sum(r['st'] == 'harvest' for r in rr),
                                round(statistics.mean(t), 3) if t else None]
    # cycles par ferme : mise a l'eau = premier mois d'un bloc "smolt" ; un cycle s'arrete au premier trou de 3 mois
    bysite = defaultdict(list)
    for r in atl: bysite[r['id']].append(r)
    cycles, sites = [], []
    last = months[-1]
    for sid, rr in bysite.items():
        rr.sort(key=lambda r: r['k'])
        cyc = None
        prev = None
        for r in rr:
            gap = mdiff(r['k'], prev) if prev else 99
            if cyc is not None and cyc['end'] is None and gap > 4:
                cyc['end'] = prev                                   # jachere : le cycle est fini
            if r['st'] == 'smolt':
                open_ = cyc is not None and cyc['end'] is None
                if not open_ or cyc['harv0'] is not None or mdiff(r['k'], cyc['entry']) >= 6:
                    if open_: cyc['end'] = prev
                    cyc = {'id': sid, 'entry': r['k'], 'harv0': None, 'harv1': None, 'end': None, 'months': 0, 'mort': 0.0, 'last': r['k']}
                    cycles.append(cyc)
            if cyc is not None and cyc['end'] is None:
                cyc['months'] += 1
                cyc['mort'] += r['tot'] or 0
                cyc['last'] = r['k']
                if r['st'] == 'harvest':
                    if cyc['harv0'] is None: cyc['harv0'] = r['k']
                    cyc['harv1'] = r['k']
            prev = r['k']
        if cyc and cyc['end'] is None and mdiff(last, prev) > 3: cyc['end'] = prev
        lr = rr[-1]
        cur = cycles[-1] if cycles and cycles[-1]['id'] == sid else None
        m12 = [r['tot'] for r in rr if r['k'] > mback(last, 12) and r['tot'] is not None]
        sites.append({'id': sid, 'n': lr['n'], 'co': lr['co'], 'amu': lr['amu'], 'lat': float(lr['lat'] or 0), 'lon': float(lr['lon'] or 0),
                      'last': lr['k'], 'st': lr['st'] if lr['k'] == last else 'none',
                      'entry': cur['entry'] if cur and cur['end'] is None else None,
                      'harv0': cur['harv0'] if cur and cur['end'] is None else None,
                      'mort_last': lr['tot'] if lr['k'] == last else None,
                      'mort12': round(sum(m12), 2) if m12 else None, 'n12': len(m12)})
    # duree mise a l'eau -> premiere recolte, et duree de recolte, sur les cycles termines recents
    done = [c for c in cycles if c['harv0'] and c['end'] and c['entry'] >= 201501]
    to_h = [mdiff(c['harv0'], c['entry']) for c in done]
    h_len = [mdiff(c['harv1'], c['harv0']) + 1 for c in done]
    cyc_mort = [c['mort'] for c in done]
    stats = {'n_cycles': len(done), 'to_harvest_med': statistics.median(to_h) if to_h else None,
             'to_harvest_p25': sorted(to_h)[len(to_h) // 4] if to_h else None, 'to_harvest_p75': sorted(to_h)[3 * len(to_h) // 4] if to_h else None,
             'harvest_len_med': statistics.median(h_len) if h_len else None,
             'cycle_mort_med': round(statistics.median(cyc_mort), 1) if cyc_mort else None,
             'to_harvest_hist': {str(n): to_h.count(n) for n in sorted(set(to_h))}, 'harvest_len_hist': {str(n): h_len.count(n) for n in sorted(set(h_len))}}
    # mises a l'eau par mois (nombre de fermes qui commencent un cycle)
    entries = defaultdict(lambda: defaultdict(int))
    for c in cycles: entries[str(c['entry'])][next(s['co'] for s in sites if s['id'] == c['id'])] += 1
    site_months = {sid: sorted({r['k'] for r in rr}) for sid, rr in bysite.items()}
    return {'site_months': site_months, 'last': last, 'first': months[0], 'causes': cause_names, 'months': mon, 'by_company': byco,
            'sites': sorted(sites, key=lambda s: (s['st'] == 'none', s['co'], s['n'])), 'cycles': cycles, 'cycle_stats': stats,
            'entries': {k: dict(v) for k, v in sorted(entries.items())},
            'other_species_sites': len({r['id'] for r in recs if not r['atl'] and r['k'] == last})}


def build_sst(S):
    out = []
    for zid, lab, coast, la, lo in SST_ZONES:
        m = {int(k): v for k, v in (S.get(zid) or {}).items()}
        if not m: continue
        last = max(m)
        clim = defaultdict(list)
        for k, v in m.items():
            if k // 100 < last // 100: clim[k % 100].append(v)
        out.append({'id': zid, 'lab': lab, 'coast': coast, 'lat': la, 'lon': lo, 'm': {str(k): v for k, v in sorted(m.items())},
                    'clim': {str(mm): round(sum(v) / len(v), 2) for mm, v in sorted(clim.items())},
                    'clim_years': f'{min(m) // 100}–{last // 100 - 1}'})
    return out


def outlook(car, ports):
    """Recolte BC des 4 prochains trimestres a partir de la structure des fermes.

    Chaque ferme en cours de cycle a une date de mise a l'eau : on lui applique la distribution historique
    (cycles termines) du delai mise a l'eau -> premiere recolte et de la duree de recolte, pour obtenir
    le nombre attendu de "mois-fermes en recolte" par trimestre a venir. Converti en tonnes avec le volume
    moyen par mois-ferme en recolte des 12 derniers mois (tonnes des postes du Pacifique / mois-fermes en recolte).
    Retro-test : meme calcul refait a chaque fin de trimestre passee avec les seules donnees connues a ce moment.
    """
    mon = {r['m']: r for r in car['months']}
    pac = {r['m']: r['pac_t'] for r in ports['rows'] if r.get('pac_t') is not None}
    cycles = car['cycles']
    site_months = car.get('site_months') or {}
    CO = {x['id']: x['co'] for x in car.get('sites', [])}
    co_of = lambda c: 'Cermaq Canada (ex-Grieg BC)' if 'grieg' in CO.get(c['id'], '').lower() else CO.get(c['id'], '?')

    def dist(asof):
        done = [c for c in cycles if c['harv0'] and c['end'] and c['end'] <= asof and c['entry'] >= mback(asof, 120)]
        th = [mdiff(c['harv0'], c['entry']) for c in done]
        hl = [mdiff(c['harv1'], c['harv0']) + 1 for c in done]
        return th, hl

    def project(asof, nq=4):
        th, hl = dist(asof)
        if len(th) < 15: return None
        # cycles en cours a la date asof
        live = []
        for c in cycles:
            if c['entry'] > asof: continue
            end = c['end']
            if end is not None and end <= asof: continue
            # derniere declaration connue a la date asof : la ferme doit avoir declare dans les 3 derniers mois
            seen = [k for k in site_months.get(c['id'], ()) if k <= asof]
            if not seen or mdiff(asof, max(seen)) > 3: continue
            started = c['harv0'] is not None and c['harv0'] <= asof
            # une ferme en recolte qui ne declare plus le mois de reference a ete videe (une ferme avec du poisson declare chaque mois) ;
            # sans ce test, Koskimo, Mahatta East, Bawden et Dixon Bay (vides en avril-mai 2026) restaient « en recolte » jusqu'en 2027
            if started and max(seen) < asof: continue
            live.append((c, started))
        fut = [mback(asof, -i) for i in range(1, 3 * nq + 1)]
        exp = {k: 0.0 for k in fut}
        eco = defaultdict(lambda: defaultdict(float))      # meme calcul, par entreprise
        pairs = [(a, b) for a in th for b in hl]
        for c, started in live:
            age = mdiff(asof, c['entry'])
            if started:
                done_h = mdiff(asof, c['harv0']) + 1
                cand = [b for b in hl if b > done_h] or [done_h + 1]
                for b in cand:
                    for i in range(1, b - done_h + 1):
                        k = mback(asof, -i)
                        if k in exp: exp[k] += 1 / len(cand); eco[co_of(c)][k] += 1 / len(cand)
            else:
                cand = [(a, b) for a, b in pairs if a > age] or [(age + 1, statistics.median(hl))]
                w = 1 / len(cand)
                for a, b in cand:
                    for i in range(int(b)):
                        k = mback(c['entry'], -(a + i))
                        if k in exp: exp[k] += w; eco[co_of(c)][k] += w
        # mises a l'eau a venir : autant que sur les 12 mois precedents, decalees d'un an
        newx = {k: 0.0 for k in fut}
        starts = defaultdict(int)
        for c in cycles:
            if mback(asof, 12) < c['entry'] <= asof: starts[c['entry']] += 1
        for m0, n in starts.items():
            e = mback(m0, -12)
            for a, b in pairs:
                for i in range(int(b)):
                    k = mback(e, -(a + i))
                    if k in newx: newx[k] += n / len(pairs)
        # tonnes par mois-ferme en recolte, 12 derniers mois connus
        hist = [k for k in sorted(mon) if k <= asof][-12:]
        hs = sum(mon[k]['harvest'] for k in hist)
        ts = sum(pac.get(k, 0) for k in hist)
        if not hs or not ts: return None
        rate = ts / hs
        q = []
        for i in range(nq):
            ks = fut[3 * i:3 * i + 3]
            sm, sn = sum(exp[k] for k in ks), sum(newx[k] for k in ks)
            q.append({'q': f'{ks[0] // 100}Q{(ks[0] % 100 + 2) // 3}', 'months': ks, 'site_months': round(sm + sn, 1),
                      't': round((sm + sn) * rate), 't_in_sea': round(sm * rate), 't_future_smolt': round(sn * rate),
                      'by_co': {co: round(sum(v[k] for k in ks), 1) for co, v in sorted(eco.items())}})
        return {'asof': asof, 'rate_t_per_site_month': round(rate, 1), 'live_cycles': len(live),
                'started': sum(1 for _, s in live if s), 'new_entries_12m': sum(starts.values()), 'quarters': q}

    last = car['last']
    # on cale le point de depart sur une fin de trimestre
    asof = last if last % 100 in (3, 6, 9, 12) else mback(last, last % 100 % 3)
    cur = project(asof, 6)
    # retro-test
    bt = []
    k = 202103
    while k <= mback(asof, 3):
        p = project(k, 4)
        if p:
            for i, qq in enumerate(p['quarters']):
                act = [pac.get(m) for m in qq['months']]
                if all(a is not None for a in act):
                    bt.append({'asof': k, 'h': i + 1, 'q': qq['q'], 'pred': qq['t'], 'act': round(sum(act))})
        k = mback(k, -3)
    err = {}
    # erreur sur la somme des 4 trimestres suivants (le chiffre annuel est plus fiable que chaque trimestre)
    yr = defaultdict(lambda: [0, 0, 0])
    for b in bt: yr[b['asof']][0] += b['pred']; yr[b['asof']][1] += b['act']; yr[b['asof']][2] += 1
    ya = [(k, v[0] / v[1] - 1) for k, v in sorted(yr.items()) if v[2] == 4 and v[1] > 0 and k >= 202301]
    if ya: err['year'] = {'mape': round(100 * statistics.mean(abs(e) for _, e in ya), 1), 'bias': round(100 * statistics.mean(e for _, e in ya), 1),
                         'n': len(ya), 'points': [{'asof': k, 'err': round(100 * e, 1)} for k, e in ya]}
    for h in (1, 2, 3, 4):
        e = [abs(b['pred'] / b['act'] - 1) for b in bt if b['h'] == h and b['act'] > 0 and b['asof'] >= 202401]
        b_ = [b['pred'] / b['act'] - 1 for b in bt if b['h'] == h and b['act'] > 0 and b['asof'] >= 202401]
        if e: err[str(h)] = {'mape': round(100 * statistics.mean(e), 1), 'bias': round(100 * statistics.mean(b_), 1), 'n': len(e)}
    # trimestres observes (tonnes Pacifique) pour comparaison
    obs = defaultdict(lambda: [0, 0])
    for m, v in pac.items():
        qk = f'{m // 100}Q{(m % 100 + 2) // 3}'; obs[qk][0] += v; obs[qk][1] += 1
    obs_co = defaultdict(lambda: defaultdict(int))
    for co, d in (car.get('by_company') or {}).items():
        cn = 'Cermaq Canada (ex-Grieg BC)' if 'grieg' in co.lower() else co
        for m, v in d.items(): m = int(m); obs_co[cn][f'{m // 100}Q{(m % 100 + 2) // 3}'] += v[2]
    return {'current': cur, 'backtest': bt, 'errors': err, 'observed_sites_harvesting': {c: dict(v) for c, v in obs_co.items()},
            'observed': {k: round(v[0]) for k, v in sorted(obs.items()) if v[1] == 3}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', help='dossier de donnees brutes (relu s\'il existe, ecrit sinon)')
    ap.add_argument('--dump', action='store_true', help='imprime les donnees brutes compressees (sonde)')
    a = ap.parse_args()
    raw = None
    if a.cache and os.path.exists(os.path.join(a.cache, 'raw.json')):
        raw = json.load(open(os.path.join(a.cache, 'raw.json')))
    if raw is None:
        key = os.environ.get('CENSUS_API_KEY', '')
        raw = {}
        try: raw['ports'] = fetch_ports(key)
        except Exception as e: print('  ERREUR Census :', e); raw['ports'] = None
        try: raw['carcass'] = fetch_carcass()
        except Exception as e: print('  ERREUR DFO :', e); raw['carcass'] = None
        try: raw['sst'] = fetch_sst()
        except Exception as e: print('  ERREUR SST :', e); raw['sst'] = None
        if a.cache:
            os.makedirs(a.cache, exist_ok=True); json.dump(raw, open(os.path.join(a.cache, 'raw.json'), 'w'))
    if a.dump:
        import base64, gzip
        b = base64.b64encode(gzip.compress(json.dumps(raw).encode())).decode()
        print('===RAW-BEGIN===')
        for i in range(0, len(b), 8000): print(b[i:i + 8000])
        print('===RAW-END===')
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    out = {'meta': {'built': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}}
    out['ports'] = build_ports(raw['ports']) if raw.get('ports') else old.get('ports')
    out['carcass'] = build_carcass(raw['carcass']) if raw.get('carcass') else old.get('carcass')
    out['sst'] = build_sst(raw['sst']) if raw.get('sst') else old.get('sst')
    if out['carcass'] and out['ports']:
        try: out['outlook'] = outlook(out['carcass'], out['ports'])
        except Exception as e: print('  ERREUR perspectives :', e); out['outlook'] = old.get('outlook')
    if out['carcass']:
        out['carcass'].pop('cycles', None); out['carcass'].pop('site_months', None)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('ecrit', OUT, os.path.getsize(OUT), 'octets')


if __name__ == '__main__':
    main()
