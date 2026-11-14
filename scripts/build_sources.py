#!/usr/bin/env python3
"""
Inventaire de TOUT ce que le tableau de bord collecte, range par bassin -> data/sources.json
(panneau « Updated » en haut a droite de docs/production.html).

    python3 scripts/build_sources.py

Pour chaque source : ce qu'on collecte, d'ou, a quel rythme, jusqu'ou vont les donnees (lu dans les fichiers),
quand le fichier a ete rafraichi pour la derniere fois, et le resultat du dernier passage de la collecte.

  to         derniere periode presente dans les donnees (lue dans le fichier, pas une date de calendrier)
  collected  date du dernier changement du fichier : date ecrite par le script dans le fichier, sinon date du dernier
             commit du fichier (API GitHub, si GITHUB_TOKEN est la)
  run        dernier passage du workflow qui collecte la source : date et resultat (API GitHub, si GITHUB_TOKEN est la)
  flag       ok | late (la collecte n'a pas tourne depuis plus de `max` jours) | failed (dernier passage en echec) | manual (tenu a la main)
             Un fichier inchange n'est pas un retard : la collecte a tourne, la source n'a rien publie de nouveau.

Ajouter une source = ajouter une ligne a CATALOGUE ; un fichier de data/ qui n'est cite par aucune ligne
est signale dans meta.unlisted (pour que la liste reste exhaustive).
"""
import datetime as dt
import glob
import io
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DD = os.path.join(ROOT, 'data')
OUT = os.path.join(DD, 'sources.json')
REPO = os.environ.get('GITHUB_REPOSITORY', 'EmileviardotFO/saumon')
TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')

_cache = {}


def J(f):
    if f not in _cache:
        p = os.path.join(DD, f)
        try:
            _cache[f] = json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else None
        except Exception:
            _cache[f] = None
    return _cache[f]


MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def ym(k):
    """202609, '2026-09', '202609' -> 'Sep 2026'"""
    if k is None:
        return None
    s = re.sub(r'\D', '', str(k))[:6]
    if len(s) < 6:
        return None
    return f"{MON[int(s[4:6]) - 1]} {s[:4]}"


def wk(y, w):
    return f"W{int(w)} {int(y)}"


def day(s):
    return str(s)[:10] if s else None


def meta(f, *keys):
    j = J(f) or {}
    m = j.get('meta') if isinstance(j.get('meta'), dict) else j.get('_meta') if isinstance(j.get('_meta'), dict) else j
    for k in keys:
        if isinstance(m, dict) and m.get(k) not in (None, ''):
            return m[k]
    return None


D = lambda: J('data.json') or {}


def t_biomass():
    r = D().get('records') or []
    return ym(max(x['year'] * 100 + x['month'] for x in r)) if r else None


def t_akva_week():
    w = D().get('weekly') or []
    k = max((x['report_year'], x['report_week']) for x in w) if w else None
    return wk(*k) if k else None


def t_akva_month():
    m = [x for x in (D().get('monthly_akvafakta') or []) if x.get('price_nok_kg')]
    return ym(max(x['year'] * 100 + x['month'] for x in m)) if m else None


def t_ssb():
    ks = list(((D().get('ssb_exports') or {}).get('meta') or {}).get('months') or {})
    return ym(max(ks)) if ks else None


def t_ssb_week():
    l = ((D().get('ssb_weekly') or {}).get('meta') or {}).get('last')
    return wk(l // 100, l % 100) if l else None


def t_ssb_copro():
    r = (D().get('ssb_coproducts') or {}).get('rows') or []
    try:
        return ym(max(x[0] if isinstance(x, list) else x.get('k') for x in r))
    except Exception:
        return None


def t_bw():
    l = ((D().get('bw_weekly') or {}).get('meta') or {}).get('last')
    return wk(l[0], l[1]) if l else None


def t_wb():
    l = meta('wellboats.json', 'last_full_week')
    return wk(l // 100, l % 100) if l else None


def t_nat(c):
    return lambda: ym((((D().get('status') or {}).get('national') or {}).get(c) or {}).get('last'))


def t_rows(f):
    def g():
        l = meta(f, 'last', 'last_period')
        if l:
            return ym(l)
        r = (J(f) or {}).get('rows') or []
        try:
            return ym(max(x[0] for x in r))
        except Exception:
            return None
    return g


def t_meta(f, *keys, fmt=ym):
    return lambda: fmt(meta(f, *keys))


def t_hfs():
    w = meta('faroe_hfs.json', 'last_week')
    return ('W' + w[6:] + ' ' + w[:4]) if w else None


def t_faroe():
    d = meta('faroe.json', 'dates')
    return ym(d[-1]) if d else None


def t_cl_wb():
    return day(meta('chile_wellboats.json', 'last'))


def t_cl_cycles():
    p = meta('chile_cycles.json', 'periods')
    return p[-1] if p else None


def t_sc_week():
    return day(meta('scotland_weekly.json', 'last_week'))


def t_au_m():
    return ym(meta('australia.json', 'last_month'))


def t_au_p():
    f = meta('australia.json', 'last_fy')
    return ('FY' + f) if f else None


def t_ca_lice():
    return ym(meta('canada.json', 'lice_last'))


def t_stories():
    return day(meta('stories.json', 'to'))


def t_keys(f, k):
    return lambda: ym(max((J(f) or {}).get(k) or {}))


def t_chl():
    return max(p['last'] for p in J('chlorophyll.json')['points'] if p.get('last'))


def t_sst():
    return max(p['last_day'] for p in J('sea_temp.json')['points'] if p.get('last_day'))


def t_world():
    return ym(max(r[0] for r in J('world_imports.json')['rows']))


def t_quarterly():
    return max(r['quarter'] for r in J('quarterly.json')['reports']).replace('-', ' ')


def t_caligus():
    v = J('chile_caligus.json')['versions'][-1]['version']
    return f"{v[:4]}-{v[4:6]}-{v[6:]}"


def t_cl_sub():
    i = meta('chile_subpesca.json', 'last_id')
    return f"res. {i}" if i else None


# rythme -> (libelle affiche, age maximal en jours du fichier avant d'etre signale en retard)
DAILY, TWICE, WEEKLY, MONTHLY, FOURW, HAND, STATIC = ('daily', 3), ('twice a week', 6), ('weekly', 10), ('daily', 3), ('twice a week', 6), ('by hand', None), ('once', None)

# (bassin, ce qu'on collecte, source, rythme, fichiers de data/, cle de data.json ou None, workflow, lecture de la derniere periode, publication de la source)
C = []


def add(basin, what, source, cad, files, wf, to=None, pub='', key=None):
    C.append(dict(basin=basin, what=what, source=source, cad=cad, files=files if isinstance(files, list) else [files], wf=wf, to=to, pub=pub, key=key))


NO, CL, GB, FO, IS, CA, AU, MK, OC, NW = 'Norway', 'Chile', 'Scotland', 'Faroe Islands', 'Iceland', 'Canada', 'Australia', 'Markets & trade', 'Ocean & climate', 'News & companies'

# ---------------- Norvege
add(NO, 'Biomass register: fish numbers, weight, biomass, harvest, losses, smolts — by production zone and generation', 'Fiskeridirektoratet, Biomasseregisteret', MONTHLY, 'data.json', 'maj-norvege-mensuel', t_biomass, 'around the 20th for the previous month', 'records')
add(NO, 'Weekly export volumes, prices and size split of the spot panel', 'Sjømat Norge, Akvafakta weekly report', TWICE, 'data.json', 'maj-marches', t_akva_week, 'Wednesday for the previous week', 'weekly')
add(NO, 'Monthly stock by generation, feed, markets and prices', 'Sjømat Norge, Akvafakta monthly report', TWICE, 'data.json', 'maj-marches', t_akva_month, 'second half of the following month', 'monthly_akvafakta')
add(NO, 'Exports by country and product (fresh whole, fillets, frozen)', 'SSB, Statistikkbanken', MONTHLY, 'data.json', 'maj-norvege-mensuel', t_ssb, 'around the 15th for the previous month', 'ssb_exports')
add(NO, 'Weekly exports of whole salmon: tonnes and price', 'SSB, weekly salmon exports', TWICE, 'data.json', 'maj-marches', t_ssb_week, 'Wednesday for the previous week', 'ssb_weekly')
add(NO, 'Exports of co-products (frozen heads, frames, offal)', 'SSB, table 08799', MONTHLY, 'data.json', 'maj-norvege-mensuel', t_ssb_copro, 'monthly', 'ssb_coproducts')
add(NO, 'Fish health by site and week: sea lice, temperature, diseases (PD, ISA), treatments, fallow status', 'BarentsWatch, Fiskehelse API', TWICE, ['data.json', 'bw_site_lice.json', 'bw_disease_sites.json', 'bw_treatments.json', 'bw_site_status.json', 'bw_farm_state.json'], 'maj-barentswatch', t_bw, 'weekly, Tuesday', 'bw_weekly')
add(NO, 'Site register and history: licences, MTB, operators, positions', 'BarentsWatch + Fiskeridirektoratet (Akvakulturregisteret)', FOURW, ['bw_sites.json', 'bw_localities.json', 'data.json'], 'maj-barentswatch', lambda: day(meta('bw_sites.json', 'cycle_started')), 'register, re-read over a 4-week cycle', 'bw_register')
add(NO, 'Wellboat and harvest-vessel visits at farms (harvest pulse, smolt deliveries)', 'BarentsWatch, vessel visits (AIS, Kystverket)', DAILY, ['wellboats.json', 'wellboats_hist.json', 'harvest_pulse_log.json'], 'maj-wellboats', t_wb, 'daily')
add(NO, 'Live wellboat positions in the salmon regions (all basins)', 'aisstream.io (free AIS feed)', ('every 2 hours', 2), ['ais/vessels.json'], 'collecte-ais', None, 'continuous')
add(NO, 'Vessels approved to carry live fish', 'Mattilsynet, approved transport units', ('every 2 hours', None), 'wellboats_no.json', 'collecte-ais', None, 'register')
add(NO, 'Approved slaughterhouses and processing plants', 'Mattilsynet, fishery establishments', TWICE, ['data.json', 'plants.json', 'plants_geo.json'], 'maj-international', lambda: day(((D().get('establishments') or {}).get('meta') or {}).get('fetched')), 'register', 'establishments')
add(NO, 'Norwegian plants registered for export to China', 'GACC (China customs), CIFER register', TWICE, ['data.json', 'china_history.json'], 'maj-international', lambda: day(((D().get('china') or {}).get('meta') or {}).get('fetched')), 'register, fragile source', 'china')
add(NO, 'Slaughter by quality class (superior, ordinary, production, rejects); MTB ceiling by company; weekly site activity', 'Mattilsynet (quality dashboard) + Fiskeridirektoratet (licence register)', WEEKLY, 'no_extra.json', 'maj-sources-nouvelles', None, 'quarterly (quality), register')
add(NO, 'Annual accounts of privately held farmers', 'Brønnøysundregistrene (public API)', TWICE, 'private_accounts.json', 'maj-international', None, 'yearly, as accounts are filed')
add(NO, 'Harmful algae status by production zone', 'Havforskningsinstituttet, algestatus.hi.no', DAILY, 'algae_watch.json', 'maj-algues', None, 'weekly bulletin + episode reports')
add(NO, 'Post-smolt strategy by farmer (smolt size statements)', 'Company statements, Nofima survey', HAND, 'postsmolt.json', None, None)

# ---------------- Chili
add(CL, 'Export declarations: tonnes, value, product, destination, exporter group', 'Servicio Nacional de Aduanas (DUS, datos.gob.cl)', WEEKLY, ['chile_customs.json', 'chile_customs_cache.json', 'douanes_config.json'], 'maj-chili', t_rows('chile_customs.json'), 'monthly')
add(CL, 'Regional harvest and plant output: Los Lagos, Aysén, Magallanes', 'Sernapesca figures via INE regional bulletins', WEEKLY, 'chile_regional.json', 'maj-chili', t_keys('chile_regional.json', 'los_lagos'), 'monthly (Aysén quarterly)')
add(CL, 'Sea lice: high-dissemination centres (CAD)', 'Sernapesca, PSEVC-Caligidosis', WEEKLY, 'chile_caligus.json', 'maj-chili', t_caligus, 'weekly list')
add(CL, 'Fish authorised to stock by farm (density resolutions) and monthly sector reports', 'Subpesca, resolutions and informes sectoriales', DAILY, ['chile_subpesca.json', 'chile_subpesca_manual.json'], 'chili-subpesca', t_cl_sub, 'as resolutions are signed')
add(CL, 'Concessions map: sites, holders, status', 'Subpesca, public geoportal (IDE)', TWICE, 'chile_sites.json', 'maj-international', None, 'register')
add(CL, 'Finished cycles by farm: harvest, mortality, treatments', 'Sernapesca, transparency files of law 21.532', WEEKLY, 'chile_cycles.json', 'maj-sources-nouvelles', t_cl_cycles, 'half-yearly')
add(CL, 'Wellboat port visits (harvest activity by region)', 'Global Fishing Watch API (AIS)', WEEKLY, ['chile_wellboats.json', 'chile_wellboats_raw.json'], 'maj-chili-wellboats', t_cl_wb, 'about 5 days behind')
add(CL, 'Plants authorised to slaughter and process salmonids', 'Sernapesca, listado de plantas autorizadas', TWICE, 'plants.json', 'maj-international', lambda: meta('plants.json', 'cl_edition'), 'monthly edition')
add(CL, 'Plant coordinates', 'RETC, Ministerio del Medio Ambiente', STATIC, 'plants_cl_exact.json', None, None)
add(CL, 'Mortality notices (algal blooms, oxygen) and bloom conditions (rain, sun, wind)', 'Sernapesca press notices + NASA POWER', DAILY, 'algae_watch.json', 'maj-algues', None, 'as published')
add(CL, 'Exports by destination (cross-check)', 'UN Comtrade, reported by Chile', TWICE, 'national_trade.json', 'maj-international', t_nat('CL'), 'irregular, 2–3 months behind')
add(CL, 'Biomass, fish numbers and harvest weight quoted by analysts and farmers (fit points of our biomass estimate)', 'Pareto, RaboResearch, company reports, via InfoSalmon, Aqua.cl, Salmonexpert', HAND, 'chile_anchors.json', None, None)
add(CL, 'Average harvest weight by company and quarter', 'Company reports (CMF filings, trading updates)', HAND, 'chile_harvest_weights.json', None, None)
add(CL, 'Annual production, health and mortality by region (starter dataset)', 'Sernapesca, Subpesca yearbooks', HAND, 'chili.json', None, None)

# ---------------- Ecosse
add(GB, 'Biomass, mortality, feed and treatments by site and month', "SEPA, monthly reports (Scotland's Aquaculture)", TWICE, 'scotland.json', 'maj-international', t_meta('scotland.json', 'last'), 'monthly, with a long delay')
add(GB, 'Sea lice counts by site and week', "Scottish Government (Scotland's Aquaculture)", WEEKLY, 'scotland_weekly.json', 'maj-sources-nouvelles', t_sc_week, 'weekly')
add(GB, 'Monthly mortality rate by farm, with cause', 'Salmon Scotland, monthly mortality reports', WEEKLY, 'scotland_mortality.json', 'maj-sources-nouvelles', t_meta('scotland_weekly.json', 'mort_last'), 'about a month in arrears')
add(GB, 'Movement restrictions, escapes, site register by operator', 'Marine Directorate, Fish Health Inspectorate', TWICE, 'scotland_extra.json', 'maj-international', None, 'as recorded')
add(GB, 'Reported mortality events by site, with cause', 'Fish Health Inspectorate, monthly spreadsheet', ('twice a day', 3), 'events.json', 'maj-actualite', None, 'monthly')
add(GB, 'Annual production survey: tonnes, smolts, survival, staff', 'Marine Directorate, Scottish Fish Farm Production Survey', HAND, 'scotland_survey.json', None, lambda: meta('scotland_survey.json', 'published'), 'yearly, September')
add(GB, 'Quarterly harvest of Mowi Scotland, Bakkafrost Scotland, Scottish Sea Farms', 'Company quarterly reports', HAND, 'scotland_companies.json', None, None)
add(GB, 'Exports by destination', 'HMRC overseas trade statistics', TWICE, 'national_trade.json', 'maj-international', t_nat('GB'), 'monthly, about 6 weeks behind')

# ---------------- Feroe
add(FO, 'Fish by site at month end, sea lice counts, treatments, weekly harvest by size', 'HFS (Heilsufrøðiliga Starvsstovan), Aling > Hagtøl', WEEKLY, 'faroe_hfs.json', 'maj-feroe-hfs', t_hfs, 'weekly / monthly')
add(FO, 'Bakkafrost fish per farm, harvest and smolts; licence register', 'Bakkafrost sustainability data + Landsverk', TWICE, 'faroe.json', 'maj-international', t_faroe, 'monthly')
add(FO, 'Exports by product and destination', 'Hagstova Føroya, table UH01046', TWICE, 'national_trade.json', 'maj-international', t_nat('FO'), 'monthly, about 6 weeks behind')
add(FO, 'Bakkafrost quarterly figures (harvest, weight, smolts)', 'Bakkafrost quarterly reports', HAND, 'big_six_manual.json', None, None)

# ---------------- Islande
add(IS, 'Biomass, fish numbers, mortality, harvest by site and month; cycles', 'MAST, Mælaborð fiskeldis (public dashboard)', DAILY, 'iceland_mast.json', 'maj-norvege-mensuel', lambda: ym(meta('iceland_outlook.json', 'last')), 'monthly')
add(IS, 'Farm sites, sea areas, licences and applications (map layers)', 'MAST, public map server', TWICE, 'iceland.json', 'maj-international', None, 'register')
add(IS, 'Exports by product and destination', 'Statistics Iceland, table UTA02801', TWICE, 'national_trade.json', 'maj-international', t_nat('IS'), 'monthly, about 4 weeks behind')

# ---------------- Canada
add(CA, 'British Columbia: sea lice counts, mortality events, fish transfers by farm', 'DFO Pacific, public reporting', TWICE, 'canada.json', 'maj-international', t_ca_lice, 'quarterly batches')
add(CA, 'British Columbia: licences, production status and carcasses by facility, lice mitigation, health events', 'DFO Pacific, public reporting', WEEKLY, 'canada_bc.json', 'maj-sources-nouvelles', t_meta('canada_bc.json', 'last'), 'quarterly batches')
add(CA, 'Atlantic coast: sites, leases, stocking, ISA, escapes, production (NB, NS, NL)', 'Provincial governments + DFO', TWICE, 'canada_atl.json', 'maj-international', None, 'irregular')
add(CA, 'Shipments to the US by border post (west / east coast split)', 'US Census, imports by port', TWICE, 'canada_extra.json', 'maj-international', None, 'monthly')
add(CA, 'Exports by province, product and destination', 'Statistics Canada, CIMT', TWICE, 'canada_trade.json', 'maj-canada-commerce', t_rows('canada_trade.json'), 'monthly, about 5 weeks behind')
add(CA, 'Exports by destination (cross-check)', 'UN Comtrade, reported by Canada', TWICE, 'national_trade.json', 'maj-international', t_nat('CA'), 'irregular, 2–3 months behind')

# ---------------- Australie
add(AU, 'Tasmania: salmon mortalities by month and disposal method', 'EPA Tasmania', TWICE, 'australia.json', 'maj-international', t_au_m, 'quarterly, about 3 weeks after the quarter')
add(AU, 'Tasmania: production by company, leases', 'NRE Tasmania, salmon farming portal', TWICE, 'australia.json', 'maj-international', t_au_p, 'yearly (financial year)')
add(AU, 'Exports by destination', 'UN Comtrade, reported by Australia', TWICE, 'national_trade.json', 'maj-international', t_nat('AU'), 'irregular, 2–3 months behind')

# ---------------- Marches
add(MK, 'EU salmon trade flows by product and country', 'Eurostat, Comext DS-045409', TWICE, 'eurostat.json', 'maj-international', t_rows('eurostat.json'), 'monthly, 6–8 weeks behind')
add(MK, 'US imports by product and origin', 'US Census Bureau, trade API', TWICE, 'us_imports.json', 'maj-international', t_rows('us_imports.json'), 'monthly, about 5 weeks behind')
add(MK, 'Japan imports of salmon and trout by form and origin', 'UN Comtrade, reported by Japan', TWICE, 'japan_imports.json', 'maj-international', t_rows('japan_imports.json'), 'monthly, 2–3 months behind')
add(MK, 'China and Hong Kong imports by origin', 'UN Comtrade, reported by China and Hong Kong', TWICE, 'cn_imports.json', 'maj-international', t_rows('cn_imports.json'), 'monthly, 2–4 months behind')
add(MK, 'World imports by importing country and product', 'UN Comtrade (HS6, monthly)', TWICE, 'world_imports.json', 'maj-international', t_world, 'monthly, uneven by country')
add(MK, 'Swiss imports by tariff line and origin', 'Swiss customs (FOCBS), open data', WEEKLY, 'swiss_imports.json', 'maj-suisse', t_rows('swiss_imports.json'), 'monthly')
add(MK, 'Feed raw-material prices: fish meal, soy, rapeseed, wheat, oils, energy', 'World Bank, commodity price data (Pink Sheet)', DAILY, 'feed.json', 'maj-norvege-mensuel', lambda: ym(J('feed.json')['prices']['months'][-1]), 'monthly, early in the month')
add(MK, 'World feed market, marine ingredients, Peru anchovy quota', 'IFFO, company and ministry releases', HAND, 'feed_manual.json', None, None)
add(MK, 'Industry supply by region (analyst comparison only)', 'Kontali figures quoted in Mowi reports', HAND, 'global_supply.json', None, None)

# ---------------- Ocean
add(OC, 'Sea surface temperature by farming area, all basins; ENSO index', 'NOAA OISST v2.1 (daily)', DAILY, ['sea_temp.json', 'coast_hd.json'], 'maj-temperature-mer', t_sst, 'daily, 1–2 days behind')
add(OC, 'Chlorophyll-a from satellite (algal bloom alert)', 'NOAA CoastWatch, VIIRS ocean colour', DAILY, 'chlorophyll.json', 'maj-chlorophylle', t_chl, 'daily')
add(OC, 'Climate and sea-temperature news by basin', 'Institutes and press', HAND, 'climate_news.json', None, None)

# ---------------- Actualite
add(NW, 'Headlines of the week, all basins', 'iLaks, Kyst.no, Fish Farming Expert, Salmonexpert.cl, The Fish Site, Undercurrent, Mundo Acuícola, Google News', ('twice a day', 2), ['news.json', 'news_archive.json', 'news_links.json', 'stories.json'], 'maj-actualite', t_stories, 'continuous')
add(NW, 'Mortality events watch (algae, jellyfish, disease, oxygen, storms)', 'Trade press + Google News by basin and language', ('twice a day', 2), 'events.json', 'maj-actualite', None, 'continuous')
add(NW, 'Quarterly reports: harvest, cost per kg, EBIT, guidance', "Farmers' own releases (GlobeNewswire, Cision, NewsWeb, company sites)", ('twice a day', 2), 'quarterly.json', 'maj-actualite', t_quarterly, 'at each results date')
add(NW, 'Disease research and news (lice, gill disease, PD, ISA, SRS, jellyfish…)', 'Europe PMC, OpenAlex (open access), Google News', DAILY, 'disease_research.json', 'maj-maladies', None, 'continuous')
add(NW, 'Disease evidence cards and figures by basin', 'Open-access papers, institute and company reports', HAND, ['disease_knowledge.json', 'disease_manual.json'], None, None)
add(NW, 'Pinned topics, agenda, quarterly figures of the listed farmers', 'Company calendars and reports', HAND, ['watch.json', 'summary_manual.json', 'big_six_manual.json'], None, None)

# fichiers de data/ fabriques a partir des precedents (modeles, archives, index) : pas des collectes
DERIVED = {'sources.json', 'site_alerts.json', 'chile_market.json', 'summary.json', 'big_six.json', 'basin_cards.json', 'big_fish.json', 'big_fish_archive.json', 'forecast_archive.json', 'gen_outlook.json', 'generations.json',
           'generations_archive.json', 'six_stock.json', 'register_brief.json', 'iceland_outlook.json', 'own_supply.json', 'search_index.json', 'smoke.json'}
DATA_KEYS_DERIVED = {'meta', 'status', 'cohort', 'country'}   # cohort et country viennent du registre et d'Akvafakta


def api(path):
    if not TOKEN:
        return None
    try:
        rq = urllib.request.Request(f'https://api.github.com/repos/{REPO}/{path}', headers={'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'salmon-outlook'})
        return json.load(urllib.request.urlopen(rq, timeout=30))
    except Exception as e:
        print('  API', path[:70], '->', str(e)[:80])
        return None


def collected(f):
    """date du dernier rafraichissement du fichier : date ecrite dedans, sinon dernier commit"""
    for k in ('generated', 'built', 'fetched', 'probed', 'updated', 'written'):
        v = meta(f, k)
        if v:
            return day(v)
    j = api(f'commits?path=data/{f}&per_page=1')
    if j:
        return day(j[0]['commit']['committer']['date'])
    return None


def main():
    today = dt.date.today()
    prev = J('sources.json') or {}
    prev_run = {s['wf']: s.get('run') for b in prev.get('basins', []) for s in b['sources'] if s.get('wf') and s.get('run')}
    prev_col = {(s['what']): s.get('collected') for b in prev.get('basins', []) for s in b['sources']}
    runs = {}
    for wf in sorted({c['wf'] for c in C if c['wf']}):
        j = api(f'actions/workflows/{wf}.yml/runs?per_page=1&status=completed')
        r = (j or {}).get('workflow_runs') or []
        runs[wf] = {'date': day(r[0]['created_at']), 'ok': r[0]['conclusion'] == 'success', 'url': r[0]['html_url']} if r else prev_run.get(wf)
    basins, order = {}, []
    listed = set()
    for c in C:
        listed.update(c['files'])
        to = None
        if c['to']:
            try:
                to = c['to']()
            except Exception as e:
                print('  to', c['what'][:40], '->', e)
        if c['key']:
            col = day((D().get('meta') or {}).get('generated'))
        else:
            ds = [collected(f) for f in c['files'][:2]]
            col = max([d for d in ds if d], default=None) or prev_col.get(c['what'])
        run = runs.get(c['wf']) if c['wf'] else None
        mx = c['cad'][1]
        age = (today - dt.date.fromisoformat(run['date'])).days if run and run.get('date') else None
        flag = 'manual' if not c['wf'] else 'failed' if run and not run['ok'] else 'late' if (mx and age is not None and age > mx) else 'ok'
        if c['basin'] not in basins:
            basins[c['basin']] = []
            order.append(c['basin'])
        basins[c['basin']].append({'what': c['what'], 'source': c['source'], 'cadence': c['cad'][0], 'pub': c['pub'], 'to': to, 'collected': col, 'wf': c['wf'], 'run': run, 'flag': flag,
                                   'files': c['files'], **({'key': c['key']} if c['key'] else {})})
    have = {os.path.relpath(p, DD) for p in glob.glob(os.path.join(DD, '*.json'))}
    unlisted = sorted(have - listed - DERIVED)
    dkeys = sorted(set(D().keys()) - {c['key'] for c in C if c['key']} - DATA_KEYS_DERIVED)
    n = sum(len(v) for v in basins.values())
    cnt = lambda f: sum(1 for v in basins.values() for s in v if s['flag'] == f)
    out = {'meta': {'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M+00:00'), 'n': n, 'ok': cnt('ok'), 'late': cnt('late'), 'failed': cnt('failed'), 'manual': cnt('manual'),
                    'runs_checked': bool(TOKEN), 'unlisted': unlisted + ['data.json:' + k for k in dkeys],
                    'derived': sorted(DERIVED & have),
                    'note': 'to = last period present in the data; collected = last time the file changed; run = last run of the collection; late = the collection has not run within its usual rhythm; failed = its last run failed.'},
           'basins': [{'name': b, 'sources': basins[b]} for b in order]}
    # rapprochement avec les bulles du calendrier de publication (sourceStatus() de la page) : debut du nom de la bulle
    SS = [('Biomass register', 'Biomasseregisteret'), ('Weekly export volumes', 'Akvafakta weekly'), ('Monthly stock by generation', 'Akvafakta monthly'), ('Exports by country and product', 'SSB exports'),
          ('Weekly exports of whole salmon', 'SSB weekly'), ('Fish health by site and week', 'BarentsWatch fish health'), ('Site register and history', 'BarentsWatch site register'),
          ('EU salmon trade', 'Eurostat'), ('US imports', 'US Census'), ('Norwegian plants registered', 'GACC'), ('Approved slaughterhouses', 'Mattilsynet'),
          ('Tasmania: salmon mortalities', 'Australia — EPA'), ('Tasmania: production', 'Australia — NRE'), ('British Columbia: sea lice', 'Canada BC — DFO sea lice')]
    NAT = {'Faroe Islands': 'Faroe export', 'Iceland': 'Iceland export', 'Scotland': 'UK export', 'Chile': 'Chile export', 'Canada': 'Canada export'}
    for b in out['basins']:
        for x in b['sources']:
            m = next((v for k, v in SS if x['what'].startswith(k)), None)
            if not m and x['files'] == ['national_trade.json']:
                m = NAT.get(b['name'])
            if m:
                x['ss'] = m
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"sources.json : {n} sources, {len(order)} bassins — ok {out['meta']['ok']}, en retard {out['meta']['late']}, en echec {out['meta']['failed']}, a la main {out['meta']['manual']}"
          + (f" ; NON LISTES : {out['meta']['unlisted']}" if out['meta']['unlisted'] else ''))


if __name__ == '__main__':
    main()
