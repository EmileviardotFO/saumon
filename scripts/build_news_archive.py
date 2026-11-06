#!/usr/bin/env python3
"""
News archive for the search box of the News tab.

    python3 scripts/build_news_archive.py            -> data/news_archive.json (after update_news.py and build_stories.py)
    python3 scripts/build_news_archive.py --seed     -> also reads every past version of news.json / stories.json in git

news.json keeps only the last two weeks of headlines and stories.json the current stories, so each run adds them to
an archive kept 400 days: headlines (date, title, link, source, language, basins) and stories (title, summary, who,
basin, dates, the first sources). Nothing else reads this file.
"""
import datetime as dt
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'news_archive.json')
KEEP = 400


def add(arch, news, stories):
    H, S = arch['headlines'], arch['stories']
    for n in (news or {}).get('items', []):
        key = n.get('url') or n.get('id')
        if not key or not n.get('title'):
            continue
        H[key] = {'d': n.get('date'), 't': n['title'], 'u': n.get('url'), 'l': n.get('link'), 's': n.get('source'), 'g': n.get('lang'), 'b': n.get('basins') or []}
    for s in (stories or {}).get('stories', []):
        arts = s.get('arts') or []
        if not s.get('title') or not arts:
            continue
        key = (arts[0].get('url') or '') + '|' + (s.get('first') or min((a.get('date') or '') for a in arts))
        S[key] = {'t': s['title'], 'm': s.get('summary') or '', 'w': s.get('who') or '', 'e': s.get('event') or '', 'b': s.get('basin'),
                  'f': s.get('first') or min((a.get('date') or '') for a in arts), 'z': s.get('last') or max((a.get('date') or '') for a in arts),
                  'a': [{'d': a.get('date'), 't': a.get('title'), 'u': a.get('url'), 'l': a.get('link'), 's': a.get('source'), 'g': a.get('lang'), 'x': a.get('access')} for a in arts[:6]]}


def git_versions(path):
    try:
        revs = subprocess.run(['git', '-C', ROOT, 'log', '--format=%H', '--', path], capture_output=True, text=True, check=True).stdout.split()
    except Exception:
        return
    for r in reversed(revs):
        try:
            yield json.loads(subprocess.run(['git', '-C', ROOT, 'show', f'{r}:{path}'], capture_output=True, text=True, check=True).stdout)
        except Exception:
            continue


def main():
    try:
        arch = json.load(io.open(OUT, encoding='utf-8'))
        arch['headlines'] = {x['u'] or x['t']: x for x in arch.get('headlines', [])}
        arch['stories'] = {(x['a'][0]['u'] if x.get('a') else '') + '|' + x['f']: x for x in arch.get('stories', [])}
    except Exception:
        arch = {'headlines': {}, 'stories': {}}
    if '--seed' in sys.argv:
        for v in git_versions('data/news.json'):
            add(arch, v, None)
        for v in git_versions('data/stories.json'):
            add(arch, None, v)
    rd = lambda p: json.load(io.open(os.path.join(ROOT, 'data', p), encoding='utf-8')) if os.path.exists(os.path.join(ROOT, 'data', p)) else None
    add(arch, rd('news.json'), rd('stories.json'))
    lim = (dt.date.today() - dt.timedelta(days=KEEP)).isoformat()
    H = sorted((x for x in arch['headlines'].values() if (x.get('d') or '') >= lim), key=lambda x: x.get('d') or '', reverse=True)
    S = sorted((x for x in arch['stories'].values() if (x.get('z') or '') >= lim), key=lambda x: x.get('z') or '', reverse=True)
    out = {'meta': {'generated': dt.date.today().isoformat(), 'keep_days': KEEP}, 'headlines': H, 'stories': S}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'news archive: {len(H)} headlines, {len(S)} stories, from {H[-1]["d"] if H else "-"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
