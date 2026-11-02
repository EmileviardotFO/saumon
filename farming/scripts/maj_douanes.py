#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maj_douanes.py : interroge les API des douanes et statistiques nationales, stocke les séries
saumon en CSV, détecte les révisions, et dit pour chaque source quel est le DERNIER MOIS
RÉELLEMENT DISPONIBLE dans l'API (pas la date du calendrier : c'est le piège de l'Islande).

Sources branchées (voir douanes_config.json)
  census   États-Unis, API du Census : importations par pays d'origine et code SH à 10 chiffres.
           Clé facultative (variable d'environnement CENSUS_KEY) au-delà de 500 requêtes/jour.
  pxweb    Toute base PxWeb (Norvège SSB, Islande Hagstofa, Féroé Hagstova) : le script lit
           les métadonnées de la table, donc connaît la dernière période publiée sans rien
           télécharger d'autre ; les données sont tirées seulement si une sélection est configurée.
Non automatisables ici (voir la clé "manuel" du fichier de configuration)
  Chine (pas d'API publique connue), Chili (API de la Banque centrale sur inscription).

Usage
  python maj_douanes.py                       # toutes les sources actives
  python maj_douanes.py --source census_us
  python maj_douanes.py --decouvrir ssb_mois  # affiche variables et codes d'une table PxWeb
  python maj_douanes.py --fraicheur           # seulement le dernier mois disponible par source

Sorties : donnees_douanes/<source>.csv, journal.csv, fraicheur.csv

Limite : écrit d'après la documentation des API, sans accès réseau à ces sites pendant le
développement. Les chemins de tables PxWeb marqués « a_confirmer » se vérifient avec --decouvrir.
"""
import argparse, calendar, csv, datetime as dt, json, os, sys, time, urllib.parse, urllib.request

UA = {'User-Agent': 'suivi-salmonicole/1.0'}
CONFIG = 'douanes_config.json'


# ----------------------------------------------------------------------------- réseau
def http(url, data=None, essais=3):
    for k in range(essais):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                         headers={**UA, **({'Content-Type': 'application/json'} if data else {})})
            rep = urllib.request.urlopen(req, timeout=90)
            return rep.read().decode('utf-8-sig') if rep.status != 204 else ''
        except urllib.error.HTTPError as e:
            if e.code in (400, 404): raise RuntimeError(f'{e.code} sur {url} : {e.read()[:300]!r}')
            err = e
        except Exception as e:                                      # noqa: BLE001
            err = e
        time.sleep(5 * (k + 1))
    raise RuntimeError(f'injoignable : {url} ({err})')


# ----------------------------------------------------------------------------- périodes
def periode_iso(p):
    """'2026M09', '2026-09', '2026M09D' ... -> '2026-09' ; semaines '2026U36' -> '2026-W36'."""
    p = str(p).strip()
    if len(p) >= 7 and p[4] in 'M-' and p[5:7].isdigit(): return f'{p[:4]}-{p[5:7]}'
    if len(p) >= 7 and p[4] in 'UW' and p[5:7].isdigit(): return f'{p[:4]}-W{p[5:7]}'
    return p

def attendu(derniere, delai_jours, frequence='mois'):
    """Date à laquelle la période suivante devrait être publiée."""
    if not derniere: return None
    if len(derniere) == 4 and derniere.isdigit():                       # table annuelle
        return dt.date(int(derniere) + 1, 12, 31) + dt.timedelta(days=delai_jours)
    if frequence == 'semaine':
        an, sem = int(derniere[:4]), int(derniere[-2:])
        fin = dt.date.fromisocalendar(an, sem, 7) + dt.timedelta(days=7)
        return fin + dt.timedelta(days=delai_jours)
    an, m = int(derniere[:4]), int(derniere[5:7])
    an, m = (an + 1, 1) if m == 12 else (an, m + 1)
    return dt.date(an, m, calendar.monthrange(an, m)[1]) + dt.timedelta(days=delai_jours)

def statut(derniere, cfg, aujourdhui):
    a = attendu(derniere, cfg.get('delai_jours', 40), cfg.get('frequence', 'mois'))
    if not derniere: return 'inconnu', a
    if len(derniere) == 4 and derniere.isdigit(): return 'TABLE ANNUELLE : choisir la table mensuelle', a
    if a and aujourdhui > a + dt.timedelta(days=cfg.get('tolerance_jours', 7)):
        return 'EN RETARD', a
    return ('période suivante attendue maintenant' if a and aujourdhui >= a else 'à jour'), a


# ----------------------------------------------------------------------------- Census
CENSUS = 'https://api.census.gov/data/timeseries/intltrade/{flux}/hs'

def census_tableau(texte):
    """Réponse JSON du Census (liste de listes, 1re ligne = en-têtes) -> liste de dicts.
    Corps vide = HTTP 204, aucune donnée pour cette requête."""
    if not texte.strip(): return []
    try:
        t = json.loads(texte)
    except ValueError:
        raise RuntimeError(f'réponse non JSON du Census : {texte[:200]!r}')
    out = []
    for r in t[1:]:
        d = {}
        for k, v in zip(t[0], r):          # le Census répète les colonnes de filtre en fin de ligne :
            d.setdefault(k, v)             # on garde la première occurrence (le vrai code, pas « 030214* »)
        out.append(d)
    return out

def census_url(flux, params):
    if os.environ.get('CENSUS_KEY'): params['key'] = os.environ['CENSUS_KEY']
    return CENSUS.format(flux=flux) + '?' + urllib.parse.urlencode(params, safe='*,:', quote_via=urllib.parse.quote)

def mois_entre(debut, fin):
    a, m = int(debut[:4]), int(debut[5:7]); out = []
    while (a, m) <= (int(fin[:4]), int(fin[5:7])):
        out.append(f'{a}-{m:02d}'); a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out

def census(cfg, mois):
    """Une requête par mois et par code : simple, et c'est la syntaxe la mieux documentée."""
    flux = cfg.get('flux', 'imports')
    pref = 'I' if flux == 'imports' else 'E'
    val, qte = (('GEN_VAL_MO', 'GEN_QY1_MO') if flux == 'imports' else ('ALL_VAL_MO', 'QTY_1_MO'))
    lignes = []
    for per in mois:
        for code in cfg['codes_sh']:
            params = {'get': f'CTY_CODE,CTY_NAME,{pref}_COMMODITY,{val},{qte},UNIT_QY1',
                      'time': per, 'COMM_LVL': 'HS10', f'{pref}_COMMODITY': f'{code}*'}
            for r in census_tableau(http(census_url(flux, params))):
                if r.get('CTY_CODE', '').startswith(('-', '0')): continue   # total et regroupements (UE, OCDE...)
                lignes.append({'periode': per, 'partenaire': r['CTY_NAME'], 'code_partenaire': r['CTY_CODE'],
                               'produit': r[f'{pref}_COMMODITY'], 'valeur': r.get(val) or '', 'quantite': r.get(qte) or '',
                               'unite_quantite': r.get('UNIT_QY1', ''), 'unite_valeur': 'USD'})
    return lignes

def census_derniere(cfg):
    """Dernier mois publié : on sonde les mois en reculant depuis le mois dernier (au plus 8)."""
    flux = cfg.get('flux', 'imports'); pref = 'I' if flux == 'imports' else 'E'
    d = dt.date.today().replace(day=1)
    for _ in range(8):
        d = (d - dt.timedelta(days=1)).replace(day=1)
        per = f'{d.year}-{d.month:02d}'
        params = {'get': 'GEN_VAL_MO' if flux == 'imports' else 'ALL_VAL_MO', 'time': per,
                  'COMM_LVL': 'HS2', f'{pref}_COMMODITY': '03'}
        if census_tableau(http(census_url(flux, params))): return per
    return None


# ----------------------------------------------------------------------------- PxWeb
def pxweb_meta(url):
    return json.loads(http(url))

def pxweb_temps(meta):
    for v in meta['variables']:
        if v.get('time') or v['code'].lower() in ('tid', 'time', 'mánuður', 'manudur', 'ár', 'month'):
            return v
    return meta['variables'][-1]

def pxweb_derniere(cfg):
    v = pxweb_temps(pxweb_meta(cfg['url']))
    return max(periode_iso(x) for x in v['values'])

def jsonstat2_lignes(js):
    """Aplatit une réponse json-stat2 en lignes {dimension: libellé, ..., valeur}."""
    ids, tailles, dims = js['id'], js['size'], js['dimension']
    codes = []
    for d in ids:
        idx = dims[d]['category']['index']
        ordre = sorted(idx, key=idx.get) if isinstance(idx, dict) else list(idx)
        codes.append(ordre)
    vals = js['value']
    if isinstance(vals, dict): vals = [vals.get(str(i)) for i in range(int(__import__('math').prod(tailles)))]
    out = []
    for i, v in enumerate(vals):
        r, reste = {}, i
        for k in range(len(ids) - 1, -1, -1):
            j = reste % tailles[k]; reste //= tailles[k]
            r[ids[k]] = codes[k][j]
        r['valeur'] = v
        out.append(r)
    return out

def pxweb(cfg, debut, fin):
    meta = pxweb_meta(cfg['url'])
    tv = pxweb_temps(meta)
    periodes = [p for p in tv['values'] if debut <= periode_iso(p)[:7] <= fin]
    q = [{'code': c, 'selection': s} for c, s in cfg['selection'].items()]
    q.append({'code': tv['code'], 'selection': {'filter': 'item', 'values': periodes}})
    js = json.loads(http(cfg['url'], data={'query': q, 'response': {'format': 'json-stat2'}}))
    lignes = []
    for r in jsonstat2_lignes(js):
        if r['valeur'] is None: continue
        r['periode'] = periode_iso(r.pop(tv['code']))
        lignes.append(r)
    return lignes

def decouvrir(cfg):
    meta = pxweb_meta(cfg['url'])
    print(meta.get('title', ''))
    for v in meta['variables']:
        vals = v['values']; txt = v.get('valueTexts', vals)
        print(f"\n[{v['code']}] {v['text']} : {len(vals)} valeurs" + (' (temps)' if v.get('time') else ''))
        for c, t in list(zip(vals, txt))[:15]: print(f'   {c:14} {t}')
        if len(vals) > 15: print(f'   ... dernière : {vals[-1]} {txt[-1]}')


# ----------------------------------------------------------------------------- stockage
def cle(r): return tuple((k, str(v)) for k, v in sorted(r.items()) if k not in ('valeur', 'quantite', 'releve'))

def fusionner(chemin, nouvelles, releve):
    """Écrit le CSV de la source ; renvoie (nouvelles périodes, révisions)."""
    anciennes = {}
    if os.path.exists(chemin):
        with open(chemin, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh): anciennes[cle(r)] = r
    per_avant = {r['periode'] for r in anciennes.values()}
    revisions = []
    for r in nouvelles:
        k = cle(r); r['releve'] = releve
        if k in anciennes:
            for champ in ('valeur', 'quantite'):
                a, n = str(anciennes[k].get(champ, '')), str(r.get(champ, ''))
                if a and n and a != n:
                    revisions.append(f"{r['periode']} {dict(k).get('partenaire', '')} {dict(k).get('produit', '')} {champ}: {a} -> {n}")
        anciennes[k] = {**anciennes.get(k, {}), **r}
    champs = sorted({c for r in anciennes.values() for c in r})
    with open(chemin, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=champs); w.writeheader()
        w.writerows(sorted(anciennes.values(), key=lambda r: (r.get('periode', ''), str(r))))
    nouvelles_per = sorted({r['periode'] for r in nouvelles} - per_avant)
    return nouvelles_per, revisions

def journal(dossier, source, statut_, detail):
    p = os.path.join(dossier, 'journal.csv'); neuf = not os.path.exists(p)
    with open(p, 'a', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        if neuf: w.writerow(['horodatage', 'source', 'statut', 'detail'])
        w.writerow([dt.datetime.now().isoformat(timespec='seconds'), source, statut_, detail])
    print(f'[{statut_}] {source} : {detail}')


# ----------------------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default=CONFIG)
    ap.add_argument('--sortie', default='donnees_douanes')
    ap.add_argument('--source', action='append')
    ap.add_argument('--decouvrir')
    ap.add_argument('--fraicheur', action='store_true')
    ap.add_argument('--depuis', default='2023-01')
    ap.add_argument('--strict', action='store_true')
    a = ap.parse_args()
    conf = json.load(open(a.config, encoding='utf-8'))
    sources = {k: v for k, v in conf['sources'].items() if not k.startswith('_')}
    if a.decouvrir:
        decouvrir(sources[a.decouvrir]); return
    os.makedirs(a.sortie, exist_ok=True)
    auj = dt.date.today(); releve = auj.isoformat(); fin = f'{auj.year}-12'
    alertes, fraich = [], []
    for nom, cfg in sources.items():
        if a.source and nom not in a.source: continue
        if not cfg.get('actif', True): continue
        try:
            derniere = census_derniere(cfg) if cfg['type'] == 'census' else pxweb_derniere(cfg)
            st, att = statut(derniere, cfg, auj)
            fraich.append({'source': nom, 'libelle': cfg.get('libelle', ''), 'derniere_periode_disponible': derniere,
                           'publication_suivante_attendue': att, 'statut': st, 'verifie_le': releve})
            journal(a.sortie, nom, st, f'dernière période réellement disponible : {derniere}')
            if st == 'EN RETARD': alertes.append(f'{nom} en retard (attendu {att})')
            if a.fraicheur: continue
            if cfg['type'] == 'pxweb' and not cfg.get('selection'):
                journal(a.sortie, nom, 'sélection à configurer', 'lancer --decouvrir pour choisir les codes'); continue
            if cfg['type'] == 'census':
                deja = set()
                p = os.path.join(a.sortie, f'{nom}.csv')
                if os.path.exists(p):
                    with open(p, encoding='utf-8-sig', newline='') as fh: deja = {r['periode'] for r in csv.DictReader(fh)}
                tous = mois_entre(a.depuis, derniere) if derniere else []
                a_tirer = [m for m in tous if m not in deja] + [m for m in tous[-3:] if m in deja]
                lignes = census(cfg, sorted(set(a_tirer)))
            else:
                if len(derniere or '') == 4:
                    journal(a.sortie, nom, 'ignorée', 'table annuelle : remplacer l\'adresse par la table mensuelle'); continue
                lignes = pxweb(cfg, a.depuis, fin)
            for r in lignes: r['source'] = nom
            nouv, rev = fusionner(os.path.join(a.sortie, f'{nom}.csv'), lignes, releve)
            journal(a.sortie, nom, 'données', f'{len(lignes)} lignes ; nouvelles périodes : {", ".join(nouv) or "aucune"}')
            for x in rev: journal(a.sortie, nom, 'RÉVISION', x)
            if rev: alertes.append(f'{nom} : {len(rev)} révision(s)')
        except Exception as e:                                       # noqa: BLE001
            journal(a.sortie, nom, 'ERREUR', str(e)[:400]); alertes.append(f'{nom} : {e}')
    with open(os.path.join(a.sortie, 'fraicheur.csv'), 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['source', 'libelle', 'derniere_periode_disponible', 'publication_suivante_attendue', 'statut', 'verifie_le'])
        w.writeheader(); w.writerows(fraich)
    for m in conf.get('manuel', []): print(f"[manuel] {m['source']} : {m['note']}")
    if alertes: print('\nALERTES :'); [print(' -', x) for x in alertes]
    sys.exit(1 if alertes and a.strict else 0)


if __name__ == '__main__':
    main()
