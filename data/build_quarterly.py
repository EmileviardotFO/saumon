#!/usr/bin/env python3
"""
Extracts the key figures of salmon farmers' quarterly reports into data/quarterly.json, by company, quarter and
region (segment): harvest, farming cost per kg and its drivers, operational EBIT (total and per kg), harvest guidance
and its change. Used by the "This week" page (results strip under each results story and in the top five) and by the
Scotland tab (Bakkafrost Scotland, Scottish Sea Farms, Mowi Scotland...).

    python3 scripts/build_quarterly.py

Sources: the results stories found in data/stories.json; for each, the company's own press release and report
(GlobeNewswire, Cision, MFN, NewsWeb, company sites: public documents) and free trade-press articles, text only.
Claude (secret ANTHROPIC_API_KEY) reads them and fills a fixed schema; every number kept must be written in the
source text, otherwise it is dropped. Already-extracted reports are kept; history builds up quarter after quarter.
"""
import datetime as dt
import html
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORIES = os.path.join(ROOT, 'data', 'stories.json')
OUT = os.path.join(ROOT, 'data', 'quarterly.json')
MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5-5')
UA = {'User-Agent': 'Mozilla/5.0 (salmon dashboard; contact via GitHub)'}
OFFICIEL = ('globenewswire', 'cision', 'mfn.se', 'newsweb', 'oslobors', 'bakkafrost.com', 'salmar.no', 'mowi.com', 'leroyseafood',
            'griegseafood', 'icelandic.is', 'arnarlax', 'kaldvik', 'scottishseafarms')
SANS_TEXTE = ('intrafish', 'undercurrent', 'fiskeribladet', 'finansavisen', 'seafoodnews', 'news.google.com')

# Amorce : chiffres publies le 3 novembre 2026 (communique SalMar, presentation du 3e trimestre), verifies a la main.
AMORCE = [
    {'company': 'SalMar', 'quarter': '2026-Q3', 'published': '2026-11-03', 'seed': True, 'source': 'SalMar Q3 2026 release (GlobeNewswire) and presentation',
     'url': 'https://www.globenewswire.com/news-release/2026/11/03/3393880/0/en/salmar-record-high-harvest-volume-and-significant-improvement-in-results.html',
     'segments': [
        {'segment': 'Group', 'basin': 'NO', 'currency': 'NOK', 'harvest_t': 105100, 'harvest_t_ly': 93200, 'ebit_per_kg': 15.3, 'ebit_per_kg_ly': 7.6,
         'guidance_year': 2026, 'guidance_t': 347000, 'guidance_prev_t': 349000, 'guidance_reason': 'Iceland and Scotland cut; 2027 guided at 348,000 t',
         'notes': ['Record quarterly harvest; results below analyst estimates']},
        {'segment': 'Scottish Sea Farms', 'basin': 'GB', 'currency': 'NOK', 'ebit_per_kg': 1.0, 'guidance_year': 2026, 'guidance_t': 40000,
         'guidance_prev_t': 43000, 'guidance_reason': 'incident-based mortality; affected sites harvested out in October', 'notes': ['100% basis; joint venture with Lerøy']},
        {'segment': 'Icelandic Salmon', 'basin': 'IS', 'currency': 'NOK', 'ebit_m': 15, 'ebit_m_ly': -110, 'guidance_year': 2026, 'guidance_t': 20000,
         'guidance_prev_t': 21000, 'guidance_reason': '18,000 t expected in 2027', 'notes': []}]},
]
SCHEMA = """{"company": "...", "quarter": "YYYY-Qn", "published": "YYYY-MM-DD", "segments": [
 {"segment": "Group | Norway | Scotland | Faroe Islands | Iceland | Chile | Canada | Ireland | a named subsidiary such as Scottish Sea Farms",
  "basin": "NO | GB | FO | IS | CL | CA | IE | AU | US", "currency": "NOK | DKK | EUR | GBP | USD | JPY | CLP",
  "harvest_t": n, "harvest_t_ly": n, "avg_harvest_weight_kg": n,
  "cost_per_kg": n, "cost_per_kg_ly": n, "cost_basis": "...", "cost_drivers": ["what raised or lowered cost, as stated"],
  "period": "the period the figures cover if not a single quarter, e.g. nine months to December",
  "ebit_m": n, "ebit_m_ly": n, "ebit_per_kg": n, "ebit_per_kg_ly": n, "net_profit_m": n, "net_profit_m_ly": n,
  "price_achievement_pct": n, "contract_share_pct": n, "superior_share_pct": n,
  "incident_mortality_cost_m": n, "mortality_pct": n, "biomass_end_t": n, "smolt_released_m": n,
  "guidance_year": n, "guidance_t": n, "guidance_prev_t": n, "guidance_reason": "...",
  "next_year_guidance_t": n, "cost_outlook": "...",
  "biology": ["at most three short facts: mortality, lice, disease, incidents, treatments"],
  "market": ["at most three short facts: prices, destinations, demand, industry supply outlook"],
  "notes": ["at most two other key facts: capex, financing, M&A, regulation"]}]}"""
PROMPT = f"""You extract the key figures of a salmon farmer's quarterly report (press release, interim report or presentation text).
Return ONE JSON object and nothing else, following this schema; n = a number. Omit any field the text does not state; never compute,
convert or guess:
{SCHEMA}
Rules: numbers exactly as written (millions for EBIT and costs in millions, tonnes for harvest, biomass and guidance, per kg in the
reporting currency, percentages as numbers); "_ly" = same quarter a year earlier; guidance_prev_t = the previous guidance if stated.
price_achievement_pct = achieved price relative to the reference price (e.g. 96 for 96 %). One segment per region or subsidiary reported
separately, plus "Group" when group totals are given. "quarter" = the calendar quarter in which the reported period ends (a Japanese
fiscal Q2 ending in September is 2026-Q3). For a subsidiary reported by its parent (e.g. Cermaq in Mitsubishi's results), report the
subsidiary only. English only."""
MOTS = ('cost', 'kost', 'ebit', 'guidance', 'harvest', 'slakt', 'mortality', 'dødelighet', 'price achievement', 'prisoppnåelse', 'superior',
        'reference price', 'contract', 'biomass', 'smolt', 'outlook', 'segment', 'scotland', 'faroe', 'iceland', 'per kg')
ISSUERS = {'MOWI': 'Mowi', 'SALM': 'SalMar', 'LSG': 'Lerøy', 'GSF': 'Grieg', 'BAKKA': 'Bakkafrost', 'MAS': 'Måsøval',
           'SALME': 'Salmon Evolution', 'ISLAX': 'Icelandic Salmon', 'KALDV': 'Kaldvík', 'ARCTIC': 'Arctic Fish',
           'ATLA': 'Atlantic Sapphire', 'PROXI': 'Proximar', 'ANDF': 'Andfjord Salmon'}
# Entreprises sans communique a Oslo, ou privees mais suivies par la presse (Cermaq : resultats publies par Mitsubishi) :
# veille gratuite sur Bing News (RSS) ; un rapport n'est lu que si un titre de resultats paraît dans les 5 derniers jours.
PRESSE = {
    'Cermaq': ['Cermaq Mitsubishi profit', 'Cermaq results quarter'],
    'Multi X': ['"Multi X" salmon results quarter', '"Multi X" resultados trimestre'],
    'Blumar': ['Blumar salmon results quarter', 'Blumar resultados trimestre salmones'],
    'Camanchaca': ['Camanchaca salmon results quarter', 'Salmones Camanchaca resultados trimestre'],
    'Australis': ['Australis Seafoods results', 'Australis Mar resultados trimestre'],
    'AquaChile': ['AquaChile Agrosuper results', 'Agrosuper resultados trimestre acuícola'],
    'Salmones Austral': ['Salmones Austral resultados'],
    'Ventisqueros': ['Ventisqueros salmon resultados'],
    'Grieg': ['Grieg Seafood quarter results'],
    'Mowi': ['Mowi quarter results'], 'SalMar': ['SalMar quarter results'], 'Lerøy': ['Leroy Seafood quarter results'],
    'Bakkafrost': ['Bakkafrost quarter results'], 'Måsøval': ['Måsøval quarter results'],
    'Icelandic Salmon': ['Icelandic Salmon Arnarlax quarter results'], 'Kaldvík': ['Kaldvik quarter results'],
    'Arctic Fish': ['Arctic Fish quarter results'], 'Salmon Evolution': ['Salmon Evolution quarter results'],
    'Cooke': ['Cooke Aquaculture results'], 'Tassal': ['Tassal results'], 'Huon': ['Huon Aquaculture results'],
}
RESULTATS = re.compile(r'result|earnings|profit|loss|ebit|quarter|q[1-4]\b|resultad|trimestre|utilidad|ganancia|pérdida|kvartal|resultat', re.I)
NEWSWEB = 'https://api3.oslo.oslobors.no/v1/newsreader'
RAPPORT = re.compile(r'(q[1-4]|first|second|third|fourth|1st|2nd|3rd|4th|kvartal|quarter|interim|half[- ]year|annual)\b.*(report|result|rapport|presentation)|'
                     r'(report|result|rapport|resultat).*(q[1-4]|quarter|kvartal)', re.I)
PAS_RAPPORT = re.compile(r'invitation|webcast|presentation of|conference call|kallelse|notice of|financial calendar|share buy|trade', re.I)
MAX_PASSAGE, MAX_MOIS = 8, 60          # plafonds d'appels a Claude : par passage, par mois


def http(url, binaire=False):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read(15_000_000)
    return raw if binaire else raw.decode('utf-8', 'replace')


def texte_html(h):
    h = re.sub(r'(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>', ' ', h)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h))).strip()


def texte_pdf(raw, budget=40000):
    """Texte des pages les plus utiles d'un rapport : les 2 premieres (faits marquants), puis celles qui parlent couts,
    EBIT, guidance, recolte, mortalite... jusqu'a ~40 000 caracteres : l'appel reste court."""
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(raw); f.flush()
        try:
            t = subprocess.run(['pdftotext', '-l', '60', '-layout', f.name, '-'], capture_output=True, timeout=120).stdout.decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001
            return ''
    pages = t.split('\f')
    score = lambda p: sum(p.lower().count(m) for m in MOTS)
    garde = list(range(min(2, len(pages))))
    for k in sorted(range(len(pages)), key=lambda k: -score(pages[k])):
        if k not in garde and score(pages[k]) >= 3 and sum(len(pages[x]) for x in garde) + len(pages[k]) <= budget: garde.append(k)
    return '\n'.join(f'[page {k + 1}] ' + re.sub(r'[ \t]{2,}', '  ', pages[k]) for k in sorted(garde))


def collecte(story):
    """Texte du communique et du rapport (PDF lie) si disponibles, puis articles gratuits ; 60 000 caracteres au plus."""
    arts = sorted(story['arts'], key=lambda a: (not any(o in a['url'] for o in OFFICIEL), a['access'] != 'free'))
    morceaux, vus = [], 0
    for a in arts:
        if any(x in a['url'] for x in SANS_TEXTE) or a['access'] in ('pay', 'metered'): continue
        try:
            h = http(a['url'])
        except Exception:  # noqa: BLE001
            continue
        morceaux.append(f"[{a['source']}] {texte_html(h)[:20000]}")
        if any(o in a['url'] for o in OFFICIEL):
            for lien in re.findall(r'href="([^"]+\.pdf)"', h, re.I)[:3]:
                if re.search(r'report|quarter|presentation|q[1-4]|kvartal', lien, re.I):
                    try:
                        u = lien if lien.startswith('http') else urllib.parse.urljoin(a['url'], lien)
                        morceaux.append(f'[report PDF] {texte_pdf(http(u, True))[:30000]}')
                    except Exception:  # noqa: BLE001
                        pass
        vus += 1
        if vus >= 4 or sum(len(m) for m in morceaux) > 60000: break
    return '\n\n'.join(morceaux)[:60000]


def cherche(o, cle):
    """Toutes les valeurs d'une cle dans un JSON imbrique (le format de NewsWeb change parfois)."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == cle: yield v
            yield from cherche(v, cle)
    elif isinstance(o, list):
        for x in o: yield from cherche(x, cle)


def newsweb(jours=4):
    """Rapports trimestriels publies ces derniers jours sur Oslo Bors NewsWeb : gratuit, sans appel a Claude."""
    fin = dt.date.today(); debut = fin - dt.timedelta(days=jours)
    trouves = []
    for code, nom in ISSUERS.items():
        try:
            j = json.loads(http(f'{NEWSWEB}/list?issuer={code}&fromDate={debut}&toDate={fin}'))
        except Exception:  # noqa: BLE001
            continue
        msgs = [x for x in cherche(j, 'messages')]
        for lst in msgs:
            for x in lst if isinstance(lst, list) else []:
                titre = x.get('title') or ''
                if RAPPORT.search(titre) and not PAS_RAPPORT.search(titre):
                    trouves.append({'company': nom, 'id': x.get('messageId') or x.get('id'), 'title': titre,
                                    'published': (x.get('publishedTime') or '')[:10] or str(fin)})
    return trouves


def presse(jours=5):
    """Articles de resultats parus ces derniers jours, par entreprise (Bing News RSS ; liens d'origine)."""
    import email.utils
    lim = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=jours)
    par = {}
    for nom, requetes in PRESSE.items():
        for q in requetes:
            try:
                xml = http('https://www.bing.com/news/search?' + urllib.parse.urlencode({'q': q, 'format': 'rss', 'setlang': 'en'}))
            except Exception:  # noqa: BLE001
                continue
            for it in re.findall(r'<item>(.*?)</item>', xml, re.S):
                titre = html.unescape(re.sub(r'<.*?>', '', (re.search(r'<title>(.*?)</title>', it, re.S) or [None, ''])[1]))
                lien = html.unescape((re.search(r'<link>(.*?)</link>', it, re.S) or [None, ''])[1]).strip()
                m = re.search(r'[?&]url=([^&]+)', lien)
                if m: lien = urllib.parse.unquote(m.group(1))
                try: date = email.utils.parsedate_to_datetime((re.search(r'<pubDate>(.*?)</pubDate>', it, re.S) or [None, ''])[1])
                except Exception: date = None  # noqa: BLE001
                nom_court = nom.split()[0].lower()
                if not date or date < lim or nom_court not in titre.lower() or not RESULTATS.search(titre) or PAS_RAPPORT.search(titre): continue
                src = re.sub(r'^www\.', '', urllib.parse.urlparse(lien).netloc)
                par.setdefault(nom, {})[lien] = {'title': titre, 'url': lien, 'source': src, 'date': date.date().isoformat(),
                                                 'access': 'pay' if any(x in src for x in SANS_TEXTE) else 'free'}
    return {nom: list(v.values()) for nom, v in par.items()}


def trimestre(titre, publie):
    m = re.search(r'Q([1-4])\s*-?\s*(20\d\d)', titre, re.I)
    if m: return f'{m.group(2)}-Q{m.group(1)}'
    es = {'primer': 1, 'segundo': 2, 'tercer': 3, 'cuarto': 4, 'first': 1, 'second': 2, 'third': 3, 'fourth': 4}
    m = re.search(r'(primer|segundo|tercer|cuarto|first|second|third|fourth)\s+(trimestre|quarter)', titre, re.I)
    if m:
        n = es[m.group(1).lower()]; d = dt.date.fromisoformat(publie)
        return f'{d.year - 1 if n == 4 and d.month <= 4 else d.year}-Q{n}'      # un 4e trimestre publie en debut d'annee
    d = dt.date.fromisoformat(publie)
    q = (d.month - 1) // 3 or 4                                      # un rapport publie en novembre porte sur le 3e trimestre
    return f'{d.year if q != 4 else d.year - 1}-Q{q}'


def texte_newsweb(mid):
    j = json.loads(http(f'{NEWSWEB}/message?messageId={mid}'))
    corps = ' '.join(str(b) for b in cherche(j, 'body'))
    morceaux = [texte_html(corps)[:15000]]
    for att in [a for lst in cherche(j, 'attachments') for a in (lst if isinstance(lst, list) else [])][:3]:
        aid, nom = att.get('id') or att.get('attachmentId'), att.get('name') or ''
        if not aid or not nom.lower().endswith('.pdf'): continue
        for url in (f'{NEWSWEB}/attachment?messageId={mid}&attachmentId={aid}',
                    f'https://newsweb.oslobors.no/obsvc/attachment.obsvc?messageId={mid}&attachmentId={aid}'):
            try:
                morceaux.append(f'[{nom}] ' + texte_pdf(http(url, True))); break
            except Exception:  # noqa: BLE001
                continue
    return '\n\n'.join(morceaux)[:60000]


def claude(texte, cle, who, quarter):
    body = {'model': MODEL, 'max_tokens': 6000, 'system': PROMPT,
            'messages': [{'role': 'user', 'content': f'Company: {who}. Quarter: {quarter}.\n\n{texte}'}]}
    req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=json.dumps(body).encode('utf-8'),
                                 headers={'x-api-key': cle, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    rep = json.loads(urllib.request.urlopen(req, timeout=300).read().decode('utf-8'))
    txt = ''.join(b.get('text', '') for b in rep.get('content', []) if b.get('type') == 'text')
    m = re.search(r'\{.*\}', txt, re.S)
    return json.loads(m.group(0)) if m else None


def verifie(rep, texte):
    """Garde un nombre seulement s'il est ecrit dans le texte source (au format 1,234.5 / 1 234,5 / 1.2 billion...)."""
    norm = re.sub(r'(?<=\d)[ ,\u00a0\u202f](?=\d{3}\b)', '', texte)
    def ecrit(v):
        if not isinstance(v, (int, float)): return False
        a = abs(v)
        formes = {f'{a:g}', f'{a:.1f}', f'{a:.2f}', f'{a:.0f}'.rstrip('.'), f'{a:.1f}'.replace('.', ','), f'{a:.2f}'.replace('.', ',')}
        if a >= 1000: formes |= {f'{a / 1000:g}', f'{a / 1000:.1f}', f'{a / 1e6:.1f}', f'{a / 1e6:.2f}'}
        return any(re.search(r'(?<![\d.,])' + re.escape(f) + r'(?![\d])', norm) for f in formes if f not in ('0', '0.0'))
    for sg in rep.get('segments') or []:
        for k in list(sg):
            if isinstance(sg[k], (int, float)) and k not in ('guidance_year',) and not ecrit(sg[k]):
                del sg[k]
    return rep


def main():
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {'reports': []}
    reps = {(r['company'], r['quarter']): r for r in AMORCE}
    reps.update({(r['company'], r['quarter']): r for r in ancien.get('reports', [])})
    cle = os.environ.get('ANTHROPIC_API_KEY')
    mois = dt.date.today().strftime('%Y-%m')
    compteur = dict((ancien.get('meta') or {}).get('calls', {}))
    faits, notes, appels = 0, [], 0
    a_lire = []                                                     # (societe, trimestre, fonction qui rend le texte, source, url)
    for x in newsweb():
        q = trimestre(x['title'], x['published'])
        a_lire.append((x['company'], q, (lambda mid=x['id']: texte_newsweb(mid)), f"Oslo Børs NewsWeb: {x['title'][:80]}",
                       f"https://newsweb.oslobors.no/message/{x['id']}"))
    for nom, arts in presse().items():
        titres = ' '.join(a['title'] for a in arts)
        q = trimestre(titres, max(a['date'] for a in arts))
        faux = {'arts': arts}
        a_lire.append((nom, q, (lambda f=faux: collecte(f)), ', '.join(sorted({a['source'] for a in arts}))[:200], arts[0]['url']))
    st = json.load(io.open(STORIES, encoding='utf-8')) if os.path.exists(STORIES) else {'stories': []}
    for s in st.get('stories', []):
        m = re.search(r'Q([1-4])\s*(20\d\d)', s.get('event') or '') or re.search(r'Q([1-4])\s*(20\d\d)', s.get('title') or '')
        if s.get('who') in (None, '', 'Sector') or not m or not re.search(r'result|report|earnings|quarter', (s.get('event', '') + s['title']), re.I): continue
        a_lire.append((s['who'], f'{m.group(2)}-Q{m.group(1)}', (lambda s=s: collecte(s)), ', '.join(sorted({a['source'] for a in s['arts']}))[:200],
                       next((a['url'] for a in s['arts'] if any(o in a['url'] for o in OFFICIEL)), s['arts'][0]['url'])))
    vus = set()
    for who, q, lire, source, url in a_lire:
        # un rapport deja lu n'est jamais relu ; une amorce saisie a la main, si (elle sera completee par le rapport complet)
        if (who, q) in vus or ((who, q) in reps and not reps[(who, q)].get('seed')) or not cle: continue
        vus.add((who, q))
        if appels >= MAX_PASSAGE or compteur.get(mois, 0) >= MAX_MOIS:
            notes.append(f'{who} {q}: postponed (call limit reached)'); continue
        try:
            texte = lire()
            if len(texte) < 500: notes.append(f'{who} {q}: no free text'); continue
            r = claude(texte, cle, who, q); appels += 1; compteur[mois] = compteur.get(mois, 0) + 1
            if not r or not r.get('segments'): notes.append(f'{who} {q}: nothing extracted'); continue
            r = verifie(r, texte)
            r.update({'company': who, 'quarter': q, 'source': source, 'url': url})
            amorce = reps.get((who, q))
            if amorce and amorce.get('seed'):                       # garder les segments et chiffres de l'amorce que le rapport ne donne pas
                par_nom = {g['segment']: g for g in r.get('segments', [])}
                for g in amorce.get('segments', []):
                    if g['segment'] in par_nom: par_nom[g['segment']] = {**g, **par_nom[g['segment']]}
                    else: par_nom[g['segment']] = g
                r['segments'] = list(par_nom.values())
            reps[(who, q)] = r; faits += 1
        except Exception as e:  # noqa: BLE001
            notes.append(f'{who} {q}: {str(e)[:100]}')
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'model': MODEL if cle else None,
                    'new': faits, 'claude_calls_this_run': appels, 'calls': compteur, 'limits': {'per_run': MAX_PASSAGE, 'per_month': MAX_MOIS},
                    'notes': notes[:20]},
           'reports': sorted(reps.values(), key=lambda r: (r['quarter'], r['company']), reverse=True)}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f"data/quarterly.json : {len(out['reports'])} reports, {faits} new, {appels} Claude calls"
          + (f" — {'; '.join(notes[:5])}" if notes else ''))


if __name__ == '__main__':
    import urllib.parse  # noqa: F401
    main()
