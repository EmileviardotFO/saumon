#!/usr/bin/env python3
"""
Telecharge les listes officielles d'etablissements agrees, pour les analyser
ensuite. Premier passage = reconnaissance : on enregistre ce que renvoient les
sites, sans encore rien interpreter.

1. Mattilsynet - "Virksomheter som handterer fiskerivarer (Fishery
   establishments)" : liste officielle des etablissements agrees (numero
   d'agrement, nom, adresse, activites : abattoir, transformation, entrepot...).
   La page propose un telechargement ; on enregistre la page et tout lien de
   fichier (csv, xlsx, xls, pdf) qu'elle contient.
2. Douanes chinoises (GACC, CIFER) : liste publique des etablissements etrangers
   enregistres pour exporter vers la Chine. On teste simplement l'acces.

Deux modes :
  python3 scripts/fetch_establishments.py            reconnaissance (sonde) :
        enregistre pages et fichiers bruts dans data/establishments/
  python3 scripts/fetch_establishments.py --update   mise a jour courante :
        telecharge la liste Mattilsynet (CSV) et l'ecrit dans data/data.json,
        cle 'establishments' (une ligne par numero d'agrement)
"""
import csv
import datetime as dt
import io
import sys
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'establishments')
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36 saumon-dashboard')
PAGES = {
    'mattilsynet_fishery': 'https://www.mattilsynet.no/godkjente-produkter-og-virksomheter/'
                           'fisk-og-fiskerivarer-fish-and-fishery-products-virksomheter-som-h%C3%A5ndterer-'
                           'fiskerivarer-fishery-establishments',
    'mattilsynet_index': 'https://www.mattilsynet.no/godkjente-produkter-og-virksomheter',
    'mattilsynet_china': 'https://www.mattilsynet.no/mat-og-drikke/eksport-av-mat-og-drikke/eksport-av-fisk-og-sjomat/'
                         'eksport-av-fisk-og-sjomat/landoversikt/eksport-av-fisk-og-sjomat-til-kina/'
                         'krav-til-produsent-eksport-av-fisk-og-sjomat-til-kina',
    'gacc_cifer_query': 'https://ciferquery.singlewindow.cn/',
    'mattilsynet_codes': 'https://www.mattilsynet.no/mat-og-drikke/matproduksjon/fisk-og-sjomat/'
                         'forklaring-til-produksjonsformer-for-mottak-slakting-og-produksjon-av-fiskerivarer-og-muslinger',
}
DATA = os.path.join(ROOT, 'data', 'data.json')
JS_RE = re.compile(r'src="([^"]+\.js[^"]*)"', re.I)
FILE_RE = re.compile(r'href="([^"]+?(?:\.csv|\.xlsx?|\.pdf|/attachment/[^"]+|[?&]format=csv[^"]*))"', re.I)


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*',
                                               'Accept-Language': 'nb-NO,nb;q=0.9,en;q=0.8'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get('Content-Type', ''), r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type', ''), e.read(), url
    except Exception as e:
        return None, '', repr(e).encode(), url


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = {'run_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), 'pages': [], 'files': []}
    for name, url in PAGES.items():
        st, ct, raw, final = get(url)
        open(os.path.join(OUT, f'{name}.html'), 'wb').write(raw[:3_000_000])
        links = []
        if st == 200 and b'<' in raw[:2000]:
            html = raw.decode('utf-8', 'replace')
            links = sorted(set(urllib.parse.urljoin(final, h.replace('&amp;', '&')) for h in FILE_RE.findall(html)))
        summary['pages'].append({'name': name, 'url': url, 'status': st, 'content_type': ct,
                                 'bytes': len(raw), 'file_links': links[:40]})
        print(f'{name:<22} {st} {ct[:30]:<30} {len(raw):>9} o, {len(links)} liens de fichier')
        if name == 'gacc_cifer_query' and st == 200:
            # l'adresse de la requete de recherche est dans les scripts du site
            html = raw.decode('utf-8', 'replace')
            for j, src in enumerate(JS_RE.findall(html), 1):
                if any(x in src for x in ('jquery', 'bootstrap', 'layer', 'laydate')):
                    continue
                u = urllib.parse.urljoin(final, src)
                st3, _, js, _ = get(u)
                open(os.path.join(OUT, f'gacc_js_{j}.js'), 'wb').write(js[:2_000_000])
                summary['files'].append({'link': u, 'status': st3, 'bytes': len(js), 'saved_as': f'gacc_js_{j}.js'})
        if name.startswith('mattilsynet_fishery'):
            for i, link in enumerate(links[:6], 1):
                st2, ct2, raw2, _ = get(link, timeout=180)
                ext = (re.search(r'\.(csv|xlsx?|pdf)', link, re.I) or re.search(r'(csv)', ct2, re.I))
                fn = f'mattilsynet_fishery_file{i}.{(ext.group(1).lower() if ext else "bin")}'
                open(os.path.join(OUT, fn), 'wb').write(raw2)
                summary['files'].append({'link': link, 'status': st2, 'content_type': ct2,
                                         'bytes': len(raw2), 'saved_as': fn})
                print(f'   fichier {i}: {st2} {ct2[:30]} {len(raw2)} o -> {fn}')
    json.dump(summary, open(os.path.join(OUT, 'summary.json'), 'w'), indent=1, ensure_ascii=False)


def update():
    """Liste Mattilsynet -> data.json['establishments']."""
    st, ct, raw, final = get(PAGES['mattilsynet_fishery'])
    if st != 200:
        sys.exit(f'Page Mattilsynet indisponible ({st})')
    html = raw.decode('utf-8', 'replace')
    links = [urllib.parse.urljoin(final, h.replace('&amp;', '&')) for h in FILE_RE.findall(html)]
    csvs = [l for l in links if '.csv' in l.lower()]
    if not csvs:
        sys.exit('Lien CSV introuvable sur la page Mattilsynet')
    st, ct, raw, _ = get(csvs[0], timeout=180)
    if st != 200:
        sys.exit(f'CSV Mattilsynet indisponible ({st})')
    text = raw.decode('utf-8-sig', 'replace')
    rows = list(csv.DictReader(io.StringIO(text)))
    # Le fichier contient chaque etablissement deux fois (casse normale et
    # majuscules) : une ligne par numero d'agrement, en gardant la casse normale.
    best = {}
    for r in rows:
        k = (r.get('GODKJENNINGSNUMMER') or '').strip()
        if not k:
            continue
        name = (r.get('VIRKSOMHETSNAVN') or '').strip()
        if k not in best or (best[k]['VIRKSOMHETSNAVN'].isupper() and not name.isupper()):
            best[k] = r
    out = []
    for k, r in sorted(best.items()):
        codes = sorted({c.strip() for c in (r.get('PRODUKSJONSFORM') or '').split(',') if c.strip()})
        out.append([k, (r.get('VIRKSOMHETSNAVN') or '').strip(), (r.get('BEDRIFTSNUMMER') or '').strip(),
                    (r.get('ADRESSE') or '').strip(), (r.get('POSTNR') or '').strip(),
                    (r.get('POSTSTED') or '').strip().title(), codes])
    data = json.load(io.open(DATA, encoding='utf-8'))
    data['establishments'] = {
        'meta': {'source': 'Mattilsynet - Virksomheter som handterer fiskerivarer (Fishery establishments)',
                 'url': PAGES['mattilsynet_fishery'], 'csv': csvs[0],
                 'fetched': dt.date.today().isoformat(), 'n': len(out),
                 'cols': ['approval', 'name', 'orgno', 'address', 'postcode', 'city', 'codes']},
        'rows': out,
    }
    io.open(DATA, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    print(f'Etablissements agrees : {len(out)} (sur {len(rows)} lignes du CSV)')


if __name__ == '__main__':
    if '--update' in sys.argv:
        update()
    else:
        main()
