#!/usr/bin/env python3
"""
Collecte AIS des bateaux de transport de poisson vivant (wellboats / bronnbater) via aisstream.io.

Lance toutes les 2 heures par .github/workflows/collecte-ais.yml : ecoute le flux AIS gratuit d'aisstream
pendant AIS_SECONDS secondes sur les regions salmonicoles, puis garde :
  - data/ais/vessels.json      registre des wellboats reperes (MMSI, nom, indicatif, type, destination,
                               pays du pavillon, premiere / derniere fois vu, raison du reperage)
  - data/ais/pos/AAAA-MM-JJTHH.csv.gz   positions de ces bateaux pendant l'ecoute (au plus une toutes les 3 min)
Un bateau est repere comme wellboat si :
  - son indicatif d'appel est dans la liste Mattilsynet des transports de poisson vivant (data/wellboats_no.json), ou
  - sa destination AIS parle de ferme ("FISHFARM", "FISH FARMS", "MERD", "OPPDRETT"...) et son type est 70-79/90-99, ou
  - son nom correspond a une flotte connue de wellboats (Ronja, Ro ..., Gaso, Aqua ..., Migdale, Kallista...).
Les positions des autres navires ne sont pas gardees.

    AISSTREAM_KEY=... python3 scripts/collect_ais.py
"""
import asyncio
import csv
import gzip
import io
import json
import os
import pathlib
import re
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR = ROOT / 'data' / 'ais'
REG = DIR / 'vessels.json'
SEC = int(os.environ.get('AIS_SECONDS', '1200'))
KEY = os.environ.get('AISSTREAM_KEY') or os.environ.get('AISTREAM_KEY')

BOX = {  # [[lat_min, lon_min], [lat_max, lon_max]]
    'NO': [[57.8, 4.0], [71.5, 31.5]], 'GB': [[55.3, -8.0], [60.9, -0.6]], 'FO': [[61.3, -7.8], [62.5, -6.2]], 'IS': [[63.2, -25.0], [66.7, -13.0]],
    'CA-BC': [[48.2, -129.5], [52.5, -122.5]], 'CA-ATL': [[43.3, -67.5], [49.8, -52.5]], 'AU': [[-44.0, 144.5], [-40.5, 148.5]], 'CL': [[-55.5, -76.0], [-41.0, -71.5]]}
MID = {'257': 'NO', '258': 'NO', '259': 'NO', '231': 'FO', '251': 'IS', '232': 'GB', '233': 'GB', '234': 'GB', '235': 'GB', '316': 'CA', '725': 'CL', '503': 'AU', '219': 'DK', '220': 'DK'}
DEST = re.compile(r'(?i)fish\s*-?\s*farm|fiskeoppdr|oppdrett|\bmerd|lokalitet|smolt|well\s*boat|br[øo]nnb|salmon farm|piscicult|centro de cultivo|\bfarms?\b')
NAME = re.compile(r'(?i)^(ronja\b|ro (venture|fortune|fjell|vision|arctic|server|master|sea|chief|pioneer|north|west|south|east)|g[åa]s[øo]\b|aqua [a-zæøå]|seihav|novatrans|migdale|kallista|inverlussa|steigen|havtrans|bj[øo]rg pauline|vestfjord|frøy|froy|viking saga|tanja|ronja)')


def region(lat, lon):
    for k, ((a, b), (c, d)) in BOX.items():
        if a <= lat <= c and b <= lon <= d:
            return k
    return ''


async def listen(wb_cs):
    import websockets
    static, pos = {}, {}
    t0 = time.time(); n = 0
    while time.time() - t0 < SEC:
        try:
            async with websockets.connect('wss://stream.aisstream.io/v0/stream', max_size=2 ** 24, ping_interval=20) as ws:
                await ws.send(json.dumps({'APIKey': KEY, 'BoundingBoxes': list(BOX.values()),
                                          'FilterMessageTypes': ['PositionReport', 'ShipStaticData', 'StandardClassBPositionReport']}))
                while time.time() - t0 < SEC:
                    try:
                        m = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                    except asyncio.TimeoutError:
                        continue
                    if 'error' in m:
                        print('erreur aisstream :', m); return static, pos, n
                    n += 1
                    md = m.get('MetaData', {}); mm = str(md.get('MMSI') or '')
                    if not mm:
                        continue
                    if m.get('MessageType') == 'ShipStaticData':
                        s = m['Message']['ShipStaticData']
                        static[mm] = {'name': (s.get('Name') or '').strip(), 'cs': (s.get('CallSign') or '').strip().upper().replace(' ', ''), 'type': s.get('Type'),
                                      'dest': (s.get('Destination') or '').strip(), 'imo': s.get('ImoNumber') or None,
                                      'len': (s.get('Dimension') or {}).get('A', 0) + (s.get('Dimension') or {}).get('B', 0) or None}
                    else:
                        p = m['Message'].get('PositionReport') or m['Message'].get('StandardClassBPositionReport') or {}
                        la, lo = md.get('latitude'), md.get('longitude')
                        if la is None or lo is None:
                            continue
                        ts = (md.get('time_utc') or '')[:19]
                        L = pos.setdefault(mm, [])
                        if L and ts[:15] == L[-1][0][:15] and int(ts[15:16] or 0) // 3 == int(L[-1][0][15:16] or 0) // 3:
                            continue                                    # au plus une position toutes les ~3 minutes
                        L.append([ts, round(la, 5), round(lo, 5), p.get('Sog'), p.get('Cog'), p.get('NavigationalStatus')])
        except Exception as e:  # noqa: BLE001  connexion coupee : on se reconnecte
            print('reconnexion :', str(e)[:120]); await asyncio.sleep(5)
    return static, pos, n


def main():
    if not KEY:
        print('AISSTREAM_KEY manquante'); return
    DIR.mkdir(parents=True, exist_ok=True); (DIR / 'pos').mkdir(exist_ok=True)
    wb = json.load(open(ROOT / 'data' / 'wellboats_no.json', encoding='utf-8'))['vessels']
    reg = json.load(open(REG, encoding='utf-8')) if REG.exists() else {'vessels': {}}
    V = reg['vessels']
    static, pos, n = asyncio.run(listen(set(wb)))
    now = time.strftime('%Y-%m-%dT%H:%M', time.gmtime())
    new = 0
    for mm, s in static.items():
        why = 'mattilsynet' if s['cs'] in wb else 'destination' if (DEST.search(s['dest']) and (s['type'] or 0) in range(70, 100)) else 'name' if NAME.search(s['name']) else ''
        if mm in V:
            v = V[mm]; v.update({k: s[k] for k in ('name', 'cs', 'type', 'dest', 'imo', 'len') if s.get(k)}); v['last_seen'] = now
            if why and why != v.get('why'):
                v.setdefault('why_also', []); v['why_also'] = sorted(set(v['why_also'] + [why]))
        elif why:
            V[mm] = {**s, 'flag': MID.get(mm[:3], ''), 'why': why, 'first_seen': now, 'last_seen': now,
                     **({'owner': wb[s['cs']]['owner']} if s['cs'] in wb else {})}
            new += 1
    rows = []
    for mm, L in pos.items():
        if mm not in V:
            continue
        V[mm]['last_pos'] = now
        for ts, la, lo, sog, cog, st in L:
            rows.append([ts, mm, la, lo, sog, cog, st, region(la, lo)])
    if rows:
        buf = io.StringIO(); w = csv.writer(buf); w.writerow(['time_utc', 'mmsi', 'lat', 'lon', 'sog', 'cog', 'status', 'region']); w.writerows(sorted(rows))
        f = DIR / 'pos' / (time.strftime('%Y-%m-%dT%H', time.gmtime()) + '.csv.gz')
        f.write_bytes(gzip.compress(buf.getvalue().encode()))
    reg['updated'] = now
    reg['runs'] = reg.get('runs', 0) + 1
    reg.setdefault('log', []).append([now, SEC, n, len(static), len(V), new, len(rows), len({r[1] for r in rows})])
    reg['log'] = reg['log'][-400:]
    json.dump(reg, open(REG, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    seen = {r[1] for r in rows}
    by = {}
    for mm in seen:
        by[V[mm]['flag'] or '?'] = by.get(V[mm]['flag'] or '?', 0) + 1
    print(f'{n} messages, {len(static)} fiches navire ; registre {len(V)} wellboats (+{new}) ; {len(rows)} positions de {len(seen)} wellboats {by}')


if __name__ == '__main__':
    main()
