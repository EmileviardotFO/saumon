#!/usr/bin/env python3
"""
data/plants.json : abattoirs et ateliers de transformation du saumon, Norvege et Chili, avec leur position.

  Norvege : liste Mattilsynet des etablissements agrees (deja lue dans data/data.json -> establishments).
            Code FFPP-SA = abattoir de poissons d'elevage ; FFPP-P = transformation (filetage...) : on garde les
            abattoirs, et les ateliers de transformation des groupes salmonicoles connus. Adresse geocodee par
            Kartverket (ws.geonorge.no), a defaut le centre du code postal.
  Chili   : "Listado de Plantas Autorizadas para Faenar y/o Procesar Salmonidos" de Sernapesca (PDF, mis a jour
            chaque mois) : code, nom, commune, societes d'elevage servies, abattage oui/non. Commune geocodee
            par OpenStreetMap (Nominatim), une requete par seconde, resultats gardes en cache.

    python3 scripts/build_plants.py
"""
import io
import json
import os
import re
import time
import urllib.parse

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'plants.json')
CACHE = os.path.join(ROOT, 'data', 'plants_geo.json')
H = {'User-Agent': 'salmon-dashboard/1.0 (market intelligence dashboard; github.com/EmileviardotFO/saumon)'}
SERNA_PAGE = 'https://www.sernapesca.cl/informacion-utilidad/listados-y-registros/'
SERNA_FALLBACK = 'https://www.sernapesca.cl/app/uploads/2026/11/listado_de_plantas_autorizadas_salmonidos_v20261102_.pdf'

# groupes norvegiens : motif dans le nom de l'etablissement -> nom du groupe
NO_GROUPS = [
    (r'mowi|marine harvest', 'Mowi'), (r'ler[øo]y|sj[øo]troll|slakteriet brekke', 'Lerøy'), (r'salmar|kverva|refsnes', 'SalMar'),
    (r'cermaq', 'Cermaq'), (r'grieg', 'Grieg Seafood'), (r'nova sea', 'Nova Sea'), (r'nordlaks', 'Nordlaks'),
    (r'sinkaberg', 'Sinkaberg-Hansen'), (r'eide', 'Eide Fjordbruk'), (r'seashore|bremnes', 'Bremnes Seashore'),
    (r'hofseth', 'Hofseth'), (r'kr[åa]k[øo]y', 'Kråkøy Slakteri'), (r'm[åa]s[øo]val', 'Måsøval'), (r'hav ?line', 'Hav Line'),
    (r'vikenco', 'Vikenco'), (r'arn[øo]y', 'Arnøy Laks'), (r'alsv[åa]g', 'Alsvåg Lakseslakteri'), (r'lingalaks', 'Lingalaks'),
    (r'osland', 'Osland'), (r'tombre', 'Tombre'), (r'alsaker', 'Alsaker'), (r'wenberg', 'Wenberg'), (r'kvar[øo]y', 'Kvarøy'),
    (r'ellingsen', 'Ellingsen Seafood'), (r'nergård|nergard', 'Nergård'), (r'nekton', 'Nekton'), (r'engesund', 'Engesund'),
    (r'firda', 'Firda Seafood'), (r'fjordlaks', 'Fjordlaks'), (r'trolltunga', 'Trolltunga Arctic Trout'), (r'bj[øo]r[øo]ya', 'Bjørøya'),
    (r'steinvik', 'Steinvik'), (r'gigante', 'Gigante'), (r'kleiva', 'Kleiva'), (r'fl[øo]ya', 'Fløya'), (r'midt.?norsk', 'Midt-Norsk Havbruk'),
    (r'salaks', 'Salaks'), (r'br[øo]drene hjønnevåg|hjønnevåg', 'Hjønnevåg'), (r'lerøy', 'Lerøy'),
]
SALMON_PROC = re.compile(r'(?i)mowi|ler[øo]y seafood industri|ler[øo]y fossen|ler[øo]y bulandet|salmar|cermaq|grieg|nova sea|nordlaks|'
                         r'sinkaberg|seashore|hofseth|hav ?line|vikenco|kvar[øo]y|br[øo]drene hjønnevåg|lakse|laks\b|trout|salmon|slakteri')


def group_no(name):
    for rx, g in NO_GROUPS:
        if re.search(rx, name, re.I):
            return g
    return re.sub(r'(?i)\s+(as|asa|sa)\b.*$', '', name).strip() or name


def load(p, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default


def geonorge(addr, postcode, city):
    """lat, lon de l'adresse ; a defaut le premier point du code postal"""
    for q in ({'sok': addr, 'postnummer': postcode}, {'sok': f'{addr} {city}'}, {'postnummer': postcode}):
        if not all(q.values()):
            continue
        try:
            r = requests.get('https://ws.geonorge.no/adresser/v1/sok', params=dict(q, treffPerSide=1, utkoordsys=4258), headers=H, timeout=30)
            a = (r.json().get('adresser') or [None])[0]
            if a and a.get('representasjonspunkt'):
                p = a['representasjonspunkt']
                return round(p['lat'], 5), round(p['lon'], 5), ('address' if 'sok' in q else 'postcode')
        except Exception:
            pass
    return None


def nominatim(q):
    time.sleep(1.1)
    try:
        r = requests.get('https://nominatim.openstreetmap.org/search', params={'q': q, 'format': 'json', 'limit': 1, 'countrycodes': 'cl'}, headers=H, timeout=30)
        j = r.json()
        if j:
            return round(float(j[0]['lat']), 5), round(float(j[0]['lon']), 5), 'town'
    except Exception:
        pass
    return None


def norway(cache):
    d = load(os.path.join(ROOT, 'data', 'data.json'), {})
    E = (d.get('establishments') or {}).get('rows') or []
    out = []
    for appr, name, orgno, addr, pc, city, codes in E:
        slaughter = 'FFPP-SA' in codes
        proc = 'FFPP-P' in codes
        if not slaughter and not (proc and SALMON_PROC.search(name)):
            continue
        key = f'NO|{addr}|{pc}|{city}'
        if key not in cache:
            g = geonorge(addr, pc, city)
            cache[key] = list(g) if g else None
        g = cache.get(key)
        out.append({'id': appr, 'name': name, 'group': group_no(name), 'orgno': orgno, 'address': addr, 'postcode': pc, 'city': city,
                    'slaughter': slaughter, 'processing': proc, 'codes': codes,
                    'lat': g[0] if g else None, 'lon': g[1] if g else None, 'geo': g[2] if g else None})
    print(f'  Norvege : {len(out)} etablissements ({sum(x["slaughter"] for x in out)} abattoirs), {sum(1 for x in out if x["lat"])} geocodes')
    return out


def serna_url():
    try:
        t = requests.get(SERNA_PAGE, headers=H, timeout=60).text
        m = re.findall(r'href="([^"]*listado_de_plantas_autorizadas_salmonidos[^"]*\.pdf)"', t, re.I)
        if m:
            return urllib.parse.urljoin(SERNA_PAGE, m[0])
    except Exception:
        pass
    return SERNA_FALLBACK


def chile(cache):
    import pdfplumber
    url = serna_url()
    r = requests.get(url, headers=H, timeout=120)
    r.raise_for_status()
    rows, region = [], None
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        title = (pdf.pages[0].extract_text() or '').split('\n')
        edition = next((l.strip() for l in title[:3] if re.search(r'\b20\d\d\b', l)), '')
        for p in pdf.pages:
            for tb in p.extract_tables() or []:
                for c in tb:
                    c = [re.sub(r'\s+', ' ', str(x or '')).strip() for x in c]
                    if len(c) < 6 or c[0].lower().startswith('regi') or not (c[1] or c[2]):
                        continue
                    if c[0]:
                        region = c[0]
                    rows.append({'region': region, 'code': c[1], 'plant': c[2], 'town': c[3], 'farmers': c[4],
                                 'slaughter': c[5].lower().startswith('s')})
    RG = {'Punta Arenas': 'Magallanes', 'Aysen': 'Aysén'}
    seen = {}
    for x in rows:
        x['region'] = RG.get(x['region'], x['region'])
        key = f'CL|{x["town"]}|{x["region"]}'
        if key not in cache:
            g = nominatim(f'{x["town"]}, {x["region"]}, Chile') or nominatim(f'{x["town"]}, Chile')
            cache[key] = list(g) if g else None
        g = cache.get(key)
        if g:
            n = seen.get(key, 0); seen[key] = n + 1
            ang = n * 2.4                                   # plusieurs plantes dans la meme commune : en spirale autour du centre
            rad = 0.012 * (n ** 0.5)
            x['lat'], x['lon'] = round(g[0] + rad * __import__('math').sin(ang), 5), round(g[1] + rad * 1.4 * __import__('math').cos(ang), 5)
        else:
            x['lat'] = x['lon'] = None
    # positions exactes relevees a la main (registre RETC du ministere de l'environnement) : data/plants_cl_exact.json
    EX = load(os.path.join(ROOT, 'data', 'plants_cl_exact.json'), {}).get('plants', {})
    for x in rows:
        e = EX.get(x['code']) or EX.get(f"{x['code']}|{x['plant']}")
        x['geo'] = 'town'
        if e:
            x['lat'], x['lon'], x['address'], x['site'], x['geo'] = e[0], e[1], e[2], e[3], 'exact'
    print(f'  Chili : {len(rows)} plantes ({sum(x["slaughter"] for x in rows)} avec abattage), {sum(1 for x in rows if x["lat"])} geocodees')
    return rows, url, edition


def main():
    cache = load(CACHE, {})
    old = load(OUT, {})
    out = {'meta': {}}
    try:
        out['no'] = norway(cache)
        out['meta']['no_source'] = 'Mattilsynet, approved fishery establishments (FFPP-SA = farmed-fish slaughterhouse, FFPP-P = processing)'
    except Exception as e:  # noqa: BLE001
        print('  ERREUR Norvege :', e); out['no'] = old.get('no', [])
    try:
        out['cl'], url, ed = chile(cache)
        out['meta'].update({'cl_source': 'Sernapesca, Listado de Plantas Autorizadas para Faenar y/o Procesar Salmónidos', 'cl_url': url, 'cl_edition': ed})
    except Exception as e:  # noqa: BLE001
        print('  ERREUR Chili :', e); out['cl'] = old.get('cl', []); out['meta'].update({k: v for k, v in (old.get('meta') or {}).items() if k.startswith('cl_')})
    out['meta']['built'] = time.strftime('%Y-%m-%d')
    json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('ecrit', OUT)


if __name__ == '__main__':
    main()
