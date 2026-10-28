#!/usr/bin/env python3
"""
Registre des sites d'elevage, depuis la fiche de chaque site sur BarentsWatch
(GET /v2/geodata/fishhealth/locality/{site}/{annee}/{semaine}).

Ecrit :
  data/bw_sites.json   une fiche compacte par site (identite, zone, GPS,
                       capacite, licences avec titulaire et capacite,
                       entreprises exploitantes, cage d'attente d'abattage)
  data/data.json       cle 'bw_register' : les agregats lus par le tableau
                       de bord (MTB par groupe et par zone, cages d'attente,
                       entreprise de chaque site)

Rythme : la fiche change peu (licences, exploitants). Le script ne relit tout
que si le registre a plus de REFRESH_DAYS jours ; un passage interrompu
reprend ou il s'etait arrete. Environ 1 800 appels, 10 a 15 minutes.

MTB (biomasse maximale autorisee) : somme des capacites de licence, chaque
licence comptee UNE fois (une licence est rattachee a plusieurs sites).
Licences retenues : commerciales, poisson destine a la consommation
("Matfisk"), avec du saumon parmi les especes. La zone d'une licence est la
zone majoritaire des sites auxquels elle est rattachee.

Identifiants : BW_CLIENT_ID, BW_CLIENT_SECRET (secrets GitHub).
Usage : python3 scripts/update_bw_sites.py [--force] [--max-calls N]
"""
import argparse
import collections
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_barentswatch import Api  # meme authentification, memes reprises

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
SITES = os.path.join(ROOT, 'data', 'bw_sites.json')
REFRESH_DAYS = 28

# Rattachement des societes titulaires a leur groupe. Recherche d'un motif
# dans le nom du titulaire (majuscules). A completer au besoin : une societe
# non reconnue reste sous son propre nom.
GROUPS = [
    ('MOWI', 'Mowi'), ('SALMAR', 'SalMar'), ('LERØY', 'Lerøy'), ('SJØTROLL', 'Lerøy'),
    ('GRIEG', 'Grieg Seafood'), ('CERMAQ', 'Cermaq'), ('MÅSØVAL', 'Måsøval'),
    ('NOVA SEA', 'Nova Sea'), ('NORDLAKS', 'Nordlaks'), ('ALSAKER', 'Alsaker'),
    ('BREMNES', 'Bremnes Seashore'), ('EIDE FJORDBRUK', 'Eide Fjordbruk'),
    ('KVARØY', 'Kvarøy'), ('LINGALAKS', 'Lingalaks'), ('SINKABERG', 'Sinkaberg-Hansen'),
    ('MIDT-NORSK HAVBRUK', 'Midt-Norsk Havbruk'), ('BJØRØYA', 'Bjørøya'),
    ('ERKO', 'Erko Seafood'), ('KOBBEVIK', 'Kobbevik og Furuholmen'),
    ('WENBERG', 'Wenberg'), ('ENGESUND', 'Engesund'), ('HOFSETH', 'Hofseth'),
    ('FROSTMANN', 'Frøy / Frostmann'), ('ROYAL SALMON', 'SalMar'),
    ('ARNØY', 'SalMar'), ('ICELANDIC', 'SalMar'), ('SØRSMOLEN', 'Sørsmolen'),
    ('LUMARINE', 'Lumarine'), ('SELSØYVIK', 'Selsøyvik'), ('STEINVIKFISK', 'Steinvik'),
    ('TRONDSEN', 'Trondsen'), ('BÅTSFJORD', 'Båtsfjord'), ('GÅSØ', 'Gåsø'),
    ('OSMUNDSEN', 'Osmundsen'), ('SMØLA', 'Smøla Klekkeri'),
]


def group_of(holder):
    h = (holder or '').upper()
    for pat, g in GROUPS:
        if pat in h:
            return g
    return (holder or '?').title()


def compact(det, week_key):
    loc = det.get('locality') or {}
    geo = (det.get('geometry') or {}).get('coordinates') or [None, None]
    reg = det.get('aquaCultureRegister') or {}
    lic = []
    for l in reg.get('licenses') or []:
        lic.append({
            'no': l.get('licenseNo'), 'holder': l.get('licensee'),
            'cap': l.get('capacity'), 'unit': l.get('unit'),
            'species': l.get('species') or [], 'purpose': l.get('purpose'),
            'ptype': l.get('productionType'), 'green': l.get('isGreen'),
            'sites': [x.get('localityNo') for x in (l.get('localities') or [])],
        })
    orgs = [{'name': o.get('name'), 'orgno': o.get('organizationNo'), 'city': o.get('city')}
            for o in reg.get('organizations') or []]
    pa = det.get('productionArea') or {}
    return {
        'no': loc.get('no'), 'name': loc.get('name'), 'onLand': loc.get('isOnLand'),
        'po': pa.get('id'), 'lon': geo[0], 'lat': geo[1],
        'mun': (det.get('municipality') or {}).get('name'),
        'placement': reg.get('placement'), 'cap': reg.get('capacity'), 'unit': reg.get('unit'),
        'slaughter': bool(reg.get('isSlaughterHoldingCage') or det.get('isSlaughterHoldingCage')),
        'salmonoid': reg.get('hasSalmonoidLicense'),
        'ptypes': reg.get('productionTypes') or [], 'purposes': reg.get('purposes') or [],
        'lic': lic, 'org': orgs, 'read_week': week_key,
    }


def build_register(sites):
    """Agregats pour le tableau de bord."""
    po_of_site = {s['no']: s.get('po') for s in sites.values() if s.get('no')}
    licences = {}
    for s in sites.values():
        for l in s.get('lic') or []:
            if l.get('no') and l['no'] not in licences:
                licences[l['no']] = l
    # Licences de production de saumon pour la consommation : commerciales et
    # de developpement, toutes variantes "Matfisk" (5 % MTB, vertes A/B/C,
    # converties) et bio. Hors champ : recherche, vitrine, enseignement, cages
    # d'attente (Slaktemerd), smolt et geniteurs.
    keep = lambda l: (l.get('purpose') in ('Kommersiell', 'Utvikling')
                      and (l.get('ptype') or '').startswith(('Matfisk', 'Økologisk'))
                      and any('Laks' in x for x in l.get('species') or [])
                      and (l.get('unit') in (None, 'TN')) and isinstance(l.get('cap'), (int, float)))
    # Les licences a terre (fermes terrestres) ne relevent pas du meme regime
    # que la mer : elles sont mises a part, sinon elles gonflent la MTB des
    # zones (environ 400 000 t autorisees, tres peu produites).
    site_of = {s['no']: s for s in sites.values() if s.get('no')}
    on_land = lambda l: bool(l.get('sites')) and all(
        (site_of.get(x) or {}).get('placement') == 'LAND' or (site_of.get(x) or {}).get('onLand')
        for x in l['sites'] if x in site_of) and any(x in site_of for x in l['sites'])
    by_group = collections.defaultdict(lambda: {'total': 0.0, 'n': 0, 'po': collections.Counter(), 'holders': set()})
    by_po = collections.Counter()
    # MTB par titulaire de licence (la societe juridique), avec son groupe
    by_holder = collections.defaultdict(lambda: {'total': 0.0, 'n': 0, 'po': collections.Counter()})
    land = collections.defaultdict(lambda: {'total': 0.0, 'n': 0, 'po': 0, 'sites': set()})
    n_sea = 0
    for no, l in licences.items():
        if not keep(l):
            continue
        pos = [po_of_site.get(x) for x in l.get('sites') or [] if po_of_site.get(x)]
        po = collections.Counter(pos).most_common(1)[0][0] if pos else 0
        if on_land(l):
            L = land[l.get('holder') or '?']
            L['total'] += l['cap']; L['n'] += 1; L['po'] = L['po'] or po
            L['sites'].update((site_of.get(x) or {}).get('name') or str(x) for x in l['sites'] if x in site_of)
            continue
        n_sea += 1
        g = group_of(l.get('holder'))
        G = by_group[g]
        G['total'] += l['cap']; G['n'] += 1; G['po'][po] += l['cap']; G['holders'].add(l.get('holder'))
        by_po[po] += l['cap']
        H = by_holder[l.get('holder') or '?']
        H['total'] += l['cap']; H['n'] += 1; H['po'][po] += l['cap']
    # Capacite en mer de TOUTES les licences de grossissement de saumon, y compris
    # recherche, vitrine, enseignement et cages d'attente : leurs poissons sont
    # comptes dans la biomasse du Biomasseregisteret, donc c'est le bon
    # denominateur pour le taux d'utilisation par zone.
    sea_all = lambda l: ((l.get('ptype') or '').startswith(('Matfisk', 'Økologisk'))
                         and any('Laks' in x for x in l.get('species') or [])
                         and (l.get('unit') in (None, 'TN')) and isinstance(l.get('cap'), (int, float))
                         and not on_land(l))
    by_po_all = collections.Counter()
    for no, l in licences.items():
        if sea_all(l):
            pos = [po_of_site.get(x) for x in l.get('sites') or [] if po_of_site.get(x)]
            by_po_all[collections.Counter(pos).most_common(1)[0][0] if pos else 0] += l['cap']
    land_rows = sorted(({'holder': h, 'group': group_of(h), 'mtb': round(v['total']), 'licences': v['n'],
                         'po': v['po'], 'sites': sorted(v['sites'])} for h, v in land.items()),
                       key=lambda x: -x['mtb'])
    groups = sorted(({'group': g, 'mtb': round(v['total']), 'licences': v['n'],
                      'po': {str(k): round(c) for k, c in v['po'].items()},
                      'holders': sorted(h for h in v['holders'] if h)}
                     for g, v in by_group.items()), key=lambda x: -x['mtb'])
    holders = sorted(({'holder': h, 'group': group_of(h), 'mtb': round(v['total']), 'licences': v['n'],
                       'po': {str(k): round(c) for k, c in v['po'].items()}}
                      for h, v in by_holder.items()), key=lambda x: -x['mtb'])
    site_org = {}
    for s in sites.values():
        names = [o['name'] for o in s.get('org') or [] if o.get('name')]
        if not names:
            names = [l.get('holder') for l in s.get('lic') or [] if l.get('holder')]
        if names:
            site_org[str(s['no'])] = group_of(names[0]) if group_of(names[0]) != names[0].title() else names[0]
    cages = [{'no': s['no'], 'name': s['name'], 'po': s.get('po'), 'mun': s.get('mun'),
              'org': site_org.get(str(s['no'])), 'cap': s.get('cap'), 'lat': s.get('lat'), 'lon': s.get('lon')}
             for s in sites.values() if s.get('slaughter')]
    cages.sort(key=lambda c: (-(c['po'] or 0), c['name'] or ''))
    return {
        'meta': {'generated': dt.date.today().isoformat(), 'sites': len(sites),
                 'licences_total': len(licences),
                 'licences_kept': n_sea, 'licences_land': sum(v['n'] for v in land.values()),
                 'rule': 'sea-based food-fish licences for salmon (commercial and development, including '
                         'the 5% increases, green and converted licences), each licence counted once; '
                         'zone = majority zone of the sites it is attached to; land-based farms shown apart'},
        'mtb_po': {str(k): round(v) for k, v in sorted(by_po.items())},
        'mtb_po_all': {str(k): round(v) for k, v in sorted(by_po_all.items())},
        'mtb_groups': groups,
        'mtb_holders': holders,
        'mtb_land': land_rows,
        'site_org': site_org,
        'site_name': {str(s['no']): s.get('name') or '' for s in sites.values() if s.get('no')},
        'site_po': {str(s['no']): s.get('po') for s in sites.values() if s.get('no') and s.get('po')
                    and s.get('placement') != 'LAND' and not s.get('slaughter')},
        # capacite autorisee du site (lokalitets-MTB, tonnes) : taille du site
        'site_cap': {str(s['no']): round(s['cap']) for s in sites.values() if s.get('no') and s.get('po')
                     and s.get('placement') != 'LAND' and not s.get('slaughter')
                     and isinstance(s.get('cap'), (int, float)) and s.get('unit') in (None, 'TN')},
        'slaughter_cages': cages,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--max-calls', type=int, default=2500)
    args = ap.parse_args()

    store = json.load(io.open(SITES, encoding='utf-8')) if os.path.exists(SITES) else {'meta': {}, 'sites': {}}
    meta = store['meta']
    started = meta.get('cycle_started')
    fresh = started and (dt.date.today() - dt.date.fromisoformat(started)).days < REFRESH_DAYS
    if fresh and meta.get('cycle_complete') and not args.force:
        print(f"Registre a jour (cycle du {started}), rien a faire.")
    else:
        if not fresh or meta.get('cycle_complete') or args.force:
            meta['cycle_started'] = dt.date.today().isoformat()
            meta['cycle_complete'] = False
            meta['done'] = []
        api = Api()
        y, w, _ = (dt.date.today() - dt.timedelta(days=7)).isocalendar()
        week_key = f'{y}-{w:02d}'
        lst = api.call('POST', f'/v2/geodata/fishhealth/locality/{y}/{w}', body={}) or []
        todo = [str((s.get('locality') or {}).get('no')) for s in lst
                if (s.get('locality') or {}).get('no') and (s.get('hasSalmonoidLicense') or s.get('isSlaughterHoldingCage'))]
        done = set(meta.get('done') or [])
        todo = [n for n in todo if n not in done]
        print(f'{len(lst)} sites dans la liste {week_key}, {len(todo)} fiches a lire '
              f'(cycle du {meta["cycle_started"]}, {len(done)} deja lues).')
        n = 0
        for no in todo[:args.max_calls]:
            try:
                det = api.call('GET', f'/v2/geodata/fishhealth/locality/{no}/{y}/{w}')
            except RuntimeError as e:
                print('  ', no, e); continue
            if det:
                store['sites'][no] = compact(det, week_key)
            done.add(no); n += 1
            if n % 200 == 0:
                meta['done'] = sorted(done)
                io.open(SITES, 'w', encoding='utf-8').write(json.dumps(store, ensure_ascii=False, separators=(',', ':')))
                print(f'  ... {n} fiches lues')
        meta['done'] = sorted(done)
        meta['cycle_complete'] = len(todo) <= args.max_calls
        meta['updated'] = dt.date.today().isoformat()
        io.open(SITES, 'w', encoding='utf-8').write(json.dumps(store, ensure_ascii=False, separators=(',', ':')))
        print(f'{n} fiches lues ; cycle complet : {meta["cycle_complete"]}')

    reg = build_register(store['sites'])
    data = json.load(io.open(DATA, encoding='utf-8'))
    data['bw_register'] = reg
    io.open(DATA, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    m = reg['meta']
    print(f"Registre : {m['sites']} sites, {m['licences_kept']}/{m['licences_total']} licences retenues, "
          f"MTB totale {sum(reg['mtb_po'].values()):,.0f} t, {len(reg['slaughter_cages'])} cages d'attente.")
    for g in reg['mtb_groups'][:10]:
        print(f"  {g['group']:<28} {g['mtb']:>9,} t  ({g['licences']} licences)")


if __name__ == '__main__':
    main()
