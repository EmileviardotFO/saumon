"""Lance build_iceland_mast.py et imprime le fichier produit entre deux reperes (pour le recuperer dans le journal)."""
import subprocess, sys
r = subprocess.run([sys.executable, 'scripts/build_iceland_mast.py'], capture_output=True, text=True)
print(r.stdout[-3000:], r.stderr[-2000:])
print('@@@JSON-START@@@'); print(open("data/iceland_mast.json", encoding="utf-8").read()); print('@@@JSON-END@@@')
