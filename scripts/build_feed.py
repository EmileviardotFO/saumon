#!/usr/bin/env python3
"""
Feed tab: raw-material prices, feed used by salmon farming, and the hand-entered context of the world feed market.

    python3 scripts/build_feed.py        -> data/feed.json

1. World Bank Commodity Price Data ("Pink Sheet", monthly, nominal USD, updated early each month): fish meal, soybeans,
   soybean meal and oil, rapeseed, palm and sunflower oil, maize, wheat, plus Brent crude and urea (energy and fertiliser
   behind crop prices) and competing animal proteins (chicken, beef, shrimp).
2. Feed used by salmon farming, month by month, from files already built by the other scripts:
   Norway (data/data.json, Directorate of Fisheries' biomass register), Scotland (data/scotland.json, SEPA),
   Iceland (data/iceland_mast.json, MAST), with harvest and biomass so a 12-month feed conversion can be read.
3. data/feed_manual.json: figures entered by hand from reports (world feed survey, fishmeal and fish oil output,
   Peruvian anchovy quotas), each with its source and date. Never overwritten by this script.
Free, no key. A source that fails leaves its part of the previous file in place.
"""
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'feed.json')
MANUAL = os.path.join(ROOT, 'data', 'feed_manual.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
PAGE = 'https://www.worldbank.org/en/research/commodity-markets'
FALLBACK = 'https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx'
# key, column title in the Pink Sheet, label, group
SERIES = [
    ('fishmeal', 'Fish meal', 'Fish meal', 'marine'),
    ('soymeal', 'Soybean meal', 'Soybean meal', 'protein'),
    ('soybeans', 'Soybeans', 'Soybeans', 'protein'),
    ('soyoil', 'Soybean oil', 'Soybean oil', 'oil'),
    ('rapeoil', 'Rapeseed oil', 'Rapeseed oil', 'oil'),
    ('palmoil', 'Palm oil', 'Palm oil', 'oil'),
    ('sunoil', 'Sunflower oil', 'Sunflower oil', 'oil'),
    ('maize', 'Maize', 'Maize', 'grain'),
    ('wheat', 'Wheat, US HRW', 'Wheat (US HRW)', 'grain'),
    ('brent', 'Crude oil, Brent', 'Crude oil, Brent', 'energy'),
    ('urea', 'Urea', 'Urea (fertiliser)', 'energy'),
    ('chicken', 'Chicken', 'Chicken', 'meat'),
    ('beef', 'Beef', 'Beef', 'meat'),
    ('shrimp', 'Shrimps, Mexican', 'Shrimp (Mexico)', 'meat'),
]
SINCE = 2010


def get(url, timeout=120):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def pink():
    import pandas as pd
    try:
        page = get(PAGE, 60).decode('utf-8', 'replace')
        urls = sorted(set(re.findall(r'https?://[^"\']+CMO-Historical-Data-Monthly\.xlsx', page)))
        url = urls[0] if urls else FALLBACK
    except Exception:
        url = FALLBACK
    raw = get(url)
    df = pd.read_excel(io.BytesIO(raw), sheet_name='Monthly Prices', header=None)
    head = [str(x) if x == x else '' for x in df.iloc[4]]
    units = [str(x) if x == x else '' for x in df.iloc[5]]
    updated = next((str(df.iloc[i, 0]) for i in range(5) if 'Updated' in str(df.iloc[i, 0])), '')
    rows = df.iloc[6:]
    months, vals = [], {k: [] for k, *_ in SERIES}
    cols = {}
    for k, title, *_ in SERIES:
        c = next((i for i, h in enumerate(head) if re.sub(r'\s*\*+\s*$', '', h).strip().lower() == title.lower()), None)
        if c is None:
            c = next((i for i, h in enumerate(head) if h.lower().startswith(title.lower())), None)
        cols[k] = c
    for _, r in rows.iterrows():
        p = str(r.iloc[0])
        m = re.match(r'(\d{4})M(\d{2})', p)
        if not m or int(m.group(1)) < SINCE:
            continue
        months.append(f'{m.group(1)}-{m.group(2)}')
        for k in vals:
            c = cols[k]
            v = r.iloc[c] if c is not None else None
            try:
                v = round(float(v), 3)
            except (TypeError, ValueError):
                v = None
            vals[k].append(v)
    # trailing months still empty for every series (not published yet) are dropped
    while months and all(vals[k][-1] is None for k in vals):
        months.pop()
        for k in vals:
            vals[k].pop()
    series = {k: {'label': lab, 'group': g, 'unit': (units[cols[k]].strip('() ') if cols[k] is not None else ''), 'values': vals[k]}
              for k, _, lab, g in SERIES if cols[k] is not None}
    missing = [k for k in cols if cols[k] is None]
    return {'source': 'World Bank Commodity Price Data (The Pink Sheet), monthly, nominal USD', 'url': url,
            'updated': updated.replace('Updated on', '').strip(), 'months': months, 'series': series, 'missing': missing}


def norway():
    d = json.load(io.open(os.path.join(ROOT, 'data', 'data.json'), encoding='utf-8'))
    M = {}
    for r in d.get('records', []):
        k = f"{r['year']}-{r['month']:02d}"
        o = M.setdefault(k, [0.0, 0.0, 0.0])
        o[0] += (r.get('feed_kg') or 0) / 1000
        o[1] += (r.get('uttak_kg') or 0) / 1000
        o[2] += (r.get('biomasse_kg') or 0) / 1000
    return [{'m': k, 'feed_t': round(v[0]), 'harvest_t': round(v[1]), 'biomass_t': round(v[2])} for k, v in sorted(M.items()) if v[0] > 0]


def scotland():
    d = json.load(io.open(os.path.join(ROOT, 'data', 'scotland.json'), encoding='utf-8'))
    out = []
    for k, v in sorted(d.get('national', {}).items()):
        if len(v) >= 3 and v[2]:
            out.append({'m': f'{k[:4]}-{k[4:]}', 'feed_t': round(v[2]), 'biomass_t': round(v[0])})
    return out


def iceland():
    p = os.path.join(ROOT, 'data', 'iceland_mast.json')
    if not os.path.exists(p):
        return []
    d = json.load(io.open(p, encoding='utf-8'))
    return [{'m': x['m'], 'feed_t': x.get('feed_t'), 'harvest_t': x.get('harvest_t'), 'biomass_t': x.get('biomass_t')} for x in d.get('national', []) if x.get('feed_t')]


def main():
    try:
        old = json.load(io.open(OUT, encoding='utf-8'))
    except Exception:
        old = {}
    out = {'meta': {'generated': dt.date.today().isoformat(), 'status': {}}}
    for name, fn in (('prices', pink), ('norway', norway), ('scotland', scotland), ('iceland', iceland)):
        try:
            v = fn()
            out[name] = v
            out['meta']['status'][name] = 'ok'
        except Exception as e:  # noqa: BLE001
            out[name] = old.get(name)
            out['meta']['status'][name] = f'{type(e).__name__}: {str(e)[:150]} (previous kept)'
    try:
        out['manual'] = json.load(io.open(MANUAL, encoding='utf-8'))
    except Exception as e:  # noqa: BLE001
        out['manual'] = {}
        out['meta']['status']['manual'] = f'not read: {e}'
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    P = out.get('prices') or {}
    print(f"feed: prices {len(P.get('months', []))} months to {(P.get('months') or ['-'])[-1]} ({len(P.get('series', {}))} series, missing {P.get('missing')}), "
          f"Norway {len(out.get('norway') or [])} months, Scotland {len(out.get('scotland') or [])}, Iceland {len(out.get('iceland') or [])}; status {out['meta']['status']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
