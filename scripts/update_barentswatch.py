#!/usr/bin/env python3
"""
Sante des poissons par zone de production et par semaine, depuis l'API
BarentsWatch (Fish Health). Ajoute la cle 'bw_weekly' a data/data.json.

Source : un appel par semaine a
    POST /v2/geodata/fishhealth/locality/{annee}/{semaine}
qui renvoie tous les sites (environ 1 800) avec poux, temperature de la mer,
maladies et traitements. La zone de production n'y figure pas : elle est lue
une fois par site dans
    GET  /v2/geodata/fishhealth/locality/{site}/{annee}/{semaine}
puis gardee dans data/bw_localities.json (un site ne change pas de zone).

Perimetre : sites en mer, avec licence salmonides, hors cages d'attente
d'abattage. Un site est "actif" s'il a declare ses poux et n'est pas en
jachere cette semaine-la.

Par zone et par semaine (champs courts pour limiter la taille du JSON) :
  y, w, po     annee ISO, semaine ISO, zone de production (1-13)
  na           sites actifs (declares, hors jachere)
  nf           sites en jachere
  lice         moyenne simple des femelles adultes par poisson, sites actifs
               (meme convention que BarentsWatch : chaque site pese pareil)
  nl           sites actifs avec une valeur de poux
  ov           sites au-dessus de la limite legale de la semaine
  lim          limite appliquee (0,5 ; 0,2 au printemps, voir LIMIT)
  t            temperature moyenne de la mer (degres C), sites actifs
  nt           sites avec une temperature
  dis          {nom de maladie: nombre de sites concernes}
  trt          {type de traitement: nombre de sites traites}

Identifiants : variables d'environnement BW_CLIENT_ID et BW_CLIENT_SECRET
(secrets GitHub). Jamais ecrits ni affiches.

Usage :
    python3 scripts/update_barentswatch.py            # mise a jour normale
    python3 scripts/update_barentswatch.py --max-weeks 40
Premier passage : remonte jusqu'a START (2018-S01), par tranches de
--max-weeks semaines par execution pour rester dans des durees raisonnables.
Ensuite : les 4 dernieres semaines sont toujours re-telechargees (declarations
tardives), plus les semaines manquantes.
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
LOC_CACHE = os.path.join(ROOT, 'data', 'bw_localities.json')
# Maladies site par site et semaine par semaine (sites malades seulement), pour
# reperer les NOUVEAUX cas. Fichier a part : le tableau de bord ne le charge pas.
DIS_FILE = os.path.join(ROOT, 'data', 'bw_disease_sites.json')
DIS_SHORT = {'PANKREASSYKDOM': 'PD', 'INFEKSIOES_LAKSEANEMI': 'ILA',
             'BAKTERIELL_NYRESYKE': 'BKD',
             'SYSTEMISK_INFEKSJON_MED_FLAVOBACTERIUM_PSYCHROPHILUM': 'FLAVO',
             'FRANCISELLOSE': 'FRANC'}
# Detail des traitements contre les poux : un appel par site ET par annee
# (GET /v1/geodata/fishhealth/locality/{site}/liceMedicationEvents/{annee}),
# qui donne toutes les semaines traitees de l'annee avec le type de traitement
# non medicamenteux et la substance des traitements medicamenteux.
TRT_FILE = os.path.join(ROOT, 'data', 'bw_treatments.json')
TRT_FROM_YEAR = 2024          # historique detaille a partir de cette annee
TRT_BUDGET = 2800             # appels au plus par execution (annee en cours ~1 100 + rattrapage)
TRT_FROM = (TRT_FROM_YEAR, 1)
NEW_CASE_GAP = 4      # une maladie est un "nouveau cas" si absente du site les 4 semaines d'avant
TOKEN_URL = 'https://id.barentswatch.no/connect/token'
API = 'https://www.barentswatch.no/bwapi'
UA = 'saumon-dashboard (github.com/emileviardotfo/saumon)'
KEY = 'bw_weekly'
START = (2018, 1)
REFRESH_WEEKS = 4
PAUSE = 0.15          # secondes entre deux appels : BarentsWatch demande un seul fil


def LIMIT(po, week):
    """Limite legale de femelles adultes par poisson (approximation par zone).
    0,2 en semaines 16-21 au sud du Nordland (zones 1-7), en semaines 21-26
    du Nordland au Finnmark (zones 8-13) ; 0,5 le reste de l'annee."""
    if po <= 7 and 16 <= week <= 21:
        return 0.2
    if po >= 8 and 21 <= week <= 26:
        return 0.2
    return 0.5


class Api:
    def __init__(self):
        self.token = None
        self.expires = 0

    def _get_token(self):
        cid = os.environ.get('BW_CLIENT_ID', '').strip()
        sec = os.environ.get('BW_CLIENT_SECRET', '').strip()
        if not cid or not sec:
            sys.exit('BW_CLIENT_ID ou BW_CLIENT_SECRET absent : verifier les secrets du depot.')
        body = urllib.parse.urlencode({'client_id': cid, 'client_secret': sec,
                                       'scope': 'api', 'grant_type': 'client_credentials'}).encode()
        req = urllib.request.Request(TOKEN_URL, data=body, headers={
            'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                tok = json.load(r)
        except urllib.error.HTTPError as e:
            sys.exit(f'Echec du jeton BarentsWatch ({e.code}) : {e.read()[:200]!r}')
        except urllib.error.URLError as e:
            sys.exit(f'Serveur BarentsWatch injoignable : {e.reason}')
        self.token = tok['access_token']
        self.expires = time.time() + int(tok.get('expires_in', 3600)) - 120

    def call(self, method, path, body=None, tries=4):
        for attempt in range(tries):
            if not self.token or time.time() > self.expires:
                self._get_token()
            data = json.dumps(body).encode() if body is not None else None
            headers = {'Authorization': f'Bearer {self.token}', 'User-Agent': UA,
                       'Accept': 'application/json'}
            if data is not None:
                headers['Content-Type'] = 'application/json'
            req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    time.sleep(PAUSE)
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.token = None          # jeton expire : on en redemande un
                elif e.code == 404:
                    return None
                elif e.code < 500 and e.code != 429:
                    raise RuntimeError(f'{method} {path} -> {e.code} {e.read()[:200]!r}')
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(5 * (attempt + 1))
        raise RuntimeError(f'{method} {path} : echec apres {tries} essais')


def iso_weeks(start, end):
    """Semaines ISO de start a end inclus, (annee, semaine)."""
    d = dt.date.fromisocalendar(start[0], start[1], 1)
    stop = dt.date.fromisocalendar(end[0], end[1], 1)
    out = []
    while d <= stop:
        y, w, _ = d.isocalendar()
        out.append((y, w))
        d += dt.timedelta(days=7)
    return out


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def aggregate_week(api, y, w, loc_po):
    sites = api.call('POST', f'/v2/geodata/fishhealth/locality/{y}/{w}', body={})
    if not isinstance(sites, list):
        return None, 0, {}
    acc = {}
    lookups = 0
    sick = {}          # site -> [po, nom, [codes maladie]]
    for s in sites:
        loc = s.get('locality') or {}
        no = loc.get('no')
        if no is None or loc.get('isOnLand') or not s.get('hasSalmonoidLicense') \
                or s.get('isSlaughterHoldingCage'):
            continue
        rep = s.get('liceReport') or {}
        diseases = [d if isinstance(d, str) else (d or {}).get('name') for d in (s.get('diseases') or [])]
        treats = [t if isinstance(t, str) else (t or {}).get('type') for t in (s.get('liceTreatments') or [])]
        relevant = rep.get('hasReported') or rep.get('isFallow') or diseases or treats
        if not relevant:
            continue
        key = str(no)
        if key not in loc_po:
            det = api.call('GET', f'/v2/geodata/fishhealth/locality/{no}/{y}/{w}')
            pa = (det or {}).get('productionArea') or {}
            loc_po[key] = pa.get('id') or 0     # 0 = hors zone / inconnu, pour ne pas redemander
            lookups += 1
        po = loc_po[key]
        if not po or not (1 <= po <= 13):
            continue
        a = acc.setdefault(po, {'na': 0, 'nf': 0, 'ls': 0.0, 'nl': 0, 'ov': 0,
                                'ts': 0.0, 'nt': 0, 'dis': {}, 'trt': {}})
        for d in diseases:
            if d:
                a['dis'][d] = a['dis'].get(d, 0) + 1
        codes = sorted({DIS_SHORT.get(d, d) for d in diseases if d})
        if codes:
            sick[key] = [po, loc.get('name') or '', codes]
        for t in set(treats):
            if t:
                a['trt'][t] = a['trt'].get(t, 0) + 1
        if rep.get('isFallow'):
            a['nf'] += 1
            continue
        if not rep.get('hasReported'):
            continue
        a['na'] += 1
        lice = num((rep.get('adultFemaleLice') or {}).get('average'))
        if lice is not None:
            a['ls'] += lice
            a['nl'] += 1
            if lice > LIMIT(po, w):
                a['ov'] += 1
        temp = num(rep.get('seaTemperature'))
        if temp is not None and -3 < temp < 30:
            a['ts'] += temp
            a['nt'] += 1
    rows = []
    for po in sorted(acc):
        a = acc[po]
        rows.append({'y': y, 'w': w, 'po': po, 'na': a['na'], 'nf': a['nf'],
                     'lice': round(a['ls'] / a['nl'], 4) if a['nl'] else None, 'nl': a['nl'],
                     'ov': a['ov'], 'lim': LIMIT(po, w),
                     't': round(a['ts'] / a['nt'], 2) if a['nt'] else None, 'nt': a['nt'],
                     'dis': a['dis'], 'trt': a['trt']})
    return rows, lookups, sick


def _label(e, *fields):
    if isinstance(e, str):
        return e
    if isinstance(e, dict):
        for f in fields:
            v = e.get(f)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict) and isinstance(v.get('name'), str):
                return v['name'].strip()
    return None


def treatment_keys_week(wk):
    """Cles 'categorie|detail' pour une semaine d'un site (format liceMedicationEvents)."""
    keys = set()
    def med(lst, prefix='medicinal'):
        for e in lst or []:
            name = _label(e, 'name', 'substance')
            kind = _label(e, 'type', 'treatmentType')
            keys.add(f'{prefix}|{kind or "?"}|{name or "?"}')
    def nonmed(lst):
        for e in lst or []:
            keys.add('nonmedicinal|' + (_label(e, 'type', 'name', 'treatmentType') or '?'))
    med(wk.get('medicinalTreatments'))
    nonmed(wk.get('nonMedicinalTreatments'))
    for c in wk.get('combinationTreatments') or []:
        keys.add('combination')
        if isinstance(c, dict):
            med(c.get('medicinalTreatments')); nonmed(c.get('nonMedicinalTreatments'))
    for e in wk.get('cleanerFishTreatments') or []:
        keys.add('cleanerfish|' + (_label(e, 'name', 'species', 'type') or '?'))
    if wk.get('mechanicalRemoval'):
        keys.add('mechanicalremoval')
    return keys


def update_treatments(api, loc_po, all_weeks):
    """Releve par site et par annee ; renvoie {(annee, semaine): {zone: {cle: sites}}}."""
    trt = json.load(io.open(TRT_FILE, encoding='utf-8')) if os.path.exists(TRT_FILE) else {}
    if 'site_year' not in trt:
        trt = {'site_year': {}, 'samples': []}       # ancien format : on repart de zero
    this_year, this_week = all_weeks[-1]
    # L'annee en cours est relue a CHAQUE execution (lundi, mercredi, vendredi) :
    # les declarations de la semaine W arrivent jusqu'au mardi de W+1, et les
    # traitements medicamenteux ne sont plus signales dans la liste hebdomadaire,
    # donc seule une relecture complete les capte au plus pres.
    stamp = dt.date.today().isoformat()
    sites = sorted(no for no, po in loc_po.items() if po and 1 <= int(po) <= 13)
    todo = []
    for y in range(TRT_FROM_YEAR, this_year + 1):
        for no in sites:
            rec = trt['site_year'].get(f'{no}|{y}')
            if rec is None:
                todo.append((no, y))
            elif y >= this_year - (1 if this_week <= 8 else 0) and rec.get('fetched') != stamp:
                todo.append((no, y))                  # annee en cours : relue une fois par semaine
    # annee en cours d'abord, puis on remonte
    todo.sort(key=lambda t: -t[1])
    calls = 0
    for no, y in todo[:TRT_BUDGET]:
        d = api.call('GET', f'/v1/geodata/fishhealth/locality/{no}/liceMedicationEvents/{y}')
        calls += 1
        weeks = {}
        for wk in (d or {}).get('data') or []:
            k = treatment_keys_week(wk)
            if k and wk.get('week'):
                weeks[str(wk['week'])] = sorted(k)
                if len(trt['samples']) < 15 and (wk.get('nonMedicinalTreatments') or wk.get('cleanerFishTreatments')):
                    trt['samples'].append({'site': no, 'year': y, 'week': wk})
        trt['site_year'][f'{no}|{y}'] = {'fetched': stamp, 'weeks': weeks}
    io.open(TRT_FILE, 'w', encoding='utf-8').write(json.dumps(trt, ensure_ascii=False, separators=(',', ':'), sort_keys=True))
    remaining = max(0, len(todo) - TRT_BUDGET)
    print(f'Traitements : {calls} sites-annees relus, {remaining} restants pour les prochains passages.')
    # agregation par zone et par semaine
    agg = {}
    for key, rec in trt['site_year'].items():
        no, y = key.split('|')
        po = loc_po.get(no)
        if not po:
            continue
        for w, keys in rec.get('weeks', {}).items():
            d = agg.setdefault((int(y), int(w)), {}).setdefault(str(po), {})
            for k in keys:
                d[k] = d.get(k, 0) + 1
    complete_years = {y for y in range(TRT_FROM_YEAR, this_year + 1)
                      if all(f'{no}|{y}' in trt['site_year'] for no in sites)}
    # export compact site par site pour le tableau de bord : une ligne par
    # site-semaine traitee, [site, zone, annee, semaine, [indices de cles]]
    keys, kidx, site_rows = [], {}, []
    for key, rec in sorted(trt['site_year'].items()):
        no, y = key.split('|')
        po = loc_po.get(no)
        if not po:
            continue
        for w, ks in sorted(rec.get('weeks', {}).items(), key=lambda t: int(t[0])):
            ids = []
            for k in ks:
                if k not in kidx:
                    kidx[k] = len(keys); keys.append(k)
                ids.append(kidx[k])
            site_rows.append([int(no), int(po), int(y), int(w), ids])
    site_export = {'keys': keys, 'rows': site_rows, 'years': sorted(complete_years)}
    return agg, complete_years, site_export


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-weeks', type=int, default=160,
                    help='semaines manquantes traitees au plus par execution')
    args = ap.parse_args()

    data = json.load(io.open(DATA, encoding='utf-8')) if os.path.exists(DATA) else {}
    store = data.get(KEY) or {'rows': [], 'meta': {}}
    loc_po = json.load(io.open(LOC_CACHE)) if os.path.exists(LOC_CACHE) else {}
    dis = json.load(io.open(DIS_FILE, encoding='utf-8')) if os.path.exists(DIS_FILE) else {'weeks': {}, 'names': {}}
    wk_key = lambda y, w: f'{y}-{w:02d}'

    # Derniere semaine close : celle d'il y a 7 jours (rapports deposes le
    # mardi suivant au plus tard). Les REFRESH_WEEKS dernieres sont refaites.
    last = (dt.date.today() - dt.timedelta(days=7)).isocalendar()[:2]
    all_weeks = iso_weeks(START, last)
    # une semaine est "acquise" si on a a la fois ses agregats et ses maladies site par site
    have = {(r['y'], r['w']) for r in store['rows']} & {tuple(map(int, k.split('-'))) for k in dis['weeks']}
    recent = set(all_weeks[-REFRESH_WEEKS:])
    missing = [wk for wk in all_weeks if wk not in have and wk not in recent]
    todo = sorted(recent) + missing[-args.max_weeks:][::-1]   # recentes d'abord, puis on remonte
    print(f'{len(have)} semaines deja presentes, {len(missing)} manquantes, '
          f'{len(todo)} a traiter cette fois (dont {len(recent)} recentes).')

    api = Api()
    done, lookups, failed = 0, 0, []
    by_week = {}
    for r in store['rows']:
        by_week.setdefault((r['y'], r['w']), []).append(r)
    t0 = time.time()
    for (y, w) in todo:
        try:
            rows, lk, sick = aggregate_week(api, y, w, loc_po)
        except RuntimeError as e:
            print(f'  {y}-S{w:02d} : {e}')
            failed.append((y, w))
            continue
        lookups += lk
        if rows is None:
            failed.append((y, w))
            continue
        by_week[(y, w)] = rows
        dis['weeks'][wk_key(y, w)] = {no: v[2] for no, v in sick.items()}
        for no, v in sick.items():
            dis['names'][no] = v[1]
            loc_po.setdefault(no, v[0])
        done += 1
        if done % 20 == 0:
            print(f'  ... {done}/{len(todo)} semaines, {lookups} sites localises, '
                  f'{time.time() - t0:.0f} s')
            # sauvegarde intermediaire du cache, pour ne pas tout perdre en cas d'arret
            io.open(LOC_CACHE, 'w').write(json.dumps(loc_po, separators=(',', ':'), sort_keys=True))

    # Caches enregistres tout de suite : si une etape suivante echoue, les
    # 30 a 40 minutes de releve ne sont pas perdues.
    io.open(LOC_CACHE, 'w').write(json.dumps(loc_po, separators=(',', ':'), sort_keys=True))
    io.open(DIS_FILE, 'w', encoding='utf-8').write(json.dumps(dis, ensure_ascii=False, separators=(',', ':'), sort_keys=True))
    store['rows'] = [r for k in sorted(by_week) for r in by_week[k]]
    weeks_in = sorted(by_week)
    store['meta'] = {
        'generated': dt.date.today().isoformat(),
        'first': list(weeks_in[0]) if weeks_in else None,
        'last': list(weeks_in[-1]) if weeks_in else None,
        'weeks': len(weeks_in),
        'complete_from_start': not [wk for wk in all_weeks if wk not in by_week],
        'source': 'BarentsWatch Fish Health API (NLOD), donnees declarees par les eleveurs',
        'limit_rule': '0,5 femelle adulte ; 0,2 en S16-21 (zones 1-7) et S21-26 (zones 8-13)',
    }
    # Detail des traitements, rattache aux lignes zone x semaine (cle 'trd')
    try:
        agg, complete_years, site_export = update_treatments(api, loc_po, all_weeks)
        store['site_trt'] = site_export
        for (y, w), rows in by_week.items():
            if y not in complete_years:
                for r in rows:
                    r.pop('trd', None)        # annee incomplete : pas de detail partiel trompeur
                continue
            per_po = agg.get((y, w), {})
            for r in rows:
                r['trd'] = per_po.get(str(r['po']), {})
        store['meta']['treatment_detail_years'] = sorted(complete_years)
    except RuntimeError as e:
        print('Detail des traitements indisponible :', e)
    store['rows'] = [r for k in sorted(by_week) for r in by_week[k]]

    # Nouveaux cas : maladie presente sur un site et absente des NEW_CASE_GAP
    # semaines precedentes (toutes disponibles, sinon on ne conclut pas).
    seq = all_weeks
    pos_of = {wk: i for i, wk in enumerate(seq)}
    events = []
    for (y, w) in seq:
        cur = dis['weeks'].get(wk_key(y, w))
        if cur is None:
            continue
        i = pos_of[(y, w)]
        prev_keys = [wk_key(*seq[j]) for j in range(i - NEW_CASE_GAP, i) if j >= 0]
        if len(prev_keys) < NEW_CASE_GAP or any(k not in dis['weeks'] for k in prev_keys):
            continue
        for no, codes in cur.items():
            before = set()
            for k in prev_keys:
                before.update(dis['weeks'][k].get(no, []))
            for c in codes:
                if c not in before:
                    events.append([y, w, int(loc_po.get(no) or 0), int(no), c])
    store['events'] = events
    # Maladies site par site en periodes continues, pour le detail par zone du
    # tableau de bord : [site, zone, code, debut (annee*100+semaine), fin]
    spans, open_ = [], {}
    for (y, w) in [wk for wk in seq if wk >= (TRT_FROM_YEAR - 1, 1)]:
        cur = dis['weeks'].get(wk_key(y, w))
        if cur is None:
            continue
        yw = y * 100 + w
        present = {(no, c) for no, codes in cur.items() for c in codes}
        for key in list(open_):
            if key not in present:
                spans.append(open_.pop(key))
        for (no, c) in present:
            if (no, c) in open_:
                open_[(no, c)][4] = yw
            else:
                open_[(no, c)] = [int(no), int(loc_po.get(no) or 0), c, yw, yw]
    spans.extend(open_.values())
    store['site_dis'] = sorted(spans, key=lambda r: (r[1], r[0], r[3]))
    # noms des sites cites (nouveaux cas et periodes de maladie)
    names = {str(e[3]): dis['names'].get(str(e[3]), '') for e in events}
    names.update({str(r[0]): dis['names'].get(str(r[0]), '') for r in spans})
    store['names'] = names
    store['meta']['events'] = len(events)
    store['meta']['new_case_rule'] = f'disease present at a site and absent from it in the {NEW_CASE_GAP} previous weeks'
    data[KEY] = store
    io.open(DATA, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    io.open(LOC_CACHE, 'w').write(json.dumps(loc_po, separators=(',', ':'), sort_keys=True))
    io.open(DIS_FILE, 'w', encoding='utf-8').write(json.dumps(dis, ensure_ascii=False, separators=(',', ':'), sort_keys=True))
    print(f'Nouveaux cas de maladie identifies : {len(events)}')
    print(f'\n{done} semaines traitees, {lookups} nouveaux sites localises '
          f'({len(loc_po)} en cache), {len(failed)} echecs.')
    print(f"Couverture : {store['meta']['first']} -> {store['meta']['last']}, "
          f"{store['meta']['weeks']} semaines ; complete depuis 2018 : {store['meta']['complete_from_start']}")
    if failed:
        print('Semaines en echec (reprises au prochain passage) :', failed[:20])


if __name__ == '__main__':
    main()
