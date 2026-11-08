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
import re
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


PSL = 'https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.oisst.v2.highres/sst.day.mean.{y}.nc'
_LONG = {}


def psl_jours(y):
    """Nombre de jours publies dans le fichier annuel OISST de NOAA PSL (l'annee en cours grandit chaque jour)."""
    if y not in _LONG:
        st, raw = http(PSL.format(y=y) + '.dds')
        m = re.search(r'sst\[time = (\d+)\]', raw.decode('utf-8', 'replace'))
        _LONG[y] = int(m.group(1)) if m else 0
    return _LONG[y]


def psl(la, lo, y, i0=0, i1=None):
    """Temperature journaliere OISST a la maille (la, lo) pour l'annee y, par OPeNDAP (NOAA PSL), {date: °C}."""
    n = psl_jours(y)
    if not n:
        return {}
    i1 = n - 1 if i1 is None else min(i1, n - 1)
    if i0 > i1:
        return {}
    ia, io_ = round((la + 89.875) / .25), round(((lo % 360) - .125) / .25)
    st, raw = http(PSL.format(y=y) + f'.ascii?sst[{i0}:1:{i1}][{ia}][{io_}]')
    out, d0 = {}, dt.date(y, 1, 1)
    for ligne in raw.decode('utf-8', 'replace').splitlines():
        m = re.match(r'^\[(\d+)\](?:\[\d+\])*,\s*(\S+)', ligne.strip())
        if m:
            v = float(m.group(2))
            if -5 < v < 40:                                   # valeur de remplissage (terre) : -9.97e36
                out[(d0 + dt.timedelta(days=i0 + int(m.group(1)))).isoformat()] = v
    return out


def oisst(la, lo, debut, fin):
    """Temperature de surface journaliere NOAA OISST v2.1 a la maille (la, lo), {date: °C} (vide si maille terrestre).
    Source 1 : NOAA PSL (OPeNDAP, fichiers annuels) ; source 2 : NOAA CoastWatch ERDDAP (qui met parfois sur liste noire les
    adresses des serveurs GitHub partages)."""
    t0 = time.time()
    try:
        out = {}
        if debut == 'probe':
            y = dt.date.today().year
            n = psl_jours(y) or psl_jours(y - 1)
            if not psl_jours(y): y -= 1
            out = psl(la, lo, y, max(0, n - 20), n - 1)
        else:
            y0, y1 = int(debut[:4]), int(fin[:4]) if fin else dt.date.today().year
            for y in range(y0, y1 + 1):
                i0 = (dt.date.fromisoformat(debut) - dt.date(y, 1, 1)).days if y == y0 else 0
                i1 = (dt.date.fromisoformat(fin) - dt.date(y, 1, 1)).days if fin and y == y1 else None
                out.update(psl(la, lo, y, max(0, i0), i1))
                time.sleep(.3)
        print(f'    PSL {la},{lo} {debut}..{fin} -> {len(out)} jours, {time.time() - t0:.1f} s', flush=True)
        return out
    except Exception as e:  # noqa: BLE001
        print(f'    PSL indisponible ({str(e)[:100]}), essai ERDDAP', flush=True)
    t1 = 'last' if fin is None else f'{fin}T12:00:00Z'
    tq = '[last-20:1:last]' if debut == 'probe' else f'[({debut}T12:00:00Z):1:({t1})]'
    q = f'?sst{tq}[(0.0)][({la})][({lo})]'
    try:
        st, raw = http(ERDDAP + urllib.parse.quote(q, safe='?[]():,'))
    except RuntimeError as e:
        if 'HTTP Error 404' in str(e) or 'HTTP Error 400' in str(e):
            return {}
        raise
    out = {}
    for ligne in raw.decode('utf-8', 'replace').splitlines()[2:]:
        c = ligne.split(',')
        if len(c) >= 5 and c[4] not in ('', 'NaN'):
            out[c[0][:10]] = float(c[4])
    print(f'    ERDDAP {la},{lo} {debut}..{fin} -> {len(out)} jours, {time.time() - t0:.1f} s', flush=True)
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


import threading
VERROU = threading.Lock()
NCEI = 'https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr/{ym}/'


def ncei_fichiers(d0, d1):
    """Fichiers quotidiens OISST (NCEI) entre d0 et d1 : {date: url}, version definitive sinon provisoire (2 dernieres semaines)."""
    out = {}
    ms = sorted({(d0 + dt.timedelta(days=i)).strftime('%Y%m') for i in range((d1 - d0).days + 1)})
    for ym in ms:
        st, raw = http(NCEI.format(ym=ym))
        for nom in set(re.findall(r'oisst-avhrr-v02r01\.(\d{8})(_preliminary)?\.nc', raw.decode('utf-8', 'replace'))):
            d = dt.date(int(nom[0][:4]), int(nom[0][4:6]), int(nom[0][6:]))
            if d0 <= d <= d1 and (d.isoformat() not in out or not nom[1]):
                out[d.isoformat()] = NCEI.format(ym=ym) + f'oisst-avhrr-v02r01.{nom[0]}{nom[1]}.nc'
    return out


def ncei_lire(urls, mailles):
    """Telecharge les fichiers quotidiens en parallele et lit la temperature des mailles voulues : {date: {(ia, io): °C}}."""
    import concurrent.futures as cf
    import netCDF4                                               # pip install netCDF4 numpy
    import numpy as np
    def un(item):
        d, u = item
        for k in range(3):
            try:
                st, raw = http(u, tries=2, timeout=120)
                with VERROU:                                     # la bibliotheque HDF5 n'accepte qu'un fil a la fois (sinon plantage)
                    with netCDF4.Dataset(f'm{d}', memory=raw) as nc:
                        v = np.ma.filled(nc.variables['sst'][0, 0, :, :].astype(float), np.nan)
                return d, {m: (None if np.isnan(v[m]) else round(float(v[m]), 2)) for m in mailles}
            except Exception as e:  # noqa: BLE001
                err = e; time.sleep(3)
        print(f'    {d} : {str(err)[:100]}', flush=True)
        return d, None
    out = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for i, (d, vals) in enumerate(ex.map(un, sorted(urls.items()))):
            if vals: out[d] = vals
            if i % 200 == 0: print(f'    {i}/{len(urls)} fichiers lus', flush=True)
    return out


def mailles_mer(premier):
    """Pour chaque point, la maille de mer OISST la plus proche (a moins de 1 degre), a partir d'un fichier quotidien complet."""
    import netCDF4
    import numpy as np
    st, raw = http(premier, timeout=120)
    with VERROU, netCDF4.Dataset('premier', memory=raw) as nc:
        v = np.ma.filled(nc.variables['sst'][0, 0, :, :].astype(float), np.nan)
    res = {}
    for b, pid, lab, la, lo in POINTS:
        best = None
        for a_, b_ in DECALAGES:
            ia, io_ = round((la + a_ + 89.875) / .25), round((((lo + b_) % 360) - .125) / .25)
            if not np.isnan(v[ia, io_]):
                best = (ia, io_); break
        res[pid] = best
    return res


def main():
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    complet = os.environ.get('SST_FULL') == '1'
    olds = {p['id']: p for p in ancien.get('points', []) if p.get('monthly') and p.get('clim') and p.get('cell') and p.get('src') == 'ncei'}
    fin = dt.date.today() - dt.timedelta(days=1)
    plein = complet or len(olds) < 0.8 * len(POINTS)     # un point sans maille de mer ne doit pas relancer tout l'historique chaque jour
    if plein:
        d0 = dt.date.fromisoformat(DEBUT)
    else:                                   # passage quotidien : les 3 derniers mois (provisoire -> definitif apres ~2 semaines)
        d0 = dt.date.today().replace(day=1)
        for _ in range(2):
            d0 = (d0 - dt.timedelta(days=1)).replace(day=1)
    t0 = time.time()
    urls = ncei_fichiers(d0, fin)
    print(f'NCEI : {len(urls)} fichiers quotidiens de {d0} a {fin} ({time.time() - t0:.0f} s)', flush=True)
    if not urls:
        print('sea_temp : NCEI ne repond pas, fichier inchange'); return
    cells = {pid: tuple(p['cell_idx']) for pid, p in olds.items()} if not plein else mailles_mer(urls[max(urls)])
    mailles = sorted({c for c in cells.values() if c})
    lu = ncei_lire(urls, mailles)
    print(f'NCEI : {len(lu)} jours lus en {time.time() - t0:.0f} s', flush=True)
    pts, erreurs = [], []
    for b, pid, lab, la, lo in POINTS:
        c = cells.get(pid)
        old = None if plein else olds.get(pid)
        jours = {d: v[c] for d, v in lu.items() if c and v.get(c) is not None and -5 < v[c] < 40}
        if not jours:
            erreurs.append(f'{pid}: aucune maille de mer a moins de 1 degre' if not c else f'{pid}: aucune donnee')
            if pid in olds: pts.append(olds[pid])
            continue
        r = resume(jours, old)
        r['clim'] = old['clim'] if old else climato(jours)
        recent = {**((old or {}).get('recent') or {}), **{d: round(v, 2) for d, v in jours.items()}}
        r['recent'] = dict(sorted(recent.items())[-45:])
        r['alert'] = alerte(r['recent'], r['clim'])
        pts.append({'basin': b, 'id': pid, 'label': lab, 'lat': la, 'lon': lo, 'cell': [round(c[0] * .25 - 89.875, 3), round(c[1] * .25 + .125 - (360 if c[1] * .25 + .125 > 180 else 0), 3)],
                    'cell_idx': list(c), 'src': 'ncei', **r})
        print(f'  {pid:14s} {len(jours)} jours, dernier mois {max(r["monthly"]) if r["monthly"] else "-"}', flush=True)
    ENSO_CACHE['v'] = enso(ancien.get('enso')); ENSO_CACHE['p'] = presse(ancien.get('press'))
    print('El Niño :', (ENSO_CACHE['v'] or {}).get('status'), '| presse climat :', len(ENSO_CACHE['p'] or []), 'titres', flush=True)
    ecrire(pts, erreurs)


ENSO_CACHE = {}


def ecrire(pts, erreurs):
    if not pts:
        print('sea_temp : rien de lu, fichier inchange', erreurs)
        return
    src = {'oisst' if p.get('src') == 'ncei' else 'open-meteo' for p in pts}
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'source': 'NOAA OISST v2.1 (daily optimum interpolation sea surface temperature, satellites + buoys + ships, 0.25° grid), via NOAA NCEI daily files; public domain' if src == {'oisst'} else 'Open-Meteo Marine API (modelled sea surface temperature), being replaced by NOAA OISST v2.1',
                    'url': 'https://www.ncei.noaa.gov/products/optimum-interpolation-sst', 'thresholds': list(SEUILS), 'normal': f'2016-{dt.date.today().year - 1}' if src == {'oisst'} else f'2023-{dt.date.today().year - 1}',
                    'note': 'Risk thresholds 16.5 / 17 / 18 °C from Canepa et al., Reviews in Aquaculture 2026 (Tasmania); growth optimum 12-16 °C.',
                    'basins': BASSINS, 'errors': erreurs,
                    'alerts': [{'id': p['id'], 'basin': p['basin'], 'label': p['label'], **p['alert']} for p in pts if (p.get('alert') or {}).get('level')]},
           'points': pts}
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    out['enso'] = ENSO_CACHE.get('v') if ENSO_CACHE.get('v') is not None else ancien.get('enso')
    out['press'] = ENSO_CACHE.get('p') if ENSO_CACHE.get('p') is not None else ancien.get('press')
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f'data/sea_temp.json : {len(pts)} points, {len(erreurs)} erreurs')


# ---------------- El Niño (NOAA Climate Prediction Center) et presse climat ----------------
CPC = 'https://www.cpc.ncep.noaa.gov'


def enso(ancien):
    """Indice Niño 3.4 hebdomadaire (ecart a la normale 1991-2020), ONI trimestriel et statut officiel du systeme d'alerte ENSO.
    Donnees du gouvernement americain, domaine public. En cas d'echec, on garde la version precedente."""
    out = dict(ancien or {})
    try:
        st, raw = http(CPC + '/data/indices/wksst9120.for', timeout=60)
        wk = []
        for ligne in raw.decode('utf-8', 'replace').splitlines():
            m = re.match(r'\s*(\d{2})([A-Z]{3})(\d{4})', ligne)
            if not m: continue
            v = re.findall(r'-?\d+\.\d', ligne[m.end():])                  # Nino1+2, 3, 3.4, 4 : temperature puis ecart (colonnes parfois collees)
            if len(v) >= 6:
                d = dt.datetime.strptime(m.group(1) + m.group(2) + m.group(3), '%d%b%Y').date()
                wk.append([d.isoformat(), float(v[4]), float(v[5])])
        if wk: out['weekly_nino34'] = wk[-104:]
    except Exception as e:  # noqa: BLE001
        print('  ENSO hebdo :', str(e)[:120])
    try:
        st, raw = http(CPC + '/data/indices/oni.ascii.txt', timeout=60)
        oni = []
        for ligne in raw.decode('utf-8', 'replace').splitlines()[1:]:
            c = ligne.split()
            if len(c) == 4: oni.append([c[0], int(c[1]), float(c[3])])
        if oni: out['oni'] = oni[-36:]
    except Exception as e:  # noqa: BLE001
        print('  ONI :', str(e)[:120])
    try:
        st, raw = http(CPC + '/products/analysis_monitoring/enso_advisory/ensodisc.shtml', timeout=60)
        import html as H
        t = H.unescape(re.sub(r'<[^>]+>', ' ', raw.decode('utf-8', 'replace'))).replace('\xa0', ' '); t = re.sub(r'\s+', ' ', t)
        m = re.search(r'ENSO Alert System Status:\s*(.{3,80}?)\s{1,3}(?:Synopsis|Synopsis:)', t)
        sy = re.search(r'Synopsis:\s*(.{20,400}?\.)\s', t)
        dd = re.search(r'issued by CLIMATE PREDICTION CENTER.{0,120}?(\d{1,2} [A-Z][a-z]+ \d{4})', t)
        if m: out['status'] = m.group(1).strip()
        if sy: out['synopsis'] = sy.group(1).strip()
        if dd: out['issued'] = dd.group(1)
        out['url'] = CPC + '/products/analysis_monitoring/enso_advisory/ensodisc.shtml'
    except Exception as e:  # noqa: BLE001
        print('  ENSO statut :', str(e)[:120])
    return out


PRESSE_Q = [   # titres seulement (Google News), gardes s'ils parlent de temperature de la mer ET d'elevage de salmonides, ou d'El Niño
    ('"El Niño" (salmon OR salmón OR aquaculture OR acuicultura)', 'en', 'US', 'US:en'),
    ('"El Niño" (salmonicultura OR salmón OR "floraciones de algas" OR FAN) Chile', 'es-419', 'CL', 'CL:es-419'),
    ('("marine heatwave" OR "sea temperature" OR "water temperature") salmon farm', 'en', 'GB', 'GB:en'),
    ('(sjøtemperatur OR "marin hetebølge" OR "marin kuldebølge" OR havtemperatur) (laks OR oppdrett OR havbruk)', 'no', 'NO', 'NO:no'),
    ('("temperatura del mar" OR "ola de calor marina") (salmón OR salmonicultura)', 'es-419', 'CL', 'CL:es-419'),
    ('("marine heatwave" OR "water temperature") (Tasmania OR Macquarie) salmon', 'en', 'AU', 'AU:en'),
]
CLIMAT = re.compile(r'el ni[ñn]o|la ni[ñn]a|heatwave|hetebølge|kuldebølge|temperat|ola de calor|warm(ing|er) (water|sea|ocean)|sjøtemp|havtemp|cold (water|spell)|algal bloom|floraci|\bFAN\b|\bENSO\b', re.I)
MER = re.compile(r'pesca|fish|seafood|marisc|anchov|harina|sardin|ocean|oc[eé]ano|\bmar\b|sea\b|chile|aysén|los lagos', re.I)
ELEVAGE = re.compile(r'salm|laks|oppdrett|havbruk|aquacult|acuicult|fish farm|fiskeoppdrett|trucha|trout', re.I)
BASSIN_RX = [('NO', r'norw|norg|norsk|noreg'), ('CL', r'chile|chilen|ays[eé]n|los lagos|magallanes|chilo[eé]'), ('GB', r'scotl|escoc|skott'), ('FO', r'faroe|føroy|færø'),
             ('IS', r'iceland|island'), ('CA', r'canad|british columbia|newfoundland|new brunswick'), ('AU', r'tasmania|australia|macquarie'), ('IE', r'ireland|irlan')]


def presse(ancien):
    """Titres de presse sur la temperature de la mer, les vagues de chaleur marines et El Niño en lien avec l'elevage : 90 derniers jours."""
    items = {i['u']: i for i in (ancien or []) if i.get('u')}
    for q, hl, gl, ceid in PRESSE_Q:
        try:
            st, raw = http('https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q + ' when:30d', 'hl': hl, 'gl': gl, 'ceid': ceid}), timeout=40)
            for it in re.findall(r'<item>(.*?)</item>', raw.decode('utf-8', 'replace'), re.S):
                t = re.search(r'<title>(.*?)</title>', it, re.S); u = re.search(r'<link>(.*?)</link>', it, re.S); d = re.search(r'<pubDate>(.*?)</pubDate>', it, re.S); sname = re.search(r'<source[^>]*>(.*?)</source>', it, re.S)
                if not (t and u and d): continue
                titre = re.sub(r'<!\[CDATA\[|\]\]>', '', t.group(1)).replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'").strip()
                if not CLIMAT.search(titre): continue
                try: dd = dt.datetime.strptime(d.group(1).strip()[:25], '%a, %d %b %Y %H:%M:%S').date().isoformat()
                except ValueError: continue
                b = next((k for k, r in BASSIN_RX if re.search(r, titre, re.I)), 'ALL')
                items[u.group(1).strip()] = {'d': dd, 't': titre, 'src': (sname.group(1).strip() if sname else ''), 'u': u.group(1).strip(), 'b': b,
                                             'enso': bool(re.search(r'el ni[ñn]o|la ni[ñn]a|enso', titre, re.I))}
        except Exception as e:  # noqa: BLE001
            print('  presse :', q[:40], str(e)[:80])
        time.sleep(1)
    lim = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    SAUMON = re.compile(r'salm|laks|trucha|trout|ørret|anchov|harina de pescado|fishmeal', re.I)
    ok = lambda t: CLIMAT.search(t) and not re.search(r'facebook|instagram|youtube', t, re.I) and (SAUMON.search(t) or (any(re.search(r, t, re.I) for _, r in BASSIN_RX) and (ELEVAGE.search(t) or MER.search(t))))
    return sorted([i for i in items.values() if i['d'] >= lim and ok(i['t'])], key=lambda i: i['d'], reverse=True)[:60]


if __name__ == '__main__':
    main()
