#!/usr/bin/env python3
"""
Sonde ponctuelle de l'API BarentsWatch (Fish Health).

But : verifier que les identifiants fonctionnent et enregistrer des
echantillons de reponse reels, pour ecrire ensuite le script d'agregation
par zone de production sur les vrais noms de champs (la documentation
publique ne les detaille pas).

Identifiants lus dans les variables d'environnement (secrets GitHub) :
    BW_CLIENT_ID, BW_CLIENT_SECRET
Rien n'est jamais ecrit ni affiche a partir de ces valeurs.

Sortie : data/bw_probe/  (summary.json + un fichier brut par appel, tronque)
Les donnees BarentsWatch sont sous licence NLOD : les publier dans le depot
public est autorise.

Usage : python3 scripts/probe_barentswatch.py
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'bw_probe')
TOKEN_URL = 'https://id.barentswatch.no/connect/token'
API = 'https://www.barentswatch.no/bwapi'
MAX_SAVE = 60_000          # octets gardes par reponse brute
UA = 'saumon-dashboard probe (github.com/emileviardotfo/saumon)'


def get_token():
    cid = os.environ.get('BW_CLIENT_ID', '').strip()
    sec = os.environ.get('BW_CLIENT_SECRET', '').strip()
    if not cid or not sec:
        sys.exit('BW_CLIENT_ID ou BW_CLIENT_SECRET absent : verifier les secrets du depot.')
    body = urllib.parse.urlencode({
        'client_id': cid, 'client_secret': sec,
        'scope': 'api', 'grant_type': 'client_credentials',
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={
        'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        # Le corps d'erreur OAuth ne contient pas le secret : on peut l'afficher.
        sys.exit(f'Echec du jeton ({e.code}) : {e.read()[:300]!r}\n'
                 '-> identifiant ou secret incorrect, ou espace en trop dans un secret.')
    except urllib.error.URLError as e:
        sys.exit(f'Serveur BarentsWatch injoignable : {e.reason}')
    print(f"Jeton obtenu : type={tok.get('token_type')}, expire dans {tok.get('expires_in')} s")
    return tok['access_token']


def call(token, method, path, params=None, body=None):
    url = API + path + ('?' + urllib.parse.urlencode(params) if params else '')
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Authorization': f'Bearer {token}', 'User-Agent': UA,
               'Accept': 'application/json, text/csv, */*'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.headers.get('Content-Type', ''), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type', ''), e.read()
    except Exception as e:  # reseau, timeout
        return None, '', repr(e).encode()


def keys_tree(obj, depth=0, maxdepth=4):
    """Structure (noms de champs et types) d'un objet JSON, sans les valeurs."""
    if depth >= maxdepth:
        return type(obj).__name__
    if isinstance(obj, dict):
        return {k: keys_tree(v, depth + 1, maxdepth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [keys_tree(obj[0], depth + 1, maxdepth), f'len={len(obj)}'] if obj else []
    return type(obj).__name__


def main():
    os.makedirs(OUT, exist_ok=True)
    token = get_token()

    # Derniere semaine ISO complete, moins une : les rapports de poux sont
    # deposes en debut de semaine suivante.
    ref = dt.date.today() - dt.timedelta(days=14)
    year, week, _ = ref.isocalendar()
    ref4 = ref - dt.timedelta(days=21)
    y4, w4, _ = ref4.isocalendar()
    print(f'Semaine de reference : {year}-S{week:02d}')

    summary = {'run_utc': dt.datetime.utcnow().isoformat(timespec='seconds'),
               'ref_year': year, 'ref_week': week, 'calls': []}

    def probe(name, method, path, params=None, body=None, fname=None):
        st, ctype, raw = call(token, method, path, params, body)
        entry = {'name': name, 'method': method, 'path': path, 'params': params,
                 'body': body, 'status': st, 'content_type': ctype, 'bytes': len(raw)}
        parsed = None
        if st == 200 and 'json' in ctype:
            try:
                parsed = json.loads(raw)
                entry['structure'] = keys_tree(parsed)
                if isinstance(parsed, list):
                    entry['n_items'] = len(parsed)
            except ValueError:
                pass
        if st == 200 and ('csv' in ctype or 'text' in ctype or 'octet' in ctype):
            head = raw[:4000].decode('utf-8', 'replace').splitlines()
            entry['first_lines'] = head[:6]
            entry['n_lines'] = raw.count(b'\n')
        if fname:
            with open(os.path.join(OUT, fname), 'wb') as f:
                f.write(raw[:MAX_SAVE])
            entry['saved_as'] = fname
        if st != 200:
            entry['error_excerpt'] = raw[:500].decode('utf-8', 'replace')
        summary['calls'].append(entry)
        print(f"  {name:<34} -> {st} {ctype[:40]} {len(raw):>9} o")
        return st, parsed, raw

    # 1. Liste hebdomadaire de tous les sites (v2, POST avec filtres)
    st, sites, _ = probe('locality_week_list', 'POST',
                         f'/v2/geodata/fishhealth/locality/{year}/{week}', body={},
                         fname='locality_week_list.json')

    # 2. Statistiques nationales de la semaine
    probe('national_week', 'POST', f'/v2/geodata/fishhealth/{year}/{week}', body={},
          fname='national_week.json')

    # 3. Detail d'un site (contient productionArea et seaTemperature)
    loc_no = None
    if isinstance(sites, list):
        for s in sites:
            loc = s.get('locality') if isinstance(s, dict) else None
            cand = (loc or {}).get('no') or (loc or {}).get('localityNo') or s.get('localityNo')
            rep = s.get('liceReport') or {}
            if cand and rep.get('hasReported'):
                loc_no = cand
                break
        if loc_no is None and sites:
            s = sites[0]
            loc_no = (s.get('locality') or {}).get('no') or s.get('localityNo')
    if loc_no:
        probe('locality_detail', 'GET', f'/v2/geodata/fishhealth/locality/{loc_no}/{year}/{week}',
              fname='locality_detail.json')
        probe('locality_disease_year', 'GET', f'/v3/geodata/fishhealth/locality/{loc_no}/disease/{year}',
              fname='locality_disease_year.json')
    else:
        print('  (aucun numero de site trouve dans la liste : detail non teste)')

    # 4. Detail des traitements contre les poux : la liste hebdomadaire ne dit
    #    que "medicamenteux / non medicamenteux". Le type (thermique, mecanique,
    #    eau douce, bain, aliment...) est dans la fiche du site. On lit quelques
    #    sites traites cette semaine, et une semaine de 2023 ou les traitements
    #    medicamenteux etaient encore signales dans la liste.
    def treated(lst, label=None, n=4):
        out = []
        for x in (lst or []):
            t = x.get('liceTreatments') or []
            if t and (label is None or label in t):
                out.append((x.get('locality') or {}).get('no'))
            if len(out) >= n:
                break
        return [o for o in out if o]
    for no in treated(sites, 'IKKE_MEDIKAMENTELL', 4):
        probe(f'treat_nonmed_{no}', 'GET', f'/v2/geodata/fishhealth/locality/{no}/{year}/{week}',
              fname=f'treat_nonmed_{no}.json')
    st23, sites23, _ = probe('locality_week_list_2023w40', 'POST', '/v2/geodata/fishhealth/locality/2023/40', body={})
    med = treated(sites23, 'MEDIKAMENTELL', 3)
    for no in med:
        probe(f'treat_med_{no}', 'GET', f'/v2/geodata/fishhealth/locality/{no}/2023/40',
              fname=f'treat_med_{no}.json')
    if med:
        probe('lice_medication_events', 'GET',
              f'/v1/geodata/fishhealth/locality/{med[0]}/liceMedicationEvents/2023',
              fname='lice_medication_events.json')

    # 5. Specification OpenAPI : donne la liste exacte des types de traitement.
    global MAX_SAVE
    MAX_SAVE = 3_000_000
    for i, path in enumerate(['/openapi/v1/openapi.json', '/openapi/v2/openapi.json',
                              '/swagger/v1/swagger.json', '/openapi/openapi.json'], 1):
        st, _, _ = probe(f'openapi_spec_{i}', 'GET', path, fname=f'openapi_spec_{i}.json')
        if st == 200:
            break

    with open(os.path.join(OUT, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=1, ensure_ascii=False, default=str)
    ok = sum(1 for c in summary['calls'] if c['status'] == 200)
    print(f'\n{ok}/{len(summary["calls"])} appels reussis. Resume : data/bw_probe/summary.json')


if __name__ == '__main__':
    main()
