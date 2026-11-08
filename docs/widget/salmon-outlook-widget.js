// Salmon Outlook — widget d'écran d'accueil pour Scriptable (iPhone / iPad)
//
// Installation : dans Scriptable, "+" puis coller ce script, le nommer "Salmon Outlook".
// Sur l'écran d'accueil : appui long > Modifier > "+" > Scriptable, choisir la taille,
// puis appui long sur le widget > Modifier le widget > Script : "Salmon Outlook".
//
// Choisir ce qui s'affiche : champ "Paramètre" du widget (appui long > Modifier le widget).
// Plusieurs blocs séparés par "+" ; filtre de bassin après ":" ; exemples :
//   news                  dernières actualités, tous bassins (par défaut)
//   news:NO,CL            dernières actualités Norvège et Chili
//   news:FEED             aliments et matières premières
//   top                   "This week in five" (les sujets à plus fort impact de la semaine)
//   chile                 estimation de la récolte chilienne (wellboats)
//   top+news:CL           les deux, l'un sous l'autre
//   news titles           titres seuls (plus de sujets) ; par defaut chaque titre a son resume (moyen et grand format)
// Codes de bassin : NO CL GB FO IS CA AU IE NZ US global FEED
//
// Sujets suivis (data/watch.json, ex. florfenicol en Tasmanie) : toujours affiches en tete, quelle que soit l'actualite de la semaine.
// Un appui sur une ligne ouvre Scriptable avec une liste depliante (menu deroulant) : statut, chronologie datee et sources,
// resume et articles de chaque sujet ; un appui ailleurs ouvre le dashboard.

const BASE = 'https://emileviardotfo.github.io/saumon/';
const DASH = BASE + 'docs/production.html';
const C = { bg: new Color('#0b1620'), card: new Color('#102231'), ink: new Color('#e7eef2'), muted: new Color('#8fa4b0'),
            accent: new Color('#4fc3f7'), up: new Color('#81c784'), down: new Color('#ffb74d') };
const BASIN = { NO: 'Norway', CL: 'Chile', GB: 'Scotland', FO: 'Faroes', IS: 'Iceland', CA: 'Canada', AU: 'Australia',
                IE: 'Ireland', NZ: 'New Zealand', US: 'USA', global: 'Global', FEED: 'Feed' };
const ACCESS = { free: 0, '?': 1, metered: 2, pay: 3 };

async function getJSON(name) {
  const fm = FileManager.local(), path = fm.joinPath(fm.cacheDirectory(), 'so-' + name);
  try {
    const r = new Request(BASE + 'data/' + name); r.timeoutInterval = 20;
    const j = await r.loadJSON(); fm.writeString(path, JSON.stringify(j)); return j;
  } catch (e) {   // hors ligne : derniere version gardee en cache
    return fm.fileExists(path) ? JSON.parse(fm.readString(path)) : null;
  }
}

function parse(param) {
  const p = (param || 'news').trim() || 'news';
  return p.split('+').map(x => { const [k, f] = x.trim().split(':'); return { k: k.toLowerCase(), f: f ? f.split(',').map(s => s.trim()) : null }; });
}

function day(d) {   // "4 Nov"
  if (!d) return '';
  const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return (+d.slice(8, 10)) + ' ' + m[+d.slice(5, 7) - 1];
}

function bestLink(s) {
  const a = (s.arts || []).slice().sort((x, y) => (ACCESS[x.access] ?? 1) - (ACCESS[y.access] ?? 1) || (x.date < y.date ? 1 : -1))[0];
  return a ? a.url : DASH;
}

function header(w, txt, sub) {
  const h = w.addStack(); h.centerAlignContent();
  const t = h.addText(txt.toUpperCase()); t.font = Font.boldSystemFont(11); t.textColor = C.accent;
  h.addSpacer();
  if (sub) { const s = h.addText(sub); s.font = Font.systemFont(10); s.textColor = C.muted; }
  w.addSpacer(4);
}

const RUN = 'scriptable:///run/' + encodeURIComponent(Script.name());
const openUrl = what => RUN + '?open=' + encodeURIComponent(what);

function activeWatch(W) {
  const today = new Date().toISOString().slice(0, 10);
  return ((W || {}).topics || []).filter(t => !t.until || t.until >= today);
}

function watchRow(w, t, small) {
  const row = w.addStack(); row.layoutVertically(); row.url = openUrl('watch:' + t.id);
  row.backgroundColor = C.card; row.cornerRadius = 10; row.setPadding(6, 8, 6, 8);
  const last = (t.timeline || []).slice().sort((a, b) => (a.d < b.d ? 1 : -1))[0] || {};
  const m = row.addText('WATCH · ' + t.label + (last.d ? ' · ' + day(last.d.length > 7 ? last.d : last.d + '-01') : ''));
  m.font = Font.boldSystemFont(9.5); m.textColor = C.down; m.lineLimit = 1;
  const st = row.addText(t.status || ''); st.font = Font.semiboldSystemFont(small ? 11.5 : 12.5); st.textColor = C.ink; st.lineLimit = small ? 4 : 2;
  w.addSpacer(small ? 4 : 7);
}

function storyRow(w, s, small, sum, i) {
  const row = w.addStack(); row.layoutVertically(); row.url = i === undefined ? bestLink(s) : openUrl('story:' + i);
  const meta = row.addText(`${BASIN[s.basin] || s.basin}${s.who && s.who !== 'Sector' ? ' · ' + s.who : ''} · ${day(s.last)}`);
  meta.font = Font.mediumSystemFont(9.5); meta.textColor = C.muted; meta.lineLimit = 1;
  const t = row.addText(s.title || ''); t.font = Font.semiboldSystemFont(small ? 12 : 13); t.textColor = C.ink; t.lineLimit = small ? 3 : 2;
  if (sum && s.summary) {   // resume ecrit pour la page (titres et descriptions des editeurs, jamais de texte payant)
    row.addSpacer(2);
    const d = row.addText(s.summary); d.font = Font.systemFont(11.5); d.textColor = new Color('#b8c7d1'); d.lineLimit = sum;
  }
  w.addSpacer(small ? 4 : (sum ? 9 : 6));
}

async function build() {
  const fam = config.widgetFamily || 'large';
  const room = { small: 3, medium: 4, large: 9, extraLarge: 11 }[fam] || 9, small = fam === 'small';
  const raw = (args.widgetParameter || '').trim(), titles = /\btitles?\b/i.test(raw);
  const blocks = parse(raw.replace(/\btitles?\b|\bnowatch\b/ig, '').trim());
  const sum = small || titles ? 0 : (fam === 'medium' ? 3 : 2);   // lignes de resume par sujet
  const cost = sum ? 2 : 1;
  const w = new ListWidget(); w.backgroundColor = C.bg; w.url = DASH; w.setPadding(12, 14, 12, 14);
  w.refreshAfterDate = new Date(Date.now() + 60 * 60 * 1000);   // iOS rafraichit au plus a peu pres toutes les heures
  let left = room;
  const ST = blocks.some(b => b.k === 'news' || b.k === 'top') ? await getJSON('stories.json') : null;
  // sujets suivis : toujours en tete (obligatoire), une ligne chacun
  const WT = activeWatch(await getJSON('watch.json'));
  if (WT.length && !/\bnowatch\b/i.test(raw)) { WT.forEach(t => watchRow(w, t, small)); left -= WT.length * (small ? 2 : 1.5); }
  for (const b of blocks) {
    if (left <= 0) break;
    if ((b.k === 'news' || b.k === 'top') && ST) {
      let S = ST.stories || [];
      if (b.f) S = S.filter(s => b.f.includes(s.basin));
      if (b.k === 'top') {
        S = (ST.top || []).map(t => (ST.stories || [])[t.i]).filter(Boolean);
        header(w, 'This week in five', '');
      } else {
        S = S.slice().sort((x, y) => (x.last < y.last ? 1 : x.last > y.last ? -1 : 0) || (+x.priority || 9) - (+y.priority || 9));
        header(w, b.f ? b.f.map(f => BASIN[f] || f).join(' · ') : 'Latest salmon news', small ? '' : 'to ' + day((ST.meta || {}).news_generated));
      }
      const fit = Math.max(1, Math.floor((left - 1) / cost));
      const n = Math.min(fit, b.k === 'top' ? 5 : fit, S.length);
      S.slice(0, n).forEach(s => storyRow(w, s, small, sum, (ST.stories || []).indexOf(s)));
      if (!n) { const t = w.addText('Nothing this week.'); t.font = Font.systemFont(12); t.textColor = C.muted; }
      left -= Math.max(1, n) * cost + 1;
    } else if (b.k === 'chile') {
      const J = await getJSON('chile_wellboats.json');
      header(w, 'Chile · wellboat watch', '');
      if (!J) continue;
      const E = J.ll_estimate || {}, O = J.ll_official || {}, k = Object.keys(E).sort().pop();
      if (k) {
        const ly = (+k.slice(0, 4) - 1) + k.slice(4), d = O[ly] ? Math.round(100 * (E[k] / O[ly] - 1)) : null;
        const t = w.addText(`${day(k + '-01').split(' ')[1]} ${k.slice(0, 4)}: ≈ ${Math.round(E[k] / 1000)} kt`); t.font = Font.boldSystemFont(small ? 18 : 20); t.textColor = C.ink;
        if (d !== null) { const s = w.addText(`${d > 0 ? '+' : ''}${d} % vs a year earlier · Los Lagos plants`); s.font = Font.systemFont(11); s.textColor = d >= 0 ? C.up : C.down; }
      }
      w.addSpacer(6); left -= 1;
    }
  }
  w.addSpacer();
  const f = w.addText('Salmon Outlook · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })); f.font = Font.systemFont(9); f.textColor = C.muted;
  return w;
}

// ---------- dans l'application : liste depliante (appui sur une ligne du widget) ----------
async function detail(open) {
  const [ST, W] = [await getJSON('stories.json'), await getJSON('watch.json')];
  const WT = activeWatch(W), S = (ST && ST.stories) || [];
  const shut = {}; let want = open || '';
  const t = new UITable(); t.showSeparators = true;
  const txt = (s, size, col, bold) => { const r = new UITableRow(); const c = r.addText(s); c.titleFont = bold ? Font.boldSystemFont(size) : Font.systemFont(size); c.titleColor = col; c.widthWeight = 100; r.dynamicHeight = true; return r; };
  const match = tp => S.filter(s => tp.kw.some(k => JSON.stringify([s.title, s.summary, s.event]).toLowerCase().includes(k)));
  function draw() {
    t.removeAllRows();
    const h = txt('Pinned topics', 13, C.accent, true); h.isHeader = true; t.addRow(h);
    WT.forEach(tp => {
      const key = 'watch:' + tp.id, on = want === key;
      const r = txt((on ? '▾ ' : '▸ ') + tp.label + '\n' + (tp.status || ''), 14, Color.dynamic(Color.black(), Color.white()), true);
      r.onSelect = () => { want = on ? '' : key; draw(); }; t.addRow(r);
      if (!on) return;
      tp.timeline.slice().sort((a, b) => (a.d < b.d ? 1 : -1)).forEach(e => {
        const x = txt((e.d.length > 7 ? day(e.d) + ' ' + e.d.slice(0, 4) : e.d) + ' — ' + e.t + (e.u ? '  ↗' : ''), 12.5, Color.gray());
        if (e.u) x.onSelect = () => Safari.open(e.u); t.addRow(x);
      });
      match(tp).forEach(s => { const x = txt('In this week\'s news: ' + s.title + '  ↗', 12.5, C.accent); x.onSelect = () => Safari.open(bestLink(s)); t.addRow(x); });
    });
    const h2 = txt('This week\'s news' + (ST && ST.meta ? ' · to ' + day(ST.meta.news_generated) : ''), 13, C.accent, true); h2.isHeader = true; t.addRow(h2);
    S.map((s, i) => [s, i]).sort((a, b) => (a[0].last < b[0].last ? 1 : a[0].last > b[0].last ? -1 : 0)).forEach(([s, i]) => {
      const key = 'story:' + i, on = want === key;
      const r = txt((on ? '▾ ' : '▸ ') + (BASIN[s.basin] || s.basin) + ' · ' + day(s.last) + '\n' + s.title, 13.5, Color.dynamic(Color.black(), Color.white()), true);
      r.onSelect = () => { want = on ? '' : key; draw(); }; t.addRow(r);
      if (!on) return;
      if (s.summary) t.addRow(txt(s.summary, 12.5, Color.gray()));
      (s.arts || []).forEach(a => { const x = txt((a.src || a.source || 'Article') + (a.access && a.access !== 'free' ? ' (' + a.access + ')' : '') + ' — ' + (a.title || a.url) + '  ↗', 12, C.accent); x.onSelect = () => Safari.open(a.url); t.addRow(x); });
      const d = txt('Open the dashboard  ↗', 12, C.muted); d.onSelect = () => Safari.open(DASH); t.addRow(d);
    });
    t.reload();
  }
  draw();
  await t.present(true);
}

if (config.runsInWidget) Script.setWidget(await build());
else if (args.queryParameters && args.queryParameters.open) await detail(args.queryParameters.open);
else await detail('');
Script.complete();
