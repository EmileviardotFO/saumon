#!/usr/bin/env python3
"""
Collecte de sources publiques ajoutees en novembre 2026 (fichiers bruts deposes dans le depot, lus ensuite par les builders).

Ecosse  -> farming/donnees_gb/
  ms_sea_lice_current.csv, ms_sea_lice_archive.csv   poux par site et par semaine (Scotland's Aquaculture), depuis mars 2021
  ms_site_details.csv, se_permit_conditions.csv      sites (operateur, zone, coordonnees), biomasse maximale autorisee
  salmon_scotland_mortality.csv                      Salmon Scotland : mortalite mensuelle par ferme, cause, statut (tableaux HTML)
  fhi_mortality.xlsx                                 Fish Health Inspectorate : evenements de mortalite par site
  survey_T*.csv                                      enquete annuelle de production (Marine Directorate)
Norvege -> farming/donnees_no/
  akvakulturregisteret.csv                           licences et capacites par site (Fiskeridirektoratet, instantane du jour)
  nsc_ukestat_<annee>_<semaine>.txt                  Norges sjomatrad : statistique hebdomadaire par produit et marche (texte du PDF)
  mattilsynet_slakting.txt                           page des classes de qualite a l'abattage (texte)
Chili   -> xlsx/chile/transparencia/                 Sernapesca, loi 21.532 : recoltes, mortalites, traitements, evasions

    python3 scripts/fetch_new_sources.py
"""
import csv, datetime as dt, io, os, re, sys, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GB, NO, CL = (os.path.join(ROOT, p) for p in ('farming/donnees_gb', 'farming/donnees_no', 'xlsx/chile/transparencia'))
for d in (GB, NO, CL):
    os.makedirs(d, exist_ok=True)
S = requests.Session()
S.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'


def get(url, **kw):
    for i in range(3):
        try:
            r = S.get(url, timeout=120, **kw)
            if r.status_code == 200:
                return r
            print(f'  {r.status_code} {url}')
            if r.status_code in (403, 404):
                return None
        except Exception as e:
            print(f'  error {str(e)[:120]} {url}')
        time.sleep(3)
    return None


def save(url, path, minsize=500):
    r = get(url)
    if r is None or len(r.content) < minsize:
        print(f'ECHEC {url}')
        return False
    open(path, 'wb').write(r.content)
    print(f'ok {os.path.relpath(path, ROOT)} {len(r.content):,} octets')
    return True


def scotland():
    base = 'https://aquaculture.scotland.gov.uk/csv/'
    for f in ('ms_sea_lice_current.csv', 'ms_sea_lice_archive.csv', 'ms_site_details.csv', 'se_permit_conditions.csv', 'se_monthly_reports.csv'):
        ok = save(base + f, os.path.join(GB, f))
        if ok:
            head = open(os.path.join(GB, f), encoding='utf-8', errors='replace').read(600).splitlines()[:3]
            print('   ', head)
    # enquete annuelle : tables utiles
    for t in ('T24', 'T25', 'T27', 'T28', 'T30', 'T37'):
        save(f'https://data.marine.gov.scot/sites/default/files//2026%20Scottish%20Fish%20Farm%20Production%20Survey%20{t}.csv', os.path.join(GB, f'survey_{t}.csv'), 50)
    # Fish Health Inspectorate : le lien du classeur change chaque mois
    r = get('https://www.gov.scot/publications/fish-health-inspectorate-mortality-information/')
    if r is not None:
        m = re.findall(r'href="([^"]+\.xlsx[^"]*)"', r.text)
        print('  FHI xlsx links:', m[:5])
        for h in m[:1]:
            u = h if h.startswith('http') else 'https://www.gov.scot' + h
            if save(u, os.path.join(GB, 'fhi_mortality.xlsx'), 5000):
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(os.path.join(GB, 'fhi_mortality.xlsx'), read_only=True, data_only=True)
                    for ws in wb.worksheets[:6]:
                        print('   sheet', ws.title, ws.max_row, ws.max_column)
                        for i, row in enumerate(ws.iter_rows(values_only=True)):
                            if i >= 4:
                                break
                            print('     ', [str(v)[:28] if v is not None else None for v in row[:14]])
                except Exception as e:
                    print('   cannot read xlsx', e)
    # Salmon Scotland : un tableau HTML par mois ; les adresses sont irregulieres, on part de l'index
    import pandas as pd
    links = {}
    for page in range(0, 8):
        r = get('https://www.salmonscotland.co.uk/reports' + (f'?page={page}' if page else ''))
        if r is None:
            break
        found = re.findall(r'href="(/reports/monthly-mortality-rate[^"#?]*)"[^>]*>(.*?)</a>', r.text, flags=re.S)
        n0 = len(links)
        for h, t in found:
            links.setdefault(h, re.sub(r'<[^>]+>|\s+', ' ', t).strip())
        if page and len(links) == n0:
            break
    print('  Salmon Scotland reports found:', len(links))
    MON = {m.lower(): i + 1 for i, m in enumerate(['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'])}
    rows, done = [], 0
    for h in sorted(links):
        r = get('https://www.salmonscotland.co.uk' + h)
        if r is None:
            continue
        title = re.search(r'<h1[^>]*>(.*?)</h1>', r.text, flags=re.S)
        title = re.sub(r'<[^>]+>|\s+', ' ', title.group(1)).strip() if title else links[h]
        m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', title)
        if not m:
            print('   no month in title:', h, title[:80])
            continue
        ym = f'{m.group(2)}-{MON[m.group(1).lower()]:02d}'
        try:
            tabs = pd.read_html(io.StringIO(r.text))
        except Exception as e:
            print('   no table', h, str(e)[:60])
            continue
        for t in tabs:
            cols = [str(c).strip().lower() for c in t.columns]
            if not any('farm' in c for c in cols):
                continue
            for rec in t.fillna('').astype(str).values.tolist():
                rows.append([ym, h] + [x.strip() for x in rec[:6]])
        done += 1
        if done <= 2:
            print('   ', ym, h, [list(t.columns) for t in tabs][:3])
        time.sleep(0.4)
    if rows:
        with open(os.path.join(GB, 'salmon_scotland_mortality.csv'), 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['month', 'page', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6'])
            w.writerows(rows)
        print(f'ok salmon_scotland_mortality.csv {len(rows)} lignes, {done} mois, {min(r[0] for r in rows)} -> {max(r[0] for r in rows)}')


def norway():
    save('https://api.fiskeridir.no/pub-aqua/api/v1/dump/new-legacy-csv-file', os.path.join(NO, 'akvakulturregisteret.csv'), 100000)
    try:
        print('   ', open(os.path.join(NO, 'akvakulturregisteret.csv'), encoding='utf-8', errors='replace').read(900).splitlines()[:3])
    except Exception:
        pass
    # Norges sjomatrad : statistique hebdomadaire (PDF) ; noms de fichiers irreguliers, on essaie plusieurs formes pour les 6 dernieres semaines
    import pdfplumber
    today = dt.date.today()
    got = 0
    for back in range(1, 9):
        y, w, _ = (today - dt.timedelta(weeks=back)).isocalendar()
        out = os.path.join(NO, f'nsc_ukestat_{y}_{w:02d}.txt')
        if os.path.exists(out):
            got += 1
            continue
        base = f'https://en.seafood.no/globalassets/markedsinnsikt/apne-rapporter/ukestatistikk/{y}/'
        cands = [f'uke-{w}/ukestat-laks-og-orret-uke-{w}.pdf', f'uke-{w}/ukestat-laks-og-orret-uke{w}.pdf', f'uke-{w:02d}/ukestat-laks-og-orret-uke-{w:02d}.pdf', f'ukestat-laks-og-orret-uke-{w}.pdf',
                 f'uke-{w}/ukestat-laks-og-orret-uke-{w}-{y}.pdf', f'uke{w}/ukestat-laks-og-orret-uke{w}.pdf']
        for c in cands:
            r = get(base + c)
            if r is not None and r.content[:4] == b'%PDF':
                with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                    txt = '\n\n=== PAGE ===\n'.join((p.extract_text() or '') for p in pdf.pages)
                open(out, 'w', encoding='utf-8').write(f'# {base + c}\n' + txt)
                print(f'ok nsc_ukestat_{y}_{w:02d}.txt {len(txt):,} caracteres, {len(pdf.pages)} pages')
                if got == 0:
                    print(txt[:2500])
                got += 1
                break
        if got >= 4:
            break
    for u in ('https://en.seafood.no/market-insight/open-reports/', 'https://seafood.no/markedsinnsikt/apne-rapporter/'):
        r = get(u)
        if r is not None:
            print('  NSC open reports page', u, len(r.text), sorted(set(re.findall(r'href="([^"]*(?:ukestat|ukestatistikk|weekly)[^"]*)"', r.text)))[:20])
    r = get('https://mattilsynet.no/fisk-og-akvakultur/slakting-av-fisk/statistikk-om-slakting-av-oppdrettet-laksefisk')
    if r is not None:
        txt = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', r.text, flags=re.S)
        txt = re.sub(r'<[^>]+>', ' ', txt)
        txt = re.sub(r'\s+', ' ', txt)
        open(os.path.join(NO, 'mattilsynet_slakting.txt'), 'w', encoding='utf-8').write(txt)
        i = txt.find('Statistikk')
        print('  Mattilsynet page text:', txt[max(0, i):i + 3000])
        print('  links:', sorted(set(re.findall(r'href="([^"]*(?:datastudio|lookerstudio|\.xlsx|\.csv|api)[^"]*)"', r.text)))[:20])


def chile():
    r = get('https://www.sernapesca.cl/manuales_y_publicaciones/informacion-para-la-transparencia-en-la-acuicultura/')
    if r is None:
        return
    links = sorted(set(re.findall(r'href="([^"]+\.xlsx)"', r.text)))
    print('  Sernapesca transparencia xlsx:', links)
    import openpyxl
    for u in links:
        name = re.sub(r'_v\d{8}(-\d+)?', '', u.split('/')[-1])
        path = os.path.join(CL, name)
        if save(u, path, 5000):
            try:
                wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
                for ws in wb.worksheets[:4]:
                    print('   sheet', ws.title, ws.max_row, ws.max_column)
                    for i, row in enumerate(ws.iter_rows(values_only=True)):
                        if i >= 5:
                            break
                        print('     ', [str(v)[:26] if v is not None else None for v in row[:16]])
            except Exception as e:
                print('   cannot read', e)


def canada():
    """Colombie-Britannique : fichiers ouverts du ministere federal des Peches (DFO) que les constructeurs existants ne prennent pas."""
    out = os.path.join(ROOT, 'farming', 'donnees_ca', 'dfo')
    os.makedirs(out, exist_ok=True)
    base = 'https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/{}/attachments/{}'
    for name, rid, f in (
            ('licences.csv', '522d1b67-30d8-4a34-9b62-5da99b1035e6', 'license-permis-mer-mar-rpt-pac-dfo-mpo-aquaculture-eng.csv'),
            ('lice_mitigation.csv', 'fdba4d10-51aa-40df-884e-09e1c29049d8', 'lice-poux-mitigation-attenuation-2011-ongoing-rpt-pac-dfo-mpo-aquaculture-eng.csv'),
            ('health_events.csv', 'deefd1d7-7184-44c7-83aa-ec0db91aad27', 'health-even-sante-2016-ongoing-rpt-pac-dfo-mpo-aquaculture-eng.csv'),
            ('carcass.csv', '0a8c5505-ecb3-4d8b-8120-462bd7def6bb', 'carc-cat-fac-inst-2013-ongoing-rpt-pac-dfo-mpo-aquaculture-eng.csv'),
            ('transfers.csv', '700fe290-7653-49e1-b961-741dc1ead924', 'transfers-transfert-2015-ongoing-rpt-pac-dfo-mpo-aquaculture-eng.csv'),
            ('escapes.csv', '691dd994-4911-433d-b3b6-00349ba9f24e', 'escapes-evasions-2011-ongoing-rpt-pac-dfo-mpo-aquaculture-eng.csv'),
            ('benthic_industry.csv', '7e76fdc8-c36a-491a-9afb-4f9280c929e8', 'benth-indust-2011-ongoing-rpt-pac-dfo-mpo-aquaculture-eng.csv')):
        if save(base.format(rid, f), os.path.join(out, name)):
            try:
                txt = open(os.path.join(out, name), encoding='utf-8-sig', errors='replace').read().split('\n')
                print('   ', len(txt), 'lignes |', txt[0][:300])
                print('   ', txt[1][:300]); print('   ', txt[-2][:300])
            except Exception as e:
                print('   cannot read', e)


if __name__ == '__main__':
    for fn in (scotland, norway, chile, canada):
        print('\n' + '=' * 90 + '\n' + fn.__name__.upper(), flush=True)
        try:
            fn()
        except Exception as e:
            print('ERREUR', fn.__name__, repr(e)[:300])
    print('\nFIN')
