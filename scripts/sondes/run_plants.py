"""Lance build_plants.py et imprime les deux fichiers produits (entre marqueurs)."""
import os, subprocess, sys, base64, gzip
root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
subprocess.run([sys.executable, os.path.join(root, 'scripts', 'build_plants.py')], check=False)
for f in ('plants.json', 'plants_geo.json'):
    b = base64.b64encode(gzip.compress(open(os.path.join(root, 'data', f), 'rb').read())).decode()
    print(f'==={f}-BEGIN==='); [print(b[i:i + 8000]) for i in range(0, len(b), 8000)]; print(f'==={f}-END===')
