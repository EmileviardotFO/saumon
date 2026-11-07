import requests, re, sys, io, gzip, base64
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
s = requests.Session(); s.headers.update(H)
for u in ['https://aquaculture.scotland.gov.uk/Data/FishFarmMonthlyBiomassAndTreatmentReports',
          'https://aquaculture.scotland.gov.uk/Data',
          'https://aquaculture.scotland.gov.uk/Resources/DatasetDescriptions/FishFarmMonthlyBiomassAndTreatmentReports']:
    try:
        r = s.get(u, timeout=60); print('==', u, r.status_code, len(r.text))
        links = sorted(set(re.findall(r'(?:href|action|src)="([^"]+)"', r.text)))
        print('\n'.join(l for l in links if not l.endswith(('.css', '.png', '.jpg', '.svg', '.ico'))))
        for m in re.finditer(r'<form[\s\S]{0,3000}?</form>', r.text): print('FORM', m.group(0)[:2500])
        for m in re.finditer(r'(?i)(csv|export|download|api)[^<>"]{0,120}', r.text): print('KW', m.group(0)[:150])
    except Exception as e: print('ERR', u, e)
