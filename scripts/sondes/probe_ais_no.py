"""Sonde : combien des bronnbater agrees (Mattilsynet) aisstream voit-il en Norvege en 20 min ?"""
import os, json, time, asyncio, collections, re
import websockets
KEY = os.environ.get('AISSTREAM_KEY') or os.environ.get('AISTREAM_KEY')
WB = json.load(open('data/wellboats_no.json'))['vessels']
BOX = [[[57.8, 4.0], [71.5, 31.5]], [[55.3, -8.0], [60.9, -0.6]]]
async def run(sec):
    static, pos, n = {}, collections.defaultdict(list), 0
    async with websockets.connect('wss://stream.aisstream.io/v0/stream', max_size=2**24, ping_interval=20) as ws:
        await ws.send(json.dumps({'APIKey': KEY, 'BoundingBoxes': BOX, 'FilterMessageTypes': ['PositionReport', 'ShipStaticData']}))
        t0 = time.time()
        while time.time() - t0 < sec:
            try: m = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            except asyncio.TimeoutError: continue
            n += 1; md = m.get('MetaData', {}); mm = md.get('MMSI')
            if m.get('MessageType') == 'ShipStaticData':
                s = m['Message']['ShipStaticData']; static[mm] = {'name': s.get('Name', '').strip(), 'cs': s.get('CallSign', '').strip().upper(), 'type': s.get('Type'), 'dest': s.get('Destination', '').strip(), 'imo': s.get('ImoNumber')}
            elif m.get('MessageType') == 'PositionReport':
                p = m['Message']['PositionReport']; pos[mm].append([md.get('time_utc', '')[:19], round(md['latitude'], 4), round(md['longitude'], 4), p.get('Sog'), p.get('NavigationalStatus')])
    print('messages', n, 'navires avec statique', len(static), 'avec position', len(pos))
    hit = {mm: s for mm, s in static.items() if s['cs'] in WB}
    print(f'bronnbater agrees vus : {len(hit)} / {len(WB)}')
    for mm, s in sorted(hit.items(), key=lambda x: x[1]['name']):
        P = pos.get(mm, []); print(f"  {s['name']:24s} {s['cs']:8s} mmsi {mm}  type {s['type']}  positions {len(P)}  {P[-1] if P else ''}  -> {s['dest']}")
    # bateaux non listes qui ressemblent a des wellboats (noms connus en Ecosse / ailleurs)
    oth = [s for s in static.values() if s['cs'] not in WB and re.search(r'(?i)ronja|inverlussa|migdale|kallista|kvitbj|seihav|novatrans|well ?boat|gåsø|gaso|steigen|aqua|smolt|salmon', s['name'])]
    print('autres candidats', len(oth)); print(oth[:40])
    json.dump({'static': static, 'hit': hit}, open('sonde_out/ais_no.json', 'w'))
asyncio.run(run(1080))
