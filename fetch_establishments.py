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

Sortie : data/establishments/  (fichiers bruts + summary.json)
Usage  : python3 scripts/fetch_establishments.py
"""
import datetime as dt
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
}
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


if __name__ == '__main__':
    main()
