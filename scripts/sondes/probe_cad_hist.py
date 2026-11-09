"""Sonde : anciennes listes CAD (centres a haute dissemination de caligus) de Sernapesca, via l'index de Wayback."""
import json, urllib.request, re, io, os
UA = {'User-Agent': 'Mozilla/5.0 (salmon-outlook probe)'}
def get(u, t=90):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t) as r: return r.read()
for pat in ['sernapesca.cl/app/uploads/*', 'sernapesca.cl/sites/default/files/*']:
    try:
        x = json.loads(get('http://web.archive.org/cdx/search/cdx?url=' + pat + '&output=json&fl=timestamp,original,statuscode&filter=original:.*(?i)(diseminaci|CAD).*&collapse=urlkey&limit=500'))
        print(pat, len(x))
        for r in x[1:200]: print('  ', r)
    except Exception as e: print(pat, 'ERR', str(e)[:200])
