#!/usr/bin/env python3
"""
Importations mondiales de saumon par pays importateur, chaque mois, d'apres UN Comtrade (declarations
des pays importateurs), avec le detail par grande origine, et alertes sur les variations importantes.

    python3 scripts/update_world_imports.py              # met a jour data/world_imports.json
    python3 scripts/update_world_imports.py --depuis 2022

Necessite une cle Comtrade gratuite (secret COMTRADE_KEY) : l'API publique sans cle plafonne a 500 lignes
par appel, trop peu pour tous les pays. Sans cle, le script s'arrete proprement et le signale.

Ecrit aussi data/world_imports_new_alerts.md : les alertes nouvelles depuis le dernier passage, que le
workflow publie en ticket GitHub (GitHub envoie alors un courriel de notification).
"""
import argparse
import collections
import datetime as dt
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'world_imports.json')
NEW = os.path.join(ROOT, 'data', 'world_imports_new_alerts.md')
API = 'https://comtradeapi.un.org/data/v1/get/C/M/HS'
CODES = {'030214': 'Fresh whole', '030441': 'Fresh fillets', '030313': 'Frozen whole', '030481': 'Frozen fillets',
         '030541': 'Smoked', '030311': 'Sockeye, frozen', '030312': 'Other Pacific salmon, frozen', '030213': 'Pacific salmon, fresh',
         # co-produits : chutes et morceaux de saumon (propre au saumon), puis codes communs a tous les poissons (signales comme tels)
         '030452': 'Fresh trimmings & pieces (salmonids)', '030399': 'Frozen heads, tails, fins & offal (all fish)'}
COPRODUITS = ['030452', '030399']
GENERIQUES = ['030399']
ORIGINES = {578: 'NO', 152: 'CL', 234: 'FO', 826: 'GB', 352: 'IS', 124: 'CA', 36: 'AU', 842: 'US', 643: 'RU', 156: 'CN'}
SEUIL_PCT, SEUIL_T = 30, 300          # alerte : variation de 30 % ou plus sur 3 mois, sur au moins 300 t
SEUIL_PART = 15                       # alerte : part d'une origine qui bouge de 15 points ou plus


def appel(cle, code, periodes, partenaires):
    q = {'cmdCode': code, 'flowCode': 'M', 'period': ','.join(periodes),
         'motCode': 0, 'customsCode': 'C00', 'partner2Code': 0, 'includeDesc': 'true'}
    if partenaires: q['partnerCode'] = partenaires
    url = API + '?' + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={'Ocp-Apim-Subscription-Key': cle, 'User-Agent': 'suivi-salmonicole/1.0'})
    for essai in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=120).read().decode('utf-8')).get('data') or []
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and essai < 3: time.sleep(15 * (essai + 1)); continue
            raise
    return []


def lignes(data):
    out = {}
    for r in data:
        rep = r.get('reporterISO') or str(r.get('reporterCode'))
        p = int(r.get('partnerCode') or 0)
        part = 'W' if p == 0 else ORIGINES.get(p, r.get('partnerISO') or str(p))
        if rep in ('W00', 'WLD') or (r.get('motCode') not in (None, 0)) or (r.get('partner2Code') not in (None, 0)): continue
        k = (int(r['period']), rep, str(r['cmdCode']), part)
        x = out.setdefault(k, [0.0, 0.0]); x[0] += float(r.get('netWgt') or 0); x[1] += float(r.get('cifvalue') or r.get('primaryValue') or 0)
    return [[k[0], k[1], k[2], k[3], round(v[0]), round(v[1])] for k, v in out.items() if v[0] or v[1]]


def moins(ym, n):
    a, m = divmod(ym, 100); i = a * 12 + m - 1 - n
    return (i // 12) * 100 + i % 12 + 1


def alertes(rows, noms):
    """Par pays importateur (total saumon, poids) : 3 derniers mois declares contre les memes mois un an plus tot ;
    et parts des grandes origines sur ces 3 mois contre un an plus tot."""
    tot, orig = collections.defaultdict(float), collections.defaultdict(float)
    dernier = collections.defaultdict(int)
    for ym, rep, hs, part, kg, usd in rows:
        if hs in COPRODUITS: continue
        if part == 'W': tot[(rep, ym)] += kg; dernier[rep] = max(dernier[rep], ym)
        else: orig[(rep, ym, part)] += kg
    out = []
    for rep, L in dernier.items():
        m3 = [moins(L, i) for i in range(3)]; p3 = [moins(x, 12) for x in m3]
        a, b = sum(tot[(rep, x)] for x in m3) / 1000, sum(tot[(rep, x)] for x in p3) / 1000
        if b and max(a, b) >= SEUIL_T and abs(100 * (a / b - 1)) >= SEUIL_PCT:
            out.append({'id': f'{rep}-{L}-vol', 'rep': rep, 'name': noms.get(rep, rep), 'last': L, 'kind': 'volume',
                        'now_t': round(a), 'prev_t': round(b), 'pct': round(100 * (a / b - 1), 1)})
        if a >= SEUIL_T and b:
            for o in ORIGINES.values():
                sa = 100 * sum(orig[(rep, x, o)] for x in m3) / 1000 / a
                sb = 100 * sum(orig[(rep, x, o)] for x in p3) / 1000 / b
                if abs(sa - sb) >= SEUIL_PART:
                    out.append({'id': f'{rep}-{L}-{o}', 'rep': rep, 'name': noms.get(rep, rep), 'last': L, 'kind': 'origin share',
                                'origin': o, 'share_now': round(sa, 1), 'share_prev': round(sb, 1)})
    return sorted(out, key=lambda x: (x['kind'] != 'volume', -abs(x.get('pct') or (x.get('share_now', 0) - x.get('share_prev', 0)))))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--depuis', type=int, default=2023); a = ap.parse_args()
    cle = os.environ.get('COMTRADE_KEY')
    ancien = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {'rows': [], 'meta': {}}
    if not cle:
        print('COMTRADE_KEY absente : importations mondiales non mises a jour (cle gratuite sur comtradeplus.un.org, a mettre en secret GitHub).')
        if os.path.exists(NEW): os.remove(NEW)
        return
    an = dt.date.today().year
    a_tirer = [y for y in range(a.depuis, an + 1) if y >= an - 1 or not any(r[0] // 100 == y for r in ancien['rows'])]
    garde = [r for r in ancien['rows'] if r[0] // 100 not in a_tirer]
    neuves, noms, echecs = [], dict(ancien['meta'].get('names', {})), []
    partenaires = None                      # tous les pays partenaires : les pays de transit (Suede, Danemark...) sont nommes, rien ne tombe en « autres »
    for y in a_tirer:
        periodes = [f'{y}{m:02d}' for m in range(1, 13) if dt.date(y, m, 1) <= dt.date.today()]
        for code in CODES:
            try:
                data = appel(cle, code, periodes, partenaires)
                for r in data:
                    if r.get('reporterISO') and r.get('reporterDesc'): noms[r['reporterISO']] = r['reporterDesc']
                neuves += lignes(data)
            except Exception as e:  # noqa: BLE001
                echecs.append(f'{y} {code} : {e}')
            time.sleep(1.5)
    rows = sorted(garde + neuves)
    if not rows: raise SystemExit('aucune donnee recue : ' + '; '.join(echecs[:3]))
    al = alertes(rows, noms)
    deja = set(ancien['meta'].get('notified', []))
    nouvelles = [x for x in al if x['id'] not in deja]
    dernier = {}
    for r in rows:
        if r[3] == 'W': dernier[r[1]] = max(dernier.get(r[1], 0), r[0])
    meta = {'fetched': dt.date.today().isoformat(), 'source': 'UN Comtrade, monthly imports declared by each importing country (HS6)',
            'cols': ['ym', 'reporter', 'hs6', 'partner (W = world)', 'kg', 'usd_cif'], 'codes': CODES, 'origins': list(ORIGINES.values()),
            'coproducts': COPRODUITS, 'generic': GENERIQUES,
            'names': noms, 'last_by_reporter': dernier, 'reporters': len(dernier), 'alerts': al,
            'thresholds': {'pct': SEUIL_PCT, 't': SEUIL_T, 'share_pts': SEUIL_PART},
            'notified': sorted(deja | {x['id'] for x in al}), 'failed': echecs[:20]}
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps({'meta': meta, 'rows': rows}, ensure_ascii=False, separators=(',', ':')))
    if nouvelles:
        mois = lambda k: dt.date(k // 100, k % 100, 1).strftime('%m/%Y')
        t = lambda v: f'{v:,}'.replace(',', ' ')
        txt = ['Nouvelles variations importantes dans les importations de saumon (UN Comtrade, 3 derniers mois declares contre un an plus tot) :', '']
        for x in nouvelles:
            if x['kind'] == 'volume':
                txt.append(f"- **{x['name']}** (jusqu'a {mois(x['last'])}) : {t(x['now_t'])} t contre {t(x['prev_t'])} t, **{x['pct']:+.0f} %**")
            else:
                txt.append(f"- **{x['name']}** (jusqu'a {mois(x['last'])}) : part de {x['origin']} {x['share_prev']:.0f} % -> **{x['share_now']:.0f} %**")
        txt += ['', "Detail dans l'onglet World imports du tableau de bord."]
        io.open(NEW, 'w', encoding='utf-8').write('\n'.join(txt) + '\n')
    elif os.path.exists(NEW):
        os.remove(NEW)
    print(f'data/world_imports.json : {len(rows)} lignes, {len(dernier)} pays importateurs, {len(al)} alertes dont {len(nouvelles)} nouvelles'
          + (f', {len(echecs)} appels en echec' if echecs else ''))


if __name__ == '__main__':
    main()
