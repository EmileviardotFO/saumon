#!/usr/bin/env python3
"""
Liste des etablissements norvegiens enregistres aupres des douanes chinoises
(GACC, systeme CIFER) pour exporter des denrees vers la Chine.

Source : https://ciferquery.singlewindow.cn/ (page de recherche publique).
Les reponses du site sont chiffrees et dechiffrees par son propre JavaScript :
on pilote donc la vraie page dans un navigateur sans ecran (Playwright),
on choisit le pays "Norvege", on lance la recherche et on lit le tableau
page par page, tel que la page l'a dechiffre.

Ecrit :
  data/data.json, cle 'china' : {meta, cols, rows}
  data/china_history.json      : date de premiere apparition de chaque
                                 enregistrement (pour reperer les nouveaux)
  data/establishments/gacc_rows_raw.json : lignes brutes (diagnostic)
En cas d'echec : data/establishments/gacc_debug.html (+ .png) pour comprendre.

    python3 scripts/fetch_china_gacc.py
"""
import datetime as dt
import io
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'data.json')
HIST = os.path.join(ROOT, 'data', 'china_history.json')
OUT = os.path.join(ROOT, 'data', 'establishments')
URL = 'https://ciferquery.singlewindow.cn/'
COUNTRY_TERMS = ['挪威', 'NORWAY', 'Norway']
MAX_PAGES = 400


def log(*a):
    print(*a, flush=True)


def pick(row, *patterns):
    """Premiere valeur dont le nom de champ correspond a l'un des motifs."""
    for p in patterns:
        for k, v in row.items():
            if re.search(p, k, re.I) and v not in (None, ''):
                return v
    return None


def norm_date(v):
    if v in (None, ''):
        return None
    if isinstance(v, (int, float)) and v > 1e11:          # horodatage en millisecondes
        return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc).date().isoformat()
    m = re.search(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', str(v))
    return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else None


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1400, 'height': 1000}, locale='zh-CN')
        page.set_default_timeout(60000)
        try:
            page.goto(URL, wait_until='networkidle')
            page.wait_for_timeout(3000)
            # 1. pays = Norvege, via la liste d'autocompletion du site
            chosen = None
            for term in COUNTRY_TERMS:
                page.fill('#countryName', '')
                page.type('#countryName', term, delay=80)
                page.keyboard.press('Space')
                page.wait_for_timeout(2500)
                cand = page.locator(f'text=/{term}/i').filter(has_not=page.locator('#countryName'))
                n = cand.count()
                for j in range(n):
                    el = cand.nth(j)
                    try:
                        if el.is_visible():
                            el.click()
                            page.wait_for_timeout(800)
                            if page.input_value('#country'):
                                chosen = term
                                break
                    except Exception:
                        continue
                if chosen:
                    break
            code = page.input_value('#country')
            if not code:
                log('Pays non selectionne par la liste : essai du code NOR')
                page.evaluate("() => { document.querySelector('#country').value = 'NOR'; document.querySelector('#countryName').value = '挪威'; }")
                code = 'NOR'
            log(f'Pays : {page.input_value("#countryName")} (code {code})')
            # 2. statut : tous
            try:
                page.select_option('#status', 'ALL')
            except Exception:
                pass
            # 3. recherche
            page.evaluate('() => chaxun()')
            page.wait_for_timeout(5000)
            body_text = page.inner_text('body')
            if 'Real-name' in body_text or '实名' in body_text:
                log('Le site demande une connexion pour cette recherche.')
            rows, seen_pages = [], 0
            last_first = None
            while seen_pages < MAX_PAGES:
                data = page.evaluate("() => { try { return $('#ciferMessStatVoList').bootstrapTable('getData'); } catch (e) { return null; } }")
                if not data:
                    break
                first = json.dumps(data[0], sort_keys=True, ensure_ascii=False)
                if first == last_first:
                    break                                   # la page n'a plus change : fin
                last_first = first
                rows.extend(data)
                seen_pages += 1
                opts = page.evaluate("() => { const o = $('#ciferMessStatVoList').bootstrapTable('getOptions'); return {n: o.pageNumber, total: o.totalPages}; }")
                if not opts or opts['n'] >= (opts['total'] or 0):
                    break
                page.evaluate("() => $('#ciferMessStatVoList').bootstrapTable('nextPage')")
                page.wait_for_timeout(2500)
            log(f'{len(rows)} lignes lues sur {seen_pages} page(s)')
            if not rows:
                raise RuntimeError('aucune ligne lue')
        except Exception as e:
            log('ECHEC :', e)
            try:
                io.open(os.path.join(OUT, 'gacc_debug.html'), 'w', encoding='utf-8').write(page.content())
                page.screenshot(path=os.path.join(OUT, 'gacc_debug.png'), full_page=True)
            except Exception:
                pass
            browser.close()
            sys.exit(1)
        browser.close()

    json.dump(rows, io.open(os.path.join(OUT, 'gacc_rows_raw.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    log('Champs disponibles :', sorted(rows[0].keys()))

    today = dt.date.today().isoformat()
    hist = json.load(io.open(HIST, encoding='utf-8')) if os.path.exists(HIST) else {'first_seen': {}, 'runs': []}
    out, seen = [], set()
    for r in rows:
        reg = str(pick(r, r'^regCo', r'regco', r'registerNo', r'regNo') or '').strip()
        org = str(pick(r, r'^orgNo', r'orgno', r'countryReg', r'localReg') or '').strip()
        name = str(pick(r, r'enterpriseName', r'entName', r'companyName', r'name') or '').strip()
        typ = str(pick(r, r'registerTypeName', r'typeName', r'registerType', r'productType') or '').strip()
        status = str(pick(r, r'statusName', r'^status', r'state') or '').strip()
        d_reg = norm_date(pick(r, r'regDate', r'registerDate', r'approveDate', r'effect.*Date', r'startDate', r'validDate', r'Date'))
        d_end = norm_date(pick(r, r'endDate', r'expire', r'validTo', r'invalid'))
        key = reg or (org + '|' + name)
        if key in seen:
            continue
        seen.add(key)
        hist['first_seen'].setdefault(key, today)
        out.append([org, reg, name, typ, status, d_reg, d_end, hist['first_seen'][key]])
    hist['runs'].append({'date': today, 'n': len(out)})
    hist['runs'] = hist['runs'][-60:]
    io.open(HIST, 'w', encoding='utf-8').write(json.dumps(hist, ensure_ascii=False, separators=(',', ':'), sort_keys=True))

    data = json.load(io.open(DATA, encoding='utf-8'))
    data['china'] = {
        'meta': {'source': 'GACC CIFER — Registration information of overseas manufacturers of imported food',
                 'url': URL, 'fetched': today, 'n': len(out),
                 'first_run': hist['runs'][0]['date'] if hist['runs'] else today},
        'cols': ['org_no', 'china_reg_no', 'name', 'type', 'status', 'reg_date', 'end_date', 'first_seen'],
        'rows': out,
    }
    io.open(DATA, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    dated = [r for r in out if r[5]]
    one_year = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    log(f'Etablissements norvegiens enregistres en Chine : {len(out)} ; '
        f'avec date d\'enregistrement : {len(dated)} ; enregistres depuis {one_year} : {sum(1 for r in dated if r[5] >= one_year)}')


if __name__ == '__main__':
    main()
