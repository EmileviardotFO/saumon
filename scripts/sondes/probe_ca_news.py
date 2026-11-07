"""Sonde : ce que remontent les nouvelles requetes presse sur le Canada atlantique (sans rien ecrire)."""
import sys; sys.path.insert(0, 'scripts')
import update_events as U
U.FEEDS[:] = []
U.GQ[:] = [q for q in U.GQ if q[1] == 'CA']
st = {}
for it in sorted(U.news_items(st), key=lambda x: x['date'], reverse=True): print(it['date'], it['basins'], it['causes'], it['title'][:120], '|', it['source'])
print(st)
