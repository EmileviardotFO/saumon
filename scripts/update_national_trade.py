#!/usr/bin/env python3
"""
Exportations de saumon des Iles Feroe, de l'Islande et du Royaume-Uni (Ecosse),
par pays de destination et par mois, depuis les statistiques nationales :

  - Feroe   : Hagstova Foroya, table UH01046 "Inn- og utflutningur skiftur a
              vorunummar og land" (uh_cn_t.px), mensuelle depuis 2023, CN8.
  - Islande : Hagstofa Islands, table UTA02801 "Utflutningur eftir
              tollskrarnumerum 2024-2026, kafli 1-40", numeros tarifaires
              islandais a 8 chiffres (saumon d'elevage atlantique separe).
  - Chili et Canada : ONU Comtrade (API publique, donnees declarees par chaque pays, SH6).
  - En plus : importations des Etats-Unis par origine (US Census Bureau, data/us_imports.json)
    et de la Chine et de Hong Kong (UN Comtrade, data/cn_imports.json), pour les onglets
    "USA focus" et "China focus" et le controle des declarations des exportateurs.
  - Royaume-Uni : HMRC, API OData publique uktradeinfo (OTS), CN8 ; le saumon
              d'elevage britannique est ecossais (quelques reexportations de
              saumon norvegien incluses).

Comme les statistiques norvegiennes, elles donnent le pays de destination
declare a l'export, meme quand le saumon est dedouane au Danemark ou aux
Pays-Bas : c'est ce qui permet de savoir combien de saumon feroien ou
islandais va reellement en Espagne, en France, etc.

Le script lit d'abord la description de chaque table (variables et valeurs),
reconnait seul les dimensions (produit, pays, mois, unite, sens du flux), puis
telecharge par tranches d'un an. Les valeurs en couronnes sont converties en
euros (couronne danoise : parite fixe ; couronne islandaise : taux mensuel
moyen d'Eurostat).

Sortie : data/national_trade.json
  rows = [annee*100+mois, origine (FO/IS), destination (ISO2), indice de forme
          (0 entier frais, 1 entier congele, 2 filets frais, 3 filets congeles,
          5 fume, 6 prepare), tonnes, milliers de monnaie locale, milliers d'euros]
Les descriptions des tables sont enregistrees dans data/national_probe/ pour
le depannage.

    python3 scripts/update_national_trade.py
"""
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'national_trade.json')
DBG = os.path.join(ROOT, 'data', 'national_probe')
UA = 'Mozilla/5.0 (X11; Linux x86_64) saumon-dashboard (github.com/emileviardotfo/saumon)'

SOURCES = {
    'FO': {
        'name': 'Hagstova Føroya, table UH01046 (exports by CN8 and country, monthly)',
        'urls': ['https://statbank.hagstova.fo/api/v1/en/H2/UH/UH01/uh_cn_t.px',
                 'https://statbank.hagstova.fo/api/v1/fo/H2/UH/UH01/uh_cn_t.px'],
        'currency': 'DKK',
        # code CN8 -> indice de forme du tableau de bord
        'codes': {'03021400': 0, '03031300': 1, '03044100': 2, '03048100': 3, '03054100': 5, '16041100': 6},
    },
    'IS': {
        'name': 'Statistics Iceland, table UTA02801 (exports by tariff number, monthly)',
        'urls': ['https://px.hagstofa.is/pxen/api/v1/en/Efnahagur/utanrikisverslun/1_voruvidskipti/02_uttollskra/UTA02801.px',
                 'https://px.hagstofa.is/pxis/api/v1/is/Efnahagur/utanrikisverslun/1_voruvidskipti/02_uttollskra/UTA02801.px'],
        'currency': 'ISK',
        # Hagstofa remplace cette table chaque annee (2024-2026, puis 2025-2027...) : on cherche
        # d'abord dans le dossier la table "chapitres 1-40" la plus recente.
        'folder': 'https://px.hagstofa.is/pxen/api/v1/en/Efnahagur/utanrikisverslun/1_voruvidskipti/02_uttollskra',
        'pick': r'(\d{4})\s*-\s*(\d{4}).*(chapter|kafli)s?\s*1\s*-\s*40',
        # numeros islandais : saumon atlantique d'elevage (et filets congeles de saumon atlantique)
        'codes': {'03021401': 0, '03031301': 1, '03044111': 2, '03048101': 3, '03048110': 3, '03048120': 3,
                  '03054100': 5, '16041100': 6, '16041101': 6, '16041109': 6},
    },
}
SOURCES['GB'] = {
    'kind': 'hmrc',
    'name': 'HMRC overseas trade statistics (uktradeinfo API), United Kingdom — farmed salmon is Scottish',
    'currency': 'GBP',
    'codes': {'03021400': 0, '03031300': 1, '03044100': 2, '03048100': 3, '03054100': 5, '16041100': 6},
}
SOURCES['CL'] = {
    'kind': 'comtrade',
    'name': 'UN Comtrade, exports reported by Chile (HS6, monthly; FOB in USD)',
    'currency': 'USD',
    # HS6 : 030214 entier frais atlantique, 030313 entier congele atlantique,
    # 030441 / 030481 filets frais / congeles (saumon atlantique et du Pacifique : coho inclus)
    'codes': {'030214': 0, '030313': 1, '030441': 2, '030481': 3, '030541': 5, '160411': 6},
    'reporter': 152,
}
SOURCES['CA'] = {
    'kind': 'comtrade',
    'name': 'UN Comtrade, exports reported by Canada (HS6, monthly; FOB in USD)',
    'currency': 'USD',
    'codes': {'030214': 0, '030313': 1, '030441': 2, '030481': 3, '030541': 5, '160411': 6},
    'reporter': 124,
}
SOURCES['AU'] = {
    'kind': 'comtrade',
    'name': 'UN Comtrade, exports reported by Australia (HS6, monthly; FOB in USD) — farmed salmon is Tasmanian',
    'currency': 'USD',
    'codes': {'030214': 0, '030313': 1, '030441': 2, '030481': 3, '030541': 5, '160411': 6},
    'reporter': 36,
    # source ajoutee en octobre 2026 : un echec (Australie absente ou en retard sur Comtrade) ne bloque pas
    # la mise a jour ; il est signale dans meta.failed_optional
    'optional': True,
}
DKK_PER_EUR = 7.46038       # parite centrale MCE II


def http(url, body=None, tries=3):
    data = json.dumps(body).encode() if body is not None else None
    for a in range(tries):
        req = urllib.request.Request(url, data=data, headers={'User-Agent': UA, 'Accept': 'application/json',
                                                              'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            txt = e.read()
            if e.code in (400, 403, 404):
                return e.code, txt
            print(f'    HTTP {e.code}, nouvel essai')
        except Exception as e:
            print('   ', repr(e)[:150])
        time.sleep(8 * (a + 1))
    return None, b''


def code_of(v):
    m = re.match(r'\s*(\d{8})', v)
    return m.group(1) if m else None


def detect(meta, codes):
    """Reconnait les dimensions de la table : produit, pays, temps, unite, flux, autres."""
    dims = {}
    for v in meta['variables']:
        vals, texts = v['values'], v.get('valueTexts', v['values'])
        blob = (v['code'] + ' ' + v['text']).lower()
        if any((code_of(x) or code_of(t) or '') in codes for x, t in zip(vals, texts)):
            dims['product'] = v
        elif v.get('time') or all(re.match(r'^\d{4}M\d{2}$', x) for x in vals[:5]):
            dims['time'] = v
        elif re.search(r'land|country|lond', blob):
            dims['country'] = v
        elif re.search(r'flow|rák|rak|innflutn|útflutn|import|export', blob + ' ' + ' '.join(texts).lower()) and len(vals) <= 4:
            dims['flow'] = v
        elif re.search(r'unit|eining|mát|mat|measure|contents|statistic', blob) or \
                any(re.search(r'kg|kíló|kilo|nøgd|quantity|value|virði|krón|fob', t, re.I) for t in texts):
            dims['unit'] = v
        else:
            dims.setdefault('other', []).append(v)
    return dims


def pick_units(v):
    """-> (valeur de la quantite en kg, valeur du montant)"""
    qty = val = None
    for x, t in zip(v['values'], v.get('valueTexts', v['values'])):
        tl = t.lower()
        if qty is None and re.search(r'kg|kíló|kilo|nøgd|quantity|weight|net', tl):
            qty = x
        elif val is None and re.search(r'value|virði|krón|kr\.|fob|isk|dkk|amount|verð', tl):
            val = x
    return qty, val


def iso_map():
    try:
        import pycountry
    except ImportError:
        pycountry = None
    over = {'united states': 'US', 'usa': 'US', 'united kingdom': 'GB', 'great britain': 'GB', 'russia': 'RU',
            'russian federation': 'RU', 'south korea': 'KR', 'korea, republic of': 'KR', 'korea': 'KR', 'taiwan': 'TW',
            'vietnam': 'VN', 'viet nam': 'VN', 'czech republic': 'CZ', 'czechia': 'CZ', 'hong kong': 'HK',
            'china': 'CN', 'turkey': 'TR', 'türkiye': 'TR', 'iran': 'IR', 'netherlands': 'NL', 'holland': 'NL',
            'the netherlands': 'NL', 'faroe islands': 'FO', 'greenland': 'GL', 'ivory coast': 'CI',
            'united arab emirates': 'AE', 'moldova': 'MD', 'belarus': 'BY', 'macedonia': 'MK', 'north macedonia': 'MK',
            'bosnia and herzegovina': 'BA', 'kosovo': 'XK', 'serbia': 'RS', 'montenegro': 'ME', 'tanzania': 'TZ',
            'bolivia': 'BO', 'venezuela': 'VE', 'syria': 'SY', 'laos': 'LA', 'brunei': 'BN', 'cape verde': 'CV',
            'macao': 'MO', 'macau': 'MO', 'palestine': 'PS', 'swaziland': 'SZ', 'eswatini': 'SZ',
            # noms feroiens / islandais les plus courants (au cas ou la table n'existe qu'en langue locale)
            'danmark': 'DK', 'danmörk': 'DK', 'spania': 'ES', 'spánn': 'ES', 'frakland': 'FR', 'frakkland': 'FR',
            'týskland': 'DE', 'þýskaland': 'DE', 'pólland': 'PL', 'niðurlond': 'NL', 'bandaríkin': 'US', 'usa (bandaríkini)': 'US',
            'stóra bretland': 'GB', 'bretland': 'GB', 'russland': 'RU', 'rússland': 'RU', 'kina': 'CN', 'kína': 'CN',
            'italia': 'IT', 'ítalía': 'IT', 'belgia': 'BE', 'belgía': 'BE', 'portugal': 'PT', 'portúgal': 'PT',
            'svøríki': 'SE', 'svíþjóð': 'SE', 'noreg': 'NO', 'noregur': 'NO', 'sveis': 'CH', 'sviss': 'CH',
            'japan': 'JP', 'japan ': 'JP', 'kanada': 'CA', 'litava': 'LT', 'litháen': 'LT', 'ísland': 'IS', 'føroyar': 'FO'}
    eng = {'spain': 'ES', 'france': 'FR', 'poland': 'PL', 'germany': 'DE', 'denmark': 'DK', 'italy': 'IT', 'belgium': 'BE',
           'portugal': 'PT', 'sweden': 'SE', 'finland': 'FI', 'norway': 'NO', 'iceland': 'IS', 'ireland': 'IE', 'austria': 'AT',
           'switzerland': 'CH', 'luxembourg': 'LU', 'greece': 'GR', 'cyprus': 'CY', 'malta': 'MT', 'lithuania': 'LT', 'latvia': 'LV',
           'estonia': 'EE', 'slovakia': 'SK', 'slovenia': 'SI', 'hungary': 'HU', 'romania': 'RO', 'bulgaria': 'BG', 'croatia': 'HR',
           'ukraine': 'UA', 'georgia': 'GE', 'kazakhstan': 'KZ', 'israel': 'IL', 'egypt': 'EG', 'morocco': 'MA', 'tunisia': 'TN',
           'nigeria': 'NG', 'south africa': 'ZA', 'canada': 'CA', 'mexico': 'MX', 'brazil': 'BR', 'argentina': 'AR', 'chile': 'CL',
           'colombia': 'CO', 'peru': 'PE', 'japan': 'JP', 'thailand': 'TH', 'singapore': 'SG', 'malaysia': 'MY', 'indonesia': 'ID',
           'philippines': 'PH', 'india': 'IN', 'australia': 'AU', 'new zealand': 'NZ', 'saudi arabia': 'SA', 'qatar': 'QA',
           'kuwait': 'KW', 'bahrain': 'BH', 'oman': 'OM', 'jordan': 'JO', 'lebanon': 'LB', 'armenia': 'AM', 'azerbaijan': 'AZ',
           'uzbekistan': 'UZ', 'albania': 'AL', 'andorra': 'AD', 'monaco': 'MC', 'gibraltar': 'GI', 'liechtenstein': 'LI',
           'taiwan, province of china': 'TW', 'korea, republic of': 'KR', 'republic of korea': 'KR', 'viet nam': 'VN',
           'russian federation': 'RU', 'china, hong kong': 'HK', 'hong kong, china': 'HK', 'united states of america': 'US',
           'united kingdom of great britain and northern ireland': 'GB', 'cayman islands': 'KY', 'dominican republic': 'DO',
           'sri lanka': 'LK', 'pakistan': 'PK', 'bangladesh': 'BD', 'cambodia': 'KH', 'myanmar': 'MM', 'mongolia': 'MN',
           'ecuador': 'EC', 'uruguay': 'UY', 'paraguay': 'PY', 'costa rica': 'CR', 'panama': 'PA', 'guatemala': 'GT',
           'puerto rico': 'PR', 'cuba': 'CU', 'jamaica': 'JM', 'bahamas': 'BS', 'barbados': 'BB', 'algeria': 'DZ', 'ghana': 'GH',
           'kenya': 'KE', 'angola': 'AO', 'mauritius': 'MU', 'seychelles': 'SC', 'maldives': 'MV', 'iraq': 'IQ', 'libya': 'LY'}
    over.update(eng)

    def f(code, text):
        c = (code or '').strip().upper()
        if re.fullmatch(r'[A-Z]{2}', c) and c not in ('XX',):
            return c
        t = re.sub(r'^\s*[A-Z]{2}\s*[-–]\s*', '', text or '').strip()
        tl = t.lower()
        if tl in over:
            return over[tl]
        if re.search(r'total|alls|samtals|tilsamans|tilsaman|all countries|other|annað|onnur|ótilgreint|unknown', tl):
            return None
        if pycountry:
            try:
                return pycountry.countries.lookup(t).alpha_2
            except LookupError:
                pass
        return None
    return f


def eur_rates(cur):
    """Taux moyens mensuels : unites de monnaie pour 1 EUR (Eurostat ert_bil_eur_m)."""
    url = ('https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/ert_bil_eur_m'
           f'?format=JSON&lang=EN&currency={cur}&statinfo=AVG&sinceTimePeriod=2018-01')
    st, raw = http(url)
    out = {}
    if st != 200:
        print(f'  taux {cur} indisponibles ({st})')
        return out
    j = json.loads(raw)
    idx = j['dimension']['time']['category']['index']
    for t, i in idx.items():
        v = j['value'].get(str(i))
        if v:
            y, m = t.split('-') if '-' in t else t.split('M')
            out[int(y) * 100 + int(m)] = float(v)
    print(f'  {len(out)} taux {cur} mensuels')
    return out


def to_eur(val, ym, cur, fx):
    if cur == 'DKK':
        return val / DKK_PER_EUR
    r = fx.get(cur, {})
    rate = r.get(ym) or (r[max(k for k in r if k <= ym)] if any(k <= ym for k in r) else (r[min(r)] if r else None))
    return val / rate if rate else None


def fetch_hmrc(key, src, to_iso, fx):
    """Royaume-Uni : HMRC, API OData publique de uktradeinfo (OTS = commerce par produit et pays)."""
    base = 'https://api.uktradeinfo.com'
    os.makedirs(DBG, exist_ok=True)

    def pages(url):
        out = []
        while url:
            st, raw = http(url)
            if st != 200:
                raise RuntimeError(f'{url[:120]} -> {st} {raw[:200]!r}')
            j = json.loads(raw)
            out += j.get('value', [])
            url = j.get('@odata.nextLink')
        return out
    flows = pages(base + '/FlowType')
    json.dump(flows, open(os.path.join(DBG, 'hmrc_flowtypes.json'), 'w'), indent=0)
    exp_ids = [f['FlowTypeId'] for f in flows if re.search(r'xport', ' '.join(str(v) for v in f.values()), re.I)]
    print(f'  {key} : types de flux export : {exp_ids}')
    if not exp_ids:
        raise RuntimeError('types de flux export introuvables')
    ctry = pages(base + '/Country')
    json.dump(ctry[:400], open(os.path.join(DBG, 'hmrc_countries.json'), 'w'), indent=0, ensure_ascii=False)
    cmap = {}
    for c in ctry:
        alpha = c.get('CountryCodeAlpha') or c.get('CountryCodeAlpha2') or ''
        cmap[c['CountryId']] = to_iso(alpha, c.get('CountryName'))
    agg, start = {}, 202301
    for code, pi in src['codes'].items():
        cid = int(code)
        flt = f'CommodityId eq {cid} and MonthId ge {start} and (' + ' or '.join(f'FlowTypeId eq {i}' for i in exp_ids) + ')'
        rows = pages(base + '/OTS?$filter=' + urllib.parse.quote(flt) + '&$select=MonthId,FlowTypeId,CountryId,NetMass,Value')
        print(f'  {key} : {code} -> {len(rows)} lignes')
        if rows and code == '03021400':
            json.dump(rows[:50], open(os.path.join(DBG, 'hmrc_sample.json'), 'w'), indent=0)
        for r in rows:
            iso = cmap.get(r.get('CountryId'))
            if not iso:
                continue
            k = (int(r['MonthId']), iso, pi)
            x = agg.setdefault(k, [0.0, 0.0])
            x[0] += float(r.get('NetMass') or 0)
            x[1] += float(r.get('Value') or 0)
    out = []
    for (ym, iso, pi), (kg, val) in sorted(agg.items()):
        if kg <= 0 and val <= 0:
            continue
        e = to_eur(val, ym, 'GBP', fx)
        out.append([ym, key, iso, pi, round(kg / 1000, 3), round(val / 1000, 2), round(e / 1000, 2) if e is not None else None])
    t0 = sum(r[4] for r in out if r[3] == 0)
    if t0:
        print(f'  {key} : entier frais, prix moyen {sum(r[6] or 0 for r in out if r[3] == 0) / t0:.2f} EUR/kg')
    return out, {'source': src['name'], 'url': base + '/OTS', 'currency': 'GBP',
                 'last': max((r[0] for r in out), default=None), 'first': min((r[0] for r in out), default=None)}


def fetch_source(key, src, to_iso, fx):
    meta = url = None
    urls = list(src['urls'])
    if src.get('folder'):
        st, raw = http(src['folder'])
        try:
            best = None
            for it in json.loads(raw) if st == 200 else []:
                m = re.search(src['pick'], it.get('text', ''), re.I)
                if it.get('type') == 't' and m and (best is None or int(m.group(2)) > best[0]):
                    best = (int(m.group(2)), it['id'])
            if best:
                u = src['folder'] + '/' + best[1]
                print(f'  {key} : table la plus recente du dossier : {best[1]} (jusqu\'a {best[0]})')
                urls = [u] + [x for x in urls if x != u]
        except ValueError:
            pass
    for u in urls:
        st, raw = http(u)
        if st == 200:
            try:
                meta, url = json.loads(raw), u
                break
            except ValueError:
                pass
        print(f'  {key} : {u} -> {st}')
    if not meta:
        raise RuntimeError(f'{key} : description de table introuvable')
    os.makedirs(DBG, exist_ok=True)
    json.dump(meta, open(os.path.join(DBG, f'meta_{key}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    dims = detect(meta, set(src['codes']))
    print(f'  {key} : dimensions reconnues :', {k: (v['code'] if isinstance(v, dict) else [x['code'] for x in v]) for k, v in dims.items()})
    for need in ('product', 'time', 'country'):
        if need not in dims:
            raise RuntimeError(f'{key} : dimension "{need}" non reconnue ({[v["code"] for v in meta["variables"]]})')
    pv, tv, cv = dims['product'], dims['time'], dims['country']
    texts = pv.get('valueTexts', pv['values'])
    prod = {}                                   # valeur de la table -> indice de forme
    for x, t in zip(pv['values'], texts):
        c = code_of(x) or code_of(t)
        if c in src['codes']:
            prod[x] = src['codes'][c]
    print(f'  {key} : produits trouves : {sorted(prod)}')
    q_unit = v_unit = None
    query_base = [{'code': pv['code'], 'selection': {'filter': 'item', 'values': sorted(prod)}},
                  {'code': cv['code'], 'selection': {'filter': 'all', 'values': ['*']}}]
    if 'unit' in dims:
        q_unit, v_unit = pick_units(dims['unit'])
        print(f'  {key} : unites : quantite={q_unit}, valeur={v_unit}')
        query_base.append({'code': dims['unit']['code'], 'selection': {'filter': 'item', 'values': [u for u in (q_unit, v_unit) if u]}})
    if 'flow' in dims:
        fv = dims['flow']
        exp = [x for x, t in zip(fv['values'], fv.get('valueTexts', fv['values'])) if re.search(r'xport|útflutn|utflutn', t, re.I)]
        query_base.append({'code': fv['code'], 'selection': {'filter': 'item', 'values': exp[:1] or fv['values'][-1:]}})
    for ov in dims.get('other', []):
        # dimension inconnue : on prend la premiere valeur (souvent le total) et on le signale
        print(f'  {key} : dimension non reconnue {ov["code"]} ({ov["text"]}) -> valeur {ov["values"][0]}')
        query_base.append({'code': ov['code'], 'selection': {'filter': 'item', 'values': ov['values'][:1]}})
    ctext = dict(zip(cv['values'], cv.get('valueTexts', cv['values'])))
    times = tv['values']
    agg = {}
    unknown = set()
    for i in range(0, len(times), 6):
        chunk = times[i:i + 6]
        body = {'query': query_base + [{'code': tv['code'], 'selection': {'filter': 'item', 'values': chunk}}],
                'response': {'format': 'json'}}
        st, raw = http(url, body)
        if st != 200:
            raise RuntimeError(f'{key} : requete {chunk[0]}-{chunk[-1]} -> {st} {raw[:200]!r}')
        j = json.loads(raw)
        cols = [c['code'] for c in j['columns']]
        for d in j['data']:
            k = dict(zip(cols, d['key']))
            vals = d['values']
            m = re.match(r'(\d{4})M(\d{2})', k[tv['code']])
            if not m:
                continue
            ym = int(m.group(1)) * 100 + int(m.group(2))
            iso = to_iso(k[cv['code']], ctext.get(k[cv['code']]))
            if not iso:
                unknown.add(ctext.get(k[cv['code']], k[cv['code']]))
                continue
            if iso in ('IS', 'FO') and iso == key:
                continue
            pi = prod.get(k[pv['code']])
            num = lambda s: float(s) if s not in (None, '', '.', '..', '-', '…') else 0.0
            if 'unit' in dims:
                u = k[dims['unit']['code']]
                qty, val = (num(vals[0]), 0.0) if u == q_unit else (0.0, num(vals[0]))
            else:
                # sans dimension d'unite, les mesures sont des colonnes de type 'c'
                cc = [c for c in j['columns'] if c.get('type') == 'c']
                qty = val = 0.0
                for c, s in zip(cc, vals):
                    if re.search(r'kg|kíló|kilo|nøgd|quantity', c['text'], re.I):
                        qty = num(s)
                    else:
                        val = num(s)
            x = agg.setdefault((ym, iso, pi), [0.0, 0.0])
            x[0] += qty
            x[1] += val
        time.sleep(1)
    if unknown:
        print(f'  {key} : pays non reconnus (ignores) : {sorted(unknown)[:30]}')
    # unite monetaire : on suppose des couronnes (pas des milliers) ; controle par le prix au kilo
    rows = []
    for (ym, iso, pi), (kg, val) in sorted(agg.items()):
        if kg <= 0 and val <= 0:
            continue
        e = to_eur(val, ym, src['currency'], fx)
        keur = round(e / 1000, 2) if e is not None else None
        rows.append([ym, key, iso, pi, round(kg / 1000, 3), round(val / 1000, 2), keur])
    tot_kg = sum(r[4] for r in rows if r[3] == 0)
    tot_v = sum(r[6] or 0 for r in rows if r[3] == 0)
    if tot_kg:
        print(f'  {key} : entier frais, prix moyen {tot_v / tot_kg:.2f} EUR/kg (controle de l\'unite monetaire)')
    return rows, {'source': src['name'], 'url': url, 'currency': src['currency'],
                  'last': max((r[0] for r in rows), default=None), 'first': min((r[0] for r in rows), default=None)}


def iso3_map():
    try:
        import pycountry
        return lambda a3: (pycountry.countries.get(alpha_3=a3).alpha_2 if a3 and pycountry.countries.get(alpha_3=a3) else None)
    except ImportError:
        return lambda a3: None


def fetch_comtrade(key, src, to_iso, fx):
    """Chili, Canada, Australie : ONU Comtrade, API publique 'preview' (sans cle, 500 lignes par appel), un appel par mois."""
    base = 'https://comtradeapi.un.org/public/v1/preview/C/M/HS'
    a3 = iso3_map()
    codes = ','.join(src['codes'])
    os.makedirs(DBG, exist_ok=True)
    today = dt.date.today()
    months, y, m = [], 2023, 1
    while y * 100 + m <= today.year * 100 + today.month:
        months.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    agg, empty_tail, sample_done = {}, 0, False
    for ym in months:
        url = f'{base}?reporterCode={src["reporter"]}&period={ym}&cmdCode={codes}&flowCode=X&includeDesc=true'
        st, raw = http(url)
        if st == 429:
            time.sleep(30)
            st, raw = http(url)
        if st != 200:
            print(f'  {key} : {ym} -> {st} {raw[:150]!r}')
            continue
        j = json.loads(raw)
        rows = j.get('data') or []
        if not sample_done and rows:
            json.dump(rows[:20], open(os.path.join(DBG, f'comtrade_{key.lower()}_sample.json'), 'w'), indent=0, ensure_ascii=False)
            sample_done = True
        if len(rows) >= 500:
            print(f'  {key} : {ym} : 500 lignes, la limite de la preview est peut-etre atteinte')
        n = 0
        for r in rows:
            pc = r.get('partnerCode')
            if pc in (0, None) or str(r.get('flowCode')) != 'X':
                continue
            iso = a3(r.get('partnerISO')) or to_iso('', r.get('partnerDesc'))
            if not iso:
                continue
            pi = src['codes'].get(str(r.get('cmdCode')))
            if pi is None:
                continue
            kg = float(r.get('netWgt') or 0)
            usd = float(r.get('fobvalue') or r.get('primaryValue') or 0)
            x = agg.setdefault((ym, iso, pi), [0.0, 0.0])
            x[0] += kg
            x[1] += usd
            n += 1
        print(f'  {key} : {ym} : {n} lignes')
        time.sleep(2)
    out = []
    for (ym, iso, pi), (kg, val) in sorted(agg.items()):
        if kg <= 0 and val <= 0:
            continue
        e = to_eur(val, ym, 'USD', fx)
        out.append([ym, key, iso, pi, round(kg / 1000, 3), round(val / 1000, 2), round(e / 1000, 2) if e is not None else None])
    t0 = sum(r[4] for r in out if r[3] == 0)
    if t0:
        print(f'  {key} : entier frais, prix moyen {sum(r[6] or 0 for r in out if r[3] == 0) / t0:.2f} EUR/kg')
    return out, {'source': src['name'], 'url': base, 'currency': 'USD',
                 'last': max((r[0] for r in out), default=None), 'first': min((r[0] for r in out), default=None)}


US_OUT = os.path.join(ROOT, 'data', 'us_imports.json')
US_HS6 = {'030214': 0, '030313': 1, '030441': 2, '030481': 3, '030541': 5, '160411': 6}


def fetch_us_imports(to_iso, fx):
    """Importations des Etats-Unis (US Census Bureau, API publique) par pays d'origine et par code
    HTS a 10 chiffres. Pour les filets, le fume et le prepare, on ne garde que les lignes dont le
    libelle parle de saumon atlantique (le Pacifique est a part). Valeur en douane (hors fret et
    assurance, comparable au FOB), droits calcules et frais d'acheminement, en dollars."""
    base = 'https://api.census.gov/data/timeseries/intltrade/imports/hs'
    fields = 'CTY_CODE,CTY_NAME,I_COMMODITY,I_COMMODITY_SDESC,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1,CAL_DUT_MO,GEN_CHA_MO'
    key = os.environ.get('CENSUS_API_KEY', '')
    agg, kept, dropped, attempts = {}, set(), set(), []
    for hs6, pi in US_HS6.items():
        rows = None
        # plusieurs formes de requete, de la plus detaillee a la plus simple ; chaque essai est
        # enregistre dans data/national_probe/us_census_attempts.json pour le depannage
        minimal = 'CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1'
        tries = [('HS10', hs6 + '*', fields, 'from+2023-01'), ('HS10', hs6 + '*', minimal, 'from+2023-01'),
                 ('HS6', hs6, fields, 'from+2023-01'), ('HS6', hs6, minimal, 'from+2023-01')]
        for lvl, code, flds, tm in tries:
            url = f'{base}?get={flds}&COMM_LVL={lvl}&I_COMMODITY={code}&time={tm}'
            st, raw = http(url + (f'&key={key}' if key else ''))
            attempts.append({'hs6': hs6, 'url': url, 'status': st, 'head': raw[:400].decode('utf-8', 'replace')})
            if b'Missing Key' in raw[:2000] or b'Invalid Key' in raw[:2000]:
                json.dump(attempts, open(os.path.join(DBG, 'us_census_attempts.json'), 'w'), indent=1, ensure_ascii=False)
                raise RuntimeError('le US Census exige une cle d\'API : creer une cle gratuite sur https://api.census.gov/data/key_signup.html '
                                   'et l\'enregistrer dans les secrets GitHub sous le nom CENSUS_API_KEY' + (' (la cle actuelle est refusee)' if key else ''))
            if st == 200 and raw.strip():
                try:
                    j = json.loads(raw)
                    rows = [dict(zip(j[0], r)) for r in j[1:]]
                    print(f'  US : {hs6} ({lvl}, {"complet" if flds == fields else "minimal"}) -> {len(rows)} lignes')
                    break
                except ValueError:
                    pass
            print(f'  US : {hs6} ({lvl}) -> {st} {raw[:200]!r}')
        json.dump(attempts, open(os.path.join(DBG, 'us_census_attempts.json'), 'w'), indent=1, ensure_ascii=False)
        if not rows:
            raise RuntimeError(f'aucune donnee pour {hs6}')
        if hs6 == '030441':
            json.dump(rows[:40], open(os.path.join(DBG, 'us_census_sample.json'), 'w'), indent=0, ensure_ascii=False)
        for r in rows:
            desc = (r.get('I_COMMODITY_SDESC') or '').upper()
            if pi >= 2 and len(r.get('I_COMMODITY', '')) == 10:
                # filets, fume, prepare : uniquement le saumon atlantique (libelles HTS)
                if 'ATLANTIC' not in desc or re.search(r'PACIFIC|SOCKEYE|COHO|CHINOOK|CHUM|PINK|SILVER', desc):
                    dropped.add(r['I_COMMODITY'] + ' ' + desc)
                    continue
                kept.add(r['I_COMMODITY'] + ' ' + desc)
            cc = r.get('CTY_CODE', '')
            if not re.fullmatch(r'\d{4}', cc) or cc.startswith('0') or cc[0] == '-':
                continue                                   # totaux et regroupements
            iso = to_iso('', (r.get('CTY_NAME') or '').title())
            if not iso:
                continue
            t = r.get('time', '')
            mm = re.match(r'(\d{4})-(\d{2})', t)
            if not mm:
                continue
            ym = int(mm.group(1)) * 100 + int(mm.group(2))
            num = lambda k: float(r.get(k) or 0)
            kg = num('GEN_QY1_MO') if (r.get('UNIT_QY1') or 'KG').upper().startswith('KG') else 0.0
            x = agg.setdefault((ym, iso, pi), [0.0, 0.0, 0.0, 0.0])
            x[0] += kg
            x[1] += num('GEN_VAL_MO')
            x[2] += num('CAL_DUT_MO')
            x[3] += num('GEN_CHA_MO')
        time.sleep(1)
    print(f'  US : codes HTS gardes : {sorted(kept)}')
    print(f'  US : codes HTS ecartes (Pacifique) : {sorted(dropped)}')
    out = []
    for (ym, iso, pi), (kg, val, duty, cha) in sorted(agg.items()):
        if kg <= 0 and val <= 0:
            continue
        e = to_eur(val, ym, 'USD', fx)
        out.append([ym, iso, pi, round(kg / 1000, 3), round(val / 1000, 2), round(e / 1000, 2) if e is not None else None,
                    round(duty / 1000, 2), round(cha / 1000, 2)])
    if not out:
        raise RuntimeError('aucune ligne')
    meta = {'fetched': dt.date.today().isoformat(), 'source': 'US Census Bureau, international trade API (imports by HTS10 and country)',
            'last': max(r[0] for r in out), 'first': min(r[0] for r in out), 'kept_codes': sorted(kept), 'dropped_codes': sorted(dropped),
            'cols': ['ym', 'origin', 'form', 'tonnes', 'k_usd_customs_value', 'k_eur', 'k_usd_duty', 'k_usd_charges']}
    io.open(US_OUT, 'w', encoding='utf-8').write(json.dumps({'meta': meta, 'rows': out}, ensure_ascii=False, separators=(',', ':')))
    print(f'  US : {len(out)} lignes, {meta["first"]} -> {meta["last"]}')


CN_OUT = os.path.join(ROOT, 'data', 'cn_imports.json')
CN_HS6 = {'030214': 0, '030313': 1, '030441': 2, '030481': 3, '030541': 5, '160411': 6}
CN_REPORTERS = {'CN': 156, 'HK': 344}


def fetch_cn_imports(to_iso, fx):
    """Importations de la Chine et de Hong Kong par pays d'origine (ONU Comtrade, donnees declarees
    par chaque pays, SH6, mensuel). Valeur CIF a l'arrivee, en dollars."""
    base = 'https://comtradeapi.un.org/public/v1/preview/C/M/HS'
    a3 = iso3_map()
    codes = ','.join(CN_HS6)
    today = dt.date.today()
    months, y, m = [], 2023, 1
    while y * 100 + m <= today.year * 100 + today.month:
        months.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    agg, sample = {}, False
    for rep, rcode in CN_REPORTERS.items():
        for ym in months:
            url = f'{base}?reporterCode={rcode}&period={ym}&cmdCode={codes}&flowCode=M&includeDesc=true'
            st, raw = http(url)
            if st == 429:
                time.sleep(30)
                st, raw = http(url)
            if st != 200:
                print(f'  {rep} : {ym} -> {st} {raw[:150]!r}')
                continue
            rows = json.loads(raw).get('data') or []
            if rows and not sample:
                json.dump(rows[:20], open(os.path.join(DBG, 'comtrade_cn_imports_sample.json'), 'w'), indent=0, ensure_ascii=False)
                sample = True
            if len(rows) >= 500:
                print(f'  {rep} : {ym} : 500 lignes, limite de la preview peut-etre atteinte')
            n = 0
            for r in rows:
                if r.get('partnerCode') in (0, None) or str(r.get('flowCode')) != 'M':
                    continue
                iso = a3(r.get('partnerISO')) or to_iso('', r.get('partnerDesc'))
                pi = CN_HS6.get(str(r.get('cmdCode')))
                if not iso or pi is None:
                    continue
                x = agg.setdefault((ym, iso, pi, rep), [0.0, 0.0])
                x[0] += float(r.get('netWgt') or 0)
                x[1] += float(r.get('cifvalue') or r.get('primaryValue') or 0)
                n += 1
            if n:
                print(f'  {rep} : {ym} : {n} lignes')
            time.sleep(2)
    out = []
    for (ym, iso, pi, rep), (kg, val) in sorted(agg.items()):
        if kg <= 0 and val <= 0:
            continue
        e = to_eur(val, ym, 'USD', fx)
        out.append([ym, iso, pi, round(kg / 1000, 3), round(val / 1000, 2), round(e / 1000, 2) if e is not None else None, rep])
    if not out:
        raise RuntimeError('aucune ligne')
    meta = {'fetched': dt.date.today().isoformat(), 'source': 'UN Comtrade, imports reported by China and Hong Kong (HS6, monthly, CIF in USD)',
            'last': max(r[0] for r in out), 'first': min(r[0] for r in out),
            'last_by_reporter': {rp: max((r[0] for r in out if r[6] == rp), default=None) for rp in CN_REPORTERS},
            'cols': ['ym', 'origin', 'form', 'tonnes', 'k_usd_cif', 'k_eur', 'reporter']}
    io.open(CN_OUT, 'w', encoding='utf-8').write(json.dumps({'meta': meta, 'rows': out}, ensure_ascii=False, separators=(',', ':')))
    print(f'  CN/HK : {len(out)} lignes, {meta["first"]} -> {meta["last"]} {meta["last_by_reporter"]}')


def main():
    to_iso = iso_map()
    fx = {c: eur_rates(c) for c in ('ISK', 'GBP', 'NOK', 'USD')}
    old = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {'meta': {}, 'rows': []}
    rows, meta, failed, failed_opt = [], {}, [], []
    for key, src in SOURCES.items():
        print(f'{key} :')
        try:
            r, m = {'hmrc': fetch_hmrc, 'comtrade': fetch_comtrade}.get(src.get('kind'), fetch_source)(key, src, to_iso, fx)
            if not r:
                raise RuntimeError('aucune ligne')
            # les mois que la nouvelle table ne couvre plus (table islandaise glissante) restent
            keep = [x for x in old['rows'] if x[1] == key and x[0] < m['first']]
            if keep:
                print(f'  {key} : {len(keep)} lignes plus anciennes conservees du fichier precedent')
                m['first'] = min(x[0] for x in keep)
            rows += keep + r
            meta[key] = m
            print(f'  {key} : {len(r)} lignes, {m["first"]} -> {m["last"]}')
        except Exception as e:
            print(f'  ECHEC {key} : {e}' + (' (source optionnelle : la mise a jour continue)' if src.get('optional') else ''))
            (failed_opt if src.get('optional') else failed).append(key)
            rows += [x for x in old['rows'] if x[1] == key]
            if key in old.get('meta', {}):
                meta[key] = old['meta'][key]
    # taux de change (unites pour 1 EUR) gardes pour le tableau de bord (conversion des NOK norvegiennes)
    fxm = {c: {str(k): v for k, v in r.items()} for c, r in fx.items() if r}
    if not fxm and old.get('meta', {}).get('fx'):
        fxm = old['meta']['fx']
    out = {'meta': {'fetched': dt.date.today().isoformat(), 'sources': meta, 'failed': failed, 'failed_optional': failed_opt, 'fx': fxm,
                    'cols': ['ym', 'origin', 'destination', 'form', 'tonnes', 'k_local', 'k_eur'],
                    'forms': {'0': 'Fresh whole', '1': 'Frozen whole', '2': 'Fresh fillets', '3': 'Frozen fillets',
                              '5': 'Smoked', '6': 'Prepared / preserved'}},
           'rows': rows}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'{len(rows)} lignes ecrites, echecs : {failed or "aucun"}')
    print('Importations de la Chine et de Hong Kong (UN Comtrade) :')
    try:
        os.makedirs(DBG, exist_ok=True)
        fetch_cn_imports(to_iso, fx)
    except Exception as e:
        print(f'  ECHEC CN : {e}')
        failed.append('CN_IMP')
    print('Importations des Etats-Unis (US Census) :')
    try:
        os.makedirs(DBG, exist_ok=True)
        fetch_us_imports(to_iso, fx)
    except Exception as e:
        print(f'  ECHEC US : {e}')
        failed.append('US_IMP')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
