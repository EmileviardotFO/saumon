#!/usr/bin/env python3
"""
Sources qui refusent les requetes simples (403) ou ne s'affichent qu'en JavaScript : lues avec un navigateur sans tete.
  Salmon Scotland  -> farming/donnees_gb/salmon_scotland_mortality.csv  (mortalite mensuelle par ferme, cause, statut)
  Marine Directorate, enquete annuelle -> farming/donnees_gb/survey_T*.csv
  Mattilsynet, classes de qualite a l'abattage (Looker Studio) -> farming/donnees_no/mattilsynet_quality_*.txt / .csv

    python3 scripts/fetch_browser_sources.py
"""
import csv, io, os, re, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GB, NO = os.path.join(ROOT, 'farming/donnees_gb'), os.path.join(ROOT, 'farming/donnees_no')
MON = {m.lower(): i + 1 for i, m in enumerate(['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'])}


def salmon_scotland(ctx):
    import pandas as pd
    pg = ctx.new_page()
    links = {}
    for page in range(0, 12):
        try:
            pg.goto('https://www.salmonscotland.co.uk/reports' + (f'?page={page}' if page else ''), timeout=90000, wait_until='domcontentloaded')
            pg.wait_for_timeout(2500)
        except Exception as e:
            print('  index failed', str(e)[:120]); break
        found = pg.evaluate("[...document.querySelectorAll('a')].map(a => [a.getAttribute('href') || '', a.innerText.trim()]).filter(x => /monthly-mortality/i.test(x[0]))")
        n0 = len(links)
        for h, t in found:
            links.setdefault(h.split('?')[0], t)
        if page == 0:
            print('  index title:', pg.title(), '| links on first page:', len(links), '| text:', pg.inner_text('body')[:200].replace('\n', ' '))
        if len(links) == n0 and page:
            break
    print('  Salmon Scotland monthly reports:', len(links))
    # chaque lien renvoie directement le PDF du mois (le nom du lien ne correspond pas toujours au mois : le
    # constructeur lit le mois dans le PDF). On ne retelecharge pas un PDF deja present, sauf les 3 plus recents
    # de la liste (Salmon Scotland corrige parfois le rapport du mois precedent).
    out = os.path.join(GB, 'salmon_scotland')
    os.makedirs(out, exist_ok=True)
    got = kept = 0
    for n, h in enumerate(links):
        u = h if h.startswith('http') else 'https://www.salmonscotland.co.uk' + h
        dest = os.path.join(out, re.sub(r'[^a-z0-9-]+', '-', u.rstrip('/').split('/')[-1].lower()) + '.pdf')
        if os.path.exists(dest) and n >= 3:
            kept += 1
            continue
        try:
            # requete faite depuis la page de la liste elle-meme (meme origine, memes cookies, pile reseau du navigateur) :
            # une requete directe hors navigateur recoit un 403
            import base64
            res = pg.evaluate("""async u => { const r = await fetch(u, {credentials: 'include'}); const b = new Uint8Array(await r.arrayBuffer());
                let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768)); return [r.status, r.headers.get('content-type') || '', btoa(s)]; }""", u)
            b = base64.b64decode(res[2])
            if b[:4] != b'%PDF':
                try:
                    with pg.expect_download(timeout=30000) as dl:
                        pg.evaluate("u => { const a = document.createElement('a'); a.href = u; a.download = ''; document.body.appendChild(a); a.click(); }", u)
                    b = open(dl.value.path(), 'rb').read()
                except Exception as e2:
                    print('   clic :', str(e2)[:60])
            if b[:4] == b'%PDF':
                open(dest, 'wb').write(b)
                got += 1
            else:
                print('   pas un PDF :', h, res[0], res[1], len(b))
                if got == 0 and n >= 3:
                    print('   abandon : le site refuse les telechargements')
                    break
        except Exception as e:
            print('   failed', h, str(e)[:100])
    print(f'ok salmon_scotland : {got} PDF telecharges, {kept} deja presents')
    pg.close()


def survey(ctx):
    pg = ctx.new_page()
    try:
        pg.goto('https://data.marine.gov.scot/node/2606', timeout=90000, wait_until='domcontentloaded'); pg.wait_for_timeout(3000)
        links = pg.evaluate("[...document.querySelectorAll('a')].map(a => a.href).filter(h => /\\.csv/i.test(h))")
        print('  survey csv links:', len(links))
        for h in links:
            m = re.search(r'(T\d{1,2}|Appendix%20\d)', h)
            if not m or m.group(1) not in ('T24', 'T25', 'T27', 'T28', 'T29', 'T30', 'T37'):
                continue
            r = ctx.request.get(h, timeout=90000)
            if r.ok and len(r.body()) > 50:
                open(os.path.join(GB, f'survey_{m.group(1)}.csv'), 'wb').write(r.body())
                print('ok survey', m.group(1), len(r.body()), r.text()[:160].replace('\n', ' | '))
            else:
                print('  failed', r.status, h[-60:])
    except Exception as e:
        print('  survey failed', str(e)[:200])
    pg.close()


def mattilsynet(ctx):
    pg = ctx.new_page()
    net = []
    pg.on('response', lambda r: net.append(r) if ('batchedDataV2' in r.url or 'getData' in r.url) else None)
    url = 'https://lookerstudio.google.com/reporting/75f2fc95-a9de-4df0-9149-8e05ea20a771/page/p_tdnxxmekxd'
    try:
        pg.goto(url, timeout=120000, wait_until='networkidle'); pg.wait_for_timeout(12000)
    except Exception as e:
        print('  looker goto:', str(e)[:160])
    print('  looker title:', pg.title(), '| url:', pg.url[:120])
    txt = pg.inner_text('body')
    open(os.path.join(NO, 'mattilsynet_quality_page1.txt'), 'w', encoding='utf-8').write(txt)
    print('  page text chars', len(txt)); print(txt[:1800])
    # autres pages du rapport (menu de gauche) : on clique chaque entree et on garde le texte
    try:
        items = pg.evaluate("[...document.querySelectorAll('[role=tab], .navigation-item, mat-list-item, a')].map(e => e.innerText.trim()).filter(t => t && t.length < 60)")
        print('  nav items:', list(dict.fromkeys(items))[:25])
        for name in list(dict.fromkeys(items))[:8]:
            if re.search(r'(?i)tabell|produksjonsomr|nasjonal', name):
                try:
                    pg.get_by_text(name, exact=True).first.click(timeout=8000); pg.wait_for_timeout(9000)
                    t2 = pg.inner_text('body')
                    fn = 'mattilsynet_quality_' + re.sub(r'[^a-z0-9]+', '_', name.lower())[:30] + '.txt'
                    open(os.path.join(NO, fn), 'w', encoding='utf-8').write(t2)
                    print('  page', name, len(t2)); print(t2[:1500])
                except Exception as e:
                    print('  click failed', name, str(e)[:100])
    except Exception as e:
        print('  nav failed', str(e)[:160])
    # reponses de donnees interceptees
    for i, r in enumerate(net[:12]):
        try:
            b = r.text()
            open(os.path.join(NO, f'mattilsynet_quality_raw_{i}.json'), 'w', encoding='utf-8').write(b)
            print('  data response', i, r.url[:90], len(b))
        except Exception as e:
            print('  data response unreadable', str(e)[:80])
    pg.close()


def newfoundland(ctx):
    """Terre-Neuve : page de publication des eleveurs (NAIA) et deux rapports en « flipbook ». On liste les liens et les cadres,
    on garde tout PDF charge par la page, et le texte des pages du flipbook quand il est lisible."""
    out = os.path.join(ROOT, 'farming', 'donnees_ca', 'nl')
    os.makedirs(out, exist_ok=True)
    pg = ctx.new_page()
    seen = []

    def on_resp(r):
        try:
            ct = r.headers.get('content-type', '')
            u = r.url
            if 'pdf' in ct or re.search(r'\.pdf(\?|$)', u, re.I):
                b = r.body()
                if b[:4] == b'%PDF':
                    name = re.sub(r'[^A-Za-z0-9._-]+', '_', u.split('?')[0].split('/')[-1])[-80:] or 'doc.pdf'
                    open(os.path.join(out, name if name.endswith('.pdf') else name + '.pdf'), 'wb').write(b)
                    print('   PDF', len(b), u[:200])
            elif 'json' in ct or 'image' in ct and len(seen) < 400:
                seen.append((ct[:20], u[:220]))
        except Exception:
            pass
    pg.on('response', on_resp)
    for u in ('https://naia.ca/index.php/media/public-reporting', 'https://naia.ca/index.php/media/public-reporting-archived-sea-lice-numbers'):
        try:
            r = pg.goto(u, timeout=90000, wait_until='networkidle'); pg.wait_for_timeout(4000)
            print(' ', r.status if r else '?', u, '| title:', pg.title())
            print('   text:', pg.inner_text('body')[:1500].replace('\n', ' | '))
            for t, h in pg.evaluate("[...document.querySelectorAll('a')].map(a => [a.innerText.trim().slice(0, 80), a.href]).filter(x => x[1] && !/facebook|twitter|linkedin|instagram|#$/.test(x[1]))"):
                if re.search(r'(?i)report|lice|incident|portal|download|archiv|mortal|public', t + ' ' + h):
                    print('   link:', t, '|', h)
            print('   frames:', [f.url[:200] for f in pg.frames][:12])
            print('   iframes/embeds:', pg.evaluate("[...document.querySelectorAll('iframe,embed,object,img')].map(e => (e.src || e.data || '').slice(0, 200)).filter(x => x && !/logo|icon/i.test(x)).slice(0, 25)"))
        except Exception as e:
            print('   failed', u, str(e)[:160])
    for slug in ('caia-2024-sustainability-report', 'economic-impacts-of-the-newfoundland-and-labrador-aquaculture-industry'):
        del seen[:]
        try:
            r = pg.goto('https://flipbooklets.com/pdfflipbooklets/' + slug, timeout=90000, wait_until='networkidle'); pg.wait_for_timeout(8000)
            print(' ', r.status if r else '?', slug, '| title:', pg.title(), '| frames:', [f.url[:160] for f in pg.frames][:6])
            html = pg.content()
            print('   pdf refs in html:', sorted(set(re.findall(r'[\w:/.%~-]+\.pdf[^"\'\s<>]{0,60}', html)))[:10])
            print('   resources:', sorted({u for _, u in seen})[:25])
            txt = ''
            for f in pg.frames:
                try:
                    txt += f.evaluate("document.body ? document.body.innerText : ''") + '\n'
                except Exception:
                    pass
            open(os.path.join(out, slug + '.txt'), 'w', encoding='utf-8').write(txt)
            print('   text chars:', len(txt), '|', txt[:600].replace('\n', ' | '))
        except Exception as e:
            print('   failed', slug, str(e)[:160])
    pg.close()


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(accept_downloads=True, locale='en-GB', user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36')
        for fn in (newfoundland, salmon_scotland, survey, mattilsynet):
            print('\n' + '=' * 80 + '\n' + fn.__name__.upper(), flush=True)
            try:
                fn(ctx)
            except Exception as e:
                print('ERREUR', fn.__name__, repr(e)[:300])
        b.close()
    print('FIN')


if __name__ == '__main__':
    main()
