#!/usr/bin/env python3
"""
Builds data/stories.json for the "This week" home page from data/news.json (headlines collected by
scripts/update_news.py): headlines grouped into stories, by basin then by company, each with a short
English title and summary, the sources ordered free first, and a small chart when two comparable
figures are stated in the sources.

    python3 scripts/build_stories.py            # last 8 days
    python3 scripts/build_stories.py --days 14

With the secret ANTHROPIC_API_KEY, grouping, titles and summaries are written by Claude from the
headlines and the publishers' own short descriptions (og:description of free pages only, never
paywalled text). Without it, or if the call fails, headlines are grouped by rules (same company or
same key words within a few days) and the title is the most representative free English headline.

COST: incremental. Stories already written are kept from one run to the next (with their headline ids);
Claude only receives the NEW headlines of a basin group, with the titles of that group's existing stories,
and either attaches them to an existing story (updating its summary if they add facts) or writes new stories.
A group with fewer than STORIES_MIN_NEW new headlines (default 6) is not sent at all: they wait for the
next run (shown meanwhile as rule-grouped stories). The top five is re-picked only when stories changed.
A full rewrite happens only if STORIES_FULL=1 or when no previous stories exist.
"""
import argparse
import datetime as dt
import html
import io
import json
import os
import re
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS = os.path.join(ROOT, 'data', 'news.json')
OUT = os.path.join(ROOT, 'data', 'stories.json')
MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5-5')
UA = {'User-Agent': 'Mozilla/5.0 (salmon dashboard; contact via GitHub)'}

# Access to each source: free / metered (a few free articles a month) / pay (subscription). Unknown = '?'.
ACCESS = {
    'free': ['salmon business', 'salmonbusiness', 'fish farmer', 'fishfarmermagazine', 'fishfarming expert', 'fishfarmingexpert',
             'kyst.no', 'kyst', 'thefishsite', 'the fish site', 'landbasedaq', 'salmonexpert', 'mundoacuicola', 'aqua.cl', 'trade-news',
             'ilaks', 'globenewswire', 'investing.com', 'yahoo', 'tradingview', 'tipranks', 'infobae', 'seafoodsource', 'nrk',
             'grocery trade news', 'biggo', 'marketscreener', 'cision', 'mfn', 'newsweb', 'oslo børs', 'hagstova', 'ssb', 'fiskeridir',
             'gov.scot', 'regjeringen', 'sernapesca', 'subpesca', 'salmonchile', 'aquafeed', 'feednavigator', 'thefishsite.com',
             'nettavisen', 'shetland news', 'feed strategy', 'mispeces', 'ap news', 'euronews', 'agencia andina', 'andina', 'mundo marítimo',
             'diario acuícola', 'ipac', 'sea west news', 'fishfarmer.affino', 'food ingredients first', 'el peruano', 'tvperú', 'rpp'],
    'metered': ['la tercera', 'el mercurio', 'diario financiero', 'the herald', 'heraldscotland', 'the press and journal', 'e24',
                'gestión', 'gestion', 'el comercio', 'tridge', 'forbes',
                'reuters', 'indexbox', 'the guardian', 'abc news', 'bbc'],
    'pay': ['stavanger aftenblad', 'intrafish', 'undercurrent', 'fiskeribladet', 'finansavisen', 'dagens næringsliv', 'dn.no', 'seafoodnews', 'seafood news',
            'bloomberg', 'financial times', 'ft.com', 'wall street journal', 'tradewinds', 'kontali', 'nikkei'],
}
COMPANIES = ['Mowi', 'SalMar', 'Lerøy', 'Leroy', 'Bakkafrost', 'Grieg', 'Cermaq', 'Måsøval', 'Nova Sea', 'Nordlaks', 'Eidsfjord', 'Kvarøy',
             'Scottish Sea Farms', 'Icelandic Salmon', 'Arnarlax', 'Arctic Fish', 'Kaldvík', 'Ice Fish Farm', 'Hiddenfjord', 'Luna',
             'AquaChile', 'Agrosuper', 'Multi X', 'Australis', 'Blumar', 'Salmones Camanchaca', 'Camanchaca', 'Salmones Austral', 'Ventisqueros',
             'Invermar', 'Nova Austral', 'Yadran', 'Cooke', 'Tassal', 'Huon', 'Petuna', 'Organic Sea Harvest', 'Loch Duart',
             'BioMar', 'Skretting', 'Cargill', 'Mowi Feed', 'Benchmark', 'Salmon Evolution', 'Andfjord', 'Atlantic Sapphire', 'Proximar']
ALIAS = {'Leroy': 'Lerøy', 'Luna': 'Hiddenfjord', 'Agrosuper': 'AquaChile', 'Salmones Camanchaca': 'Camanchaca'}
BASINS = {'NO': 'Norway', 'CL': 'Chile', 'GB': 'Scotland', 'FO': 'Faroe Islands', 'IS': 'Iceland', 'CA': 'Canada', 'AU': 'Australia',
          'IE': 'Ireland', 'NZ': 'New Zealand', 'US': 'United States', 'global': 'Global', 'FEED': 'Feed & raw materials'}
THEMES = ['market', 'feed', 'biology', 'regulation', 'companies', 'other']


def access(src):
    s = (src or '').lower()
    for k in ('pay', 'metered', 'free'):
        if any(w in s for w in ACCESS[k]): return k
    return '?'


def company(text):
    for c in COMPANIES:
        if re.search(r'(?<![A-Za-zÀ-ÿ])' + re.escape(c) + r'(?![A-Za-zÀ-ÿ])', text, re.I): return ALIAS.get(c, c)
    return None


FEED_CO = {'BioMar', 'Skretting', 'Cargill', 'Mowi Feed', 'Benchmark'}


def basin_of(n):
    th = n.get('themes') or []
    if company(n['title']) in FEED_CO or (th and th[0] == 'feed'): return 'FEED'
    b = [x for x in (n.get('basins') or []) if x != 'global']
    return b[0] if b else 'global'


def og_description(url):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10).read(400000).decode('utf-8', 'replace')
    except Exception:  # noqa: BLE001
        return ''
    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']{20,600})', raw, re.I) \
        or re.search(r'<meta[^>]+content=["\']([^"\']{20,600})["\'][^>]+(?:property|name)=["\'](?:og:description|description)', raw, re.I)
    return html.unescape(m.group(1)).strip()[:400] if m else ''


# ----------------------------------------------------------------------------- rules (fallback)
def mots(t):
    stop = {'the', 'and', 'for', 'with', 'from', 'after', 'into', 'over', 'says', 'said', 'salmon', 'laks', 'salmón', 'de', 'la', 'el',
            'en', 'los', 'las', 'del', 'og', 'i', 'på', 'til', 'av', 'som', 'med', 'for', 'to', 'of', 'in', 'on', 'a', 'an', 'its', 'as'}
    return {w for w in re.findall(r'[a-zà-ÿ0-9]{3,}', t.lower()) if w not in stop}


def rules(items):
    groups = []
    for n in sorted(items, key=lambda x: x['date']):
        c, w, b = company(n['title']), mots(n['title']), basin_of(n)
        best = None
        for g in groups:
            if abs((dt.date.fromisoformat(n['date']) - dt.date.fromisoformat(g['last'])).days) > 4: continue
            same_co = c and g['who'] == c
            common = len(w & g['words'])
            jac = common / max(1, len(w | g['words']))
            if len(g['items']) >= 15 and not same_co: continue
            if (same_co and (common >= 1 or g['basin'] == b)) or (not c and not g['who'] and g['basin'] == b and common >= 4 and jac >= 0.3):
                best = g; break
        if best:
            best['items'].append(n); best['words'] |= w; best['last'] = max(best['last'], n['date'])
        else:
            groups.append({'who': c, 'basin': b, 'words': w, 'last': n['date'], 'items': [n]})
    out = []
    for g in groups:
        its = g['items']
        lead = sorted(its, key=lambda x: (access(x['source']) != 'free', x.get('lang') != 'en', -len(x['title'])))[0]
        th = []
        for n in its:
            for t in n.get('themes') or []:
                if t in THEMES and t != 'other' and t not in th: th.append(t)
        out.append({'basin': g['basin'], 'who': g['who'] or 'Sector', 'event': '', 'title': lead['title'], 'summary': '',
                    'themes': th[:2] or ['other'], 'ids': [n['id'] for n in its], 'chart': None, 'priority': None})
    return out


# ----------------------------------------------------------------------------- Claude
PROMPT = """You turn salmon-farming trade-press headlines into a news digest for an industry analyst. Write in English only.

Group the headlines into stories (one real-world event or development each; several outlets reporting the same results are ONE story).
Output ONE JSON object PER LINE (JSON Lines), nothing else: no array, no prose, no code fences. Each line:
{"basin": "...", "who": "...", "event": "...", "title": "...", "summary": "...", "themes": [...], "ids": [...], "chart": null, "priority": 1}
- basin: one of NO, CL, GB, FO, IS, CA, AU, IE, NZ, US, global, FEED (FEED = fish feed and its raw materials: fishmeal, fish oil, anchovy, El Nino, soy, krill, feed companies). Scottish Sea Farms is GB even when reported by SalMar or Leroy; Icelandic Salmon is IS.
- who: the company the story is about, or "Sector" for a country, market or policy story.
- event: short label such as "Q3 2026 results, published 3 Nov" when relevant, else "".
- title: one plain English sentence (max 16 words) saying what happened, translated if the headlines are in Norwegian, Spanish, Faroese or Icelandic.
- summary: 1-3 English sentences with context and key figures, using ONLY facts stated in the given headlines and descriptions. Never add outside knowledge or guess numbers. Do not use double quotes inside text values.
- themes: 1-2 of market, feed, biology, regulation, companies.
- ids: ids of every headline in the story (each id at most once).
- chart: null, or only if the inputs state 2-4 directly comparable figures (same unit): {"title": "...", "bars": [{"label": "...", "value": number, "display": "as written"}]}.
- priority: 1, 2 or 3, for a salmon market analyst.
  1 = market access and trade (tariffs, duties, export taxes, bans, inspections by an importing country, e.g. Brazil or China),
      prices, exports and demand; mortality, disease, algal blooms, jellyfish or other losses; the economic weight of salmon farming
      for the country (GDP, exports, jobs).
  2 = results and guidance of farmers, production rules (licences, lice rules, capacity), feed costs and raw materials.
  3 = everything else (people, awards, events, technology, local news).
Skip headlines that are not about salmon farming, salmon markets or fish feed."""

LOTS = [('NO',), ('CL', 'CA', 'AU', 'US', 'NZ', 'IE'), ('FO', 'GB', 'IS'), ('FEED', 'global')]
MIN_NEW = int(os.environ.get('STORIES_MIN_NEW', '6'))

INCR = """

INCREMENTAL MODE. The input is {"existing": [...], "headlines": [...]}: "existing" are stories already written (number k, who,
event, title, summary); "headlines" are NEW headlines only. For new headlines that belong to an existing story, output one line
{"k": <k>, "ids": [<new ids>], "summary": "<rewritten 1-3 sentence summary including the new facts>"} (omit "summary" if the new
headlines add no fact). For the other new headlines, output full story lines as described above. Never repeat an existing story
without new ids."""


def claude_incr(new, existing, cle):
    lignes = [{'id': n['id'], 'date': n['date'], 'source': n['source'], 'title': n['title'], 'basins': n.get('basins'),
               **({'desc': n['desc']} if n.get('desc') else {})} for n in new]
    ex = [{'k': k, 'who': s['who'], 'event': s.get('event', ''), 'title': s['title'], 'summary': s.get('summary', '')} for k, s in enumerate(existing)]
    body = {'model': MODEL, 'max_tokens': 16000, 'system': PROMPT + INCR,
            'messages': [{'role': 'user', 'content': json.dumps({'existing': ex, 'headlines': lignes}, ensure_ascii=False)}]}
    req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=json.dumps(body).encode('utf-8'),
                                 headers={'x-api-key': cle, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    rep = json.loads(urllib.request.urlopen(req, timeout=600).read().decode('utf-8'))
    txt = ''.join(b.get('text', '') for b in rep.get('content', []) if b.get('type') == 'text')
    adds, nouvelles = [], []
    for ligne in txt.splitlines():
        ligne = ligne.strip().strip(',')
        if not ligne.startswith('{'): continue
        try: x = json.loads(ligne)
        except ValueError: continue
        (adds if isinstance(x.get('k'), int) else nouvelles).append(x)
    return adds, nouvelles, {'in': (rep.get('usage') or {}).get('input_tokens'), 'out': (rep.get('usage') or {}).get('output_tokens')}


def anciennes(by_id):
    """Stories of the previous run, with their headline ids (kept in the file; older files: found again from the article urls)."""
    if os.environ.get('STORIES_FULL') == '1' or not os.path.exists(OUT): return None
    old = json.load(io.open(OUT, encoding='utf-8'))
    if (old.get('meta') or {}).get('method') != 'claude': return None
    par_url = {}
    for i, n in by_id.items():
        for u in (n.get('url'), n.get('link')):
            if u: par_url[u] = i
    out = []
    for s in old.get('stories', []):
        ids = [i for i in (s.get('ids') or [par_url.get(a.get('url')) or par_url.get(a.get('link')) for a in s.get('arts', [])]) if i in by_id]
        if ids: out.append({k: v for k, v in s.items() if k not in ('arts', 'last')} | {'ids': list(dict.fromkeys(ids))})
    return {'stories': out, 'top': old.get('top', []), 'titles': [s['title'] for s in old.get('stories', [])],
            'seen': set((old.get('meta') or {}).get('seen_ids') or []) & set(by_id) | {i for s in out for i in s['ids']}}


def claude_lot(items, cle):
    lignes = [{'id': n['id'], 'date': n['date'], 'source': n['source'], 'title': n['title'], 'basins': n.get('basins'),
               **({'desc': n['desc']} if n.get('desc') else {})} for n in items]
    body = {'model': MODEL, 'max_tokens': 32000, 'system': PROMPT,
            'messages': [{'role': 'user', 'content': json.dumps(lignes, ensure_ascii=False)}]}
    req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=json.dumps(body).encode('utf-8'),
                                 headers={'x-api-key': cle, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    rep = json.loads(urllib.request.urlopen(req, timeout=600).read().decode('utf-8'))
    txt = ''.join(b.get('text', '') for b in rep.get('content', []) if b.get('type') == 'text')
    out, bad = [], 0
    for ligne in txt.splitlines():                                  # une ligne = un sujet : une ligne abimee ne perd qu'un sujet
        ligne = ligne.strip().strip(',')
        if not ligne.startswith('{'): continue
        try: out.append(json.loads(ligne))
        except ValueError: bad += 1
    return out, {'stop': rep.get('stop_reason'), 'in': (rep.get('usage') or {}).get('input_tokens'),
                 'out': (rep.get('usage') or {}).get('output_tokens'), 'bad_lines': bad}


def claude(items, cle):
    """Un appel par groupe de bassins : des reponses plus courtes, qui ne sont pas coupees."""
    tous, journal = [], []
    for lot in LOTS:
        part = [n for n in items if basin_of(n) in lot]
        if not part: continue
        try:
            st, info = claude_lot(part, cle)
            tous += st; journal.append({'lot': '+'.join(lot), 'headlines': len(part), 'stories': len(st), **info})
        except Exception as e:  # noqa: BLE001
            journal.append({'lot': '+'.join(lot), 'headlines': len(part), 'error': str(e)[:200]})
    if not tous: raise RuntimeError('; '.join(x.get('error', '') for x in journal) or 'no story returned')
    return tous, journal


TOP_PROMPT = """You pick the five biggest salmon-industry stories of the week for a salmon sales and market analyst. Write in English.
Criteria, in order: (1) likely impact on salmon supply, prices or costs: taxes and market access, production rules, feed and raw-material
costs, results and guidance of large farmers, price and volume moves; (2) how widely the story was reported; (3) diversity: at most two
stories from the same basin; (4) recency: the reader looks at this page during the current week, so a story whose latest article is
more than 6 days older than the newest story is only picked if nothing recent matters more (old weekly price reports never).
Merge nothing: pick from the numbered list only.
Output ONE JSON object PER LINE, nothing else: {"i": <story number>, "why": "<one short English sentence on why it matters, using only facts in the story>"}"""


def top5(stories, cle):
    liste = [{'i': i, 'basin': s['basin'], 'who': s['who'], 'event': s.get('event', ''), 'title': s['title'], 'summary': s.get('summary', ''),
              'sources': len({a['source'] for a in s['arts']}), 'latest_article': s.get('last')} for i, s in enumerate(stories)]
    body = {'model': MODEL, 'max_tokens': 4000, 'system': TOP_PROMPT, 'messages': [{'role': 'user', 'content': json.dumps(liste, ensure_ascii=False)}]}
    req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=json.dumps(body).encode('utf-8'),
                                 headers={'x-api-key': cle, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    rep = json.loads(urllib.request.urlopen(req, timeout=300).read().decode('utf-8'))
    txt = ''.join(b.get('text', '') for b in rep.get('content', []) if b.get('type') == 'text')
    out, par_bassin = [], defaultdict(int)
    for ligne in txt.splitlines():
        ligne = ligne.strip().strip(',')
        if not ligne.startswith('{'): continue
        try: x = json.loads(ligne)
        except ValueError: continue
        i = x.get('i')
        if isinstance(i, int) and 0 <= i < len(stories) and i not in [t['i'] for t in out] and par_bassin[stories[i]['basin']] < 2:
            par_bassin[stories[i]['basin']] += 1; out.append({'i': i, 'why': str(x.get('why') or '')[:220]})
        if len(out) == 5: break
    return out


def top5_regles(stories):
    out, par_bassin = [], defaultdict(int)
    for i, s in sorted(enumerate(stories), key=lambda t: -len({a['source'] for a in t[1]['arts']})):
        if s['who'] == 'Sector' and s['basin'] == 'global': continue
        if par_bassin[s['basin']] < 2: par_bassin[s['basin']] += 1; out.append({'i': i, 'why': ''})
        if len(out) == 5: break
    return out


def check(stories, by_id):
    """Keeps only valid ids (each once), drops a chart whose figures are not written in the story's own sources."""
    seen, out = set(), []
    for s in stories:
        ids = [i for i in s.get('ids') or [] if i in by_id and i not in seen]
        if not ids: continue
        seen.update(ids)
        ch = s.get('chart')
        if ch:
            src = ' '.join(by_id[i]['title'] + ' ' + by_id[i].get('desc', '') for i in ids)
            digits = lambda x: re.sub(r'[^\d.]', '', str(x)).strip('.')
            norm = re.sub(r'(?<=\d)[ ,\u00a0\u202f](?=\d{3})', '', src)
            ok = 2 <= len(ch.get('bars') or []) <= 4 and all(digits(b.get('display')) and digits(b.get('display')) in norm for b in ch['bars'])
            if not ok: ch = None
        out.append({'basin': s.get('basin') if s.get('basin') in BASINS else 'global', 'who': (s.get('who') or 'Sector')[:60],
                    'event': (s.get('event') or '')[:80], 'title': (s.get('title') or by_id[ids[0]]['title'])[:200],
                    'summary': (s.get('summary') or '')[:700], 'themes': [t for t in s.get('themes') or [] if t in THEMES][:2] or ['other'],
                    'ids': ids, 'chart': ch, 'priority': s.get('priority') if s.get('priority') in (1, 2, 3) else None})
    return out, seen


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--days', type=int, default=8); a = ap.parse_args()
    news = json.load(io.open(NEWS, encoding='utf-8'))
    gen = (news.get('meta') or {}).get('generated') or dt.date.today().isoformat()
    since = (dt.date.fromisoformat(gen) - dt.timedelta(days=a.days - 1)).isoformat()
    items = [n for n in news.get('items', []) if n.get('date', '') >= since]
    by_id = {n['id']: n for n in items}
    # descriptions des editeurs : pages gratuites seulement, sujets les plus repris d'abord (au plus 80 pages)
    cles = defaultdict(int)
    for n in items:
        c = company(n['title'])
        if c: cles[c] += 1
    cand = [n for n in items if access(n['source']) == 'free' and 'news.google.com' not in (n.get('link') or n['url'])]
    cand.sort(key=lambda n: -cles.get(company(n['title']) or '', 0))
    if os.environ.get('STORIES_HORS_LIGNE') != '1':
        for n in cand[:80]:
            n['desc'] = og_description(n.get('link') or n['url'])
    method, note, stories = 'rules', '', []
    cle = os.environ.get('ANTHROPIC_API_KEY')
    prev = anciennes(by_id) if cle else None
    changed = True
    if cle and items and prev:
        stories, journal, appels = [dict(s) for s in prev['stories']], [], 0
        connus = set(prev['seen'])
        attente = []
        for lot in LOTS:
            new = [n for n in items if basin_of(n) in lot and n['id'] not in connus]
            if not new: continue
            if len(new) < MIN_NEW:
                attente += new; journal.append(f"{'+'.join(lot)}: {len(new)} new, waiting"); continue
            idx = [k for k, s in enumerate(stories) if s['basin'] in lot]
            try:
                adds, nouvelles, info = claude_incr(new, [stories[k] for k in idx], cle); appels += 1
                connus |= {n['id'] for n in new}          # lus par Claude (meme ceux qu'il ecarte : hors sujet)
                ok_ids = {n['id'] for n in new}
                for a in adds:
                    if 0 <= a['k'] < len(idx):
                        st = stories[idx[a['k']]]; ids = [i for i in a.get('ids') or [] if i in ok_ids and i not in st['ids']]
                        if ids:
                            st['ids'] += ids; ok_ids -= set(ids)
                            if a.get('summary'): st['summary'] = str(a['summary'])[:700]
                ns, _ = check(nouvelles, {i: by_id[i] for i in ok_ids})
                stories += ns
                journal.append(f"{'+'.join(lot)}: {len(new)} new, {len(ns)} new stories, tokens {info['in']}/{info['out']}")
            except Exception as e:  # noqa: BLE001
                attente += new; journal.append(f"{'+'.join(lot)}: ERROR {str(e)[:80]}")
        stories += rules([n for n in attente if company(n['title'])]) if attente else []
        method, note, changed = 'claude', f'incremental, {appels} Claude call(s); ' + '; '.join(journal), appels > 0
    elif cle and items:
        try:
            brut, journal = claude(items, cle)
            stories, seen = check(brut, by_id)
            rest = [n for n in items if n['id'] not in seen and company(n['title'])]
            stories += rules(rest) if rest else []
            method = 'claude'
            note = '; '.join(f"{x['lot']}: {x.get('stories', 0)} stories" + (f", stop={x['stop']}" if x.get('stop') not in (None, 'end_turn') else '')
                             + (f", {x['bad_lines']} unreadable lines" if x.get('bad_lines') else '') + (f", ERROR {x['error']}" if x.get('error') else '') for x in journal)
        except Exception as e:  # noqa: BLE001
            note = f'Claude call failed ({e}); grouped by rules'
            stories = rules(items)
    else:
        note = '' if cle else 'no ANTHROPIC_API_KEY: grouped by rules, no summaries'
        stories = rules(items)
    out = []
    for s in stories:
        arts = [{'date': by_id[i]['date'], 'source': by_id[i]['source'], 'title': by_id[i]['title'], 'url': by_id[i]['url'],
                 **({'link': by_id[i]['link']} if by_id[i].get('link') else {}),
                 'lang': by_id[i].get('lang', ''), 'access': access(by_id[i]['source'])} for i in s['ids']]
        arts.sort(key=lambda x: ({'free': 0, '?': 1, 'metered': 2, 'pay': 3}[x['access']], x['date']), reverse=False)
        out.append(dict(s) | {'arts': arts, 'last': max(x['date'] for x in arts)})
    out.sort(key=lambda s: (-len(s['arts']), s['last']), reverse=False)
    top = []
    if prev and not changed:                                        # rien de nouveau envoye a Claude : on garde le top cinq (par titre)
        pos = {s['title']: i for i, s in enumerate(out)}
        top = [{'i': pos[prev['titles'][t['i']]], 'why': t.get('why', '')} for t in prev['top']
               if t.get('i') is not None and t['i'] < len(prev['titles']) and prev['titles'][t['i']] in pos]
    if not top and method == 'claude' and cle:
        try: top = top5(out, cle)
        except Exception as e:  # noqa: BLE001
            note += f'; top five by rules ({str(e)[:80]})'
    if not top: top = top5_regles(out)
    meta = {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'news_generated': gen, 'from': since, 'to': gen,
            'method': method, 'model': MODEL if method == 'claude' else None, 'headlines': len(items), 'note': note, 'basins': BASINS}
    meta['note'] = note
    if method == 'claude': meta['seen_ids'] = sorted(connus if prev else set(by_id))
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps({'meta': meta, 'stories': out, 'top': top}, ensure_ascii=False, separators=(',', ':')))
    print(f'data/stories.json : {len(out)} stories from {len(items)} headlines ({method})' + (f' — {note}' if note else ''))


if __name__ == '__main__':
    main()
