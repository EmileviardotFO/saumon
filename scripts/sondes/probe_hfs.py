#!/usr/bin/env python3
"""
Sonde HFS (Heilsufrøðiliga Starvsstovan, Feroe) : le portail est en Oracle ADF, tout est rendu en JavaScript.
On rend les pages avec un navigateur sans tete, on liste les liens et les fichiers (xlsx, pdf, csv), on les
telecharge dans sonde_out/ et on imprime pour chaque classeur les feuilles, les en-tetes et les premieres lignes.
Tout ce qui compte est ecrit sur la sortie standard (le journal du workflow), les fichiers restent en artefact.

    python3 scripts/sondes/probe_hfs.py
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

OUT = 'sonde_out'
os.makedirs(OUT, exist_ok=True)
PAGES = [
    'https://www.hfs.fo/webcenter/portal/HFS/Aling',
    'https://www.hfs.fo/webcenter/portal/HFS/pages_aling/hagtl',
    'https://www.hfs.fo/webcenter/portal/HFS/pages_aling/hagtl/talavlaksialikjum',
]


def sh(cmd):
    print('$', cmd, flush=True)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(r.stdout[-3000:], r.stderr[-2000:], flush=True)
    return r.returncode


def ensure_playwright():
    try:
        import playwright  # noqa
    except ImportError:
        sh(f'{sys.executable} -m pip install -q playwright')
    sh(f'{sys.executable} -m playwright install chromium')
    sh(f'{sys.executable} -m playwright install-deps chromium || true')


def main():
    ensure_playwright()
    from playwright.sync_api import sync_playwright
    seen_links, files = {}, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(accept_downloads=True, locale='fo-FO', user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36')
        pg = ctx.new_page()
        net = []
        pg.on('response', lambda r: net.append((r.status, r.headers.get('content-type', '')[:40], r.url[:200])))
        queue = list(PAGES)
        done = set()
        while queue and len(done) < 40:
            url = queue.pop(0)
            if url in done:
                continue
            done.add(url)
            print('\n' + '=' * 100 + '\nPAGE', url, flush=True)
            try:
                pg.goto(url, timeout=90000, wait_until='networkidle')
                pg.wait_for_timeout(5000)
            except Exception as e:
                print('  goto failed:', str(e)[:300], flush=True)
                continue
            print('  title:', pg.title())
            txt = pg.inner_text('body')
            print('  text chars:', len(txt))
            print('  --- text (first 6000) ---')
            print(txt[:6000])
            links = pg.evaluate("[...document.querySelectorAll('a')].map(a=>[a.innerText.trim().replace(/\\s+/g,' ').slice(0,90), a.href]).filter(x=>x[1])")
            print('  --- links', len(links), '---')
            for t, h in links:
                if h not in seen_links:
                    seen_links[h] = t
                    print('   ', t, '|', h)
                hl = h.lower()
                if re.search(r'\.(xlsx|xls|csv|pdf)(\?|$)', hl) or 'content/conn' in hl or 'download' in hl:
                    files.append((t, h))
                elif 'hfs.fo/webcenter/portal/HFS' in h and ('aling' in hl or 'hagt' in hl) and h not in done and len(queue) < 60:
                    queue.append(h.split('?')[0])
            # tableaux rendus dans la page
            tables = pg.evaluate("[...document.querySelectorAll('table')].map(t=>[...t.querySelectorAll('tr')].slice(0,8).map(r=>[...r.children].map(c=>c.innerText.trim().slice(0,30)).join(' | ')).join('\\n')).filter(x=>x.length>40)")
            print('  --- tables', len(tables), '---')
            for t in tables[:15]:
                print(t, '\n   ...')
            # fichiers charges par la page (api, json)
            for st, ct, u in net[-80:]:
                if 'json' in ct or 'octet' in ct or 'excel' in ct or 'spreadsheet' in ct or 'pdf' in ct:
                    print('   net', st, ct, u)
        # telechargements
        print('\n' + '=' * 100 + '\nFILES', len(files))
        for t, h in files[:40]:
            name = re.sub(r'[^A-Za-z0-9._-]+', '_', urllib.parse.unquote(h.split('/')[-1].split('?')[0]))[:80] or 'file'
            path = os.path.join(OUT, name)
            try:
                with pg.expect_download(timeout=60000) as dl:
                    pg.evaluate("u => { const a = document.createElement('a'); a.href = u; a.download = ''; document.body.appendChild(a); a.click(); }", h)
                dl.value.save_as(path)
                print('  downloaded', t, '->', path, os.path.getsize(path))
            except Exception as e:
                try:
                    r = ctx.request.get(h, timeout=60000)
                    if r.ok:
                        open(path, 'wb').write(r.body())
                        print('  fetched', t, '->', path, os.path.getsize(path))
                    else:
                        print('  failed', h, r.status)
                except Exception as e2:
                    print('  failed', h, str(e)[:120], str(e2)[:120])
        b.close()
    # apercu des classeurs
    try:
        import openpyxl
    except ImportError:
        sh(f'{sys.executable} -m pip install -q openpyxl')
        import openpyxl
    for f in sorted(os.listdir(OUT)):
        if f.lower().endswith('.xlsx'):
            print('\n' + '-' * 100 + '\nXLSX', f)
            try:
                wb = openpyxl.load_workbook(os.path.join(OUT, f), data_only=True, read_only=True)
                for ws in wb.worksheets[:30]:
                    print(' sheet', ws.title, ws.max_row, ws.max_column)
                    for i, row in enumerate(ws.iter_rows(values_only=True)):
                        if i >= 8:
                            break
                        print('   ', [str(v)[:22] if v is not None else None for v in row[:16]])
            except Exception as e:
                print('  cannot read:', e)
    json.dump({'links': seen_links, 'files': files}, open(os.path.join(OUT, 'hfs_links.json'), 'w'), ensure_ascii=False, indent=1)
    print('\nDONE')


if __name__ == '__main__':
    main()
