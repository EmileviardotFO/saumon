#!/usr/bin/env python3
"""Veille des evenements de mortalite (algues, meduses, maladies, oxygene, tempetes...) dans tous les bassins.

Trois sources, fusionnees dans data/events.json :
  1. presse : flux RSS directs (iLaks, Kyst.no, SalmonBusiness, Fish Farming Expert, Salmonexpert.cl, Fish Farmer)
     + recherches Google News par bassin et par langue (norvegien, espagnol, islandais, anglais, danois/feroien) ;
     chaque article est garde s'il contient un mot de mortalite ET un mot d'elevage, puis classe par cause et par bassin ;
  2. Ecosse : tableur mensuel du Fish Health Inspectorate (mortalites declarees par site, avec la cause) ;
  3. evenements saisis a la main (cle "manual"), jamais ecrases par le script ;
  4. evenements detectes automatiquement (cle "auto") : mois inhabituels dans les donnees de chaque bassin (registre norvegien,
     MAST, SEPA, EPA Tasmanie) et, ailleurs, sujets de mortalite repris par la presse, avec les chiffres cites dans les titres.

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
           r'quell[oó]n', r'calbuco', r'comau', r'reloncav', r'multi ?x\b', r'invermar', r'salmones\b', r'salmonicultura', r'salmonera', r'caleta bay'],
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
    # kyst.no, fishfarmingexpert.com et salmonexpert.cl (Labrador CMS) : flux a /?lab_viewport=rss (les anciennes adresses /rss
    # repondent 404 depuis l'automne 2026) ; thefishsite.com : /feed.xml. Verifie le 2 novembre 2026.
    ('https://www.kyst.no/?lab_viewport=rss', 'NO', 'no'),
    ('https://www.fishfarmingexpert.com/?lab_viewport=rss', None, 'en'),
    ('https://www.fishfarmermagazine.com/feed/', None, 'en'),
    ('https://www.salmonexpert.cl/?lab_viewport=rss', 'CL', 'es'),
    ('https://thefishsite.com/feed.xml', None, 'en'),
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
    # Canada atlantique : les avis publics de Terre-Neuve (pertes > 10 % d'un site, a publier sous 24 h par l'eleveur sur son site)
    # ne sont plus regroupes nulle part (les PDF de la NAIA ont disparu en 2026) : on les attrape par la presse, avec les noms des baies
    (gnews('salmon ("Harbour Breton" OR "Fortune Bay" OR "Bay d\'Espoir" OR "Placentia Bay" OR "Connaigre" OR "Passamaquoddy" OR "Grand Manan" OR "Charlotte County") (mortality OR "die-off" OR dead OR ISA OR lice)', 'en', 'CA', 'CA:en'), 'CA', 'en'),
    (gnews('("infectious salmon anaemia" OR "infectious salmon anemia" OR ISA) ("New Brunswick" OR "Nova Scotia" OR Newfoundland) salmon farm', 'en', 'CA', 'CA:en'), 'CA', 'en'),
    (gnews('("Mowi Canada East" OR "Cooke Aquaculture" OR "Northern Harvest") (mortality OR "mortality event" OR "die-off" OR "sea lice")', 'en', 'CA', 'CA:en'), 'CA', 'en'),
    # salmonbusiness.com n'a plus de flux RSS (novembre 2026) : ses articles passent par Google News
    (gnews('site:salmonbusiness.com (mortality OR deaths OR algae OR jellyfish OR disease OR lice OR ILA OR ISA)', 'en', 'GB', 'GB:en'), None, 'en'),
]

# en-tetes d'un navigateur ordinaire, pour les sites qui renvoient une autre page aux robots (gov.scot)
BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
           'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'en-GB,en;q=0.9'}

def fetch(url, timeout=30, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()

def strip(s): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()

def parse_feed(raw):
    out = []
    try: root = ET.fromstring(raw)
    except ET.ParseError:
        # flux mal forme : salmonexpert.cl (nov. 2026) annonce de l'UTF-8 mais a envoye au robot des accents en Latin-1
        # ("not well-formed" sur le "í" de "Artículos") ; aussi "&" nus ou caracteres de controle. On decode, on nettoie, on relit.
        if isinstance(raw, bytes):
            try: txt = raw.decode('utf-8')
            except UnicodeDecodeError: txt = raw.decode('cp1252', 'replace')
        else: txt = raw
        txt = re.sub(r'&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);)', '&amp;', txt)
        txt = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', txt)
        root = ET.fromstring(txt.encode('utf-8'))
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
        page = fetch(FHI_PAGE, 60, BROWSER).decode('utf-8', 'ignore')
        links = re.findall(r'href=["\']([^"\']+\.xlsx)["\']', page, re.I)
        link = next((l for l in links if 'ortality' in l and 'notification' not in l.lower()), None)
        if not link:
            # la page recue n'est pas celle d'un navigateur (le 2 nov. 2026 la vraie page avait bien le lien) : on note ce qui est arrive
            t = re.search(r'<title[^>]*>(.*?)</title>', page, re.S | re.I)
            status['gov.scot FHI'] = f"error: no xlsx link ({len(page)} chars, {len(links)} xlsx links, title: {strip(t.group(1))[:80] if t else '—'})"; return None
        if link.startswith('/'): link = 'https://www.gov.scot' + link
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(fetch(link, 90, BROWSER)), read_only=True, data_only=True)
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
        recent = sorted([r for r in rows_out if r['date'] >= cut], key=lambda r: r['date'], reverse=True)[:3000]   # toutes les declarations de 3 ans (causes par site sur la carte)
        status['gov.scot FHI'] = f'ok {len(rows_out)} reports, last {max(r["date"] for r in rows_out)}'
        return {'source': link, 'monthly': dict(sorted(agg.items())), 'reports': recent}
    except Exception as e:
        status['gov.scot FHI'] = f'error: {type(e).__name__}: {str(e)[:120]}'; return None

# ------------------------------------------------------------------ fusion

# ------------------------------------------------------------------ evenements automatiques (tous bassins)
def _med(v):
    v = sorted(x for x in v if x is not None)
    return (v[(len(v) - 1) // 2] + v[len(v) // 2]) / 2 if v else None


def _load(p):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return None


NUM = r'(\d{1,3}(?:[ ., ]\d{3})+|\d+(?:[.,]\d+)?)'
def _num(t):
    t = t.replace(' ', ' ').strip()
    if re.fullmatch(r'\d{1,3}(?:[ .,]\d{3})+', t): return float(re.sub(r'[ .,]', '', t))
    return float(t.replace(',', '.'))


def press_figures(title):
    """tonnes et nombre de poissons cites dans un titre ('1,600 tonnes', '1 million fish', '600.000 peces'...)"""
    t, f = None, None
    m = re.search(NUM + r'\s*(tonnes|tons|toneladas|tonn|tonnes?|t)\b', title, re.I)
    if m:
        try: t = _num(m.group(1))
        except Exception: pass
    m = re.search(NUM + r'\s*(million|millones|millioner|millj[oó]n\w*|mill\.?|m)?\s*(farmed |de )?(fish|peces|fisk|laks|salmon|salmones|salmónidos|ejemplares|laxa|fiskar)', title, re.I)
    if m:
        try:
            v = _num(m.group(1)); f = v * 1e6 if m.group(2) else v
            if not m.group(2) and v < 1000: f = None
        except Exception: pass
    return t, f


def auto_events(news, manual):
    out = []
    have = {(e.get('basin'), (e.get('date') or '')[:7]) for e in manual}
    # Norvege : registre de la biomasse, zone par zone (morts du mois / poissons du mois precedent)
    d = _load('data/data.json')
    if d:
        R = {}
        for r in d.get('records', []):
            if r.get('po'): R[(r['po'], r['year'] * 100 + r['month'])] = r
        ks = sorted({k for _, k in R})
        for po in range(1, 14):
            rates = []
            for i, k in enumerate(ks):
                a, b = R.get((po, ks[i - 1])) if i else None, R.get((po, k))
                if not a or not b or not a.get('behfisk_stk'): rates.append(None); continue
                dead = (b.get('dodfisk_stk') or 0); rt = dead / a['behfisk_stk']
                m = _med(rates[-24:])
                if m and rt >= 2 * m and dead >= 400000 and k >= 201901:
                    mo = f'{k // 100}-{k % 100:02d}'
                    if ('NO', mo) not in have or True:
                        out.append({'date': mo, 'basin': 'NO', 'region': f'PO{po}', 'cause': 'unspecified', 'agent': 'register (automatic)',
                                    'fish_m': round(dead / 1e6, 2), 'tonnes': None, 'company': '',
                                    'note': f'{dead / 1e6:.2f} M dead fish in the month, {100 * rt:.1f} % of the fish present, against a usual {100 * m:.1f} %',
                                    'url': 'https://www.fiskeridir.no/Akvakultur/Tall-og-analyse/Biomassestatistikk', 'src': 'Fiskeridirektoratet, biomass register', 'auto': 'data'})
                rates.append(rt)
    # Islande : tableau de bord MAST
    m_ = _load('data/iceland_mast.json')
    if m_ and m_.get('national'):
        N = m_['national']
        for i, x in enumerate(N):
            if i < 12: continue
            med = _med([y['mortality_t'] for y in N[i - 12:i]])
            if not (x['mortality_t'] >= 600 and med and x['mortality_t'] >= 2 * med): continue
            S = sorted([y for y in m_.get('sites', []) if y['m'] == x['m']], key=lambda y: -y['dead'])
            out.append({'date': x['m'], 'basin': 'IS', 'region': ', '.join(dict.fromkeys(y['fjord'] for y in S[:3] if y.get('fjord'))), 'cause': 'unspecified', 'agent': 'MAST (automatic)',
                        'fish_m': round(sum(y['dead'] for y in S) / 1e6, 2) if S else None, 'tonnes': x['mortality_t'], 'company': '',
                        'note': f"national deaths {round(x['mortality_t'])} t against a usual {round(med)} t" + (('; most at ' + ', '.join(f"{y['site']} ({y['co']}, {round(y['dead'] / 1000)}k fish)" for y in S[:3])) if S else ''),
                        'url': (m_.get('meta') or {}).get('url'), 'src': 'MAST dashboard', 'auto': 'data'})
    # Ecosse : rapports SEPA par region (environ six mois de retard)
    sc = _load('data/scotland.json')
    if sc and sc.get('regions'):
        for rg, ser in sc['regions'].items():
            ks = sorted(ser)
            for i, k in enumerate(ks):
                if i < 12 or int(k) < 201901: continue
                v = ser[k][1]; med = _med([ser[j][1] for j in ks[i - 12:i]])
                if v and med and v >= 200 and v >= 2.5 * med:
                    out.append({'date': f'{k[:4]}-{k[4:]}', 'basin': 'GB', 'region': rg, 'cause': 'unspecified', 'agent': 'SEPA reports (automatic)', 'fish_m': None, 'tonnes': round(v),
                                'company': '', 'note': f'{round(v)} t of dead fish declared in the month against a usual {round(med)} t (sites\' reports to SEPA, about six months late)',
                                'url': (sc.get('meta') or {}).get('url'), 'src': 'SEPA', 'auto': 'data'})
    # Tasmanie : dechets de mortalite declares a l'EPA
    au = _load('data/australia.json')
    if au and au.get('mortality'):
        M = au['mortality']
        for i, x in enumerate(M):
            if i < 12: continue
            med = _med([y.get('total') for y in M[i - 12:i]])
            if x.get('total') and med and x['total'] >= 1500 and x['total'] >= 2 * med:
                out.append({'date': f"{str(x['m'])[:4]}-{str(x['m'])[4:]}", 'basin': 'AU', 'region': 'Tasmania', 'cause': 'unspecified', 'agent': 'EPA (automatic)', 'fish_m': None,
                            'tonnes': round(x['total']), 'company': '', 'note': f"{round(x['total'])} t of mortality waste declared against a usual {round(med)} t",
                            'url': None, 'src': 'EPA Tasmania', 'auto': 'data'})
    # presse : sujets de mortalite par bassin, cause et mois, quand ni une saisie ni les donnees ne couvrent deja ce mois
    covered = have | {(e['basin'], e['date']) for e in out}
    DEATH = re.compile(r'\b(died|dead|deaths?|die-?off|mortalit\w*|mortalidad\w*|murieron|muert\w+|d[øo]de?|d[øo]delighet|d[øo]dfisk|tap(et|te)?\b|lost|losses|perd\w+|killed|kills?|drápust|dauð\w*|dráp\w*)', re.I)
    G = {}
    for n in news:
        bs = [k for k, r in RB.items() if r.search(n['title'])] or n.get('basins', [])
        if len(bs) != 1 or not DEATH.search(n['title']): continue
        n = dict(n, basins=bs)
        cs = [c for c in n.get('causes', []) if c != 'unspecified']
        for b in n.get('basins', []):
            for c in cs or ['unspecified']:
                G.setdefault((b, n['date'][:7], c), []).append(n)
    for (b, mo, c), L in G.items():
        if (b, mo) in covered or b in ('other',): continue
        figs = [press_figures(n['title']) for n in L]
        t = max((f[0] for f in figs if f[0]), default=None); fm = max((f[1] for f in figs if f[1]), default=None)
        if len(L) < 2 and not t and not fm: continue
        if c == 'unspecified' and not (t or fm): continue
        # meme chiffre deja connu ce mois-la (un evenement d'un autre bassin repris par une presse etrangere) : on ne le duplique pas
        if t and any((e.get('date') or '')[:7] == mo and e.get('tonnes') and abs(e['tonnes'] - t) <= 2 for e in list(manual) + out): continue
        L = sorted(L, key=lambda n: n['date'])
        out.append({'date': mo, 'basin': b, 'region': '', 'cause': c, 'agent': 'press (automatic)', 'fish_m': round(fm / 1e6, 2) if fm else None, 'tonnes': t, 'company': '',
                    'note': f'{len(L)} article{"s" if len(L) > 1 else ""}: ' + ' · '.join(n['title'] for n in L[:3]), 'url': L[0].get('url'), 'src': L[0].get('source'), 'auto': 'press'})
    return sorted(out, key=lambda e: e['date'], reverse=True)

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
    try:
        out['auto'] = auto_events(newsl, out['manual'])
    except Exception as ex:  # noqa: BLE001
        out['auto'] = old.get('auto', []); status['auto'] = f'{type(ex).__name__}: {ex}'
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'events: {len(newsl)} articles ({len(news)} this run), {len(out["manual"])} manual events, {len(out.get("auto", []))} automatic')
    for k, v in status.items(): print(f'  {k}: {v}')

if __name__ == '__main__':
    main()
