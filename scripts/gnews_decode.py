"""Retrouve l'adresse de l'article d'origine derriere un lien Google News (news.google.com/rss/articles/...).

Ces liens ne menent nulle part une fois ouverts hors de Google News (dans l'app installee, ils
retombent sur la page d'accueil de Google News). Google n'expose plus l'adresse dans le lien
lui-meme : il faut lire la signature de la page de l'article puis interroger son service interne
"batchexecute", comme le fait la page de Google News.

Les adresses trouvees sont gardees dans data/news_links.json pour ne jamais redemander deux fois.
Un echec n'est pas grave : le lien Google News reste en place.
"""
import base64
import json
import re
import time
import urllib.parse
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9'}
RX_ID = re.compile(r'news\.google\.com/(?:rss/)?articles/([^?/#]+)')


def is_gnews(url):
    return bool(url) and RX_ID.search(url) is not None


def _old_format(gid):
    """Anciens liens (avant 2024) : l'adresse est directement dans l'identifiant encode en base64."""
    try:
        raw = base64.urlsafe_b64decode(gid + '=' * (-len(gid) % 4))
    except Exception:
        return None
    if b'AU_yqL' in raw[:12]:
        return None
    m = re.search(rb'https?://[\x21-\x7e]+', raw)
    return m.group(0).decode('ascii', 'ignore') if m else None


def decode(url, timeout=15):
    m = RX_ID.search(url or '')
    if not m:
        return None
    gid = m.group(1)
    old = _old_format(gid)
    if old:
        return old
    req = urllib.request.Request(f'https://news.google.com/articles/{gid}', headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        page = r.read().decode('utf-8', 'replace')
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return None
    inner = ["garturlreq",
             [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
             gid, int(ts.group(1)), sg.group(1)]
    body = urllib.parse.urlencode({'f.req': json.dumps([[["Fbv4je", json.dumps(inner), None, "generic"]]])}).encode()
    req = urllib.request.Request('https://news.google.com/_/DotsSplashUi/data/batchexecute', data=body,
                                 headers=dict(UA, **{'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        txt = r.read().decode('utf-8', 'replace')
    for part in txt.split('\n'):
        part = part.strip()
        if not part.startswith('[['):
            continue
        try:
            row = json.loads(part)[0]
            res = json.loads(row[2])
            if isinstance(res, list) and len(res) > 1 and str(res[1]).startswith('http'):
                return res[1]
        except Exception:
            continue
    return None


def resolve_all(urls, cache_path, budget=250, pause=0.25, log=print):
    """Complete le cache {lien Google News: adresse d'origine} ; renvoie le cache."""
    try:
        cache = json.load(open(cache_path, encoding='utf-8'))
    except Exception:
        cache = {}
    todo = [u for u in dict.fromkeys(urls) if is_gnews(u) and u not in cache]
    ok = fail = 0
    for u in todo[:budget]:
        try:
            real = decode(u)
        except Exception:
            real = None
        if real:
            cache[u] = real
            ok += 1
        else:
            fail += 1
        time.sleep(pause)
    keep = set(urls)
    cache = {k: v for k, v in cache.items() if k in keep}          # le cache suit les titres encore publies
    json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log(f'google news links: {ok} resolved, {fail} failed, {max(0, len(todo) - budget)} left for next run, {len(cache)} in cache')
    return cache
