#!/usr/bin/env python3
"""
Feroe : construit data/faroe_hfs.json pour l'onglet Faroe Islands a partir de
  - farming/donnees_fo/hfs_fish.csv, hfs_lice.csv, hfs_med.csv (HFS, scripts/fetch_hfs.py) : poissons par site a la fin
    de chaque mois, comptages de poux par site, traitements par site ;
  - farming/donnees_fo/toka_av_laksi.xlsx (HFS) : recolte par semaine et par calibre, kg vides et nombre de poissons ;
  - farming/donnees_fo/bakkafrost_trimestriel.csv et bakkafrost_mensuel.csv (tenus a la main depuis les rapports de
    Bakkafrost) : recolte, poids moyen, smolts mis a l'eau et poids des smolts ;
  - data/sea_temp.json (NOAA) : temperature de la mer aux Feroe, pour les degres-jours.

Ce qui est deduit : cycles par site (mise a l'eau -> site vide ; 9 mois ou moins = poissons deplaces), temps en mer par
fermier, mises a l'eau (hausses de stock), TGC par cycle (poids de smolt de Bakkafrost au trimestre de mise a l'eau quand
il est connu, 0,5 kg sinon ; poids de recolte = moyenne nationale des mois ou le site se vide, vide / 0,88 ; degres-jours
NOAA), et pour Bakkafrost le rendement par smolt (recolte de 4 trimestres / smolts mis a l'eau 5 trimestres plus tot).
Pas de projection site par site : rejouee sur 18 mois elle se trompait de 30 % a un mois.

    python3 scripts/build_faroe_hfs.py
"""
import os, math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/'
import csv, collections, datetime as dt, statistics as S, json, re, openpyxl, calendar
R=ROOT
F=list(csv.DictReader(open(R+'farming/donnees_fo/hfs_fish.csv'))); L=list(csv.DictReader(open(R+'farming/donnees_fo/hfs_lice.csv'))); M=list(csv.DictReader(open(R+'farming/donnees_fo/hfs_med.csv')))
pd_=lambda s: dt.date.fromisoformat(s[:10])
CO={'Bakkafrost Farming P/F':'Bakkafrost','Luna P/F':'Hiddenfjord','Mowi P/F':'Mowi'}
for r in F: r['d']=pd_(r['date']); r['n']=float(r['fish'] or 0); r['co']=CO[r['company']]
for r in L: r['d']=pd_(r['date']); r['v']=float(r['adult_females'] or 0); r['co']=CO[r['company']]
for r in M: r['d0']=pd_(r['start']); r['d1']=pd_(r['end']) if r['end'] else r['d0']; r['bath']=r['type'].startswith('Ba'); r['co']=CO[r['company']]
# ---- recolte hebdo
wb=openpyxl.load_workbook(R+'farming/donnees_fo/toka_av_laksi.xlsx',data_only=True); W={}
for ws in wb.worksheets:
    y=int(ws.title)
    for row in ws.iter_rows(values_only=True):
        c0=row[0]
        if isinstance(c0,str):
            m=re.search(r'(?i)(yvirlit yvir (alla )?tøkuna|samanteljing av tøkuni) í (\d{4})', c0)
            if m: y=int(m.group(3)); continue
        wk=None
        if isinstance(c0,(int,float)) and 1<=c0<=53: wk=int(c0)
        elif isinstance(c0,str):
            m=re.match(r'(?i)vika\s*(\d+)$', c0.strip())
            if m: wk=int(m.group(1))
            elif c0.strip()=='52 & 53': wk=52
        if wk is None or not isinstance(row[10],(int,float)) or not row[10] or (y,wk) in W: continue
        W[(y,wk)]={'s':[float(v or 0) for v in row[1:10]],'kg':float(row[10]),'n':float(row[11] or 0)}
lastw=max(W); LY,LW=lastw
weekly=[]
for wk in range(1,53):
    weekly.append({'w':wk, **{str(y): ({'kt':round(W[(y,wk)]['kg']/1e6,2),'n':round(W[(y,wk)]['n']/1e3),'w':round(W[(y,wk)]['kg']/W[(y,wk)]['n'],2),'s6':round(100*sum(W[(y,wk)]['s'][5:])/W[(y,wk)]['kg'],1),'s4':round(100*sum(W[(y,wk)]['s'][:3])/W[(y,wk)]['kg'],1),'sz':[round(x/1e3) for x in W[(y,wk)]['s']]} if (y,wk) in W else None) for y in (LY-2,LY-1,LY)}})
def cum(y,upto):
    ks=[k for k in W if k[0]==y and k[1]<=upto]; kg=sum(W[k]['kg'] for k in ks); n=sum(W[k]['n'] for k in ks)
    return {'kt':round(kg/1e6,1),'n':round(n/1e6,2),'w':round(kg/n,2),'s6':round(100*sum(sum(W[k]['s'][5:]) for k in ks)/kg,1),'s4':round(100*sum(sum(W[k]['s'][:3]) for k in ks)/kg,1)}
years=[{'y':y, **cum(y,53), 'ytd':cum(y,LW)} for y in range(2011,LY+1)]
# poids moyen national par mois (vide), pour les poids de recolte
mw=collections.defaultdict(lambda:[0.0,0.0]); mh=collections.defaultdict(lambda:[0.0,0.0])
for (y,wk),d in W.items():
    th=dt.date.fromisocalendar(y,wk,4); mw[(th.year,th.month)][0]+=d['kg']; mw[(th.year,th.month)][1]+=d['n']
MW={k:v[0]/v[1] for k,v in mw.items() if v[1]}
def addm(d,n):
    y,m=d.year,d.month-1+n; y+=m//12; m=m%12+1; return dt.date(y,m,calendar.monthrange(y,m)[1])
# ---- stock par site
ser=collections.defaultdict(dict)
for r in F: ser[r['site']][r['d']]=r['n']
co={r['site']:r['co'] for r in F}; name={r['site']:r['name'] for r in F}; dates=sorted({r['d'] for r in F}); last=dates[-1]
stock=[{'k':d.year*100+d.month, **{c: round(sum(r['n'] for r in F if r['d']==d and r['co']==c)/1e6,2) for c in CO.values()}} for d in dates]
# ---- cycles
def mdiff(a,b): return (b.year-a.year)*12+b.month-a.month
cycles=[]; current={}
for s,S_ in ser.items():
    prev=None; start=None; peak=0; hist=[]
    for d in dates:
        n=S_.get(d)
        if n is None: continue
        if (prev in (None,0)) and n>0: start=d; peak=n; hist=[]
        elif start and n>peak: peak=n
        if start: hist.append((d,n))
        if prev and prev>0 and n==0 and start:
            drops=[(hist[i][0],hist[i-1][1]-hist[i][1]) for i in range(1,len(hist)) if hist[i-1][1]-hist[i][1]>0]
            cycles.append(dict(site=s,co=co[s],start=start,end=d,months=mdiff(start,d),peak=peak,drops=drops,known=start>dates[0]))
            start=None; peak=0
        prev=n
    if start and prev and prev>0: current[s]=dict(site=s,co=co[s],start=start,months=mdiff(start,last),peak=peak,now=prev,known=start>dates[0])
T0=dt.date(last.year-2,last.month,1)+dt.timedelta(days=31)
good=lambda c: c['known'] and c['months']>9
def tas(c_,a,b): 
    C=[c for c in cycles if c['co']==c_ and good(c) and a<=c['end']<=b]; return (round(S.median(c['months'] for c in C),1), len(C)) if C else (None,0)
# ---- temperature Feroe (mensuelle, NOAA) et TGC par cycle
st=json.load(open(R+'data/sea_temp.json')); fo=[p for p in st['points'] if p['basin']=='FO'][0]; TM={int(k[:4])*100+int(k[5:]):v for k,v in fo['monthly'].items()}; NORM={int(k):v for k,v in fo['normal'].items()}
def temp(y,m): return TM.get(y*100+m, NORM[m])
def dd(a,b):
    t=0; d=a
    while d<b:
        t+=temp(d.year,d.month); d+=dt.timedelta(days=1)
    return t
def tgc(c,ws):
    tot=sum(x for _,x in c['drops'])
    if not tot: return None
    # date et poids moyens de recolte, ponderes par les baisses de stock ; milieu du mois
    hd=dt.date.fromordinal(round(sum(dt.date(d.year,d.month,15).toordinal()*x for d,x in c['drops'])/tot))
    wg=sum(MW.get((d.year,d.month),0)*x for d,x in c['drops'] if (d.year,d.month) in MW)/sum(x for d,x in c['drops'] if (d.year,d.month) in MW)
    wl=wg/0.88; s0=dt.date(c['start'].year,c['start'].month,15)
    D=dd(s0,hd)
    return dict(tgc=((wl*1000)**(1/3)-(ws*1000)**(1/3))*1000/D, wl=wl, days=(hd-s0).days, dd=D, hd=hd)
for c in cycles:
    if good(c):
        t=tgc(c,0.5)
        if t: c.update(tgc=round(t['tgc'],2), tgc_lo=round(tgc(c,0.7)['tgc'],2), tgc_hi=round(tgc(c,0.3)['tgc'],2), hw=round(t['wl'],2), days=t['days'], dd=round(t['dd']), hd=t['hd'])
tg={}
for c_ in CO.values():
    for lab,a,b in (('prev',dt.date(2022,11,1),T0),('last',T0,last)):
        C=[c for c in cycles if c['co']==c_ and good(c) and c.get('tgc') and a<=c['end']<=b]
        tg[(c_,lab)]=dict(n=len(C), tgc=round(S.median(c['tgc'] for c in C),2), lo=round(S.median(c['tgc_lo'] for c in C),2), hi=round(S.median(c['tgc_hi'] for c in C),2), days=round(S.median(c['days'] for c in C)), dd=round(S.median(c['dd'] for c in C))) if C else None
ALL=[c for c in cycles if good(c) and c.get('tgc')]
by_y=collections.defaultdict(list)
for c in ALL: by_y[c['hd'].year].append(c['tgc'])
tg_year={y:(round(S.median(v),2),len(v)) for y,v in sorted(by_y.items())}
# ---- delousages deduits : le registre HFS ne contient que les medicaments (bain, aliment) ; les traitements sans medicament
# (eau douce, thermique, mecanique) n'y sont pas. On les lit dans les comptages : chute d'au moins 50 % entre deux comptages
# espaces de 24 jours au plus, en partant de 0,2 femelle adulte ou plus (regle recalee sur Gotuvik, cycle 2025-26 : 9 traitements
# connus pour le site, la regle en retrouve 8 sur les deux cotes ; l'ancienne, 60 % depuis 0,3, n'en voyait que 6). 'med' = un medicament est declare sur le site autour de la chute.
lice_by=collections.defaultdict(list)
for l in L: lice_by[l['site']].append((l['d'],l['v']))
KD=[]
for s_,v in lice_by.items():
    v.sort()
    for (a,x),(b,y) in zip(v,v[1:]):
        if x>=0.2 and y<=0.5*x and (b-a).days<=24:
            KD.append(dict(site=s_,co=co.get(s_),a=a,b=b,x=x,y=y,med=any(a-dt.timedelta(days=10)<=m['d0']<=b for m in M if m['site']==s_)))
# ---- fermiers
comp=[]
for c_ in CO.values():
    Tm=[m for m in M if m['co']==c_ and T0<=m['d0']]; st_=S.mean(x[c_] for x in stock[-24:])
    Lv=[l['v'] for l in L if l['co']==c_ and T0<=l['d']]
    a,na=tas(c_,T0,last); b,nb=tas(c_,dt.date(2022,11,1),T0)
    kd=[k for k in KD if k['co']==c_ and k['b']>=T0]
    comp.append(dict(co=c_, kd=len(kd), kd_nomed=sum(1 for k in kd if not k['med']), kd_m=round(len(kd)/st_/2,2), stock=stock[-1][c_], stock_ly=stock[-13][c_], sites=sum(1 for s in current if co[s]==c_), tas=a, tas_n=na, tas_prev=b, trt=len(Tm), bath=sum(m['bath'] for m in Tm), trt_m=round(len(Tm)/st_/2,2), lice=round(S.mean(Lv),2), lice_hi=round(100*sum(v>0.5 for v in Lv)/len(Lv)), tgc=tg[(c_,'last')], tgc_prev=tg[(c_,'prev')]))
TAS={c['co']:c['tas'] for c in comp}
# ---- sites + projection
fj=json.load(open(R+'data/faroe.json')); pos={x['code']:(x['lat'],x['lon']) for x in fj['sites']+fj['register_other']}
sites=[]; proj=collections.defaultdict(lambda: collections.defaultdict(float))
def addm(d,n):
    y,m=d.year,d.month-1+n; y+=m//12; m=m%12+1; return dt.date(y,m,calendar.monthrange(y,m)[1])
HSPAN=4   # la recolte d'un site s'etale sur les 4 derniers mois du cycle (mediane observee)
for s in sorted(ser):
    cur=current.get(s); lv=sorted([l for l in L if l['site']==s], key=lambda l:l['d']); ll=lv[-1] if lv else None
    row=dict(site=s,name=name[s],co=co[s],fish=ser[s].get(last,0),lat=pos.get(s,(None,None))[0],lon=pos.get(s,(None,None))[1],lice=ll['v'] if ll else None,lice_d=ll['d'].isoformat() if ll else None)
    if cur:
        T=TAS[cur['co']]; endm=addm(cur['start'],round(T)); harvesting=cur['now']<0.9*cur['peak'] and cur['months']>=9
        if endm<=last: endm=addm(last,2 if harvesting else 3)
        row.update(start=cur['start'].isoformat()[:7], months=cur['months'], known=cur['known'], peak=cur['peak'], end=endm.isoformat()[:7], hstart=addm(endm,-3).isoformat()[:7], state='harvesting' if harvesting else ('smolts' if cur['months']<=4 else 'growing'),
                   trt=sum(1 for m in M if m['site']==s and m['d0']>=cur['start']), kd=sum(1 for k in KD if k['site']==s and k['a']>=cur['start']), kd_nomed=sum(1 for k in KD if k['site']==s and k['a']>=cur['start'] and not k['med']))
    else: row.update(state='fallow', trt=0)
    sites.append(row)
def addm(d,n):
    y,m=d.year,d.month-1+n; y+=m//12; m=m%12+1; return dt.date(y,m,calendar.monthrange(y,m)[1])
# ---- mises a l'eau et baisses par mois
flows=[]
for i in range(1,len(dates)):
    d,p=dates[i],dates[i-1]; inc=collections.defaultdict(float); dec=0
    for s,S_ in ser.items():
        if d in S_ and p in S_:
            x=S_[d]-S_[p]
            if x>0: inc[co[s]]+=x
            else: dec-=x
    flows.append(dict(k=d.year*100+d.month, inc={c:round(v/1e6,2) for c,v in inc.items()}, dec=round(dec/1e6,2), harv=round(mw[(d.year,d.month)][1]/1e6,2) if (d.year,d.month) in mw else None))
# ---- poux hebdo, traitements mensuels
lw=collections.defaultdict(list)
for l in L: lw[l['d'].isocalendar()[:2]].append(l['v'])
lice=[{'w':wk, **{str(y): ({'m':round(S.mean(lw[(y,wk)]),2),'hi':round(100*sum(v>0.5 for v in lw[(y,wk)])/len(lw[(y,wk)])),'n':len(lw[(y,wk)])} if (y,wk) in lw else None) for y in (LY-2,LY-1,LY)}} for wk in range(1,53)]
med=[]
d=dt.date(last.year-2,last.month,1)
for i in range(1,25):
    e=addm(d,i); k=(e.year,e.month); T=[m for m in M if (m['d0'].year,m['d0'].month)==k]
    med.append(dict(k=e.year*100+e.month, kd=sum(1 for q in KD if (q['b'].year,q['b'].month)==k and not q['med']), bath=sum(m['bath'] for m in T), feed=sum(not m['bath'] for m in T), by={c:sum(1 for m in T if m['co']==c) for c in CO.values()}))
subst=collections.Counter(((m['substance'] or m['product']).lower().replace('emamektin','emamectin').replace('emamectinbenzoate','emamectin').split(' ')[0].replace('slice','emamectin'), m['co']) for m in M if m['d0']>=T0)
med_last=max(m['d0'] for m in M).isoformat()
cyc=[dict(site=c['site'],name=name[c['site']],co=c['co'],start=c['start'].isoformat()[:7],end=c['end'].isoformat()[:7],months=c['months'],peak=round(c['peak']/1e6,2),transfer=c['months']<=9,tgc=c.get('tgc'),hw=c.get('hw'),days=c.get('days'),dd=c.get('dd')) for c in sorted(cycles,key=lambda c:c['end']) if c['known'] and c['end']>=T0]

# ---- Bakkafrost : smolts -> recolte, rendement par smolt, verifications
def rd(f): return [r for r in csv.DictReader(l for l in open(R+'farming/donnees_fo/'+f, encoding='utf-8') if not l.startswith('#'))]
fl=lambda x: float(x) if x not in ('',None) else None
Q=rd('bakkafrost_trimestriel.csv'); B=rd('bakkafrost_mensuel.csv')
for r in Q: r['h']=fl(r['harvest_tgw']); r['w']=fl(r['harvest_kg']); r['sm']=fl(r['smolt_m']); r['sg']=fl(r['smolt_g'])
def corr(a,b):
    P_=[(x,y) for x,y in zip(a,b) if x is not None and y is not None]
    if len(P_)<6: return None
    a,b=zip(*P_); ma,mb=S.mean(a),S.mean(b); return [round(sum((x-ma)*(y-mb) for x,y in P_)/math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b)),2), len(P_)]
LAG=5
yl=[]
for i in range(LAG+3,len(Q)):
    h=sum(Q[j]['h'] for j in range(i-3,i+1)); s_=sum(Q[j-LAG]['sm'] for j in range(i-3,i+1)); g=[(Q[j-LAG]['sg'],Q[j-LAG]['sm']) for j in range(i-3,i+1) if Q[j-LAG]['sg']]
    yl.append(dict(q=Q[i]['quarter'], h=round(h), sm=round(s_,1), y=round(h/s_/1000,2), sg=round(sum(a*b for a,b in g)/sum(b for a,b in g)) if g else None))
def qadd(q,n):
    y,k=int(q[:4]),int(q[-1])-1+n; return f'{y+k//4}-Q{k%4+1}'
ylast=S.mean(x['y'] for x in yl[-4:]); ylo=min(x['y'] for x in yl[-4:]); yhi=max(x['y'] for x in yl[-4:])
fc=[]
for k in range(1,LAG):
    i=len(Q)-1+k; s_=sum(Q[j-LAG]['sm'] for j in range(i-3,i+1)); known=sum(Q[j]['h'] for j in range(i-3,len(Q)))
    fc.append(dict(q=qadd(Q[-1]['quarter'],k), sm=round(s_,1), lo=round(s_*ylo,1), mid=round(s_*ylast,1), hi=round(s_*yhi,1), known=round(known/1000,1), nq=k))
inc=collections.defaultdict(float)
for s,S_ in ser.items():
    if co[s]!='Bakkafrost': continue
    prev=None
    for d in dates:
        n=S_.get(d)
        if n is None: continue
        if prev is not None and n>prev: inc[f'{d.year}-Q{(d.month-1)//3+1}']+=n-prev
        prev=n
qtab=[dict(q=r['quarter'], h=r['h'], w=r['w'], sm=r['sm'], sg=r['sg'], conf=r['conf'], hfs=round(inc[r['quarter']]/1e6,2) if r['quarter'] in inc and r['quarter']>=f'{dates[1].year}-Q{(dates[1].month-1)//3+2}' else None) for r in Q]
mon=[]
for r in B:
    y,m=int(r['month'][:4]),int(r['month'][5:]); k=(y,m)
    if k in MW: mon.append(dict(k=y*100+m, bk=float(r['harvest_kt']), nat=round(mw[k][0]/1e6,1), bw=float(r['harvest_kg']), nw=round(MW[k],2)))
BW={(int(r['month'][:4]),int(r['month'][5:])):float(r['harvest_kg']) for r in B}; SG={r['quarter']:r['sg'] for r in Q}
cy=[]
for c in cycles:
    if c['co']!='Bakkafrost' or not good(c): continue
    sg=SG.get(f"{c['start'].year}-Q{(c['start'].month-1)//3+1}"); tot=sum(x for d,x in c['drops'])
    if not sg or not tot: continue
    hd=dt.date.fromordinal(round(sum(dt.date(d.year,d.month,15).toordinal()*x for d,x in c['drops'])/tot))
    ws=[(BW.get((d.year,d.month)) or MW.get((d.year,d.month)),x) for d,x in c['drops']]; ws=[(a,b) for a,b in ws if a]
    if not ws: continue
    wl=sum(a*b for a,b in ws)/sum(b for a,b in ws)/0.88; D_=dd(dt.date(c['start'].year,c['start'].month,15),hd)
    c['tgc_real']=round(((wl*1000)**(1/3)-sg**(1/3))*1000/D_,2); c['sg']=sg
    cy.append((hd.year,c['tgc_real'],sg,c['months']))
tgc_real=[dict(y=y, n=len([o for o in cy if o[0]==y]), tgc=round(S.median(o[1] for o in cy if o[0]==y),2), sg=round(S.mean(o[2] for o in cy if o[0]==y)), months=S.median(o[3] for o in cy if o[0]==y)) for y in sorted({o[0] for o in cy})]
BK=dict(quarters=qtab, yield_=yl, lag=LAG, forecast=fc, yield_recent=[round(ylo,2),round(ylast,2),round(yhi,2)], monthly=mon, tgc=tgc_real,
        corr=dict(vol=corr([sum(Q[j]['h'] for j in range(i-3,i+1)) for i in range(LAG+3,len(Q))],[sum(Q[j-LAG]['sm'] for j in range(i-3,i+1)) for i in range(LAG+3,len(Q))]),
                  weight=corr([r['w'] for r in Q[4:]],[Q[i-4]['sg'] for i in range(4,len(Q))]), months=corr([o[2] for o in cy],[o[3] for o in cy]), nat=corr([m['bw'] for m in mon],[m['nw'] for m in mon])))
out=dict(meta=dict(last_week=f'{LY}-W{LW:02d}', LY=LY, LW=LW, stock_date=last.isoformat(), lice_last=max(l['d'] for l in L).isoformat(), med_last=med_last),
         weekly=weekly, years=years, stock=stock[-37:], comp=comp, sites=sites, flows=flows[-24:], lice=lice, med=med, subst=[[k[0],k[1],v] for k,v in subst.most_common()], cycles=cyc,
         bk=BK, tgc=dict(year={str(y):v for y,v in tg_year.items()}, all=round(S.median(c['tgc'] for c in ALL),2), n=len(ALL)))
json.dump(out,open(R+'data/faroe_hfs.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
print(f"faroe_hfs.json : recolte jusqu'a {out['meta']['last_week']}, stock au {out['meta']['stock_date']}, {len(sites)} sites, {len(cyc)} cycles fermes sur 24 mois, rendement Bakkafrost {BK['yield_recent']} kg par smolt")
