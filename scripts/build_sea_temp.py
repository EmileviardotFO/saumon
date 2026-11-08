#!/usr/bin/env python3
"""
Temperature de la mer par bassin producteur de saumon, et jours de chaleur.

    python3 scripts/build_sea_temp.py        -> data/sea_temp.json   (NOAA OISST v2.1 via ERDDAP : gratuit, libre de droits, sans cle)

Pour chaque bassin, quelques points en mer pres des fermes (un par grande region de production). Pour chaque point :
temperature de surface journaliere (maille OISST de 0,25° la plus proche en mer), puis
  - moyenne mensuelle et ecart a la normale du meme mois (annees completes disponibles, 2023 et suivantes) ;
  - jours de chaleur par annee et mois : jours au-dessus de 16,5 / 17 / 18 °C (seuils de risque de mortalite cites par
    Canepa et al., Reviews in Aquaculture 2026, « Turning Up the Heat » ; optimum de croissance 12-16 °C, limite haute ~20 °C).
Premier passage (ou SST_FULL=1) : historique complet depuis 2016 ; ensuite chaque jour seuls les 3 derniers mois sont relus.
Norvege : la temperature declaree chaque semaine par les sites (BarentsWatch) reste la reference par zone dans le tableau de bord ;
les points OISST servent a comparer les bassins sur la meme base.
"""
import datetime as dt
import io
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'sea_temp.json')
UA = {'User-Agent': 'Mozilla/5.0 (salmon-outlook sea temperature)'}
SEUILS = (16.5, 17.0, 18.0)
DEBUT = '2016-01-01'
# NOAA OISST v2.1 (satellites + bouees + navires, grille 0,25°, quotidien depuis 1981) via ERDDAP : donnees du gouvernement americain,
# libres de droits y compris pour un usage commercial, sans cle ni quota declare. Open-Meteo (utilise d'abord) n'autorise son API
# gratuite qu'en usage non commercial et sa serie de temperature de mer ne commence qu'a fin 2022.
ERDDAP = 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg_LonPM180.csv'
DECALAGES = [(0, 0), (0, -.25), (0, .25), (.25, 0), (-.25, 0), (0, -.5), (0, .5), (.5, 0), (-.5, 0), (.25, -.25), (-.25, -.25), (.25, .25), (-.25, .25),
             (0, -.75), (0, .75), (.5, -.5), (-.5, -.5), (.5, .5), (-.5, .5), (0, -1), (0, 1), (.75, 0), (-.75, 0)]   # premiere maille de mer proche (OISST masque la cote)

# bassin, identifiant, libelle, latitude, longitude (point en mer, au large immediat des fermes)
POINTS = [
    # Norvege : un point par zone de production (a comparer aux temperatures declarees par les sites, BarentsWatch)
    ('NO', 'no_po1', 'Norway · zone 1 Svenskegrensen–Jæren', 58.45, 5.75),
    ('NO', 'no_po2', 'Norway · zone 2 Ryfylket', 59.15, 5.55),
    ('NO', 'no_po3', 'Norway · zone 3 Karmøy–Sotra', 59.95, 5.00),
    ('NO', 'no_po4', 'Norway · zone 4 Nordhordland–Stadt', 61.20, 4.70),
    ('NO', 'no_po5', 'Norway · zone 5 Stadt–Hustadvika', 62.55, 5.85),
    ('NO', 'no_po6', 'Norway · zone 6 Nordmøre–Sør-Trøndelag', 63.70, 8.30),
    ('NO', 'no_po7', 'Norway · zone 7 Nord-Trøndelag–Bindal', 64.80, 10.80),
    ('NO', 'no_po8', 'Norway · zone 8 Helgeland–Bodø', 66.40, 12.40),
    ('NO', 'no_po9', 'Norway · zone 9 Vestfjorden–Vesterålen', 68.30, 14.20),
    ('NO', 'no_po10', 'Norway · zone 10 Andøya–Senja', 69.40, 16.90),
    ('NO', 'no_po11', 'Norway · zone 11 Kvaløya–Loppa', 70.10, 19.50),
    ('NO', 'no_po12', 'Norway · zone 12 Vest-Finnmark', 70.75, 23.00),
    ('NO', 'no_po13', 'Norway · zone 13 Øst-Finnmark', 70.40, 30.80),
    ('FO', 'fo', 'Faroe Islands', 62.00, -6.60),
    ('IS', 'is_west', 'Iceland · Westfjords', 65.75, -24.10),
    ('IS', 'is_east', 'Iceland · East fjords', 64.90, -13.50),
    ('GB', 'gb_argyll', 'Scotland · Argyll & Clyde', 56.20, -5.90),
    ('GB', 'gb_west', 'Scotland · West Highlands & Skye', 57.30, -6.40),
    ('GB', 'gb_hebrides', 'Scotland · Outer Hebrides', 57.90, -7.20),
    ('GB', 'gb_orkney', 'Scotland · Orkney', 58.85, -3.00),
    ('GB', 'gb_shetland', 'Scotland · Shetland', 60.30, -1.10),
    ('IE', 'ie_west', 'Ireland · West coast', 53.40, -10.10),
    ('CA', 'ca_bc', 'Canada · British Columbia (Broughton)', 50.70, -126.55),
    ('CA', 'ca_bc_west', 'Canada · British Columbia (west Vancouver Island)', 49.30, -126.20),
    ('CA', 'ca_nb', 'Canada · New Brunswick (Bay of Fundy)', 44.95, -66.90),
    ('CA', 'ca_nl', 'Canada · Newfoundland (south coast)', 47.45, -55.60),
    ('CL', 'cl_loslagos', 'Chile · Los Lagos (Chiloé)', -42.30, -73.30),
    ('CL', 'cl_aysen', 'Chile · Aysén', -45.40, -73.80),
    ('CL', 'cl_magallanes', 'Chile · Magallanes', -52.80, -72.80),
    ('AU', 'au_storm', 'Tasmania · Storm Bay / D\'Entrecasteaux', -43.20, 147.45),
    ('AU', 'au_east', 'Tasmania · East coast', -42.60, 148.10),
    ('AU', 'au_macq', 'Tasmania · Macquarie Harbour (west)', -42.30, 145.10),
]
BASSINS = {'NO': 'Norway', 'FO': 'Faroe Islands', 'IS': 'Iceland', 'GB': 'Scotland', 'IE': 'Ireland', 'CA': 'Canada', 'CL': 'Chile', 'AU': 'Tasmania'}


def http(url, tries=3, timeout=60):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:            # trop de requetes : on patiente
                time.sleep(65)
                continue
            if 400 <= e.code < 500:
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(5 * (i + 1))
    raise RuntimeError(f'{url[:120]} : {last}')


def oisst(la, lo, debut, fin):
    """Temperature de surface journaliere NOAA OISST a la maille (la, lo), {date: °C} (vide si maille terrestre)."""
    t1 = 'last' if fin is None else f'{fin}T12:00:00Z'
    tq = '[last-20:1:last]' if debut == 'probe' else f'[({debut}T12:00:00Z):1:({t1})]'
    q = f'?sst{tq}[(0.0)][({la})][({lo})]'
    t0 = time.time()
    try:
        st, raw = http(ERDDAP + urllib.parse.quote(q, safe='?[]():,'))
    except RuntimeError as e:
        if 'HTTP Error 404' in str(e) or 'HTTP Error 400' in str(e):   # periode hors serie (ex. derniers jours pas encore publies)
            return {}
        raise
    out = {}
    for ligne in raw.decode('utf-8', 'replace').splitlines()[2:]:
        c = ligne.split(',')
        if len(c) >= 5 and c[4] not in ('', 'NaN'):
            out[c[0][:10]] = float(c[4])
    print(f'    {la},{lo} {debut}..{fin} -> {len(out)} jours, {time.time() - t0:.1f} s', flush=True)
    return out


def maille(la, lo):
    """Premiere maille de mer autour du point (OISST n'a pas de valeur sur les mailles touchant la terre)."""
    for a, b in DECALAGES:
        c = (math.floor((la + a) * 4) / 4 + .125, math.floor((lo + b) * 4) / 4 + .125)   # centre de maille OISST
        if oisst(c[0], c[1], 'probe', None):
            return c
        time.sleep(1)
    return None


def journalier(la, lo, debut, fin):
    return oisst(la, lo, debut, fin)


def resume(jours, old=None):
    """Moyennes mensuelles, normales et jours de chaleur par mois.
    old : point deja en fichier ; ses mois anterieurs a la periode relue sont conserves (mise a jour incrementale)."""
    mois = defaultdict(list)
    for d, v in jours.items():
        mois[d[:7]].append(v)
    mm = {k: round(sum(v) / len(v), 2) for k, v in sorted(mois.items()) if len(v) >= 20}
    if old:
        d0 = min(mois) if mois else '9999'
        mm = {**{k: v for k, v in (old.get('monthly') or {}).items() if k < d0}, **mm}
    norm = defaultdict(list)
    for k, v in mm.items():
        if k[:4] < str(dt.date.today().year):      # normale = annees completes depuis 2016
            norm[int(k[5:])].append(v)
    normal = {m: round(sum(v) / len(v), 2) for m, v in norm.items() if len(v) >= 2}
    chaud = {k: v for k, v in ((old or {}).get('hot_days') or {}).items() if k < (min(mois) if mois else '9999')}
    for k, L in sorted(mois.items()):
        chaud[k] = [sum(1 for v in L if v > s) for s in SEUILS]
    return {'monthly': mm, 'normal': {str(m): v for m, v in sorted(normal.items())},
            'anomaly': {k: round(v - normal[int(k[5:])], 2) for k, v in mm.items() if int(k[5:]) in normal},
            'hot_days': {k: v for k, v in sorted(chaud.items()) if any(v)}, 'days': (old or {}).get('days') or len(jours), 'last_day': max(jours) if jours else None}


def climato(jours):
    """Normale journaliere (annees completes) par jour de l'annee (fenetre glissante de 15 jours), {doy: °C}."""
    par = defaultdict(list)
    for d, v in jours.items():
        if d[:4] < str(dt.date.today().year):
            par[min(365, dt.date.fromisoformat(d).timetuple().tm_yday)].append(v)
    out = {}
    for j in range(1, 366):
        L = [v for o in range(-7, 8) for v in par.get((j - 1 + o) % 365 + 1, [])]
        if len(L) >= 30:
            out[str(j)] = round(sum(L) / len(L), 2)
    return out


def alerte(recent, clim):
    """Ecart moyen des 7 derniers jours a la normale du jour ; alerte au-dela de ±1 °C ou si un jour depasse 16,5 °C."""
    if not recent or not clim:
        return None
    jours = sorted(recent)[-7:]
    ec = [recent[d] - clim[str(min(365, dt.date.fromisoformat(d).timetuple().tm_yday))] for d in jours
          if str(min(365, dt.date.fromisoformat(d).timetuple().tm_yday)) in clim]
    if len(ec) < 5:
        return None
    a7 = round(sum(ec) / len(ec), 2)
    chaud = sum(1 for d in jours if recent[d] > SEUILS[0])
    niveau = 'warm' if a7 >= 1 else 'cold' if a7 <= -1 else 'heat' if chaud else None
    return {'until': jours[-1], 'anom7': a7, 'hot7': chaud, 'level': niveau}


def main():
    hier = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    pts, erreurs = [], []
    complet = os.environ.get('SST_FULL') == '1'
    for b, pid, lab, la, lo in POINTS:
        try:
            old = next((p for p in ancien.get('points', []) if p.get('id') == pid and p.get('monthly') and p.get('clim') and p.get('cell')), None)
            jours = {}
            # OISST publie avec ~1-2 jours de retard (provisoire, remplace par le definitif apres ~2 semaines) : fin = dernier jour publie
            fin = None
            cell = old['cell'] if old else maille(la, lo)
            if not cell:
                raise RuntimeError('aucune maille de mer a moins de 1 degre')
            if old and not complet:
                # passage quotidien : on ne relit que les 3 derniers mois
                t = dt.date.today().replace(day=1)
                for _ in range(2):
                    t = (t - dt.timedelta(days=1)).replace(day=1)
                jours = journalier(cell[0], cell[1], t.isoformat(), fin)
            else:
                old = None
                for a0 in range(int(DEBUT[:4]), dt.date.today().year + 1, 4):     # historique complet depuis 2016, par blocs de 4 ans
                    d0, d1 = f'{a0}-01-01', (f'{a0 + 3}-12-31' if a0 + 3 < dt.date.today().year else None)
                    jours.update(journalier(cell[0], cell[1], d0, d1))
                    time.sleep(1)
            if not jours:
                raise RuntimeError('aucune donnee')
            r = resume(jours, old)
            r['clim'] = old['clim'] if old else climato(jours)
            r['recent'] = {d: round(v, 2) for d, v in sorted(jours.items())[-45:]}
            r['alert'] = alerte(r['recent'], r['clim'])
            pts.append({'basin': b, 'id': pid, 'label': lab, 'lat': la, 'lon': lo, 'cell': list(cell), **r})
            print(f'  {pid:14s} {r["days"]} jours, dernier mois {max(r["monthly"]) if r["monthly"] else "-"}', flush=True)
            if len(pts) % 4 == 0:
                # premier passage long : on ecrit au fur et a mesure (points deja lus + anciens)
                ecrire(pts + [p for p in ancien.get('points', []) if p.get('id') not in {q['id'] for q in pts}], erreurs)
        except Exception as e:  # noqa: BLE001
            erreurs.append(f'{pid}: {str(e)[:120]}')
            old = next((p for p in ancien.get('points', []) if p.get('id') == pid), None)
            if old:
                pts.append(old)          # on garde la serie precedente plutot qu'un trou
    ecrire(pts, erreurs)


def ecrire(pts, erreurs):
    if not pts:
        print('sea_temp : rien de lu, fichier inchange', erreurs)
        return
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'source': 'NOAA OISST v2.1 (daily optimum interpolation sea surface temperature, satellites + buoys + ships, 0.25° grid), via NOAA CoastWatch ERDDAP; public domain',
                    'url': 'https://www.ncei.noaa.gov/products/optimum-interpolation-sst', 'thresholds': list(SEUILS), 'normal': f'2016-{dt.date.today().year - 1}',
                    'note': 'Risk thresholds 16.5 / 17 / 18 °C from Canepa et al., Reviews in Aquaculture 2026 (Tasmania); growth optimum 12-16 °C.',
                    'basins': BASSINS, 'errors': erreurs,
                    'alerts': [{'id': p['id'], 'basin': p['basin'], 'label': p['label'], **p['alert']} for p in pts if (p.get('alert') or {}).get('level')]},
           'points': pts}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'data/sea_temp.json : {len(pts)} points, {len(erreurs)} erreurs')


if __name__ == '__main__':
    main()
