#!/usr/bin/env python3
"""
data/chile_regional.json : ce que les bureaux regionaux de l'INE (Instituto Nacional de Estadisticas) publient sur
le saumon, region par region, d'apres les chiffres provisoires du Sernapesca :
  - Los Lagos (Region X), chaque mois : production des usines de transformation par espece (tonnes) ;
  - Magallanes (Region XII), chaque mois : recolte des centres de culture par espece ;
  - Aysen (Region XI), chaque trimestre : recolte des centres de culture par espece.
Chaque bulletin donne le mois (ou trimestre) et le meme mois un an plus tot : l'historique se reconstitue.
Les PDF sont lus en texte (pdfplumber). Sources : https://regiones.ine.cl/<region>/estadisticas-regionales/economia/...
"""
import io, json, os, re, time, unicodedata
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'chile_regional.json')
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}
B = 'https://regiones.ine.cl'
MES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
MES3 = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
TRIM = ['primer', 'segundo', 'tercer', 'cuarto']
SP = [('atlantic', r'salmondelatlantico'), ('coho', r'salmon(plateado)?(o)?coho|salmonplateado'), ('trout', r'truchaarcoiris')]


def flat(t):
    t = unicodedata.normalize('NFKD', t.replace('´', '').replace('˜', '').replace('ı', 'i')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', '', t)


def num(s):
    return float(s.replace('.', '').replace(',', '.'))


def pdf_text(url):
    import pdfplumber
    r = requests.get(url, headers=H, timeout=120)
    if not r.ok or not r.content.startswith(b'%PDF'): return None
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        return '\n'.join((p.extract_text() or '') for p in pdf.pages)


def species_rows(text, want=None):
    """Lignes de tableau « Espece  N-1  N  [ecart]  variation% », rangees selon le dernier titre lu au-dessus :
    'harvest' (cosecha des centres de culture) ou 'processing' (production des usines). Une ligne n'est gardee que si
    la variation imprimee correspond aux deux chiffres (evite de lire une autre serie). want = contexte voulu."""
    out, ctx = {}, None
    for line in text.splitlines():
        f = flat(line)
        if re.search(r'cosecha', f): ctx = 'harvest'
        elif re.search(r'elaboraci|plantas?de|produccionpesquerayacuicola|lineadeelaboracion|lineas', f): ctx = 'processing'
        for k, pat in SP:
            if not re.match(r'(' + pat + r')-?\d', f): continue
            nums = re.findall(r'-?(?<![\d,])\d{1,3}(?:\.\d{3})*(?:,\d+)?(?![\d])', line)
            if len(nums) < 3: continue
            try:
                a, b = num(nums[0]), num(nums[1])
                var = 100 * (b / a - 1) if a else None
                if var is not None and any(abs(num(v) - var) <= 0.35 for v in nums[2:5]):
                    out.setdefault(ctx or 'other', {}).setdefault(k, [a, b])
            except (ValueError, ZeroDivisionError):
                pass
    if want:
        return out.get(want) or {}
    return out


def los_lagos(y, m):
    urls = [f'{B}/documentos/default-source/region-x/estadisticas/industria-pesquera-y-acuicola/boletines/{y}/bolet%c3%adn-de-industria-pesquera-y-acu%c3%adcola-{MES[m - 1]}-{y}.pdf']
    for u in urls:
        t = pdf_text(u)
        if t: return t, u
    return None, None


def magallanes(y, m):
    for v in ('(3-0)', '(2-0)', '(1-0)', ''):
        u = f'{B}/documentos/default-source/region-xii/estadisticas/pesca/boletines/{y}/pes_{MES3[m - 1]}_{y}{"_" + v if v else ""}.pdf'
        t = pdf_text(u)
        if t: return t, u
    return None, None


def aysen(y, q):
    for name in (f'bolet%C3%ADn-de-pesca---{TRIM[q - 1]}-trimestre-{y}', f'boletin-de-pesca---{TRIM[q - 1]}-trimestre-{y}'):
        u = f'{B}/documentos/default-source/region-xi/estadisticas/pesca/boletines/{y}/{name}.pdf'
        t = pdf_text(u)
        if t: return t, u
    return None, None


def page_links(path):
    try:
        r = requests.get(B + path, headers=H, timeout=60)
        return [l.replace('&amp;', '&') for l in re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text)]
    except Exception:  # noqa: BLE001
        return []


def main():
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    data = {k: dict(old.get(k, {})) for k in ('los_lagos', 'magallanes', 'aysen')}
    now = time.localtime(); Y = now.tm_year
    # liens publies sur les pages (avec leur jeton de version) : essayes en premier
    extra = {'los_lagos': page_links('/los-lagos/estadisticas-regionales/economia/agricultura-agroindustria-y-pesca/industria-pesquera-acuicola'),
             'magallanes': page_links('/magallanes/estadisticas-regionales/economia/agricultura-agroindustria-y-pesca/pesca')}
    WANT = {'los_lagos': None, 'magallanes': 'harvest', 'aysen': 'harvest'}
    def put(region, key, text, url, what):
        rows = species_rows(text, WANT[region])
        if region == 'los_lagos': rows = next(iter(rows.values()), {}) if rows else {}
        if not rows: return False
        y, p = key.split('-')
        prev = f'{int(y) - 1}-{p}'
        data[region][key] = {'t': {k: v[1] for k, v in rows.items()}, 'what': what, 'url': url.split('?')[0]}
        if prev not in data[region]:
            data[region][prev] = {'t': {k: v[0] for k, v in rows.items()}, 'what': what, 'url': url.split('?')[0], 'from_next_year': True}
        return True
    for u in extra['los_lagos']:
        m = re.search(r'acu%c3%adcola-(\w+)-(\d{4})', u, re.I)
        if m and m.group(1).lower() in MES:
            t = pdf_text(u if u.startswith('http') else B + u)
            if t: put('los_lagos', f'{m.group(2)}-{MES.index(m.group(1).lower()) + 1:02d}', t, u, 'processing plant output')
    for u in extra['magallanes']:
        m = re.search(r'pes_(\w{3})_(\d{4})', u)
        if m and m.group(1) in MES3:
            t = pdf_text(u if u.startswith('http') else B + u)
            if t: put('magallanes', f'{m.group(2)}-{MES3.index(m.group(1)) + 1:02d}', t, u, 'farm harvest')
    for y in range(Y - 2, Y + 1):
        for mth in range(1, 13):
            if (y, mth) >= (now.tm_year, now.tm_mon): break
            k = f'{y}-{mth:02d}'
            if k not in data['los_lagos'] or data['los_lagos'][k].get('from_next_year'):
                t, u = los_lagos(y, mth)
                if t: put('los_lagos', k, t, u, 'processing plant output')
            if k not in data['magallanes'] or data['magallanes'][k].get('from_next_year'):
                t, u = magallanes(y, mth)
                if t: put('magallanes', k, t, u, 'farm harvest')
        for q in range(1, 5):
            k = f'{y}-Q{q}'
            if (y, q * 3) >= (now.tm_year, now.tm_mon): break
            if k not in data['aysen'] or data['aysen'][k].get('from_next_year'):
                t, u = aysen(y, q)
                if t: put('aysen', k, t, u, 'farm harvest (quarter)')
    out = {'meta': {'built': time.strftime('%Y-%m-%d'), 'unit': 'tonnes (Sernapesca provisional figures, via INE regional bulletins)',
                    'note': 'Los Lagos = output of processing plants (monthly); Magallanes = harvest at farms (monthly); Aysén = harvest at farms (quarterly). '
                            'Each bulletin also gives the same period a year earlier.'},
           **{k: dict(sorted(v.items())) for k, v in data.items()}}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    for k in ('los_lagos', 'magallanes', 'aysen'):
        ks = sorted(out[k]); print(k, len(ks), ks[:1], ks[-1:], out[k][ks[-1]]['t'] if ks else '')


if __name__ == '__main__':
    main()
