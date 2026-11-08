#!/usr/bin/env python3
"""
Veille scientifique et presse par maladie du saumon d'elevage, sources gratuites :

  - Europe PMC (API REST, articles en acces libre, resume inclus)
  - OpenAlex (API, travaux en acces libre, y compris preprints et rapports)
  - Google News RSS (presse professionnelle en anglais, norvegien, espagnol), 60 derniers jours

Pour chaque article on garde la phrase du resume qui parle de mortalite, croissance, poids, cout ou survie (« ce qu'on
apprend »), sans resume automatique payant.

    python3 scripts/build_disease_research.py      -> data/disease_research.json
"""
import datetime as dt
import html
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'disease_research.json')
UA = {'User-Agent': 'Mozilla/5.0 (salmon-outlook disease watch; mailto:research@salmon-outlook.org)'}
JOURS = 400          # profondeur des publications
JOURS_PRESSE = 60
# id -> (requete Europe PMC sur titre/resume, requete OpenAlex, requetes presse [(texte, langue)])
DIS = {
    'lice': ('("sea lice" OR "salmon lice" OR "Lepeophtheirus salmonis" OR "Caligus rogercresseyi" OR delousing)', 'salmon lice Lepeophtheirus delousing',
             [('"sea lice" salmon farm', 'en'), ('lakselus avlusing', 'no'), ('caligus salmones', 'es')]),
    'pd': ('("pancreas disease" OR "salmonid alphavirus")', 'salmonid alphavirus pancreas disease',
           [('"pancreas disease" salmon', 'en'), ('pankreassykdom PD laks', 'no')]),
    'isa': ('("infectious salmon anaemia" OR "infectious salmon anemia" OR ISAV)', 'infectious salmon anaemia virus',
            [('"infectious salmon anaemia" OR "ISA outbreak" salmon', 'en'), ('ILA-utbrudd laks', 'no'), ('"virus ISA" salmones', 'es')]),
    'cms': ('("cardiomyopathy syndrome" OR "piscine myocarditis virus")', 'cardiomyopathy syndrome salmon piscine myocarditis',
            [('kardiomyopatisyndrom CMS laks', 'no'), ('"cardiomyopathy syndrome" salmon', 'en')]),
    'hsmi': ('("heart and skeletal muscle inflammation" OR "piscine orthoreovirus")', 'piscine orthoreovirus heart skeletal muscle inflammation salmon',
             [('HSMB laks', 'no'), ('"piscine orthoreovirus" salmon', 'en')]),
    'gill': ('("amoebic gill disease" OR "gill disease" OR "Paramoeba perurans" OR "Neoparamoeba perurans" OR "gill poxvirus") AND salmon', 'salmon gill disease amoebic',
             [('salmon "gill disease"', 'en'), ('gjellesykdom laks', 'no')]),
    'srs': ('(piscirickettsiosis OR "Piscirickettsia salmonis")', 'Piscirickettsia salmonis',
            [('SRS piscirickettsiosis salmon Chile', 'en'), ('SRS salmones Sernapesca', 'es')]),
    'bkd': ('("bacterial kidney disease" OR "Renibacterium salmoninarum")', 'Renibacterium salmoninarum bacterial kidney disease',
            [('"bacterial kidney disease" salmon', 'en'), ('BKD salmones', 'es')]),
    'ulcers': ('("Moritella viscosa" OR "winter ulcer" OR tenacibaculosis OR Tenacibaculum) AND salmon', 'Tenacibaculum Moritella salmon ulcer',
               [('tenacibaculosis OR "winter ulcer" salmon', 'en'), ('vintersår laks', 'no'), ('tenacibaculosis salmones', 'es')]),
    'hab': ('("harmful algal bloom" OR Pseudochattonella OR Heterosigma OR Chrysochromulina OR jellyfish) AND (salmon OR aquaculture)', 'harmful algal bloom salmon aquaculture mortality',
            [('algae bloom salmon farm mortality', 'en'), ('algeoppblomstring laks dødelighet', 'no'), ('floración algal salmones mortalidad', 'es')]),
    'pasteurellosis': ('(pasteurellosis OR "Pasteurella skyensis" OR "Pasteurella atlantica" OR Phocoenobacter OR "pilchard orthomyxovirus") ', 'pasteurellosis salmon Pasteurella',
                       [('pasteurellose laks', 'no'), ('Pasteurella salmon Scotland OR Tasmania', 'en')]),
    'nonin': ('("Salmo salar") AND (hypoxia OR "marine heatwave" OR "handling stress" OR "smolt quality" OR "thermal delousing" OR "mechanical delousing")', 'Atlantic salmon hypoxia heatwave smolt mortality',
              [('salmon mortality oxygen heat farm', 'en'), ('dødelighet laks oksygen', 'no')]),
}
# filtre de pertinence (titre + resume, ou titre de presse) : la recherche plein texte d'OpenAlex ramene des voisins
MUST = {
    'lice': r'lice|lus\b|lusen|Lepeophtheirus|Caligus|delous|avlus|piojo',
    'pd': r'pancrea|alphavirus|\bSAV\d?\b|\bPD\b|pankreas',
    'isa': r'infectious salmon an(a)?emia|\bISAV?\b|\bILA\b|lakseanemi|anemia infecciosa',
    'cms': r'cardiomyopath|myocarditis|PMCV|\bCMS\b|kardiomyopat|hjertesprekk',
    'hsmi': r'heart and skeletal|orthoreovirus|\bPRV|\bHSMI\b|\bHSMB\b|melanin',
    'gill': r'gill|gjelle|Paramoeba|AGD|branqui',
    'srs': r'Piscirickettsi|\bSRS\b|rickettsia',
    'bkd': r'kidney disease|Renibacterium|\bBKD\b|nyresyke',
    'ulcers': r'Moritella|ulcer|Tenacibacul|mouthrot|yellow mouth|vintersår|munnråte|úlcera',
    'hab': r'alga|bloom|Pseudochattonella|Heterosigma|Chrysochromulina|jellyfish|manet|floraci|\bFAN\b|plankton',
    'pasteurellosis': r'Pasteurell|Phocoenobacter|orthomyxovirus|POMV|Tasmania|Macquarie',
    'nonin': r'hypox|oxygen|oksygen|ox[ií]geno|heatwave|temperature|handling|smolt|delous|welfare|mortalit|dødelighet',
}
CLE = re.compile(r'mortalit|surviv|death|died|dead|growth|weight|harvest|feed conversion|FCR|cost|loss|economic|yield|downgrad|quality|prevalen|incidence|outbreak|efficac|protect|reduc', re.I)
NUM = re.compile(r'\d')


def get(url, timeout=60):
    last = None
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(8 * (i + 1))
    raise RuntimeError(f'{url[:120]}: {last}')


def propre(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def lecon(abstract):
    """La phrase du resume la plus parlante pour un analyste : mortalite / croissance / cout, de preference chiffree."""
    if not abstract: return ''
    ph = [p.strip() for p in re.split(r'(?<=[.!?])\s+(?=[A-Z])', abstract) if 40 < len(p.strip()) < 420]
    sc = []
    for i, p in enumerate(ph):
        s = len(CLE.findall(p)) * 2 + (2 if NUM.search(p) else 0) + (2 if re.match(r'(Our|These|The) (results|findings|study)|We (found|show|conclude)|In conclusion|Overall', p) else 0) + i / max(1, len(ph))
        sc.append((s, p))
    return max(sc)[1] if sc else ''


def epmc(q, depuis):
    query = f'TITLE_ABS:{q} AND (TITLE_ABS:salmon OR TITLE_ABS:"Salmo salar" OR TITLE_ABS:salmonid) AND OPEN_ACCESS:y AND FIRST_PDATE:[{depuis} TO 3000-01-01]'
    u = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urllib.parse.urlencode({'query': query, 'format': 'json', 'pageSize': 40, 'resultType': 'core'})
    out = []
    for r in json.loads(get(u))['resultList']['result']:
        doi = (r.get('doi') or '').lower()
        ab = propre(r.get('abstractText'))
        url = f'https://doi.org/{doi}' if doi else f'https://europepmc.org/article/{r.get("source")}/{r.get("id")}'
        for f in ((r.get('fullTextUrlList') or {}).get('fullTextUrl') or []):
            if f.get('availabilityCode') == 'OA' and f.get('documentStyle') in ('html', 'pdf'): url = f['url']; break
        out.append({'title': propre(r.get('title')), 'date': r.get('firstPublicationDate'), 'journal': (r.get('journalInfo') or {}).get('journal', {}).get('title') or r.get('bookOrReportDetails', {}).get('publisher') or r.get('source'),
                    'doi': doi, 'url': url, 'type': 'preprint' if r.get('source') == 'PPR' else 'paper', 'finding': lecon(ab), 'src': 'Europe PMC', '_ab': ab[:3000]})
    return out


def openalex(q, depuis):
    u = 'https://api.openalex.org/works?' + urllib.parse.urlencode({'search': q, 'filter': f'from_publication_date:{depuis},is_oa:true', 'per-page': 25, 'sort': 'publication_date:desc',
                                                                    'mailto': 'research@salmon-outlook.org'})
    out = []
    for r in json.loads(get(u))['results']:
        t = r.get('title') or ''
        if not re.search(r'salmon|salar|salmonid|aquacult|fish farm', t + ' ' + json.dumps(r.get('abstract_inverted_index') or {})[:3000], re.I): continue
        inv = r.get('abstract_inverted_index') or {}
        pos = sorted((p, w) for w, ps in inv.items() for p in ps)
        ab = ' '.join(w for _, w in pos)
        doi = (r.get('doi') or '').replace('https://doi.org/', '').lower()
        src = ((r.get('primary_location') or {}).get('source') or {}).get('display_name')
        out.append({'title': propre(t), 'date': r.get('publication_date'), 'journal': src, 'doi': doi,
                    'url': (r.get('open_access') or {}).get('oa_url') or (f'https://doi.org/{doi}' if doi else r.get('id')),
                    'type': 'preprint' if r.get('type') == 'preprint' or (src and re.search(r'rxiv', src, re.I)) else (r.get('type') or 'paper'), 'finding': lecon(ab), 'src': 'OpenAlex', '_ab': ab[:3000]})
    return out


def presse(q, lang):
    hl = {'en': ('en', 'US', 'US:en'), 'no': ('no', 'NO', 'NO:no'), 'es': ('es-419', 'CL', 'CL:es-419')}[lang]
    u = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': f'{q} when:{JOURS_PRESSE}d', 'hl': hl[0], 'gl': hl[1], 'ceid': hl[2]})
    x = get(u); out = []
    for it in re.findall(r'<item>(.*?)</item>', x, re.S):
        t = propre(re.search(r'<title>(.*?)</title>', it, re.S).group(1)); l = propre(re.search(r'<link>(.*?)</link>', it, re.S).group(1))
        d = re.search(r'<pubDate>(.*?)</pubDate>', it); s = re.search(r'<source[^>]*>(.*?)</source>', it, re.S)
        try: d = dt.datetime.strptime(d.group(1)[:25].strip(), '%a, %d %b %Y %H:%M:%S').date().isoformat()
        except Exception: d = ''  # noqa: BLE001
        src = propre(s.group(1)) if s else ''
        if src and t.endswith(' - ' + src): t = t[:-len(src) - 3]
        if re.search(r'facebook|instagram|tiktok|youtube|linkedin', src, re.I): continue
        out.append({'title': t, 'date': d, 'source': src, 'url': l, 'lang': lang})
    return out


def main():
    old = json.load(io.open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    depuis = (dt.date.today() - dt.timedelta(days=JOURS)).isoformat()
    res, err = {}, []
    for k, (qe, qo, qp) in DIS.items():
        pubs, news = {}, {}
        for f, q in ((epmc, qe), (openalex, qo)):
            try:
                for p in f(q, depuis):
                    key = p['doi'] or re.sub(r'\W+', '', p['title'].lower())[:80]
                    if key in pubs:
                        if not pubs[key]['finding'] and p['finding']: pubs[key]['finding'] = p['finding']
                        continue
                    pubs[key] = p
            except Exception as e:  # noqa: BLE001
                err.append(f'{k} {f.__name__}: {str(e)[:150]}')
            time.sleep(3)
        for q, lang in qp:
            try:
                for n in presse(q, lang):
                    key = re.sub(r'\W+', '', n['title'].lower())[:70]
                    if key not in news: news[key] = n
            except Exception as e:  # noqa: BLE001
                err.append(f'{k} presse {lang}: {str(e)[:150]}')
            time.sleep(1.5)
        mk = re.compile(MUST[k], re.I)
        pubs = {a: b for a, b in pubs.items() if mk.search(b['title'] + ' ' + (b.get('_ab') or '')) and not re.match(r'(correction|erratum|retraction|corrigendum)\b', b['title'], re.I)}
        news = {a: b for a, b in news.items() if mk.search(b['title'])}
        for b in pubs.values(): b.pop('_ab', None)
        P = sorted(pubs.values(), key=lambda p: p['date'] or '', reverse=True)[:30]
        N = sorted(news.values(), key=lambda n: n['date'] or '', reverse=True)[:20]
        if not P and k in (old.get('diseases') or {}): P = old['diseases'][k].get('papers', [])
        if not N and k in (old.get('diseases') or {}): N = old['diseases'][k].get('news', [])
        res[k] = {'papers': P, 'news': N}
        print(f'{k:15s} {len(P):3d} publications, {len(N):3d} articles de presse', flush=True)
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps({'meta': {'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'), 'since': depuis, 'news_days': JOURS_PRESSE,
        'sources': ['Europe PMC (open access)', 'OpenAlex (open access works)', 'Google News'], 'note': '"What we learn" is the sentence of the abstract that speaks most about mortality, growth, weight, cost or survival, picked automatically; read the paper before quoting it.',
        'errors': err}, 'diseases': res}, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()
