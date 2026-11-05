"""Sonde 3 : lance build_iceland_mast.py et montre ce qu'il a lu."""
import json, os, subprocess, sys
r = subprocess.run([sys.executable, 'scripts/build_iceland_mast.py'], capture_output=True, text=True)
print(r.stdout[-6000:]); print(r.stderr[-4000:])
p = 'data/iceland_mast.json'
if os.path.exists(p):
    d = json.load(open(p, encoding='utf-8'))
    print('keys', list(d))
    print('national last', d.get('national', [])[-14:])
    print('species', d.get('meta', {}).get('species_seen'))
    S = d.get('sites', []); print('site rows', len(S), S[:5])
    C = d.get('cycles', {}); print('cycles iceland', C.get('iceland')); print('by company', C.get('by_company')); print('by fjord', C.get('by_fjord'))
    print('done sample', C.get('done', [])[:12]); print('active', C.get('active', [])[:40])
