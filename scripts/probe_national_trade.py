#!/usr/bin/env python3
"""
Sonde des statistiques d'exportation de saumon des pays producteurs hors
Norvege, pour l'onglet "Producers" (exportations vers toutes destinations,
pas seulement vers l'UE) :

  - Iles Feroe  : Hagstova (PxWeb)
  - Islande     : Hagstofa Islands (PxWeb)
  - Royaume-Uni : HMRC, API OData de uktradeinfo
  - Chili et tous les autres : ONU, Comtrade (API publique "preview", sans cle)

Pour chaque source, on teste plusieurs formes d'URL connues, on liste les
tables qui parlent d'exportations ou de poisson (PxWeb), et on enregistre les
reponses dans data/national_probe/ (summary.json + un fichier par essai), pour
choisir ensuite la source et ecrire le script de collecte.

    python3 scripts/probe_national_trade.py
"""
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'national_probe')
UA = 'Mozilla/5.0 (X11; Linux x86_64) saumon-dashboard (github.com/emileviardotfo/saumon)'
KEYWORDS = re.compile(r'export|trade|salmon|fish|laks|lax|fisk|utflutning|útflutning|utanrik|vøru|uttanland|external|goods', re.I)

TESTS = {
    # --- Feroe (Hagstova, PxWeb) ---
    'fo_root_a': 'https://statbank.hagstova.fo/api/v1/en/H2/',
    'fo_root_b': 'https://statbank.hagstova.fo/pxweb/api/v1/en/H2/',
    'fo_root_c': 'https://statbank.hagstova.fo/api/v1/en/',
    'fo_search': 'https://statbank.hagstova.fo/api/v1/en/H2/?query=salmon',
    # --- Islande (Hagstofa, PxWeb) ---
    'is_root': 'https://px.hagstofa.is/pxen/api/v1/en/',
    'is_search_a': 'https://px.hagstofa.is/pxen/api/v1/en/Efnahagur?query=salmon',
    'is_search_b': 'https://px.hagstofa.is/pxen/api/v1/en/Efnahagur?query=export',
    'is_trade': 'https://px.hagstofa.is/pxen/api/v1/en/Efnahagur/utanrikisverslun/',
    # --- Royaume-Uni (HMRC uktradeinfo, OData) ---
    'uk_commodity': 'https://api.uktradeinfo.com/Commodity?$filter=Cn8Code eq \'03021400\'',
    'uk_ots_a': 'https://api.uktradeinfo.com/OTS?$filter=' + urllib.parse.quote('CommodityId eq 3021400 and MonthId ge 202501') + '&$top=200',
    'uk_ots_b': 'https://api.uktradeinfo.com/OTS?$filter=' + urllib.parse.quote('CommodityId eq 3021400 and MonthId ge 202501 and (FlowTypeId eq 2 or FlowTypeId eq 4)') + '&$top=200',
    'uk_flowtypes': 'https://api.uktradeinfo.com/FlowType',
    # --- ONU Comtrade (preview publique, 500 lignes max) : Chili, Feroe, Islande, Royaume-Uni ---
    'ct_cl_month': 'https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=152&period=202506&cmdCode=030214,030441,030481,030313&flowCode=X&partnerCode=0',
    'ct_cl_bypartner': 'https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=152&period=202506&cmdCode=030214&flowCode=X',
    'ct_fo_month': 'https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=234&period=202506&cmdCode=030214,030441,030481,030313&flowCode=X&partnerCode=0',
    'ct_is_month': 'https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=352&period=202506&cmdCode=030214,030441,030481,030313&flowCode=X&partnerCode=0',
    'ct_gb_month': 'https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=826&period=202506&cmdCode=030214,030441,030481,030313&flowCode=X&partnerCode=0',
    'ct_availability': 'https://comtradeapi.un.org/public/v1/getDA/C/M/HS?reporterCode=152,234,352,826',
}


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json, */*'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get('Content-Type', ''), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type', ''), e.read()
    except Exception as e:
        return None, '', repr(e).encode()


def walk_px(base, depth=3, path=''):
    """Parcourt l'arborescence PxWeb et garde les tables dont le titre parle d'exportations ou de poisson."""
    found = []
    st, ct, raw = get(base + path)
    if st != 200:
        return found
    try:
        items = json.loads(raw)
    except ValueError:
        return found
    for it in items if isinstance(items, list) else []:
        p = (path + '/' if path else '') + it.get('id', '')
        if it.get('type') == 't':
            if KEYWORDS.search(it.get('text', '')):
                found.append({'path': p, 'text': it.get('text'), 'updated': it.get('updated')})
        elif depth > 0 and it.get('type') == 'l' and (depth == 3 or KEYWORDS.search(it.get('text', '') + ' ' + it.get('id', ''))):
            found += walk_px(base, depth - 1, p)
    return found


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = {'run_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'tests': [], 'px_tables': {}}
    for name, url in TESTS.items():
        st, ct, raw = get(url)
        ext = 'json' if 'json' in ct else 'xml' if 'xml' in ct else 'txt'
        fn = f'{name}.{ext}'
        open(os.path.join(OUT, fn), 'wb').write(raw[:3_000_000])
        summary['tests'].append({'name': name, 'url': url, 'status': st, 'content_type': ct, 'bytes': len(raw), 'saved_as': fn,
                                 'head': raw[:300].decode('utf-8', 'replace')})
        print(f'{name:18s} {st} {ct[:30]:30s} {len(raw):>9} o')
    # arborescences PxWeb : tables d'exportations / poisson
    for key, base in [('faroe', 'https://statbank.hagstova.fo/api/v1/en/H2/'), ('iceland', 'https://px.hagstofa.is/pxen/api/v1/en/')]:
        try:
            tabs = walk_px(base)
        except Exception as e:
            tabs = [{'error': repr(e)}]
        summary['px_tables'][key] = tabs
        print(f'{key}: {len(tabs)} tables trouvees')
    json.dump(summary, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
