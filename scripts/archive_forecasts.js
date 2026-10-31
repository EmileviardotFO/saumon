#!/usr/bin/env node
/*
 Archive des previsions : a chaque nouveau mois du Biomasseregisteret, enregistre ce que le tableau de bord
 prevoit A CE MOMENT-LA, pour pouvoir comparer plus tard prevision et realite (onglet Generations map).

   - par zone et par generation : poids moyen attendu dans 1, 2 et 3 mois (modele de croissance + temperature),
     la fourchette a 80 % des scenarios a 3 mois, et pour les generations de 4 kg+ le poids attendu des poissons ABATTUS (wh)
   - par zone : biomasse attendue dans 1, 2 et 3 mois (et la MTB de la zone)
   - Norvege : offre des 12 mois suivants (kt vides, chaque generation sortant au rythme des 4 dernieres annees)
   - Norvege : part de 6 kg+, 5-6 kg et 4-5 kg attendue 2 mois plus tard dans les ventes du panel Akvafakta
     ET dans tous les poissons abattus en Norvege (registre),
     et projection du reservoir correspondant sur 6 mois

 Le code des modeles n'est pas recopie : il est lu dans docs/production.html (memes fonctions que la page).

 Les mois deja archives ne sont jamais reecrits ('live' = enregistre au moment ou le mois est sorti).
 Au premier passage, les mois passes depuis 2021 sont reconstitues ('reconstructed') en ne donnant aux
 modeles que les donnees anterieures a chaque mois - mais avec les chiffres tels qu'ils sont aujourd'hui
 (revisions comprises), d'ou l'etiquette distincte.

 Usage : node scripts/archive_forecasts.js
*/
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '..');
const DATA = path.join(ROOT, 'data', 'data.json'), OUT = path.join(ROOT, 'data', 'forecast_archive.json');
const PAGE = fs.readFileSync(path.join(ROOT, 'docs', 'production.html'), 'utf8');
const RECON_FROM = 202101;

function block(start, end) {
  const i = PAGE.indexOf(start), j = PAGE.indexOf(end, i);
  if (i < 0 || j < 0) throw new Error(`bloc introuvable dans production.html : ${start.slice(0, 50)}`);
  return PAGE.slice(i, j);
}
// noyau des pics (computePeaks) et modele de croissance de l'onglet Generations map
const PEAKS = new Function(block('// ===== Reservoir de gros poissons et pics de 6+', '\nfunction peaksSvg') + '\nreturn { computePeaks, PK_6P, pkSh };')();
const GM = new Function('data', block('const GUT = 0.888, MON_GM', '// ---------------------------------------------------------------- indicateurs par zone') +
  '\nG = prepare(data);\nreturn { G, project, simulate, harvFore, harvForeMix, supplyProj, fitAt, sh, GUT };');

const sh = PEAKS.pkSh;
const raw = JSON.parse(fs.readFileSync(DATA, 'utf8'));
const M = GM(raw);
const months = M.G.months, last = months[months.length - 1];
const arch = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, 'utf8')) : { meta: {}, entries: [] };
const have = new Set(arch.entries.map(e => e.k));

// donnees telles qu'on les avait au moment ou le registre du mois k est sorti (~20 du mois suivant)
function asOf(k) {
  const lim = sh(k, 1), cut = Date.UTC(Math.floor(lim / 100), lim % 100 - 1, 20);
  const thu = (y, w) => { const j4 = Date.UTC(y, 0, 4), d = new Date(j4).getUTCDay(); return j4 - ((d + 6) % 7) * 864e5 + (Math.min(w, 53) - 1) * 7 * 864e5 + 3 * 864e5; };
  return Object.assign({}, raw, {
    records: raw.records.filter(r => r.year * 100 + r.month <= k),
    cohort: raw.cohort.filter(c => c.year * 100 + c.month <= k),
    weekly: raw.weekly.filter(r => r.dist_week && thu(r.report_year - (r.dist_week >= 50 && r.report_week <= 2 ? 1 : 0), r.dist_week) + 4 * 864e5 <= cut),
    ssb_weekly: null,
  });
}
function entry(k, kind) {
  const e = { k, made: new Date().toISOString().slice(0, 10), kind, zones: {}, biomass: {}, peaks: {} };
  const COH = M.G.COH, REC = M.G.REC;
  for (let po = 1; po <= 13; po++) {
    const z = {}, gens = Object.entries(COH[po] || {}).filter(([, s]) => s[k] && s[k].stock > 1e5 && s[k].weight_kg);
    gens.forEach(([g, s]) => { const p = M.project(po, s[k].weight_kg, k, 3); if (!p) return; const q = M.simulate(po, s[k].weight_kg, k, 3, (s[k].harv_stk || 0) > 0.01 * s[k].stock);
      const HM = M.harvForeMix(po, +g, k), hv = HM ? HM.v : null;
      z[g] = { w0: +s[k].weight_kg.toFixed(3), n0: Math.round(s[k].stock), w: p.map(v => +v.toFixed(3)), q3: q && q[2] ? [+q[2].p10.toFixed(3), +q[2].p90.toFixed(3)] : null,
        wh: hv ? hv.map(v => +v.toFixed(3)) : null }; });
    e.zones[po] = z;
    // biomasse : celle de la zone x evolution de la biomasse norvegienne sur les memes mois l'an dernier (comme dans la page)
    const R = REC[po] || {}, now = R[k];
    if (now) {
      const natB = kk => Object.values(REC).reduce((t, Rp) => t + (Rp[kk] ? Rp[kk].biomasse_kg : 0), 0);
      const b = [1, 2, 3].map(h => { const n0 = natB(sh(k, -12)), n1 = natB(sh(k, h - 12)); return n0 && n1 ? +(now.biomasse_kg / 1e6 * n1 / n0).toFixed(2) : null; });
      e.biomass[po] = { b0: +(now.biomasse_kg / 1e6).toFixed(2), b, mtb: ((raw.bw_register || {}).mtb_po_all || (raw.bw_register || {}).mtb_po || {})[String(po)] / 1000 || null };
    }
  }
  // offre norvegienne des 12 mois suivants (kt vides) : [mois, prevu, bas, haut]
  const SPj = M.supplyProj(k); if (SPj) e.supply = SPj.p.map(x => [x.k, +x.v.toFixed(1), +x.lo.toFixed(1), +x.hi.toFixed(1)]);
  const D = kind === 'live' ? raw : asOf(k);
  [['6+', PEAKS.PK_6P], ['5-6', ['5-6']], ['4-5', ['4-5']]].forEach(([lab, sel]) => {
    try { const P = PEAKS.computePeaks(D, sel); if (!P) return;
      e.peaks[lab] = { lastB: P.now.lastB, reservoir: +P.now.cur.toFixed(2), fc2: P.fc2 ? { k: P.fc2.k, v: +P.fc2.v.toFixed(2), usual: +P.fc2.usual.toFixed(2) } : null,
        fcN: P.fcN ? { k: P.fcN.k, v: +P.fcN.v.toFixed(2), usual: +P.fcN.usual.toFixed(2) } : null,
        proj: P.proj.map(p => ({ k: p.k, v: p.v === null ? null : +p.v.toFixed(2), lo: p.lo === undefined ? null : +p.lo.toFixed(2), hi: p.hi === undefined ? null : +p.hi.toFixed(2) })) };
    } catch (err) { e.peaks[lab] = { error: String(err).slice(0, 200) }; } });
  return e;
}
let added = 0;
if (!have.has(last)) { arch.entries.push(entry(last, 'live')); added++; console.log(`  ${last} : previsions enregistrees (live)`); }
else console.log(`  ${last} : deja archive`);
const t0 = Date.now();
months.filter(k => k >= RECON_FROM && k < last && !have.has(k)).forEach(k => { arch.entries.push(entry(k, 'reconstructed')); added++; });
if (added > 1) console.log(`  ${added - 1} mois passes reconstitues (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
arch.entries.sort((a, b) => a.k - b.k);
arch.meta = { updated: new Date().toISOString().slice(0, 10), last, n: arch.entries.length,
  note: "live = saved when the month came out; reconstructed = rebuilt later with only the data before that month (current figures, revisions included)",
  weights: 'live kg (multiply by 0.888 for gutted); w = fish left in the sea, wh = fish harvested' };
fs.writeFileSync(OUT, JSON.stringify(arch));
console.log(`  archive : ${arch.entries.length} mois, ${(fs.statSync(OUT).size / 1024).toFixed(0)} ko`);
