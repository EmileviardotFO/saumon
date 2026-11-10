#!/usr/bin/env python3
"""
Feroe : telecharge les trois tables publiques de HFS (Heilsufrodiliga Starvsstovan, autorite sanitaire),
rubrique Aling > Hagtol. Le portail est en Oracle ADF (tout en JavaScript) : on rend la page dans un
navigateur sans tete (Playwright) et on clique « Flyt ut til Excel », qui renvoie un HTML deguise en .xls.

  Tal av laksi   poissons par site d'elevage a la fin de chaque mois (depuis nov. 2021) -> farming/donnees_fo/hfs_fish.csv
  Lusatol        femelles adultes de poux par poisson, par site et date de comptage       -> farming/donnees_fo/hfs_lice.csv
  Heilivagur     traitements medicamenteux par site : dates, bain/aliment, produit, dose  -> farming/donnees_fo/hfs_med.csv

Chaque export contient tout l'historique : le fichier est reecrit entierement a chaque passage (pas de doublons).
On cherche aussi, sur les pages de la rubrique, un classeur de recolte hebdomadaire par calibre (« Toka av laksi ») ;
s'il est trouve il est enregistre sous farming/donnees_fo/toka_av_laksi.xlsx.

    python3 scripts/fetch_hfs.py           (GitHub Actions : pip install playwright && playwright install chromium)
"""
import csv
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'farming', 'donnees_fo')
os.makedirs(OUT, exist_ok=True)
BASE = 'https://www.hfs.fo/webcenter/portal/HFS/pages_aling/hagtl/'
TABLES = {
    'fish': (BASE + 'talavlaksialikjum', ['as', 'site', 'name', 'company', 'species', 'date', 'fish']),
    'lice': (BASE + 'lsatl', ['adult_females', 'as', 'site', 'name', 'company', 'date']),
    'med': (BASE + 'alingvigerirtest', ['site', 'name', 'company', 'start', 'end', 'type', 'product', 'substance', 'amount', 'unit']),
}
PAGES_XLSX = [BASE + 'frgreiing', BASE, 'https://www.hfs.fo/webcenter/portal/HFS/Aling']


def parse_export(raw):
    """Export ADF : tableau HTML ; renvoie les lignes (listes de chaines), sans la colonne d'index vide."""
    import pandas as pd
    txt = raw.decode('utf-8', 'replace')
    dfs = pd.read_html(io.StringIO(txt), header=None)
    df = max(dfs, key=len)
    rows = []
    for r in df.itertuples(index=False):
        vals = ['' if (isinstance(v, float) and v != v) else str(v).strip() for v in r]
        while vals and vals[0] == '':
            vals.pop(0)
        if vals:
            rows.append(vals)
    return rows


def norm_num(s):
    s = s.replace(' ', '').replace(' ', '')
    if re.fullmatch(r'-?\d{1,3}(\.\d{3})+', s):
        return s.replace('.', '')
    return s.replace(',', '.')


def main():
    from playwright.sync_api import sync_playwright
    ok = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(accept_downloads=True, user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36')
        pg = ctx.new_page()
        for key, (url, cols) in TABLES.items():
            try:
                pg.goto(url, timeout=120000, wait_until='networkidle')
                pg.wait_for_timeout(4000)
                loc = pg.locator('text=Flyt út til Excel').first
                with pg.expect_download(timeout=120000) as dl:
                    loc.click()
                raw = open(dl.value.path(), 'rb').read()
                rows = parse_export(raw)
                rows = [r for r in rows if len(r) >= len(cols) - 1 and any(re.search(r'\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}', x) for x in r)]
                if len(rows) < 50:
                    raise RuntimeError(f'only {len(rows)} rows')
                path = os.path.join(OUT, f'hfs_{key}.csv')
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(cols)
                    for r in rows:
                        r = (r + [''] * len(cols))[:len(cols)]
                        if key == 'fish':
                            r[6] = norm_num(r[6])
                        if key == 'lice':
                            r[0] = norm_num(r[0])
                        if key == 'med':
                            r[8] = norm_num(r[8])
                        w.writerow(r)
                ok[key] = len(rows)
                print(f'{key}: {len(rows)} lignes -> {path}', flush=True)
            except Exception as e:
                print(f'{key}: ECHEC {str(e)[:300]}', flush=True)
        # classeur de recolte hebdomadaire, si un lien xlsx existe quelque part dans la rubrique
        for url in PAGES_XLSX:
            try:
                pg.goto(url, timeout=120000, wait_until='networkidle')
                pg.wait_for_timeout(3000)
                links = pg.evaluate("[...document.querySelectorAll('a')].map(a => [a.innerText.trim(), a.href]).filter(x => /\\.xlsx?(\\?|$)/i.test(x[1]))")
                for t, h in links:
                    print('xlsx link:', t, h)
                    if re.search(r'(?i)t.ka|laksi|harvest', t + h):
                        r = ctx.request.get(h, timeout=120000)
                        if r.ok and len(r.body()) > 10000:
                            open(os.path.join(OUT, 'toka_av_laksi.xlsx'), 'wb').write(r.body())
                            print('  -> toka_av_laksi.xlsx', len(r.body()))
                            break
            except Exception as e:
                print('xlsx scan', url, 'failed:', str(e)[:200])
        b.close()
    if 'fish' not in ok:
        sys.exit('HFS : la table des poissons par site n a pas pu etre lue')


if __name__ == '__main__':
    main()
