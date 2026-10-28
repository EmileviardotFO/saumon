#!/usr/bin/env python3
"""
Exportations de saumon des Iles Feroe et de l'Islande, par pays de destination
et par mois, depuis les statistiques nationales (API PxWeb) :

  - Feroe   : Hagstova Foroya, table UH01046 "Inn- og utflutningur skiftur a
              vorunummar og land" (uh_cn_t.px), mensuelle depuis 2023, CN8.
  - Islande : Hagstofa Islands, table UTA02801 "Utflutningur eftir
              tollskrarnumerum 2024-2026, kafli 1-40", numeros tarifaires
              islandais a 8 chiffres (saumon d'elevage atlantique separe).

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
        # numeros islandais : saumon atlantique d'elevage (et filets congeles de saumon atlantique)
        'codes': {'03021401': 0, '03031301': 1, '03044111': 2, '03048101': 3, '03048110': 3, '03048120': 3,
                  '03054100': 5, '16041100': 6, '16041101': 6, '16041109': 6},
    },
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


def isk_rates():
    """Taux moyens mensuels ISK pour 1 EUR (Eurostat ert_bil_eur_m)."""
    url = ('https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/ert_bil_eur_m'
           '?format=JSON&lang=EN&currency=ISK&statinfo=AVG&sinceTimePeriod=2022-01')
    st, raw = http(url)
    out = {}
    if st != 200:
        print(f'  taux ISK indisponibles ({st})')
        return out
    j = json.loads(raw)
    idx = j['dimension']['time']['category']['index']
    for t, i in idx.items():
        v = j['value'].get(str(i))
        if v:
            y, m = t.split('-') if '-' in t else t.split('M')
            out[int(y) * 100 + int(m)] = float(v)
    print(f'  {len(out)} taux ISK mensuels')
    return out


def fetch_source(key, src, to_iso, fx):
    meta = url = None
    for u in src['urls']:
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
        rate = DKK_PER_EUR if src['currency'] == 'DKK' else fx.get(ym) or (fx[max(fx)] if fx else None)
        keur = round(val / rate / 1000, 2) if rate else None
        rows.append([ym, key, iso, pi, round(kg / 1000, 3), round(val / 1000, 2), keur])
    tot_kg = sum(r[4] for r in rows if r[3] == 0)
    tot_v = sum(r[6] or 0 for r in rows if r[3] == 0)
    if tot_kg:
        print(f'  {key} : entier frais, prix moyen {tot_v / tot_kg:.2f} EUR/kg (controle de l\'unite monetaire)')
    return rows, {'source': src['name'], 'url': url, 'currency': src['currency'],
                  'last': max((r[0] for r in rows), default=None), 'first': min((r[0] for r in rows), default=None)}


def main():
    to_iso = iso_map()
    fx = isk_rates()
    old = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {'meta': {}, 'rows': []}
    rows, meta, failed = [], {}, []
    for key, src in SOURCES.items():
        print(f'{key} :')
        try:
            r, m = fetch_source(key, src, to_iso, fx)
            if not r:
                raise RuntimeError('aucune ligne')
            rows += r
            meta[key] = m
            print(f'  {key} : {len(r)} lignes, {m["first"]} -> {m["last"]}')
        except Exception as e:
            print(f'  ECHEC {key} : {e}')
            failed.append(key)
            rows += [x for x in old['rows'] if x[1] == key]
            if key in old.get('meta', {}):
                meta[key] = old['meta'][key]
    out = {'meta': {'fetched': dt.date.today().isoformat(), 'sources': meta, 'failed': failed,
                    'cols': ['ym', 'origin', 'destination', 'form', 'tonnes', 'k_local', 'k_eur'],
                    'forms': {'0': 'Fresh whole', '1': 'Frozen whole', '2': 'Fresh fillets', '3': 'Frozen fillets',
                              '5': 'Smoked', '6': 'Prepared / preserved'}},
           'rows': rows}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'{len(rows)} lignes ecrites, echecs : {failed or "aucun"}')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
