#!/usr/bin/env python3
"""
Veille algues nocives, trois sources gratuites :

  1. Norvege - bulletin de l'Institut de recherche marine (HI, algestatus.hi.no) : statut hebdomadaire et rapports
     d'episode, risque (lav / moderat / hoy) par zone de production.
  2. Chili - communiques de Sernapesca sur les mortalites (FAN, oxygene...) : flux RSS de la recherche du site.
  3. Chili - conditions de floraison (suivi en coulisse) : pluie, ensoleillement et vent (NASA POWER, domaine public) et
     temperature de la mer (data/sea_temp.json) aux points ou ont eclate les blooms de 2016 et 2021. Ces conditions ne sont
     publiees que si elles se confirment : secheresse + eau chaude + (soleil fort ou vent faible) tous les jours des 10
     derniers jours.

    python3 scripts/build_algae_watch.py      -> data/algae_watch.json
"""
import datetime as dt
import html
import io
import json
import os
import re
import statistics as S
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'algae_watch.json')
UA = {'User-Agent': 'Mozilla/5.0 (salmon-outlook algae watch)'}
HI = 'https://algestatus.hi.no'
SPECIES = ['Pseudochattonella', 'Chrysochromulina', 'Prymnesium', 'Karenia', 'Dictyocha', 'Chaetoceros', 'Alexandrium', 'Heterosigma',
           'Noctiluca', 'Phaeocystis', 'Dinophysis', 'Pseudo-nitzschia', 'Leptocylindrus', 'Skeletonema']
LEVEL = {'lav': 1, 'moderat': 2, 'høy': 3, 'hoy': 3}
LEVEL_EN = {0: 'none stated', 1: 'low', 2: 'moderate', 3: 'high'}


def get(url, timeout=60):
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(3 * (i + 1))
    raise RuntimeError(f'{url}: {last}')


def texte(h):
    h = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', h, flags=re.S)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h))).strip()


def corps(h):
    """Texte principal d'une page algestatus (entre le titre et le pied de page)."""
    t = texte(h)
    t = re.split(r'Nettstedkart|Kontakt Lars', t)[0]
    t = re.sub(r'^.*?Hendelsesrapportering Satellittinformasjon( Hjem)?', '', t)
    return t.strip()


def risques(t):
    """Niveau de risque par zone de production (PO) cite dans le texte, phrase par phrase ; niveau global = le plus haut."""
    po, glob = {}, 0
    for ph in re.split(r'(?<=[.!?])\s+', t):
        lv = [LEVEL[m] for m in re.findall(r'\b(lav|moderat|høy|hoy)e?\b', ph.lower()) if m in LEVEL]
        if not lv or 'risiko' not in ph.lower(): continue
        L = max(lv); glob = max(glob, L)
        zs = set()
        for a, b in re.findall(r'(?:PO|produksjonsområde(?:ne|t)?)\s*(\d{1,2})(?:\s*(?:til|-|–)\s*(\d{1,2}))?', ph, re.I):
            zs.update(range(int(a), int(b) + 1) if b else [int(a)])
        zs.update(int(x) for x in re.findall(r'PO\s?(\d{1,2})', ph))
        for z in zs:
            if 1 <= z <= 13: po[z] = max(po.get(z, 0), L)
    return glob, {str(k): v for k, v in sorted(po.items())}


def resume_en(t, glob, po):
    sp = [s for s in SPECIES if s.lower() in t.lower()]
    under = bool(re.search(r'under (fare)?grense', t.lower()))
    s = f'Risk {LEVEL_EN[glob]}'
    if po: s += ' — ' + ', '.join(f'PO{k} {LEVEL_EN[v]}' for k, v in po.items())
    if sp: s += '. Algae named: ' + ', '.join(sp)
    if under: s += '. Concentrations below harmful thresholds'
    return s + '.', sp


def hi_bulletin():
    out = {'source': 'Institute of Marine Research (HI), Algestatus', 'url': HI}
    h = get(HI + '/')
    wk = re.findall(r'href="(/ukestatus/[^"]+)"', h)
    if wk:
        u = HI + wk[0]; p = get(u); t = corps(p)
        title = re.search(r'Statusrapport uke (\d+),? (\d{4})', t)
        g, po = risques(t); en, sp = resume_en(t, g, po)
        out['weekly'] = {'url': u, 'week': int(title.group(1)) if title else None, 'year': int(title.group(2)) if title else None,
                         'level': g, 'level_en': LEVEL_EN[g], 'po': po, 'species': sp, 'summary_en': en, 'text_no': t[:1200]}
    # rapports d'episode (pendant un bloom, plusieurs par semaine)
    lst = get(HI + '/statusrapporter'); ev = []
    for path in dict.fromkeys(re.findall(r'href="(/statusrapporter/[a-z0-9-]+)"', lst)):
        try:
            p = get(HI + path); t = corps(p)
        except Exception:  # noqa: BLE001
            continue
        m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', texte(p))
        d = f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None
        g, po = risques(t); en, sp = resume_en(t, g, po)
        ttl = re.split(r' \| ', texte(re.search(r'<title>(.*?)</title>', p, re.S).group(1)))[0] if '<title>' in p else path
        ev.append({'url': HI + path, 'title_no': ttl, 'date': d, 'level': g, 'level_en': LEVEL_EN[g], 'po': po, 'species': sp, 'summary_en': en, 'text_no': t[:600]})
        time.sleep(.5)
    # la date est parfois absente de la page : on la tire du titre (« Statusrapport 29 mars, 2026 »)
    MO = {'januar': 1, 'februar': 2, 'mars': 3, 'april': 4, 'mai': 5, 'juni': 6, 'juli': 7, 'august': 8, 'september': 9, 'oktober': 10, 'november': 11, 'desember': 12}
    for e in ev:
        m = re.search(r'(\d{1,2})\.? (' + '|'.join(MO) + r'),? (\d{4})', e['title_no'].lower())
        if m: e['date'] = f'{m.group(3)}-{MO[m.group(2)]:02d}-{int(m.group(1)):02d}'
    ev.sort(key=lambda e: e['date'] or '', reverse=True)
    out['events'] = ev[:20]
    out['ongoing'] = not re.search(r'Ingen pågående oppblomstringer', texte(h).split('Ukentlig statusrapport')[0])
    return out


def sernapesca():
    """Communiques de Sernapesca sur les mortalites de saumons (FAN, oxygene, contingences)."""
    items = {}
    for q in ['mortalidad', 'FAN', 'floracion', 'contingencia']:
        try:
            x = get(f'https://www.sernapesca.cl/search/{q}/feed/rss2/')
            root = ET.fromstring(x.encode('utf-8'))
        except Exception as e:  # noqa: BLE001
            print('sernapesca', q, str(e)[:120]); continue
        for it in root.iter('item'):
            t = (it.findtext('title') or '').strip(); u = (it.findtext('link') or '').strip(); d = it.findtext('pubDate') or ''
            try: d = dt.datetime.strptime(d[:25].strip(), '%a, %d %b %Y %H:%M:%S').date().isoformat()
            except ValueError: d = ''
            ds = texte(it.findtext('description') or '')[:500]
            if not re.search(r'mortalidad|FAN|floraci|salm|contingencia|oxígeno|oxigeno', t + ' ' + ds, re.I): continue
            if not re.search(r'salm|centro|cultivo|acuicult|FAN|floraci', t + ' ' + ds, re.I): continue
            tn = re.findall(r'(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?)\s*(?:toneladas|ton\b|t\b)', t + ' ' + ds)
            reg = re.findall(r'Los Lagos|Aysén|Aysen|Magallanes|Biobío|Los Ríos|Ñuble|Valparaíso', t + ' ' + ds)
            items[u] = {'date': d, 'title': html.unescape(t), 'url': u, 'text': ds, 'tonnes': [float(v.replace('.', '').replace(' ', '').replace(',', '.')) for v in tn][:3],
                        'region': sorted(set(r.replace('Aysen', 'Aysén') for r in reg)), 'cause': 'algal bloom (FAN)' if re.search(r'FAN|floraci|alga', t + ds, re.I) else 'low oxygen' if re.search(r'ox[ií]geno', t + ds, re.I) else ''}
        time.sleep(1)
    L = sorted(items.values(), key=lambda x: x['date'], reverse=True)
    return {'source': 'Sernapesca press releases (search feed)', 'url': 'https://www.sernapesca.cl/?s=mortalidad', 'items': L[:40]}


# ------------------------------------------------------------------ conditions de floraison au Chili
PTS = [('reloncavi', 'Reloncaví Sound', -41.6, -72.6, 'cl_loslagos'), ('chiloe', 'Chiloé inner sea', -42.5, -73.1, 'cl_loslagos'),
       ('aysen', 'Aysén fjords', -45.4, -73.3, 'cl_aysen'), ('magallanes', 'Magallanes', -52.6, -72.6, 'cl_magallanes')]


def power(la, lo, d0, d1):
    u = ('https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,ALLSKY_SFC_SW_DWN,WS10M&community=AG'
         f'&longitude={lo}&latitude={la}&start={d0:%Y%m%d}&end={d1:%Y%m%d}&format=JSON')
    p = json.loads(get(u, timeout=180))['properties']['parameter']
    return {k: {f'{d[:4]}-{d[4:6]}-{d[6:]}': v for d, v in s.items() if v is not None and v > -900} for k, s in p.items()}


def fenetre(serie, fin, n, f):
    v = [serie.get((fin - dt.timedelta(days=i)).isoformat()) for i in range(n)]
    v = [x for x in v if x is not None]
    return f(v) if len(v) >= n * .8 else None


def conditions():
    st = json.load(io.open(os.path.join(ROOT, 'data', 'sea_temp.json'), encoding='utf-8')) if os.path.exists(os.path.join(ROOT, 'data', 'sea_temp.json')) else {}
    SP = {p['id']: p for p in st.get('points', [])}
    today = dt.date.today(); d0 = dt.date(2003, 1, 1)
    out = []
    for pid, lab, la, lo, sid in PTS:
        try:
            P = power(la, lo, d0, today)
        except Exception as e:  # noqa: BLE001
            print('POWER', pid, str(e)[:150]); continue
        R, SW, W = P.get('PRECTOTCORR', {}), P.get('ALLSKY_SFC_SW_DWN', {}), P.get('WS10M', {})
        last = min(max(R), max(SW), max(W)); D = dt.date.fromisoformat(last)
        sp = SP.get(sid, {}); rec = sp.get('recent') or {}; clim = sp.get('clim') or {}
        days = []
        for k in range(10):
            d = D - dt.timedelta(days=k)
            rain = fenetre(R, d, 60, sum); sun = fenetre(SW, d, 14, S.mean); wind = fenetre(W, d, 14, S.mean)
            nr, ns, nw = [], [], []
            for y in range(d.year - 22, d.year):
                try: dd = d.replace(year=y)
                except ValueError: dd = d.replace(year=y, day=28)
                a, b, c = fenetre(R, dd, 60, sum), fenetre(SW, dd, 14, S.mean), fenetre(W, dd, 14, S.mean)
                if a is not None: nr.append(a)
                if b is not None: ns.append(b)
                if c is not None: nw.append(c)
            # mer : derniere valeur journaliere disponible jusqu'a ce jour, contre la normale du jour de l'annee
            sst = sst_a = None
            for j in range(0, 6):
                x = (d - dt.timedelta(days=j)).isoformat()
                if x in rec: sst = rec[x]; doy = str(min(365, (d - dt.timedelta(days=j)).timetuple().tm_yday)); sst_a = round(sst - clim[doy], 2) if doy in clim else None; break
            r_rat = rain / S.median(nr) if rain is not None and nr and S.median(nr) > 0 else None
            s_rat = sun / S.median(ns) if sun is not None and ns else None
            w_rat = wind / S.median(nw) if wind is not None and nw else None
            f = {'dry': r_rat is not None and r_rat <= .6, 'warm': sst_a is not None and sst_a >= .5,
                 'sunny': s_rat is not None and s_rat >= 1.10, 'calm': w_rat is not None and w_rat <= .85}
            days.append({'date': d.isoformat(), 'rain60_mm': round(rain, 1) if rain is not None else None, 'rain_ratio': round(r_rat, 2) if r_rat else None,
                         'sun_ratio': round(s_rat, 2) if s_rat else None, 'wind_ratio': round(w_rat, 2) if w_rat else None, 'sst': sst, 'sst_anom': sst_a,
                         'factors': f, 'alert': f['dry'] and f['warm'] and (f['sunny'] or f['calm'])})
        conf = all(x['alert'] for x in days)
        out.append({'id': pid, 'label': lab, 'lat': la, 'lon': lo, 'last': last, 'now': days[0], 'alert_days_of_10': sum(x['alert'] for x in days), 'confirmed': conf})
        print(f'  {pid:10s} {last} pluie60 {days[0]["rain_ratio"]} soleil14 {days[0]["sun_ratio"]} vent14 {days[0]["wind_ratio"]} mer {days[0]["sst_anom"]} -> {sum(x["alert"] for x in days)}/10', flush=True)
        time.sleep(2)
    return {'source': 'NASA POWER (MERRA-2, CERES; public domain) for rain, sunshine and wind; NOAA OISST for the sea',
            'rule': 'Bloom-prone when, at the same point: rain over the last 60 days at most 60 % of normal (2003 onwards), sea at least +0.5 °C above normal, '
                    'and either sunshine over 14 days at least 10 % above normal or wind at least 15 % below normal. Published only if this holds on each of the last 10 days.',
            'points': out, 'published': any(p['confirmed'] for p in out)}


def main():
    old = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    res = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes')}, 'errors': []}
    for k, f in (('norway_hi', hi_bulletin), ('chile_sernapesca', sernapesca), ('chile_conditions', conditions)):
        try:
            res[k] = f()
        except Exception as e:  # noqa: BLE001
            res['errors'].append(f'{k}: {str(e)[:200]}'); print('ERREUR', k, e)
            if k in old: res[k] = old[k]
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(res, ensure_ascii=False, separators=(',', ':')))
    w = (res.get('norway_hi') or {}).get('weekly') or {}
    print(f"HI semaine {w.get('week')} : {w.get('summary_en')} ; {len((res.get('norway_hi') or {}).get('events', []))} rapports d'episode")
    print(f"Sernapesca : {len((res.get('chile_sernapesca') or {}).get('items', []))} communiques ; conditions Chili publiees : {(res.get('chile_conditions') or {}).get('published')}")


if __name__ == '__main__':
    main()
