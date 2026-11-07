import requests, re, io, csv, collections
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
B = 'https://aquaculture.scotland.gov.uk'
r = requests.get(B + '/csv/se_monthly_reports.csv', headers=H, timeout=300); print('CSV', r.status_code, len(r.content))
rows = list(csv.reader(io.StringIO(r.content.decode('utf-8-sig', 'replace'))))
print(rows[0]); yi = rows[0].index('Year')
c = collections.Counter(x[yi][-8:] for x in rows[1:]); print(sorted(c.items(), key=lambda kv: (kv[0][-4:], kv[0]))[-24:])
r = requests.get(B + '/Data', headers=H, timeout=60)
pages = sorted(set(re.findall(r'href="(/Data/[^"]+)"', r.text))); print(pages)
for p in pages:
    t = requests.get(B + p, headers=H, timeout=60).text
    print('==', p, re.findall(r'/csv/[^"\']+', t), re.findall(r'/js/datasets/[^"\']+', t))
