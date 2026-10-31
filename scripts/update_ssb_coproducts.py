#!/usr/bin/env python3
"""
Co-produits du saumon exportes par la Norvege (SSB, Statistikkbanken, table 08799, mensuel) :
tetes, aretes (rygger / ryggbein), queues et autres biproduits comestibles, congeles.

La nomenclature norvegienne ne separe PAS les tetes des aretes : tout passe sous un seul
code, 'spiselige biprodukter av oppdrettet atlanterhavslaks, fryst' :
    03039901  depuis 2017
    03031312  2012-2016 (meme libelle, ancien code)
Seuls ces codes sont telecharges. Les autres codes dont le libelle evoque des abats ou du saumon
sont seulement listes dans data/national_probe/ssb_08799_coproducts.json, pour verification.

Ecrit data.json['ssb_coproducts'] :
    meta.products  = {code: libelle}      (ordre = index utilise dans les lignes)
    meta.countries = {iso: nom}
    rows = [[annee*100+mois, index produit, iso, kg, nok], ...]   (kg = poids produit, nok = valeur FOB)

Tout l'historique depuis START est retelecharge a chaque passage (une dizaine de requetes) :
les revisions de SSB sont donc toujours prises en compte.
Nouvelle source (octobre 2026) : un echec n'empeche pas le reste de la mise a jour.
"""
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
DBG = os.path.join(ROOT, 'data', 'national_probe')
TABLE = '08799'
BASE = f'https://data.ssb.no/api/pxwebapi/v2/tables/{TABLE}'
KEY = 'ssb_coproducts'
START = 201501
CHUNK = 12
PAUSE = 1.0
# codes connus (biproduits comestibles de saumon d'elevage, congeles)
KNOWN = {'03039901': 'Edible by-products of farmed Atlantic salmon, frozen (heads, frames, tails...)',
         '03031312': 'Edible by-products of farmed Atlantic salmon, frozen (code used 2012-2016)'}


def http_json(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print("=== Reponse d'erreur de l'API SSB ===")
        print(e.read().decode('utf-8', errors='replace')[:2000])
        raise


def cats(meta, dim):
    idx = meta['dimension'][dim]['category']['index']
    return sorted(idx, key=lambda c: idx[c]) if isinstance(idx, dict) else list(idx)


def label(meta, dim, code):
    return (meta['dimension'][dim]['category'].get('label') or {}).get(code, code)


def parse_jsonstat2(data):
    dims = data['id']
    sizes = [data['size'][i] for i in range(len(dims))]
    cs, labels = [], {}
    for d in dims:
        cat = data['dimension'][d]['category']
        idx = cat['index']
        cs.append([c for c, _ in sorted(idx.items(), key=lambda kv: kv[1])] if isinstance(idx, dict) else list(idx))
        labels[d] = cat.get('label', {})
    strides = [1] * len(dims)
    for i in range(len(dims) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]
    rows = []
    for flat, v in enumerate(data['value']):
        if v is None:
            continue
        rem, row = flat, {}
        for i, d in enumerate(dims):
            row[d] = cs[i][rem // strides[i]]
            rem %= strides[i]
        row['value'] = v
        rows.append(row)
    return rows, labels


def is_coproduct(lab):
    l = lab.lower()
    salmon = any(w in l for w in ('salmon', 'salmo salar', 'laks'))
    part = any(w in l for w in ('by-product', 'byproduct', 'biprodukt', 'offal', 'heads', 'hoder', 'backbone', 'frames', 'rygg'))
    return salmon and part


def main():
    os.makedirs(DBG, exist_ok=True)
    meta = http_json(f'{BASE}/metadata?lang=en&outputFormat=json-stat2')
    vk = cats(meta, 'Varekoder')
    # seuls les codes connus sont telecharges : les libelles anglais de SSB sont generiques (« subgroup of 030399 ... »)
    # et une recherche par mots-cles ramenait des codes sans rapport (chair de poisson hors salmonides, poisson fume...).
    # Les autres candidats sont seulement listes dans le fichier de depannage, pour verification manuelle.
    found = {c: label(meta, 'Varekoder', c) for c in vk if c.split('_')[0] in KNOWN}
    cand = {c: label(meta, 'Varekoder', c) for c in vk if c not in found and is_coproduct(label(meta, 'Varekoder', c))}
    json.dump({'downloaded': found, 'candidates_not_downloaded': cand}, io.open(os.path.join(DBG, 'ssb_08799_coproducts.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(f'  codes retenus : {found}')
    if not found:
        raise RuntimeError('aucun code de co-produit dans la table')
    api_codes = sorted(found)
    tids = [t for t in cats(meta, 'Tid') if len(t) == 7 and t[4] == 'M' and int(t[:4]) * 100 + int(t[5:]) >= START]
    if not tids:
        raise RuntimeError('aucun mois dans les metadonnees')
    print(f'  {len(tids)} mois, {tids[0]} -> {tids[-1]}')
    cells, names = {}, {}
    for i in range(0, len(tids), CHUNK):
        part = tids[i:i + CHUNK]
        url = (f'{BASE}/data?lang=en&valueCodes[Varekoder]={",".join(api_codes)}&valueCodes[ImpEks]=2&valueCodes[Land]=*'
               f'&valueCodes[ContentsCode]=Mengde1,Verdi&valueCodes[Tid]={",".join(part)}&outputFormat=json-stat2')
        rows, labels = parse_jsonstat2(http_json(url))
        names.update(labels.get('Land', {}))
        for r in rows:
            if not r['value']:
                continue
            k = int(r['Tid'][:4]) * 100 + int(r['Tid'][5:])
            slot = cells.setdefault((k, r['Varekoder'].split('_')[0], r['Land']), [0, 0])
            slot[0 if r['ContentsCode'] == 'Mengde1' else 1] += r['value']
        print(f'  {part[0]} -> {part[-1]} : {len(cells)} cellules')
        time.sleep(PAUSE)
    if not cells:
        raise RuntimeError('aucune donnee')
    # un code par produit, dans un ordre stable : les codes connus d'abord
    base = []
    for c in list(KNOWN) + sorted({c.split('_')[0] for c in found}):
        if c not in base and any(code == c for (_, code, _) in cells):
            base.append(c)
    prods = {c: next((found[x] for x in found if x.split('_')[0] == c), KNOWN.get(c, c)) for c in base}
    rows = sorted([[k, base.index(code), iso, int(round(kg)), int(round(nok))]
                   for (k, code, iso), (kg, nok) in cells.items() if code in base and (kg or nok)])
    countries = {iso: names.get(iso, iso) for iso in sorted({r[2] for r in rows})}
    data = json.load(io.open(DATA, encoding='utf-8'))
    data[KEY] = {'meta': {'fetched': dt.date.today().isoformat(), 'table': TABLE,
                          'source': 'SSB Statistikkbanken table 08799, exports by commodity number and country',
                          'products': prods, 'known': KNOWN, 'countries': countries,
                          'cols': ['k', 'hs', 'iso', 'kg', 'nok'], 'first': rows[0][0], 'last': rows[-1][0]},
                 'rows': rows}
    io.open(DATA, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    tot = {}
    for k, h, iso, kg, nok in rows:
        tot[k // 100] = tot.get(k // 100, 0) + kg
    print(f'  {len(rows)} lignes ; tonnes par annee : ' + ', '.join(f'{y}: {v / 1000:,.0f}' for y, v in sorted(tot.items())))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'ECHEC SSB co-produits : {e.__class__.__name__}: {e}')
        sys.exit(1)
