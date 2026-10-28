#!/usr/bin/env python3
"""
Sonde Eurostat Comext (commerce exterieur de l'UE, mensuel, par produit CN8).

Objectif : trouver la forme d'URL qui marche pour interroger, depuis GitHub
Actions, les flux de saumon :
  - amont : importations des pays de l'UE, par pays d'origine ;
  - aval  : exportations du Danemark, de la Pologne et des Pays-Bas, par
            destination et par forme de produit.

On essaie plusieurs variantes d'URL connues (API "statistics" JSON-stat et
SDMX 2.1), sur une requete minuscule (Pologne, importations de saumon frais
entier de Norvege, quelques mois), plus la description du jeu de donnees.
Tout est enregistre dans data/eurostat_probe/ pour analyse.

    python3 scripts/probe_eurostat.py
"""
import datetime as dt
import json
import os
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'eurostat_probe')
UA = 'Mozilla/5.0 (X11; Linux x86_64) saumon-dashboard (github.com/emileviardotfo/saumon)'
BASE = 'https://ec.europa.eu/eurostat/api/comext/dissemination'
DS = 'DS-045409'
Q = 'reporter=PL&partner=NO&product=03021400&flow=1&freq=M&indicators=QUANTITY_IN_100KG'

TESTS = {
    'dataflow_all': f'{BASE}/sdmx/2.1/dataflow/ESTAT/all?detail=allstubs',
    'structure_045409': f'{BASE}/sdmx/2.1/datastructure/ESTAT/{DS}?references=children',
    'stat_json_a': f'{BASE}/statistics/1.0/data/{DS}?format=JSON&lang=EN&{Q}&sinceTimePeriod=2025-01',
    'stat_json_b': f'{BASE}/statistics/1.0/data/{DS}?format=JSON&lang=en&{Q}&time=2025-01&time=2025-02&time=2025-03',
    'stat_json_c': f'{BASE}/statistics/1.0/data/{DS}?{Q}&lastTimePeriod=6',
    'sdmx_csv_a': f'{BASE}/sdmx/2.1/data/{DS}/M.PL.NO.03021400.1.QUANTITY_IN_100KG?startPeriod=2025-01&format=SDMX-CSV',
    'sdmx_csv_b': f'{BASE}/sdmx/2.1/data/{DS}/M.PL.NO.03021400.1.QUANTITY_IN_100KG?startPeriod=2025-01&format=csvdata',
    'sdmx_xml': f'{BASE}/sdmx/2.1/data/{DS}/M.PL.NO.03021400.1.QUANTITY_IN_100KG?startPeriod=2025-01',
    # requete plus large : toutes origines, plusieurs produits (teste les listes avec '+')
    'stat_json_multi': f'{BASE}/statistics/1.0/data/{DS}?format=JSON&lang=EN&reporter=PL&partner=NO&partner=GB&partner=FO'
                       f'&product=03021400&product=03044100&product=03054100&flow=1&flow=2&freq=M&indicators=QUANTITY_IN_100KG'
                       f'&indicators=VALUE_IN_EUROS&sinceTimePeriod=2025-06',
    'sdmx_csv_multi': f'{BASE}/sdmx/2.1/data/{DS}/M.PL.NO+GB+FO.03021400+03044100+03054100.1+2.QUANTITY_IN_100KG+VALUE_IN_EUROS'
                      f'?startPeriod=2025-06&format=SDMX-CSV',
}


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get('Content-Type', ''), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type', ''), e.read()
    except Exception as e:
        return None, '', repr(e).encode()


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = {'run_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'tests': []}
    for name, url in TESTS.items():
        st, ct, raw = get(url)
        ext = 'json' if 'json' in ct else 'csv' if ('csv' in ct or 'text/plain' in ct) else 'xml' if 'xml' in ct else 'txt'
        fn = f'{name}.{ext}'
        open(os.path.join(OUT, fn), 'wb').write(raw[:4_000_000])
        head = raw[:300].decode('utf-8', 'replace')
        summary['tests'].append({'name': name, 'url': url, 'status': st, 'content_type': ct, 'bytes': len(raw), 'saved_as': fn, 'head': head})
        print(f'{name:18s} {st} {ct[:35]:35s} {len(raw):>9} o')
    json.dump(summary, open(os.path.join(OUT, 'summary.json'), 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
