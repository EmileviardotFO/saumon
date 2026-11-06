"""Essai du lecteur Subpesca sur une petite plage d'ids, et impression du resultat."""
import json, os, subprocess, sys
env = dict(os.environ, BACKFILL_FROM=os.environ.get('FROM', '130670'), MAX_IDS=os.environ.get('N', '220'), THREADS='4')
r = subprocess.run([sys.executable, 'scripts/build_chile_subpesca.py'], capture_output=True, text=True, env=env)
print(r.stdout[-3000:], r.stderr[-3000:])
d = json.load(open('data/chile_subpesca.json', encoding='utf-8'))
for x in d['resolutions']:
    print('RES', x['id'], x.get('date'), x.get('region'), x.get('fallow'), x.get('modifies'), '|', x.get('company', '')[:60], '| rows', len(x['rows']), 'fish', sum(r['fish'] for r in x['rows']), x.get('error', ''))
    print('    ', x['rows'][:3])
for x in d['reports']: print('REP', json.dumps(x, ensure_ascii=False))
print('STOCK', json.dumps(d['stocking'], ensure_ascii=False)[:1500])
