import requests, io, csv
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
B = 'https://aquaculture.scotland.gov.uk/csv/'
for f in ['ms_movement_restrictions.csv', 'ms_fish_escapes.csv', 'ms_site_details.csv', 'ms_operator_transfers.csv', 'ms_site_facilities.csv', 'se_annual_emissions.csv']:
    r = requests.get(B + f, headers=H, timeout=300)
    rows = list(csv.reader(io.StringIO(r.content.decode('utf-8-sig', 'replace'))))
    print('=====', f, r.status_code, len(rows)); print(rows[0])
    for x in rows[1:4] + rows[-4:]: print('  ', [c[:60] for c in x])
