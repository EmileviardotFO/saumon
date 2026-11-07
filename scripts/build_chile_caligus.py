#!/usr/bin/env python3
"""
data/chile_caligus.json : fermes chiliennes classees « centre a haute dissemination » (CAD) de caligus par le Sernapesca
(programme PSEVC-Caligidosis) : charge moyenne >= 3 femelles ovigeres au controle hebdomadaire qui suit la fin de la
fenetre officielle de traitement de leur zone (ACS). Le Sernapesca met a jour la liste (PDF) sur la page
« Listados y Registros » ; chaque version est cumulative pour la saison. On garde toutes les entrees vues, avec la
version ou elles sont apparues, et on signale les nouvelles (ticket GitHub par l'etape de notification).
Pas de comptage de poux ferme par ferme en libre acces au Chili : c'est le signal public le plus fin.
"""
import io, json, os, re, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'chile_caligus.json')
ALERT = os.path.join(ROOT, 'data', 'chile_caligus_new_alerts.md')
PAGE = 'https://www.sernapesca.cl/informacion-utilidad/listados-y-registros/'
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
ROW = re.compile(r'^\s*(\d+)\s+(\d{6})\s+(.+?)\s+(X{1,2}I{0,2}|XI|XII|X)\s+(\d{1,2}\s?[A-Z]?(?:-\d)?)\s+(S\.A\.|T\.A\.|S\.C\.|O\.K\.|\S+)\s+(\d{2})/(\d{4})\s*$')


def parse(pdf_bytes):
    import pdfplumber
    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            for line in (p.extract_text() or '').splitlines():
                m = ROW.match(line)
                if not m: continue
                n, code, mid, reg, acs, sp, wk, yr = m.groups()
                # « NOM CENTRE  EMPRESA » : la societe commence au premier mot de raison sociale connu
                mm = re.search(r'\s((?:[A-ZÁÉÍÓÚÑ.,&]+\s)*?(?:S\.A\.|S\.A|LTDA\.?|LIMITADA|SPA|SpA)\.?(?:,\s*[A-ZÁÉÍÓÚÑ ]+)?)$', mid)
                rows.append({'n': int(n), 'code': code, 'site_company': mid, 'region': {'X': 'Los Lagos', 'XI': 'Aysén', 'XII': 'Magallanes'}.get(reg, reg),
                             'acs': acs.replace(' ', ''), 'sp': {'S.A': 'atlantic', 'T.A': 'trout', 'S.C': 'coho', 'O.K': 'coho'}.get(sp.rstrip('.'), sp), 'week': f'{yr}-W{wk}'})
    return rows


def split_company(s):
    """Separe « NOM CENTRE » et « SOCIETE » (la societe finit par S.A., LTDA., SpA...)."""
    toks = s.split()
    for i in range(len(toks)):
        rest = ' '.join(toks[i:])
        if re.match(r'^(AQUA|SALMO|CERMAQ|NUEVA|MOWI|MULTI|AUSTRALIS|BLUMAR|SALMONES|CULTIVOS|INVERMAR|EXPORTADORA|TORNAGALEONES|GRANJA|COOKE|NOVA|EMPRESA|PRODUCTOS|CALETA BAY|FRIO|FRÍO|PISCICULTURA|AGROSUPER|YADRAN|VENTISQUEROS|CAMANCHACA|PESQUERA|ACUICOLA|ACUÍCOLA|AQUAGEN|TRUSAL|PACIFIC|SALMONCHILE|PROCESADORA|ATLANTIS|LOS FIORDOS)', rest):
            return ' '.join(toks[:i]).strip(), rest.strip()
    return s, ''


def main():
    old = json.load(open(OUT)) if os.path.exists(OUT) else {'entries': [], 'versions': []}
    html = requests.get(PAGE, headers=H, timeout=60).text
    links = sorted(set(re.findall(r'href="([^"]*[Dd]iseminaci[^"]*\.pdf)"', html)))
    if not links: print('aucune liste CAD trouvee'); return
    url = links[-1]; ver = re.search(r'v(\d{8})', url); ver = ver.group(1) if ver else time.strftime('%Y%m%d')
    if ver in [v['version'] for v in old['versions']]:
        print('liste CAD deja lue :', ver); open(ALERT, 'w').write(''); return
    rows = parse(requests.get(url, headers=H, timeout=120).content)
    if not rows: print('liste CAD illisible :', url); return
    seen = {(e['code'], e['week']) for e in old['entries']}
    new = []
    for r in rows:
        site, comp = split_company(r.pop('site_company')); r['site'], r['company'] = site, comp
        if (r['code'], r['week']) not in seen: r['first_seen'] = ver; new.append(r)
    entries = old['entries'] + new
    versions = old['versions'] + [{'version': ver, 'url': url, 'rows': len(rows), 'new': len(new)}]
    out = {'meta': {'built': time.strftime('%Y-%m-%d'), 'source': 'Sernapesca, PSEVC-Caligidosis: list of high-dissemination centres (CAD)', 'page': PAGE,
                    'rule': 'CAD = average load of 3 or more gravid female caligus at the weekly count after the end of the official treatment window of its area (ACS)'},
           'versions': versions, 'entries': sorted(entries, key=lambda e: (e['week'], e['code']))}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    # alerte : nouvelles fermes CAD depuis la derniere version lue
    if new and old['versions']:
        by_co = {}
        for r in new: by_co.setdefault(r['company'] or '?', []).append(r)
        lines = [f"Sernapesca a publie une nouvelle liste de centres a haute dissemination de caligus (version {ver}) : {len(new)} nouvelle(s) entree(s).", '']
        for co, rs in sorted(by_co.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"- **{co}** : " + ', '.join(f"{r['site']} ({r['region']}, ACS {r['acs']}, semaine {r['week']})" for r in rs))
        lines += ['', f'Liste : {url}']
        open(ALERT, 'w').write('\n'.join(lines))
    else:
        open(ALERT, 'w').write('')
    print(f'CAD version {ver} : {len(rows)} lignes, {len(new)} nouvelles ; total {len(entries)}')


if __name__ == '__main__':
    main()
