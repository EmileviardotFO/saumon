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
# matieres premieres et acteurs de l'aliment, et organismes qui suivent la peche minotiere : suffisent a rendre un titre pertinent
FEED_CORE = rx([r'fish ?meal', r'fiskemel', r'harina de pescado', r'fish ?oil', r'fiskeolje', r'aceite de pescado', r'anchov', r'ansjos', r'\bIFFO\b', r'\bIMARPE\b',
                r'\bENFEN\b', r'samasa', r'cuota de anchoveta', r'temporada de pesca', r'pesca (industrial|exploratoria|pel[aá]gica)', r'pesquer', r'blue whiting', r'kolmule',
                r'aquafeed', r'fish feed', r'salmon feed', r'laksefôr', r'skretting', r'biomar', r'\bewos\b', r'havsbr[uú]n', r'\bkrill', r'algae oil', r'algeolje'])

# ------------------------------------------------------------------ tri (novembre 2026)
# Sources ecartees : agregateurs financiers, generateurs de pages de marche, reseaux sociaux. Leurs titres reprennent ceux de la
# presse (ou sont generes automatiquement) sans rien apporter.
BLOCK_SRC = rx([r'investing\.com', r'yahoo', r'gurufocus', r'tradingview', r'marketscreener', r'tipranks', r'biggo', r'indexbox', r'tridge', r'openpr',
                r'dealroom', r'facebook', r'instagram', r'tiktok', r'youtube', r'indiaipo', r'investywise', r'haberler', r'marketbeat', r'zacks', r'simply ?wall',
                r'stocktitan', r'seeking ?alpha', r'bioengineer', r'techround', r'newser', r'talent24h', r'trending now', r'news of bahrain', r'msn\b'])
BLOCK_TITLE = rx([r'earnings call transcript', r'\bslides:', r'stock (is )?(dropping|falling|rising|jumps?)', r'shares (fall|rise|jump|drop)', r'reports earnings results for',
                  r'market (size|forecast|to reach|report)', r'prices? & trade data', r'export data & price', r'forecast to 20[3-4]\d',
                  r'invitation to (the )?presentation', r'invitasjon til presentasjon', r'sets .{0,30}results release', r'\bwebinar\b', r'^news - aqua agenda'])
# presse specialisee et sources officielles : un sujet qu'elles traitent pese plus
TIER2 = rx([r'ilaks', r'kyst', r'intrafish', r'fiskeribladet', r'salmon ?business', r'fish ?farmer', r'fishfarming ?expert', r'undercurrent', r'salmonexpert',
            r'mundoacuicola', r'aqua\.cl', r'diario acu[ií]cola', r'seafood ?source', r'seafoodnews', r'e24', r'dagens n[æa]ringsliv', r'finansavisen', r'\bntb\b',
            r'landbasedaq', r'aquafeed\.com', r'mispeces', r'regjeringen', r'mattilsynet', r'sernapesca', r'subpesca', r'\bsepa\b', r'gov\.scot', r'\bmast\b',
            r'vitinn', r'heimildin', r'kvf', r'portal\.fo', r'iffo', r'imarpe', r'enfen'])
# sujets lourds : chiffres, decisions, crises
STRONG = rx([r'\bQ[1-4]\b', r'kvartal', r'quarter', r'trimestre', r'resultat', r'results?\b', r'resultados', r'guidance', r'guiding', r'\bprice', r'\bpris', r'precio',
             r'auction', r'auksjon', r'subasta', r'mortalit', r'd[øo]delighet', r'mortalidad', r'\bILA\b', r'\bISA\b', r'alg(ae|e|as)\b', r'jellyfish', r'manet', r'medusa',
             r'\btax', r'skatt', r'impuesto', r'refinanc', r'refinansier', r'acqui', r'oppkj[øo]p', r'adquisici', r'\bban\b', r'forbud', r'appeal', r'anke', r'tribunal',
             r'decision', r'vedtak', r'quota', r'kvote', r'cuota', r'temporada', r'\bIFFO\b', r'\bENFEN\b', r'forecast', r'prognose', r'proyecci', r'tariff', r'toll', r'arancel',
             r'escape', r'r[øo]mming', r'fuga', r'bankrupt', r'konkurs', r'quiebra', r'waiver'])
# publication de resultats : la meme entreprise le meme jour (a un jour pres) = un seul sujet, quelle que soit la langue
RESULT = rx([r'\bQ[1-4]\b', r'kvartal', r'quarter', r'trimestre', r'resultat', r'results?\b', r'resultados', r'earnings', r'\bEBIT', r'profit', r'overskudd', r'utbytte', r'dividend'])
STOP = set('''the and for with from that this after over into about their they have will been more than what when which while says said amid also
de la el los las del para con por una que sobre ante como más tras entre sus hasta desde este esta
og som med for til fra det den har ikke etter blir kan skal vil nye eller også mot over under'''.split())
def toks(t):
    w = re.findall(r'[0-9a-zæøåáéíóúñðþ]+', t.lower())
    return {x[:6] for x in w if len(x) >= 4 and x not in STOP}
ENT = re.compile(r'\b(mowi|salmar|ler[øo]y|grieg|bakkafrost|hiddenfjord|cermaq|aquachile|camanchaca|blumar|australis|multi ?export|arnarlax|icelandic salmon|kaldv[ií]k|'
                 r'arctic fish|scottish sea farms|loch duart|cooke|nova sea|m[åa]s[øo]val|salmon evolution|proximar|andfjord|akva|skretting|biomar|cargill|iffo|imarpe|enfen|'
                 r'noaa|sepa|sernapesca|subpesca|mattilsynet|corbion|ventisqueros|yadran|invermar|tassal|huon|kingfish|atlantic sapphire)\b', re.I)

def curate(items, excl):
    """ecarte le bruit, regroupe les titres d'un meme sujet, note chaque sujet. Renvoie (items gardes, compteurs d'ecarts)."""
    ex_ids, ex_src = set(excl.get('ids', [])), [s.lower() for s in excl.get('sources', [])]
    ex_words = [w.lower() for w in excl.get('title_words', [])]
    out, dropped = [], {'source': 0, 'title': 0, 'manual': 0}
    for n in items:
        srcs = [x for x in n.get('srcs', [n['source']]) if not BLOCK_SRC.search(x)]
        tl = n['title'].lower()
        if n['id'] in ex_ids or any(s in ' '.join(srcs).lower() for s in ex_src if s) or any(w in tl for w in ex_words if w): dropped['manual'] += 1; continue
        if not srcs or BLOCK_SRC.search(n['source']) and not srcs: dropped['source'] += 1; continue
        if BLOCK_TITLE.search(n['title']): dropped['title'] += 1; continue
        n = dict(n, srcs=srcs)
        if BLOCK_SRC.search(n['source']): n['source'] = srcs[0]
        out.append(n)
    # regroupement par sujet (union-find) : meme fenetre de 4 jours, titres proches ou meme acteur + deux mots communs
    T = [toks(n['title']) for n in out]; E = [{m.lower().replace(' ', '') for m in ENT.findall(n['title'])} for n in out]
    ET = [set().union(*[toks(m) for m in ENT.findall(n['title'])]) if ENT.search(n['title']) else set() for n in out]   # mots des noms d'acteurs
    D = [dt.date.fromisoformat(n['date']) for n in out]; par = list(range(len(out)))
    def f(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            if abs((D[i] - D[j]).days) > 4 or not T[i] or not T[j]: continue
            common = T[i] & T[j]; jac = len(common) / len(T[i] | T[j])
            same_res = E[i] & E[j] and abs((D[i] - D[j]).days) <= 1 and RESULT.search(out[i]['title']) and RESULT.search(out[j]['title'])
            # meme acteur : il faut en plus deux mots communs autres que son nom (sinon "Icelandic Salmon" relie tout ce qui parle de saumon islandais)
            same_ent = E[i] & E[j] and len(common - ET[i] - ET[j]) >= 2 and jac >= 0.15
            if jac >= 0.34 or same_ent or (len(common) >= 4 and jac >= 0.25) or same_res:
                par[f(i)] = f(j)
    groups = {}
    for i in range(len(out)): groups.setdefault(f(i), []).append(i)
    # ENFEN seul (pluies, chaleur, ports...) : garde seulement si le sujet est repris largement (le bulletin officiel) ou touche la peche
    def weather_only(n): return not RF.search(n['title']) and not FEED_CORE.search(re.sub(r'(?i)\benfen\b', '', n['title']))
    keep_i = set()
    for g in groups.values():
        if all(weather_only(out[i]) for i in g) and len({x for i in g for x in out[i]['srcs']}) < 4: dropped['off_topic_weather'] = dropped.get('off_topic_weather', 0) + len(g)
        else: keep_i.update(g)
    groups = {k: g for k, g in groups.items() if g[0] in keep_i}
    out_kept = [out[i] for i in sorted(keep_i)]
    for g in groups.values():
        mem = [out[i] for i in g]
        tier = lambda n: 2 if any(TIER2.search(x) for x in n['srcs']) else 1
        # titre de tete : source specialisee d'abord, puis le titre le plus representatif du groupe (le plus de mots partages avec les autres)
        cen = {id(out[i]): sum(len(T[i] & T[k]) for k in g if k != i) for i in g}
        lead = sorted(mem, key=lambda n: (-tier(n), -cen[id(n)], n['lang'] != 'en', n['date']))[0]
        srcs = sorted({x for n in mem for x in n['srcs']})
        wsrc = sum(1 if TIER2.search(x) else 0.5 for x in srcs)      # la presse generaliste compte moitie
        themes = [t for t in THEME_ORDER + ['other'] if any(t in n['themes'] for n in mem)]
        basins = [b for b in dict.fromkeys(b for n in mem for b in n['basins'])]
        if len(basins) > 1: basins = [b for b in basins if b != 'global']
        score = min(wsrc, 8) + (2 if tier(lead) == 2 else 0) + (1.5 if any(STRONG.search(n['title']) for n in mem) else 0) + \
                (0.5 if set(basins) & {'NO', 'CL', 'GB', 'FO', 'IS'} else 0)
        for n in mem:
            if n is lead:
                n.update(score=round(score, 1), nsrc=len(srcs), cl=lead['id'], themes=themes if themes != ['other'] or len(themes) == 1 else themes, basins=basins,
                         more=[{'t': m['title'], 'u': m['url'], 's': m['source'], 'd': m['date']} for m in sorted(mem, key=lambda m: m['date']) if m is not lead][:20])
            else:
                n.update(cl=lead['id'])
                n.pop('score', None); n.pop('more', None); n.pop('nsrc', None)
    return out_kept, dropped

# ------------------------------------------------------------------ sources
# specialisee = presse d'aquaculture : un titre y est garde des qu'il touche un theme, meme sans le mot "saumon"
FEEDS = [  # (url, bassin par defaut, langue, specialisee)
    ('https://ilaks.no/feed/', 'NO', 'no', True),
    # kyst.no, fishfarmingexpert.com, salmonexpert.cl (Labrador CMS) : /?lab_viewport=rss ; thefishsite.com : /feed.xml.
    # fiskeribladet.no et salmonbusiness.com n'ont pas de flux : recherches Google News "site:" plus bas. Verifie le 2 novembre 2026.
    ('https://www.kyst.no/?lab_viewport=rss', 'NO', 'no', True),
    ('https://www.fishfarmingexpert.com/?lab_viewport=rss', None, 'en', True),
    ('https://www.fishfarmermagazine.com/feed/', None, 'en', True),
    ('https://www.undercurrentnews.com/feed/', None, 'en', False),
    ('https://thefishsite.com/feed.xml', None, 'en', False),
    ('https://www.salmonexpert.cl/?lab_viewport=rss', 'CL', 'es', True),
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
    ('site:salmonbusiness.com', EN_, None, 'en'),
    ('site:fiskeribladet.no (laks OR oppdrett OR havbruk OR fôr OR fiskemel)', NO_, 'NO', 'no'),
]

def norm_title(t): return re.sub(r'[^0-9a-zæøåáéíóúñðþ]+', '', t.lower())[:90]

def classify(title, summary, b0, specialist=False):
    txt = f'{title} {summary}'
    themes = [k for k in THEME_ORDER if THEMES[k].search(txt)]
    # biologie : les mots de mortalite / causes de la veille mortalite comptent aussi
    if 'biology' not in themes and (RM.search(txt) or any(r.search(txt) for r in RC.values())) and RF.search(txt): themes.append('biology')
    # ni elevage ni matiere premiere de l'aliment : hors sujet (El Niño, soja, omega-3 seuls ne suffisent pas : pluies au Perou, mais...)
    if not RF.search(txt) and not FEED_CORE.search(txt) and not (specialist and themes): return None
    basins = [k for k in ['NO', 'CL', 'GB', 'FO', 'IS', 'CA', 'IE', 'AU', 'NZ', 'US'] if RB[k].search(txt)]
    if not basins and b0: basins = [b0]
    return {'themes': themes or ['other'], 'basins': basins or ['global']}

def iso_week(d):
    y, w, _ = d.isocalendar(); return f'{y}-W{w:02d}'

def collect(status, today):
    items = []
    srcs = [(u, b, l, sp, urllib.parse.urlparse(u).netloc) for u, b, l, sp in FEEDS] + \
           [(gnews(q, *p), b, l, q.startswith('site:'), f'news.google.com ({b or "multi"} {l} #{i + 1})') for i, (q, p, b, l) in enumerate(GQ)]
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
    excl = old.get('exclude') or {'ids': [], 'sources': [], 'title_words': [], 'note': 'entered by hand, never overwritten: headline ids, source names or title words to drop'}
    # titres deja enregistres : leur pertinence est reverifiee avec les regles du jour (les regles changent, pas les titres)
    keep = []
    for n in by_id.values():
        if n['date'] < cut: continue
        c = classify(n['title'], '', None, any(TIER2.search(x) for x in n.get('srcs', [])) and 'news.google' not in n.get('url', ''))
        if c is None: continue
        b0 = [b for b in n.get('basins', []) if b != 'global']   # bassin par defaut de la source d'origine, garde s'il n'en est pas trouve d'autre
        keep.append(dict(n, themes=c['themes'], basins=c['basins'] if c['basins'] != ['global'] or not b0 else b0))
    kept, dropped = curate(keep, excl)
    items = sorted(kept, key=lambda n: (n['date'], len(n['srcs'])), reverse=True)
    # plafond par semaine (les plus reprises d'abord)
    weeks = {}
    for n in items: weeks.setdefault(n['week'], []).append(n)
    items = []
    for w in sorted(weeks, reverse=True):
        items += sorted(weeks[w], key=lambda n: (len(n['srcs']), n['date']), reverse=True)[:MAX_PER_WEEK]
    out = {'meta': {'generated': today.isoformat(), 'status': status, 'fresh_days': FRESH_DAYS, 'keep_weeks': KEEP_WEEKS,
                    'dropped': dict(dropped, off_topic=len([n for n in by_id.values() if n['date'] >= cut]) - len(keep)),
                    'themes': THEME_ORDER + ['other'], 'basins': ['NO', 'CL', 'GB', 'FO', 'IS', 'CA', 'IE', 'AU', 'NZ', 'US', 'global'],
                    'note': 'headlines only (title, source, date, link), collected automatically from RSS feeds and Google News; classified by keyword, not verified. '
                            'calendar = upcoming dates entered by hand (date YYYY-MM-DD, basin, theme, what, url), never overwritten by the script.'},
           'calendar': old.get('calendar', []), 'exclude': excl, 'items': items}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'news: {len(items)} headlines kept over {len(weeks)} weeks ({sum(1 for n in items if "score" in n)} stories), {added} new this run, {len(new)} collected, dropped {out['meta']['dropped']}')
    for k, v in status.items(): print(f'  {k}: {v}')

if __name__ == '__main__':
    main()
