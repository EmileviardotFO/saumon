#!/usr/bin/env python3
"""
Iceland: tests and reads what MAST (Matvælastofnun, the Icelandic Food and Veterinary Authority) publishes, for the Iceland tab.

    python3 scripts/build_iceland.py        -> data/iceland.json

1. MAST's public map server (GeoServer, WFS): lists every layer, and downloads those about fish farming (farm sites, sea areas,
   licences, applications) with their attributes, so that licences and biomass by fjord can be read when MAST publishes them there.
2. MAST's aquaculture dashboard (Mælaborð fiskeldis): finds how it is embedded (Power BI, ArcGIS, Tableau...), the first step to
   reading its monthly figures (biomass, fish numbers, mortality, sea lice by fjord).
Free, no key. The result says plainly what could be read and what could not.
"""
import datetime as dt
import io
import json
import os
import re
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'iceland.json')
WFS = 'https://geoserver.mast.is/geoserver/wfs'
DASH = ['https://www.mast.is/is/maelabord-fiskeldis', 'https://www.mast.is/is/fiskeldi/maelabord-fiskeldis']
UA = {'User-Agent': 'Mozilla/5.0 (salmon dashboard; contact via GitHub)'}
UTILE = re.compile(r'eldi|eldis|fisk|sjokv|sjókv|leyfi|rekstrar|lifmass|lífmass|burdar|burðar|kvi|kví|aquac|farm|site|svaed|svæð', re.I)


def get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def couches():
    xml = get(WFS + '?service=WFS&request=GetCapabilities&version=2.0.0').decode('utf-8', 'replace')
    out = []
    for ft in re.findall(r'<(?:wfs:)?FeatureType>(.*?)</(?:wfs:)?FeatureType>', xml, re.S):
        nm = re.search(r'<(?:wfs:)?Name>(.*?)</', ft); ti = re.search(r'<(?:wfs:)?Title>(.*?)</', ft); ab = re.search(r'<(?:wfs:)?Abstract>(.*?)</', ft, re.S)
        if nm: out.append({'name': nm.group(1).strip(), 'title': (ti.group(1).strip() if ti else ''), 'abstract': (ab.group(1).strip()[:200] if ab else '')})
    return out


def objets(nom, n=2000):
    q = {'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature', 'typeNames': nom, 'outputFormat': 'application/json', 'count': n, 'srsName': 'EPSG:4326'}
    j = json.loads(get(WFS + '?' + urllib.parse.urlencode(q), timeout=120).decode('utf-8', 'replace'))
    feats = []
    for f in j.get('features', []):
        g = f.get('geometry') or {}; c = g.get('coordinates')
        while isinstance(c, list) and c and isinstance(c[0], list): c = c[0]          # premier point d'un polygone
        feats.append({'props': f.get('properties', {}), 'lon': c[0] if isinstance(c, list) and len(c) >= 2 else None, 'lat': c[1] if isinstance(c, list) and len(c) >= 2 else None})
    return feats


def tableau_de_bord():
    for url in DASH:
        try:
            h = get(url).decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001
            continue
        srcs = re.findall(r'<iframe[^>]+src="([^"]+)"', h, re.I) + re.findall(r'(https://app\.powerbi\.com/[^"\'\s<]+|https://[^"\'\s<]*arcgis[^"\'\s<]+|https://public\.tableau\.com/[^"\'\s<]+)', h)
        return url, sorted(set(srcs))[:5]
    return None, []


def main():
    res = {'meta': {'probed': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}, 'layers': [], 'features': {}}
    notes = []
    try:
        L = couches()
        res['meta']['wfs_layers_total'] = len(L)
        for c in L:
            if not UTILE.search(c['name'] + ' ' + c['title'] + ' ' + c['abstract']): continue
            try:
                F = objets(c['name'])
                c['features'] = len(F); c['fields'] = sorted({k for f in F[:50] for k in f['props']})[:40]
                res['features'][c['name']] = F
            except Exception as e:  # noqa: BLE001
                c['features'] = None; c['error'] = str(e)[:120]
            res['layers'].append(c)
        notes.append(f"map server reachable: {len(L)} layers, {len(res['layers'])} about fish farming"
                     + (f" ({sum(1 for c in res['layers'] if c.get('features'))} downloaded)" if res['layers'] else ''))
    except Exception as e:  # noqa: BLE001
        notes.append(f'map server not reachable ({str(e)[:100]})')
    try:
        url, srcs = tableau_de_bord()
        if url:
            res['meta']['dashboard_page'] = url
            res['meta']['dashboard_embed'] = ', '.join(srcs) if srcs else 'no embedded report found in the page (probably built in JavaScript)'
            notes.append('dashboard page reachable' + (f', embedded report: {srcs[0][:80]}' if srcs else ', embed not found in the raw page'))
        else:
            notes.append('dashboard page not reachable')
    except Exception as e:  # noqa: BLE001
        notes.append(f'dashboard check failed ({str(e)[:80]})')
    res['meta']['summary'] = '; '.join(notes) + '.'
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(res, ensure_ascii=False, separators=(',', ':')))
    print('data/iceland.json :', res['meta']['summary'])


if __name__ == '__main__':
    main()
