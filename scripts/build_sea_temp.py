#!/usr/bin/env python3
"""
Temperature de la mer par bassin producteur de saumon, et jours de chaleur.

    python3 scripts/build_sea_temp.py        -> data/sea_temp.json   (gratuit : Open-Meteo Marine, sans cle)

Pour chaque bassin, quelques points en mer pres des fermes (un par grande region de production). Pour chaque point :
temperature de surface journaliere (moyenne des heures), puis
  - moyenne mensuelle et ecart a la moyenne 2016-2025 du meme mois ;
  - jours de chaleur par annee et mois : jours au-dessus de 16,5 / 17 / 18 °C (seuils de risque de mortalite cites par
    Canepa et al., Reviews in Aquaculture 2026, « Turning Up the Heat » ; optimum de croissance 12-16 °C, limite haute ~20 °C).
Le fichier est relu en entier a chaque passage (2016 a hier) : les series modelisees d'Open-Meteo peuvent etre revisees.
Norvege : la temperature declaree chaque semaine par les sites (BarentsWatch) reste la reference par zone dans le tableau de bord ;
les points Open-Meteo servent a comparer les bassins sur la meme base.
"""
import datetime as dt
import io
import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'sea_temp.json')
UA = {'User-Agent': 'Mozilla/5.0 (salmon-outlook sea temperature)'}
SEUILS = (16.5, 17.0, 18.0)
DEBUT = '2016-01-01'

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


def http(url, tries=3, timeout=120):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.status, r.read()
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f'{url[:120]} : {last}')


def journalier(la, lo, debut, fin):
    """Temperature de surface journaliere (moyenne des heures disponibles), {date: °C}."""
    q = {'latitude': la, 'longitude': lo, 'hourly': 'sea_surface_temperature', 'start_date': debut, 'end_date': fin, 'timezone': 'UTC'}
    st, raw = http('https://marine-api.open-meteo.com/v1/marine?' + urllib.parse.urlencode(q))
    if st != 200 or not raw:
        return {}
    h = (json.loads(raw).get('hourly') or {})
    j = defaultdict(list)
    for t, s in zip(h.get('time', []), h.get('sea_surface_temperature', [])):
        if s is not None:
            j[t[:10]].append(s)
    return {d: sum(v) / len(v) for d, v in j.items() if len(v) >= 12}


def resume(jours):
    """Moyennes mensuelles, normales 2016-2025 et jours de chaleur par mois."""
    mois = defaultdict(list)
    for d, v in jours.items():
        mois[d[:7]].append(v)
    mm = {k: round(sum(v) / len(v), 2) for k, v in sorted(mois.items()) if len(v) >= 20}
    norm = defaultdict(list)
    for k, v in mm.items():
        if '2016' <= k[:4] <= '2025':
            norm[int(k[5:])].append(v)
    normal = {m: round(sum(v) / len(v), 2) for m, v in norm.items() if len(v) >= 5}
    chaud = {}
    for k, L in sorted(mois.items()):
        chaud[k] = [sum(1 for v in L if v > s) for s in SEUILS]
    return {'monthly': mm, 'normal': {str(m): v for m, v in sorted(normal.items())},
            'anomaly': {k: round(v - normal[int(k[5:])], 2) for k, v in mm.items() if int(k[5:]) in normal},
            'hot_days': {k: v for k, v in chaud.items() if any(v)}, 'days': len(jours)}


def main():
    hier = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    pts, erreurs = [], []
    for b, pid, lab, la, lo in POINTS:
        try:
            jours = {}
            for a0 in range(int(DEBUT[:4]), dt.date.today().year + 1, 4):     # par blocs de 4 ans (reponses plus legeres)
                d0, d1 = f'{a0}-01-01', min(f'{a0 + 3}-12-31', hier)
                jours.update(journalier(la, lo, d0, d1))
            if not jours:
                raise RuntimeError('aucune donnee')
            r = resume(jours)
            pts.append({'basin': b, 'id': pid, 'label': lab, 'lat': la, 'lon': lo, **r})
            print(f'  {pid:14s} {r["days"]} jours, dernier mois {max(r["monthly"]) if r["monthly"] else "-"}')
        except Exception as e:  # noqa: BLE001
            erreurs.append(f'{pid}: {str(e)[:120]}')
            old = next((p for p in ancien.get('points', []) if p.get('id') == pid), None)
            if old:
                pts.append(old)          # on garde la serie precedente plutot qu'un trou
    if not pts:
        print('sea_temp : rien de lu, fichier inchange', erreurs)
        return
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'source': 'Open-Meteo Marine API (modelled sea surface temperature, daily mean of hourly values)',
                    'url': 'https://open-meteo.com/en/docs/marine-weather-api', 'thresholds': list(SEUILS), 'normal': '2016-2025',
                    'note': 'Risk thresholds 16.5 / 17 / 18 °C from Canepa et al., Reviews in Aquaculture 2026 (Tasmania); growth optimum 12-16 °C.',
                    'basins': BASSINS, 'errors': erreurs},
           'points': pts}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'data/sea_temp.json : {len(pts)} points, {len(erreurs)} erreurs')


if __name__ == '__main__':
    main()
