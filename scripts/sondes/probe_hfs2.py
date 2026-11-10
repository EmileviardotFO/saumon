#!/usr/bin/env python3
"""
Sonde HFS n° 2 : exporte en Excel les trois tables du portail (Tal av laksi = poissons par site et par mois,
Lúsatøl = comptages de poux par site, Heilivágur = traitements par site) via le bouton « Flyt út til Excel »,
sinon lit la table rendue ; imprime des resumes complets dans le journal.

    python3 scripts/sondes/probe_hfs2.py
"""
import collections
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys

OUT = 'sonde_out'
os.makedirs(OUT, exist_ok=True)
PAGES = {
    'fish': 'https://www.hfs.fo/webcenter/portal/HFS/pages_aling/hagtl/talavlaksialikjum',
    'lice': 'https://www.hfs.fo/webcenter/portal/HFS/pages_aling/hagtl/lsatl',
    'med': 'https://www.hfs.fo/webcenter/portal/HFS/pages_aling/hagtl/alingvigerirtest',
}


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print('$', cmd, '->', r.returncode, flush=True)


def ensure():
    try:
        import playwright  # noqa
    except ImportError:
        sh(f'{sys.executable} -m pip install -q playwright openpyxl pandas')
    sh(f'{sys.executable} -m playwright install chromium')
    sh(f'{sys.executable} -m playwright install-deps chromium || true')


def num(s):
    s = str(s).strip().replace(' ', '').replace(' ', '')
    if not s:
        return None
    if re.fullmatch(r'-?\d{1,3}(\.\d{3})+', s):      # 1.107.988 -> milliers a points
        return float(s.replace('.', ''))
    s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def main():
    ensure()
    from playwright.sync_api import sync_playwright
    tables = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(accept_downloads=True, user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36')
        pg = ctx.new_page()
        for key, url in PAGES.items():
            print('\n' + '=' * 100 + '\n', key, url, flush=True)
            try:
                pg.goto(url, timeout=90000, wait_until='networkidle')
                pg.wait_for_timeout(4000)
            except Exception as e:
                print('  goto failed', str(e)[:200])
                continue
            # 1) export Excel
            got = None
            for sel in ['text=Flyt út til Excel', 'a:has-text("Excel")', 'button:has-text("Excel")', '[title*="Excel"]']:
                try:
                    loc = pg.locator(sel).first
                    if loc.count() == 0:
                        continue
                    with pg.expect_download(timeout=90000) as dl:
                        loc.click()
                    d = dl.value
                    name = re.sub(r'[^A-Za-z0-9._-]+', '_', d.suggested_filename or f'{key}.xlsx')
                    path = os.path.join(OUT, f'hfs_{key}_{name}')
                    d.save_as(path)
                    got = path
                    print('  export ->', path, os.path.getsize(path), flush=True)
                    break
                except Exception as e:
                    print('  export via', sel, 'failed:', str(e)[:160], flush=True)
            rows = None
            if got:
                rows = read_export(got)
            if not rows:
                # 2) table rendue : faire defiler pour charger toutes les lignes, puis lire les cellules
                print('  reading rendered table', flush=True)
                for _ in range(60):
                    pg.mouse.wheel(0, 20000)
                    pg.wait_for_timeout(400)
                rows = pg.evaluate("""() => { const T = [...document.querySelectorAll('table')].filter(t => t.querySelectorAll('tr').length > 20).sort((a, b) => b.querySelectorAll('tr').length - a.querySelectorAll('tr').length);
                    if (!T.length) return []; return [...T[0].querySelectorAll('tr')].map(r => [...r.querySelectorAll('td,th')].map(c => c.innerText.trim().slice(0, 80))).filter(r => r.length >= 5 && r.every(c => c.length < 80)); }""")
                print('  rendered rows', len(rows))
            tables[key] = rows or []
            print('  rows', len(tables[key]), 'first', [str(x)[:40] for x in (tables[key][0] if tables[key] else [])][:8], 'last', [str(x)[:40] for x in (tables[key][-1] if tables[key] else [])][:8], flush=True)
            json.dump(tables[key], open(os.path.join(OUT, f'hfs_{key}.json'), 'w'), ensure_ascii=False)
        b.close()
    summarize(tables)
    print('\nDONE')


def read_export(path):
    try:
        import pandas as pd
        raw = open(path, 'rb').read()
        if raw[:200].lstrip().lower().startswith(b'<'):      # export ADF : HTML deguise en .xls
            sh(f'{sys.executable} -m pip install -q lxml html5lib beautifulsoup4')
            txt = raw.decode('utf-8', 'replace')
            dfs = pd.read_html(io.StringIO(txt), header=None)
            df = max(dfs, key=len)
        elif path.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(path, header=None, dtype=str)
        else:
            df = pd.read_csv(io.StringIO(raw.decode('utf-8', 'replace')), sep=None, engine='python', header=None, dtype=str)
        rows = df.fillna('').astype(str).values.tolist()
        print('  export rows', len(rows), 'cols', len(rows[0]) if rows else 0, 'head', [r[:8] for r in rows[:3]])
        return rows
    except Exception as e:
        print('  cannot read export:', str(e)[:200])
        try:
            print('  head bytes:', open(path, 'rb').read(300))
        except Exception:
            pass
        return None


def pdate(s):
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', str(s))
    if m:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', str(s))
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def summarize(T):
    # ---- poissons par site et par mois
    R = T.get('fish') or []
    recs = []
    for r in R:
        d = next((pdate(x) for x in r if pdate(x)), None)
        if not d:
            continue
        nums = [num(x) for x in r]
        n = next((v for v in reversed(nums) if v is not None), None)
        site = next((x for x in r if re.fullmatch(r'A-\d+', str(x).strip())), None)
        co = next((x for x in r if 'P/F' in str(x) or 'P/f' in str(x)), None)
        name = r[2] if len(r) > 2 else ''
        recs.append((d, site, name, co, n))
    print('\n' + '#' * 100 + '\nFISH rows', len(recs))
    if recs:
        ds = sorted({x[0] for x in recs})
        print(' dates', ds[0], '->', ds[-1], 'n dates', len(ds), 'sites', len({x[1] for x in recs}), 'companies', sorted({x[3] for x in recs if x[3]}))
        bym = collections.defaultdict(lambda: collections.defaultdict(float))
        for d, site, name, co, n in recs:
            bym[d][co or '?'] += n or 0
        print(' month | total | by company')
        for d in ds:
            print(' ', d, round(sum(bym[d].values()) / 1e6, 3), 'M |', {k: round(v / 1e6, 3) for k, v in sorted(bym[d].items())})
        last = ds[-1]
        print(' latest month by site:')
        for d, site, name, co, n in sorted([x for x in recs if x[0] == last], key=lambda x: -(x[4] or 0)):
            print('  ', site, name, co, n)
    # ---- poux
    R = T.get('lice') or []
    L = []
    for r in R:
        d = next((pdate(x) for x in r if pdate(x)), None)
        if not d:
            continue
        v = num(r[0])
        site = next((x for x in r if re.fullmatch(r'A-\d+', str(x).strip())), None)
        co = next((x for x in r if 'P/F' in str(x) or 'P/f' in str(x)), None)
        L.append((d, site, co, v))
    print('\n' + '#' * 100 + '\nLICE rows', len(L))
    if L:
        ds = sorted({x[0] for x in L})
        print(' dates', ds[0], '->', ds[-1], 'counts', len(L), 'sites', len({x[1] for x in L}))
        byw = collections.defaultdict(list)
        for d, site, co, v in L:
            if v is not None:
                byw[d.isocalendar()[:2]].append(v)
        print(' weekly mean adult females (all sites counted that week), last 3 years:')
        for (y, w), vs in sorted(byw.items()):
            if y >= 2024:
                print(f'  {y}-W{w:02d} n={len(vs)} mean={sum(vs)/len(vs):.2f} max={max(vs):.2f} share>0.5={sum(v > 0.5 for v in vs)/len(vs):.0%}')
        bym = collections.defaultdict(list)
        for d, site, co, v in L:
            if v is not None:
                bym[(d.year, d.month)].append(v)
        print(' monthly mean by year/month:')
        for y in sorted({k[0] for k in bym}):
            print(' ', y, [round(sum(bym[(y, m)]) / len(bym[(y, m)]), 2) if (y, m) in bym else None for m in range(1, 13)])
    # ---- traitements
    R = T.get('med') or []
    M = []
    for r in R:
        d = next((pdate(x) for x in r if pdate(x)), None)
        if not d:
            continue
        M.append((d, r))
    print('\n' + '#' * 100 + '\nMED rows', len(M))
    if M:
        ds = sorted({x[0] for x in M})
        print(' dates', ds[0], '->', ds[-1])
        c = collections.Counter()
        for d, r in M:
            typ = next((x for x in r if str(x).strip() in ('Bað', 'Fóður', 'Bad', 'Fodur')), '?')
            prod = r[6] if len(r) > 6 else '?'
            c[(d.year, typ, str(prod)[:28])] += 1
        for k, v in sorted(c.items()):
            print('  ', k, v)
        print(' last 15:')
        for d, r in sorted(M)[-15:]:
            print('  ', [str(x)[:30] for x in r])


if __name__ == '__main__':
    main()
