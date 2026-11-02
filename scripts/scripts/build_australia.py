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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'farming', 'donnees_au')
OUT = os.path.join(ROOT, 'data', 'australia.json')
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


def main():
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
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f'data/australia.json : {len(mort)} mois de mortalites (dernier {last}), {len(prod)} valeurs de production')


if __name__ == '__main__':
    main()
