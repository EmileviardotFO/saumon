"""Sonde 8 nov : bulletin algues HI, Sernapesca (mortalite, FAN), DGA, NASA POWER, API de publications."""
import json, re, urllib.request, urllib.parse, os
UA = {'User-Agent': 'Mozilla/5.0 (salmon-outlook research probe)'}
os.makedirs('sonde_out', exist_ok=True)
def get(u, n=1500, save=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
            b = r.read(); ct = r.headers.get('content-type')
        print(f'\n=== {u}\n  {r.status} {ct} {len(b)} o')
        if save: open('sonde_out/' + save, 'wb').write(b)
        t = b.decode('utf-8', 'replace')
        return t
    except Exception as e:
        print(f'\n=== {u}\n  ERREUR {str(e)[:200]}'); return ''
def links(t, pat):
    L = sorted(set(re.findall(r'href="([^"]*' + pat + r'[^"]*)"', t)))
    print('  liens', pat, len(L)); [print('   ', l) for l in L[:40]]
def text(t, n=1500):
    s = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', t, flags=re.S); s = re.sub(r'<[^>]+>', ' ', s); s = re.sub(r'\s+', ' ', s)
    print('  TEXTE:', s[:n])
# --- HI algestatus
t = get('https://algestatus.hi.no/', save='hi_root.html'); links(t, 'statusrapport'); text(t, 2500)
t2 = get('https://algestatus.hi.no/statusrapporter', save='hi_list.html'); links(t2, 'statusrapport'); text(t2, 1500)
L = sorted(set(re.findall(r'href="([^"]*statusrapport-[^"]*)"', t + t2)))
if L:
    u = L[0] if L[0].startswith('http') else 'https://algestatus.hi.no' + L[0]
    t3 = get(u, save='hi_report.html'); text(t3, 4000)
for u in ['https://algestatus.hi.no/statusrapporter/statusrapport-29-mars-2026', 'https://algestatus.hi.no/api', 'https://algestatus.hi.no/sitemap.xml', 'https://algestatus.hi.no/rss', 'https://algestatus.hi.no/feed']:
    x = get(u); text(x, 1200)
# --- Sernapesca (WordPress ?)
for q in ['mortalidad', 'FAN', 'floracion', 'contingencia']:
    x = get('https://www.sernapesca.cl/wp-json/wp/v2/posts?per_page=10&search=' + q)
    try:
        for p in json.loads(x): print('   ', p['date'][:10], p['link'], re.sub('<[^>]+>', '', p['title']['rendered'])[:120])
    except Exception: print('  pas json', x[:200])
x = get('https://www.sernapesca.cl/?s=mortalidad'); links(x, 'mortalidad'); links(x, 'fan')
x = get('https://www.sernapesca.cl/informes/'); links(x, 'informe'); text(x, 800)
x = get('https://www.sernapesca.cl/wp-json/wp/v2/types'); print(x[:800])
# --- DGA
for u in ['https://snia.mop.gob.cl/dgasat/pages/dgasat_main/dgasat_main.htm', 'https://dga.mop.gob.cl/', 'https://snia.mop.gob.cl/BNAConsultas/reportes', 'https://explorador.cr2.cl/', 'https://www.cr2.cl/datos-de-caudales/']:
    x = get(u); text(x, 600); links(x, 'caudal')
# --- NASA POWER (soleil, pluie, vent) Reloncavi
x = get('https://power.larc.nasa.gov/api/temporal/daily/point?parameters=ALLSKY_SFC_SW_DWN,PRECTOTCORR,WS10M,T2M&community=AG&longitude=-72.6&latitude=-41.6&start=20260901&end=20261107&format=JSON')
try:
    d = json.loads(x); p = d['properties']['parameter']; print('  POWER', {k: list(v.items())[-3:] for k, v in p.items()}); print('  header', json.dumps(d.get('header'))[:400])
except Exception as e: print('  POWER pas lu', e, x[:300])
# --- publications
x = get('https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urllib.parse.urlencode({'query': '(TITLE_ABS:"salmon" AND (TITLE_ABS:"piscirickettsia" OR TITLE_ABS:"pancreas disease")) AND OPEN_ACCESS:y AND FIRST_PDATE:[2026-09-01 TO 2026-11-08]', 'format': 'json', 'pageSize': 5, 'resultType': 'core'}))
try:
    d = json.loads(x); print('  EPMC hits', d.get('hitCount')); [print('   ', r.get('firstPublicationDate'), r.get('journalInfo', {}).get('journal', {}).get('title'), r.get('title')[:100], r.get('doi')) for r in d['resultList']['result']]
except Exception as e: print('  EPMC', e, x[:200])
x = get('https://api.openalex.org/works?' + urllib.parse.urlencode({'search': 'salmon gill disease', 'filter': 'from_publication_date:2026-09-01,is_oa:true', 'per-page': 5, 'mailto': 'research@example.org'}))
try:
    d = json.loads(x); print('  OpenAlex', d['meta']['count']); [print('   ', r['publication_date'], r['title'][:100], (r.get('open_access') or {}).get('oa_url')) for r in d['results']]
except Exception as e: print('  OA', e, x[:200])
x = get('https://news.google.com/rss/search?q=' + urllib.parse.quote('Sernapesca mortalidad salmones when:30d') + '&hl=es-419&gl=CL&ceid=CL:es-419')
for m in re.findall(r'<item>.*?<title>(.*?)</title>.*?<pubDate>(.*?)</pubDate>', x, re.S)[:15]: print('   ', m[1][:16], m[0][:140])
x = get('https://www.vetinst.no/rss'); print(x[:300])
x = get('https://www.vetinst.no/nyheter/rss'); print(x[:300])
