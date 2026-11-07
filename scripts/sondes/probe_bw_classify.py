"""Sonde Norvege : classer chaque passage de wellboat (recolte / smolts / traitement) grace a l'etat hebdomadaire
des fermes (BarentsWatch : en jachere, traitements), puis agreger par zone et par mois (lignes AGG dans le log)."""
import os, sys, json, time, datetime as dt
from collections import defaultdict, Counter
import requests
sys.path.insert(0, 'scripts')
import build_wellboats as B

T = B.token()
def post(path):
    for i in range(4):
        try:
            r = requests.post(B.API + path, json={}, headers={**B.H, 'Authorization': 'Bearer ' + T}, timeout=120)
            if r.ok: return r.json()
        except requests.RequestException: pass
        time.sleep(5 * (i + 1))
    return None

reg = json.load(open('data/data.json')).get('bw_register') or {}
site_po = reg.get('site_po', {})
# 1. etat hebdomadaire de chaque ferme
weeks = []
d = dt.date(2023, 10, 2)
while d < dt.date.today() - dt.timedelta(days=6):
    y, w, _ = d.isocalendar(); weeks.append((y, w)); d += dt.timedelta(weeks=1)
idx = {k: i for i, k in enumerate(weeks)}
state = defaultdict(dict)  # site -> {i: 'F'|'A'}
treat = defaultdict(dict)  # site -> {i: set(types)}
tc = Counter()
t0 = time.time()
for (y, w) in weeks:
    L = post(f'/v2/geodata/fishhealth/locality/{y}/{w}') or []
    for s in L:
        loc = s.get('locality') or {}; no = loc.get('no')
        if no is None or loc.get('isOnLand'): continue
        rep = s.get('liceReport') or {}
        i = idx[(y, w)]
        if rep.get('isFallow'): state[str(no)][i] = 'F'
        elif rep.get('hasReported'): state[str(no)][i] = 'A'
        tt = [t if isinstance(t, str) else (t or {}).get('type') for t in (s.get('liceTreatments') or [])]
        tt = {t for t in tt if t}
        if tt: treat[str(no)][i] = tt; tc.update(tt)
print('etats', len(state), 'sites ;', len(weeks), 'semaines en', round(time.time() - t0), 's ; types de traitement', tc.most_common(12))
# 2. passages 2024, 2025, 2026
V = B.get('/v1/geodata/fishhealth/vessels', T) or []
kinds = {v['mmsi']: ('S' if v.get('isSlaughterBoat') else 'W') for v in V if v.get('isWellboat') or v.get('isSlaughterBoat')}
locs = sorted(site_po, key=int)
hist = json.load(open('data/wellboats_hist.json'))['years']
rows = hist.get('2025', [])
for Y in (2024, 2026):
    t0 = time.time(); r = B.year_visits(locs, Y, T, kinds); rows += r; print(Y, len(r), 'passages', round(time.time() - t0), 's')
MECH = None
def cls(no, y, w, k):
    if k == 'S': return 'H'
    i = idx.get((y, w))
    if i is None: return 'H'
    st = state.get(str(no), {}); tr = treat.get(str(no), {})
    if any(tr.get(j) for j in (i - 1, i, i + 1)):
        tt = set().union(*[tr.get(j, set()) for j in (i - 1, i, i + 1)])
        if tt - {'inFeed', 'feed', 'cleanerFish'}: return 'T'
    before = [st.get(j) for j in range(i - 8, i)]
    after = [st.get(j) for j in range(i, i + 4)]
    if 'F' in before and 'A' in after: return 'M'   # mise en eau de smolts
    return 'H'
agg = defaultdict(lambda: [0, 0, 0, 0.0, 0.0, 0.0])  # H, M, T visites ; H, M, T heures
cc = Counter()
for no, y, w, mm, k, start, hrs in rows:
    if not start: continue
    c = cls(no, y, w, k); cc[c, k] += 1
    po = site_po.get(str(no))
    j = {'H': 0, 'M': 1, 'T': 2}[c]
    for key in ('NO', f'PO{po}'):
        a = agg[(key, start[:7])]; a[j] += 1; a[3 + j] += hrs or 0
print('classes', cc.most_common())
items = [[k[0], k[1]] + [round(x) for x in v] for k, v in sorted(agg.items())]
for i in range(0, len(items), 60):
    print('AGG', json.dumps(items[i:i + 60], separators=(',', ':')))
