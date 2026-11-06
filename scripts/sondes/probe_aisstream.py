"""Sonde aisstream.io : couverture par region salmonicole et par ligne de fret (3 x 2 min)."""
import os, json, time, asyncio, collections
import websockets
KEY = os.environ.get('AISSTREAM_KEY') or os.environ.get('AISTREAM_KEY')
print('cle presente :', bool(KEY))
BOX = {  # [[lat_min, lon_min], [lat_max, lon_max]]
    'Norway': [[58.0, 4.5], [71.5, 31.0]], 'Faroe': [[61.3, -7.8], [62.5, -6.2]], 'Iceland': [[63.2, -25.0], [66.7, -13.0]],
    'Scotland': [[55.3, -8.0], [60.9, -0.6]], 'Chile': [[-55.5, -76.0], [-41.0, -71.5]], 'Canada BC': [[48.2, -129.0], [51.5, -122.5]],
    'Canada Atl': [[44.0, -67.5], [48.0, -52.0]], 'Tasmania': [[-44.0, 144.5], [-40.5, 148.5]], 'North Sea / Channel': [[50.5, -1.5], [58.0, 9.0]],
    'US East': [[40.0, -71.5], [44.8, -66.0]]}
async def run(sec):
    seen = collections.defaultdict(set); pos = collections.Counter(); static = {}
    async with websockets.connect('wss://stream.aisstream.io/v0/stream', max_size=2**24) as ws:
        await ws.send(json.dumps({'APIKey': KEY, 'BoundingBoxes': list(BOX.values()), 'FilterMessageTypes': ['PositionReport', 'ShipStaticData', 'StandardClassBPositionReport']}))
        t0 = time.time()
        while time.time() - t0 < sec:
            try: m = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            except asyncio.TimeoutError: print('rien depuis 30 s'); continue
            if 'error' in m: print('ERREUR', m); return
            md = m.get('MetaData', {}); la, lo = md.get('latitude'), md.get('longitude')
            for k, ((a, b), (c, d)) in BOX.items():
                if la is not None and a <= la <= c and b <= lo <= d: seen[k].add(md.get('MMSI')); pos[k] += 1
            if m.get('MessageType') == 'ShipStaticData':
                s = m['Message']['ShipStaticData']; static[md.get('MMSI')] = [s.get('Name', '').strip(), s.get('CallSign', '').strip(), s.get('Type'), s.get('Destination', '').strip()]
    for k in BOX: print(f'{k:22s} navires {len(seen[k]):5d}  messages {pos[k]:6d}')
    print('statiques', len(static)); print(list(static.values())[:40])
    import re
    print([v for v in static.values() if re.search(r'(?i)ronja|norr[øo]na|mykines|akranes|eimskip|samskip|smyril|brua|dettifoss|br[uú]arfoss|godafoss|selfoss|lagarfoss|gasø|g[åa]s[øo]|seihav|novatrans|inverlussa|patag|orca', v[0])])
asyncio.run(run(150))
