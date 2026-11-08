#!/usr/bin/env python3
"""
Trait de cote fin pour la carte de l'onglet Sea temperature : terres de Natural Earth au 1:10 000 000 (domaine public),
decoupees sur les bassins salmonicoles et simplifiees.

    python3 scripts/build_coast.py      -> data/coast_hd.json   (a relancer seulement si les cadres changent)

La carte du monde de la page (WORLD, 1:110 000 000) reste utilisee partout ; en zoomant, la page masque ces cadres et
y dessine ce trait plus fin.
"""
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'coast_hd.json')
SRC = ['https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson',
       'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_minor_islands.geojson']
# cadres (lon min, lat min, lon max, lat max)
BOXES = {'NO': [3, 57, 32, 72], 'NA': [-28, 51, 3, 67.5], 'BC': [-132, 47, -122, 55.5], 'CAE': [-70, 42.5, -52, 50],
         'CL': [-80, -56, -70, -38], 'AU': [143, -44.5, 149.5, -39.5]}
TOL = 0.012     # tolerance de simplification (degres, ~1 km)


def clip(ring, b):
    """Sutherland-Hodgman : polygone decoupe par le rectangle b."""
    x0, y0, x1, y1 = b
    def cut(pts, inside, inter):
        out = []
        for i, p in enumerate(pts):
            q = pts[i - 1]
            if inside(p):
                if not inside(q): out.append(inter(q, p))
                out.append(p)
            elif inside(q): out.append(inter(q, p))
        return out
    def ix(x):
        return lambda p, q: (x, p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0]))
    def iy(y):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]), y)
    pts = [tuple(p[:2]) for p in ring]
    for inside, inter in ((lambda p: p[0] >= x0, ix(x0)), (lambda p: p[0] <= x1, ix(x1)), (lambda p: p[1] >= y0, iy(y0)), (lambda p: p[1] <= y1, iy(y1))):
        if not pts: break
        pts = cut(pts, inside, inter)
    return pts


def dp(pts, tol):
    """Douglas-Peucker iteratif."""
    if len(pts) < 4: return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True; st = [(0, len(pts) - 1)]
    while st:
        a, b = st.pop(); ax, ay = pts[a]; bx, by = pts[b]; dx, dy = bx - ax, by - ay; n = (dx * dx + dy * dy) ** .5 or 1e-12
        imax, dmax = None, tol
        for i in range(a + 1, b):
            d = abs(dy * pts[i][0] - dx * pts[i][1] + bx * ay - by * ax) / n
            if d > dmax: imax, dmax = i, d
        if imax is not None:
            keep[imax] = True; st += [(a, imax), (imax, b)]
    return [p for p, k in zip(pts, keep) if k]


def main():
    rings = []
    for u in SRC:
        with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'salmon-outlook'}), timeout=180) as r:
            gj = json.loads(r.read())
        for f in gj['features']:
            g = f['geometry']; polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
            for poly in polys: rings.append(poly[0])
        print(u.rsplit('/', 1)[1], len(rings), 'anneaux cumules')
    out, npts = {}, 0
    for k, b in BOXES.items():
        L = []
        for ring in rings:
            xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
            if max(xs) < b[0] or min(xs) > b[2] or max(ys) < b[1] or min(ys) > b[3]: continue
            c = clip(ring, b)
            if len(c) < 3: continue
            if c[0] == c[-1]: c = c[:-1]
            # anneau ferme : on coupe au point le plus eloigne du premier, puis on simplifie les deux moities (sinon tout s'efface)
            j = max(range(len(c)), key=lambda i: (c[i][0] - c[0][0]) ** 2 + (c[i][1] - c[0][1]) ** 2)
            c = dp(c[:j + 1], TOL)[:-1] + dp(c[j:] + [c[0]], TOL)[:-1]
            c = [[round(x, 3), round(y, 3)] for x, y in c]
            if len(c) >= 3: L.append(c); npts += len(c)
        out[k] = {'box': b, 'rings': L}
        print(k, len(L), 'polygones')
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps({'meta': {'source': 'Natural Earth 1:10m land and minor islands (public domain)', 'tolerance_deg': TOL}, 'areas': out}, separators=(',', ':')))
    print(f'{OUT} : {npts} points, {os.path.getsize(OUT) // 1024} ko')


if __name__ == '__main__':
    main()
