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
    import requests          # Power BI refuses urllib's default request (no compression, bare headers)
    h = dict(UA, **(headers or {}))
    r = requests.post(url, json=data, headers=h, timeout=timeout) if data is not None else requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()


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
            except Exception as ex:
                self.err = f'{host}: {type(ex).__name__} {str(ex)[:160]}'
                continue
        if not self.mx:
            raise RuntimeError('no Power BI cluster answered; last error ' + getattr(self, 'err', ''))
        m = self.mx['models'][0]
        self.model_id, self.db = m['id'], m['dbName']
        self.report_id = (self.mx.get('exploration', {}).get('report') or {}).get('objectId')
        sch = http(f'{self.host}/public/reports/conceptualschema', {'modelIds': [self.model_id], 'userPreferredLocale': 'en-US'}, self.h)
        self.tables = {e['Name']: [p['Name'] for p in e.get('Properties', [])] for e in sch['schemas'][0]['schema']['Entities']}

    def query(self, table, groups, sums, where=None, count=30000, fn=0):
        """Rows of `groups` columns with the sum (fn=0) or average (fn=1) of each `sums` column, as a list of dicts."""
        src = {'SourceRef': {'Source': 't'}}
        sel = [{'Column': {'Expression': src, 'Property': g}, 'Name': f't.{g}'} for g in groups] + \
              [{'Aggregation': {'Expression': {'Column': {'Expression': src, 'Property': s}}, 'Function': fn}, 'Name': f'Sum(t.{s})'} for s in sums]
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


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def month(v):
    """Power BI dates come back as epoch milliseconds (or ISO text)."""
    if isinstance(v, (int, float)):
        d = dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=v)
    else:
        d = dt.datetime.fromisoformat(str(v)[:19])
    return f'{d.year}-{d.month:02d}'


# MAST lists the operating company of each site; the same group appears under several names
GROUP = [(r'(?i)^arnarlax', 'Arnarlax (Icelandic Salmon)'), (r'(?i)^(kaldv[ií]k|ice fish farm)', 'Kaldvík'), (r'(?i)^arctic', 'Arctic Fish'),
         (r'(?i)^h[áa]afell', 'Háafell'), (r'(?i)^laxar', 'Laxar')]


def group(co):
    for rx, g in GROUP:
        if re.match(rx, co or ''):
            return g
    return co


MIN_CYCLE = 8      # months: shorter runs are fish moved between sites or emptied early (ISA in 2021-22), not full cycles


def cycles(site_rows):
    """Production cycles from monthly fish counts of each site: first month with fish after >= 2 empty months -> last month with fish."""
    last_all = max(r['m'] for r in site_rows)
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
        if start is not None and allm[-1] == last_all:
            active.append({'site': site, 'co': L[-1]['co'], 'fjord': L[-1]['fjord'], 'start': start, 'age': months_between(start, allm[-1]) + 1,
                           'fish': fish.get(allm[-1], 0)})
    # a cycle that started before the first month of data is cut: its length is unknown
    first = min(r['m'] for r in site_rows)
    done = [c for c in done if c['start'] > first]
    short = [c for c in done if c['months'] < MIN_CYCLE]
    done = [c for c in done if c['months'] >= MIN_CYCLE]
    return done, active, short


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
            o['biomass_t'] += num(x.get('BiomassKg_Closing')) / 1000
            o['feed_t'] += num(x.get('FeedUseKg_InPeriod')) / 1000
            o['mortality_t'] += num(x.get('MortalityBiomass_InPeriod')) / 1000
            o['harvest_t'] += num(x.get('Slátrað: Lífmassi (g)')) / 1000   # labelled grams, but the values are kilograms
            o['discard_t'] += num(x.get('Fargað: Lífmassi (kg)')) / 1000
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
            o = S.setdefault(k, {'site': x['Svæði'], 'm': m, 'co': group(x['Fyrirtæki']), 'fjord': fj.get(x['Svæði']), 'fish': 0, 'in': 0, 'out': 0, 'dead': 0, 'bio_t': 0})
            o['fish'] += num(x.get('Count_Closing'))
            o['in'] += num(x.get('InputCount_InPeriod'))
            o['out'] += num(x.get('HarvestCountDiscards_InPeriod'))
            o['dead'] += num(x.get('MortalityCount_InPeriod'))
            o['bio_t'] += num(x.get('BiomassKg_Closing')) / 1000
        # biomass by site: the "fish numbers" report has no biomass column; another report's cage_report has it
        rb = next((x for x in reports if 'BiomassKg_Closing' in x.tables.get('cage_report', [])), None)
        if rb and 'BiomassKg_Closing' not in cols:
            try:
                nb = 0
                for x in rb.query('cage_report', ['Lok tímabils', 'Svæði', 'Tegund'], ['BiomassKg_Closing']):
                    if not is_salmon(x['Tegund']) or x['Lok tímabils'] is None or not x['Svæði']:
                        continue
                    o = S.get((x['Svæði'], month(x['Lok tímabils'])))
                    if o is not None:
                        o['bio_t'] += num(x.get('BiomassKg_Closing')) / 1000
                        nb += 1
                print('site biomass:', nb, 'site-months')
            except Exception as ex:
                print('site biomass not read:', ex)
        site_rows = sorted(S.values(), key=lambda o: (o['site'], o['m']))
        done, active, short = cycles(site_rows)
        last = max(o['m'] for o in site_rows)
        out['sites_last_month'] = last
        out['sites'] = [{**o, 'bio_t': round(o['bio_t']), 'fish': round(o['fish']), 'in': round(o['in']), 'out': round(o['out']), 'dead': round(o['dead'])}
                        for o in site_rows if o['m'] >= add_months(last, -36)]
        out['cycles'] = {'done': done, 'active': active, 'short_runs': len(short), 'min_months': MIN_CYCLE,
                         'note': f'a cycle runs from the first month with fish after at least two empty months to the last month with fish; '
                                 f'runs shorter than {MIN_CYCLE} months (fish moved between sites, early emptying) are left out'}
        L = [c['months'] for c in done]
        out['cycles']['iceland'] = summary(L)
        out['cycles']['by_company'] = {co: summary([c['months'] for c in done if c['co'] == co]) for co in sorted({c['co'] for c in done})}
        out['cycles']['by_fjord'] = {f: summary([c['months'] for c in done if c['fjord'] == f]) for f in sorted({c['fjord'] for c in done if c['fjord']})}
        print('cycles:', out['cycles']['iceland'], 'by company:', out['cycles']['by_company'])
        print('active sites:', len(active))

    # ---- sea temperature by site and month (average temperature of the period in the lice reports) ----
    r = next((x for x in reports if 'Lús: Meðalhiti á tímabili' in x.tables.get('cage_lice_report', [])), None)
    if r:
        try:
            rows = r.query('cage_lice_report', ['Lok tímabils', 'Svæði'], ['Lús: Meðalhiti á tímabili'], fn=1)
            T = {}
            for x in rows:
                v = x.get('Lús: Meðalhiti á tímabili')
                if x['Lok tímabils'] is None or not x['Svæði'] or v is None:
                    continue
                v = num(v)
                if not (-2 < v < 20):
                    continue
                T.setdefault((x['Svæði'], month(x['Lok tímabils'])), []).append(v)
            out['temp'] = [{'site': s_, 'm': m_, 't': round(sum(v) / len(v), 2)} for (s_, m_), v in sorted(T.items())]
            print('sea temperature:', len(out['temp']), 'site-months')
        except Exception as ex:
            print('sea temperature not read:', ex)

    # ---- annual production by species, farming type (sea / land) and region, from MAST's yearly reports ----
    r = find('aquaculture_from_old_reports')
    if r:
        try:
            rows = r.query('aquaculture_from_old_reports', ['Species', 'Eldi', 'Region', 'Year'], ['Amount'])
            out['annual'] = [{'species': x['Species'], 'type': x['Eldi'], 'region': x['Region'], 'year': int(num(x['Year'])) if x['Year'] is not None else None,
                              't': round(num(x.get('Amount')))} for x in rows if x.get('Year') is not None]
            print('annual production:', len(out['annual']), 'rows; types', sorted({str(x['type']) for x in out['annual']}), 'species', sorted({str(x['species']) for x in out['annual']}))
        except Exception as ex:
            print('annual production not read:', ex)

    if len(out) == 1:
        print('Nothing read from MAST: previous file kept.'); return 1
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('data/iceland_mast.json written')
    return 0


if __name__ == '__main__':
    sys.exit(main())
