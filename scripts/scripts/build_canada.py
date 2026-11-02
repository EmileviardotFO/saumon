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
from collections import Counter, defaultdict

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
            'events': mortalites(M) if M else None, 'transfers': transferts(T) if T else None}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f"data/canada.json : poux {len(P)} lignes (dernier mois {data['meta']['lice_last']}), "
          f"{len(M)} evenements de mortalite, {len(T)} lignes de transferts")


if __name__ == '__main__':
    main()
