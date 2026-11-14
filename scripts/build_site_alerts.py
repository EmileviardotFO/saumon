#!/usr/bin/env python3
"""
data/site_alerts.json : fermes norvegiennes ou le bateau de ramassage des poissons morts (ensilage) reste anormalement
longtemps, et ce qui suit (arrivee des bateaux d'abattage, site vide). Notification ntfy a chaque etape nouvelle.

Pourquoi : une mortalite massive se voit d'abord la. Grieg (Tollaksholmen, septembre 2026) : 10 h puis 20 h de bateau
d'ensilage deux semaines avant l'annonce en bourse ; Mowi (Oksen, meme mois) : 39 h, puis site vide en trois semaines ;
mars 2026 : trois sites de la zone 1 pendant la floraison de Pseudochattonella.

Regle : au moins SEUIL_H heures de bateau d'ensilage sur une ferme en 7 jours (une visite ordinaire dure moins d'une heure).
Un seul evenement par ferme tant que 42 jours ne se sont pas ecoules sans nouveau depassement.
Etapes : dead (le signal), harvest (bateaux d'abattage dans les 21 jours alors qu'il n'y en avait pas avant), empty (site
declare vide dans les 10 semaines).

Limite : BarentsWatch ne suit qu'un bateau d'ensilage (Scanbio Embla), qui travaille surtout du Rogaland au Vestland
(zones 1 a 4) et beaucoup pour Mowi. Une ferme servie par un autre bateau ne declenche rien.

Lit ce que maj-wellboats vient d'ecrire (wellboats_hist.json, wellboats.json, bw_farm_state.json) et les caches
BarentsWatch (bw_sites.json, bw_treatments.json, bw_site_lice.json). Aucun appel reseau hors ntfy.

    NTFY_TOPIC=... python3 scripts/build_site_alerts.py        # NTFY_TEST=1 : renvoie le dernier evenement, marque [TEST]
"""
import collections
import datetime as dt
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda f: os.path.join(ROOT, 'data', f)
OUT = D('site_alerts.json')
PAGE = 'https://emileviardotfo.github.io/saumon/docs/production.html'
SEUIL_H = 9          # heures de bateau d'ensilage sur 7 jours
GAP_D = 42           # jours sans depassement avant de compter un nouvel evenement sur la meme ferme
SILAGE = ('SCANBIO',)   # debut du nom des bateaux d'ensilage suivis par BarentsWatch
TRT = {'MEKANISK_BEHANDLING': 'mechanical', 'TERMISK_BEHANDLING': 'thermal', 'FERSKVANNSBEHANDLING': 'freshwater', 'SPYLING': 'flushing'}
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def load(f, default=None):
    try:
        return json.load(open(D(f), encoding='utf-8'))
    except (OSError, ValueError):
        return default


def day(t):
    return f'{t.day} {MON[t.month - 1]}'


def wkey(t):
    y, w, _ = t.isocalendar()
    return f'{y}-{w:02d}'


def detect():
    hist = load('wellboats_hist.json', {})
    boats = (load('wellboats.json', {}) or {}).get('boats', {})
    sil = {int(m) for m, v in boats.items() if any(v[0].startswith(p) for p in SILAGE)}
    rows = []
    for y in sorted(hist.get('years', {})):
        rows += hist['years'][y]
    rows += (hist.get('current') or {}).get('rows', [])
    V, S = collections.defaultdict(list), collections.defaultdict(list)
    for no, _y, _w, mm, k, start, hrs in rows:
        t = dt.datetime.fromisoformat(start)
        if mm in sil:
            V[no].append((t, hrs or 0))
        if k == 'S':
            S[no].append(t)
    last_seen = max((t for v in V.values() for t, _ in v), default=None)
    ev = []
    for no, v in V.items():
        v.sort(); cur = None
        for t, _h in v:
            win = [(tt, hh) for tt, hh in v if t - dt.timedelta(days=7) < tt <= t]
            tot = sum(hh for _, hh in win)
            if tot < SEUIL_H:
                continue
            if cur and (t - cur['_last']).days <= GAP_D:
                cur['_last'] = t; cur['hours'] = round(max(cur['hours'], tot), 1); cur['until'] = t.date().isoformat()
                continue
            cur = {'no': no, 'start': win[0][0].date().isoformat(), 'detected': t.date().isoformat(), 'until': t.date().isoformat(),
                   'hours': round(tot, 1), '_last': t, '_t0': win[0][0]}
            ev.append(cur)
    return ev, V, S, last_seen


def context(e, V, S, sites, org, state, trt, lice):
    no, t0 = e['no'], e['_t0']
    s = sites.get(str(no), {})
    e.update(name=s.get('name') or str(no), po=s.get('po'), mun=s.get('mun'), cap=s.get('cap'),
             org=org.get(str(no)) or ((s.get('org') or [{}])[0].get('name', '?').title()))
    # heures d'ensilage habituelles : moyenne hebdomadaire des 26 semaines precedentes
    prev = [h for t, h in V[no] if dt.timedelta(0) < t0 - t <= dt.timedelta(weeks=26)]
    e['usual_h_week'] = round(sum(prev) / 26, 1)
    e['total_h'] = round(sum(h for t, h in V[no] if dt.timedelta(0) <= t - t0 <= dt.timedelta(days=28)), 1)
    # bateaux d'abattage : avant (21 jours) et apres (21 jours)
    before = [t for t in S[no] if dt.timedelta(0) < t0 - t <= dt.timedelta(days=21)]
    after = sorted(t for t in S[no] if dt.timedelta(0) <= t - t0 <= dt.timedelta(days=28))
    e['slaughter_before'] = len(before)
    e['slaughter_after'] = len(after)
    e['slaughter_first'] = after[0].date().isoformat() if after else None
    e['slaughter_last'] = after[-1].date().isoformat() if after else None
    # semaines en mer avant le signal, et site vide ensuite
    wks, st = state.get('weeks', []), (state.get('sites', {}) or {}).get(str(no), '')
    k = wkey(t0); e['weeks_at_sea'] = None; e['empty_week'] = None
    if k in wks and st:
        i = wks.index(k); n = 0
        for c in reversed(st[:i + 1]):
            if c == 'F':
                break
            n += 1
        e['weeks_at_sea'] = n if n < i + 1 else None      # None : en mer depuis avant le debut de l'historique
        for j in range(i + 1, min(i + 11, len(st))):
            if st[j] == 'F':
                e['empty_week'] = wks[j]; break
    # traitements anti-poux declares dans les 8 semaines avant
    tk = []
    for b in range(0, 9):
        w = wkey(t0 - dt.timedelta(weeks=b)).split('-')
        x = trt.get(f'{no}|{int(w[0])}|{int(w[1])}')
        if x:
            tk.append(sorted({TRT.get(q.split('|')[-1], q.split('|')[0]) for q in x.get('keys', []) if q != 'combination'}))
    e['treatments_8w'] = len(tk)
    e['treatment_kinds'] = sorted({q for x in tk for q in x})
    lw, ls = lice.get('weeks', []), (lice.get('sites', {}) or {}).get(str(no), [])
    e['lice'] = None
    if k in lw and ls:
        i = lw.index(k)
        e['lice'] = next((x for x in reversed(ls[max(0, i - 3):i + 1]) if x is not None), None)
    stages = ['dead']
    if e['slaughter_after'] >= 2 and e['slaughter_before'] <= 1:
        stages.append('harvest')
    if e['empty_week']:
        stages.append('empty')
    e['stages'] = stages
    e['id'] = f"{no}-{e['start']}"
    for q in ('_last', '_t0'):
        e.pop(q, None)
    return e


def where(e):
    return f"{e['name']} ({e['org']}, zone {e['po']})"


def message(e, stage, others):
    age = ('farm reported empty that week' if e['weeks_at_sea'] == 0 else f"fish at sea for {e['weeks_at_sea']} weeks" if e['weeks_at_sea'] else None)
    head = ' · '.join(x for x in [e.get('mun'), f"licence {e['cap']:,.0f} t".replace(',', ' ') if e.get('cap') else None, age] if x)
    d0 = dt.date.fromisoformat(e['start'])
    L = [head]
    if stage == 'dead':
        title = f"Dead-fish boat {e['hours']:.0f} h at {where(e)}"
        L.append(f"Silage boat on site {e['hours']:.0f} h within 7 days from {day(d0)}; usual there: {e['usual_h_week']} h a week.")
    elif stage == 'harvest':
        title = f"{where(e)}: slaughter boats after the dead-fish alert"
        f1 = dt.date.fromisoformat(e['slaughter_first'])
        L.append(f"First slaughter boat on {day(f1)}, {(f1 - d0).days} days after the silage boat ({e['total_h']:.0f} h so far); {e['slaughter_after']} visits since. None in the three weeks before."
                 if not e['slaughter_before'] else
                 f"{e['slaughter_after']} slaughter-boat visits since {day(f1)} ({e['slaughter_before']} in the three weeks before); silage boat {e['total_h']:.0f} h so far.")
    else:
        title = f"{where(e)}: site emptied after the dead-fish alert"
        L.append(f"Reported empty in week {e['empty_week'].split('-')[1]}; silage boat {e['total_h']:.0f} h from {day(d0)}, {e['slaughter_after']} slaughter-boat visits.")
    if e['treatments_8w']:
        L.append(f"Before: {e['treatments_8w']} weeks with a lice treatment in the last 8 ({', '.join(e['treatment_kinds'])})" + (f"; lice {e['lice']}." if e['lice'] is not None else '.'))
    elif e['lice'] is not None:
        L.append(f"No lice treatment reported in the 8 weeks before; lice {e['lice']}.")
    if stage == 'dead':
        L.append(f"Slaughter boats already there: {e['slaughter_before']} visits in the three weeks before." if e['slaughter_before'] > 1 else
                 (f"Slaughter boats: {e['slaughter_after']} visits since {day(dt.date.fromisoformat(e['slaughter_first']))}." if e['slaughter_after'] else 'Slaughter boats: none yet.'))
    if others:
        L.append('Same signal in the last 45 days: ' + ', '.join(f"{o['name']} (zone {o['po']})" for o in others[:6]) + '.')
    L.append('Cause not known from the boats: could be algae, gills, treatment losses or disease.')
    return title, '\n'.join(L)


def send(title, body, test=False):
    topic = os.environ.get('NTFY_TOPIC', '').strip()
    if test:
        title = '[TEST] ' + title
    if os.environ.get('NTFY_DRY_RUN') or not topic:
        print('---', title); print(body)
        return bool(os.environ.get('NTFY_DRY_RUN'))
    req = urllib.request.Request(f'https://ntfy.sh/{topic}', data=body.encode('utf-8'), method='POST',
                                 headers={'Title': title.encode('utf-8').decode('latin-1'), 'Tags': 'warning,fish', 'Priority': 'high', 'Click': PAGE,
                                          'Actions': f'view, Open the dashboard, {PAGE}'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f'Notification envoyee ({r.status}) : {title}')
        return True
    except Exception as x:                       # une notification manquee ne doit pas bloquer la collecte ; elle repartira demain
        print(f'Notification non envoyee : {x}')
        return False


def main():
    ev, V, S, last_seen = detect()
    sites = (load('bw_sites.json', {}) or {}).get('sites', {})
    org = ((load('data.json', {}) or {}).get('bw_register') or {}).get('site_org', {})
    state = load('bw_farm_state.json', {}) or {}
    trt = (load('bw_treatments.json', {}) or {}).get('site_week', {})
    lice = load('bw_site_lice.json', {}) or {}
    ev = sorted((context(e, V, S, sites, org, state, trt, lice) for e in ev), key=lambda e: e['start'], reverse=True)
    old = load('site_alerts.json')
    sent = {e['id']: list(e.get('sent', [])) for e in (old or {}).get('events', [])}
    today = dt.date.today()
    first_run = old is None
    test = bool(os.environ.get('NTFY_TEST'))

    def others(e):
        d = dt.date.fromisoformat(e['start'])
        return [o for o in ev if o['id'] != e['id'] and 0 <= (d - dt.date.fromisoformat(o['start'])).days <= 45]

    if test and ev:
        e = ev[0]
        send(*message(e, e['stages'][-1], others(e)), test=True)
    n = 0
    for e in ev:
        done = sent.get(e['id'], [])
        age = (today - dt.date.fromisoformat(e['start'])).days
        for st in e['stages']:
            if st in done:
                continue
            # premier passage, ou evenement ancien : on note sans notifier (pas de rafale sur l'historique)
            if first_run or test or age > (30 if st == 'dead' else 100):
                done.append(st); continue
            if send(*message(e, st, others(e))):
                done.append(st); n += 1
        e['sent'] = done
    by_year = collections.Counter(e['start'][:4] for e in ev)
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M+00:00'),
                    'last_silage_visit': last_seen.date().isoformat() if last_seen else None,
                    'rule': f'silage boat on a farm for at least {SEUIL_H} h within 7 days (an ordinary visit lasts under an hour); one event per farm until {GAP_D} days pass without it',
                    'stages': 'dead = the signal; harvest = at least 2 slaughter-boat visits in the 4 weeks after, at most 1 in the 3 weeks before; empty = farm reported empty within 10 weeks',
                    'limit': 'BarentsWatch tracks one silage boat only (Scanbio Embla), working mostly from Rogaland to Vestland (zones 1 to 4) and largely for Mowi; a farm served by another boat raises nothing. The boats do not tell the cause.',
                    'source': 'BarentsWatch fish health API (vessel visits at farms, AIS), farm reports (fallow, lice, treatments)',
                    'per_year': dict(sorted(by_year.items()))},
           'events': ev}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'ecrit {OUT} : {len(ev)} evenements ({dict(sorted(by_year.items()))}), {n} notifications')
    return 0


if __name__ == '__main__':
    sys.exit(main())
