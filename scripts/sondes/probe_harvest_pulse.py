"""Sonde : 'pouls des abattages' Norvege, semaine par semaine 2024-2026 (lignes FEAT dans le log).
Passages des bateaux d'abattage et des wellboats de recolte, ponderes par la capacite (MTB) de la ferme,
et livraisons aux cages d'attente des abattoirs (ventemerd)."""
import sys, json, time
from collections import defaultdict
sys.path.insert(0, 'scripts')
import build_wellboats as B

T = B.token()
V = B.get('/v1/geodata/fishhealth/vessels', T) or []
kinds = {v['mmsi']: ('S' if v.get('isSlaughterBoat') else 'W') for v in V if v.get('isWellboat') or v.get('isSlaughterBoat')}
reg = json.load(open('data/data.json'))['bw_register']
cap = {k: v or 0 for k, v in reg['site_cap'].items()}
cages = [str(c['no']) for c in reg['slaughter_cages']]
hist = json.load(open('data/wellboats_hist.json'))['years']
st = json.load(open('data/bw_farm_state.json')); idx = {k: i for i, k in enumerate(st['weeks'])}; S = st['sites']
def cls(no, y, w, k):
    if k == 'S': return 'S'
    i = idx.get(f'{y}-{w:02d}'); v = S.get(str(no))
    if i is None or not v: return 'H'
    if 'T' in v[max(0, i - 1):i + 2]: return 'T'
    if 'F' in v[max(0, i - 8):i] and ('A' in v[i:i + 4] or 'T' in v[i:i + 4]): return 'M'
    return 'H'
farm = hist.get('2024', []) + hist.get('2025', [])
t0 = time.time(); farm += B.year_visits(sorted(reg['site_po'], key=int), 2026, T, kinds); print('farm 2026', round(time.time() - t0), 's')
cv = []
for Y in (2024, 2025, 2026):
    cv += B.year_visits(cages, Y, T, kinds)
print('visites aux cages d attente', len(cv))
F = defaultdict(lambda: defaultdict(float))
for no, y, w, mm, k, start, hrs in farm:
    c = cls(no, y, w, k); key = y * 100 + w; cp = cap.get(str(no), 0)
    F[key][c] += 1; F[key][c + 'cap'] += cp; F[key][c + 'h'] += hrs or 0
for no, y, w, mm, k, start, hrs in cv:
    key = y * 100 + w; F[key]['C'] += 1; F[key]['Ch'] += hrs or 0; F[key]['C' + k] += 1
cols = ['S', 'Scap', 'Sh', 'H', 'Hcap', 'Hh', 'T', 'M', 'C', 'Ch', 'CW', 'CS']
print('COLS', json.dumps(cols))
rows = [[k] + [round(F[k][c]) for c in cols] for k in sorted(F)]
for i in range(0, len(rows), 40):
    print('FEAT', json.dumps(rows[i:i + 40], separators=(',', ':')))
