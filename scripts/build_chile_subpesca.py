#!/usr/bin/env python3
"""
Chile: what Subpesca (Subsecretaría de Pesca y Acuicultura) publishes that tells where the salmon supply is going.

    python3 scripts/build_chile_subpesca.py                 -> data/chile_subpesca.json (new documents since last run)
    BACKFILL_FROM=120000 THREADS=6 python3 scripts/...      -> first run: scans every document id from there

1. "Fija densidad de cultivo" resolutions. Before each production cycle, every company's farms in a group of concessions
   (ACS, "barrio") get a resolution that sets, farm by farm, the number of fish they may put to sea ("N° de peces a
   sembrar"), with the species, after the coordinated fallow of that ACS. Summed by company, species and stocking
   window, it is the closest public figure to Chile's generations: how many smolts each company plans to stock, cycle
   after cycle. "Modifica" resolutions replace the table of an earlier one; the latest figure of each farm is kept.
2. "Informe sectorial de pesca y acuicultura" (monthly): harvest of Atlantic salmon, Pacific salmon (coho) and rainbow
   trout accumulated since January, by region, from Sernapesca's preliminary figures (about one month late), and the
   eggs produced. A month on its own = difference of two consecutive reports.

Subpesca has no list of these documents: each one is a numbered page (w3-article-<id>.html, title = the resolution)
with its PDF (articles-<id>_documento.pdf). The script reads the ids it has not seen yet and keeps a state in the
output file. Nothing is interpolated.
"""
import concurrent.futures as cf
import datetime as dt
import io
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'chile_subpesca.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
BASE = 'https://www.subpesca.cl/portal'
MONTHS = {m: i + 1 for i, m in enumerate(['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'])}
S = requests.Session()
S.headers.update(UA)


def get(url, timeout=40, tries=3):
    for t in range(tries):
        try:
            r = S.get(url, timeout=timeout)
            if r.status_code in (200, 404):
                return r
        except Exception:
            pass
        time.sleep(2 + 3 * t)
    return None


def pdf_text(content, pages=None):
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        P = pdf.pages if pages is None else pdf.pages[:pages]
        for p in P:
            out.append((p.extract_text() or '', p))
        return [t for t, _ in out], pdf


def num(s):
    s = str(s or '').strip().replace(' ', '')
    if re.fullmatch(r'\d{1,3}(\.\d{3})+', s):
        return int(s.replace('.', ''))
    if re.fullmatch(r'\d+', s):
        return int(s)
    return None


def species(s):
    s = (s or '').lower()
    if 'coho' in s or 'plateado' in s or 'pac' in s:
        return 'coho'
    if 'trucha' in s:
        return 'trucha'
    if 'atl' in s or 'salar' in s:
        return 'salar'
    return None


def es_date(text):
    m = re.search(r'(\d{1,2})\s+de\s+(' + '|'.join(MONTHS) + r')\s+de\s+(\d{4})', text, re.I)
    return f'{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}' if m else None


# ------------------------------------------------------------------ 1. resolutions
def parse_resolution(aid, title, content):
    import pdfplumber
    rows, seen, cols, harv = [], set(), None, {}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        texts = []
        for i, p in enumerate(pdf.pages):
            t = p.extract_text() or ''
            texts.append(t)
            # (dans les resolutions anciennes, le tableau de la resolution est une image : on le retrouve en texte dans
            #  l'informe technique joint, avec le meme en-tete ; le premier chiffre lu pour un centre est garde)
            for tb in p.extract_tables() or []:
                if not tb or not tb[0]:
                    continue
                head = [re.sub(r'\s+', ' ', str(h or '')).lower() for h in tb[0]]
                # recoltes et pertes du cycle qui se termine (effectives et projetees), centre par centre
                if head and 'digo' in head[0] and len(head) >= 4 and re.search(r'cosecha|p[ée]rdida', head[1]):
                    kind = ('harv' if 'cosecha' in head[1] else 'loss') + ('_proj' if 'proyect' in head[1] else '')
                    for r in tb[1:]:
                        code = re.sub(r'\D', '', str(r[0] or ''))
                        if len(code) == 6 and num(r[1]) is not None:
                            w = str(r[2] or '').replace('.', '').replace(',', '.')
                            harv.setdefault(kind, {})[code] = {'fish': num(r[1]), 'w': float(w) if re.fullmatch(r'[\d.]+', w) else None}
                    continue
                ci = next((j for j, h in enumerate(head) if 'peces' in h and 'sembrar' in h), None)
                cc = next((j for j, h in enumerate(head) if 'digo' in h or 'centro' in h), None)
                cs = next((j for j, h in enumerate(head) if 'especie' in h), None)
                ca = next((j for j, h in enumerate(head) if h.strip() == 'acs' or h.startswith('acs')), None)
                body = tb[1:]
                if ci is not None and cc is not None:
                    cols = (ci, cc, cs, ca, len(tb[0]))
                elif cols and len(tb[0]) == cols[4]:
                    ci, cc, cs, ca, _ = cols          # suite du tableau sur la page suivante, sans en-tete
                    body = tb
                else:
                    continue
                for r in body:
                    code = re.sub(r'\D', '', str(r[cc] or ''))
                    n = num(r[ci])
                    if len(code) == 6 and n is not None and code not in seen:
                        seen.add(code)
                        rows.append({'centre': code, 'acs': (str(r[ca]).strip() if ca is not None and r[ca] else ''), 'sp': species(r[cs] if cs is not None else ''), 'fish': n})
    full = '\n'.join(texts)
    # repli : lignes de texte "25A 110227 del 500.000 ..." quand pdfplumber ne voit pas le tableau
    if not rows:
        for m in re.finditer(r'(?m)^\s*(\d{1,2}[A-Z]?(?:-\d)?)\s+(1[0-2]\d{4})\s+(?:\S+\s+){0,3}?(\d{1,3}(?:\.\d{3})+)\s', full):
            rows.append({'centre': m.group(2), 'acs': m.group(1), 'sp': None, 'fish': num(m.group(3))})
    head = full[:2500]
    # region : le code de centre commence par le numero de region (10 Los Lagos, 11 Aysen, 12 Magallanes)
    RG = {'10': 'Los Lagos', '11': 'Aysén', '12': 'Magallanes'}
    for row in rows:
        row['region'] = RG.get(row['centre'][:2])
    regs = sorted({row['region'] for row in rows if row['region']})
    reg = ', '.join(regs) if regs else next((r for r in ('Magallanes', 'Aysén', 'Los Lagos') if r.lower() in head.lower()), None)
    fallow = re.search(r'descanso sanitario coordinado entre:?\s*(' + '|'.join(MONTHS) + r')\s+de\s+(\d{4})\s+a\s+(' + '|'.join(MONTHS) + r')\s+de\s+(\d{4})', full, re.I)
    comp = re.search(r'(?i)titularidad\s+de\s+(.+?)(?:,?\s*como grupo|\.?\s*aprueba|\.\s*\(|\s*\(Publicado|\.\s*$|$)', title)
    if not comp:
        comp = re.search(r'(?m)^ACUI/\s*PRS\s+(?:GRUPO\s+)?(.+)$', head)
    return {'id': aid, 'title': title, 'date': es_date(head) or es_date(full), 'region': reg,
            'company': (comp.group(1).strip().rstrip('.').strip() if comp else ''), 'modifies': bool(re.match(r'(?i)\s*res\.?\s*ex\.?.{0,25}modifica', title)),
            'fallow': [f'{fallow.group(2)}-{MONTHS[fallow.group(1).lower()]:02d}', f'{fallow.group(4)}-{MONTHS[fallow.group(3).lower()]:02d}'] if fallow else None,
            'rows': rows, 'cycle': {k: list(v.values()) and {'farms': len(v), 'fish': sum(x['fish'] for x in v.values()),
                                                   't': round(sum(x['fish'] * (x['w'] or 0) for x in v.values()) / 1000)} for k, v in harv.items()},
            'kind': 'prs' if rows else ('density' if re.search(r'(?i)agrupaci', title) else 'unread')}


# ------------------------------------------------------------------ 2. monthly sector report
def parse_report(aid, texts):
    """mois du rapport et cumul depuis janvier de chaque espece. Les titres des especes sont des images dans les rapports
    recents : les trois puces qui suivent le total des poissons sont, dans l'ordre, saumon atlantique, saumon du
    Pacifique (coho) et truite arc-en-ciel."""
    full = '\n'.join(texts)
    M = '|'.join(MONTHS)
    t = re.search(r'cosecha total de peces acumulada (?:a|al mes de) (' + M + r')(?: de)? (\d{4})(.{0,6000})', full, re.I | re.S)
    if not t:
        return None
    k = int(t.group(2)) * 100 + MONTHS[t.group(1).lower()]
    rest = t.group(3).split('ovas')[0]
    out = {'id': aid, 'k': k, 'species': {}}
    P = list(re.finditer(r'La cosecha acumulada (?:a|al mes de) (?:' + M + r')(?: de)?(?: \d{4})? fue de\s+([\d.,]+)\s*mil\s*t,?\s*(?:cifra|lo que es|lo que representa)?\s*(?:un\s+)?([\d,]+)\s*%\s*(mayor|menor)', rest, re.I | re.S))
    for key, m in zip(('salar', 'coho', 'trucha'), P[:3]):
        seg = rest[m.end():m.end() + 500]
        regs = {}
        for rm in re.finditer(r'(Ays[ée]n|Los Lagos|Magallanes)[^\d]{0,80}?con\s+([\d,]+)\s*mil\s*t', seg):
            regs.setdefault('Aysén' if 'Ays' in rm.group(1) else rm.group(1), float(rm.group(2).replace(',', '.')))
        rr = re.search(r'Regiones de (.{3,90}?)\s+y\s+(.{3,40}?),\s*con\s+([\d,]+)\s*mil\s*t[^)]*\)\s*y\s+([\d,]+)\s*mil\s*t', seg, re.S)
        if rr:
            regs = {}
            for nm, v in ((rr.group(1), rr.group(3)), (rr.group(2), rr.group(4))):
                nm = 'Aysén' if 'Ays' in nm else 'Los Lagos' if 'Lagos' in nm else 'Magallanes' if 'Magall' in nm else nm.strip()
                regs[nm] = float(v.replace(',', '.'))
        out['species'][key] = {'cum_kt': float(m.group(1).replace('.', '').replace(',', '.')),
                               'var_pct': float(m.group(2).replace(',', '.')) * (1 if m.group(3).lower() == 'mayor' else -1), 'regions_kt': regs}
    o = re.search(r'producci[óo]n acumulada de ovas[^.]{0,60}?fue de\s+([\d.,]+)\s*millones', full, re.I)
    if o:
        out['eggs_m'] = float(o.group(1).replace('.', '').replace(',', '.'))
    return out if out['species'] else None


# ------------------------------------------------------------------ scan
def look(aid):
    """one document id -> ('res', dict) | ('rep', dict) | ('other', None) | ('none', None) | ('err', None)"""
    r = get(f'{BASE}/615/w3-article-{aid}.html', 30)
    if r is None:
        return aid, 'err', None
    if r.status_code == 200:
        t = re.search(r'<title>(.*?)</title>', r.text, re.S)
        title = re.sub(r'\s+', ' ', t.group(1)).replace(' - SUBPESCA Normativa', '').strip() if t else ''
        if re.search(r'(?i)densidad de cultivo', title) and re.search(r'(?i)\b(fija|modifica)', title):
            p = get(f'{BASE}/615/articles-{aid}_documento.pdf', 90)
            if p is None or p.status_code != 200:
                return aid, 'err', None
            try:
                return aid, 'res', parse_resolution(aid, title, p.content)
            except Exception as ex:  # noqa: BLE001
                return aid, 'res', {'id': aid, 'title': title, 'error': f'{type(ex).__name__}: {ex}'[:200], 'rows': []}
        return aid, 'other', None
    # pas de page dans "Normativa" : peut-etre une publication (portail 616), dont l'informe sectorial mensuel
    for host in ('https://source.subpesca.cl/portal', BASE):
        try:
            h = S.head(f'{host}/616/articles-{aid}_documento.pdf', timeout=30, allow_redirects=True)
        except Exception:
            continue
        if h.status_code == 200 and 300_000 < int(h.headers.get('content-length', 0) or 0) < 15_000_000:
            p = get(f'{host}/616/articles-{aid}_documento.pdf', 120)
            if p is None or p.status_code != 200:
                return aid, 'err', None
            try:
                texts, _ = pdf_text(p.content, 3)
                if 'Informe Sectorial de Pesca y Acuicultura' not in ' '.join(texts):
                    return aid, 'other', None
                texts, _ = pdf_text(p.content)
                return aid, 'rep', parse_report(aid, texts) or {'id': aid, 'k': None, 'species': {}, 'unread': True}
            except Exception:
                return aid, 'other', None
        if h.status_code == 200:
            return aid, 'other', None
    return aid, 'none', None


def main():
    try:
        st = json.load(io.open(OUT, encoding='utf-8'))
    except Exception:
        st = {'meta': {}, 'resolutions': [], 'reports': []}
    M = st.setdefault('meta', {})
    start = int(os.environ.get('BACKFILL_FROM') or 0) or (M.get('last_id', 130600) + 1)
    threads = int(os.environ.get('THREADS') or 3)
    limit = int(os.environ.get('MAX_IDS') or 600)
    stop_after = 250                       # ids vides d'affilee au-dela du dernier document : fin
    R = {x['id']: x for x in st.get('resolutions', [])}
    P = {x['id']: x for x in st.get('reports', []) if x}
    last_found, errors, aid, seen = M.get('last_id', start - 1), [], start, 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(threads) as ex:
        while seen < limit:
            batch = list(range(aid, aid + threads * 4))
            aid += len(batch)
            seen += len(batch)
            for i, kind, val in ex.map(look, batch):
                if kind == 'err':
                    errors.append(i)
                if kind in ('res', 'rep', 'other'):
                    last_found = max(last_found, i)
                if kind == 'res' and val:
                    R[i] = val
                if kind == 'rep' and val:
                    P[i] = val
            if aid - last_found > stop_after:
                break
    M.update({'last_id': last_found, 'generated': dt.date.today().isoformat(), 'source': 'Subpesca: resoluciones de densidad de cultivo (N° de peces a sembrar por centro) e informes sectoriales mensuales',
              'url': 'https://www.subpesca.cl/portal/615/w3-channel.html', 'errors_last_run': errors[:50],
              'note': 'fish to stock = the number authorised in each density resolution for the next cycle of each farm, after the ACS fallow; a later resolution modifying a farm replaces its figure'})
    st['resolutions'] = sorted(R.values(), key=lambda x: x['id'])
    st['reports'] = sorted(P.values(), key=lambda x: (x['k'] or 0, x['id']))
    st['stocking'] = summarise(st['resolutions'])
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(st, ensure_ascii=False, separators=(',', ':')))
    print(f'chile subpesca: ids {start}..{aid - 1} in {time.time() - t0:.0f}s, last document {last_found}, {len(R)} resolutions '
          f'({sum(len(x.get("rows", [])) for x in R.values())} farm rows), {len(P)} monthly reports, {len(errors)} errors')
    return 0


def summarise(res):
    """latest figure per farm (a later resolution replaces an earlier one within 15 months), then totals by company,
    species and stocking half-year (from the resolution date, or the end of the ACS fallow when stated)."""
    farm = {}
    for r in sorted(res, key=lambda x: (x.get('date') or '', x['id'])):
        when = (r.get('date') or '')[:7] or (r.get('fallow') or [None, None])[1]
        for row in r.get('rows', []):
            k = row['centre']
            prev = farm.get(k)
            if prev and prev['when'] and when and (int(when[:4]) * 12 + int(when[5:7])) - (int(prev['when'][:4]) * 12 + int(prev['when'][5:7])) <= 15 and r.get('modifies'):
                farm[k] = dict(prev, fish=row['fish'], sp=row['sp'] or prev['sp'], id=r['id'])
                continue
            key = f"{k}|{when[:4]}"
            farm[key if prev and prev['when'][:4] != when[:4] else k] = {'centre': k, 'acs': row['acs'], 'sp': row['sp'], 'fish': row['fish'], 'when': when,
                                                                        'company': r.get('company'), 'region': row.get('region') or r.get('region'), 'id': r['id']}
    agg = {}
    for f in farm.values():
        if not f['when']:
            continue
        y, m = int(f['when'][:4]), int(f['when'][5:7])
        half = f'{y}-H{1 if m <= 6 else 2}'
        o = agg.setdefault((half, f['company'] or '?', f['sp'] or '?', f['region'] or '?'), {'fish': 0, 'farms': 0})
        o['fish'] += f['fish']
        o['farms'] += 1
    return [{'half': h, 'company': c, 'sp': s, 'region': rg, **v} for (h, c, s, rg), v in sorted(agg.items())]


if __name__ == '__main__':
    sys.exit(main())
