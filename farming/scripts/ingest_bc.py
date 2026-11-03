#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_bc.py : charge les CSV DFO Pacifique (poux, événements de mortalité,
transferts) et sort un CSV mensuel pour l'onglet BC_Mensuel.

NON TESTÉ sur les vrais fichiers : les en-têtes DFO n'ont pas pu être lus
depuis l'environnement de travail. D'où deux temps.

1) python ingest_bc.py inspect <fichier_ou_url>
   Affiche les colonnes et 3 lignes. Renseigner ensuite COLS ci-dessous.
2) python ingest_bc.py build --poux <csv> [--mortalite <csv>] [--transferts <csv>] -o bc_mensuel.csv
   ou python ingest_bc.py build --catalogue      (adresses lues dans le catalogue, ne refait rien si inchangé)
   python ingest_bc.py catalogue                 (dit seulement ce qui a changé côté DFO)
   python ingest_bc.py telecharger               (télécharge les 3 CSV du DFO s'ils ont changé -> donnees_ca/brut/,
                                                  que scripts/build_canada.py transforme en data/canada.json)

Poux : moyenne par mois des moyennes par ferme, pondérée par le nombre de
poissons comptés si la colonne existe, sinon moyenne simple (signalé en sortie).
Mortalité et transferts : somme (transferts) ou nombre de lignes (événements) par mois.
"""
import argparse, csv, io, sys, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime

COLS = {
    'poux':       {'date': None, 'ferme': None, 'moyenne': None, 'poissons_comptes': None},
    'mortalite':  {'date': None},
    'transferts': {'date': None, 'nb_poissons': None},
}
# Catalogue open.canada.ca (CKAN) : l'API donne l'adresse du CSV et sa date de modification,
# ce qui évite de coder les adresses en dur et de retélécharger un fichier inchangé.
CKAN = 'https://open.canada.ca/data/api/action/package_show?id='
JEUX = {   # identifiant du jeu sur open.canada.ca ; None = à trouver
    'poux':       '3cafbe89-c98b-4b44-88f1-594e8d28838d',   # Industry sea lice counts
    'mortalite':  '7fbb2662-391a-4df7-99b4-3343fa68fc93',   # Mortality events
    'transferts': None,                                     # Finfish transfers : identifiant non trouvé
}
ETAT = 'etat_catalogue_bc.json'

def _nom(r):
    n = r.get('name') or ''
    if isinstance(n, dict): n = n.get('en') or ' '.join(n.values())
    t = r.get('name_translated') or {}
    return f"{n} {t.get('en', '') if isinstance(t, dict) else ''}"

MOTIFS = {'poux': 'lice-count', 'mortalite': 'mort-ev', 'transferts': 'transfers-transfert'}   # noms des fichiers du DFO

def _api(action, **params):
    import json
    url = CKAN.replace('package_show?id=', action + '?') + urllib.parse.urlencode(params)
    rep = json.loads(urllib.request.urlopen(url, timeout=60).read().decode('utf-8'))
    if not rep.get('success'): raise RuntimeError(f'catalogue : échec {action} {params}')
    return rep['result']

def _csv_anglais(resources, motif=None):
    """Le CSV de DONNÉES en anglais : fichier « ...-rpt-...-eng.csv » (« -def- » = terminologie)."""
    def ok(r):
        u = (r.get('url') or '').lower()
        if motif: return motif in u and '-rpt-' in u and u.endswith('eng.csv')
        return 'data' in _nom(r).lower() and ('english' in _nom(r).lower() or 'en' in (r.get('language') or [])) \
            and (r.get('format') or '').upper() == 'CSV'
    return [r for r in resources if ok(r)]

def ressource(package_id, motif=None):
    """-> (url du CSV de données en anglais, date de dernière modification)"""
    res = _api('package_show', id=package_id)['resources']
    cand = _csv_anglais(res, motif) or _csv_anglais(res)
    if not cand: raise RuntimeError(f'catalogue : aucun CSV de données anglais dans {package_id}')
    r = cand[0]
    return r['url'], (r.get('last_modified') or r.get('metadata_modified') or '')

def trouver_jeu(motif):
    """Identifiant d'un jeu dont on connaît le nom de fichier mais pas l'identifiant."""
    for q in (motif, 'Introductions Transfers British Columbia aquaculture', 'finfish transfers British Columbia aquaculture'):
        for pkg in _api('package_search', q=q, rows=20).get('results', []):
            if _csv_anglais(pkg.get('resources', []), motif): return pkg['id']
    return None

def telecharger():
    """Télécharge les CSV de données du DFO dans donnees_ca/brut/ quand le catalogue dit qu'ils ont changé."""
    import json, os
    etat = json.load(open(ETAT)) if os.path.exists(ETAT) else {}
    os.makedirs(os.path.join('donnees_ca', 'brut'), exist_ok=True)
    echecs = []
    for jeu, motif in MOTIFS.items():
        try:
            pid = JEUX.get(jeu) or trouver_jeu(motif)
            if not pid: raise RuntimeError('jeu introuvable dans le catalogue')
            url, modif = ressource(pid, motif)
            dest = os.path.join('donnees_ca', 'brut', f'{jeu}.csv')
            if etat.get(jeu) == modif and os.path.exists(dest):
                print(f'{jeu:11} : inchangé (modifié {modif})'); continue
            data = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'suivi-salmonicole/1.0'}), timeout=180).read()
            if len(data) < 1000 or b',' not in data[:500]: raise RuntimeError(f'fichier suspect ({len(data)} octets)')
            open(dest, 'wb').write(data)
            etat[jeu] = modif
            print(f'{jeu:11} : TÉLÉCHARGÉ ({len(data) // 1024} ko, modifié {modif})')
        except Exception as e:                                    # noqa: BLE001
            echecs.append(jeu); print(f'{jeu:11} : ERREUR {e}')
    json.dump(etat, open(ETAT, 'w'), indent=1)
    if echecs: raise SystemExit(f'échec pour : {", ".join(echecs)}')

def catalogue():
    """Affiche, pour chaque jeu, l'adresse du CSV et s'il a changé depuis le dernier passage."""
    import json, os
    etat = json.load(open(ETAT)) if os.path.exists(ETAT) else {}
    changes = {}
    for jeu, pid in JEUX.items():
        if not pid:
            print(f'{jeu:11} : identifiant inconnu, à renseigner dans JEUX'); continue
        url, modif = ressource(pid, MOTIFS.get(jeu))
        change = etat.get(jeu) != modif
        changes[jeu] = (url, change)
        print(f'{jeu:11} : {"CHANGÉ" if change else "inchangé"} (modifié {modif or "?"})  {url}')
        etat[jeu] = modif
    json.dump(etat, open(ETAT, 'w'), indent=1)
    return changes

DATE_FORMATS = ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y-%m', '%Y/%m/%d', '%d-%b-%y', '%b-%y')

def ouvrir(src):
    if src.startswith('http'):
        raw = urllib.request.urlopen(src, timeout=120).read()
    else:
        raw = open(src, 'rb').read()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue

def lire(src):
    return list(csv.DictReader(io.StringIO(ouvrir(src))))

def mois(txt):
    t = (txt or '').strip()
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(t, fmt)
            return f'{d.year:04d}-{d.month:02d}'
        except ValueError:
            continue
    return None

def nombre(v):
    try:
        return float(str(v).replace(',', '.').replace(' ', ''))
    except (ValueError, TypeError):
        return None

def exiger(bloc, *cles):
    manque = [k for k in cles if not COLS[bloc].get(k)]
    if manque:
        sys.exit(f'COLS["{bloc}"] incomplet : {manque}. Lancer d\'abord « inspect ».')

def inspect(src):
    rows = lire(src)
    print(f'{len(rows)} lignes · colonnes :')
    for c in rows[0]:
        print('  -', c)
    for r in rows[:3]:
        print(dict(list(r.items())[:8]))

def poux(src):
    exiger('poux', 'date', 'moyenne')
    c = COLS['poux']
    num = defaultdict(float); den = defaultdict(float); n = defaultdict(int); fermes = defaultdict(set)
    ponderee = bool(c.get('poissons_comptes'))
    for r in lire(src):
        m = mois(r.get(c['date']))
        x = nombre(r.get(c['moyenne']))
        if not m or x is None:
            continue
        w = nombre(r.get(c['poissons_comptes'])) if ponderee else 1.0
        w = w if w and w > 0 else 1.0
        num[m] += x * w; den[m] += w; n[m] += 1
        if c.get('ferme'):
            fermes[m].add(r.get(c['ferme']))
    if not ponderee:
        print('Poux : pas de colonne de poissons comptés, moyenne simple.', file=sys.stderr)
    return {m: {'poux_moy': num[m] / den[m], 'comptages': n[m], 'fermes_actives': len(fermes[m]) or ''} for m in num}

def mortalite(src):
    exiger('mortalite', 'date')
    out = defaultdict(int)
    for r in lire(src):
        m = mois(r.get(COLS['mortalite']['date']))
        if m:
            out[m] += 1
    return {m: {'evenements_mortalite': v} for m, v in out.items()}

def transferts(src):
    exiger('transferts', 'date', 'nb_poissons')
    out = defaultdict(float)
    for r in lire(src):
        m = mois(r.get(COLS['transferts']['date']))
        x = nombre(r.get(COLS['transferts']['nb_poissons']))
        if m and x:
            out[m] += x
    return {m: {'transferts_poissons': v} for m, v in out.items()}

def build(a):
    if getattr(a, 'catalogue', False):
        ch = catalogue()
        if not getattr(a, 'force', False) and not any(c for _, c in ch.values()):
            print('aucun jeu modifié depuis le dernier passage : rien à faire'); return
        a.poux = a.poux or (ch.get('poux') or (None,))[0]
        a.mortalite = a.mortalite or (ch.get('mortalite') or (None,))[0]
    res = defaultdict(dict)
    for src, fn in ((a.poux, poux), (a.mortalite, mortalite), (a.transferts, transferts)):
        if src:
            for m, d in fn(src).items():
                res[m].update(d)
    champs = ['mois', 'poux_moy', 'fermes_actives', 'comptages', 'transferts_poissons', 'evenements_mortalite']
    with open(a.sortie, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=champs)
        w.writeheader()
        for m in sorted(res):
            if '2023-01' <= m <= '2026-10':
                w.writerow({'mois': m, **res[m]})
    print(f'{a.sortie} : {sum(1 for m in res if "2023-01" <= m <= "2026-10")} mois')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest='cmd', required=True)
    i = sp.add_parser('inspect'); i.add_argument('src')
    b = sp.add_parser('build')
    b.add_argument('--poux'); b.add_argument('--mortalite'); b.add_argument('--transferts')
    b.add_argument('-o', '--sortie', default='bc_mensuel.csv')
    b.add_argument('--catalogue', action='store_true', help='adresses et dates lues dans le catalogue open.canada.ca')
    b.add_argument('--force', action='store_true', help='reconstruire même si rien n\'a changé')
    sp.add_parser('catalogue')
    sp.add_parser('telecharger')
    a = p.parse_args()
    if a.cmd == 'inspect': inspect(a.src)
    elif a.cmd == 'catalogue': catalogue()
    elif a.cmd == 'telecharger': telecharger()
    else: build(a)
