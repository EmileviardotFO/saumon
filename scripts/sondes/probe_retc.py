"""Sonde : etablissements RETC (MMA Chili) avec coordonnees, filtres sur le poisson / la salmoniculture."""
import io, json, re, requests, pandas as pd, base64, gzip
H = {'User-Agent': 'salmon-dashboard/1.0'}
u = 'https://datosretc.mma.gob.cl/dataset/220c2663-92e3-4d42-87d8-5a1f9417e40f/resource/d1682353-3e5f-4100-9a53-f4b9650e2984/download/establecimientos_ckan.xlsx'
r = requests.get(u, headers=H, timeout=180); print(r.status_code, len(r.content))
df = pd.read_excel(io.BytesIO(r.content)); print(df.columns.tolist(), len(df))
print(df['Rubro RETC'].value_counts().head(40).to_string()) if 'Rubro RETC' in df else None
txt = df.astype(str).agg(' '.join, axis=1).str.lower()
m = txt.str.contains(r'salm|pesc|acu[ií]c|marine harvest|mowi|cermaq|multiexport|camanchaca|blumar|australis|yadr|invermar|ventisquer|caleta bay|trusal|cooke|abick|nova austral|los fiordos|aquachile|empresas aquachile|salmoproceso|surprocesos|antarfood|invertec|tornagaleones|pacific star|rio dulce|r[ií]o dulce|sealand|congelados|frigor', regex=True)
reg = df.iloc[:, 0].astype(str).str.contains('Lagos|Ays|Magall|Biob|Arauc', regex=True)
sub = df[m & reg]; print('candidats', len(sub))
b = base64.b64encode(gzip.compress(sub.to_json(orient='records', force_ascii=False).encode())).decode()
print('===RETC-BEGIN==='); [print(b[i:i + 8000]) for i in range(0, len(b), 8000)]; print('===RETC-END===')
