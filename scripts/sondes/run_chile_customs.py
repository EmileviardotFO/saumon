"""Lance build_chile_customs.py et renvoie data/chile_customs.json (gzip+base64) dans le journal."""
import subprocess, gzip, base64, sys
subprocess.run('sudo apt-get install -y -qq p7zip-full p7zip-rar >/dev/null 2>&1', shell=True)
subprocess.run([sys.executable, 'scripts/build_chile_customs.py', '--depuis', '2023'], check=False)
print('==CC=='); print(base64.b64encode(gzip.compress(open('data/chile_customs.json', 'rb').read())).decode()); print('==/CC==')
