#!/usr/bin/env python3
"""Veille des evenements de mortalite (algues, meduses, maladies, oxygene, tempetes...) dans tous les bassins.

Trois sources, fusionnees dans data/events.json :
  1. presse : flux RSS directs (iLaks, Kyst.no, SalmonBusiness, Fish Farming Expert, Salmonexpert.cl, Fish Farmer)
     + recherches Google News par bassin et par langue (norvegien, espagnol, islandais, anglais, danois/feroien) ;
     chaque article est garde s'il contient un mot de mortalite ET un mot d'elevage, puis classe par cause et par bassin ;
  2. Ecosse : tableur mensuel du Fish Health Inspectorate (mortalites declarees par site, avec la cause) ;
  3. evenements saisis a la main (cle "manual"), jamais ecrases par le script.

Rien ne bloque la mise a jour : une source qui ne repond pas est notee dans meta.status et le reste continue.
"""
import json, re, sys, time, html, hashlib, io, datetime as dt
import urllib.request, urllib.parse
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

OUT = 'data/events.json'
KEEP_DAYS = 3 * 365          # profondeur de l'historique presse conserve
UA = {'User-Agent': 'Mozilla/5.0 (saumon dashboard; +https://emileviardotfo.github.io/saumon/)'}

# ------------------------------------------------------------------ vocabulaire
# causes : chaque motif est une expression reguliere insensible a la casse ; un article peut avoir plusieurs causes
CAUSES = {
    'algae': [
        r'alg(e|ae|a|as|er|ene)?[ -]?(bloom|oppbl[oø]mstring|blomstring|flor|invasion)', r'algeoppbl[oø]mstring', r'\balgetap', r'algeangrep', r'algesituasjon', r'giftige? alger',
        r'harmful algal', r'\balgas?\b', r'\balger\b', r'algal\b', r'\bHABs?\b', r'plankton bloom', r'phytoplankton', r'microalga', r'microalgas?', r'fitoplancton',
        r'floraci[oó]n(es)? alga', r'bloom de algas', r'\bFAN\b', r'marea roja', r'\bþörunga', r'þörungabl[oó]m', r'\balgur',
        r'pseudochattonella', r'chrysochromulina', r'prymnesium', r'heterosigma', r'alexandrium', r'karenia', r'chaetoceros',
        r'leptocylindrus', r'dictyocha', r'pseudo-?nitzschia', r'cochlodinium', r'margalefidinium', r'gymnodinium', r'skeletonema',
    ],
    'jellyfish': [
        r'manet(er|ene|angrep|invasjon)?\b', r'brennmanet', r'glassmanet', r'kammanet', r'jellyfish', r'medusa', r'medusas', r'aguaviva',
        r'marglytt', r'hydrozo', r'muggiaea', r'apolemia', r'cyanea', r'aurelia', r'pelagia', r'siphonophor', r'salp(s|er)?\b',
    ],
    'gill': [r'\bgills?\b', r'g[aæ]lle(sykdom|skade|helse|problem)', r'\bAGD\b', r'amoebic gill', r'\bCGD\b', r'complex gill', r'branquial', r'tálknveik', r'tálknaskemmd'],
    'oxygen': [r'oksygen(svikt|mangel|nivå)', r'lavt oksygen', r'low oxygen', r'hypoxi', r'anoxi', r'deoxygen', r'ox[ií]geno (bajo|disuelto)', r'hipoxia', r'súrefnis'],
    'temperature': [r'heat ?wave', r'hetebølge', r'marine heatwave', r'high (sea|water) temperature', r'h[øo]y(e)? (sjø)?temperatur', r'ola de calor',
                    r'temperaturas? (alta|elevada)', r'super-?chill', r'superkj[øo]l', r'kuldesjokk', r'iskald', r'cold snap', r'ni[ñn]o', r'vetrarkulda', r'kuldakast'],
    'disease': [r'\bILA\b', r'\bISA\b', r'infeksi[øo]s lakseanemi', r'infectious salmon an(a)?emia', r'anemia infecciosa', r'\bPD\b', r'pankreassykdom', r'pancreas disease',
                r'\bSRS\b', r'piscirickettsi', r'\bBKD\b', r'renibacter', r'\bIPN\b', r'\bCMS\b', r'hjertesprekk', r'\bHSMB\b', r'vintersår', r'winter ulcer', r'moritella',
                r'tenacibacul', r'yersini', r'pasteurell', r'virus', r'bacteri', r'sjúkdóm', r'blóðþorra', r'\bISAV\b', r'lakselus', r'sea lice', r'\bcaligus', r'\blús\b'],
    'treatment': [r'avlusing', r'delousing', r'thermolicer', r'optilicer', r'hydrolicer', r'termisk behandling', r'thermal treatment', r'mechanical (treatment|delousing)',
                  r'behandlingsdødelighet', r'treatment mortality', r'tratamiento', r'handling'],
    'storm': [r'\bstorm', r'uvær', r'orkan', r'temporal', r'tormenta', r'óveð', r'r[øo]mming', r'escape(d|s)?\b', r'\bfuga\b', r'escapó', r'strok(u|ið)', r'sjókví(a)? (brast|skemmd)'],
}
# mortalite : au moins un de ces mots, sinon l'article n'est pas garde (evite les articles scientifiques ou commerciaux)
MORT = [r'd[øo]d(e|fisk|t)?\b', r'd[øo]delighet', r'tok livet', r'drept', r'omkom', r'massed[øo]d', r'fiskeslakt', r'n[øo]dslakt', r'mortal', r'mortalidad', r'muert[oa]s?', r'p[eé]rdida', r'perd(ió|ieron)',
        r'die-?off', r'dead fish', r'deaths?\b', r'died', r'killed', r'kills?\b', r'tons? of (dead|fish)', r'toneladas de (mortalidad|peces|salm)',
        r'dauð', r'drápust', r'fiskadauð', r'laxadauð', r'deyð', r'deydu', r'dødsfald', r'contingencia', r'tap av fisk', r'emergency harvest', r'cosecha anticipada']
# mots faibles (pertes financieres possibles) : gardes seulement si une cause est reconnue
WEAK = [r'losses?\b', r'\blost\b', r'p[eé]rdidas?', r'\btapt', r'\btap\b', r'tjón']
FARM = [r'laks', r'salmon', r'salm[oó]n', r'salmonid', r'oppdrett', r'fish ?farm', r'piscicult', r'acuicult', r'aquacult', r'centro(s)? de cultivo', r'salmoner',
        r'\blax', r'laxeld', r'sjókví', r'fiskeld', r'\balibr', r'aliboð', r'havbruk', r'\bmerd', r'\bcages?\b', r'jaula', r'\bpens?\b', r'\bfarm', r'oppdretter', r'lokalitet', r'anlegg', r'algetap', r'\bcentros?\b', r'concesi[oó]n',
        r'bakkafrost', r'mowi', r'salmar', r'ler[øo]y', r'grieg', r'cermaq', r'aquachile', r'multiexport', r'arnarlax', r'arctic fish', r'kaldv[ií]k', r'scottish sea farms',
        r'cooke', r'tassal', r'huon', r'camanchaca', r'blumar', r'australis', r'hiddenfjord', r'nova sea', r'eide fjordbruk', r'lingalaks', r'sea site', r'smolt', r'trucha', r'trout', r'coho']

# bassin : mots qui le designent dans le texte (le bassin de la requete sert de repli)
BASINS = {
    'NO': [r'norw', r'norge', r'noreg', r'norsk', r'nordland', r'troms', r'finnmark', r'vestland', r'rogaland', r'agder', r'møre', r'trøndelag', r'hordaland', r'sunnmøre',
           r'helgeland', r'lofoten', r'vesterålen', r'hardanger', r'ryfylke', r'produksjonsområde', r'\bPO ?\d', r'mowi', r'salmar', r'lerøy', r'grieg', r'nova sea', r'cermaq norway',
           r'skagerrak', r'sørlandet', r'vestlandet', r'mattilsynet', r'fiskeridirektoratet', r'barentswatch'],
    'CL': [r'chile', r'chilen', r'los lagos', r'ays[eé]n', r'magallanes', r'chilo[eé]', r'puerto montt', r'sernapesca', r'subpesca', r'\bACS\b', r'agrupaci[oó]n de concesiones',
           r'aquachile', r'multiexport', r'camanchaca', r'blumar', r'australis', r'ventisqueros', r'yadran', r'cermaq chile', r'mowi chile', r'cooke chile', r'salmones austral',
           r'quell[oó]n', r'calbuco', r'comau', r'reloncav'],
    'IS': [r'iceland', r'ísland', r'island(sk|ic)', r'westfjord', r'vestfir', r'austfir', r'eastfjord', r'arnarlax', r'arctic fish', r'kaldvík', r'ice fish farm', r'háafell',
           r'mast\b', r'matvælastofnun', r'tálknaf', r'patreksf', r'dýraf', r'berufj', r'berufir', r'reyðarf', r'fáskrúðsf', r'stöðvarf', r'ísafjarðardj', r'arnarf', r'önundarf', r'eyjaf'],
    'GB': [r'scotland', r'scottish', r'shetland', r'orkney', r'hebrides', r'skye', r'loch ', r'argyll', r'highland', r'sepa\b', r'fish health inspectorate', r'mowi scotland',
           r'scottish sea farms', r'bakkafrost scotland', r'cooke scotland', r'loch duart', r'kames', r'organic sea harvest', r'salmon scotland'],
    'FO': [r'faroe', r'færø', r'føroy', r'fær[øo]ysk', r'bakkafrost', r'hiddenfjord', r'luna\b', r'mowi faroe', r'heilsufrøði', r'havbúnað', r'tórshavn', r'klaksvík'],
    'CA': [r'canada', r'canadian', r'british columbia', r'\bB\.?C\.?\b', r'new brunswick', r'nova scotia', r'newfoundland', r'cooke aquaculture', r'grieg (nl|newfoundland)',
           r'mowi canada', r'cermaq canada', r'bay of fundy', r'fortune bay'],
    'IE': [r'ireland', r'irish', r'connemara', r'galway', r'donegal', r'bim\b', r'mowi ireland'],
    'AU': [r'tasmania', r'australia', r'huon', r'tassal', r'petuna', r'macquarie harbour'],
    'NZ': [r'new zealand', r'marlborough', r'new zealand king salmon', r'mt cook'],
    'US': [r'maine', r'washington state', r'alaska', r'cooke (usa|maine)'],
}

def rx(lst): return re.compile('|'.join(f'(?:{p})' for p in lst), re.I)
RC = {k: rx(v) for k, v in CAUSES.items()}
RM, RF, RW = rx(MORT), rx(FARM), rx(WEAK)
RB = {k: rx(v) for k, v in BASINS.items()}

# ------------------------------------------------------------------ sources presse
FEEDS = [  # (url, bassin par defaut, langue)
    ('https://ilaks.no/feed/', 'NO', 'no'),
    ('https://www.kyst.no/rss', 'NO', 'no'),
    ('https://www.salmonbusiness.com/feed/', None, 'en'),
    ('https://www.fishfarmingexpert.com/rss', None, 'en'),
    ('https://www.fishfarmermagazine.com/feed/', None, 'en'),
    ('https://www.salmonexpert.cl/rss', 'CL', 'es'),
    ('https://thefishsite.com/rss', None, 'en'),
]
def gnews(q, hl, gl, ceid): return 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q + ' when:60d', 'hl': hl, 'gl': gl, 'ceid': ceid})
GQ = [
    (gnews('(alger OR algeoppblomstring OR Pseudochattonella OR Chrysochromulina OR manet OR brennmanet OR massedød OR "økt dødelighet" OR nødslakt OR oksygensvikt) laks', 'no', 'NO', 'NO:no'), 'NO', 'no'),
    (gnews('(dødelighet OR "døde fisk" OR vintersår OR gjellesykdom OR ILA) oppdrett laks', 'no', 'NO', 'NO:no'), 'NO', 'no'),
    (gnews('(FAN OR "floración algal" OR "bloom de algas" OR microalgas OR medusas OR "mortalidad masiva" OR Heterosigma OR Pseudochattonella OR Alexandrium) salmón', 'es-419', 'CL', 'CL:es-419'), 'CL', 'es'),
    (gnews('(mortalidad OR "contingencia" OR SRS OR caligus OR "anemia infecciosa") salmoneras Sernapesca', 'es-419', 'CL', 'CL:es-419'), 'CL', 'es'),
    (gnews('(laxadauði OR fiskadauði OR þörungar OR marglytta OR vetrarsár OR "dauður fiskur" OR blóðþorri) laxeldi', 'is', 'IS', 'IS:is'), 'IS', 'is'),
    (gnews('Iceland salmon farm (mortality OR "mass death" OR algae OR jellyfish OR "winter ulcer" OR ISA)', 'en', 'GB', 'GB:en'), 'IS', 'en'),
    (gnews('Scotland salmon farm (mortality OR "algal bloom" OR jellyfish OR "gill disease" OR plankton OR deaths)', 'en', 'GB', 'GB:en'), 'GB', 'en'),
    (gnews('Faroe salmon (mortality OR algae OR jellyfish OR ISA OR deaths)', 'en', 'GB', 'GB:en'), 'FO', 'en'),
    (gnews('(laksur OR alibrúk) deyð OR deydu OR algur', 'da', 'DK', 'DK:da'), 'FO', 'fo'),
    (gnews('salmon farm (Canada OR "British Columbia" OR "New Brunswick" OR Newfoundland) (mortality OR "algal bloom" OR "die-off" OR deaths OR oxygen)', 'en', 'CA', 'CA:en'), 'CA', 'en'),
    (gnews('salmon farm (Ireland OR Tasmania OR "New Zealand") (mortality OR "algal bloom" OR jellyfish OR heatwave OR deaths)', 'en', 'GB', 'GB:en'), None, 'en'),
]

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()

def strip(s): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()

def parse_feed(raw):
    out = []; root = ET.fromstring(raw)
    for it in root.iter():
        tag = it.tag.split('}')[-1]
        if tag not in ('item', 'entry'): continue
        # attention : un element XML sans enfant est "faux" en Python, d'ou les tests explicites a None
        def g(*names):
            for n in names:
                e = next((c for c in it if c.tag.split('}')[-1] == n), None)
                if e is not None: return e
            return None
        t, l, d, s = g('title'), g('link'), g('pubDate', 'published', 'updated', 'date'), g('description', 'summary')
        link = (l.get('href') if l is not None and l.get('href') else (l.text if l is not None else '')) or ''
        src = g('source')
        out.append({'title': strip(t.text if t is not None else ''), 'url': link.strip(), 'summary': strip(s.text if s is not None else '')[:400],
                    'date': (d.text or '').strip() if d is not None else '', 'source': strip(src.text) if src is not None and src.text else ''})
    return out

def to_date(s):
    if not s: return None
    try: return parsedate_to_datetime(s).date()
    except Exception: pass
    try: return dt.date.fromisoformat(s[:10])
    except Exception: return None

def classify(title, summary, basin0):
    txt = f'{title} {summary}'
    if not RF.search(txt): return None
    causes = [k for k, r in RC.items() if r.search(txt)]
    if not RM.search(txt) and not (causes and RW.search(txt)): return None
    basins = [k for k, r in RB.items() if r.search(txt)]
    if not basins and basin0: basins = [basin0]
    return {'causes': causes or ['unspecified'], 'basins': basins or ['other']}

def news_items(status):
    items = []
    for i, (url, b0, lang) in enumerate(FEEDS + GQ):
        name = urllib.parse.urlparse(url).netloc + ('' if 'google' not in url else f' ({b0 or "multi"} {lang} #{i - len(FEEDS) + 1})')
        try:
            arts = parse_feed(fetch(url)); kept = 0
            for a in arts:
                c = classify(a['title'], a['summary'], b0)
                d = to_date(a['date'])
                if not c or not d: continue
                # titre Google News : "titre - source"
                src = a['source'] or (a['title'].rsplit(' - ', 1)[1] if ' - ' in a['title'] and 'google' in url else urllib.parse.urlparse(a['url']).netloc)
                title = a['title'].rsplit(' - ', 1)[0] if 'google' in url and ' - ' in a['title'] else a['title']
                items.append({'date': d.isoformat(), 'title': title, 'url': a['url'], 'source': src, 'lang': lang, **c}); kept += 1
            status[name] = f'ok {len(arts)} articles, {kept} kept'
        except Exception as e:
            status[name] = f'error: {type(e).__name__}: {str(e)[:120]}'
        time.sleep(1)
    return items

# ------------------------------------------------------------------ Ecosse : mortalites declarees au Fish Health Inspectorate
FHI_PAGE = 'https://www.gov.scot/publications/fish-health-inspectorate-mortality-information/'
def scotland_fhi(status):
    try:
        page = fetch(FHI_PAGE).decode('utf-8', 'ignore')
        links = re.findall(r'href="([^"]+\.xlsx)"', page)
        link = next((l for l in links if 'ortality' in l and 'notification' not in l.lower()), None)
        if not link: status['gov.scot FHI'] = 'error: no xlsx link'; return None
        if link.startswith('/'): link = 'https://www.gov.scot' + link
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(fetch(link, 90)), read_only=True, data_only=True)
        rows_out, sheets = [], []
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True)); hdr_i = None
            for i, r in enumerate(rows[:30]):   # ligne d'en-tete : contient "site" et une date ou un mois
                cells = [str(c or '').strip().lower() for c in r]
                if any('site' in c for c in cells) and any(('date' in c or 'month' in c or 'year' in c) for c in cells): hdr_i = i; break
            if hdr_i is None: continue
            H = [str(c or '').strip().lower() for c in rows[hdr_i]]; sheets.append(ws.title)
            col = lambda *keys: next((j for j, h in enumerate(H) if any(k in h for k in keys)), None)
            cS, cD, cM, cY = col('site name', 'site'), col('date'), col('month'), col('year')
            cC = col('reason', 'cause', 'comment', 'description', 'detail', 'explanation')
            cN, cP = col('number', 'no. of', 'mortalit', 'fish'), col('%', 'percent')
            cB = col('business', 'company', 'operator')
            for r in rows[hdr_i + 1:]:
                if not r or all(v in (None, '') for v in r): continue
                d = r[cD] if cD is not None else None
                if isinstance(d, dt.datetime): d = d.date()
                if not isinstance(d, dt.date):
                    try:
                        y = int(r[cY]) if cY is not None and r[cY] else None
                        m = r[cM] if cM is not None else None
                        if isinstance(m, (dt.date, dt.datetime)): d = dt.date(m.year, m.month, 1)
                        elif y and m: d = dt.date(y, int(m) if str(m).isdigit() else dt.datetime.strptime(str(m)[:3], '%b').month, 1)
                    except Exception: d = None
                if not d: continue
                cause = str(r[cC] or '') if cC is not None else ''
                tags = [k for k, rr in RC.items() if rr.search(cause)] or ['unspecified']
                rows_out.append({'date': d.isoformat(), 'site': str(r[cS] or '') if cS is not None else '', 'company': str(r[cB] or '') if cB is not None else '',
                                 'cause': cause[:200], 'causes': tags,
                                 'n': r[cN] if cN is not None and isinstance(r[cN], (int, float)) else None,
                                 'pct': r[cP] if cP is not None and isinstance(r[cP], (int, float)) else None})
        if not rows_out: status['gov.scot FHI'] = f'error: no rows parsed (sheets {sheets})'; return None
        # agregat mensuel par cause, 36 derniers mois
        cut = (dt.date.today() - dt.timedelta(days=36 * 31)).isoformat()
        agg = {}
        for r in rows_out:
            if r['date'] < cut: continue
            k = r['date'][:7]; a = agg.setdefault(k, {'reports': 0, 'causes': {}})
            a['reports'] += 1
            for c in r['causes']: a['causes'][c] = a['causes'].get(c, 0) + 1
        recent = sorted([r for r in rows_out if r['date'] >= cut], key=lambda r: r['date'], reverse=True)[:300]
        status['gov.scot FHI'] = f'ok {len(rows_out)} reports, last {max(r["date"] for r in rows_out)}'
        return {'source': link, 'monthly': dict(sorted(agg.items())), 'reports': recent}
    except Exception as e:
        status['gov.scot FHI'] = f'error: {type(e).__name__}: {str(e)[:120]}'; return None

# ------------------------------------------------------------------ fusion
def main():
    try: old = json.load(open(OUT, encoding='utf-8'))
    except Exception: old = {}
    status = {}
    news = news_items(status)
    # cle de dedoublonnage : url, sinon titre normalise ; le meme sujet repris par plusieurs titres reste (date + source differentes)
    key = lambda n: hashlib.md5((n.get('url') or n['title'].lower()).encode()).hexdigest()[:12]
    allnews = {key(n): n for n in old.get('news', [])}
    for n in news: allnews.setdefault(key(n), n)
    cut = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    newsl = sorted([dict(n, id=k) for k, n in allnews.items() if n['date'] >= cut], key=lambda n: n['date'], reverse=True)
    sco = scotland_fhi(status) or old.get('scotland_fhi')
    out = {'meta': {'generated': dt.date.today().isoformat(), 'status': status,
                    'note': 'news = articles kept by keyword (a mortality word + a farming word), classified by cause and basin; manual = events entered by hand with their losses; scotland_fhi = mortalities reported to the Scottish Fish Health Inspectorate',
                    'causes': list(CAUSES.keys()), 'basins': list(BASINS.keys())},
           'manual': old.get('manual', []), 'news': newsl, 'scotland_fhi': sco}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'events: {len(newsl)} articles ({len(news)} this run), {len(out["manual"])} manual events')
    for k, v in status.items(): print(f'  {k}: {v}')

if __name__ == '__main__':
    main()
