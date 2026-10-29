#!/usr/bin/env python3
"""
Exportations hebdomadaires de saumon d'elevage (SSB, Statistikkbanken, table 03024) :
volume (tonnes) et prix a l'export (NOK/kg) par semaine, saumon frais et congele.
Ajoute la cle 'ssb_weekly' a data/data.json.

C'est la seule source publique de VOLUMES hebdomadaires : Akvafakta ne donne que la
repartition par calibre (en parts) et les prix. Multiplies ensemble, ils donnent une
estimation des tonnes de gros calibre exportees chaque semaine.

API publique PxWebApi v2, sans cle. Les dimensions et codes de la table sont lus dans
ses metadonnees plutot que supposes ; elles sont aussi enregistrees dans
data/national_probe/ssb_03024_meta.json pour le depannage.

Format :
  ssb_weekly.meta.products = [libelle de chaque produit, dans l'ordre de l'index]
  ssb_weekly.rows = [[annee*100+semaine, index produit, tonnes, NOK/kg], ...]

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
TABLE = '03024'
BASE = f'https://data.ssb.no/api/pxwebapi/v2/tables/{TABLE}'
KEY = 'ssb_weekly'
START_YEAR = 2018
CHUNK = 104          # semaines par requete
PAUSE = 1.0


def http_json(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print("=== Reponse d'erreur de l'API SSB ===")
        print(body[:2000])
        raise


def cats(meta, dim):
    idx = meta['dimension'][dim]['category']['index']
    return sorted(idx, key=lambda c: idx[c]) if isinstance(idx, dict) else list(idx)


def label(meta, dim, code):
    return (meta['dimension'][dim]['category'].get('label') or {}).get(code, code)


def parse_jsonstat2(data):
    dims = data['id']
    sizes = [data['size'][i] for i in range(len(dims))]
    cs = []
    for d in dims:
        idx = data['dimension'][d]['category']['index']
        cs.append([c for c, _ in sorted(idx.items(), key=lambda kv: kv[1])] if isinstance(idx, dict) else list(idx))
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
    return rows


def week_key(tid):
    """'2026U43' -> 202643"""
    return int(tid[:4]) * 100 + int(tid[5:])


def main():
    os.makedirs(DBG, exist_ok=True)
    meta = http_json(f'{BASE}/metadata?lang=en&outputFormat=json-stat2')
    dims = meta['id']
    json.dump({d: {'label': meta['dimension'][d].get('label'),
                   'categories': {c: label(meta, d, c) for c in cats(meta, d)[:60]}} for d in dims},
              io.open(os.path.join(DBG, 'ssb_03024_meta.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    tdim = 'Tid' if 'Tid' in dims else dims[-1]
    cdim = 'ContentsCode' if 'ContentsCode' in dims else None
    if not cdim:
        raise RuntimeError(f'dimension ContentsCode introuvable : {dims}')
    others = [d for d in dims if d not in (tdim, cdim)]
    print(f'  dimensions : {dims}')
    # contenus : poids et prix, reperes par leur libelle
    contents = cats(meta, cdim)
    lab = {c: label(meta, cdim, c).lower() for c in contents}
    c_w = next((c for c in contents if any(w in lab[c] for w in ('weight', 'tonn', 'vekt', 'volume', 'quantity'))), None)
    c_p = next((c for c in contents if any(w in lab[c] for w in ('price', 'pris', 'nok'))), None)
    print(f'  contenus : poids = {c_w} ({lab.get(c_w)}), prix = {c_p} ({lab.get(c_p)})')
    if not c_w:
        raise RuntimeError(f'contenu "poids" introuvable parmi {lab}')
    weeks = [t for t in cats(meta, tdim) if len(t) == 7 and t[4] in 'UW' and int(t[:4]) >= START_YEAR]
    if not weeks:
        raise RuntimeError('aucune semaine dans les metadonnees')
    print(f'  {len(weeks)} semaines, {weeks[0]} -> {weeks[-1]}')
    # produits : toutes les categories des autres dimensions (frais / congele)
    prod_keys, prod_lab = [], {}
    cells = {}
    for i in range(0, len(weeks), CHUNK):
        part = weeks[i:i + CHUNK]
        url = (f'{BASE}/data?lang=en&outputFormat=json-stat2'
               + ''.join(f'&valueCodes[{d}]=*' for d in others)
               + f'&valueCodes[{cdim}]={",".join(c for c in (c_w, c_p) if c)}'
               + f'&valueCodes[{tdim}]={",".join(part)}')
        for r in parse_jsonstat2(http_json(url)):
            pk = tuple(r[d] for d in others)
            if pk not in prod_lab:
                prod_lab[pk] = ' / '.join(label(meta, d, r[d]) for d in others)
                prod_keys.append(pk)
            x = cells.setdefault((week_key(r[tdim]), pk), [None, None])
            x[0 if r[cdim] == c_w else 1] = r['value']
        print(f'  {part[0]} -> {part[-1]} : {len(cells)} cellules')
        time.sleep(PAUSE)
    rows = [[k, prod_keys.index(pk), round(v[0], 1) if v[0] is not None else None, round(v[1], 2) if v[1] is not None else None]
            for (k, pk), v in sorted(cells.items()) if v[0] is not None]
    if not rows:
        raise RuntimeError('aucune ligne')
    data = json.load(io.open(DATA, encoding='utf-8'))
    data[KEY] = {'meta': {'fetched': dt.date.today().isoformat(), 'table': TABLE,
                          'source': 'SSB Statistikkbanken table 03024, weekly exports of farmed salmon (volume, export price)',
                          'products': [prod_lab[pk] for pk in prod_keys], 'weight_label': lab.get(c_w), 'price_label': lab.get(c_p),
                          'first': rows[0][0], 'last': rows[-1][0], 'cols': ['yw', 'product', 'weight', 'nok_per_kg']},
                 'rows': rows}
    io.open(DATA, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f'  {len(rows)} lignes, produits : {data[KEY]["meta"]["products"]}, unite : {lab.get(c_w)}')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'ECHEC SSB hebdomadaire : {e.__class__.__name__}: {e}')
        sys.exit(1)
