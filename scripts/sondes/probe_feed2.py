"""Sonde 4 : build_iceland_mast.py puis build_feed.py, resumes."""
import json, subprocess, sys
for s in ('scripts/build_iceland_mast.py', 'scripts/build_feed.py'):
    r = subprocess.run([sys.executable, s], capture_output=True, text=True); print(s, '\n', r.stdout[-3000:], r.stderr[-3000:])
d = json.load(open('data/iceland_mast.json')); C = d['cycles']
print('IS national last', d['national'][-3:]); print('IS cycles', C['iceland'], C['short_runs']); print('by co', C['by_company']); print('active', len(C['active']), [(a['co'], a['age']) for a in C['active']])
f = json.load(open('data/feed.json')); P = f['prices']
print('prices', P['updated'], P['months'][-3:], {k: v['values'][-1] for k, v in P['series'].items()}, {k: v['unit'] for k, v in P['series'].items()})
print('norway', f['norway'][-2:]); print('scotland', f['scotland'][-2:]); print('iceland', f['iceland'][-2:])
