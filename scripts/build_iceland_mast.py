#!/usr/bin/env python3
"""
Iceland: monthly figures of MAST's aquaculture dashboard (Mælaborð fiskeldis), read from its public Power BI reports.

    python3 scripts/build_iceland_mast.py        -> data/iceland_mast.json

What is read (sea farming of Atlantic salmon only):
  - national, month by month: biomass, feed used, harvest, mortality, discards (tonnes);
  - site by site and month by month: fish at sea (end of month), fish stocked, harvested, dead, by company and fjord.
From the site series the script rebuilds each production cycle (stocking after a fallow -> site emptied), as for Norway:
months at sea by company and by fjord, sites with fish now and their age.

The dashboard is the public "Publish to web" Power BI that MAST embeds on mast.is; the queries below are the ones its own
charts send. Free, no key. If Power BI changes, the script stops cleanly and the tab keeps the previous file.
"""
import base64
import datetime as dt
import json
import os
import re
import statistics
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'iceland_mast.json')
PROBE = os.path.join(ROOT, 'data', 'iceland.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
HOSTS = ['https://wabi-north-europe-d-primary-api.analysis.windows.net'] + \
        [f'https://wabi-north-europe{L}-primary-api.analysis.windows.net' for L in ('-a', '-b', '-c', '-e', '-f', '-g', '-h', '-i', '-j', '-k', '-l', '-m')] + \
        [f'https://wabi-west-europe{L}-primary-api.analysis.windows.net' for L in ('-a', '-b', '-c', '-d', '-e', '-f')]
is_salmon = lambda t: bool(t) and re.match(r'(?i)\s*(lax|atlantic salmon|salmo salar)', str(t)) is not None   # "Tegund" = species


def http(url, data=None, headers=None, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers=dict(UA, **(headers or {}), **({'Content-Type': 'application/json'} if data is not None else {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


class Report:
    """One public Power BI report: finds its cluster, model and runs semantic queries against it."""

    def __init__(self, embed):
        r = re.search(r'r=([^&]+)', embed).group(1)
        self.key = json.loads(base64.b64decode(r + '=' * (-len(r) % 4)))['k']
        self.h = {'X-PowerBI-ResourceKey': self.key, 'Accept': 'application/json'}
        self.mx = None
        for host in HOSTS:
            try:
                self.mx = http(f'{host}/public/reports/{self.key}/modelsAndExploration?preferReadOnlySession=true', headers=self.h, timeout=30)
                self.host = host
                break
            except Exception:
                continue
        if not self.mx:
            raise RuntimeError('no Power BI cluster answered')
        m = self.mx['models'][0]
        self.model_id, self.db = m['id'], m['dbName']
        self.report_id = (self.mx.get('exploration', {}).get('report') or {}).get('objectId')
        sch = http(f'{self.host}/public/reports/conceptualschema', {'modelIds': [self.model_id], 'userPreferredLocale': 'en-US'}, self.h)
        self.tables = {e['Name']: [p['Name'] for p in e.get('Properties', [])] for e in sch['schemas'][0]['schema']['Entities']}

    def query(self, table, groups, sums, where=None, count=30000):
        """Rows of `groups` columns with the sum of each `sums` column, as a list of dicts."""
        src = {'SourceRef': {'Source': 't'}}
        sel = [{'Column': {'Expression': src, 'Property': g}, 'Name': f't.{g}'} for g in groups] + \
              [{'Aggregation': {'Expression': {'Column': {'Expression': src, 'Property': s}}, 'Function': 0}, 'Name': f'Sum(t.{s})'} for s in sums]
        q = {'Version': 2, 'From': [{'Name': 't', 'Entity': table, 'Type': 0}], 'Select': sel}
        if where:
            q['Where'] = [{'Condition': {'In': {'Expressions': [{'Column': {'Expression': src, 'Property': col}}],
                                                'Values': [[{'Literal': {'Value': f"'{v}'"}}] for v in vals]}}} for col, vals in where.items()]
        rows, token = [], None
        for _ in range(40):
            window = {'Count': count}
            if token:
                window['RestartTokens'] = token
            body = {'version': '1.0.0', 'cancelQueries': [], 'modelId': self.model_id, 'queries': [{
                'Query': {'Commands': [{'SemanticQueryDataShapeCommand': {
                    'Query': q,
                    'Binding': {'Primary': {'Groupings': [{'Projections': list(range(len(sel)))}]},
                                'DataReduction': {'DataVolume': 4, 'Primary': {'Window': window}}, 'Version': 1}}}]},
                'QueryId': '', 'ApplicationContext': {'DatasetId': self.db, 'Sources': [{'ReportId': self.report_id}] if self.report_id else []}}]}
            res = http(f'{self.host}/public/reports/querydata?synchronous=true', body, self.h)
            out, token = decode_dsr(res, len(sel))
            rows += out
            if not token:
                break
        names = groups + sums
        return [dict(zip(names, r)) for r in rows]


def decode_dsr(res, ncol):
    """Power BI's compressed result format (DSR): repeated values ('R' bitmask), nulls ('Ø' bitmask), dictionaries ('D0'...)."""
    data = res['results'][0]['result']['data']
    dsr = data['dsr']
    ds = dsr['DS'][0]
    dicts = ds.get('ValueDicts', {})
    ph = ds['PH'][0]
    dm = next(v for k, v in ph.items() if k.startswith('DM'))
    schema = None
    rows, prev = [], [None] * ncol
    for item in dm:
        if 'S' in item:
            schema = item['S']
        vals = item.get('C', [])
        rep, nul = item.get('R', 0), item.get('Ø', 0)
        row, vi = [], 0
        for i in range(ncol):
            if rep >> i & 1:
                row.append(prev[i])
            elif nul >> i & 1:
                row.append(None)
            else:
                v = vals[vi] if vi < len(vals) else None
                vi += 1
                dn = (schema[i].get('DN') if schema and i < len(schema) else None)
                if dn and isinstance(v, int) and dn in dicts:
                    v = dicts[dn][v]
                row.append(v)
        prev = row
        rows.append(row)
    token = ds.get('RT')
    return rows, token


def month(v):
    """Power BI dates come back as epoch milliseconds (or ISO text)."""
    if isinstance(v, (int, float)):
        d = dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=v)
    else:
        d = dt.datetime.fromisoformat(str(v)[:19])
    return f'{d.year}-{d.month:02d}'


def cycles(site_rows):
    """Production cycles from monthly fish counts of each site: first month with fish after >= 2 empty months -> last month with fish."""
    by_site = {}
    for r in site_rows:
        by_site.setdefault(r['site'], []).append(r)
    done, active = [], []
    for site, L in by_site.items():
        L.sort(key=lambda r: r['m'])
        months = [r['m'] for r in L]
        fish = {r['m']: (r['fish'] or 0) for r in L}
        stocked = {r['m']: (r['in'] or 0) for r in L}
        allm = month_range(months[0], months[-1])
        start, empty = None, 2
        for m in allm:
            has = fish.get(m, 0) > 1000
            if has and start is None and empty >= 2:
                start = m
                # the cycle starts at the first month with fish stocked if it is the month before
                prevm = add_months(m, -1)
                if stocked.get(prevm, 0) > 1000:
                    start = prevm
            if has:
                empty = 0
            else:
                if start is not None:
                    end = add_months(m, -1)
                    co = next((r['co'] for r in reversed(L) if r['m'] <= end), L[-1]['co'])
                    done.append({'site': site, 'co': co, 'fjord': L[-1]['fjord'], 'start': start, 'end': end, 'months': months_between(start, end) + 1})
                    start = None
                empty += 1
        if start is not None:
            active.append({'site': site, 'co': L[-1]['co'], 'fjord': L[-1]['fjord'], 'start': start, 'age': months_between(start, allm[-1]) + 1,
                           'fish': fish.get(allm[-1], 0)})
    # a cycle that started before the first month of data is cut: its length is unknown
    first = min(r['m'] for r in site_rows)
    done = [c for c in done if c['start'] > first]
    return done, active


def month_range(a, b):
    out, m = [], a
    while m <= b:
        out.append(m)
        m = add_months(m, 1)
    return out


def add_months(m, k):
    y, mo = int(m[:4]), int(m[5:7]) + k
    while mo > 12:
        y, mo = y + 1, mo - 12
    while mo < 1:
        y, mo = y - 1, mo + 12
    return f'{y}-{mo:02d}'


def months_between(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def summary(L):
    if not L:
        return None
    s = sorted(L)
    return {'n': len(s), 'median': round(statistics.median(s), 1), 'p25': s[len(s) // 4], 'p75': s[(3 * len(s)) // 4]}


def main():
    meta = json.load(open(PROBE, encoding='utf-8')).get('meta', {})
    embeds = [u.strip() for u in str(meta.get('dashboard_embed', '')).split(',') if 'powerbi' in u]
    if not embeds:
        print('No MAST Power BI link in data/iceland.json: run scripts/build_iceland.py first.'); return 1
    reports = []
    for e in embeds:
        try:
            reports.append(Report(e))
        except Exception as ex:
            print('report skipped:', ex)
    find = lambda t: next((r for r in reports if t in r.tables), None)
    out = {'meta': {'generated': dt.date.today().isoformat(), 'source': 'MAST, Mælaborð fiskeldis (public Power BI), sea farming of Atlantic salmon',
                    'url': 'https://www.mast.is/is/maelabord-fiskeldis'}}

    # ---- national, month by month ----
    r = find('aquaculture_overall')
    if r:
        cols = r.tables['aquaculture_overall']
        sums = [c for c in ('BiomassKg_Closing', 'FeedUseKg_InPeriod', 'MortalityBiomass_InPeriod', 'Slátrað: Lífmassi (g)', 'Fargað: Lífmassi (kg)') if c in cols]
        rows = r.query('aquaculture_overall', ['Lok tímabils', 'Tegund'], sums)
        species = sorted({x['Tegund'] for x in rows if x['Tegund']})
        print('national: species', species, len(rows), 'rows')
        nat = {}
        for x in rows:
            if not is_salmon(x['Tegund']) or x['Lok tímabils'] is None:
                continue
            m = month(x['Lok tímabils'])
            o = nat.setdefault(m, {'m': m, 'biomass_t': 0, 'feed_t': 0, 'mortality_t': 0, 'harvest_t': 0, 'discard_t': 0})
            o['biomass_t'] += (x.get('BiomassKg_Closing') or 0) / 1000
            o['feed_t'] += (x.get('FeedUseKg_InPeriod') or 0) / 1000
            o['mortality_t'] += (x.get('MortalityBiomass_InPeriod') or 0) / 1000
            o['harvest_t'] += (x.get('Slátrað: Lífmassi (g)') or 0) / 1e6
            o['discard_t'] += (x.get('Fargað: Lífmassi (kg)') or 0) / 1000
        out['national'] = [{k: (round(v) if isinstance(v, float) else v) for k, v in o.items()} for _, o in sorted(nat.items())]
        out['meta']['species_seen'] = species

    # ---- site by site, month by month ----
    r = find('cage_report')
    if r:
        cols = r.tables['cage_report']
        sums = [c for c in ('Count_Closing', 'InputCount_InPeriod', 'HarvestCountDiscards_InPeriod', 'MortalityCount_InPeriod', 'BiomassKg_Closing') if c in cols]
        rows = r.query('cage_report', ['Lok tímabils', 'Fyrirtæki', 'Svæði', 'Tegund'], sums)
        print('sites:', len(rows), 'rows')
        fj = {}
        rf = find('license_sites_timeseries')
        if rf:
            try:
                for x in rf.query('license_sites_timeseries', ['Eldissvæði', 'Fjörður'], []):
                    if x['Eldissvæði']:
                        fj[x['Eldissvæði']] = x['Fjörður']
            except Exception as ex:
                print('fjords not read:', ex)
        S = {}
        for x in rows:
            if not is_salmon(x['Tegund']) or x['Lok tímabils'] is None or not x['Svæði']:
                continue
            m = month(x['Lok tímabils'])
            k = (x['Svæði'], m)
            o = S.setdefault(k, {'site': x['Svæði'], 'm': m, 'co': x['Fyrirtæki'], 'fjord': fj.get(x['Svæði']), 'fish': 0, 'in': 0, 'out': 0, 'dead': 0, 'bio_t': 0})
            o['fish'] += x.get('Count_Closing') or 0
            o['in'] += x.get('InputCount_InPeriod') or 0
            o['out'] += x.get('HarvestCountDiscards_InPeriod') or 0
            o['dead'] += x.get('MortalityCount_InPeriod') or 0
            o['bio_t'] += (x.get('BiomassKg_Closing') or 0) / 1000
        site_rows = sorted(S.values(), key=lambda o: (o['site'], o['m']))
        done, active = cycles(site_rows)
        last = max(o['m'] for o in site_rows)
        out['sites_last_month'] = last
        out['sites'] = [{**o, 'bio_t': round(o['bio_t']), 'fish': round(o['fish']), 'in': round(o['in']), 'out': round(o['out']), 'dead': round(o['dead'])}
                        for o in site_rows if o['m'] >= add_months(last, -36)]
        out['cycles'] = {'done': done, 'active': active, 'note': 'a cycle runs from the first month with fish after at least two empty months to the last month with fish'}
        L = [c['months'] for c in done]
        out['cycles']['iceland'] = summary(L)
        out['cycles']['by_company'] = {co: summary([c['months'] for c in done if c['co'] == co]) for co in sorted({c['co'] for c in done})}
        out['cycles']['by_fjord'] = {f: summary([c['months'] for c in done if c['fjord'] == f]) for f in sorted({c['fjord'] for c in done if c['fjord']})}
        print('cycles:', out['cycles']['iceland'], 'by company:', out['cycles']['by_company'])
        print('active sites:', len(active))

    if len(out) == 1:
        print('Nothing read from MAST: previous file kept.'); return 1
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('data/iceland_mast.json written')
    return 0


if __name__ == '__main__':
    sys.exit(main())
