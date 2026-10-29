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

Consequences des maladies (onglet Generations du tableau de bord) :
  data/bw_site_status.json garde, pour chaque site, son statut semaine par
  semaine depuis 2018 : 'a' = poissons (poux declares), 'f' = jachere,
  '-' = pas de declaration, '?' = semaine pas encore relue. L'historique est
  rattrape par tranches (STATUS_MAX semaines par execution, plus recentes
  d'abord). A partir de ces statuts et des maladies site par site, chaque
  episode de maladie (ILA, PD...) recoit sa consequence : site vide combien de
  semaines apres la detection, ou encore en production. Cle 'episodes' de
  bw_weekly :
    [site, zone, maladie, debut (annee*100+semaine), fin, poissons au debut
     (1/0/null), semaine du vidage (annee*100+semaine ou null), semaines entre
     detection et vidage (ou null), etat]
  etat : 'E' vide, 'S' encore en production a la derniere semaine connue,
  'N' pas de poisson au debut de l'episode, 'U' statuts pas encore rattrapes.

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
# Detail des traitements contre les poux. La liste hebdomadaire dit seulement
# quels sites ont traite (medicamenteux ou non) ; pour ces sites-semaines-la, la
# fiche du site (GET /v2/geodata/fishhealth/locality/{site}/{annee}/{semaine})
# donne le type exact : thermique, mecanique, eau douce, nettoyeurs,
# bain ou aliment medicamenteux et substance. Environ 60 sites-semaines par
# semaine en Norvege.
TRT_FILE = os.path.join(ROOT, 'data', 'bw_treatments.json')
TRT_FROM_YEAR = 2024          # historique detaille a partir de cette annee
TRT_BUDGET = 3000             # fiches lues au plus par execution (semaines recentes + rattrapage)
TRT_FROM = (TRT_FROM_YEAR, 1)
NEW_CASE_GAP = 4      # une maladie est un "nouveau cas" si absente du site les 4 semaines d'avant
STAT_FILE = os.path.join(ROOT, 'data', 'bw_site_status.json')
STATUS_UNTIL = 40 * 60    # rattrapage de l'historique des statuts arrete apres 40 min
STATUS_MAX = 150          # semaines d'historique rattrapees au plus par execution
EPISODE_GAP = 8           # maladie absente moins de 8 semaines : meme episode
EMPTY_RUN = 3             # site vide : jachere, ou plus de declaration 3 semaines de suite
EMPTY_HORIZON = 104       # vidage cherche jusqu'a 2 ans apres la detection
TOKEN_URL = 'https://id.barentswatch.no/connect/token'
API = 'https://www.barentswatch.no/bwapi'
UA = 'saumon-dashboard (github.com/emileviardotfo/saumon)'
KEY = 'bw_weekly'
START = (2018, 1)
REFRESH_WEEKS = 4
PAUSE = 0.15          # secondes entre deux appels : BarentsWatch demande un seul fil
# Garde-fous de duree (l'etape du workflow est coupee a 60 min et perdrait tout) :
T_START = time.time()
WEEKS_UNTIL = 33 * 60     # releve des semaines arrete apres 33 min
DETAIL_UNTIL = 52 * 60    # fiches des sites traites arretees apres 52 min


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


# Statut de chaque site par semaine releve pendant cette execution :
# {(annee, semaine): {site: 'a' (poisson, poux declares) ou 'f' (jachere)}}
STATUS = {}


def aggregate_week(api, y, w, loc_po):
    sites = api.call('POST', f'/v2/geodata/fishhealth/locality/{y}/{w}', body={})
    if not isinstance(sites, list):
        return None, 0, {}, {}
    acc = {}
    lookups = 0
    sick = {}          # site -> [po, nom, [codes maladie]]
    treated = {}       # site -> [po, [types de la liste hebdomadaire]]
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
        if any(treats):
            treated[key] = [po, sorted({t for t in treats if t})]
        if rep.get('isFallow'):
            a['nf'] += 1
            STATUS.setdefault((y, w), {})[key] = 'f'
            continue
        if not rep.get('hasReported'):
            continue
        a['na'] += 1
        STATUS.setdefault((y, w), {})[key] = 'a'
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
    return rows, lookups, sick, treated


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


def _names(lst, *fields):
    out = []
    for e in lst or []:
        n = _label(e, *fields)
        if n:
            out.append(n)
    return out


def treatment_keys_detail(lt, fallback):
    """Cles 'categorie|detail' a partir du bloc liceTreatments d'une fiche de site."""
    keys = set()
    if not isinstance(lt, dict):
        lt = {}

    def med(lst, kind=None):
        for e in lst or []:
            if not isinstance(e, dict):
                continue
            k = kind or _label(e, 'treatmentType', 'type') or '?'
            subs = [_label(d.get('substance') or {}, 'name') or _label(d, 'name', 'substanceName')
                    for d in e.get('treatmentDetail') or [] if isinstance(d, dict)]
            subs = [x for x in subs if x] or [_label(e, 'name', 'substance') or '?']
            for sname in subs:
                keys.add(f'medicinal|{k}|{sname}')

    def nonmed(lst):
        for e in lst or []:
            keys.add('nonmedicinal|' + (_label(e, 'type', 'name', 'treatmentType') or '?'))

    med(lt.get('medicinalTreatments'))
    med(lt.get('bathTreatments'), 'Bath')
    med(lt.get('inFeedTreatments'), 'InFeed')
    nonmed(lt.get('nonMedicinalTreatments'))
    for c in lt.get('combinationTreatments') or []:
        keys.add('combination')
        if isinstance(c, dict):
            med(c.get('medicinalTreatments')); med(c.get('bathTreatments'), 'Bath')
            med(c.get('inFeedTreatments'), 'InFeed'); nonmed(c.get('nonMedicinalTreatments'))
    cf = lt.get('cleanerFishTreatment')
    if cf:
        sp = _names((cf or {}).get('cleanerFish') or (cf or {}).get('species') or [], 'name', 'species', 'type') \
            if isinstance(cf, dict) else []
        keys.add('cleanerfish|' + (', '.join(sorted(set(sp))) or 'cleaner fish'))
    if lt.get('mechanicalRemovalTreatment'):
        keys.add('mechanicalremoval')
    if not keys:
        # la liste disait "traite" mais la fiche ne detaille rien
        for t in fallback:
            keys.add(('medicinal|?|?' if t == 'MEDIKAMENTELL' else 'nonmedicinal|?'))
    return keys


def update_treatments(api, loc_po, all_weeks, dis):
    """Fiche de chaque site-semaine traite depuis TRT_FROM ; renvoie
    ({(annee, semaine): {zone: {cle: sites}}}, annees completes, export site par site)."""
    trt = json.load(io.open(TRT_FILE, encoding='utf-8')) if os.path.exists(TRT_FILE) else {}
    if trt.get('v') != 2:
        trt = {'v': 2, 'site_week': {}, 'samples': []}   # ancien format (par annee) : abandonne
    sw = trt['site_week']
    wk_key = lambda y, w: f'{y}-{w:02d}'
    recent = set(all_weeks[-REFRESH_WEEKS:])
    weeks = [wk for wk in all_weeks if wk >= TRT_FROM]
    todo = []
    for (y, w) in weeks:
        lst = dis.get('trt_weeks', {}).get(wk_key(y, w))
        if lst is None:
            continue
        for no, (po, types) in lst.items():
            k = f'{no}|{y}|{w}'
            if k not in sw or ((y, w) in recent and sw[k].get('types') != types):
                todo.append((y, w, no, types))
    # semaines recentes d'abord, puis on remonte
    todo.sort(key=lambda t: (-t[0], -t[1]))
    calls = 0
    for (y, w, no, types) in todo[:TRT_BUDGET]:
        if time.time() - T_START > DETAIL_UNTIL:
            print('  arret des fiches (duree), reprise au prochain passage')
            break
        try:
            det = api.call('GET', f'/v2/geodata/fishhealth/locality/{no}/{y}/{w}')
        except RuntimeError as e:
            print('  ', no, y, w, e); continue
        calls += 1
        lt = (det or {}).get('liceTreatments')
        sw[f'{no}|{y}|{w}'] = {'types': types, 'keys': sorted(treatment_keys_detail(lt, types))}
        if len(trt['samples']) < 12 and isinstance(lt, dict) and any(lt.get(x) for x in lt):
            trt['samples'].append({'site': no, 'year': y, 'week': w, 'liceTreatments': lt})
    # on ne garde que les sites-semaines encore signales comme traites
    valid = {f'{no}|{y}|{w}' for (y, w) in weeks
             for no in (dis.get('trt_weeks', {}).get(wk_key(y, w)) or {})}
    for k in [k for k in sw if k not in valid]:
        del sw[k]
    io.open(TRT_FILE, 'w', encoding='utf-8').write(json.dumps(trt, ensure_ascii=False, separators=(',', ':'), sort_keys=True))
    remaining = max(0, len(todo) - calls)
    print(f'Traitements : {calls} fiches site-semaine lues, {remaining} restantes pour les prochains passages.')
    agg, keys, kidx, site_rows = {}, [], {}, []
    for k, rec in sorted(sw.items(), key=lambda t: (int(t[0].split('|')[1]), int(t[0].split('|')[2]), int(t[0].split('|')[0]))):
        no, y, w = k.split('|')
        po = loc_po.get(no)
        if not po:
            continue
        d = agg.setdefault((int(y), int(w)), {}).setdefault(str(po), {})
        ids = []
        for key in rec.get('keys') or []:
            d[key] = d.get(key, 0) + 1
            if key not in kidx:
                kidx[key] = len(keys); keys.append(key)
            ids.append(kidx[key])
        site_rows.append([int(no), int(po), int(y), int(w), ids])
    # annee complete : toutes ses semaines ont leur liste de sites traites, et
    # tous ces sites-semaines ont leur fiche
    done_keys = set(sw)
    complete_years = set()
    for yr in sorted({y for y, _ in weeks}):
        ws = [wk for wk in weeks if wk[0] == yr]
        if all(wk_key(*wk) in dis.get('trt_weeks', {}) for wk in ws) and \
                all(f'{no}|{y}|{w}' in done_keys for (y, w) in ws
                    for no in dis['trt_weeks'][wk_key(y, w)]):
            complete_years.add(yr)
    return agg, complete_years, {'keys': keys, 'rows': site_rows, 'years': sorted(complete_years)}


def fetch_status(api, y, w, loc_po):
    """Statut de chaque site pour une semaine deja agregee (rattrapage de l'historique)."""
    sites = api.call('POST', f'/v2/geodata/fishhealth/locality/{y}/{w}', body={})
    if not isinstance(sites, list):
        return False
    st = STATUS.setdefault((y, w), {})
    for s in sites:
        loc = s.get('locality') or {}
        no = loc.get('no')
        if no is None or loc.get('isOnLand') or not s.get('hasSalmonoidLicense') \
                or s.get('isSlaughterHoldingCage'):
            continue
        po = loc_po.get(str(no))
        if not po or not (1 <= po <= 13):
            continue
        rep = s.get('liceReport') or {}
        if rep.get('isFallow'):
            st[str(no)] = 'f'
        elif rep.get('hasReported'):
            st[str(no)] = 'a'
    return True


def load_status(all_weeks):
    """Historique des statuts : {'first', 'have' [semaines relues], 'sites' {site: chaine}}."""
    stat = json.load(io.open(STAT_FILE)) if os.path.exists(STAT_FILE) else {}
    n = len(all_weeks)
    first = '%d-%02d' % all_weeks[0]
    if stat.get('first') != first:
        stat = {}
    stat['first'] = first
    stat.setdefault('have', [])
    stat['sites'] = {k: v.ljust(n, '?')[:n] for k, v in (stat.get('sites') or {}).items()}
    return stat


def merge_status(stat, all_weeks):
    """Ajoute les semaines relues pendant cette execution (STATUS) a l'historique."""
    idx = {wk: i for i, wk in enumerate(all_weeks)}
    n = len(all_weeks)
    have = set(stat['have'])
    sites = {k: list(v) for k, v in stat['sites'].items()}
    for wk, st in STATUS.items():
        i = idx.get(wk)
        if i is None:
            continue
        have.add('%d-%02d' % wk)
        for no in st:
            if no not in sites:
                # site nouveau : '-' pour les semaines deja relues ou il n'apparaissait pas
                sites[no] = ['-' if ('%d-%02d' % all_weeks[j]) in have else '?' for j in range(n)]
        for no, arr in sites.items():
            arr[i] = st.get(no, '-')
    stat['have'] = sorted(have)
    stat['sites'] = {k: ''.join(v) for k, v in sites.items()}
    return stat


def build_episodes(dis, all_weeks, stat, loc_po):
    """Episodes de maladie par site et leur consequence (vidage du site ou non)."""
    keys = ['%d-%02d' % wk for wk in all_weeks]
    yw = [y * 100 + w for (y, w) in all_weeks]
    have = set(stat['have'])
    opened, eps = {}, []
    for i, k in enumerate(keys):
        cur = dis['weeks'].get(k)
        if cur is None:
            continue
        for no, codes in cur.items():
            for c in codes:
                o = opened.get((no, c))
                if o and i - o[1] <= EPISODE_GAP:
                    o[1] = i
                else:
                    if o:
                        eps.append((no, c, o[0], o[1]))
                    opened[(no, c)] = [i, i]
    eps += [(no, c, o[0], o[1]) for (no, c), o in opened.items()]
    out = []
    last_known = max((i for i, k in enumerate(keys) if k in have), default=-1)
    for no, c, a, b in sorted(eps, key=lambda e: (e[2], e[0])):
        s = stat['sites'].get(no)
        row = [int(no), int(loc_po.get(no) or 0), c, yw[a], yw[b]]
        if not s or any(keys[j] not in have for j in range(max(0, a - 4), a + 1)):
            out.append(row + [None, None, None, 'U'])
            continue
        fish0 = 1 if 'a' in s[max(0, a - 4):a + 1] else 0
        if not fish0:
            out.append(row + [0, None, None, 'N'])
            continue
        state, empty = 'S', None
        for j in range(a, min(a + EMPTY_HORIZON, len(keys))):
            if keys[j] not in have:
                state = 'U'
                break
            if s[j] == 'f' or (s[j] == '-' and s[j:j + EMPTY_RUN] == '-' * EMPTY_RUN):
                state, empty = 'E', j
                break
        if state == 'S' and last_known < min(a + EMPTY_HORIZON, len(keys)) - 1 and last_known < len(keys) - 1:
            state = 'U'
        out.append(row + [1, yw[empty] if empty is not None else None,
                          (empty - a) if empty is not None else None, state])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-weeks', type=int, default=160,
                    help='semaines manquantes traitees au plus par execution')
    args = ap.parse_args()

    data = json.load(io.open(DATA, encoding='utf-8')) if os.path.exists(DATA) else {}
    store = data.get(KEY) or {'rows': [], 'meta': {}}
    loc_po = json.load(io.open(LOC_CACHE)) if os.path.exists(LOC_CACHE) else {}
    dis = json.load(io.open(DIS_FILE, encoding='utf-8')) if os.path.exists(DIS_FILE) else {'weeks': {}, 'names': {}}
    dis.setdefault('trt_weeks', {})
    wk_key = lambda y, w: f'{y}-{w:02d}'

    # Derniere semaine close : celle d'il y a 7 jours (rapports deposes le
    # mardi suivant au plus tard). Les REFRESH_WEEKS dernieres sont refaites.
    last = (dt.date.today() - dt.timedelta(days=7)).isocalendar()[:2]
    all_weeks = iso_weeks(START, last)
    # une semaine est "acquise" si on a a la fois ses agregats et ses maladies site par site
    # depuis TRT_FROM, il faut aussi la liste des sites traites de la semaine
    have = {(r['y'], r['w']) for r in store['rows']} & {tuple(map(int, k.split('-'))) for k in dis['weeks']}
    have = {wk for wk in have if wk < TRT_FROM or wk_key(*wk) in dis['trt_weeks']}
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
        if time.time() - T_START > WEEKS_UNTIL and (y, w) not in recent:
            print(f'  arret du releve des semaines (duree) apres {done} semaines, reprise au prochain passage')
            break
        try:
            rows, lk, sick, treated = aggregate_week(api, y, w, loc_po)
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
        if (y, w) >= TRT_FROM:
            dis['trt_weeks'][wk_key(y, w)] = treated
        for no, v in sick.items():
            dis['names'][no] = v[1]
            loc_po.setdefault(no, v[0])
        done += 1
        if done % 20 == 0:
            print(f'  ... {done}/{len(todo)} semaines, {lookups} sites localises, '
                  f'{time.time() - t0:.0f} s')
            # sauvegarde intermediaire du cache, pour ne pas tout perdre en cas d'arret
            io.open(LOC_CACHE, 'w').write(json.dumps(loc_po, separators=(',', ':'), sort_keys=True))

    # Historique des statuts de site (poissons / jachere) : semaines relues
    # ci-dessus, puis rattrapage des semaines anciennes, plus recentes d'abord.
    stat = load_status(all_weeks)
    have_st = set(stat['have']) | {'%d-%02d' % wk for wk in STATUS}
    back = [wk for wk in all_weeks[::-1] if '%d-%02d' % wk not in have_st][:STATUS_MAX]
    nb = 0
    for (y, w) in back:
        if time.time() - T_START > STATUS_UNTIL:
            break
        try:
            if fetch_status(api, y, w, loc_po):
                nb += 1
        except RuntimeError as e:
            print(f'  statuts {y}-S{w:02d} : {e}')
    stat = merge_status(stat, all_weeks)
    io.open(STAT_FILE, 'w').write(json.dumps(stat, separators=(',', ':'), sort_keys=True))
    print(f'Statuts de site : {nb} semaines d\'historique rattrapees, '
          f'{len(stat["have"])}/{len(all_weeks)} semaines connues.')

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
        agg, complete_years, site_export = update_treatments(api, loc_po, all_weeks, dis)
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
    # Sites en production sur les REFRESH_WEEKS dernieres semaines (relues a
    # chaque execution) : nombre de semaines avec poisson / en jachere, par site.
    # Sert a l'onglet Farm register pour ponderer la MTB par l'activite reelle.
    act = {}
    rw = sorted(wk for wk in STATUS if wk in recent)
    for wk in rw:
        for no, st in STATUS[wk].items():
            a = act.setdefault(no, [0, 0])
            a[0 if st == 'a' else 1] += 1
    if act:
        store['site_act'] = {'weeks': [list(wk) for wk in rw], 'sites': act}
    store['meta']['events'] = len(events)
    # Episodes de maladie et leur consequence (vidage du site)
    store['episodes'] = build_episodes(dis, all_weeks, stat, loc_po)
    store['meta']['status_weeks'] = [len(stat['have']), len(all_weeks)]
    store['meta']['episode_rule'] = (f'episode = same disease at a site, gaps under {EPISODE_GAP} weeks; site emptied = fallow, '
                                     f'or no lice report {EMPTY_RUN} weeks in a row, within {EMPTY_HORIZON} weeks of detection')
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
