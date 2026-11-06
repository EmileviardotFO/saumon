"""Lance build_canada_extra.py avec --dump (donnees brutes dans le journal) puis imprime un resume."""
import json, os, subprocess, sys
root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
subprocess.run([sys.executable, os.path.join(root, 'scripts', 'build_canada_extra.py'), '--dump'], check=False)
d = json.load(open(os.path.join(root, 'data', 'canada_extra.json')))
print(json.dumps({k: (v if k in ('meta',) else str(v)[:1500]) for k, v in d.items()}, indent=1))
