"""Sonde : (1) registre aquacole du Nouveau-Brunswick, section des conditions a declaration obligatoire ;
(2) site de la NAIA (Terre-Neuve) : pages qui listent les avis publics de mortalite anormale, et liens PDF."""
import html, re, requests
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard; github.com/EmileviardotFO/saumon)'}


def text(u):
    r = requests.get(u, headers=H, timeout=60); print(u, r.status_code, len(r.content), r.headers.get('content-type'))
    return r


r = text('https://dnr-mrn.gnb.ca/AquacultureRegistry/')
x = re.sub(r'(?s)<script.*?</script>|<style.*?</style>', '', r.text)
t = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', x)))
for key in ('Date of Report', 'Reportable', 'Nature Source', 'ORDERS', 'Escapes'):
    i = t.find(key); print('---', key, i); print(t[max(0, i - 300): i + 1500] if i >= 0 else '')
print('dates 2026 :', sorted(set(re.findall(r'2026-\d\d-\d\d', t)))[-20:])
print('dates 2025 :', len(set(re.findall(r'2025-\d\d-\d\d', t))))
links = re.findall(r'href="([^"]+)"', r.text); print('liens', len(links)); print([l for l in links if 'eport' in l or 'ondition' in l or 'ealth' in l][:40])

for u in ('https://naia.ca/', 'https://naia.ca/index.php/public-reporting', 'https://naia.ca/index.php/sustainability', 'https://naia.ca/index.php/public-notices',
          'https://naia.ca/index.php/fish-health', 'https://www.naia.ca/'):
    try:
        r = text(u)
        if r.ok:
            L = re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
            print('  liens :', len(L))
            for h, l in L:
                l = re.sub(r'<[^>]+>|\s+', ' ', l).strip()
                if re.search(r'(?i)mortal|notice|report|download_file|public|health', h + ' ' + l): print('   ', h, '|', l[:120])
    except Exception as e:  # noqa: BLE001
        print(u, 'ERREUR', e)
