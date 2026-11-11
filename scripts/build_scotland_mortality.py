#!/usr/bin/env python3
"""
Ecosse : mortalite mensuelle par ferme, rapports « Monthly mortality rate » de Salmon Scotland (PDF, un par mois).
Le site refuse les robots : les PDF sont deposes a la main dans farming/donnees_gb/salmon_scotland/ (n'importe quel nom).

Chaque rapport donne, par ferme : la mortalite du mois (% des poissons presents), la cause declaree, et la mortalite
cumulee du cycle quand la ferme vient d'etre videe ; plus, en tete, la mortalite mensuelle de toute la filiere depuis 2018.

    python3 scripts/build_scotland_mortality.py        -> data/scotland_mortality.json
"""
import collections, glob, json, os, re, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'farming', 'donnees_gb', 'salmon_scotland')
MON = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
SHORT = {'Bakkafrost Scotland': 'Bakkafrost Scotland', 'Cooke Aquaculture (Scotland)': 'Cooke', 'Mowi Scotland Limited': 'Mowi', 'Scottish Sea Farms Ltd': 'Scottish Sea Farms', 'Loch Duart Ltd': 'Loch Duart',
         'Organic Sea Harvest Ltd': 'Organic Sea Harvest', 'Hendrix-Genetics': 'Hendrix Genetics'}


def text(pdf):
    try:
        return subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True, check=True).stdout
    except Exception:
        # pas de repli sur pdfplumber : sa mise en page decale les colonnes et fait perdre des fermes et la serie filiere.
        # Sans pdftotext (paquet poppler-utils) on ne reecrit rien plutot que d'abimer le fichier.
        raise SystemExit('scotland mortality : pdftotext absent (installer poppler-utils), fichier laisse tel quel')


def parse(pdf):
    L = text(pdf).split('\n')
    m = next((re.search(r'(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(20\d\d)', l) for l in L[:5] if l.strip()), None)
    if not m:
        return None
    ym = int(m.group(2)) * 100 + MON[m.group(1).lower()]
    ind = {}
    for l in L[:60]:
        for v, mo, y in re.findall(r'(\d+\.\d+)% in ([A-Za-z]{3})[a-z]*\.? (20\d\d)', l):
            ind[int(y) * 100 + MON[mo.lower()]] = float(v)
    farms = []
    for l in L:
        f = re.split(r'\s{2,}', l.strip())
        if len(f) < 4 or f[0] not in SHORT:
            continue
        mm = re.match(r'(\d+(?:\.\d+)?)\s*(?:\((.*)\))?$', f[2])
        cause = f[3] if len(f) == 5 and f[3] != 'Fallow' else ''
        cum = float(f[-1]) if re.fullmatch(r'\d+(\.\d+)?', f[-1]) else None
        ev = (mm.group(2) or '') if mm else ''
        status = 'fallow' if not mm else 'stocked' if 'stocked' in ev else 'emptied' if 'fallowed' in ev else 'production'
        farms.append({'co': SHORT[f[0]], 'farm': f[1], 'm': float(mm.group(1)) if mm else None, 'st': status, 'cause': cause, 'cum': cum,
                      'moved': 'not harvested' in (ev + ' ' + f[-1]).lower()})
    return ym, ind, farms


def main():
    months, ind = {}, {}
    for pdf in sorted(glob.glob(os.path.join(SRC, '*.pdf'))):
        r = parse(pdf)
        if not r or len(r[2]) < 50:
            print('illisible :', os.path.basename(pdf))
            continue
        ym, i, farms = r
        ind.update(i)
        act = [x for x in farms if x['m'] is not None]
        co = collections.defaultdict(list)
        for x in act:
            co[x['co']].append(x['m'])
        causes = collections.Counter(c.strip() for x in act for c in x['cause'].split(',') if c.strip())
        months[str(ym)] = {'farms': farms, 'n': len(farms), 'active': len(act), 'industry': i.get(ym),
                           'over5': sum(x['m'] >= 5 for x in act), 'over10': sum(x['m'] >= 10 for x in act),
                           'emptied': sum(x['st'] == 'emptied' for x in farms), 'stocked': sum(x['st'] == 'stocked' for x in farms),
                           'companies': sorted(({'co': k, 'n': len(v), 'mean': round(sum(v) / len(v), 2), 'median': round(sorted(v)[len(v) // 2], 1), 'max': max(v), 'over5': sum(z >= 5 for z in v)} for k, v in co.items()), key=lambda z: -z['n']),
                           'causes': causes.most_common()}
        print(ym, len(farms), 'fermes,', len(act), 'en mer, filiere', i.get(ym), '%')
    if not months:
        print('scotland mortality : aucun PDF dans', SRC)
        return
    for k in months:
        months[k]['industry'] = ind.get(int(k), months[k]['industry'])
    # cycles termines : mortalite cumulee declaree le mois ou la ferme est videe
    cycles = sorted(({'m': k, 'co': x['co'], 'farm': x['farm'], 'cum': x['cum']} for k in months for x in months[k]['farms'] if x['cum'] is not None), key=lambda z: z['m'])
    out = {'meta': {'source': 'Salmon Scotland, Monthly mortality rate (one PDF a month, published about a month in arrears)', 'url': 'https://www.salmonscotland.co.uk/reports',
                    'note': 'Monthly mortality = fish lost in the month as % of the fish on the farm. Company means are simple averages of farms, not weighted by fish numbers. Cumulative = whole sea cycle, reported once the farm is emptied.'},
           'industry': {str(k): v for k, v in sorted(ind.items())}, 'cycles': cycles, 'months': months, 'latest': max(months)}
    json.dump(out, open(os.path.join(ROOT, 'data', 'scotland_mortality.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main()
