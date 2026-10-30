#!/usr/bin/env python3
"""
Test de fumee du tableau de bord, lance par le workflow apres chaque mise a
jour des donnees : ouvre docs/production.html avec le data.json qui vient
d'etre produit, clique sur chaque onglet et verifie que tout s'affiche.

Verifie :
  - aucune erreur JavaScript au chargement ni dans aucun onglet ;
  - le bandeau "Donnees a jour" (data.json lu correctement) ;
  - la periode par defaut = dernier mois present dans les donnees ;
  - chaque onglet affiche un tableau ou un graphique non vide ;
  - le dernier prix mensuel Akvafakta est bien repris par la page.

Resultat ecrit en JSON (chemin en argument, par defaut data/smoke.json) ;
code de sortie 1 si un controle echoue, pour que le workflow le signale.

    python3 scripts/smoke_test.py [sortie.json]
"""
import datetime as dt
import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, 'docs', 'production.html')
DATA = os.path.join(ROOT, 'data', 'data.json')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'data', 'smoke.json')

TABS = ['Summary', 'Producers', 'USA focus', 'China focus', 'Co-products', 'EU markets', 'National view (Norway)', 'Multi-year comparison', 'Supply outlook', 'Markets',
        'Product per market', 'Calibre & premium', 'Generations', 'By zone (PO)', 'Fish health', 'Farm register']


def main():
    data = json.load(open(DATA, encoding='utf-8'))
    recs = data.get('records') or []
    last_ym = max(((r['year'], r['month']) for r in recs), default=None)
    prices = [r for r in data.get('monthly_akvafakta') or [] if r.get('price_nok_kg')]
    last_price = max(((r['year'], r['month']) for r in prices), default=None)

    checks, errors = [], []

    def check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail})
        print(('OK   ' if ok else 'FAIL ') + name + (f' — {detail}' if detail else ''))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/data.json', lambda route: route.fulfill(path=DATA, content_type='application/json'))
        EUF = os.path.join(ROOT, 'data', 'eurostat.json')
        page.route('**/eurostat.json', lambda route: route.fulfill(path=EUF, content_type='application/json')
                   if os.path.exists(EUF) else route.fulfill(status=404, body='missing'))
        CNF = os.path.join(ROOT, 'data', 'cn_imports.json')
        page.route('**/cn_imports.json', lambda route: route.fulfill(path=CNF, content_type='application/json')
                   if os.path.exists(CNF) else route.fulfill(status=404, body='missing'))
        USF = os.path.join(ROOT, 'data', 'us_imports.json')
        page.route('**/us_imports.json', lambda route: route.fulfill(path=USF, content_type='application/json')
                   if os.path.exists(USF) else route.fulfill(status=404, body='missing'))
        NTF = os.path.join(ROOT, 'data', 'national_trade.json')
        page.route('**/national_trade.json', lambda route: route.fulfill(path=NTF, content_type='application/json')
                   if os.path.exists(NTF) else route.fulfill(status=404, body='missing'))
        page.goto('file://' + PAGE)
        page.wait_for_timeout(4000)

        n0 = len(errors)
        check('page loads without JavaScript error', n0 == 0, '; '.join(errors[:3]))
        banner = page.evaluate('document.body.firstChild && document.body.firstChild.textContent || ""')
        check('data.json read by the page', banner.startswith('Donnees a jour'), banner[:120])

        sel = page.evaluate('[+yearSel.value, +monthSel.value]')
        check('default period = latest month in the data',
              last_ym is not None and tuple(sel) == last_ym, f'page {sel}, data {last_ym}')

        if last_price:
            k = str(last_price[0] * 100 + last_price[1])
            has = page.evaluate(f'typeof PRICES !== "undefined" && PRICES["{k}"] !== undefined')
            check('latest Akvafakta monthly price used by the page', has, k)

        for t in TABS:
            before = len(errors)
            found = page.evaluate("""t => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === t);
                                     if (!b) return false; b.click(); return true; }""", t)
            page.wait_for_timeout(2500 if t in ('EU flows', 'EU markets', 'Producers', 'USA focus', 'China focus') else 900)
            if not found:
                check(f'tab "{t}"', False, 'button not found')
                continue
            info = page.evaluate("""() => { const v = [...document.querySelectorAll('.panel')].find(x => x.offsetParent && x.id && x.id.endsWith('View'));
                                    if (!v) return null;
                                    return { id: v.id, rows: v.querySelectorAll('tbody tr, .sm-row').length,
                                             marks: v.querySelectorAll('svg path, svg circle, svg rect, svg polyline').length }; }""")
            new = errors[before:]
            ok = info is not None and (info['rows'] > 0 or info['marks'] > 0) and not new
            if (t in ('EU markets', 'Producers', 'USA focus') and not os.path.exists(os.path.join(ROOT, 'data', 'eurostat.json'))) or \
                    (t == 'USA focus' and not os.path.exists(USF)) or (t == 'China focus' and not os.path.exists(CNF)) or \
                    (t == 'Co-products' and not (data.get('ssb_coproducts') or {}).get('rows')):
                ok = info is not None and not new          # donnees Eurostat pas encore collectees
            check(f'tab "{t}"', ok, (f"{info['rows']} table rows, {info['marks']} chart marks" if info else 'no panel')
                  + (f"; error: {new[0]}" if new else ''))
        browser.close()

    res = {'run_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
           'ok': all(c['ok'] for c in checks), 'checks': checks, 'errors': errors[:10]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print('\nResultat :', 'tout est bon' if res['ok'] else 'PROBLEME, voir ci-dessus')
    sys.exit(0 if res['ok'] else 1)


if __name__ == '__main__':
    main()
