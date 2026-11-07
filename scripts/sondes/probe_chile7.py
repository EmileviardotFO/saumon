import requests, re
H = {'User-Agent': 'Mozilla/5.0 (salmon-dashboard)'}
for u in ['https://www.sernapesca.cl/manuales_y_publicaciones/caligus/', 'https://www.sernapesca.cl/informes/estadisticas/', 'https://www.sernapesca.cl/informes-y-datos/boletines-regionales/',
          'https://www.sernapesca.cl/informacion-utilidad/ventanas-oficiales-de-coordinacion-tratamientos-inmersion-caligus/', 'https://www.sernapesca.cl/informes-y-datos/resultados-de-gestion/',
          'https://www.ine.gob.cl/estadisticas/economia/agricultura-agroindustria-y-pesca/pesca']:
    try: r = requests.get(u, headers=H, timeout=90)
    except Exception as e: print('ERR', u, e); continue
    print('==', u, r.status_code)
    for l in sorted(set(re.findall(r'href="([^"]+)"', r.text))):
        if re.search(r'(?i)\.pdf|\.xlsx?|\.csv|calig|diseminac|pesca|industria|bolet|sanitar|srs|piscir', l) and 'facebook' not in l: print('  ', l)
