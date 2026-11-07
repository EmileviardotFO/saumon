#!/usr/bin/env python3
"""
data/canada_trade.json : exportations canadiennes de saumon d'elevage, chaque mois, par PROVINCE D'ORIGINE,
produit, pays de destination (et Etat americain), d'apres la base CIMT de Statistique Canada.

Source : Canadian International Merchandise Trade (CIMT), fichiers annuels "Dom_Exp" (exportations nationales,
c.-a-d. produits au Canada, hors reexportations) publies en donnees ouvertes :
  https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_Dom_Exp_AAAA.zip
fichier ODPFN016 : mois, SH8, pays, province d'origine, Etat americain de destination, valeur (CAD), quantite (kg).
La province d'origine separe directement la Colombie-Britannique (cote Pacifique) des provinces atlantiques.

    python3 scripts/build_canada_trade.py [--depuis 2018]
"""
import csv
import io
import json
import os
import sys
import time
import zipfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'canada_trade.json')
URL = 'https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_Dom_Exp_{y}.zip'
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
# SH8 canadiens du saumon de l'Atlantique (et du Danube) : prefixes SH6 -> forme
FORMS = {'030214': 'Fresh whole', '030441': 'Fresh fillets', '030313': 'Frozen whole', '030481': 'Frozen fillets', '030541': 'Smoked'}
FIDX = {k: i for i, k in enumerate(FORMS)}
DEPUIS = int(sys.argv[sys.argv.index('--depuis') + 1]) if '--depuis' in sys.argv else 2018


def read_year(y):
    r = requests.get(URL.format(y=y), headers=H, timeout=600)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = next(n for n in z.namelist() if '/ODPFN016_' in n or n.startswith('ODPFN016_'))
    last = int(name.split('_')[-1][:6])
    agg = {}
    hs8 = {}
    with z.open(name) as f:
        for row in csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig', errors='replace')):
            if len(row) < 8 or row[1][:6] not in FORMS:
                continue
            ym, h, cty, prov, st, val, qty, uom = row[:8]
            if not ym.isdigit():
                continue
            kg = float(qty or 0) if uom == 'KGM' else 0.0
            k = (int(ym), prov, FIDX[h[:6]], cty, st if cty == 'US' else '')
            a = agg.setdefault(k, [0.0, 0.0]); a[0] += kg; a[1] += float(val or 0)
            hs8[h] = hs8.get(h, 0) + kg
    return agg, (last, hs8)


def main():
    t0 = time.time()
    rows, hs, last = [], {}, None
    for y in range(DEPUIS, int(time.strftime('%Y')) + 1):
        try:
            agg, info = read_year(y)
        except Exception as e:  # noqa: BLE001
            print(f'  {y} : ERREUR {e}'); continue
        if agg is None:
            print(f'  {y} : pas encore publie'); continue
        last = max(last or 0, info[0])
        for h, kg in info[1].items():
            hs[h] = hs.get(h, 0) + kg
        rows += [[k[0], k[1], k[2], k[3], k[4], round(v[0] / 1000, 3), round(v[1] / 1000, 1)] for k, v in agg.items() if v[0] or v[1]]
        print(f'  {y} : {len(agg)} lignes, {sum(v[0] for v in agg.values()) / 1000:,.0f} t')
    if not rows:
        print('rien lu : fichier inchange'); return
    rows.sort()
    out = {'meta': {'built': time.strftime('%Y-%m-%d'), 'last': last, 'first': rows[0][0],
                    'source': 'Statistics Canada, Canadian International Merchandise Trade database (CIMT), domestic exports by HS8, country, province of origin and US state',
                    'url': URL.format(y='YYYY'), 'cols': ['ym', 'province', 'form', 'country', 'us_state', 'tonnes', 'k_cad'], 'forms': list(FORMS.values()),
                    'hs8_tonnes': {h: round(kg / 1000) for h, kg in sorted(hs.items())}},
           'rows': rows}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'))
    print(f'ecrit {OUT} ({os.path.getsize(OUT) // 1024} ko, {len(rows)} lignes, dernier mois {last}) en {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
