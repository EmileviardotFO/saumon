#!/usr/bin/env python3
"""
data/search_index.json : toutes les lignes de tous les tableaux du tableau de bord, pour la recherche.

La page docs/production.html est ouverte dans un navigateur sans ecran (Playwright), avec les fichiers de
data/ servis en local ; chaque onglet est affiche tour a tour, puis on lit chaque tableau visible :
onglet, titre de la section, en-tetes de colonnes, cellules de chaque ligne. Les sous-titres des sections
(explications, methode) sont gardes aussi, pour les questions de definition.

    python3 scripts/build_search_index.py
"""
import asyncio
import json
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'search_index.json'
URL = 'https://emileviardotfo.github.io/saumon/docs/production.html'
MAX_ROWS = 400          # par tableau
MAX_CELL = 160

EXTRACT = r"""
(args) => {
  const [maxRows, maxCell] = args;
  const P = [...document.querySelectorAll('.panel[id$="View"]')].find(p => p.style.display === 'block' || (p.offsetParent && getComputedStyle(p).display !== 'none'));
  if (!P) return null;
  const clean = t => String(t || '').replace(/\s+/g, ' ').trim().slice(0, maxCell);
  const secOf = el => { let n = el; const titles = '.sig-title, .gm-t, .gm-h1, .bs-slot';
    while (n && n !== P) { let s = n.previousElementSibling;
      while (s) { if (s.matches && s.matches(titles)) return clean(s.textContent); const q = s.querySelectorAll ? [...s.querySelectorAll(titles)] : []; if (q.length) return clean(q[q.length - 1].textContent); s = s.previousElementSibling; }
      n = n.parentElement; }
    return ''; };
  const tables = [];
  P.querySelectorAll('table').forEach((t, ti) => {
    if (!t.offsetParent && getComputedStyle(t).display === 'none') return;
    let head = [...t.querySelectorAll('thead tr')].pop();
    let H = head ? [...head.children].map(c => clean(c.textContent)) : [];
    let rows = [...t.querySelectorAll('tbody tr, tfoot tr')];
    if (!head) { const all = [...t.querySelectorAll('tr')]; if (all.length && [...all[0].children].every(c => c.tagName === 'TH')) { H = [...all[0].children].map(c => clean(c.textContent)); rows = all.slice(1); } else rows = all; }
    const R = rows.slice(0, maxRows).map(r => [...r.children].map(c => clean(c.textContent))).filter(r => r.some(x => x));
    if (!R.length) return;
    tables.push({ sec: secOf(t), h: H, r: R });
  });
  const notes = [...P.querySelectorAll('.sig-sub, .gm-s, .gm-sub')].map(s => ({ sec: secOf(s), t: clean(s.textContent).length ? String(s.textContent).replace(/\s+/g, ' ').trim().slice(0, 1500) : '' })).filter(x => x.t.length > 40);
  return { panel: P.id.replace(/View$/, ''), tables, notes };
}
"""


async def main():
    from playwright.async_api import async_playwright
    t0 = time.time()
    out = {'built': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()), 'tabs': []}
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': 1500, 'height': 1000})

        async def route(r):
            u = r.request.url
            if 'emileviardotfo.github.io/saumon/' in u:
                f = ROOT / u.split('/saumon/', 1)[1].split('?')[0]
                if f.exists():
                    return await r.fulfill(path=str(f))
                return await r.fulfill(status=404, body='')
            if any(x in u for x in ('arcgisonline', 'openstreetmap', 'fonts.g')):
                return await r.fulfill(status=404, body='')
            return await r.continue_()
        await pg.route('**/*', route)
        await pg.goto(URL, wait_until='domcontentloaded', timeout=90000)
        await pg.wait_for_timeout(8000)
        views = await pg.evaluate("[...document.querySelectorAll('#viewToggle button[data-v]')].map(b => [b.dataset.v, b.textContent.trim()])")
        for v, label in views:
            try:
                await pg.evaluate(f"document.querySelector('#viewToggle button[data-v=\"{v}\"]').click()")
                await pg.wait_for_timeout(5000)
                d = await pg.evaluate(EXTRACT, [MAX_ROWS, MAX_CELL])
                if d:
                    d.update({'v': v, 'label': label})
                    out['tabs'].append(d)
                    print(f'  {label:32s} {len(d["tables"]):3d} tableaux, {sum(len(t["r"]) for t in d["tables"]):5d} lignes, {len(d["notes"])} notes')
            except Exception as e:  # noqa: BLE001
                print(f'  {label}: ERREUR {e}')
        await b.close()
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'ecrit {OUT} ({OUT.stat().st_size // 1024} ko) en {time.time() - t0:.0f} s')


if __name__ == '__main__':
    asyncio.run(main())
