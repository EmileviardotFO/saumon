"""Renvoie leaflet.min.js et leaflet.min.css (cdnjs) en base64 dans le journal, pour les tests locaux."""
import requests, base64, gzip
for n in ['leaflet.min.js', 'leaflet.min.css']:
    b = requests.get(f'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/{n}', timeout=60).content
    print(f'=={n}=='); print(base64.b64encode(gzip.compress(b)).decode()); print(f'==/{n}==')
