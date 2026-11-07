#!/usr/bin/env python3
"""
data/wellboats.json : passages des bateaux de transport de poisson vivant (wellboats) et des bateaux d'abattage
sur les fermes norvegiennes, semaine par semaine, et alertes quand l'activite sort de l'ordinaire.

Source : API fiskehelse de BarentsWatch (meme client que les poux, scope "api") :
  /v1/geodata/fishhealth/vessels                        navires suivis, avec les drapeaux isWellboat / isSlaughterBoat
  /v1/geodata/fishhealth/locality/{no}/vessel/{annee}   passages de navires a chaque lokalitet, semaine par semaine
  /v1/geodata/fishhealth/vesselslatestpositions         derniere position de chaque navire suivi
BarentsWatch detecte un passage quand un navire reste dans l'emprise de la ferme (AIS de Kystverket).

Les fermes viennent du registre deja lu (data.json -> bw_register : zone de production et titulaire par lokalitet).
L'annee precedente est gardee dans data/wellboats_hist.json (relue une fois par mois), l'annee en cours chaque jour.

    BW_CLIENT_ID=... BW_CLIENT_SECRET=... python3 scripts/build_wellboats.py [--annee-precedente]
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import statistics
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'wellboats.json')
HIST = os.path.join(ROOT, 'data', 'wellboats_hist.json')
API = 'https://www.barentswatch.no/bwapi'
H = {'User-Agent': 'salmon-dashboard/1.0 (github.com/EmileviardotFO/saumon)'}


def token():
    r = requests.post('https://id.barentswatch.no/connect/token', data={'client_id': os.environ['BW_CLIENT_ID'], 'client_secret': os.environ['BW_CLIENT_SECRET'],
                                                                         'scope': 'api', 'grant_type': 'client_credentials'}, timeout=60)
    r.raise_for_status()
    return r.json()['access_token']


def get(path, T, tries=4):
    for i in range(tries):
        try:
            r = requests.get(API + path, headers={**H, 'Authorization': 'Bearer ' + T}, timeout=90)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(3 * (i + 1)); continue
            if r.status_code == 204:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(3 * (i + 1))
    return None


def year_visits(locs, year, T, kinds):
    """passages des wellboats et bateaux d'abattage, pour toutes les fermes, sur une annee"""
    out = []

    def one(no):
        js = get(f'/v1/geodata/fishhealth/locality/{no}/vessel/{year}', T) or []
        res = []
        for w in js:
            for v in w.get('vesselVisits') or []:
                k = kinds.get(v.get('mmsi'))
                if not k and not (v.get('isWellboat') or v.get('isSlaughterBoat')):
                    continue
                k = k or ('S' if v.get('isSlaughterBoat') else 'W')
                a, b = v.get('startTime'), v.get('stopTime')
                try:
                    hrs = (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 3600
                except Exception:
                    hrs = None
                res.append([int(no), int(w['year']), int(w['week']), int(v['mmsi']), k, a[:16] if a else None, round(hrs, 1) if hrs is not None else None])
        return res
    with cf.ThreadPoolExecutor(8) as ex:
        for r in ex.map(one, locs):
            out += r
    return out


STATE = os.path.join(ROOT, 'data', 'bw_farm_state.json')


def farm_states(T):
    """etat hebdomadaire de chaque ferme depuis octobre 2023 : F en jachere, A active, T active avec traitement anti-poux.
    Les 10 dernieres semaines sont relues a chaque passage (declarations tardives)."""
    st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {'weeks': [], 'sites': {}}
    weeks = []
    d = dt.date(2023, 10, 2)
    while d < dt.date.today() - dt.timedelta(days=6):
        y, w, _ = d.isocalendar(); weeks.append(f'{y}-{w:02d}'); d += dt.timedelta(weeks=1)
    old = {k: i for i, k in enumerate(st['weeks'])}
    sites = {no: [(v[old[k]] if k in old and old[k] < len(v) else '.') for k in weeks] for no, v in st['sites'].items()}
    todo = [i for i, k in enumerate(weeks) if k not in old or i >= len(weeks) - 10]
    hdr = {**H, 'Authorization': 'Bearer ' + T}
    for i in todo:
        y, w = map(int, weeks[i].split('-'))
        L = None
        for n in range(4):
            try:
                r = requests.post(f'{API}/v2/geodata/fishhealth/locality/{y}/{w}', json={}, headers=hdr, timeout=120)
                if r.ok: L = r.json(); break
            except requests.RequestException:
                pass
            time.sleep(5 * (n + 1))
        if not isinstance(L, list):
            continue
        for x in sites.values(): x[i] = '.'
        for s_ in L:
            loc = s_.get('locality') or {}; no = loc.get('no')
            if no is None or loc.get('isOnLand'):
                continue
            rep = s_.get('liceReport') or {}
            c = 'F' if rep.get('isFallow') else ('A' if rep.get('hasReported') else '.')
            if s_.get('liceTreatments'):
                c = 'T'
            if c != '.':
                sites.setdefault(str(no), ['.'] * len(weeks))[i] = c
    out = {'weeks': weeks, 'sites': {no: ''.join(v) for no, v in sites.items()}, 'built': dt.date.today().isoformat()}
    json.dump(out, open(STATE, 'w', encoding='utf-8'), separators=(',', ':'))
    print(f'  etats des fermes : {len(todo)} semaines relues, {len(sites)} fermes')
    return out


def classify(rows, site_po, site_org, T):
    """classe chaque passage : M mise en eau de smolts (ferme en jachere dans les 8 semaines avant, active ensuite),
    T traitement anti-poux (traitement declare la semaine d'avant, la semaine meme ou celle d'apres), H recolte ou transfert (le reste,
    et tout passage de bateau d'abattage). Agrege par mois ; estime les smolts mis en eau des mois pas encore publies."""
    st = farm_states(T)
    idx = {k: i for i, k in enumerate(st['weeks'])}; S = st['sites']

    def cls(no, y, w, k):
        if k == 'S':
            return 'H'
        i = idx.get(f'{y}-{w:02d}'); v = S.get(str(no))
        if i is None or not v:
            return 'H'
        if 'T' in v[max(0, i - 1):i + 2]:
            return 'T'
        if 'F' in v[max(0, i - 8):i] and ('A' in v[i:i + 4] or 'T' in v[i:i + 4]):
            return 'M'
        return 'H'
    mon = {}
    for no, y, w, mm, k, start, hrs in rows:
        if not start:
            continue
        c = 'HMT'.index(cls(no, y, w, k))
        for key in ('NO', f'PO{site_po.get(str(no))}', f'ORG:{site_org.get(str(no), "?")}'):
            a = mon.setdefault(key, {}).setdefault(start[:7], [0, 0, 0]); a[c] += 1
    # smolts mis en eau : chiffres officiels (Fiskeridirektoratet, data.json) et estimation des mois suivants
    rec = {}
    for r in (json.load(open(os.path.join(ROOT, 'data', 'data.json'), encoding='utf-8')).get('records') or []):
        k = f"{r['year']}-{r['month']:02d}"
        for key in ('NO', f"PO{r['po']}"):
            rec.setdefault(key, {})[k] = rec.get(key, {}).get(k, 0) + (r.get('smolt_stk') or 0)
    last_full = (dt.date.today().replace(day=1) - dt.timedelta(days=1)).strftime('%Y-%m')
    smolt = {}
    for key in ['NO'] + [f'PO{i}' for i in range(1, 14)]:
        R, Mo = rec.get(key, {}), mon.get(key, {})
        ks = sorted(k for k in R if k in Mo and k >= '2024-01')
        if len(ks) < 12:
            continue
        xs = [Mo[k][1] for k in ks]; ys = [R[k] for k in ks]
        n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
        vx = sum((x - mx) ** 2 for x in xs); vy = sum((y_ - my) ** 2 for y_ in ys)
        if not vx or not vy:
            continue
        b = sum((x - mx) * (y_ - my) for x, y_ in zip(xs, ys)) / vx; a = my - b * mx
        r_ = sum((x - mx) * (y_ - my) for x, y_ in zip(xs, ys)) / (vx * vy) ** .5
        err = []
        for i, k in enumerate(ks):
            if int(k[5:]) < 4:
                continue
            x2, y2 = xs[:i] + xs[i + 1:], ys[:i] + ys[i + 1:]; m2x = sum(x2) / len(x2); m2y = sum(y2) / len(y2)
            b2 = sum((x - m2x) * (y_ - m2y) for x, y_ in zip(x2, y2)) / sum((x - m2x) ** 2 for x in x2)
            err.append(abs(m2y + b2 * (xs[i] - m2x) - ys[i]))
        est = {k: max(0, round(a + b * Mo[k][1])) for k in sorted(Mo) if k > max(R) and k <= last_full}
        smolt[key] = {'official': {k: R[k] for k in sorted(R) if k >= '2024-01'}, 'est': est, 'r': round(r_, 2), 'err': round(sum(err) / len(err)) if err else None, 'per_visit': round(b)}
    print('  smolts estimes (Norvege) :', smolt.get('NO', {}).get('est'), 'r', smolt.get('NO', {}).get('r'))
    return {'cls': cls, 'monthly': mon, 'smolt': smolt,
            'meta': {'last_month': last_full, 'note': 'M = smolt delivery (farm fallow in the 8 weeks before, reporting after); T = lice treatment reported at the farm that week or the next/previous; H = harvest or transfer (all other visits, and every slaughter-boat visit).'}}


PULSE_LOG = os.path.join(ROOT, 'data', 'harvest_pulse_log.json')


def harvest_pulse(hist, reg, Y, T, kinds, rows):
    """'pouls des abattages' (en test, pas affiche) : chaque semaine, livraisons des wellboats aux cages d'attente des abattoirs
    + passages des bateaux d'abattage sur les fermes, contre la meme semaine un an plus tot. Chaque semaine, l'estimation est
    notee AVANT la publication SSB (data/harvest_pulse_log.json) pour juger la precision sur des semaines jamais vues.
    Test sur 2024-2026 : r = 0.88 avec les exportations SSB de saumon frais ; sens de l'ecart sur un an juste 56 fois sur 70."""
    cages = [str(c['no']) for c in reg.get('slaughter_cages') or []]
    if not cages:
        return
    hc = hist.setdefault('cages', {})
    if str(Y - 1) not in hc:
        hc[str(Y - 1)] = year_visits(cages, Y - 1, T, kinds)
    hc[str(Y)] = year_visits(cages, Y, T, kinds)
    for y in [y for y in hc if int(y) < Y - 1]:
        del hc[y]
    json.dump(hist, open(HIST, 'w', encoding='utf-8'), separators=(',', ':'))
    wk = {}
    for no, y, w, mm, k, start, hrs in hc[str(Y - 1)] + hc[str(Y)]:
        wk.setdefault(y * 100 + w, [0, 0])[0] += 1
    for no, y, w, mm, k, start, hrs in rows:
        if k == 'S':
            wk.setdefault(y * 100 + w, [0, 0])[1] += 1
    iso = dt.date.today().isocalendar(); cur = iso[0] * 100 + iso[1]
    full = max(k for k in wk if k < cur)
    ly = (dt.date.fromisocalendar(full // 100, full % 100, 1) - dt.timedelta(weeks=52)).isocalendar(); lyk = ly[0] * 100 + ly[1]
    a, b = sum(wk.get(full, [0, 0])), sum(wk.get(lyk, [0, 0]))
    log = json.load(open(PULSE_LOG, encoding='utf-8')) if os.path.exists(PULSE_LOG) else {'note': harvest_pulse.__doc__.strip(), 'weeks': {}}
    if str(full) not in log['weeks'] and b:
        log['weeks'][str(full)] = {'made': dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M'), 'cage_deliveries': wk[full][0], 'slaughter_boat_visits': wk[full][1],
                                   'same_week_last_year': b, 'yoy_pct': round(100 * (a / b - 1), 1)}
    log['series'] = {str(k): v for k, v in sorted(wk.items())}
    json.dump(log, open(PULSE_LOG, 'w', encoding='utf-8'), separators=(',', ':'))
    print(f'  pouls des abattages, semaine {full % 100} : {a} contre {b} un an plus tot ({100 * (a / b - 1) if b else 0:+.0f} %)')


def main():
    T = token()
    V = get('/v1/geodata/fishhealth/vessels', T) or []
    kinds = {v['mmsi']: ('S' if v.get('isSlaughterBoat') else 'W') for v in V if v.get('isWellboat') or v.get('isSlaughterBoat')}
    names = {v['mmsi']: v.get('vesselName') for v in V if v['mmsi'] in kinds}
    reg = (json.load(open(os.path.join(ROOT, 'data', 'data.json'), encoding='utf-8')).get('bw_register') or {})
    site_po, site_org, site_name, site_cap = reg.get('site_po', {}), reg.get('site_org', {}), reg.get('site_name', {}), reg.get('site_cap', {})
    locs = sorted(site_po, key=int)
    print(f'{len(kinds)} wellboats / bateaux d\'abattage ; {len(locs)} fermes de saumon')
    now = dt.date.today(); Y = now.isocalendar()[0]
    hist = json.load(open(HIST, encoding='utf-8')) if os.path.exists(HIST) else {}
    if '--annee-precedente' in sys.argv or str(Y - 1) not in hist.get('years', {}):
        t0 = time.time(); prev = year_visits(locs, Y - 1, T, kinds)
        hist.setdefault('years', {})[str(Y - 1)] = prev; hist['built'] = now.isoformat()
        json.dump(hist, open(HIST, 'w', encoding='utf-8'), separators=(',', ':'))
        print(f'  {Y - 1} : {len(prev)} passages en {time.time() - t0:.0f} s')
    t0 = time.time(); cur = year_visits(locs, Y, T, kinds)
    print(f'  {Y} : {len(cur)} passages en {time.time() - t0:.0f} s')
    if str(Y - 2) not in hist.get('years', {}):
        t0 = time.time(); hist['years'][str(Y - 2)] = year_visits(locs, Y - 2, T, kinds)
        json.dump(hist, open(HIST, 'w', encoding='utf-8'), separators=(',', ':'))
        print(f'  {Y - 2} : {len(hist["years"][str(Y - 2)])} passages en {time.time() - t0:.0f} s')
    for old_y in [y for y in hist.get('years', {}) if int(y) < Y - 2]:
        del hist['years'][old_y]
    rows = hist['years'].get(str(Y - 1), []) + cur
    harvest_pulse(hist, reg, Y, T, kinds, rows)
    kinds_out = classify(hist['years'].get(str(Y - 2), []) + rows, site_po, site_org, T)
    # ---- agregats hebdomadaires : Norvege, zone, titulaire
    def wk(y, w): return y * 100 + w
    last_wk = max((wk(r[1], r[2]) for r in cur), default=None)
    # la semaine en cours est incomplete : on s'arrete a la derniere semaine pleine
    iso = now.isocalendar(); cur_wk = wk(iso[0], iso[1])
    full_last = max((k for k in {wk(r[1], r[2]) for r in rows} if k < cur_wk), default=last_wk)
    agg = {}
    for no, y, w, mm, k, start, hrs in rows:
        po = site_po.get(str(no)); org = site_org.get(str(no), '?')
        for key in ('NO', f'PO{po}', f'ORG:{org}'):
            a = agg.setdefault(key, {}).setdefault(wk(y, w), [0, 0, 0.0, set()])
            if k == 'W':
                a[0] += 1; a[2] += hrs or 0; a[3].add(mm)
            else:
                a[1] += 1
    series = {key: {str(w): [v[0], v[1], round(v[2]), len(v[3])] for w, v in sorted(d.items())} for key, d in agg.items()}
    # ---- alertes : semaine pleine la plus recente contre les 8 precedentes et la meme semaine un an plus tot
    def back(k, n):
        d = dt.date.fromisocalendar(k // 100, k % 100, 1) - dt.timedelta(weeks=n); c = d.isocalendar(); return wk(c[0], c[1])
    alerts = []
    for key, d in agg.items():
        x = d.get(full_last, [0, 0, 0, set()])[0]
        prev = [d.get(back(full_last, i), [0])[0] for i in range(1, 9)]
        ly = d.get(back(full_last, 52), [0])[0]
        m = statistics.mean(prev); sd = statistics.pstdev(prev) or 1
        if x >= 5 and x >= 1.5 * max(m, 1) and (x - m) / sd >= 2:
            alerts.append({'key': key, 'week': full_last, 'visits': x, 'avg8': round(m, 1), 'ly': ly, 'z': round((x - m) / sd, 1), 'kind': 'high'})
        elif key.startswith('PO') and m >= 8 and x <= 0.4 * m:
            alerts.append({'key': key, 'week': full_last, 'visits': x, 'avg8': round(m, 1), 'ly': ly, 'z': round((x - m) / sd, 1), 'kind': 'low'})
    # ---- fermes tres frequentees ces 14 derniers jours
    since = (now - dt.timedelta(days=14)).isoformat()
    by_site = {}
    for no, y, w, mm, k, start, hrs in cur:
        if not start or start[:10] < since:
            continue
        s = by_site.setdefault(no, {'W': 0, 'S': 0, 'h': 0.0, 'boats': set(), 'last': '', 'K': {'H': 0, 'M': 0, 'T': 0}})
        s['K'][kinds_out['cls'](no, y, w, k)] += 1
        s[k] += 1; s['h'] += hrs or 0; s['boats'].add(names.get(mm) or str(mm)); s['last'] = max(s['last'], start)
    hot = sorted([{'no': no, 'name': site_name.get(str(no)), 'po': site_po.get(str(no)), 'org': site_org.get(str(no)), 'cap': site_cap.get(str(no)),
                   'wb': s['W'], 'sb': s['S'], 'kind': s['K'], 'hours': round(s['h']), 'boats': sorted(s['boats'])[:6], 'last': s['last']}
                  for no, s in by_site.items()], key=lambda x: (-(x['wb'] + 2 * x['sb']), -x['hours']))[:80]
    # ---- positions actuelles des wellboats
    pos = []
    for p in get('/v1/geodata/fishhealth/vesselslatestpositions', T) or []:
        if p.get('mmsi') in kinds and p.get('geometry'):
            lo, la = p['geometry']['coordinates'][:2]
            pos.append({'mmsi': p['mmsi'], 'name': p.get('name') or names.get(p['mmsi']), 'k': kinds[p['mmsi']], 'lat': round(la, 4), 'lon': round(lo, 4),
                        'sog': p.get('sog'), 'ts': (p.get('timestamp') or '')[:16], 'dest': p.get('destination')})
    out = {'meta': {'built': dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), 'year': Y, 'last_full_week': full_last, 'current_week': cur_wk,
                    'boats': len(kinds), 'sites': len(locs), 'source': 'BarentsWatch fish health API: vessel visits at fish farms (AIS, Norwegian Coastal Administration)'},
           'series': series, 'kinds': kinds_out['monthly'], 'smolt': kinds_out['smolt'], 'kinds_meta': kinds_out['meta'], 'alerts': sorted(alerts, key=lambda a: -a['z']), 'hot': hot, 'positions': pos,
           'boats': {str(mm): [names.get(mm), k] for mm, k in kinds.items()}}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'ecrit {OUT} ({os.path.getsize(OUT) // 1024} ko) : {len(alerts)} alertes, {len(hot)} fermes actives sur 14 jours, {len(pos)} positions')


if __name__ == '__main__':
    main()
