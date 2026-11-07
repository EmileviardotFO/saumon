#!/usr/bin/env python3
"""
data/scotland_extra.json : signaux biologiques ecossais en temps reel, d'apres Scotland's Aquaculture
(Marine Directorate, Fish Health Inspectorate) — mis a jour au fil de l'eau, contrairement aux rapports SEPA
(environ 10 mois de retard) :
  - restrictions de mouvements de poissons imposees pour maladie (avis de l'inspection sanitaire) :
    date, site, eleveur, zone de gestion, maladie, statut actif ou leve ;
  - evasions de poissons declarees : date, eleveur, site, nombre, poids, cause ;
  - nombre de sites marins de salmonides ayant produit ces 3 dernieres annees, par eleveur.
Sources (exports CSV publics) : https://aquaculture.scotland.gov.uk/Data
"""
import csv, io, json, os, sys, time, datetime as dt
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'scotland_extra.json')
B = 'https://aquaculture.scotland.gov.uk/csv/'
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}


def get(f):
    r = requests.get(B + f, headers=H, timeout=300); r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig', 'replace'))))


def d(s):
    try: return dt.datetime.strptime(s.strip(), '%d-%b-%Y').date().isoformat()
    except Exception: return None


def num(s):
    try: return int(float(str(s).replace(',', '').strip()))
    except Exception: return None


def op(s):
    s = (s or '').strip()
    for k, v in [('Mowi', 'Mowi Scotland'), ('Marine Harvest', 'Mowi Scotland'), ('Scottish Sea Farms', 'Scottish Sea Farms'), ('Bakkafrost', 'Bakkafrost Scotland'),
                 ('Scottish Salmon Company', 'Bakkafrost Scotland'), ('Cooke', 'Cooke Scotland'), ('Meridian', 'Cooke Scotland'), ('Loch Duart', 'Loch Duart'),
                 ('Grieg', 'Grieg Shetland (now SSF)'), ('Organic Sea Harvest', 'Organic Sea Harvest'), ('Kames', 'Kames'), ('Wester Ross', 'Wester Ross'), ('Dawnfresh', 'Dawnfresh (trout)')]:
        if k.lower() in s.lower(): return v
    return s


def main():
    out, since = {}, '2020-01-01'
    try:
        mr = get('ms_movement_restrictions.csv')
        rows = []
        for r in mr:
            if 'salmon' not in (r.get('Species') or '').lower() or not (r.get('Water Type') or '').lower().startswith('sea'):
                continue
            f = d(r['Date into Force'])
            act = (r.get('Movement Restriction Status') or '').strip().lower() == 'active'
            if not f or (f < since and not act):
                continue
            rows.append({'date': f, 'type': r['Notice Type'].strip(), 'disease': r['Disease Agent'].strip(), 'site': r['Site Name'].strip(), 'site_id': r['Marine Scotland Site ID'],
                         'operator': op(r['Operator']), 'area': r.get('MS Management Area', '').strip(), 'region': r.get('Region', '').strip(),
                         'active': act, 'lifted': d(r.get('Withdrawal Date Into Force', '')), 'e': num(r.get('Easting')), 'n': num(r.get('Northing'))})
        rows.sort(key=lambda x: x['date'], reverse=True)
        out['restrictions'] = rows
        print(f'restrictions : {len(rows)} (actives {sum(r["active"] for r in rows)})')
    except Exception as e:  # noqa: BLE001
        print('restrictions : ERREUR', e)
    try:
        es = get('ms_fish_escapes.csv')
        rows = []
        for r in es:
            f = d(r.get('Escape Start Date', '')) or d(r.get('Initial Date of Escape', ''))
            if not f or f < since or 'salmon' not in (r.get('Escaped Species') or '').lower():
                continue
            rows.append({'date': f, 'operator': op(r['Operator at Time of Escape']), 'site': r['Site Name'].strip(), 'water': r['Escape Water Type'].strip(),
                         'stage': r['Stage'].strip(), 'weight': r['Average Weight'].strip(), 'number': num(r['Final Number Escaped']) or num(r['Initial Number Escaped']),
                         'reason': (r['Final Escape Reason'] or r['Initial Escape Reason']).strip(), 'area': r.get('MS Management Area', '').strip()})
        rows.sort(key=lambda x: x['date'], reverse=True)
        out['escapes'] = rows
        print(f'evasions : {len(rows)}')
    except Exception as e:  # noqa: BLE001
        print('evasions : ERREUR', e)
    try:
        sd = get('ms_site_details.csv')
        c = {}
        for r in sd:
            if r['Aquaculture Type'] != 'Fish' or not r['Water Type'].lower().startswith('sea') or 'salmon' not in r['Species'].lower():
                continue
            o = op(r['Operator']); k = c.setdefault(o, {'sites': 0, 'producing': 0})
            k['sites'] += 1; k['producing'] += r['Producing in Last 3 Years'] == 'Yes'
        out['sites_by_operator'] = dict(sorted(c.items(), key=lambda kv: -kv[1]['producing']))
        print('sites :', sum(v['producing'] for v in c.values()), 'en production')
    except Exception as e:  # noqa: BLE001
        print('sites : ERREUR', e)
    if not out:
        print('rien lu : fichier inchange'); sys.exit(0)
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    old.update(out)
    old['meta'] = {'built': time.strftime('%Y-%m-%d'), 'source': "Scotland's Aquaculture (Marine Directorate Fish Health Inspectorate): movement restrictions, fish escapes, site register",
                   'url': 'https://aquaculture.scotland.gov.uk/Data', 'since': since}
    json.dump(old, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('ecrit', OUT, os.path.getsize(OUT) // 1024, 'ko')


if __name__ == '__main__':
    main()
