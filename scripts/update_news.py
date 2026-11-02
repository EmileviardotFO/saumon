#!/usr/bin/env python3
"""Recueil hebdomadaire de l'actualite saumon (onglet "This week" de production.html) -> data/news.json.

Flux RSS de la presse specialisee + recherches Google News par theme, par bassin et par langue. Chaque titre est :
  - garde s'il parle d'elevage de salmonides OU de matieres premieres de l'aliment (farine, huile, anchois...) ;
  - garde seulement s'il a ete publie dans les 14 jours precedant l'execution (evite les vieux articles qui
    remontent dans les recherches) ;
  - classe par theme (marche, aliment, biologie, reglementation, entreprises) et par bassin ;
  - regroupe avec ses doublons (meme lien, ou meme titre chez plusieurs sources) ;
  - range dans sa semaine ISO de publication. 26 semaines sont conservees.
Seuls le titre, la source, la date et le lien sont publies : pas de texte d'article.
La cle "calendar" (echeances a venir) est saisie a la main et n'est jamais ecrasee.
Une source qui ne repond pas est notee dans meta.status, le reste continue.
"""
import json, re, time, hashlib, urllib.parse, datetime as dt
from update_events import fetch, parse_feed, to_date, RC, RM, RF, RB, BASINS

OUT = 'data/news.json'
KEEP_WEEKS = 26
FRESH_DAYS = 14          # un article plus vieux que cela a l'execution n'est pas ajoute
MAX_PER_WEEK = 400

def rx(lst): return re.compile('|'.join(f'(?:{p})' for p in lst), re.I)
THEMES = {
    'market': rx([r'\bpris', r'\bprice', r'\bpricing', r'laksepris', r'eksportpris', r'spotpris', r'\bprecios?\b', r'\bspot\b', r'fish ?pool', r'sitagri', r'nasdaq salmon', r'\blfex',
                  r'\beksport', r'\bexport', r'\bimport', r'exportaci', r'importaci', r'etterspørsel', r'\bdemand\b', r'demanda', r'\btariff', r'\btoll(er|satser)?\b', r'arancel',
                  r'\bmarked(et)?\b', r'\bmarket\b', r'mercado', r'retail', r'supermarket', r'consum', r'forbruk', r'\bsushi\b', r'\bvolum(e|es|er)?\b', r'supply', r'\btilbud\b', r'oferta',
                  r'forward', r'\bNOK/kg', r'€/kg', r'USD/kg', r'kr(oner)?/kilo', r'\bkilo(et)?\b']),
    'feed': rx([r'fish ?meal', r'fiskemel', r'harina de pescado', r'fish ?oil', r'fiskeolje', r'aceite de pescado', r'anchov', r'anchoveta', r'ansjos', r'\bIFFO\b', r'\bIMARPE\b',
                r'skretting', r'biomar', r'cargill', r'\bewos\b', r'mowi feed', r'havsbr[uú]n', r'\bfôr(pris|kostnad|fabrikk|produsent|råvare)?\b', r'\bfeed (price|cost|prices|costs|supplier|maker|mill)',
                r'fish feed', r'salmon feed', r'aquafeed', r'\balimento\b', r'\bkrill', r'\bsoy(a|abean)?\b', r'algae oil', r'algeolje', r'omega-?3', r'\bEPA\b', r'\bDHA\b',
                r'el ni[ñn]o', r'\bENFEN\b', r'blue whiting', r'kolmule', r'capelin', r'lodde', r'menhaden', r'raw material', r'råvare', r'materias? primas?', r'samasa', r'pesca (industrial|pelágica)',
                r'temporada de pesca', r'cuota de anchoveta']),
    'biology': rx([r'\blus\b', r'lakselus', r'sea lice', r'caligus', r'\bsmolt', r'vaksin', r'vaccin', r'sykdom', r'disease', r'enfermedad', r'virus', r'bacteri', r'\bILA\b', r'\bISA\b', r'\bPD\b',
                   r'\bSRS\b', r'welfare', r'velferd', r'bienestar', r'rømming', r'escape', r'\bfuga\b', r'biomass(e)?\b', r'biomasa', r'\bgill', r'\balg(e|ae|as|er)\b', r'jellyfish', r'manet', r'medusa',
                   r'dødelighet', r'mortalit', r'mortalidad', r'sanitari', r'fish health', r'fiskehelse', r'mattilsynet', r'veterinærinstitutt', r'sernapesca']),
    'regulation': rx([r'\bskatt', r'grunnrente', r'normpris', r'prisråd', r'\btax(es|ation)?\b', r'impuesto', r'tributar', r'\blevy\b', r'avgift', r'fiskeldisgjald', r'royalt',
                      r'tillatelse', r'konsesjon', r'\blicen[cs]e', r'\bpermits?\b', r'concesi[oó]n', r'relocaliz', r'auksjon', r'auction', r'subasta', r'kapasitet', r'capacity',
                      r'trafikklys', r'traffic light', r'lusekvot', r'luseavgift', r'regulat', r'regulering', r'forskrift', r'høring', r'consultation', r'consulta p[uú]blica', r'\bley\b',
                      r'reglament', r'\bSEPA\b', r'subpesca', r'\bSMA\b', r'storting', r'althing', r'lagareld', r'parliament', r'parlamento', r'senado', r'c[aá]mara de diputados',
                      r'ministe', r'departement', r'regjering', r'government', r'gobierno', r'tingrett', r'lagmannsrett', r'høyesterett', r'\bcourt\b', r'tribunal', r'juzgado',
                      r'lawsuit', r'søksmål', r'statsforvalter', r'avslag', r'avslår', r'sier nei', r'\brejects?\b', r'refus', r'godkjen', r'approv', r'rechaz', r'\bappeal', r'anke', r'\bban\b', r'forbud', r'prohibici', r'decreto', r'policy', r'politikk']),
    'companies': rx([r'\bQ[1-4]\b', r'kvartal', r'quarter', r'trimestre', r'results?\b', r'resultat', r'resultados', r'earnings', r'\bEBIT', r'guidance', r'guiding', r'\bprofit', r'overskudd',
                     r'underskudd', r'utbytte', r'dividend', r'acqui', r'oppkjøp', r'kjøper', r'merger', r'fusjon', r'fusi[oó]n', r'adquisici', r'takeover', r'\bbud\b', r'\bIPO\b', r'emisjon',
                     r'refinanc', r'refinansier', r'\bbond\b', r'obligasjon', r'share price', r'aksje', r'acciones', r'\bCEO\b', r'administrerende', r'gerente general', r'hecho esencial',
                     r'lønnsom', r'profitab', r'rentabilidad', r'investe?r', r'investment', r'inversi[oó]n', r'bankrupt', r'konkurs', r'quiebra', r'restructur',
                     r'\bmowi\b', r'salmar', r'ler[øo]y', r'grieg', r'bakkafrost', r'hiddenfjord', r'cermaq', r'aquachile', r'camanchaca', r'blumar', r'australis', r'multi ?export',
                     r'arnarlax', r'icelandic salmon', r'kaldv[ií]k', r'arctic fish', r'scottish sea farms', r'loch duart', r'cooke', r'nova sea', r'måsøval', r'salmon evolution',
                     r'akva group', r'benchmark', r'aquagen', r'ventisqueros', r'yadran', r'invermar', r'tassal', r'huon']),
}
THEME_ORDER = ['market', 'feed', 'biology', 'regulation', 'companies']

# ------------------------------------------------------------------ sources
# specialisee = presse d'aquaculture : un titre y est garde des qu'il touche un theme, meme sans le mot "saumon"
FEEDS = [  # (url, bassin par defaut, langue, specialisee)
    ('https://ilaks.no/feed/', 'NO', 'no', True),
    ('https://www.kyst.no/rss', 'NO', 'no', True),
    ('https://www.fiskeribladet.no/rss', 'NO', 'no', False),
    ('https://www.salmonbusiness.com/feed/', None, 'en', True),
    ('https://www.fishfarmingexpert.com/rss', None, 'en', True),
    ('https://www.fishfarmermagazine.com/feed/', None, 'en', True),
    ('https://www.undercurrentnews.com/feed/', None, 'en', False),
    ('https://thefishsite.com/rss', None, 'en', False),
    ('https://www.salmonexpert.cl/rss', 'CL', 'es', True),
    ('https://www.mundoacuicola.cl/new/feed/', 'CL', 'es', True),
]
def gnews(q, hl, gl, ceid): return 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q + ' when:10d', 'hl': hl, 'gl': gl, 'ceid': ceid})
NO_, CL_, EN_, IS_, DA_ = ('no', 'NO', 'NO:no'), ('es-419', 'CL', 'CL:es-419'), ('en', 'GB', 'GB:en'), ('is', 'IS', 'IS:is'), ('da', 'DK', 'DK:da')
GQ = [  # (requete, parametres de langue, bassin par defaut, langue)
    ('(laksepris OR eksportpris OR spotpris OR "prisen på laks") laks', NO_, 'NO', 'no'),
    ('(grunnrenteskatt OR normpris OR prisrådet OR trafikklys OR luseavgift OR lusekvoter OR kapasitetsauksjon OR havbruksskatt OR nedtrekk) oppdrett', NO_, 'NO', 'no'),
    ('(Mowi OR SalMar OR Lerøy OR Grieg OR "Nova Sea" OR Måsøval OR "Salmon Evolution") (kvartal OR resultat OR oppkjøp OR guiding)', NO_, 'NO', 'no'),
    ('(fôrpris OR fiskemel OR fiskeolje OR fôrkostnad OR fôrprisene) laks', NO_, 'NO', 'no'),
    ('(fishmeal OR "fish oil" OR anchovy OR IFFO) (price OR prices OR supply OR quota)', EN_, None, 'en'),
    ('(Skretting OR BioMar OR Cargill OR "Mowi Feed" OR Havsbrún) (salmon OR feed)', EN_, None, 'en'),
    ('(anchoveta OR "harina de pescado" OR "aceite de pescado" OR samasa) (IMARPE OR PRODUCE OR SNP OR temporada)', ('es-419', 'PE', 'PE:es-419'), None, 'es'),
    ('"El Niño" (ENFEN OR NOAA OR anchoveta OR "Niño costero")', ('es-419', 'PE', 'PE:es-419'), None, 'es'),
    ('salmón Chile (exportaciones OR precio OR Subpesca OR ley OR Sernapesca OR arancel)', CL_, 'CL', 'es'),
    ('(AquaChile OR Camanchaca OR Blumar OR Australis OR Multiexport OR "Cermaq Chile" OR "Mowi Chile" OR Ventisqueros) salmón', CL_, 'CL', 'es'),
    ('("Scottish salmon" OR "Salmon Scotland" OR "Scottish Sea Farms" OR "Mowi Scotland" OR "Bakkafrost Scotland" OR "Loch Duart")', EN_, 'GB', 'en'),
    ('(Bakkafrost OR Hiddenfjord OR "Faroese salmon" OR "Faroe Islands salmon")', EN_, 'FO', 'en'),
    ('(laksaaling OR laksur OR alivinna OR Bakkafrost OR Hiddenfjord) Føroyar', DA_, 'FO', 'fo'),
    ('(Arnarlax OR "Icelandic Salmon" OR Kaldvík OR "Arctic Fish" OR "Iceland salmon farming")', EN_, 'IS', 'en'),
    ('(laxeldi OR sjókvíaeldi OR fiskeldi) (Kaldvík OR Arnarlax OR "Arctic Fish" OR MAST OR lög)', IS_, 'IS', 'is'),
    ('salmon (prices OR tariff OR imports OR demand) (China OR "United States" OR Japan OR Brazil OR EU)', ('en', 'US', 'US:en'), None, 'en'),
    ('"salmon price" OR "salmon prices" OR "spot price" salmon', ('en', 'US', 'US:en'), None, 'en'),
    ('salmon farming (regulation OR tax OR licence OR "sea lice" OR consultation)', EN_, None, 'en'),
]

def norm_title(t): return re.sub(r'[^0-9a-zæøåáéíóúñðþ]+', '', t.lower())[:90]

def classify(title, summary, b0, specialist=False):
    txt = f'{title} {summary}'
    themes = [k for k in THEME_ORDER if THEMES[k].search(txt)]
    # biologie : les mots de mortalite / causes de la veille mortalite comptent aussi
    if 'biology' not in themes and (RM.search(txt) or any(r.search(txt) for r in RC.values())) and RF.search(txt): themes.append('biology')
    if not RF.search(txt) and 'feed' not in themes and not (specialist and themes): return None      # ni elevage ni aliment : hors sujet
    basins = [k for k in ['NO', 'CL', 'GB', 'FO', 'IS', 'CA', 'IE', 'AU', 'NZ', 'US'] if RB[k].search(txt)]
    if not basins and b0: basins = [b0]
    return {'themes': themes or ['other'], 'basins': basins or ['global']}

def iso_week(d):
    y, w, _ = d.isocalendar(); return f'{y}-W{w:02d}'

def collect(status, today):
    items = []
    srcs = [(u, b, l, sp, urllib.parse.urlparse(u).netloc) for u, b, l, sp in FEEDS] + \
           [(gnews(q, *p), b, l, True, f'news.google.com ({b or "multi"} {l} #{i + 1})') for i, (q, p, b, l) in enumerate(GQ)]   # requetes deja ciblees
    for url, b0, lang, spec, name in srcs:
        try:
            arts = parse_feed(fetch(url)); kept = 0
            for a in arts:
                d = to_date(a['date'])
                if not d or d > today + dt.timedelta(days=1) or (today - d).days > FRESH_DAYS: continue
                g = 'google' in url
                title = a['title'].rsplit(' - ', 1)[0] if g and ' - ' in a['title'] else a['title']
                src = a['source'] or (a['title'].rsplit(' - ', 1)[1] if g and ' - ' in a['title'] else urllib.parse.urlparse(a['url']).netloc.replace('www.', ''))
                c = classify(title, a['summary'] if not g else '', b0, spec)
                if not c or len(title) < 12: continue
                items.append({'date': d.isoformat(), 'title': title, 'url': a['url'], 'source': src, 'lang': lang, **c}); kept += 1
            status[name] = f'ok {len(arts)} items, {kept} kept'
        except Exception as e:
            status[name] = f'error: {type(e).__name__}: {str(e)[:120]}'
        time.sleep(1)
    return items

def main():
    try: old = json.load(open(OUT, encoding='utf-8'))
    except Exception: old = {}
    today = dt.date.today(); status = {}
    new = collect(status, today)
    by_id, by_title = {}, {}
    for n in old.get('items', []):
        by_id[n['id']] = n; by_title.setdefault(norm_title(n['title']), n['id'])
    added = 0
    for n in new:
        nid = hashlib.md5(n['url'].encode()).hexdigest()[:12]
        if nid in by_id: continue
        tk = norm_title(n['title'])
        if tk in by_title:                       # meme titre deja vu : on ajoute la source au premier
            o = by_id[by_title[tk]]
            if n['source'] not in o['srcs']: o['srcs'].append(n['source'])
            for k in ('themes', 'basins'):
                for v in n[k]:
                    if v not in o[k] and v not in ('other', 'global'): o[k] = [x for x in o[k] if x not in ('other', 'global')] + [v]
            continue
        d = dt.date.fromisoformat(n['date'])
        it = {'id': nid, 'date': n['date'], 'week': iso_week(d), 'title': n['title'], 'url': n['url'], 'source': n['source'], 'srcs': [n['source']],
              'lang': n['lang'], 'themes': n['themes'], 'basins': n['basins']}
        by_id[nid] = it; by_title[tk] = nid; added += 1
    cut = (today - dt.timedelta(weeks=KEEP_WEEKS)).isoformat()
    items = sorted((n for n in by_id.values() if n['date'] >= cut), key=lambda n: (n['date'], len(n['srcs'])), reverse=True)
    # plafond par semaine (les plus reprises d'abord)
    weeks = {}
    for n in items: weeks.setdefault(n['week'], []).append(n)
    items = []
    for w in sorted(weeks, reverse=True):
        items += sorted(weeks[w], key=lambda n: (len(n['srcs']), n['date']), reverse=True)[:MAX_PER_WEEK]
    out = {'meta': {'generated': today.isoformat(), 'status': status, 'fresh_days': FRESH_DAYS, 'keep_weeks': KEEP_WEEKS,
                    'themes': THEME_ORDER + ['other'], 'basins': ['NO', 'CL', 'GB', 'FO', 'IS', 'CA', 'IE', 'AU', 'NZ', 'US', 'global'],
                    'note': 'headlines only (title, source, date, link), collected automatically from RSS feeds and Google News; classified by keyword, not verified. '
                            'calendar = upcoming dates entered by hand (date YYYY-MM-DD, basin, theme, what, url), never overwritten by the script.'},
           'calendar': old.get('calendar', []), 'items': items}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'news: {len(items)} headlines kept over {len(weeks)} weeks, {added} new this run, {len(new)} collected')
    for k, v in status.items(): print(f'  {k}: {v}')

if __name__ == '__main__':
    main()
