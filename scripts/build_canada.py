#!/usr/bin/env python3
"""
Construit data/canada.json pour l'onglet Canada (BC) du tableau de bord, a partir des
trois CSV du DFO Pacifique telecharges par farming/scripts/ingest_bc.py telecharger :

    farming/donnees_ca/brut/poux.csv        comptages de poux par ferme (2011 -> )
    farming/donnees_ca/brut/mortalite.csv   evenements de mortalite declares (2011 -> )
    farming/donnees_ca/brut/transferts.csv  licences de transfert de poissons (2015 -> )

Choix de calcul (voir aussi l'onglet) :
  - Fermes actives = fermes ayant au moins un comptage de poux dans le mois (obligatoire
    tous les mois sur une ferme en production) ; classe d'age 1 = moins d'un an en mer.
  - Poux moyens = moyenne des fermes, chaque ferme comptant une fois, sur les seuls comptages
    planifies (routine, pre-migration, debut de migration) : les comptages avant traitement
    ou apres depassement sont hauts par construction et biaiseraient la moyenne.
  - Fermes au-dessus du seuil = au moins un comptage du mois au-dessus du seuil de l'annee
    (3 jusqu'en 2024, 2,8 en 2025, 2,4 depuis 2026, d'apres la terminologie du DFO).
  - Transferts = licences de transfert de smolts vers une ferme en mer : une autorisation,
    pas un nombre de poissons (le DFO ne publie pas les quantites).

    python3 scripts/build_canada.py
"""
import csv
import datetime as dt
import io
import json
import os
import re
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRUT = os.path.join(ROOT, 'farming', 'donnees_ca', 'brut')
OUT = os.path.join(ROOT, 'data', 'canada.json')
MOIS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                    'september', 'october', 'november', 'december'], 1)}
# anciens noms des memes entreprises
SOCIETE = {'Marine Harvest Canada': 'MOWI Canada West', 'Mainstream Canada': 'Cermaq Canada',
           'Cermaq British Columbia': 'Cermaq Canada'}


# comptages planifies (non declenches par un probleme) : base de la moyenne
PLANIFIES = {'routine monitoring', 'pre-migration', 'first pre-migration', 'first out-migration'}


def cause(c):
    c = (c or '').replace(' - explain', '').strip()
    return {'Unknow': 'Unknown', '': 'Not stated'}.get(c, c)


# Production d'aquaculture par province (DFO, d'apres Statistique Canada 32-10-0107), une page par annee.
DFO_PAGE = ['https://www.dfo-mpo.gc.ca/stats/aqua/aqua{yy:02d}-eng.html', 'https://www.dfo-mpo.gc.ca/stats/aqua/aqua{yy:02d}-eng.htm']
PROVS = ['NL', 'PE', 'NS', 'NB', 'QC', 'ON', 'MB', 'SK', 'AB', 'BC', 'Canada']
# 2024 verifie sur la page DFO (14/01/2026) : amorce si le site n'est pas joignable
DFO_2024 = {'Salmon': {'NS': 9396, 'NB': 24864, 'BC': 53816, 'Canada': 88076},
            'Total Finfish': {'NL': 23159, 'PE': 387, 'NS': 10060, 'NB': 24864, 'QC': 996, 'ON': 5647, 'BC': 54617, 'Canada': 122449}}


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables, self.row, self.cell, self.inside = [], None, None, 0
    def handle_starttag(self, tag, a):
        if tag == 'table': self.inside += 1; self.tables.append([])
        elif tag == 'tr' and self.inside: self.row = []
        elif tag in ('td', 'th') and self.row is not None: self.cell = ''
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None: self.row.append(self.cell.strip()); self.cell = None
        elif tag == 'tr' and self.row is not None: self.tables[-1].append(self.row); self.row = None
        elif tag == 'table': self.inside -= 1
    def handle_data(self, d):
        if self.cell is not None: self.cell += d


def lire_page_dfo(html):
    """Premier tableau (tonnes) : lignes Salmon et Total Finfish par province."""
    p = _Tables(); p.feed(html)
    for t in p.tables:
        ALIAS = {'PEI': 'PE', 'Que': 'QC', 'Que.': 'QC', 'Man': 'MB', 'Sask': 'SK', 'Alta': 'AB', 'Nfld': 'NL'}
        def code(c):
            c = c.strip()
            if c.startswith('Canada'): return 'Canada'             # « Canada » + renvoi de note colle
            c = ALIAS.get(c, c)                                    # 2015-2021 : en-tetes « PEI » et « Que » -> sans alias, les colonnes glissaient d'un cran
            return c if c in PROVS else ''
        tete = next((r for r in t if 'BC' in [code(c) for c in r]), None)
        if not tete: continue
        cols = [code(c) for c in tete]          # « Canada » suivi d'un renvoi de note -> « Canada »
        out = {}
        for r in t:
            brut = (r[0] if r else '').strip()
            lab = 'Salmon' if brut.startswith('Salmon') else 'Total Finfish' if brut.startswith('Total Finfish') else None
            if lab:
                # alignement par position dans l'en-tete (meme nombre de cellules), sinon a droite
                if len(r) == len(cols): pairs = [(pr, r[i]) for i, pr in enumerate(cols) if pr]
                else: off = len(r) - len(cols); pairs = [(pr, r[i + off]) for i, pr in enumerate(cols) if pr and 0 <= i + off < len(r)]
                out[lab] = {pr: int(v.replace(',', '')) for pr, v in pairs if re.fullmatch(r'[\d,]+', v.strip() or '-')}
        if out: return out
    return None


def production_provinces():
    """Cache farming/donnees_ca/dfo_production.json : { annee: { Salmon: {...}, Total Finfish: {...} } }."""
    cache = os.path.join(ROOT, 'farming', 'donnees_ca', 'dfo_production.json')
    data = json.load(io.open(cache, encoding='utf-8')) if os.path.exists(cache) else {}
    data.setdefault('2024', DFO_2024)
    if os.environ.get('CA_HORS_LIGNE') != '1':
        for an in range(2015, dt.date.today().year):
            if str(an) in data and an < dt.date.today().year - 2: continue      # les annees anciennes ne bougent plus
            for modele in DFO_PAGE:
                try:
                    html = urllib.request.urlopen(urllib.request.Request(modele.format(yy=an % 100), headers={'User-Agent': 'suivi-salmonicole/1.0'}), timeout=60).read().decode('utf-8', 'replace')
                    t = lire_page_dfo(html)
                    if t: data[str(an)] = t; break
                except Exception:  # noqa: BLE001
                    continue
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        io.open(cache, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def sites_bc(rows):
    """Une entree par ferme : position, exploitant, zone, premier et dernier mois de comptage, poux moyens sur 12 mois."""
    S = {}
    for r in rows:
        try:
            m = int(col(r, 'Year')) * 100 + MOIS[col(r, 'Month').lower()]
        except (ValueError, KeyError):
            continue
        fid = col(r, 'Facility Reference Number')
        x = S.setdefault(fid, {'id': fid, 'n': col(r, 'Site Common Name'), 'co': soc(col(r, 'Licence Holder')), 'amu': col(r, 'Aquaculture Management Unit'),
                               'lat': f(col(r, 'Latitude')), 'lon': f(col(r, 'Longitude')), 'first': m, 'last': m, 'yc': '', 'lice': []})
        if m >= x['last']:
            x['last'] = m; x['co'] = soc(col(r, 'Licence Holder')) or x['co']; x['yc'] = col(r, 'Year Class') or x['yc']
        x['first'] = min(x['first'], m)
        v = f(col(r, 'Average L. salmonis motiles per farmed fish'))
        if v is not None: x['lice'].append((m, v))
    out = []
    for x in S.values():
        if x['lat'] is None or x['lon'] is None: continue
        lim = x['last'] - 100
        l12 = [v for m, v in x['lice'] if m > lim]
        x['lice12'] = round(sum(l12) / len(l12), 2) if l12 else None
        del x['lice']
        out.append(x)
    return sorted(out, key=lambda x: -x['last'])


def seuil(an):
    return 3.0 if an <= 2024 else 2.8 if an == 2025 else 2.4


def lire(nom):
    p = os.path.join(BRUT, nom)
    if not os.path.exists(p):
        return []
    raw = open(p, 'rb').read()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.DictReader(io.StringIO(txt)))
    return [{(k or '').strip(): (v or '').strip() for k, v in r.items()} for r in rows]


def col(r, *noms):
    """Premiere colonne presente parmi plusieurs graphies (le DFO change parfois un intitule)."""
    for n in noms:
        for k in r:
            if k.lower().replace('  ', ' ') == n.lower():
                return r[k]
    return ''


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def soc(n):
    return SOCIETE.get(n, n)


def poux(rows):
    sites, yc, rout, allc, over = (defaultdict(set) for _ in range(5))
    par_soc, par_amu = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
    for r in rows:
        try:
            m = int(col(r, 'Year')) * 100 + MOIS[col(r, 'Month').lower()]
        except (ValueError, KeyError):
            continue
        site, v = col(r, 'Facility Reference Number'), f(col(r, 'Average L. salmonis motiles per farmed fish'))
        sites[m].add(site)
        if col(r, 'Year Class') in ('1', '2'):
            yc[(m, col(r, 'Year Class'))].add(site)
        if v is None:
            continue
        allc[m].add((site, v))
        if col(r, 'Sample Type').lower() in PLANIFIES:
            rout[m].add((site, v))
        if v > seuil(m // 100):
            over[m].add(site)
    def moy_sites(paires):
        par = defaultdict(list)
        for s, v in paires:
            par[s].append(v)
        vals = [sum(x) / len(x) for x in par.values()]
        return (round(sum(vals) / len(vals), 3) if vals else None), par
    out = []
    for m in sorted(sites):
        mr, par_r = moy_sites(rout[m])
        ma, _ = moy_sites(allc[m])
        out.append({'m': m, 'sites': len(sites[m]), 'y1': len(yc[(m, '1')]), 'y2': len(yc[(m, '2')]),
                    'lice': mr, 'lice_all': ma, 'over': len(over[m]), 'thr': seuil(m // 100)})
    # par entreprise et par zone, sur les comptages de routine
    for r in rows:
        try:
            m = int(col(r, 'Year')) * 100 + MOIS[col(r, 'Month').lower()]
        except (ValueError, KeyError):
            continue
        v = f(col(r, 'Average L. salmonis motiles per farmed fish'))
        site = col(r, 'Facility Reference Number')
        par_soc[soc(col(r, 'Licence Holder'))][m].append((site, v))
        par_amu[col(r, 'Aquaculture Management Unit')][m].append((site, v))
    def resume(groupes):
        res = {}
        for g, parm in groupes.items():
            res[g] = {str(m): [len({s for s, _ in l}), round(sum(v for _, v in l if v is not None) / max(1, sum(1 for _, v in l if v is not None)), 2)]
                      for m, l in parm.items()}
        return res
    return out, resume(par_soc), resume(par_amu)


def mortalites(rows):
    ev = []
    for r in rows:
        d = col(r, 'Incident Date')[:10]
        if len(d) < 10:
            continue
        ev.append({'d': d, 'co': soc(col(r, 'Licence Holder')), 'site': col(r, 'Site Common Name'),
                   'amu': col(r, 'Aquaculture Management Unit'), 'sp': col(r, 'Species').split(' (')[0],
                   'cause': cause(col(r, 'Probable Cause or Diagnosis')), 'action': col(r, 'Action Taken')})
    ev.sort(key=lambda e: e['d'])
    par_an = defaultdict(Counter)
    for e in ev:
        par_an[e['d'][:4]][e['cause']] += 1
    par_mois = Counter(int(e['d'][:4]) * 100 + int(e['d'][5:7]) for e in ev)
    return {'by_year': {a: dict(c) for a, c in sorted(par_an.items())}, 'by_month': {str(k): v for k, v in sorted(par_mois.items())},
            'recent': ev[-25:][::-1], 'last': ev[-1]['d'] if ev else None}


def transferts(rows):
    sm = [r for r in rows if col(r, 'Lifestage').lower().startswith('smolt')
          and 'marine' in col(r, 'Destination Facility Type').lower()]
    par_an = defaultdict(lambda: {'rows': 0, 'sites': set(), 'co': defaultdict(set)})
    for r in sm:
        a = col(r, 'Introductions and Transfers Licence Issuance Year')
        x = par_an[a]
        x['rows'] += 1
        dest = col(r, 'Destination Facility Reference Number')
        x['sites'].add(dest)
        x['co'][soc(col(r, 'Transfer Licence Holder'))].add(dest)
    annees = [{'y': a, 'pairs': x['rows'], 'sites': len(x['sites']), 'co': {c: len(s) for c, s in x['co'].items()}}
              for a, x in sorted(par_an.items()) if a]
    recent = sorted(sm, key=lambda r: col(r, 'Transfer Licence Start Date'))[-20:][::-1]
    return {'by_year': annees, 'recent': [{'start': col(r, 'Transfer Licence Start Date'), 'end': col(r, 'Transfer Licence End Date'),
                                          'co': soc(col(r, 'Transfer Licence Holder')), 'from': col(r, 'Source Facility Name'),
                                          'to': col(r, 'Destination Facility Name'),
                                          'amu': col(r, 'Destination Aquaculture Mangement Unit', 'Destination Aquaculture Management Unit')}
                                         for r in recent]}


def main():
    P, M, T = lire('poux.csv'), lire('mortalite.csv'), lire('transferts.csv')
    lice, by_co, by_amu = poux(P) if P else ([], {}, {})
    # dernier mois COMPLET : chaque entreprise presente le mois d'avant (2 fermes ou plus) a deja declare
    complet = None
    for r in reversed(lice):
        prec = r['m'] - 1 if r['m'] % 100 != 1 else r['m'] - 89
        manque = [c for c, mm in by_co.items() if mm.get(str(prec), [0])[0] >= 2 and mm.get(str(r['m']), [0])[0] == 0]
        if not manque:
            complet = r['m']
            break
    data = {'meta': {'built': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                     'lice_last': lice[-1]['m'] if lice else None, 'lice_complete': complet, 'rows': {'lice': len(P), 'events': len(M), 'transfers': len(T)},
                     'thresholds': {'2011-2024': 3.0, '2025': 2.8, '2026-': 2.4}},
            'lice': lice, 'lice_by_company': by_co, 'lice_by_area': by_amu,
            'events': mortalites(M) if M else None, 'transfers': transferts(T) if T else None,
            'sites': sites_bc(P) if P else [], 'provinces': production_provinces(),
            'provinces_extra': [{'prov': 'NL', 'year': 2025, 'what': 'Salmonids (Atlantic salmon 30,567 t + steelhead 3,648 t)', 't': 34215,
                                 'src': 'Government of Newfoundland and Labrador, 2025 Seafood Industry Year in Review'}]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f"data/canada.json : poux {len(P)} lignes (dernier mois {data['meta']['lice_last']}), "
          f"{len(M)} evenements de mortalite, {len(T)} lignes de transferts")


if __name__ == '__main__':
    main()
