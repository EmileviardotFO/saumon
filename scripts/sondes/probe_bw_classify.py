"""Sonde Norvege : classer chaque passage de wellboat (recolte / smolts / traitement) grace a l'etat hebdomadaire
des fermes (BarentsWatch : en jachere, traitements), puis comparer aux chiffres officiels Fdir par zone."""
import os, sys, json, datetime as dt, concurrent.futures as cf
from collections import defaultdict, Counter
sys.path.insert(0, 'scripts')
import build_wellboats as B

T = B.token()
# 1. format du point hebdomadaire
j = B.get('/v1/geodata/fishhealth/2025/40', T)
print('week keys', list(j)[:10] if isinstance(j, dict) else type(j))
L = (j or {}).get('localities') or []
print('n loc', len(L), 'cles', list(L[0])[:40] if L else None); print(json.dumps(L[0])[:600] if L else '')
