#!/usr/bin/env python3
"""
Construit data/australia.json pour l'onglet Australia du tableau de bord, a partir
des fichiers tenus a jour par farming/scripts/maj_australie.py :

    farming/donnees_au/au_mensuel.csv      mortalites mensuelles EPA Tasmanie, par methode
    farming/donnees_au/au_entreprises.csv  production par entreprise et exercice (portail NRE)
    farming/donnees_au/au_journal.csv      journal des passages (revisions, erreurs)

Seules les valeurs lues a la source (EPA, NRE) sont publiees : rien d'estime.

    python3 scripts/build_australia.py
"""
import calendar
import csv
import datetime as dt
import io
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'farming', 'donnees_au')
OUT = os.path.join(ROOT, 'data', 'australia.json')
UA = {'User-Agent': 'suivi-salmonicole/1.0'}
# Baux marins (polygones) : LIST Tasmanie, couche publique « LIST Marine Leases »
LIST_URL = ('https://services.thelist.tas.gov.au/arcgis/rest/services/Public/OpenDataWFS/MapServer/31/query'
            '?where=1%3D1&outFields=M_LEASE_NO,MEAS_AREA&returnGeometry=true&outSR=4326&f=geojson')
PORTAIL = 'https://salmonfarming.nre.tas.gov.au/'
# Titulaires des baux du D'Entrecasteaux Channel et de la Huon River (NRE, RTI 045 2025-26, publie)
RTI_045 = {'34': 'South East Aquaculture Pty Ltd', '73': 'Tassal Operations Pty Ltd', '76': 'Aquatas Pty Ltd',
           '77': 'Tassal Operations Pty Ltd', '78': 'Tassal Operations Pty Ltd', '87': 'Huon Aquaculture Company Pty Ltd',
           '90': 'Aquatas Pty Ltd', '93': 'Huon Aquaculture Company Pty Ltd', '94': 'Aquatas Pty Ltd', '109': 'Aquatas Pty Ltd',
           '110': 'Tassal Operations Pty Ltd', '115': 'Tassal Operations Pty Ltd', '141': 'Huon Aquaculture Company Pty Ltd',
           '142': 'Tassal Operations Pty Ltd', '151': 'Huon Aquaculture Company Pty Ltd', '154': 'Aquatas Pty Ltd',
           '167': 'Huon Aquaculture Company Pty Ltd', '182': 'Aquatas Pty Ltd', '185': 'Aquatas Pty Ltd',
           '186': 'Tassal Operations Pty Ltd', '187': 'Tassal Operations Pty Ltd', '188': 'Tassal Operations Pty Ltd',
           '189': 'Tassal Operations Pty Ltd', '201': 'Tassal Operations Pty Ltd', '203': 'Tassal Operations Pty Ltd',
           '209': 'Tassal Operations Pty Ltd', '221': 'Huon Aquaculture Company Pty Ltd', '244': 'Huon Aquaculture Company Pty Ltd'}
ZONES = {'dentrecasteaux-channel-and-huon-river': "D'Entrecasteaux Channel & Huon River", 'macquarie-harbour': 'Macquarie Harbour',
         'tamar-estuary': 'Tamar Estuary'}
# titulaire -> exploitant (Aquatas est une filiale de Tassal ; Van Diemen Aquaculture = Petuna, groupe Sealord)
GROUPE = {'Tassal Operations Pty Ltd': 'Tassal', 'Aquatas Pty Ltd': 'Tassal', 'Huon Aquaculture Company Pty Ltd': 'Huon',
          'Van Diemen Aquaculture Pty Ltd': 'Petuna', 'Tassal': 'Tassal', 'Huon': 'Huon', 'Petuna': 'Petuna'}
EPA_URL = 'https://epa.tas.gov.au/business-industry/regulation/salmon-aquaculture/salmon-waste-management'
NRE_URL = 'https://salmonfarming.nre.tas.gov.au/'


def lire(nom):
    p = os.path.join(SRC, nom)
    if not os.path.exists(p):
        return []
    with io.open(p, encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


def n(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def attendu(dernier):
    """Publication EPA attendue : fin du trimestre suivant le dernier mois lu + 21 jours."""
    an, m = int(dernier[:4]), int(dernier[5:7])
    q_end = ((m - 1) // 3 + 1) * 3
    cible = q_end + 3 if m == q_end else q_end
    an2, m2 = (an, cible) if cible <= 12 else (an + 1, cible - 12)
    return (dt.date(an2, m2, calendar.monthrange(an2, m2)[1]) + dt.timedelta(days=21)).isoformat()


def http(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode('utf-8', 'replace')


def texte(html):
    html = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', html)
    t = re.sub(r'<[^>]+>', ' ', html)
    t = re.sub('[\u200b-\u200f\u2060\ufeff\xa0]', ' ', t)
    return re.sub(r'\s+', ' ', t)


def ecrire_csv(nom, champs, lignes):
    with io.open(os.path.join(SRC, nom), 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=champs); w.writeheader(); w.writerows(lignes)


def portail():
    """Pages par zone du portail NRE : exploitant de chaque bail (tableau de suivi benthique) et indicateurs
    trimestriels de sante par entreprise (evenement de mortalite significatif ; mortalite > 0,25 %/jour 3 jours
    de suite dans une cage). Le portail n'affiche que le trimestre en cours : chaque passage l'archive."""
    accueil = http(PORTAIL)
    slugs = sorted(set(re.findall(r'href="(?:https://salmonfarming\.nre\.tas\.gov\.au)?/([a-z0-9][a-z0-9-]{4,})/?"', accueil)))
    slugs = [x for x in slugs if x not in ('the-environment', 'contact', 'about', 'privacy', 'disclaimer', 'copyright')]
    baux, signaux = [], []
    for slug in slugs:
        try:
            t = texte(http(PORTAIL + slug))
        except Exception as e:  # noqa: BLE001
            print('portail', slug, ':', e); continue
        if 'Marine Farm Lease' not in t and 'Benthic' not in t:
            continue
        zone = ZONES.get(slug, slug.replace('-', ' ').title())
        for co, lease in re.findall(r'\b(Tassal|Huon|Petuna)\s+(\d{1,3})\s+\d+\s+\d+', t):
            baux.append({'bail': lease, 'exploitant': co, 'zone': zone, 'source': 'portail NRE (suivi benthique)'})
        for lab, cle in (('Significant mortality event reported', 'significant_event'), ('Mortality within a cage', 'cage_025')):
            m = re.search(re.escape(lab) + r'.{0,1500}?Quarter (\d), (\d{4})\s+((?:(?:Huon|Tassal|Petuna)\s*[YN]\s*)+)', t)
            if m:
                for co, v in re.findall(r'(Huon|Tassal|Petuna)\s*([YN])', m.group(3)):
                    signaux.append({'trimestre': f'{m.group(2)}-T{m.group(1)}', 'zone': zone, 'indicateur': cle, 'exploitant': co, 'valeur': v})
    return baux, signaux


def centroides():
    gj = json.loads(http(LIST_URL))
    out = []
    for f in gj.get('features', []):
        n = str((f.get('properties') or {}).get('M_LEASE_NO') or '').strip()
        g = f.get('geometry') or {}
        pts = []
        def cumul(c):
            if c and isinstance(c[0], (int, float)): pts.append(c)
            else:
                for x in c: cumul(x)
        cumul(g.get('coordinates') or [])
        if n and pts:
            out.append({'bail': n, 'lon': round(sum(p[0] for p in pts) / len(pts), 5), 'lat': round(sum(p[1] for p in pts) / len(pts), 5),
                        'ha': round(((f.get('properties') or {}).get('MEAS_AREA') or 0) / 10000, 1)})
    return out


def baux_et_signaux():
    """Met a jour les caches farming/donnees_au/au_baux.csv, au_exploitants.csv, au_signaux.csv ; ne casse jamais."""
    try:
        geo = centroides()
        if geo: ecrire_csv('au_baux.csv', ['bail', 'lat', 'lon', 'ha'], geo)
    except Exception as e:  # noqa: BLE001
        print('LIST (baux) :', e)
    exp = {r['bail']: r for r in lire('au_exploitants.csv')}
    for b, h in RTI_045.items():
        exp.setdefault(b, {'bail': b, 'exploitant': GROUPE.get(h, h), 'titulaire': h, 'zone': "D'Entrecasteaux Channel & Huon River", 'source': 'NRE RTI 045 2025-26'})
    try:
        bx, sg = portail()
        for r in bx:
            old = exp.get(r['bail'], {})
            exp[r['bail']] = {'bail': r['bail'], 'exploitant': r['exploitant'], 'titulaire': old.get('titulaire', ''), 'zone': r['zone'], 'source': r['source']}
        ancien = lire('au_signaux.csv')
        cles = {(r['trimestre'], r['zone'], r['indicateur'], r['exploitant']) for r in ancien}
        ecrire_csv('au_signaux.csv', ['trimestre', 'zone', 'indicateur', 'exploitant', 'valeur'],
                   ancien + [r for r in sg if (r['trimestre'], r['zone'], r['indicateur'], r['exploitant']) not in cles])
    except Exception as e:  # noqa: BLE001
        print('portail NRE :', e)
    ecrire_csv('au_exploitants.csv', ['bail', 'exploitant', 'titulaire', 'zone', 'source'],
               sorted(exp.values(), key=lambda r: int(r['bail']) if r['bail'].isdigit() else 9999))


def main():
    if os.environ.get('AU_HORS_LIGNE') != '1':
        os.makedirs(SRC, exist_ok=True); baux_et_signaux()
    geo = {r['bail']: r for r in lire('au_baux.csv')}
    leases = [{'n': r['bail'], 'co': r['exploitant'], 'holder': r.get('titulaire', ''), 'zone': r['zone'], 'src': r['source'],
               'lat': n(geo[r['bail']]['lat']), 'lon': n(geo[r['bail']]['lon']), 'ha': n(geo[r['bail']]['ha'])}
              for r in lire('au_exploitants.csv') if r['bail'] in geo]
    signals = lire('au_signaux.csv')
    mens = sorted(lire('au_mensuel.csv'), key=lambda r: r['mois'])
    mort = [{'m': int(r['mois'][:4]) * 100 + int(r['mois'][5:7]), 'total': n(r['total']),
             'rendering': n(r.get('rendering')), 'compost': n(r.get('compost')), 'landfill': n(r.get('decharge')),
             'ensiling': n(r.get('ensilage')), 'burial': n(r.get('enfouissement')),
             'note': r.get('note') or '', 'read': r.get('releve') or ''} for r in mens if r.get('mois')]
    prod = [{'company': r['entreprise'], 'fy': r['exercice'], 'fy_end': int(r['fin_exercice']), 't': n(r['tonnes'])}
            for r in lire('au_entreprises.csv') if r.get('entreprise')]
    jour = lire('au_journal.csv')
    alerts = []
    if jour:
        last_day = max((r.get('horodatage') or '')[:10] for r in jour)
        alerts = [f"{r.get('source')}: {r.get('detail')}" for r in jour
                  if (r.get('horodatage') or '')[:10] == last_day and r.get('statut') in ('RÉVISION', 'ERREUR')]
    last = mens[-1]['mois'] if mens else None
    data = {
        'meta': {'built': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                 'last_month': last, 'next_expected': attendu(last) if last else None,
                 'last_fy': max((p['fy'] for p in prod), default=None),
                 'sources': {'mortality': EPA_URL, 'production': NRE_URL}, 'alerts': alerts[:10]},
        'mortality': mort,
        'production': sorted(prod, key=lambda p: (p['fy_end'], p['company'])),
        'leases': leases, 'signals': signals,
        # mortalites publiees par entreprise : seulement des points isoles (demandes d'acces aux documents)
        'company_points': [{'co': 'Huon', 'm': 202502, 't': 3084.14, 'src': 'EPA Tasmania, RTI 013 2025-26 (all Huon leases, February 2025)'}],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f'data/australia.json : {len(mort)} mois de mortalites (dernier {last}), {len(prod)} valeurs de production, '
          f'{len(leases)} baux cartographies, {len(signals)} indicateurs trimestriels archives')


if __name__ == '__main__':
    main()
